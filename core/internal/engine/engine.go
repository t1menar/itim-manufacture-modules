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
)

type Engine struct {
	once            sync.Once // guards defaults; the value is shared by goroutines
	Pool            *pgxpool.Pool
	Topo            messaging.Topology
	Log             *slog.Logger
	MaxConcurrent   int // overridden by settings.scheduler.max_concurrent_productions when Settings is set
	DefaultLanguage string
	CallbackBaseURL string
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
}

// Tick turns queued ideas into productions (core-05 §2-§3). Ticks are serialized by an
// advisory transaction lock; the unique indexes on productions make a duplicate impossible
// even if that lock were bypassed.
func (e *Engine) Tick(ctx context.Context) (int, error) {
	e.defaults()
	maxConc := e.MaxConcurrent
	if e.Settings != nil {
		if n, err := e.Settings.MaxConcurrent(ctx); err == nil && n > 0 {
			maxConc = n
		}
	}
	created := 0
	err := db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		created = 0
		if _, err := tx.Exec(ctx, `SELECT pg_advisory_xact_lock(hashtext('core.scheduler'))`); err != nil {
			return err
		}
		var running int
		if err := tx.QueryRow(ctx, `SELECT count(*) FROM productions WHERE status = 'running'`).Scan(&running); err != nil {
			return err
		}
		slots := maxConc - running
		if slots <= 0 {
			return nil
		}
		rows, err := tx.Query(ctx, `SELECT id FROM ideas WHERE status = 'queued'
			ORDER BY priority DESC, queued_at, id LIMIT $1 FOR UPDATE SKIP LOCKED`, slots)
		if err != nil {
			return err
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[int64])
		if err != nil {
			return err
		}
		for _, id := range ids {
			ok, err := e.startIdea(ctx, tx, id)
			if err != nil {
				return fmt.Errorf("idea %d: %w", id, err)
			}
			if ok {
				created++
			}
		}
		return nil
	})
	return created, err
}

func failIdea(ctx context.Context, tx pgx.Tx, id int64, code string) error {
	_, err := tx.Exec(ctx, `UPDATE ideas SET status = 'failed', failure = jsonb_build_object('code', $2::text),
		rev = rev + 1, updated_at = now() WHERE id = $1`, id, code)
	if err == nil {
		_, err = tx.Exec(ctx, `INSERT INTO events (type, actor, payload) VALUES ('idea.failed', 'system', jsonb_build_object('idea_id', $1::bigint, 'code', $2::text))`, id, code)
	}
	return err
}

