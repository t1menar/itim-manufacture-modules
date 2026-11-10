package audit

import "time"

// Filter selects a page of audit rows. Empty strings and nil times mean "any".
type Filter struct {
	Actor, Action, Outcome string
	From, To               *time.Time
	Cursor                 int64 // exclusive upper bound on id; 0 means first page
	Limit                  int
}

// Page is a newest-first slice of audit rows plus a cursor for the next page.
type Page struct {
	Items      []map[string]any
	NextCursor string
}

func clampLimit(limit int) int {
	if limit < 1 || limit > 200 {
		return 50
	}
	return limit
}
