// Package publish implements content revisions and publish intents (core-04 §16).
// Manual republish (generation > 1) is admin-only with a required reason (accepted P2/C38).
package publish

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
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
	// OnIntentCreated, when set, runs inside the Republish transaction after the new
	// generation row and audit event are written (used to enqueue one publish job.requested).
	OnIntentCreated func(ctx context.Context, tx pgx.Tx, intent Intent) error
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
	var out Revision
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var err error
		out, err = s.CreateRevisionInTx(ctx, tx, variantID, sourceJob, body)
		return err
	})
	return out, err
}

// CreateRevisionInTx is CreateRevision inside the caller's transaction.
func (s *Store) CreateRevisionInTx(ctx context.Context, tx pgx.Tx, variantID, sourceJob uuid.UUID, body json.RawMessage) (Revision, error) {
	if len(body) == 0 || body[0] != '{' {
		return Revision{}, fmt.Errorf("body must be a JSON object")
	}
	sum := sha256.Sum256(body)
	var next int
	if err := tx.QueryRow(ctx, `SELECT coalesce(max(revision), 0) + 1 FROM content_revisions WHERE variant_id = $1`, variantID).Scan(&next); err != nil {
		return Revision{}, err
	}
	id := uuid.Must(uuid.NewV7())
	if _, err := tx.Exec(ctx, `INSERT INTO content_revisions (id, variant_id, revision, body, sha256, source_job_id)
		VALUES ($1,$2,$3,$4,$5,$6)`, id, variantID, next, body, sum[:], sourceJob); err != nil {
		return Revision{}, err
	}
	return Revision{ID: id, VariantID: variantID, Revision: next, Body: append(json.RawMessage(nil), body...), SHA256: sum[:]}, nil
}

// ApproveRevision marks the revision approved and creates generation-1 intents for every
// enabled platform account of the variant's channels. Concurrent callers: unique index
// ensures at most one intent per (variant, account, generation=1).
func (s *Store) ApproveAndCreateIntents(ctx context.Context, revisionID uuid.UUID, round int) ([]Intent, error) {
	var out []Intent
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var err error
		out, err = s.ApproveAndCreateIntentsInTx(ctx, tx, revisionID, round)
		return err
	})
	return out, err
}

