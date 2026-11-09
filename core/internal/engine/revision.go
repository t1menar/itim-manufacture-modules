package engine

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// snapshotVideoRevision writes content_revisions from the video stage result (D19/C39).
// Body snapshots artifacts + required metadata + provenance. Production-scope video jobs
// (variant_id NULL) create one revision per production variant, matched by language.
func (e *Engine) snapshotVideoRevision(ctx context.Context, tx pgx.Tx, j jobRow, output json.RawMessage) error {
	if e.Publish == nil {
		return nil
	}
	var parsed struct {
		Variants   []json.RawMessage `json:"variants"`
		Provenance json.RawMessage   `json:"provenance"`
		Changes    *string           `json:"changes"`
	}
	if err := json.Unmarshal(output, &parsed); err != nil {
		return err
	}
	if len(parsed.Variants) == 0 {
		return ErrOutputInvalid
	}

	type target struct {
		id       uuid.UUID
		language string
	}
	var targets []target
	if j.variant != nil {
		var lang string
		_ = tx.QueryRow(ctx, `SELECT language FROM variants WHERE id = $1`, *j.variant).Scan(&lang)
		targets = append(targets, target{id: *j.variant, language: lang})
	} else {
		rows, err := tx.Query(ctx, `SELECT id, language FROM variants WHERE production_id = $1 ORDER BY id`, j.production)
		if err != nil {
			return err
		}
		targets, err = pgx.CollectRows(rows, func(row pgx.CollectableRow) (target, error) {
			var t target
			err := row.Scan(&t.id, &t.language)
			return t, err
		})
		if err != nil {
			return err
		}
	}
	if len(targets) == 0 {
		return fmt.Errorf("no variants for video revision")
	}

	byLang := map[string]json.RawMessage{}
	var ordered []json.RawMessage
	for _, raw := range parsed.Variants {
		var v struct {
			Language string `json:"language"`
		}
		_ = json.Unmarshal(raw, &v)
		if v.Language != "" {
			byLang[v.Language] = raw
		}
		ordered = append(ordered, raw)
	}

	for i, t := range targets {
		raw, ok := byLang[t.language]
		if !ok {
			if i >= len(ordered) {
				return ErrOutputInvalid
			}
			raw = ordered[i]
		}
		var v map[string]any
		if err := json.Unmarshal(raw, &v); err != nil {
			return err
		}
		meta, _ := v["metadata"].(map[string]any)
		if meta == nil {
			return ErrOutputInvalid
		}
		bodyMap := map[string]any{
			"variant_id": t.id.String(),
			"job_id":     j.id.String(),
			"language":   v["language"],
			"video":      v["video"],
			"metadata":   meta,
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
		body, err := json.Marshal(bodyMap)
		if err != nil {
			return err
		}
		rev, err := e.Publish.CreateRevisionInTx(ctx, tx, t.id, j.id, body)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload)
			VALUES ($1, $2, $3, 'content_revision.created', 'system', jsonb_build_object(
				'content_revision_id', $4::text, 'revision', $5::int))`,
			j.production, t.id, j.id, rev.ID, rev.Revision); err != nil {
			return err
		}
	}
	return nil
}
