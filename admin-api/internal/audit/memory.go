package audit

import (
	"context"
	"sync"
)

// Memory is an in-process audit sink for tests.
type Memory struct {
	mu   sync.Mutex
	rows []Row
}

func (m *Memory) Write(_ context.Context, row Row) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.rows = append(append([]Row{}, m.rows...), row)
	return nil
}

func (m *Memory) List(_ context.Context, limit int) ([]map[string]any, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if limit < 1 || limit > 200 {
		limit = 50
	}
	start := 0
	if n := len(m.rows); n > limit {
		start = n - limit
	}
	out := make([]map[string]any, 0, len(m.rows)-start)
	for i := len(m.rows) - 1; i >= start; i-- {
		row := m.rows[i]
		out = append(out, map[string]any{
			"actor": row.Actor, "action": row.Action,
			"resource_type": row.ResourceType, "resource_id": row.ResourceID,
			"outcome": row.Outcome, "details": row.Details,
		})
	}
	return out, nil
}

func (m *Memory) Rows() []Row {
	m.mu.Lock()
	defer m.mu.Unlock()
	out := make([]Row, len(m.rows))
	copy(out, m.rows)
	return out
}
