package engine

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/messaging"
)

type liveJob struct {
	id, production uuid.UUID
	variant        *uuid.UUID
	stageID        string
	moduleID       *string
	position       int
	chain          uuid.UUID
	try, maxTries  int
	fence          int
	status         string
	snapshot       []StageRow
	ideaID         int64
	ideaText       string
	language       string
}

var liveStatuses = map[string]bool{"queued": true, "dispatching": true, "dispatched": true, "running": true}

// HandleJobEvent is the consumer handler for core.job-events. It runs inside the inbox
// transaction, so the inbox row, the job transition and any follow-up outbox rows commit together.
func (e *Engine) HandleJobEvent(ctx context.Context, tx pgx.Tx, env messaging.Envelope) (string, error) {
	e.defaults()
	if env.Job == nil {
		return messaging.Invalid, nil
	}
	var j liveJob
	var snap []byte
	err := tx.QueryRow(ctx, `SELECT j.id, j.production_id, j.variant_id, j.stage_id, j.module_id, j.position, j.chain_id, j.try, j.max_attempts,
			j.fence, j.status, p.pipeline_snapshot, i.id, i.text, p.language
		FROM jobs j JOIN productions p ON p.id = j.production_id JOIN ideas i ON i.id = p.idea_id
		WHERE j.id = $1 FOR UPDATE OF j`, env.Job.JobID).
		Scan(&j.id, &j.production, &j.variant, &j.stageID, &j.moduleID, &j.position, &j.chain, &j.try, &j.maxTries,
			&j.fence, &j.status, &snap, &j.ideaID, &j.ideaText, &j.language)
	if errors.Is(err, pgx.ErrNoRows) {
		return messaging.Invalid, nil
	} else if err != nil {
		return "", err
	}
	if err := json.Unmarshal(snap, &j.snapshot); err != nil {
		return "", err
	}
	if j.moduleID == nil || env.Producer != "module:"+*j.moduleID {
		return messaging.Conflict, e.event(ctx, tx, j, "job.foreign_event", map[string]any{"producer": env.Producer})
	}
	if env.Job.Fence != j.fence || !liveStatuses[j.status] {
		return messaging.Stale, e.event(ctx, tx, j, "job.stale_event", map[string]any{"fence": env.Job.Fence, "current_fence": j.fence, "status": j.status, "type": env.Type})
	}
	switch env.Type {
	case "job.progress":
		_, err := tx.Exec(ctx, `UPDATE jobs SET status = 'running', progress = $2, rev = rev + 1, updated_at = now() WHERE id = $1`, j.id, []byte(env.Payload))
		return messaging.Applied, err
	case "job.succeeded":
		var res struct {
			Output json.RawMessage `json:"output"`
		}
		if err := json.Unmarshal(env.Payload, &res); err != nil || len(res.Output) == 0 || res.Output[0] != '{' {
			return messaging.Invalid, nil
		}
		if _, err := tx.Exec(ctx, `UPDATE jobs SET status = 'succeeded', output = $2, finished_at = now(), rev = rev + 1, updated_at = now() WHERE id = $1`, j.id, []byte(res.Output)); err != nil {
			return "", err
		}
		if err := e.event(ctx, tx, j, "job.succeeded", nil); err != nil {
			return "", err
		}
		return messaging.Applied, e.advance(ctx, tx, j)
	case "job.failed":
		var f struct {
			Class   string `json:"class"`
			Message string `json:"message"`
		}
		if err := json.Unmarshal(env.Payload, &f); err != nil || (f.Class != "transient" && f.Class != "fatal" && f.Class != "blocked") {
			return messaging.Invalid, nil
		}
		if _, err := tx.Exec(ctx, `UPDATE jobs SET status = 'failed', error = $2, finished_at = now(), rev = rev + 1, updated_at = now() WHERE id = $1`, j.id, []byte(env.Payload)); err != nil {
			return "", err
		}
		if err := e.event(ctx, tx, j, "job.failed", map[string]any{"class": f.Class}); err != nil {
			return "", err
		}
		return messaging.Applied, e.onFailure(ctx, tx, j, f.Class)
	}
	return messaging.Invalid, nil
}

