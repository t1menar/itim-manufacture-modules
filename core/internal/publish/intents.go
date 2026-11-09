// Package publish implements content revisions and publish intents (core-04 §16).
// Republish (generation > 1) is not enabled: P2 is proposed, not accepted.
package publish

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/t1menar/manufacture/core/internal/db"
)

var (
	ErrNotFound     = errors.New("not_found")
	ErrInvalidState = errors.New("invalid_state")
	ErrConflict     = errors.New("already_exists")
)

type Store struct {
	Pool *pgxpool.Pool
}

type Revision struct {
	ID        uuid.UUID
	VariantID uuid.UUID
	Revision  int
	Body      json.RawMessage
	SHA256    []byte
}

type Intent struct {
	ID                uuid.UUID
	VariantID         uuid.UUID
	PlatformAccountID uuid.UUID
	Generation        int
	ContentRevisionID uuid.UUID
	Status            string
	ExternalPostID    *string
	URL               *string
	PublishedAt       *time.Time
}

// CreateRevision appends an immutable content revision for the variant (body snapshotted as-is).
func (s *Store) CreateRevision(ctx context.Context, variantID, sourceJob uuid.UUID, body json.RawMessage) (Revision, error) {
	if len(body) == 0 || body[0] != '{' {
		return Revision{}, fmt.Errorf("body must be a JSON object")
	}
	sum := sha256.Sum256(body)
	var out Revision
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var next int
		if err := tx.QueryRow(ctx, `SELECT coalesce(max(revision), 0) + 1 FROM content_revisions WHERE variant_id = $1`, variantID).Scan(&next); err != nil {
			return err
		}
		id := uuid.Must(uuid.NewV7())
		_, err := tx.Exec(ctx, `INSERT INTO content_revisions (id, variant_id, revision, body, sha256, source_job_id)
			VALUES ($1,$2,$3,$4,$5,$6)`, id, variantID, next, body, sum[:], sourceJob)
		if err != nil {
			return err
		}
		out = Revision{ID: id, VariantID: variantID, Revision: next, Body: append(json.RawMessage(nil), body...), SHA256: sum[:]}
		return nil
	})
	return out, err
}

// ApproveRevision marks the revision approved and creates generation-1 intents for every
// enabled platform account of the variant's channels. Concurrent callers: unique index
// ensures at most one intent per (variant, account, generation=1).
func (s *Store) ApproveAndCreateIntents(ctx context.Context, revisionID uuid.UUID, round int) ([]Intent, error) {
	var out []Intent
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var variantID uuid.UUID
		var approved *int
		if err := tx.QueryRow(ctx, `SELECT variant_id, approved_round FROM content_revisions WHERE id = $1 FOR UPDATE`, revisionID).
			Scan(&variantID, &approved); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if approved != nil {
			// Already approved: return existing generation-1 intents (idempotent).
			rows, err := tx.Query(ctx, `SELECT id, variant_id, platform_account_id, generation, content_revision_id, status
				FROM publish_intents WHERE variant_id = $1 AND generation = 1 AND content_revision_id = $2`, variantID, revisionID)
			if err != nil {
				return err
			}
			out, err = pgx.CollectRows(rows, scanIntent)
			return err
		}
		if _, err := tx.Exec(ctx, `UPDATE content_revisions SET approved_round = $2 WHERE id = $1 AND approved_round IS NULL`, revisionID, round); err != nil {
			return err
		}
		rows, err := tx.Query(ctx, `
			SELECT pa.id FROM platform_accounts pa
			JOIN variants v ON v.id = $1
			WHERE pa.enabled AND pa.channel_id = ANY (v.channels)
			ORDER BY pa.id
			FOR UPDATE OF pa`, variantID)
		if err != nil {
			return err
		}
		accounts, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
		if err != nil {
			return err
		}
		for _, acc := range accounts {
			id := uuid.Must(uuid.NewV7())
			tag, err := tx.Exec(ctx, `INSERT INTO publish_intents
				(id, variant_id, platform_account_id, generation, content_revision_id, status)
				VALUES ($1,$2,$3,1,$4,'pending')
				ON CONFLICT (variant_id, platform_account_id, generation) DO NOTHING`,
				id, variantID, acc, revisionID)
			if err != nil {
				return err
			}
			if tag.RowsAffected() == 0 {
				// Concurrent creator won; load existing.
				var existing Intent
				if err := tx.QueryRow(ctx, `SELECT id, variant_id, platform_account_id, generation, content_revision_id, status
					FROM publish_intents WHERE variant_id=$1 AND platform_account_id=$2 AND generation=1`,
					variantID, acc).Scan(&existing.ID, &existing.VariantID, &existing.PlatformAccountID, &existing.Generation, &existing.ContentRevisionID, &existing.Status); err != nil {
					return err
				}
				out = append(out, existing)
				continue
			}
			out = append(out, Intent{ID: id, VariantID: variantID, PlatformAccountID: acc, Generation: 1, ContentRevisionID: revisionID, Status: "pending"})
		}
		return nil
	})
	return out, err
}

