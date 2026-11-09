// Package auth resolves Bearer tokens to principals (core-04 §1.2).
package auth

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"errors"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Kind string

const (
	KindModule Kind = "module"
	KindAdmin  Kind = "admin"
)

type Principal struct {
	Kind     Kind
	ModuleID string // set when KindModule
}

var (
	ErrUnauthorized = errors.New("unauthorized")
	ErrForbidden    = errors.New("forbidden")
)

// HashToken returns SHA-256 of the raw token bytes (including the mft_/mfa_ prefix).
func HashToken(raw string) []byte {
	sum := sha256.Sum256([]byte(raw))
	return sum[:]
}

// Prefix returns the first 8 characters of the token for display.
func Prefix(raw string) string {
	if len(raw) < 8 {
		return raw
	}
	return raw[:8]
}

// Authenticator looks up tokens in the modules table (and a configured admin hash).
type Authenticator struct {
	Pool           *pgxpool.Pool
	AdminTokenHash []byte // SHA-256 of the admin-api token; empty = no admin principal
}

// FromRequest parses Authorization: Bearer and resolves the principal.
func (a *Authenticator) FromRequest(ctx context.Context, authorization string) (Principal, error) {
	const p = "Bearer "
	if !strings.HasPrefix(authorization, p) {
		return Principal{}, ErrUnauthorized
	}
	raw := strings.TrimSpace(authorization[len(p):])
	if raw == "" {
		return Principal{}, ErrUnauthorized
	}
	hash := HashToken(raw)
	if len(a.AdminTokenHash) == 32 && subtle.ConstantTimeCompare(hash, a.AdminTokenHash) == 1 {
		return Principal{Kind: KindAdmin}, nil
	}
	if strings.HasPrefix(raw, "mfa_") {
		return Principal{}, ErrUnauthorized // unknown admin token
	}
	var id string
	var cur, prev []byte
	var prevExp *time.Time
	err := a.Pool.QueryRow(ctx, `SELECT id, token_hash, prev_token_hash, prev_token_expires_at FROM modules
		WHERE token_hash = $1 OR (prev_token_hash = $1 AND (prev_token_expires_at IS NULL OR prev_token_expires_at > now()))`, hash).
		Scan(&id, &cur, &prev, &prevExp)
	if errors.Is(err, pgx.ErrNoRows) {
		return Principal{}, ErrUnauthorized
	}
	if err != nil {
		return Principal{}, err
	}
	ok := subtle.ConstantTimeCompare(hash, cur) == 1
	if !ok && len(prev) == 32 && prevExp != nil && prevExp.After(time.Now()) {
		ok = subtle.ConstantTimeCompare(hash, prev) == 1
	}
	if !ok {
		return Principal{}, ErrUnauthorized
	}
	return Principal{Kind: KindModule, ModuleID: id}, nil
}

// SetModuleToken stores the hash of a freshly issued token (used by tests and registration).
func SetModuleToken(ctx context.Context, pool *pgxpool.Pool, moduleID, raw string) error {
	_, err := pool.Exec(ctx, `UPDATE modules SET token_hash = $2, token_prefix = $3 WHERE id = $1`,
		moduleID, HashToken(raw), Prefix(raw))
	return err
}
