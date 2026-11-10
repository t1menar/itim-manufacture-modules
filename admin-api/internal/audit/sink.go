package audit

import "context"

// Sink records admin actions. Implementations must never persist secret values.
type Sink interface {
	Write(ctx context.Context, row Row) error
	List(ctx context.Context, limit int) ([]map[string]any, error)
}
