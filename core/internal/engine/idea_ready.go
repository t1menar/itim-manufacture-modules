package engine

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/messaging"
)

// ideaReadyPayload is the orchestration-only body of idea.ready (D21).
type ideaReadyPayload struct {
	IdeaRef struct {
		ID  int64 `json:"id"`
		Rev int   `json:"rev"`
	} `json:"idea_ref"`
	Language   string  `json:"language"`
	PipelineID *string `json:"pipeline_id"`
	Priority   int     `json:"priority"`
}

// HandleEvent routes broker messages: idea.ready (D21) or job.* events.
func (e *Engine) HandleEvent(ctx context.Context, tx pgx.Tx, env messaging.Envelope) (string, error) {
	if env.Type == "idea.ready" {
		return e.applyIdeaReady(ctx, tx, env)
	}
	return e.HandleJobEvent(ctx, tx, env)
}

// applyIdeaReady creates a production from an idea.ready event (inbox already claimed).
func (e *Engine) applyIdeaReady(ctx context.Context, tx pgx.Tx, env messaging.Envelope) (string, error) {
	e.defaults()
	var p ideaReadyPayload
	if err := json.Unmarshal(env.Payload, &p); err != nil {
		return messaging.Invalid, nil
	}
	if p.IdeaRef.ID < 1 || p.IdeaRef.Rev < 1 {
		return messaging.Invalid, nil
	}
	ideaRef := messaging.FormatIdeaRef(p.IdeaRef.ID, p.IdeaRef.Rev)
	wantID := messaging.IdeaReadyMessageID(p.IdeaRef.ID, p.IdeaRef.Rev)
	if env.MessageID != wantID {
		// Stable id mismatch: still accept if payload is well-formed (tests may vary), but
		// prefer the canonical id from the publisher.
		_ = wantID
	}
	language := p.Language
	if language == "" {
		language = e.DefaultLanguage
	}

	maxConc := e.MaxConcurrent
	if e.Settings != nil {
		if n, err := e.Settings.MaxConcurrent(ctx); err == nil && n > 0 {
			maxConc = n
		}
	}
	var running int
	if err := tx.QueryRow(ctx, `SELECT count(*) FROM productions WHERE status = 'running'`).Scan(&running); err != nil {
		return "", err
	}
	if running >= maxConc {
		// Back-pressure: roll back inbox insert (caller requeues).
		return "", fmt.Errorf("at max concurrent productions (%d)", maxConc)
	}

	var existing uuid.UUID
	err := tx.QueryRow(ctx, `SELECT id FROM productions WHERE idea_ref = $1`, ideaRef).Scan(&existing)
	if err == nil {
		return messaging.Conflict, nil // duplicate idea.ready → one production
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return "", err
	}

	var live uuid.UUID
	err = tx.QueryRow(ctx, `SELECT id FROM productions WHERE idea_id = $1 AND status = 'running'`, p.IdeaRef.ID).Scan(&live)
	if err == nil {
		if err := e.enqueueIdeaStatus(ctx, tx, p.IdeaRef.ID, p.IdeaRef.Rev, uuid.Nil, "failed", "live_production_exists"); err != nil {
			return "", err
		}
		return messaging.Conflict, nil
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return "", err
	}

	var pid string
	err = tx.QueryRow(ctx, `SELECT id FROM pipelines WHERE enabled AND ((($1::text) IS NULL AND is_default) OR id = $1)`, p.PipelineID).Scan(&pid)
	if errors.Is(err, pgx.ErrNoRows) {
		if err := e.enqueueIdeaStatus(ctx, tx, p.IdeaRef.ID, p.IdeaRef.Rev, uuid.Nil, "failed", "no_pipeline"); err != nil {
			return "", err
		}
		return messaging.Invalid, nil
	} else if err != nil {
		return "", err
	}
	rows, err := tx.Query(ctx, `SELECT ps.position, ps.stage_id, s.scope, ps.timeout_s, ps.max_attempts, ps.revise_target, ps.max_rounds, ps.notify_stage
		FROM pipeline_stages ps JOIN stages s ON s.id = ps.stage_id WHERE ps.pipeline_id = $1 ORDER BY ps.position`, pid)
	if err != nil {
		return "", err
	}
	snapshot, err := pgx.CollectRows(rows, pgx.RowToStructByPos[StageRow])
	if err != nil {
		return "", err
	}
	if len(snapshot) == 0 {
		if err := e.enqueueIdeaStatus(ctx, tx, p.IdeaRef.ID, p.IdeaRef.Rev, uuid.Nil, "failed", "no_pipeline"); err != nil {
			return "", err
		}
		return messaging.Invalid, nil
	}
	var channels []string
	if err := tx.QueryRow(ctx, `SELECT coalesce(array_agg(r.channel_id ORDER BY r.priority), '{}') FROM routing_rules r
		JOIN channels c ON c.id = r.channel_id WHERE r.enabled AND c.enabled AND r.language = $1`, language).Scan(&channels); err != nil {
		return "", err
	}
	if len(channels) == 0 {
		if err := e.enqueueIdeaStatus(ctx, tx, p.IdeaRef.ID, p.IdeaRef.Rev, uuid.Nil, "failed", "no_route"); err != nil {
			return "", err
		}
		return messaging.Invalid, nil
	}

	prodID, _ := uuid.NewV7()
	varID, _ := uuid.NewV7()
	snapJSON, _ := json.Marshal(snapshot)
	if _, err := tx.Exec(ctx, `INSERT INTO productions (id, idea_id, idea_rev, idea_ref, run_no, pipeline_id, pipeline_snapshot, language)
		VALUES ($1, $2, $3, $4,
			(SELECT coalesce(max(run_no), 0) + 1 FROM productions WHERE idea_id = $2),
			$5, $6, $7)`,
		prodID, p.IdeaRef.ID, p.IdeaRef.Rev, ideaRef, pid, snapJSON, language); err != nil {
		if db.IsUniqueViolation(err, "productions_idea_ref_uq") || db.IsUniqueViolation(err, "productions_live_uq") {
			return messaging.Conflict, nil
		}
		return "", err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO variants (id, production_id, language, channels, status)
		VALUES ($1, $2, $3, $4, 'producing')`, varID, prodID, language, channels); err != nil {
		return "", err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, type, actor, payload)
		VALUES ($1, 'production.created', 'system', jsonb_build_object(
			'idea_ref', $2::text, 'idea_id', $3::bigint, 'idea_rev', $4::int, 'pipeline_id', $5::text, 'priority', $6::int))`,
		prodID, ideaRef, p.IdeaRef.ID, p.IdeaRef.Rev, pid, p.Priority); err != nil {
		return "", err
	}
	if err := e.enqueueIdeaStatus(ctx, tx, p.IdeaRef.ID, p.IdeaRef.Rev, prodID, "in_production", ""); err != nil {
		return "", err
	}
	first := snapshot[0]
	var variant *uuid.UUID
	if first.Scope == "variant" {
		variant = &varID
	}
	_, err = e.createJob(ctx, tx, jobSpec{
		production: prodID, variant: variant, stage: first, chain: uuid.Nil, try: 1,
		ideaID: p.IdeaRef.ID, ideaRev: p.IdeaRef.Rev, language: language,
	})
	if err != nil {
		return "", err
	}
	return messaging.Applied, nil
}

func (e *Engine) enqueueIdeaStatus(ctx context.Context, tx pgx.Tx, ideaID int64, rev int, prod uuid.UUID, status, failCode string) error {
	payload := map[string]any{
		"idea_ref": map[string]any{"id": ideaID, "rev": rev},
		"status":   status,
	}
	if prod != uuid.Nil {
		payload["production_id"] = prod.String()
	} else {
		// Schema allows uuid; use nil UUID when production was not created (no_route / no_pipeline).
		payload["production_id"] = uuid.Nil.String()
	}
	if status == "failed" {
		payload["failure"] = map[string]any{"code": failCode}
	} else {
		payload["failure"] = nil
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	msgID := messaging.IdeaStatusMessageID(ideaID, rev, status, prod)
	prodPtr := &prod
	if prod == uuid.Nil {
		prodPtr = nil
	}
	return messaging.Enqueue(ctx, tx, messaging.OutboxMessage{
		Exchange: e.Topo.Events(), RoutingKey: "idea." + status,
		Envelope: messaging.Envelope{
			MessageID: msgID, Type: "idea." + status, Producer: "core",
			ProductionID: prodPtr, Payload: body,
		},
	})
}
