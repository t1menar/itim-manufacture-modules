// Package modules registers modules, rotates tokens and tracks liveness (core-04 §6, §2.12).
package modules

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/url"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/t1menar/manufacture/core/internal/auth"
	"github.com/t1menar/manufacture/core/internal/crypto"
	"github.com/t1menar/manufacture/core/internal/db"
)

var (
	ErrAlreadyExists = errors.New("already_exists")
	ErrNotFound      = errors.New("not_found")
	ErrValidation    = errors.New("validation_failed")
	ErrStageMismatch = errors.New("module_stage_mismatch")
	ErrContract      = errors.New("module_contract_unsupported")
)

var slugRE = regexp.MustCompile(`^[a-z0-9][a-z0-9-]{1,39}$`)

const base62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

type MasterKey struct {
	Version int
	Key     []byte
}

type Info struct {
	Name           string         `json:"name"`
	Version        string         `json:"version"`
	Contract       int            `json:"contract"`
	Stages         []string       `json:"stages"`
	SettingsSchema map[string]any `json:"settings_schema"`
	AdminEndpoints []string       `json:"admin_endpoints"`
}

// InfoFetcher retrieves GET {endpoint}/info. Tests inject a fake; production uses HTTP.
type InfoFetcher func(ctx context.Context, endpoint string) (Info, error)

type Registry struct {
	Pool      *pgxpool.Pool
	Key       MasterKey
	FetchInfo InfoFetcher   // required for Register unless Manifest is provided in RegisterOpts
	Grace     time.Duration // token rotation grace; default 15m
}

type RegisterOpts struct {
	ID, Name, Stage, Endpoint string
	Enabled                   *bool
	// Manifest, when set, skips the network probe (tests / offline registration).
	Manifest *Info
}

type Module struct {
	ID, Name, StageID, Endpoint string
	Version                     *string
	Contract                    *int
	Enabled, Active             bool
	Health, TokenPrefix         string
	LastSeenAt                  *time.Time
	Token                       string `json:"token,omitempty"` // only on create/rotate
	Rev                         int
}

func (r *Registry) defaults() {
	if r.Grace <= 0 {
		r.Grace = 15 * time.Minute
	}
}

