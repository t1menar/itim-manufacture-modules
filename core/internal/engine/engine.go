// Package engine holds the scheduler and the job state transitions of core-05, limited to this
// slice: production creation, job creation with outbox command, job events with fencing,
// retries and advancing through the pipeline snapshot. Review loop, cancel, timeouts and
// notifications follow in later slices.
package engine

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/messaging"
	"github.com/t1menar/manufacture/core/internal/publish"
)

type Engine struct {
	once            sync.Once // guards defaults; the value is shared by goroutines
	Pool            *pgxpool.Pool
	Topo            messaging.Topology
	Log             *slog.Logger
	MaxConcurrent   int // overridden by settings.scheduler.max_concurrent_productions when Settings is set
	DefaultLanguage string
	CallbackBaseURL string
	Publish         *publish.Store // optional; video success → revision (D19); review approve → intents
	Settings        SettingsSource // optional; nil keeps struct defaults
	reviewMaxRounds int
}

// SettingsSource reads versioned core settings without importing the settings package (avoids cycles).
type SettingsSource interface {
	ReviewMaxRounds(ctx context.Context) (int, error)
	MaxConcurrent(ctx context.Context) (int, error)
	CallbackBaseURL(ctx context.Context) (string, error)
}

func (e *Engine) defaults() { e.once.Do(e.setDefaults) }

func (e *Engine) setDefaults() {
	if e.Log == nil {
		e.Log = slog.Default()
	}
	if e.MaxConcurrent == 0 {
		e.MaxConcurrent = 2
	}
	if e.DefaultLanguage == "" {
		e.DefaultLanguage = "en"
	}
	if e.CallbackBaseURL == "" {
		e.CallbackBaseURL = "http://core:8080"
	}
	if e.reviewMaxRounds == 0 {
		e.reviewMaxRounds = 3
	}
}

// StageRow is one entry of productions.pipeline_snapshot.
type StageRow struct {
	Position     int     `json:"position"`
	StageID      string  `json:"stage_id"`
	Scope        string  `json:"scope"`
	TimeoutS     int     `json:"timeout_s"`
	MaxAttempts  int     `json:"max_attempts"`
	ReviseTarget *string `json:"revise_target"`
	MaxRounds    *int    `json:"max_rounds,omitempty"`
	NotifyStage  *string `json:"notify_stage,omitempty"`
}

// Idea intake is event-driven (D21): module-video publishes idea.ready; see applyIdeaReady.
// The former Tick/startIdea path that read core.ideas has been removed.

type jobSpec struct {
	production uuid.UUID
	variant    *uuid.UUID
	stage      StageRow
	chain      uuid.UUID // uuid.Nil = new chain
	try        int
	mode       string
	round      int
	ideaID     int64
	ideaRev    int
	language   string
}