func scanIntent(row pgx.CollectableRow) (Intent, error) {
	var i Intent
	err := row.Scan(&i.ID, &i.VariantID, &i.PlatformAccountID, &i.Generation, &i.ContentRevisionID, &i.Status)
	return i, err
}

// ApplyPublished marks intent published from a module callback (idempotent on same external_id).
func (s *Store) ApplyPublished(ctx context.Context, intentID uuid.UUID, externalID, url string, at time.Time) error {
	return db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var status string
		var curExt *string
		if err := tx.QueryRow(ctx, `SELECT status, external_post_id FROM publish_intents WHERE id = $1 FOR UPDATE`, intentID).
			Scan(&status, &curExt); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if status == "published" {
			if curExt != nil && *curExt == externalID {
				return nil // identical duplicate callback
			}
			return ErrConflict
		}
		if status != "pending" && status != "in_progress" && status != "unknown" {
			return ErrInvalidState
		}
		_, err := tx.Exec(ctx, `UPDATE publish_intents SET status = 'published', external_post_id = $2, url = $3,
			published_at = $4, rev = rev + 1, updated_at = now() WHERE id = $1`, intentID, externalID, url, at)
		return err
	})
}

// MarkUnknown sets status=unknown after failed reconcile (never auto-resends).
func (s *Store) MarkUnknown(ctx context.Context, intentID uuid.UUID) error {
	tag, err := s.Pool.Exec(ctx, `UPDATE publish_intents SET status = 'unknown', rev = rev + 1, updated_at = now()
		WHERE id = $1 AND status IN ('pending','in_progress','unknown')`, intentID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrInvalidState
	}
	return nil
}

// ReconcileFound applies a successful platform reconcile → published.
func (s *Store) ReconcileFound(ctx context.Context, intentID uuid.UUID, externalID, url string, at time.Time) error {
	return s.ApplyPublished(ctx, intentID, externalID, url, at)
}

// Get returns one intent.
func (s *Store) Get(ctx context.Context, id uuid.UUID) (Intent, error) {
	var i Intent
	err := s.Pool.QueryRow(ctx, `SELECT id, variant_id, platform_account_id, generation, content_revision_id, status,
		external_post_id, url, published_at FROM publish_intents WHERE id = $1`, id).
		Scan(&i.ID, &i.VariantID, &i.PlatformAccountID, &i.Generation, &i.ContentRevisionID, &i.Status,
			&i.ExternalPostID, &i.URL, &i.PublishedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Intent{}, ErrNotFound
	}
	return i, err
}

// RevisionBody returns the immutable body; used to prove later content edits do not mutate it.
func (s *Store) RevisionBody(ctx context.Context, id uuid.UUID) (json.RawMessage, error) {
	var b json.RawMessage
	err := s.Pool.QueryRow(ctx, `SELECT body FROM content_revisions WHERE id = $1`, id).Scan(&b)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, ErrNotFound
	}
	return b, err
}
