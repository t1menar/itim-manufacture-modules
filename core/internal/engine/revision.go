package engine

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// snapshotVideoRevision writes content_revisions from the video stage result (D19/C39, D22).
// The body is an opaque JSON blob (raw variant object + orchestration ids). Core does not
// interpret metadata / video / post fields as its domain model — stage JSON Schema already
// validated the result. Production-scope video jobs (variant_id NULL) create one revision
// per production variant, matched by language when present.
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
		body, err := opaqueRevisionBody(t.id, j.id, raw, parsed.Provenance, parsed.Changes)
		if err != nil {
			return err
		}
		rev, err := e.Publish.CreateRevisionInTx(ctx, tx, t.id, j.id, body)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload)
			VALUES ($1, $2, $3, 'content_revision.created', 'system', jsonb_build_object(
				'content_revision_id', $4::text, 'revision', $5::int, 'sha256', encode($6::bytea, 'hex')))`,
			j.production, t.id, j.id, rev.ID, rev.Revision, rev.SHA256); err != nil {
			return err
		}
	}
	return nil
}

// opaqueRevisionBody builds the immutable revision blob (D22): the raw variant object plus
// orchestration ids. Domain keys (metadata, video, …) are copied through without interpretation.
func opaqueRevisionBody(variantID, jobID uuid.UUID, rawVariant, provenance json.RawMessage, changes *string) (json.RawMessage, error) {
	var blob map[string]any
	if err := json.Unmarshal(rawVariant, &blob); err != nil {
		return nil, err
	}
	if blob == nil {
		blob = map[string]any{}
	}
	blob["variant_id"] = variantID.String()
	blob["job_id"] = jobID.String()
	if len(provenance) > 0 {
		blob["provenance"] = json.RawMessage(provenance)
	}
	if changes != nil {
		blob["changes"] = *changes
	}
	return json.Marshal(blob)
}