// createJob inserts a queued job and, when the stage has an active module, its job.requested
// command in the outbox, in the caller's transaction.
func (e *Engine) createJob(ctx context.Context, tx pgx.Tx, s jobSpec) (uuid.UUID, error) {
	jobID, _ := uuid.NewV7()
	chain := s.chain
	if chain == uuid.Nil {
		chain = jobID
	}
	var moduleID *string
	err := tx.QueryRow(ctx, `SELECT id FROM modules WHERE stage_id = $1 AND active AND enabled AND health = 'up'`, s.stage.StageID).Scan(&moduleID)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return uuid.Nil, err
	}
	mode := s.mode
	if mode == "" {
		mode = "create"
	}
	var attempt int
	if err := tx.QueryRow(ctx, `INSERT INTO jobs (id, production_id, variant_id, stage_id, module_id, position, attempt, chain_id, try, max_attempts, timeout_s, mode, round)
		VALUES ($1, $2, $3, $4, $5, $6, (SELECT coalesce(max(attempt), 0) + 1 FROM jobs WHERE production_id = $2 AND stage_id = $4), $7, $8, $9, $10, $11, $12)
		RETURNING attempt`, jobID, s.production, s.variant, s.stage.StageID, moduleID, s.stage.Position, chain, s.try, s.stage.MaxAttempts, s.stage.TimeoutS, mode, s.round).Scan(&attempt); err != nil {
		return uuid.Nil, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload) VALUES ($1, $2, $3, 'job.queued', 'system', jsonb_build_object('stage', $4::text, 'try', $5::int))`,
		s.production, s.variant, jobID, s.stage.StageID, s.try); err != nil {
		return uuid.Nil, err
	}
	if moduleID == nil {
		e.Log.Warn("no active module for stage; job stays queued", "stage", s.stage.StageID, "job_id", jobID)
		return jobID, nil
	}
	return jobID, e.enqueueRequest(ctx, tx, jobID, 1, *moduleID, s, attempt)
}

func (e *Engine) enqueueRequest(ctx context.Context, tx pgx.Tx, jobID uuid.UUID, fence int, moduleID string, s jobSpec, attempt int) error {
	var variant any
	if s.variant != nil {
		variant = map[string]any{"id": s.variant.String(), "language": s.language}
	}
	channels, err := loadJobChannels(ctx, tx, s)
	if err != nil {
		return err
	}
	settings, err := loadModuleSettings(ctx, tx, moduleID)
	if err != nil {
		return err
	}
	upstream, err := variantUpstream(ctx, tx, s.variant)
	if err != nil {
		return err
	}
	req := map[string]any{
		"job_id": jobID, "attempt": attempt, "try": s.try, "fence": fence, "production_id": s.production,
		"stage": s.stage.StageID, "mode": modeOrCreate(s.mode), "round": s.round, "variant": variant,
		"input": map[string]any{
			"idea_ref": map[string]any{"id": s.ideaID, "rev": s.ideaRev},
			"channels": channels, "upstream": upstream,
		},
		"settings":    settings,
		"credentials": []string{},
		"callback":    map[string]any{"base_url": fmt.Sprintf("%s/internal/v1/jobs/%s", e.CallbackBaseURL, jobID)},
		"deadline":    time.Now().UTC().Add(time.Duration(s.stage.TimeoutS) * time.Second).Format(time.RFC3339),
	}
	payload, err := json.Marshal(req)
	if err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `UPDATE jobs SET request = $2 WHERE id = $1`, jobID, payload); err != nil {
		return err
	}
	prod := s.production
	return messaging.Enqueue(ctx, tx, messaging.OutboxMessage{
		Exchange: e.Topo.Commands(), RoutingKey: "job." + s.stage.StageID + "." + moduleID,
		Envelope: messaging.Envelope{Type: "job.requested", Producer: "core", ProductionID: &prod,
			Job: &messaging.JobRef{JobID: jobID, Fence: fence}, Payload: payload},
	})
}

// loadModuleSettings returns the settings snapshot of the module for the job request: the current
// module_settings version and its values (version 1 and empty values when the module has none saved).
func loadModuleSettings(ctx context.Context, tx pgx.Tx, moduleID string) (map[string]any, error) {
	var version int
	var values []byte
	err := tx.QueryRow(ctx, `SELECT version, values FROM module_settings WHERE module_id = $1 AND is_current`, moduleID).Scan(&version, &values)
	if errors.Is(err, pgx.ErrNoRows) {
		return map[string]any{"version": 1, "values": map[string]any{}}, nil
	}
	if err != nil {
		return nil, err
	}
	return map[string]any{"version": version, "values": json.RawMessage(values)}, nil
}

// loadJobChannels builds the job-request channels array from the variant (or the
// production's variants when the stage is production-scoped). Module-video requires
// at least one channel object with id/language/name/settings (D21 job input).
func loadJobChannels(ctx context.Context, tx pgx.Tx, s jobSpec) ([]any, error) {
	var ids []string
	if s.variant != nil {
		if err := tx.QueryRow(ctx, `SELECT channels FROM variants WHERE id = $1`, *s.variant).Scan(&ids); err != nil {
			return nil, err
		}
	} else {
		if err := tx.QueryRow(ctx, `SELECT coalesce((SELECT channels FROM variants WHERE production_id = $1 ORDER BY id LIMIT 1), '{}')`, s.production).Scan(&ids); err != nil {
			return nil, err
		}
	}
	out := make([]any, 0, len(ids))
	for _, id := range ids {
		var name, language string
		if err := tx.QueryRow(ctx, `SELECT name, language FROM channels WHERE id = $1`, id).Scan(&name, &language); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				language = s.language
				if language == "" {
					language = "en"
				}
				name = id
			} else {
				return nil, err
			}
		}
		out = append(out, map[string]any{
			"id": id, "language": language, "name": name, "settings": map[string]any{},
		})
	}
	return out, nil
}

// Takeover assigns a live job to another executor (activation switch or explicit admin
// re-issue). It is the only place the fence grows; plain re-sends keep job_id, fence and
// message_id. Events still carrying the old fence are rejected as stale.
func (e *Engine) Takeover(ctx context.Context, jobID uuid.UUID, moduleID string) (int, error) {
	e.defaults()
	var fence int
	err := db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		var s jobSpec
		var stageID string
		var position int
		if err := tx.QueryRow(ctx, `SELECT j.production_id, j.variant_id, j.stage_id, j.position, j.chain_id, j.try, p.idea_id, p.idea_rev, p.language
			FROM jobs j JOIN productions p ON p.id = j.production_id
			WHERE j.id = $1 AND j.status IN ('queued','dispatching','dispatched','running') FOR UPDATE OF j`, jobID).
			Scan(&s.production, &s.variant, &stageID, &position, &s.chain, &s.try, &s.ideaID, &s.ideaRev, &s.language); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return errors.New("job is not live")
			}
			return err
		}
		var attempt int
		if err := tx.QueryRow(ctx, `UPDATE jobs SET fence = fence + 1, module_id = $2, status = 'queued', rev = rev + 1, updated_at = now()
			WHERE id = $1 RETURNING fence, attempt`, jobID, moduleID).Scan(&fence, &attempt); err != nil {
			return err
		}
		if err := tx.QueryRow(ctx, `SELECT ps.timeout_s, ps.max_attempts FROM productions p, jsonb_to_recordset(p.pipeline_snapshot) AS ps(position int, timeout_s int, max_attempts int)
			WHERE p.id = $1 AND ps.position = $2`, s.production, position).Scan(&s.stage.TimeoutS, &s.stage.MaxAttempts); err != nil {
			return err
		}
		s.stage.StageID, s.stage.Position = stageID, position
		if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, job_id, type, actor, payload) VALUES ($1, $2, 'job.taken_over', 'system', jsonb_build_object('module', $3::text, 'fence', $4::int))`,
			s.production, jobID, moduleID, fence); err != nil {
			return err
		}
		return e.enqueueRequest(ctx, tx, jobID, fence, moduleID, s, attempt)
	})
	return fence, err
}