// Register creates a module or returns the existing one when the same id+endpoint+stage is
// re-submitted (idempotent). A conflicting existing row → ErrAlreadyExists.
func (r *Registry) Register(ctx context.Context, opts RegisterOpts) (Module, error) {
	r.defaults()
	if !slugRE.MatchString(opts.ID) || !slugRE.MatchString(opts.Stage) || strings.TrimSpace(opts.Name) == "" {
		return Module{}, ErrValidation
	}
	u, err := url.Parse(opts.Endpoint)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return Module{}, ErrValidation
	}
	info := opts.Manifest
	if info == nil {
		if r.FetchInfo == nil {
			return Module{}, fmt.Errorf("no info fetcher")
		}
		got, err := r.FetchInfo(ctx, opts.Endpoint)
		if err != nil {
			return Module{}, err
		}
		info = &got
	}
	if info.Contract != 1 {
		return Module{}, ErrContract
	}
	okStage := false
	for _, s := range info.Stages {
		if s == opts.Stage {
			okStage = true
			break
		}
	}
	if !okStage {
		return Module{}, ErrStageMismatch
	}
	enabled := true
	if opts.Enabled != nil {
		enabled = *opts.Enabled
	}
	var out Module
	err = db.WithTx(ctx, r.Pool, func(tx pgx.Tx) error {
		var existing Module
		var ep string
		err := tx.QueryRow(ctx, `SELECT id, name, stage_id, endpoint, enabled, active, health, coalesce(token_prefix,''), rev
			FROM modules WHERE id = $1 FOR UPDATE`, opts.ID).
			Scan(&existing.ID, &existing.Name, &existing.StageID, &ep, &existing.Enabled, &existing.Active, &existing.Health, &existing.TokenPrefix, &existing.Rev)
		if err == nil {
			if ep == opts.Endpoint && existing.StageID == opts.Stage {
				// Idempotent re-registration: no new token.
				existing.Endpoint = ep
				existing.Token = ""
				out = existing
				return nil
			}
			return ErrAlreadyExists
		}
		if !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		var stageExists bool
		if err := tx.QueryRow(ctx, `SELECT exists(SELECT 1 FROM stages WHERE id = $1)`, opts.Stage).Scan(&stageExists); err != nil {
			return err
		}
		if !stageExists {
			return ErrValidation
		}
		raw, err := issueToken()
		if err != nil {
			return err
		}
		hash := auth.HashToken(raw)
		nonce, ct, err := crypto.Seal(r.Key.Key, []byte(raw), crypto.AADRef("module:"+opts.ID, r.Key.Version))
		if err != nil {
			return err
		}
		infoJSON, _ := json.Marshal(info)
		admins := info.AdminEndpoints
		if admins == nil {
			admins = []string{}
		}
		schema, _ := json.Marshal(info.SettingsSchema)
		if schema == nil {
			schema = []byte(`{}`)
		}
		_, err = tx.Exec(ctx, `INSERT INTO modules (
				id, name, stage_id, endpoint, version, contract, info, settings_schema, admin_endpoints,
				enabled, active, token_hash, token_prefix, token_ciphertext, token_nonce, token_key_version,
				health, last_seen_at)
			VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,false,$11,$12,$13,$14,$15,'unknown',now())`,
			opts.ID, opts.Name, opts.Stage, opts.Endpoint, info.Version, info.Contract, infoJSON, schema, admins,
			enabled, hash, auth.Prefix(raw), ct, nonce, r.Key.Version)
		if err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO module_settings (module_id, version, values, valid, is_current, author, comment)
			VALUES ($1, 1, '{}', true, true, 'system', 'registration')
			ON CONFLICT DO NOTHING`, opts.ID); err != nil {
			return err
		}
		if _, err := tx.Exec(ctx, `INSERT INTO events (type, actor, payload) VALUES ('module.registered', 'system', jsonb_build_object('module', $1::text, 'stage', $2::text))`,
			opts.ID, opts.Stage); err != nil {
			return err
		}
		out = Module{ID: opts.ID, Name: opts.Name, StageID: opts.Stage, Endpoint: opts.Endpoint,
			Enabled: enabled, Health: "unknown", TokenPrefix: auth.Prefix(raw), Token: raw, Rev: 1}
		v := info.Version
		c := info.Contract
		out.Version, out.Contract = &v, &c
		return nil
	})
	return out, err
}

// RotateToken issues a new mft_ token; the previous hash stays valid until grace expires.
func (r *Registry) RotateToken(ctx context.Context, moduleID string) (raw string, prefix string, prevExpires time.Time, err error) {
	r.defaults()
	raw, err = issueToken()
	if err != nil {
		return "", "", time.Time{}, err
	}
	prevExpires = time.Now().UTC().Add(r.Grace)
	err = db.WithTx(ctx, r.Pool, func(tx pgx.Tx) error {
		var oldHash []byte
		if err := tx.QueryRow(ctx, `SELECT token_hash FROM modules WHERE id = $1 FOR UPDATE`, moduleID).Scan(&oldHash); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		nonce, ct, err := crypto.Seal(r.Key.Key, []byte(raw), crypto.AADRef("module:"+moduleID, r.Key.Version))
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `UPDATE modules SET prev_token_hash = token_hash, prev_token_expires_at = $2,
			token_hash = $3, token_prefix = $4, token_ciphertext = $5, token_nonce = $6, token_key_version = $7,
			rev = rev + 1, updated_at = now() WHERE id = $1`,
			moduleID, prevExpires, auth.HashToken(raw), auth.Prefix(raw), ct, nonce, r.Key.Version)
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `INSERT INTO events (type, actor, payload) VALUES ('module.token_rotated', 'system', jsonb_build_object('module', $1::text))`, moduleID)
		return err
	})
	return raw, auth.Prefix(raw), prevExpires, err
}

// Heartbeat records liveness from the module (or from a successful callback).
func (r *Registry) Heartbeat(ctx context.Context, moduleID string) error {
	tag, err := r.Pool.Exec(ctx, `UPDATE modules SET last_seen_at = now(), health = CASE
		WHEN health IN ('down','unknown') THEN 'up' ELSE health END,
		consecutive_failures = 0, updated_at = now() WHERE id = $1`, moduleID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		return ErrNotFound
	}
	return nil
}

// MarkOffline marks modules whose last_seen_at is older than offlineAfter as down.
func (r *Registry) MarkOffline(ctx context.Context, offlineAfter time.Duration) (int, error) {
	if offlineAfter <= 0 {
		offlineAfter = 90 * time.Second
	}
	tag, err := r.Pool.Exec(ctx, `UPDATE modules SET health = 'down',
		health_detail = jsonb_build_object('reason', 'heartbeat_timeout'),
		updated_at = now()
		WHERE enabled AND health <> 'down'
		  AND (last_seen_at IS NULL OR last_seen_at < now() - make_interval(secs => $1))`, offlineAfter.Seconds())
	if err != nil {
		return 0, err
	}
	return int(tag.RowsAffected()), nil
}

// Activate sets the module active for its stage when health is up (or force for tests).
func (r *Registry) Activate(ctx context.Context, moduleID string, replace bool) error {
	return db.WithTx(ctx, r.Pool, func(tx pgx.Tx) error {
		var stage, health string
		var enabled bool
		if err := tx.QueryRow(ctx, `SELECT stage_id, enabled, health FROM modules WHERE id = $1 FOR UPDATE`, moduleID).
			Scan(&stage, &enabled, &health); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				return ErrNotFound
			}
			return err
		}
		if !enabled || health != "up" {
			return fmt.Errorf("module_not_ready")
		}
		if replace {
			if _, err := tx.Exec(ctx, `UPDATE modules SET active = false, rev = rev + 1, updated_at = now()
				WHERE stage_id = $1 AND active AND id <> $2`, stage, moduleID); err != nil {
				return err
			}
		}
		_, err := tx.Exec(ctx, `UPDATE modules SET active = true, rev = rev + 1, updated_at = now() WHERE id = $1`, moduleID)
		return err
	})
}

// Deactivate clears active for the module (does not disable registration).
func (r *Registry) Deactivate(ctx context.Context, moduleID string) error {
	tag, err := r.Pool.Exec(ctx, `UPDATE modules SET active = false, rev = rev + 1, updated_at = now()
		WHERE id = $1 AND active`, moduleID)
	if err != nil {
		return err
	}
	if tag.RowsAffected() == 0 {
		var exists bool
		_ = r.Pool.QueryRow(ctx, `SELECT true FROM modules WHERE id = $1`, moduleID).Scan(&exists)
		if !exists {
			return ErrNotFound
		}
	}
	return nil
}

func issueToken() (string, error) {
	b := make([]byte, 32)
	for i := range b {
		n, err := rand.Int(rand.Reader, big.NewInt(int64(len(base62))))
		if err != nil {
			return "", err
		}
		b[i] = base62[n.Int64()]
	}
	return "mft_" + string(b), nil
}
