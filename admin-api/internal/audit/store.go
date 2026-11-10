package audit

import (
	"context"
	"encoding/json"

	"github.com/jackc/pgx/v5/pgxpool"
)

type Store struct {
	Pool *pgxpool.Pool
}

type Row struct {
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

func (s *Store) List(ctx context.Context, limit int) ([]map[string]any, error) {
	if limit < 1 || limit > 200 {
		limit = 50
	}
	rows, err := s.Pool.Query(ctx, `SELECT id, at, actor, action, resource_type, resource_id, outcome,
		http_status, problem_code, request_id, details
		FROM audit_log ORDER BY id DESC LIMIT $1`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []map[string]any
	for rows.Next() {
		var id int64
		var at any
		var actor, action, outcome string
		var rtype, rid, code, reqID *string
		var status int
		var details []byte
		if err := rows.Scan(&id, &at, &actor, &action, &rtype, &rid, &outcome, &status, &code, &reqID, &details); err != nil {
			return nil, err
		}
		var d any
		_ = json.Unmarshal(details, &d)
		out = append(out, map[string]any{
			"id": id, "at": at, "actor": actor, "action": action,
			"resource_type": rtype, "resource_id": rid, "outcome": outcome,
			"http_status": status, "problem_code": code, "request_id": reqID, "details": d,
		})
	}
	if out == nil {
		out = []map[string]any{}
	}
	return out, rows.Err()
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