// ApproveAndCreateIntentsInTx is ApproveAndCreateIntents inside the caller's transaction
// (review approve → intents + publish outbox in one commit).
func (s *Store) ApproveAndCreateIntentsInTx(ctx context.Context, tx pgx.Tx, revisionID uuid.UUID, round int) ([]Intent, error) {
	var out []Intent
	var variantID uuid.UUID
	var approved *int
	if err := tx.QueryRow(ctx, `SELECT variant_id, approved_round FROM content_revisions WHERE id = $1 FOR UPDATE`, revisionID).
		Scan(&variantID, &approved); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	if approved != nil {
		rows, err := tx.Query(ctx, `SELECT id, variant_id, platform_account_id, generation, content_revision_id, status
			FROM publish_intents WHERE variant_id = $1 AND generation = 1 AND content_revision_id = $2`, variantID, revisionID)
		if err != nil {
			return nil, err
		}
		return pgx.CollectRows(rows, scanIntent)
	}
	if _, err := tx.Exec(ctx, `UPDATE content_revisions SET approved_round = $2 WHERE id = $1 AND approved_round IS NULL`, revisionID, round); err != nil {
		return nil, err
	}
	rows, err := tx.Query(ctx, `
		SELECT pa.id FROM platform_accounts pa
		JOIN variants v ON v.id = $1
		WHERE pa.enabled AND pa.channel_id = ANY (v.channels)
		ORDER BY pa.id
		FOR UPDATE OF pa`, variantID)
	if err != nil {
		return nil, err
	}
	accounts, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
	if err != nil {
		return nil, err
	}
	for _, acc := range accounts {
		id := uuid.Must(uuid.NewV7())
		tag, err := tx.Exec(ctx, `INSERT INTO publish_intents
			(id, variant_id, platform_account_id, generation, content_revision_id, status)
			VALUES ($1,$2,$3,1,$4,'pending')
			ON CONFLICT (variant_id, platform_account_id, generation) DO NOTHING`,
			id, variantID, acc, revisionID)
		if err != nil {
			return nil, err
		}
		if tag.RowsAffected() == 0 {
			var existing Intent
			if err := tx.QueryRow(ctx, `SELECT id, variant_id, platform_account_id, generation, content_revision_id, status
				FROM publish_intents WHERE variant_id=$1 AND platform_account_id=$2 AND generation=1`,
				variantID, acc).Scan(&existing.ID, &existing.VariantID, &existing.PlatformAccountID, &existing.Generation, &existing.ContentRevisionID, &existing.Status); err != nil {
				return nil, err
			}
			out = append(out, existing)
			continue
		}
		out = append(out, Intent{ID: id, VariantID: variantID, PlatformAccountID: acc, Generation: 1, ContentRevisionID: revisionID, Status: "pending"})
	}
	return out, nil
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

// RepublishOpts is the admin-only manual republish (accepted P2/C38: admin + reason only).
type RepublishOpts struct {
	IntentID               uuid.UUID // any generation of the (variant, account) pair; used to resolve the key
	Reason                 string
	BaseGeneration         int        // must equal current max generation
	AcknowledgeUnknownRisk bool       // required when current status is unknown
	ContentRevisionID      *uuid.UUID // default: latest approved revision of the variant
	Actor                  string     // user:<id> or admin-api
	IdempotencyKey         string
	IdempotencyPath        string
	IdempotencyBodyHash    []byte
}

var (
	ErrGenerationConflict = errors.New("generation_conflict")
	ErrUnknownNeedsAck    = errors.New("unknown_needs_ack")
	ErrValidation         = errors.New("validation_failed")
	ErrIdempotencyReuse   = errors.New("idempotency_key_reused")
)

type RepublishResult struct {
	Intent       Intent
	Idempotent   bool
	HTTPStatus   int
	HTTPResponse json.RawMessage
}

// Republish creates generation max+1 for the same (variant, account). No automatic path calls this.
func (s *Store) Republish(ctx context.Context, opts RepublishOpts) (RepublishResult, error) {
	reason := strings.TrimSpace(opts.Reason)
	if reason == "" || len(reason) > 2000 {
		return RepublishResult{}, ErrValidation
	}
	if opts.BaseGeneration < 1 {
		return RepublishResult{}, ErrValidation
	}
	if opts.Actor == "" {
		opts.Actor = "admin-api"
	}
	var out RepublishResult
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		if opts.IdempotencyKey != "" {
			var status int
			var resp []byte
			var bodyHash []byte
			err := tx.QueryRow(ctx, `SELECT status_code, response, body_hash FROM idempotency_keys
				WHERE principal = $1 AND key = $2 FOR UPDATE`, opts.Actor, opts.IdempotencyKey).
				Scan(&status, &resp, &bodyHash)
			if err == nil {
				if subtle.ConstantTimeCompare(bodyHash, opts.IdempotencyBodyHash) != 1 {
					return ErrIdempotencyReuse
				}
				out = RepublishResult{Idempotent: true, HTTPStatus: status, HTTPResponse: resp}
				_ = json.Unmarshal(resp, &struct {
					ID *uuid.UUID `json:"id"`
				}{})
				// fill Intent from response id if present
				var parsed struct {
					ID uuid.UUID `json:"id"`
				}
				if json.Unmarshal(resp, &parsed) == nil && parsed.ID != uuid.Nil {
					out.Intent.ID = parsed.ID
				}
				return nil
			}
			if !errors.Is(err, pgx.ErrNoRows) {
				return err
			}
		}

		var variantID, accountID, curRev uuid.UUID
		var curGen int
		var status string
		err := tx.QueryRow(ctx, `SELECT variant_id, platform_account_id, generation, content_revision_id, status
			FROM publish_intents WHERE id = $1 FOR UPDATE`, opts.IntentID).
			Scan(&variantID, &accountID, &curGen, &curRev, &status)
		if errors.Is(err, pgx.ErrNoRows) {
			return ErrNotFound
		}
		if err != nil {
			return err
		}
		// Lock the latest generation for this pair (the path id may be an older generation).
		var latestID uuid.UUID
		err = tx.QueryRow(ctx, `SELECT id, generation, content_revision_id, status FROM publish_intents
			WHERE variant_id = $1 AND platform_account_id = $2
			ORDER BY generation DESC LIMIT 1 FOR UPDATE`, variantID, accountID).
			Scan(&latestID, &curGen, &curRev, &status)
		if err != nil {
			return err
		}
		prevIntentID := latestID
		if curGen != opts.BaseGeneration {
			return ErrGenerationConflict
		}
		if status == "pending" || status == "in_progress" {
			return ErrInvalidState
		}
		if status == "unknown" && !opts.AcknowledgeUnknownRisk {
			return ErrUnknownNeedsAck
		}
		revID := curRev
		if opts.ContentRevisionID != nil {
			revID = *opts.ContentRevisionID
			var approved *int
			var v uuid.UUID
			if err := tx.QueryRow(ctx, `SELECT variant_id, approved_round FROM content_revisions WHERE id = $1`, revID).
				Scan(&v, &approved); err != nil {
				return ErrNotFound
			}
			if v != variantID || approved == nil {
				return ErrValidation
			}
		} else {
			// Prefer latest approved revision of the variant.
			_ = tx.QueryRow(ctx, `SELECT id FROM content_revisions WHERE variant_id = $1 AND approved_round IS NOT NULL
				ORDER BY revision DESC LIMIT 1`, variantID).Scan(&revID)
		}
		newID := uuid.Must(uuid.NewV7())
		next := curGen + 1
		if _, err := tx.Exec(ctx, `INSERT INTO publish_intents
			(id, variant_id, platform_account_id, generation, content_revision_id, status, authorized_by, reason)
			VALUES ($1,$2,$3,$4,$5,'pending',$6,$7)`,
			newID, variantID, accountID, next, revID, opts.Actor, reason); err != nil {
			if db.IsUniqueViolation(err, "publish_intents_variant_id_platform_account_id_generation_key") ||
				db.IsUniqueViolation(err, "") {
				return ErrGenerationConflict
			}
			return err
		}
		payload, _ := json.Marshal(map[string]any{
			"intent_id": newID, "previous_intent_id": prevIntentID,
			"variant_id": variantID, "platform_account_id": accountID,
			"previous_generation": curGen, "generation": next,
			"content_revision_id": revID, "reason": reason, "actor": opts.Actor,
			"previous_status": status,
		})
		if _, err := tx.Exec(ctx, `INSERT INTO events (type, actor, payload, variant_id)
			VALUES ('publish.republish_requested', $1, $2, $3)`, opts.Actor, payload, variantID); err != nil {
			return err
		}
		out.Intent = Intent{ID: newID, VariantID: variantID, PlatformAccountID: accountID, Generation: next, ContentRevisionID: revID, Status: "pending"}
		if s.OnIntentCreated != nil {
			if err := s.OnIntentCreated(ctx, tx, out.Intent); err != nil {
				return err
			}
		}
		resp, _ := json.Marshal(map[string]any{
			"id": newID, "variant_id": variantID, "platform_account_id": accountID,
			"generation": next, "content_revision_id": revID, "status": "pending",
			"previous_generation": curGen, "authorized_by": opts.Actor, "reason": reason,
		})
		out.HTTPStatus, out.HTTPResponse = 201, resp
		if opts.IdempotencyKey != "" {
			_, err = tx.Exec(ctx, `INSERT INTO idempotency_keys (principal, key, method, path, body_hash, status_code, response)
				VALUES ($1,$2,'POST',$3,$4,$5,$6)`, opts.Actor, opts.IdempotencyKey, opts.IdempotencyPath, opts.IdempotencyBodyHash, 201, resp)
			return err
		}
		return nil
	})
	return out, err
}
