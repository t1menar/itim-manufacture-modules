// Package settings stores versioned core/module settings (core-03 §3.10, core-04 §2.13).
package settings

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/t1menar/manufacture/core/internal/db"
)

var (
	ErrVersionConflict = errors.New("settings_version_conflict")
	ErrNotFound        = errors.New("not_found")
)

type Current struct {
	Owner     string
	Version   int
	Values    json.RawMessage
	Valid     bool
	CreatedAt string
}

type Store struct {
	Pool *pgxpool.Pool
}

func (s *Store) GetCore(ctx context.Context) (Current, error) {
	return s.getSystem(ctx, "core")
}

func (s *Store) getSystem(ctx context.Context, owner string) (Current, error) {
	var c Current
	err := s.Pool.QueryRow(ctx, `SELECT owner, version, values, valid, created_at::text FROM system_settings
		WHERE owner = $1 AND is_current`, owner).Scan(&c.Owner, &c.Version, &c.Values, &c.Valid, &c.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Current{}, ErrNotFound
	}
	return c, err
}

func (s *Store) GetModule(ctx context.Context, moduleID string) (Current, error) {
	var c Current
	err := s.Pool.QueryRow(ctx, `SELECT module_id, version, values, valid, created_at::text FROM module_settings
		WHERE module_id = $1 AND is_current`, moduleID).Scan(&c.Owner, &c.Version, &c.Values, &c.Valid, &c.CreatedAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return Current{}, ErrNotFound
	}
	return c, err
}

// PutCore appends a new version. base_version must equal the current version → else ErrVersionConflict (409).
func (s *Store) PutCore(ctx context.Context, values json.RawMessage, baseVersion int, author, comment string) (Current, error) {
	var out Current
	err := db.WithTx(ctx, s.Pool, func(tx pgx.Tx) error {
		var cur int
		err := tx.QueryRow(ctx, `SELECT version FROM system_settings WHERE owner = 'core' AND is_current FOR UPDATE`).Scan(&cur)
		if errors.Is(err, pgx.ErrNoRows) {
			cur = 0
		} else if err != nil {
			return err
		}
		if cur != baseVersion {
			return ErrVersionConflict
		}
		next := cur + 1
		if _, err := tx.Exec(ctx, `UPDATE system_settings SET is_current = false WHERE owner = 'core' AND is_current`); err != nil {
			return err
		}
		return tx.QueryRow(ctx, `INSERT INTO system_settings (owner, version, values, valid, comment, author, is_current)
			VALUES ('core', $1, $2, true, $3, $4, true)
			RETURNING owner, version, values, valid, created_at::text`, next, values, comment, author).
			Scan(&out.Owner, &out.Version, &out.Values, &out.Valid, &out.CreatedAt)
	})
	return out, err
}

// ReviewMaxRounds returns review.max_rounds from current core settings (default 3).
func (s *Store) ReviewMaxRounds(ctx context.Context) (int, error) {
	c, err := s.GetCore(ctx)
	if err != nil {
		return 3, err
	}
	var v struct {
		Review struct {
			MaxRounds int `json:"max_rounds"`
		} `json:"review"`
	}
	if err := json.Unmarshal(c.Values, &v); err != nil || v.Review.MaxRounds < 1 {
		return 3, nil
	}
	return v.Review.MaxRounds, nil
}

// MaxConcurrent returns scheduler.max_concurrent_productions (default 2).
func (s *Store) MaxConcurrent(ctx context.Context) (int, error) {
	c, err := s.GetCore(ctx)
	if err != nil {
		return 2, err
	}
	var v struct {
		Scheduler struct {
			MaxConcurrent int `json:"max_concurrent_productions"`
		} `json:"scheduler"`
	}
	if err := json.Unmarshal(c.Values, &v); err != nil || v.Scheduler.MaxConcurrent < 1 {
		return 2, nil
	}
	return v.Scheduler.MaxConcurrent, nil
}

// CallbackBaseURL returns callbacks.base_url.
func (s *Store) CallbackBaseURL(ctx context.Context) (string, error) {
	c, err := s.GetCore(ctx)
	if err != nil {
		return "http://core:8080", err
	}
	var v struct {
		Callbacks struct {
			BaseURL string `json:"base_url"`
		} `json:"callbacks"`
	}
	_ = json.Unmarshal(c.Values, &v)
	if v.Callbacks.BaseURL == "" {
		return "http://core:8080", nil
	}
	return v.Callbacks.BaseURL, nil
}

// InstagramLimits holds caption/hashtag caps from system_settings.instagram (D20-era defaults).
type InstagramLimits struct {
	MaxCaptionChars int
	MaxHashtags     int
}

func (s *Store) InstagramLimits(ctx context.Context) (InstagramLimits, error) {
	out := InstagramLimits{MaxCaptionChars: 2200, MaxHashtags: 30}
	cur, err := s.GetCore(ctx)
	if err != nil {
		return out, err
	}
	var wrap struct {
		Instagram *struct {
			MaxCaptionChars *int `json:"max_caption_chars"`
			MaxHashtags     *int `json:"max_hashtags"`
		} `json:"instagram"`
	}
	if err := json.Unmarshal(cur.Values, &wrap); err != nil {
		return out, err
	}
	if wrap.Instagram != nil {
		if wrap.Instagram.MaxCaptionChars != nil {
			out.MaxCaptionChars = *wrap.Instagram.MaxCaptionChars
		}
		if wrap.Instagram.MaxHashtags != nil {
			out.MaxHashtags = *wrap.Instagram.MaxHashtags
		}
	}
	return out, nil
}
