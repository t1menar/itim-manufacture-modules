package engine

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/messaging"
	"github.com/t1menar/manufacture/core/internal/publish"
)

// afterReviewApproved creates generation-1 publish intents for the variant's accounts
// (idempotent) and enqueues one publish job.requested with those intent ids (core-05).
func (e *Engine) afterReviewApproved(ctx context.Context, tx pgx.Tx, j jobRow, round int, reviewOutput json.RawMessage) error {
	if e.Publish == nil {
		return fmt.Errorf("publish store not configured")
	}
	if round == 0 {
		round = j.round
		if round == 0 {
			round = 1
		}
	}
	revID, err := e.resolveRevisionForApprove(ctx, tx, *j.variant, j, reviewOutput)
	if err != nil {
		return err
	}
	intents, err := e.Publish.ApproveAndCreateIntentsInTx(ctx, tx, revID, round)
	if err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload)
		VALUES ($1, $2, $3, 'review.approved', 'system', jsonb_build_object(
			'content_revision_id', $4::text, 'round', $5::int, 'intent_count', $6::int))`,
		j.production, *j.variant, j.id, revID, round, len(intents)); err != nil {
		return err
	}
	if len(intents) == 0 {
		attention, _ := json.Marshal(map[string]any{"reason": "no_channel", "content_revision_id": revID.String()})
		_, err := tx.Exec(ctx, `UPDATE variants SET status = 'needs_attention', attention = $2, rev = rev + 1 WHERE id = $1`, *j.variant, attention)
		return err
	}
	_, err = e.CreateFirstPublishJob(ctx, tx, *j.variant, revID, intents)
	return err
}

func (e *Engine) resolveRevisionForApprove(ctx context.Context, tx pgx.Tx, variantID uuid.UUID, j jobRow, reviewOutput json.RawMessage) (uuid.UUID, error) {
	var hinted struct {
		ContentRevisionID *uuid.UUID `json:"content_revision_id"`
	}
	_ = json.Unmarshal(reviewOutput, &hinted)
	if hinted.ContentRevisionID != nil {
		var latest uuid.UUID
		err := tx.QueryRow(ctx, `SELECT id FROM content_revisions WHERE variant_id = $1 ORDER BY revision DESC LIMIT 1`, variantID).Scan(&latest)
		if err != nil {
			return uuid.Nil, fmt.Errorf("content_revision_id given but no revisions: %w", err)
		}
		if *hinted.ContentRevisionID != latest {
			return uuid.Nil, fmt.Errorf("%w: content_revision_id is not the latest revision", ErrOutputInvalid)
		}
		return latest, nil
	}
	var id uuid.UUID
	err := tx.QueryRow(ctx, `SELECT id FROM content_revisions WHERE variant_id = $1 ORDER BY revision DESC LIMIT 1`, variantID).Scan(&id)
	if err == nil {
		return id, nil
	}
	if err != pgx.ErrNoRows {
		return uuid.Nil, err
	}
	// Bridge until video success always snapshots a revision (PR #8 / D19): take last video output.
	var jobID uuid.UUID
	var output []byte
	err = tx.QueryRow(ctx, `SELECT id, output FROM jobs
		WHERE variant_id = $1 AND stage_id IN ('video') AND status = 'succeeded' AND output IS NOT NULL
		ORDER BY finished_at DESC NULLS LAST, updated_at DESC LIMIT 1`, variantID).Scan(&jobID, &output)
	if err == pgx.ErrNoRows {
		// Production-scope video: variant_id NULL on the job.
		err = tx.QueryRow(ctx, `SELECT id, output FROM jobs
			WHERE production_id = $1 AND stage_id = 'video' AND status = 'succeeded' AND output IS NOT NULL
			ORDER BY finished_at DESC NULLS LAST, updated_at DESC LIMIT 1`, j.production).Scan(&jobID, &output)
	}
	if err != nil {
		return uuid.Nil, fmt.Errorf("no content revision and no video output to snapshot: %w", err)
	}
	body, err := revisionBodyFromVideoOutput(variantID, jobID, output)
	if err != nil {
		return uuid.Nil, err
	}
	rev, err := e.Publish.CreateRevisionInTx(ctx, tx, variantID, jobID, body)
	if err != nil {
		return uuid.Nil, err
	}
	return rev.ID, nil
}

func revisionBodyFromVideoOutput(variantID, jobID uuid.UUID, output json.RawMessage) (json.RawMessage, error) {
	var parsed struct {
		Variants   []json.RawMessage `json:"variants"`
		Provenance json.RawMessage   `json:"provenance"`
		Changes    *string           `json:"changes"`
	}
	if err := json.Unmarshal(output, &parsed); err != nil || len(parsed.Variants) == 0 {
		return nil, ErrOutputInvalid
	}
	raw := parsed.Variants[0]
	var v map[string]any
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil, err
	}
	bodyMap := map[string]any{
		"variant_id": variantID.String(),
		"job_id":     jobID.String(),
		"language":   v["language"],
		"video":      v["video"],
		"metadata":   v["metadata"],
	}
	if len(parsed.Provenance) > 0 {
		bodyMap["provenance"] = json.RawMessage(parsed.Provenance)
	}
	if parsed.Changes != nil {
		bodyMap["changes"] = *parsed.Changes
	}
	for _, key := range []string{"contact_sheet", "cover", "preview", "script_ref", "post", "checks"} {
		if val, ok := v[key]; ok {
			bodyMap[key] = val
		}
	}
	return json.Marshal(bodyMap)
}

// CreateFirstPublishJob enqueues the first publish job for generation-1 intents after review approve.
func (e *Engine) CreateFirstPublishJob(ctx context.Context, tx pgx.Tx, variantID, revisionID uuid.UUID, intents []publish.Intent) (uuid.UUID, error) {
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
	if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'publishing', position = $2, attention = NULL, rev = rev + 1 WHERE id = $1`,
		variantID, stage.Position); err != nil {
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
			$1, 1, $6, $7, 'create', 0)
		RETURNING attempt`, jobID, production, variantID, moduleID, stage.Position, stage.MaxAttempts, stage.TimeoutS).Scan(&attempt); err != nil {
		return uuid.Nil, err
	}
	if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload)
		VALUES ($1, $2, $3, 'job.queued', 'system', jsonb_build_object('stage', 'publish', 'mode', 'create'))`,
		production, variantID, jobID); err != nil {
		return uuid.Nil, err
	}
	intentRows := make([]map[string]any, 0, len(intents))
	for _, in := range intents {
		intentRows = append(intentRows, map[string]any{
			"intent_id": in.ID.String(), "content_revision_id": revisionID.String(), "generation": in.Generation,
			"platform_account_id": in.PlatformAccountID.String(),
		})
	}
	var revBody json.RawMessage
	_ = tx.QueryRow(ctx, `SELECT body FROM content_revisions WHERE id = $1`, revisionID).Scan(&revBody)
	upstream := map[string]any{}
	if len(revBody) > 0 {
		upstream["content_revision"] = json.RawMessage(revBody)
		upstream["content_revision_id"] = revisionID.String()
	}
	if moduleID == nil {
		e.Log.Warn("no active publish module; publish job stays queued", "job_id", jobID)
		return jobID, nil
	}
	channels, err := loadJobChannels(ctx, tx, jobSpec{production: production, variant: &variantID, language: language})
	if err != nil {
		return uuid.Nil, err
	}
	req := map[string]any{
		"job_id": jobID, "attempt": attempt, "try": 1, "fence": 1, "production_id": production,
		"stage": "publish", "mode": "create", "round": 0,
		"variant": map[string]any{"id": variantID.String(), "language": language},
		"input": map[string]any{
			"idea_ref": map[string]any{"id": ideaID, "rev": ideaRev},
			"channels": channels, "upstream": upstream, "intents": intentRows,
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
