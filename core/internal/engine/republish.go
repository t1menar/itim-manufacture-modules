package engine

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/messaging"
)

// CreateRepublishJob creates one publish-stage job and enqueues a single job.requested
// outbox row for a newly created generation > 1 intent. Must run in the same transaction
// that inserted the intent. The variant must have no other live job (jobs_variant_live_uq).
func (e *Engine) CreateRepublishJob(ctx context.Context, tx pgx.Tx, variantID, intentID, revisionID uuid.UUID, generation int) (uuid.UUID, error) {
	e.defaults()
	var production uuid.UUID
	var language string
	var ideaID int64
	var ideaRev int
	var snapshotJSON []byte
	if err := tx.QueryRow(ctx, `SELECT v.production_id, v.language, p.idea_id, p.idea_rev, p.pipeline_snapshot
		FROM variants v
		JOIN productions p ON p.id = v.production_id
		WHERE v.id = $1 FOR UPDATE OF v`, variantID).
		Scan(&production, &language, &ideaID, &ideaRev, &snapshotJSON); err != nil {
		return uuid.Nil, err
	}
	var snapshot []StageRow
	if err := json.Unmarshal(snapshotJSON, &snapshot); err != nil {
		return uuid.Nil, err
	}
	var stage *StageRow
	for i := range snapshot {
		if snapshot[i].StageID == "publish" {
			stage = &snapshot[i]
			break
		}
	}
	if stage == nil {
		return uuid.Nil, fmt.Errorf("pipeline has no publish stage")
	}
	if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'publishing', attention = NULL, rev = rev + 1 WHERE id = $1`, variantID); err != nil {
		return uuid.Nil, err
	}

	jobID := uuid.Must(uuid.NewV7())
	var moduleID *string
	err := tx.QueryRow(ctx, `SELECT id FROM modules WHERE stage_id = 'publish' AND active AND enabled AND health = 'up'`).Scan(&moduleID)
	if err != nil && err != pgx.ErrNoRows {
		return uuid.Nil, err
	}
	var attempt int
	if err := tx.QueryRow(ctx, `INSERT INTO jobs (id, production_id, variant_id, stage_id, module_id, position, attempt, chain_id, try, max_attempts, timeout_s, mode, round)
		VALUES ($1, $2, $3, 'publish', $4, $5,
			(SELECT coalesce(max(attempt), 0) + 1 FROM jobs WHERE production_id = $2 AND stage_id = 'publish'),
			$1, 1, $6, $7, 'republish', 0)
		RETURNING attempt`, jobID, production, variantID, moduleID, stage.Position, stage.MaxAttempts, stage.TimeoutS).Scan(&attempt); err != nil {
		return uuid.Nil, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload)
		VALUES ($1, $2, $3, 'job.queued', 'system', jsonb_build_object('stage', 'publish', 'mode', 'republish', 'intent_id', $4::text))`,
		production, variantID, jobID, intentID); err != nil {
		return uuid.Nil, err
	}
	if moduleID == nil {
		e.Log.Warn("no active publish module; republish job stays queued", "job_id", jobID, "intent_id", intentID)
		return jobID, nil
	}
	req := map[string]any{
		"job_id": jobID, "attempt": attempt, "try": 1, "fence": 1, "production_id": production,
		"stage": "publish", "mode": "republish", "round": 0,
		"variant": map[string]any{"id": variantID.String(), "language": language},
		"input": map[string]any{
			"idea_ref": map[string]any{"id": ideaID, "rev": ideaRev},
			"channels": []any{}, "upstream": map[string]any{},
			"intents": []map[string]any{{
				"intent_id": intentID.String(), "content_revision_id": revisionID.String(), "generation": generation,
			}},
		},
		"settings":    map[string]any{"version": 1, "values": map[string]any{}},
		"credentials": []string{},
		"callback":    map[string]any{"base_url": fmt.Sprintf("%s/internal/v1/jobs/%s", e.CallbackBaseURL, jobID)},
		"deadline":    time.Now().UTC().Add(time.Duration(stage.TimeoutS) * time.Second).Format(time.RFC3339),
	}
	payload, err := json.Marshal(req)
	if err != nil {
		return uuid.Nil, err
	}
	if _, err := tx.Exec(ctx, `UPDATE jobs SET request = $2 WHERE id = $1`, jobID, payload); err != nil {
		return uuid.Nil, err
	}
	prod := production
	return jobID, messaging.Enqueue(ctx, tx, messaging.OutboxMessage{
		Exchange: e.Topo.Commands(), RoutingKey: "job.publish." + *moduleID,
		Envelope: messaging.Envelope{Type: "job.requested", Producer: "core", ProductionID: &prod,
			Job: &messaging.JobRef{JobID: jobID, Fence: 1}, Payload: payload},
	})
}
