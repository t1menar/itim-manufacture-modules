package engine

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// publicationItem is one entry of stage-publish-output.publications.
type publicationItem struct {
	Platform          string          `json:"platform"`
	PlatformAccountID uuid.UUID       `json:"platform_account_id"`
	Handle            *string         `json:"handle"`
	ExternalPostID    *string         `json:"external_post_id"`
	URL               *string         `json:"url"`
	PublishedAt       *time.Time      `json:"published_at"`
	Status            string          `json:"status"`
	Error             *string         `json:"error"`
	ErrorDetail       json.RawMessage `json:"error_detail"`
	DryRun            bool            `json:"dry_run"`
	IntentID          *uuid.UUID      `json:"intent_id"`
}

type publishOutput struct {
	Publications []publicationItem `json:"publications"`
}

// afterPublish applies publications to intents, aggregates variant status, advances or
// marks needs_attention, and enqueues notify.requested when the stage has notify_stage.
func (e *Engine) afterPublish(ctx context.Context, tx pgx.Tx, j jobRow, output json.RawMessage) error {
	if e.Publish == nil {
		return fmt.Errorf("publish store not configured")
	}
	if j.variant == nil {
		return fmt.Errorf("publish job without variant")
	}
	var out publishOutput
	if err := json.Unmarshal(output, &out); err != nil {
		return err
	}
	for _, pub := range out.Publications {
		if err := e.applyOnePublication(ctx, tx, j, pub); err != nil {
			return err
		}
	}
	agg, pubs, err := e.aggregatePublishIntents(ctx, tx, *j.variant)
	if err != nil {
		return err
	}
	switch agg {
	case "published", "dry_run":
		if err := e.advance(ctx, tx, j.liveJob); err != nil {
			return err
		}
	case "partial", "failed", "unknown":
		reason := "publish_partial"
		if agg == "failed" {
			reason = "publish_failed"
		}
		if agg == "unknown" {
			reason = "publish_outcome_unknown"
		}
		attention, _ := json.Marshal(map[string]any{"reason": reason, "job_id": j.id})
		if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'needs_attention', attention = $2, rev = rev + 1 WHERE id = $1`,
			*j.variant, attention); err != nil {
			return err
		}
	default:
		return fmt.Errorf("unexpected publish aggregate %q", agg)
	}
	return e.enqueuePublishNotify(ctx, tx, j, agg, pubs)
}

func (e *Engine) applyOnePublication(ctx context.Context, tx pgx.Tx, j jobRow, pub publicationItem) error {
	intentID, err := e.resolveIntentID(ctx, tx, j, pub)
	if err != nil {
		return err
	}
	if intentID == uuid.Nil {
		return nil // skipped without intent — nothing to apply
	}
	// D23: denormalize module account identity onto the orchestration intent.
	var handle any
	if pub.Handle != nil {
		handle = *pub.Handle
	}
	acc := pub.PlatformAccountID
	if _, err := tx.Exec(ctx, `UPDATE publish_intents SET platform = $2, handle = $3,
		platform_account_id = COALESCE(platform_account_id, NULLIF($4, '00000000-0000-0000-0000-000000000000'::uuid))
		WHERE id = $1`, intentID, pub.Platform, handle, acc); err != nil {
		return err
	}
	switch pub.Status {
	case "published":
		if pub.ExternalPostID == nil || pub.URL == nil {
			return ErrOutputInvalid
		}
		at := time.Now().UTC()
		if pub.PublishedAt != nil {
			at = pub.PublishedAt.UTC()
		}
		return e.Publish.ApplyPublishedInTx(ctx, tx, intentID, *pub.ExternalPostID, *pub.URL, at)
	case "failed":
		code, retryable, msg := parseErrorDetail(pub)
		return e.Publish.ApplyFailedInTx(ctx, tx, intentID, code, retryable, msg)
	case "unknown":
		if err := e.Publish.ApplyUnknownInTx(ctx, tx, intentID); err != nil {
			return err
		}
		return nil
	case "skipped":
		// Dry-run / skipped: leave intent pending or mark failed non-retryable? Spec: skipped counts as ok for aggregate.
		// Keep pending→treat as cancelled-equivalent for aggregation by reading status; mark cancelled.
		_, err := tx.Exec(ctx, `UPDATE publish_intents SET status = 'cancelled', rev = rev + 1, updated_at = now()
			WHERE id = $1 AND status IN ('pending','in_progress')`, intentID)
		return err
	default:
		return ErrOutputInvalid
	}
}

func parseErrorDetail(pub publicationItem) (code string, retryable bool, message string) {
	code = "publish_failed"
	if pub.Error != nil {
		message = *pub.Error
	}
	if len(pub.ErrorDetail) > 0 && string(pub.ErrorDetail) != "null" {
		var d struct {
			Code      string `json:"code"`
			Retryable *bool  `json:"retryable"`
			Message   string `json:"message"`
		}
		if json.Unmarshal(pub.ErrorDetail, &d) == nil {
			if d.Code != "" {
				code = d.Code
			}
			if d.Message != "" {
				message = d.Message
			}
			if d.Retryable != nil {
				retryable = *d.Retryable
			}
		}
	}
	return code, retryable, message
}

func (e *Engine) resolveIntentID(ctx context.Context, tx pgx.Tx, j jobRow, pub publicationItem) (uuid.UUID, error) {
	if pub.IntentID != nil {
		return *pub.IntentID, nil
	}
	if j.variant == nil {
		return uuid.Nil, fmt.Errorf("publish publication missing intent_id and variant")
	}
	var id uuid.UUID
	err := tx.QueryRow(ctx, `SELECT id FROM publish_intents
		WHERE variant_id = $1 AND platform_account_id = $2
		ORDER BY generation DESC LIMIT 1`, *j.variant, pub.PlatformAccountID).Scan(&id)
	if err == nil {
		return id, nil
	}
	if err != pgx.ErrNoRows {
		return uuid.Nil, err
	}
	// D23: core intents often have NULL platform_account_id until the module binds one.
	err = tx.QueryRow(ctx, `SELECT id FROM publish_intents
		WHERE variant_id = $1 AND platform_account_id IS NULL
		  AND status IN ('pending','in_progress','unknown')
		ORDER BY generation DESC, created_at LIMIT 1`, *j.variant).Scan(&id)
	if err == pgx.ErrNoRows {
		return uuid.Nil, nil
	}
	return id, err
}

// aggregatePublishIntents returns overall status for notify + variant: published|partial|failed|unknown|dry_run.
func (e *Engine) aggregatePublishIntents(ctx context.Context, tx pgx.Tx, variantID uuid.UUID) (string, []publicationItem, error) {
	// D23: platform/handle denormalized on the intent (filled from module results); no platform_accounts in core.
	rows, err := tx.Query(ctx, `SELECT pi.id, pi.status, pi.external_post_id, pi.url, pi.published_at, pi.last_error,
		coalesce(pi.platform, 'instagram'), coalesce(pi.platform_account_id, '00000000-0000-0000-0000-000000000000'::uuid), pi.handle
		FROM publish_intents pi
		WHERE pi.variant_id = $1
		ORDER BY pi.generation DESC, pi.created_at`, variantID)
	if err != nil {
		return "", nil, err
	}
	defer rows.Close()

	type row struct {
		id, accountID    uuid.UUID
		status, platform string
		ext, url, handle *string
		publishedAt      *time.Time
		lastError        []byte
	}
	var items []row
	seenAccount := map[uuid.UUID]bool{}
	for rows.Next() {
		var r row
		if err := rows.Scan(&r.id, &r.status, &r.ext, &r.url, &r.publishedAt, &r.lastError, &r.platform, &r.accountID, &r.handle); err != nil {
			return "", nil, err
		}
		// Prefer latest generation per account.
		if seenAccount[r.accountID] {
			continue
		}
		seenAccount[r.accountID] = true
		items = append(items, r)
	}
	if err := rows.Err(); err != nil {
		return "", nil, err
	}
	if len(items) == 0 {
		return "failed", nil, nil
	}
	nPub, nFail, nUnk, nSkip, nOpen := 0, 0, 0, 0, 0
	pubs := make([]publicationItem, 0, len(items))
	for _, r := range items {
		pi := publicationItem{
			Platform: r.platform, PlatformAccountID: r.accountID, Handle: r.handle,
			ExternalPostID: r.ext, URL: r.url, PublishedAt: r.publishedAt, Status: r.status, IntentID: &r.id,
		}
		if len(r.lastError) > 0 {
			pi.ErrorDetail = append(json.RawMessage(nil), r.lastError...)
		}
		pubs = append(pubs, pi)
		switch r.status {
		case "published":
			nPub++
		case "failed":
			nFail++
		case "unknown":
			nUnk++
		case "cancelled":
			nSkip++
		default:
			nOpen++
		}
	}
	switch {
	case nUnk > 0:
		return "unknown", pubs, nil
	case nFail > 0 && nPub > 0:
		return "partial", pubs, nil
	case nFail > 0 && nPub == 0:
		return "failed", pubs, nil
	case nPub+nSkip == len(items) && nPub == 0:
		return "dry_run", pubs, nil
	case nPub+nSkip == len(items):
		return "published", pubs, nil
	default:
		// Still open intents after a success callback — treat as partial attention.
		return "partial", pubs, nil
	}
}

func (e *Engine) enqueuePublishNotify(ctx context.Context, tx pgx.Tx, j jobRow, agg string, pubs []publicationItem) error {
	stage := j.snapshot[j.position-1]
	if stage.NotifyStage == nil || *stage.NotifyStage == "" {
		return nil
	}
	var moduleID string
	err := tx.QueryRow(ctx, `SELECT id FROM modules WHERE stage_id = $1 AND active AND enabled AND health = 'up' LIMIT 1`, *stage.NotifyStage).Scan(&moduleID)
	if err == pgx.ErrNoRows {
		e.Log.Warn("no active notify module", "stage", *stage.NotifyStage, "job_id", j.id)
		return nil
	}
	if err != nil {
		return err
	}
	notifyStatus := agg
	switch agg {
	case "unknown":
		notifyStatus = "failed"
	}
	var language string
	var channels []string
	if err := tx.QueryRow(ctx, `SELECT language, channels FROM variants WHERE id = $1`, *j.variant).Scan(&language, &channels); err != nil {
		return err
	}
	channelID := "unknown"
	if len(channels) > 0 {
		channelID = channels[0]
	}
	var channelName string
	_ = tx.QueryRow(ctx, `SELECT name FROM channels WHERE id = $1`, channelID).Scan(&channelName)
	if channelName == "" {
		channelName = channelID
	}
	notificationID := uuid.NewSHA1(uuid.NameSpaceOID, append(j.id[:], []byte("notification")...))
	pubMaps := make([]map[string]any, 0, len(pubs))
	for _, p := range pubs {
		m := map[string]any{
			"platform": p.Platform, "platform_account_id": p.PlatformAccountID.String(),
			"status": mapIntentStatusForNotify(p.Status),
		}
		if p.Handle != nil {
			m["handle"] = *p.Handle
		}
		if p.ExternalPostID != nil {
			m["external_post_id"] = *p.ExternalPostID
		}
		if p.URL != nil {
			m["url"] = *p.URL
		}
		if p.PublishedAt != nil {
			m["published_at"] = p.PublishedAt.UTC().Format(time.RFC3339)
		}
		if p.IntentID != nil {
			m["intent_id"] = p.IntentID.String()
		}
		if len(p.ErrorDetail) > 0 {
			m["error_detail"] = json.RawMessage(p.ErrorDetail)
		}
		pubMaps = append(pubMaps, m)
	}
	payload, err := json.Marshal(map[string]any{
		"notification_id": notificationID.String(),
		"production_id":   j.production.String(),
		"variant_id":      j.variant.String(),
		"language":        language,
		"status":          notifyStatus,
		"channel":         map[string]any{"id": channelID, "name": channelName, "language": language},
		"publications":    pubMaps,
		"attention_kind":  agg, // extension: published|partial|failed|unknown|dry_run
	})
	if err != nil {
		return err
	}
	return e.EnqueueNotify(ctx, tx, moduleID, payload, j.production, j.id, j.fence)
}

func mapIntentStatusForNotify(status string) string {
	switch status {
	case "published":
		return "published"
	case "cancelled":
		return "skipped"
	case "unknown":
		return "failed"
	default:
		return "failed"
	}
}

// afterPublishFail marks open intents unknown (blocked / retries exhausted) and enqueues a failed notify.
func (e *Engine) afterPublishFail(ctx context.Context, tx pgx.Tx, j liveJob, class string) error {
	if j.variant == nil || e.Publish == nil {
		return e.onFailureDefault(ctx, tx, j, class)
	}
	if class == "transient" && j.try < j.maxTries {
		return e.onFailureDefault(ctx, tx, j, class)
	}
	rows, err := tx.Query(ctx, `SELECT id FROM publish_intents
		WHERE variant_id = $1 AND status IN ('pending','in_progress')`, *j.variant)
	if err != nil {
		return err
	}
	ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return err
	}
	reason := "blocked"
	if class == "transient" {
		reason = "retries_exhausted"
	}
	if class == "fatal" {
		reason = "publish_failed"
		for _, id := range ids {
			if err := e.Publish.ApplyFailedInTx(ctx, tx, id, "publish_job_fatal", false, "publish job fatal"); err != nil {
				return err
			}
		}
		attention, _ := json.Marshal(map[string]any{"reason": reason, "job_id": j.id})
		if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'failed', attention = $2, rev = rev + 1 WHERE id = $1`, *j.variant, attention); err != nil {
			return err
		}
		if err := e.completeProduction(ctx, tx, j.production); err != nil {
			return err
		}
	} else {
		for _, id := range ids {
			if err := e.Publish.ApplyUnknownInTx(ctx, tx, id); err != nil {
				return err
			}
		}
		attention, _ := json.Marshal(map[string]any{"reason": "publish_outcome_unknown", "job_id": j.id, "class": class})
		if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'needs_attention', attention = $2, rev = rev + 1 WHERE id = $1`,
			*j.variant, attention); err != nil {
			return err
		}
		_ = reason
	}
	jr := jobRow{liveJob: j}
	// Reload snapshot position fields already on liveJob.
	agg := "failed"
	if class != "fatal" {
		agg = "unknown"
	}
	_, pubs, err := e.aggregatePublishIntents(ctx, tx, *j.variant)
	if err != nil {
		return err
	}
	return e.enqueuePublishNotify(ctx, tx, jr, agg, pubs)
}

// onFailureDefault is the generic failure path (non-publish or publish still retrying).
func (e *Engine) onFailureDefault(ctx context.Context, tx pgx.Tx, j liveJob, class string) error {
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
