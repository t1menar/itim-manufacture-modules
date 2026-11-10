package audit

import (
	"context"
	"strconv"
	"sync"
	"time"
)

// Memory is an in-process audit sink for tests.
type Memory struct {
	mu   sync.Mutex
	rows []Row
	seq  int64
}

func (m *Memory) Write(_ context.Context, row Row) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if row.ID == 0 {
		m.seq++
		row.ID = m.seq
	} else if row.ID > m.seq {
		m.seq = row.ID
	}
	if row.At.IsZero() {
		row.At = time.Now().UTC()
	}
	m.rows = append(append([]Row{}, m.rows...), row)
	return nil
}

func (m *Memory) List(_ context.Context, f Filter) (Page, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	limit := clampLimit(f.Limit)
	var matched []Row
	for i := len(m.rows) - 1; i >= 0; i-- {
		row := m.rows[i]
		if f.Actor != "" && row.Actor != f.Actor {
			continue
		}
		if f.Action != "" && row.Action != f.Action {
			continue
		}
		if f.Outcome != "" && row.Outcome != f.Outcome {
			continue
		}
		if f.From != nil && row.At.Before(*f.From) {
			continue
		}
		if f.To != nil && row.At.After(*f.To) {
			continue
		}
		if f.Cursor > 0 && row.ID >= f.Cursor {
			continue
		}
		matched = append(matched, row)
	}
	page := Page{Items: make([]map[string]any, 0, limit)}
	for i, row := range matched {
		if i >= limit {
			page.NextCursor = strconv.FormatInt(matched[limit-1].ID, 10)
			break
		}
		page.Items = append(page.Items, map[string]any{
			"id": row.ID, "at": row.At.UTC().Format(time.RFC3339Nano),
			"actor": row.Actor, "action": row.Action,
			"resource_type": row.ResourceType, "resource_id": row.ResourceID,
			"outcome": row.Outcome, "http_status": row.HTTPStatus,
			"problem_code": row.ProblemCode, "request_id": row.RequestID,
			"details": mask(row.Details),
		})
	}
	return page, nil
}

func (m *Memory) Rows() []Row {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]Row, len(m.rows))
	copy(out, m.rows)
	return out
}