// DispatchOrphans hands queued jobs that were created while their stage had no active module (so they
// carry no module and no request) to the module that is active and up now.
func (e *Engine) DispatchOrphans(ctx context.Context, limit int) (int, error) {
	rows, err := e.Pool.Query(ctx, `SELECT j.id, m.id FROM jobs j
		JOIN modules m ON m.stage_id = j.stage_id AND m.active AND m.enabled AND m.health = 'up'
		WHERE j.status = 'queued' AND j.module_id IS NULL
		ORDER BY j.created_at LIMIT $1`, limit)
	if err != nil {
		return 0, err
	}
	type pair struct {
		job    uuid.UUID
		module string
	}
	var todo []pair
	for rows.Next() {
		var p pair
		if err := rows.Scan(&p.job, &p.module); err != nil {
			rows.Close()
			return 0, err
		}
		todo = append(todo, p)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	n := 0
	for _, p := range todo {
		if _, err := e.Takeover(ctx, p.job, p.module); err != nil {
			e.Log.Warn("dispatch orphan job failed", "job_id", p.job, "module", p.module, "err", err)
			continue
		}
		n++
	}
	return n, nil
}

func modeOrCreate(m string) string {
	if m == "" {
		return "create"
	}
	return m
}

// variantUpstream gives a variant-scoped job (review, revise) the latest content revision of its
// variant, in the same shape as the publish job: upstream.content_revision (opaque blob, D22) and
// upstream.content_revision_id. A job without a variant, or a variant without a revision yet,
// gets an empty object.
func variantUpstream(ctx context.Context, tx pgx.Tx, variant *uuid.UUID) (map[string]any, error) {
	upstream := map[string]any{}
	if variant == nil {
		return upstream, nil
	}
	var id uuid.UUID
	var body json.RawMessage
	err := tx.QueryRow(ctx, `SELECT id, body FROM content_revisions WHERE variant_id = $1 ORDER BY revision DESC LIMIT 1`, *variant).
		Scan(&id, &body)
	if errors.Is(err, pgx.ErrNoRows) {
		return upstream, nil
	}
	if err != nil {
		return nil, err
	}
	upstream["content_revision"] = body
	upstream["content_revision_id"] = id.String()
	return upstream, nil
}
