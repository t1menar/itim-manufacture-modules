// Package credentials stores secrets with AES-256-GCM (core-03 §3.17, core-04 §4.1).
package credentials

import (
	"context"
	"errors"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/t1menar/manufacture/core/internal/crypto"
	"github.com/t1menar/manufacture/core/internal/db"
)

var (
	ErrNotFound   = errors.New("credential_not_found")
	ErrNotAllowed = errors.New("credential_not_allowed")
	ErrValidation = errors.New("validation_failed")
)

type MasterKey struct {
	Version int
	Key     []byte
}

type Store struct {
	Pool *pgxpool.Pool
	Key  MasterKey
}

type Meta struct {
	ID, Ref, Name, Kind, Access string
	AllowedModules              []string
	OwnerModule                 *string
	Last4                       string
	ExpiresAt                   *time.Time
	Rev                         int
}

type PutOpts struct {
	Ref, Name, Kind, Access string
	AllowedModules          []string
	OwnerModule             *string
	Value                   string
	ExpiresAt               *time.Time
}

// Put creates or replaces a credential value. The plaintext never leaves this function.
func (s *Store) Put(ctx context.Context, opts PutOpts) (Meta, error) {
	if !strings.HasPrefix(opts.Ref, "cred:") || opts.Value == "" || opts.Name == "" {
		return Meta{}, ErrValidation
	}
	if opts.Kind == "" {
		opts.Kind = "generic"
	}
	if opts.Access == "" {
		opts.Access = "job"
	}
	if opts.Access != "job" && opts.Access != "module" {
		return Meta{}, ErrValidation
	}
	last4 := opts.Value
	if utf8.RuneCountInString(last4) > 4 {
		r := []rune(last4)
		last4 = string(r[len(r)-4:])
	}
	nonce, ct, err := crypto.Seal(s.Key.Key, []byte(opts.Value), crypto.AADRef(opts.Ref, s.Key.Version))
	if err != nil {
		return Meta{}, err
	}
	id := uuid.Must(uuid.NewV7())
	var out Meta
	err = db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var existing uuid.UUID
		err := tx.QueryRow(ctx, `SELECT id FROM credentials WHERE ref = $1 FOR UPDATE`, opts.Ref).Scan(&existing)
		if errors.Is(err, pgx.ErrNoRows) {
			_, err = tx.Exec(ctx, `INSERT INTO credentials (
					id, ref, name, kind, access, allowed_modules, owner_module,
					ciphertext, nonce, key_version, last4, expires_at, rotated_at)
				VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,now())`,
				id, opts.Ref, opts.Name, opts.Kind, opts.Access, opts.AllowedModules, opts.OwnerModule,
				ct, nonce, s.Key.Version, last4, opts.ExpiresAt)
			if err != nil {
				return err
			}
			out = Meta{ID: id.String(), Ref: opts.Ref, Name: opts.Name, Kind: opts.Kind, Access: opts.Access,
				AllowedModules: opts.AllowedModules, OwnerModule: opts.OwnerModule, Last4: last4, ExpiresAt: opts.ExpiresAt, Rev: 1}
			return nil
		}
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `UPDATE credentials SET name=$2, kind=$3, access=$4, allowed_modules=$5, owner_module=$6,
			ciphertext=$7, nonce=$8, key_version=$9, last4=$10, expires_at=$11, rotated_at=now(),
			rev = rev + 1, updated_at = now() WHERE id = $1`,
			existing, opts.Name, opts.Kind, opts.Access, opts.AllowedModules, opts.OwnerModule,
			ct, nonce, s.Key.Version, last4, opts.ExpiresAt)
		if err != nil {
			return err
		}
		out = Meta{ID: existing.String(), Ref: opts.Ref, Name: opts.Name, Kind: opts.Kind, Access: opts.Access,
			AllowedModules: opts.AllowedModules, OwnerModule: opts.OwnerModule, Last4: last4, ExpiresAt: opts.ExpiresAt}
		return nil
	})
	return out, err
}

// Read returns the plaintext for an allowed module. Denied attempts are logged without the value.
func (s *Store) Read(ctx context.Context, ref, moduleID string, jobID *uuid.UUID) (value string, meta Meta, err error) {
	var id uuid.UUID
	var name, kind, access string
	var allowed []string
	var owner *string
	var ct, nonce []byte
	var keyVer int
	var last4 string
	var exp *time.Time
	var rev int
	err = s.Pool.QueryRow(ctx, `SELECT id, name, kind, access, allowed_modules, owner_module, ciphertext, nonce, key_version, last4, expires_at, rev
		FROM credentials WHERE ref = $1`, ref).
		Scan(&id, &name, &kind, &access, &allowed, &owner, &ct, &nonce, &keyVer, &last4, &exp, &rev)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", Meta{}, ErrNotFound
	}
	if err != nil {
		return "", Meta{}, err
	}
	meta = Meta{ID: id.String(), Ref: ref, Name: name, Kind: kind, Access: access, AllowedModules: allowed, OwnerModule: owner, Last4: last4, ExpiresAt: exp, Rev: rev}
	allowedModule := false
	for _, m := range allowed {
		if m == moduleID {
			allowedModule = true
			break
		}
	}
	deny := func() error {
		_, _ = s.Pool.Exec(ctx, `INSERT INTO credential_access_log (credential_id, principal, job_id, action, outcome)
			VALUES ($1, $2, $3, 'read', 'denied')`, id, "module:"+moduleID, jobID)
		return ErrNotAllowed
	}
	if !allowedModule {
		return "", meta, deny()
	}
	if access == "job" {
		if jobID == nil {
			return "", meta, deny()
		}
		var ok bool
		// Job must be live, owned by this module, and list the ref in request.credentials.
		err = s.Pool.QueryRow(ctx, `SELECT exists(
			SELECT 1 FROM jobs WHERE id = $1 AND module_id = $2
			  AND status IN ('queued','dispatching','dispatched','running')
			  AND coalesce(request->'credentials', '[]'::jsonb) ? $3)`, *jobID, moduleID, ref).Scan(&ok)
		if err != nil || !ok {
			return "", meta, deny()
		}
	}
	pt, err := crypto.Open(s.Key.Key, nonce, ct, crypto.AADRef(ref, keyVer))
	if err != nil {
		return "", meta, err
	}
	_, _ = s.Pool.Exec(ctx, `UPDATE credentials SET last_used_at = now() WHERE id = $1`, id)
	_, _ = s.Pool.Exec(ctx, `INSERT INTO credential_access_log (credential_id, principal, job_id, action, outcome)
		VALUES ($1, $2, $3, 'read', 'allowed')`, id, "module:"+moduleID, jobID)
	return string(pt), meta, nil
}
