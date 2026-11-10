package audit

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Store struct {
	Pool *pgxpool.Pool
}

type Row struct {
	ID                                                                       int64
	At                                                                       time.Time
	Actor, Action, ResourceType, ResourceID, Outcome, ProblemCode, RequestID string
	HTTPStatus                                                               int
	Details                                                                  map[string]any
}

func (s *Store) Write(ctx context.Context, row Row) error {
	if s == nil || s.Pool == nil {
		return nil
	}
	if row.Details == nil {
		row.Details = map[string]any{}
	}
	raw, _ := json.Marshal(mask(row.Details))
	_, err := s.Pool.Exec(ctx, `INSERT INTO audit_log
		(actor, action, resource_type, resource_id, outcome, http_status, problem_code, request_id, details)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)`,
		row.Actor, row.Action, nullEmpty(row.ResourceType), nullEmpty(row.ResourceID),
		row.Outcome, row.HTTPStatus, nullEmpty(row.ProblemCode), nullEmpty(row.RequestID), raw)
	return err
}

func (s *Store) List(ctx context.Context, f Filter) (Page, error) {
	limit := clampLimit(f.Limit)
	var b strings.Builder
	b.WriteString(`SELECT id, at, actor, action, resource_type, resource_id, outcome,
		http_status, problem_code, request_id, details
		FROM audit_log WHERE 1=1`)
	args := make([]any, 0, 8)
	n := 1
	add := func(clause string, v any) {
		b.WriteString(" AND ")
		b.WriteString(fmt.Sprintf(clause, n))
		args = append(args, v)
		n++
	}
	if f.Actor != "" {
		add("actor = $%d", f.Actor)
	}
	if f.Action != "" {
		add("action = $%d", f.Action)
	}
	if f.Outcome != "" {
		add("outcome = $%d", f.Outcome)
	}
	if f.From != nil {
		add("at >= $%d", *f.From)
	}
	if f.To != nil {
		add("at <= $%d", *f.To)
	}
	if f.Cursor > 0 {
		add("id < $%d", f.Cursor)
	}
	b.WriteString(fmt.Sprintf(" ORDER BY id DESC LIMIT $%d", n))
	args = append(args, limit+1)

	rows, err := s.Pool.Query(ctx, b.String(), args...)
	if err != nil {
		return Page{}, err
	}
	defer rows.Close()
	var out []map[string]any
	for rows.Next() {
		var id int64
		var at time.Time
		var actor, action, outcome string
		var rtype, rid, code, reqID *string
		var status int
		var details []byte
		if err := rows.Scan(&id, &at, &actor, &action, &rtype, &rid, &outcome, &status, &code, &reqID, &details); err != nil {
			return Page{}, err
		}
		var d any
		_ = json.Unmarshal(details, &d)
		out = append(out, map[string]any{
			"id": id, "at": at.UTC().Format(time.RFC3339Nano), "actor": actor, "action": action,
			"resource_type": rtype, "resource_id": rid, "outcome": outcome,
			"http_status": status, "problem_code": code, "request_id": reqID, "details": mask(d),
		})
	}
	if err := rows.Err(); err != nil {
		return Page{}, err
	}
	if out == nil {
		out = []map[string]any{}
	}
	page := Page{Items: out}
	if len(out) > limit {
		page.Items = out[:limit]
		page.NextCursor = strconv.FormatInt(out[limit-1]["id"].(int64), 10)
	}
	return page, nil
}

func nullEmpty(s string) any {
	if s == "" {
		return nil
	}
	return s
}

var secretKeys = map[string]struct{}{
	"password": {}, "new_password": {}, "current_password": {}, "value": {}, "secret": {},
	"token": {}, "key": {}, "code": {}, "access_token": {}, "authorization": {},
	"oauth_token": {}, "api_key": {}, "claude_oauth_token": {}, "anthropic_api_key": {},
}

func mask(v any) any {
	switch t := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(t))
		for k, val := range t {
			if _, ok := secretKeys[k]; ok {
				out[k] = "***"
				continue
			}
			out[k] = mask(val)
		}
		return out
	case []any:
		out := make([]any, len(t))
		for i, val := range t {
			out[i] = mask(val)
		}
		return out
	default:
		return t
	}
}