func (e *Engine) event(ctx context.Context, tx pgx.Tx, j liveJob, typ string, payload map[string]any) error {
	if payload == nil {
		payload = map[string]any{}
	}
	payload["stage"] = j.stageID
	b, _ := json.Marshal(payload)
	_, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload) VALUES ($1, $2, $3, $4, 'system', $5)`,
		j.production, j.variant, j.id, typ, b)
	return err
}

func (j liveJob) spec(stage StageRow, variant *uuid.UUID) jobSpec {
	return jobSpec{production: j.production, variant: variant, stage: stage, chain: uuid.Nil, try: 1, ideaID: j.ideaID, ideaText: j.ideaText, language: j.language}
}

func (e *Engine) scopeVariants(ctx context.Context, tx pgx.Tx, j liveJob) ([]uuid.UUID, error) {
	if j.variant != nil {
		return []uuid.UUID{*j.variant}, nil
	}
	rows, err := tx.Query(ctx, `SELECT id FROM variants WHERE production_id = $1 AND status NOT IN ('skipped','failed','cancelled','published') ORDER BY id FOR UPDATE`, j.production)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
}

// advance moves the scope to the next snapshot position, or finishes it.
func (e *Engine) advance(ctx context.Context, tx pgx.Tx, j liveJob) error {
	vars, err := e.scopeVariants(ctx, tx, j)
	if err != nil {
		return err
	}
	if j.position >= len(j.snapshot) {
		if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'published', rev = rev + 1 WHERE id = ANY($1)`, vars); err != nil {
			return err
		}
		return e.completeProduction(ctx, tx, j.production)
	}
	next := j.snapshot[j.position] // positions are 1-based and contiguous
	status := "producing"
	if next.ReviseTarget != nil {
		status = "in_review"
	} else if next.Position == len(j.snapshot) {
		status = "publishing"
	}
	if _, err := tx.Exec(ctx, `UPDATE variants SET position = $2, status = $3, rev = rev + 1 WHERE id = ANY($1)`, vars, next.Position, status); err != nil {
		return err
	}
	if next.Scope == "production" {
		_, err := e.createJob(ctx, tx, j.spec(next, nil))
		return err
	}
	for _, v := range vars {
		v := v
		if _, err := e.createJob(ctx, tx, j.spec(next, &v)); err != nil {
			return err
		}
	}
	return nil
}

func (e *Engine) onFailure(ctx context.Context, tx pgx.Tx, j liveJob, class string) error {
	if class == "transient" && j.try < j.maxTries {
		stage := j.snapshot[j.position-1]
		s := j.spec(stage, j.variant)
		s.chain, s.try = j.chain, j.try+1
		_, err := e.createJob(ctx, tx, s)
		return err
	}
	vars, err := e.scopeVariants(ctx, tx, j)
	if err != nil {
		return err
	}
	if class == "fatal" {
		if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'failed', rev = rev + 1 WHERE id = ANY($1)`, vars); err != nil {
			return err
		}
		return e.completeProduction(ctx, tx, j.production)
	}
	reason := "blocked"
	if class == "transient" {
		reason = "retries_exhausted"
	}
	attention, _ := json.Marshal(map[string]any{"reason": reason, "job_id": j.id})
	_, err = tx.Exec(ctx, `UPDATE variants SET status = 'needs_attention', attention = $2, rev = rev + 1 WHERE id = ANY($1)`, vars, attention)
	return err
}

// completeProduction applies core-05 §4.5.
func (e *Engine) completeProduction(ctx context.Context, tx pgx.Tx, prod uuid.UUID) error {
	var total, done, terminal, failed int
	if err := tx.QueryRow(ctx, `SELECT count(*),
			count(*) FILTER (WHERE status IN ('published','skipped')),
			count(*) FILTER (WHERE status IN ('published','skipped','failed','cancelled')),
			count(*) FILTER (WHERE status = 'failed')
		FROM variants WHERE production_id = $1`, prod).Scan(&total, &done, &terminal, &failed); err != nil {
		return err
	}
	var status string
	switch {
	case done == total:
		status = "done"
	case terminal == total && failed > 0:
		status = "failed"
	default:
		return nil
	}
	var ideaID int64
	if err := tx.QueryRow(ctx, `UPDATE productions SET status = $2, finished_at = now(), rev = rev + 1 WHERE id = $1 AND status = 'running' RETURNING idea_id`, prod, status).Scan(&ideaID); err != nil {
		return fmt.Errorf("finish production: %w", err)
	}
	_, err := tx.Exec(ctx, `UPDATE ideas SET status = $2, rev = rev + 1, updated_at = now() WHERE id = $1`, ideaID, status)
	return err
}

// RetryVariant is the admin retry of a variant in needs_attention: it locks the variant, checks
// its status and creates a new chain at the current position in one transaction, so two
// concurrent retries cannot both succeed (the variant-level live-job index backs this up).
func (e *Engine) RetryVariant(ctx context.Context, tx pgx.Tx, variantID uuid.UUID) (uuid.UUID, error) {
	e.defaults()
	var j liveJob
	var snap []byte
	var status string
	err := tx.QueryRow(ctx, `SELECT v.production_id, v.position, v.status, v.language, p.pipeline_snapshot, i.id, i.text
		FROM variants v JOIN productions p ON p.id = v.production_id JOIN ideas i ON i.id = p.idea_id
		WHERE v.id = $1 FOR UPDATE OF v`, variantID).Scan(&j.production, &j.position, &status, &j.language, &snap, &j.ideaID, &j.ideaText)
	if err != nil {
		return uuid.Nil, err
	}
	if status != "needs_attention" {
		return uuid.Nil, ErrInvalidState
	}
	if err := json.Unmarshal(snap, &j.snapshot); err != nil {
		return uuid.Nil, err
	}
	stage := j.snapshot[j.position-1]
	var variant *uuid.UUID
	if stage.Scope == "variant" {
		variant = &variantID
	}
	if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'producing', attention = NULL, rev = rev + 1 WHERE id = $1`, variantID); err != nil {
		return uuid.Nil, err
	}
	return e.createJob(ctx, tx, j.spec(stage, variant))
}

// ErrInvalidState maps to 409 invalid_state.
var ErrInvalidState = errors.New("invalid_state")
