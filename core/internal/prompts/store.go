// Package prompts stores immutable prompt versions with activation and safe substitution.
// Spec D16/C40 place prompts in the module database; this package is the shared logic and an
// MVP table in core so jobs can snapshot prompts before the video module exists.
package prompts

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/t1menar/manufacture/core/internal/db"
)

var (
	ErrNotFound        = errors.New("not_found")
	ErrVersionConflict = errors.New("version_mismatch")
	ErrUnknownVar      = errors.New("unknown_variable")
	ErrValidation      = errors.New("validation_failed")
)

var (
	placeholderRE = regexp.MustCompile(`\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}`)
	idRE          = regexp.MustCompile(`^[a-z0-9][a-z0-9._-]{0,63}$`)
)

type Version struct {
	OwnerModule string
	PromptID    string
	Version     int
	Body        string
	Variables   []string
	SHA256      []byte
	Active      bool
	Author      string
	Comment     string
}

type Store struct {
	Pool *pgxpool.Pool
}

// Create appends an immutable version (inactive). Activation is a separate call.
func (s *Store) Create(ctx context.Context, owner, promptID, body, author, comment string, variables []string) (Version, error) {
	if !regexp.MustCompile(`^[a-z0-9][a-z0-9-]{1,39}$`).MatchString(owner) || !idRE.MatchString(promptID) || strings.TrimSpace(body) == "" {
		return Version{}, ErrValidation
	}
	if variables == nil {
		variables = declaredVars(body)
	}
	sum := sha256.Sum256([]byte(body))
	var out Version
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var next int
		if err := tx.QueryRow(ctx, `SELECT coalesce(max(version), 0) + 1 FROM prompts WHERE owner_module = $1 AND prompt_id = $2`,
			owner, promptID).Scan(&next); err != nil {
			return err
		}
		_, err := tx.Exec(ctx, `INSERT INTO prompts (owner_module, prompt_id, version, body, variables, sha256, active, author, comment)
			VALUES ($1,$2,$3,$4,$5,$6,false,$7,$8)`, owner, promptID, next, body, variables, sum[:], author, comment)
		if err != nil {
			return err
		}
		out = Version{OwnerModule: owner, PromptID: promptID, Version: next, Body: body, Variables: variables, SHA256: sum[:], Author: author, Comment: comment}
		return nil
	})
	return out, err
}

// Activate makes version current. ifMatch, when > 0, must equal the currently active version
// (412 version_mismatch). Concurrent activators: only one active row via partial unique index.
func (s *Store) Activate(ctx context.Context, owner, promptID string, version int, ifMatch int) error {
	return db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var cur *int
		err := tx.QueryRow(ctx, `SELECT version FROM prompts WHERE owner_module = $1 AND prompt_id = $2 AND active FOR UPDATE`,
			owner, promptID).Scan(&cur)
		if err != nil && !errors.Is(err, pgx.ErrNoRows) {
			return err
		}
		if ifMatch > 0 {
			if cur == nil || *cur != ifMatch {
				return ErrVersionConflict
			}
		}
		var exists bool
		if err := tx.QueryRow(ctx, `SELECT exists(SELECT 1 FROM prompts WHERE owner_module=$1 AND prompt_id=$2 AND version=$3)`,
			owner, promptID, version).Scan(&exists); err != nil {
			return err
		}
		if !exists {
			return ErrNotFound
		}
		if _, err := tx.Exec(ctx, `UPDATE prompts SET active = false WHERE owner_module = $1 AND prompt_id = $2 AND active`, owner, promptID); err != nil {
			return err
		}
		tag, err := tx.Exec(ctx, `UPDATE prompts SET active = true WHERE owner_module = $1 AND prompt_id = $2 AND version = $3`, owner, promptID, version)
		if err != nil {
			return err
		}
		if tag.RowsAffected() != 1 {
			return ErrNotFound
		}
		return nil
	})
}

// Active returns the active version or ErrNotFound.
func (s *Store) Active(ctx context.Context, owner, promptID string) (Version, error) {
	var v Version
	err := s.Pool.QueryRow(ctx, `SELECT owner_module, prompt_id, version, body, variables, sha256, active, author, coalesce(comment,'')
		FROM prompts WHERE owner_module = $1 AND prompt_id = $2 AND active`, owner, promptID).
		Scan(&v.OwnerModule, &v.PromptID, &v.Version, &v.Body, &v.Variables, &v.SHA256, &v.Active, &v.Author, &v.Comment)
	if errors.Is(err, pgx.ErrNoRows) {
		return Version{}, ErrNotFound
	}
	return v, err
}

// SnapshotActive returns {prompt_id, version, sha256, body} for every active prompt of the module.
func (s *Store) SnapshotActive(ctx context.Context, owner string) ([]map[string]any, error) {
	return snapshot(ctx, s.Pool, owner)
}

// SnapshotActiveTx is the same query on the caller's transaction (avoids pool deadlock while holding locks).
func (s *Store) SnapshotActiveTx(ctx context.Context, tx pgx.Tx, owner string) ([]map[string]any, error) {
	return snapshot(ctx, tx, owner)
}

type querier interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
}

func snapshot(ctx context.Context, q querier, owner string) ([]map[string]any, error) {
	rows, err := q.Query(ctx, `SELECT prompt_id, version, encode(sha256,'hex'), body FROM prompts WHERE owner_module = $1 AND active ORDER BY prompt_id`, owner)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []map[string]any
	for rows.Next() {
		var id, hex, body string
		var ver int
		if err := rows.Scan(&id, &ver, &hex, &body); err != nil {
			return nil, err
		}
		out = append(out, map[string]any{"prompt_id": id, "version": ver, "sha256": hex, "body": body})
	}
	return out, rows.Err()
}

// Render substitutes {{var}} placeholders. Unknown variables → ErrUnknownVar. No eval.
func Render(body string, vars map[string]string) (string, error) {
	var first error
	out := placeholderRE.ReplaceAllStringFunc(body, func(m string) string {
		name := placeholderRE.FindStringSubmatch(m)[1]
		v, ok := vars[name]
		if !ok {
			if first == nil {
				first = fmt.Errorf("%w: %s", ErrUnknownVar, name)
			}
			return m
		}
		return v
	})
	return out, first
}

func declaredVars(body string) []string {
	seen := map[string]bool{}
	var out []string
	for _, m := range placeholderRE.FindAllStringSubmatch(body, -1) {
		if !seen[m[1]] {
			seen[m[1]] = true
			out = append(out, m[1])
		}
	}
	return out
}