func (e *Engine) startIdea(ctx context.Context, tx pgx.Tx, ideaID int64) (bool, error) {
	var text string
	var lang, pipelineID *string
	if err := tx.QueryRow(ctx, `SELECT text, language, pipeline_id FROM ideas WHERE id = $1`, ideaID).Scan(&text, &lang, &pipelineID); err != nil {
		return false, err
	}
	var pid string
	err := tx.QueryRow(ctx, `SELECT id FROM pipelines WHERE enabled AND ((($1::text) IS NULL AND is_default) OR id = $1)`, pipelineID).Scan(&pid)
	if errors.Is(err, pgx.ErrNoRows) {
		return false, failIdea(ctx, tx, ideaID, "no_pipeline")
	} else if err != nil {
		return false, err
	}
	var snapshot []StageRow
	rows, err := tx.Query(ctx, `SELECT ps.position, ps.stage_id, s.scope, ps.timeout_s, ps.max_attempts, ps.revise_target, ps.max_rounds
		FROM pipeline_stages ps JOIN stages s ON s.id = ps.stage_id WHERE ps.pipeline_id = $1 ORDER BY ps.position`, pid)
	if err != nil {
		return false, err
	}
	snapshot, err = pgx.CollectRows(rows, pgx.RowToStructByPos[StageRow])
	if err != nil {
		return false, err
	}
	if len(snapshot) == 0 {
		return false, failIdea(ctx, tx, ideaID, "no_pipeline")
	}
	language := e.DefaultLanguage
	if lang != nil {
		language = *lang
	}
	var channels []string
	if err := tx.QueryRow(ctx, `SELECT coalesce(array_agg(r.channel_id ORDER BY r.priority), '{}') FROM routing_rules r
		JOIN channels c ON c.id = r.channel_id WHERE r.enabled AND c.enabled AND r.language = $1`, language).Scan(&channels); err != nil {
		return false, err
	}
	if len(channels) == 0 {
		return false, failIdea(ctx, tx, ideaID, "no_route")
	}
	prodID, _ := uuid.NewV7()
	varID, _ := uuid.NewV7()
	snapJSON, _ := json.Marshal(snapshot)
	if _, err := tx.Exec(ctx, `INSERT INTO productions (id, idea_id, run_no, pipeline_id, pipeline_snapshot, language)
		VALUES ($1, $2, (SELECT coalesce(max(run_no), 0) + 1 FROM productions WHERE idea_id = $2), $3, $4, $5)`,
		prodID, ideaID, pid, snapJSON, language); err != nil {
		return false, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO variants (id, production_id, language, channels, status) VALUES ($1, $2, $3, $4, 'producing')`,
		varID, prodID, language, channels); err != nil {
		return false, err
	}
	tag, err := tx.Exec(ctx, `UPDATE ideas SET status = 'in_production', rev = rev + 1, updated_at = now() WHERE id = $1 AND status = 'queued'`, ideaID)
	if err != nil {
		return false, err
	}
	if tag.RowsAffected() != 1 {
		return false, errors.New("idea left the queued state concurrently")
	}
	if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, type, actor, payload) VALUES ($1, 'production.created', 'system', jsonb_build_object('idea_id', $2::bigint, 'pipeline_id', $3::text))`, prodID, ideaID, pid); err != nil {
		return false, err
	}
	first := snapshot[0]
	var variant *uuid.UUID
	if first.Scope == "variant" {
		variant = &varID
	}
	_, err = e.createJob(ctx, tx, jobSpec{production: prodID, variant: variant, stage: first, chain: uuid.Nil, try: 1, ideaID: ideaID, ideaText: text, language: language})
	return err == nil, err
}

type jobSpec struct {
	production uuid.UUID
	variant    *uuid.UUID
	stage      StageRow
	chain      uuid.UUID // uuid.Nil = new chain
	try        int
	mode       string
	round      int
	ideaID     int64
	ideaText   string
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
	err := tx.QueryRow(ctx, `SELECT id FROM modules WHERE stage_id = $1 AND active AND enabled`, s.stage.StageID).Scan(&moduleID)
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
	req := map[string]any{
		"job_id": jobID, "attempt": attempt, "try": s.try, "fence": fence, "production_id": s.production,
		"stage": s.stage.StageID, "mode": modeOrCreate(s.mode), "round": s.round, "variant": variant,
		"input": map[string]any{
			"idea":     map[string]any{"id": s.ideaID, "text": s.ideaText, "language": s.language},
			"channels": []any{}, "upstream": map[string]any{},
		},
		"settings":    map[string]any{"version": 1, "values": map[string]any{}},
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
		if err := tx.QueryRow(ctx, `SELECT j.production_id, j.variant_id, j.stage_id, j.position, j.chain_id, j.try, i.id, i.text, p.language
			FROM jobs j JOIN productions p ON p.id = j.production_id JOIN ideas i ON i.id = p.idea_id
			WHERE j.id = $1 AND j.status IN ('queued','dispatching','dispatched','running') FOR UPDATE OF j`, jobID).
			Scan(&s.production, &s.variant, &stageID, &position, &s.chain, &s.try, &s.ideaID, &s.ideaText, &s.language); err != nil {
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

func modeOrCreate(m string) string {
	if m == "" {
		return "create"
	}
	return m
}
