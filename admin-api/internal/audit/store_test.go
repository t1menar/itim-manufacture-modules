package audit

import (
	"context"
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/t1menar/manufacture/admin-api/internal/db"
)

func TestMaskRedactsSecretKeysAndLeavesOthers(t *testing.T) {
	in := map[string]any{
		"actor":        "local:admin",
		"key":          "telegram.bot_token",
		"value":        "dummy-telegram-bot-token-not-real",
		"access_token": "dummy-ig-token-not-a-real-secret",
		"note":         "ok",
	}
	out, ok := mask(in).(map[string]any)
	if !ok {
		t.Fatalf("mask type %T", mask(in))
	}
	if out["value"] != "***" || out["access_token"] != "***" || out["key"] != "***" {
		t.Fatalf("expected secret keys masked, got %#v", out)
	}
	if out["actor"] != "local:admin" || out["note"] != "ok" {
		t.Fatalf("non-secret fields changed: %#v", out)
	}
	raw, _ := json.Marshal(out)
	if strings.Contains(string(raw), "dummy-") {
		t.Fatalf("dummy secret leaked after mask: %s", raw)
	}
}

func TestMemoryListFiltersAndCursor(t *testing.T) {
	mem := &Memory{}
	t1 := time.Date(2026, 11, 10, 8, 0, 0, 0, time.UTC)
	t2 := t1.Add(time.Hour)
	t3 := t2.Add(time.Hour)
	_ = mem.Write(context.Background(), Row{Actor: "local:admin", Action: "audit.read", Outcome: "ok", At: t1})
	_ = mem.Write(context.Background(), Row{Actor: "local:admin", Action: "review.secrets.write", Outcome: "ok", ResourceID: "telegram.bot_token", At: t2, Details: map[string]any{"value": "dummy-telegram-bot-token-not-real"}})
	_ = mem.Write(context.Background(), Row{Actor: "other", Action: "ideas.read", Outcome: "error", At: t3})

	page, err := mem.List(context.Background(), Filter{Actor: "local:admin", Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 2 {
		t.Fatalf("actor filter: got %d", len(page.Items))
	}

	page, err = mem.List(context.Background(), Filter{Action: "ideas.read", Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 || page.Items[0]["actor"] != "other" {
		t.Fatalf("action filter: %#v", page.Items)
	}

	page, err = mem.List(context.Background(), Filter{Outcome: "error", Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 {
		t.Fatalf("outcome filter: got %d", len(page.Items))
	}

	from := t2
	to := t2
	page, err = mem.List(context.Background(), Filter{From: &from, To: &to, Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 || page.Items[0]["action"] != "review.secrets.write" {
		t.Fatalf("time filter: %#v", page.Items)
	}

	page, err = mem.List(context.Background(), Filter{Limit: 2})
	if err != nil {
		t.Fatal(err)
	}
	if page.NextCursor == "" || len(page.Items) != 2 {
		t.Fatalf("expected next cursor, got items=%d cursor=%q", len(page.Items), page.NextCursor)
	}
	cursor, _ := strconv.ParseInt(page.NextCursor, 10, 64)
	page2, err := mem.List(context.Background(), Filter{Limit: 2, Cursor: cursor})
	if err != nil {
		t.Fatal(err)
	}
	if len(page2.Items) != 1 {
		t.Fatalf("second page: got %d", len(page2.Items))
	}
	raw, _ := json.Marshal(page.Items)
	if strings.Contains(string(raw), "dummy-") {
		t.Fatalf("secret leaked in list: %s", raw)
	}
}

func TestStoreListFilters(t *testing.T) {
	url := os.Getenv("MF_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("MF_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	pool, err := db.Open(ctx, url)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(pool.Close)
	if err := db.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}
	store := &Store{Pool: pool}
	actor := "test:audit-filter"
	_, _ = pool.Exec(ctx, `DELETE FROM audit_log WHERE actor = $1`, actor)
	t1 := time.Date(2026, 11, 10, 8, 0, 0, 0, time.UTC)
	t2 := t1.Add(time.Hour)
	if err := store.Write(ctx, Row{Actor: actor, Action: "audit.read", Outcome: "ok"}); err != nil {
		t.Fatal(err)
	}
	if err := store.Write(ctx, Row{Actor: actor, Action: "review.secrets.write", Outcome: "ok", ResourceType: "secrets", ResourceID: "telegram.bot_token", Details: map[string]any{"value": "dummy-telegram-bot-token-not-real"}}); err != nil {
		t.Fatal(err)
	}
	// stamp times after insert so from/to is deterministic
	_, err = pool.Exec(ctx, `UPDATE audit_log SET at = $2 WHERE actor = $1 AND action = 'audit.read'`, actor, t1)
	if err != nil {
		t.Fatal(err)
	}
	_, err = pool.Exec(ctx, `UPDATE audit_log SET at = $2 WHERE actor = $1 AND action = 'review.secrets.write'`, actor, t2)
	if err != nil {
		t.Fatal(err)
	}

	page, err := store.List(ctx, Filter{Actor: actor, Action: "review.secrets.write", Limit: 10})
	if err != nil {
		t.Fatal(err)
	}
	if len(page.Items) != 1 || page.Items[0]["action"] != "review.secrets.write" {
		t.Fatalf("store action filter: %#v", page.Items)
	}
	raw, _ := json.Marshal(page.Items)
	if strings.Contains(string(raw), "dummy-") {
		t.Fatalf("secret leaked from store list: %s", raw)
	}
	if got, _ := page.Items[0]["details"].(map[string]any); got == nil || got["value"] != "***" {
		t.Fatalf("expected masked details, got %#v", page.Items[0]["details"])
	}

	page, err = store.List(ctx, Filter{Actor: actor, Limit: 1})
	if err != nil {
		t.Fatal(err)
	}
	if page.NextCursor == "" || len(page.Items) != 1 {
		t.Fatalf("expected cursor, got %#v", page)
	}
	cursor, _ := strconv.ParseInt(page.NextCursor, 10, 64)
	page2, err := store.List(ctx, Filter{Actor: actor, Limit: 1, Cursor: cursor})
	if err != nil {
		t.Fatal(err)
	}
	if len(page2.Items) != 1 || page2.Items[0]["id"] == page.Items[0]["id"] {
		t.Fatalf("expected distinct second page, first=%v second=%v", page.Items, page2.Items)
	}
}
