package itest

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/t1menar/manufacture/core/internal/messaging"
)

func TestPublishResultAppliesIntentsAndNotifies(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	account := uuid.Must(uuid.NewV7())
	e.exec(`INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled)
		VALUES ($1, 'itim', 'instagram', '@itim', true)`, account)
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{"output": videoStageOutput("pub"), "artifacts": []any{}})
	if res.StatusCode != 200 {
		t.Fatalf("video: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	var rev uuid.UUID
	var rf int
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'review'`).Scan(&rev, &rf); err != nil {
		t.Fatal(err)
	}
	res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
		"output": map[string]any{
			"decision": "approved", "reviewer": map[string]any{"telegram_user_id": 1},
			"decided_at": "2026-01-01T00:00:00Z", "round": 1,
		},
		"artifacts": []any{},
	})
	if res.StatusCode != 200 {
		t.Fatalf("approve: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()

	var pubJob uuid.UUID
	var pf int
	var intentID uuid.UUID
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'publish'`).Scan(&pubJob, &pf); err != nil {
		t.Fatal(err)
	}
	if err := e.pool.QueryRow(e.ctx, `SELECT id FROM publish_intents`).Scan(&intentID); err != nil {
		t.Fatal(err)
	}
	at := time.Now().UTC().Truncate(time.Second)
	output := map[string]any{
		"publications": []any{map[string]any{
			"platform": "instagram", "platform_account_id": account.String(), "handle": "@itim",
			"external_post_id": "fake_1", "url": "https://www.instagram.com/reel/fake_1/",
			"published_at": at.Format(time.RFC3339), "status": "published", "intent_id": intentID.String(),
		}},
	}
	res = e.postCallback(srv, "pubmod", "result", pubJob, pf, map[string]any{"output": output, "artifacts": []any{}})
	if res.StatusCode != 200 {
		t.Fatalf("publish result: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()

	if n := e.count(`SELECT count(*) FROM publish_intents WHERE id = $1 AND status = 'published' AND external_post_id = 'fake_1'`, intentID); n != 1 {
		t.Fatal("intent not published")
	}
	if n := e.count(`SELECT count(*) FROM variants WHERE status = 'published'`); n != 1 {
		t.Fatal("variant not published")
	}
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'notify.revmod'`); n != 1 {
		t.Fatalf("notify outbox=%d", e.count(`SELECT count(*) FROM outbox WHERE routing_key LIKE 'notify.%'`))
	}
	var msgID uuid.UUID
	var body []byte
	_ = e.pool.QueryRow(e.ctx, `SELECT message_id, body FROM outbox WHERE routing_key = 'notify.revmod'`).Scan(&msgID, &body)
	want := uuid.NewSHA1(uuid.NameSpaceOID, append(pubJob[:], []byte("notify")...))
	if msgID != want {
		t.Fatalf("message_id=%s want=%s", msgID, want)
	}
	var env messaging.Envelope
	if err := json.Unmarshal(body, &env); err != nil {
		t.Fatal(err)
	}
	if env.Type != "notify.requested" || env.MessageID != want {
		t.Fatalf("%+v", env)
	}
	var payload map[string]any
	if err := json.Unmarshal(env.Payload, &payload); err != nil {
		t.Fatal(err)
	}
	if payload["status"] != "published" {
		t.Fatalf("notify status=%v", payload["status"])
	}
	// Identical replay is a no-op (inbox dedup) — still one outbox row.
	res = e.postCallback(srv, "pubmod", "result", pubJob, pf, map[string]any{"output": output, "artifacts": []any{}})
	if res.StatusCode != 200 {
		t.Fatalf("dup: %d", res.StatusCode)
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'notify.revmod'`); n != 1 {
		t.Fatalf("dup notify outbox=%d", n)
	}
}

func TestPublishPartialNeedsAttention(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	a1, a2 := uuid.Must(uuid.NewV7()), uuid.Must(uuid.NewV7())
	e.exec(`INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled) VALUES
		($1, 'itim', 'instagram', '@a', true), ($2, 'itim', 'instagram', '@b', true)`, a1, a2)
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{"output": videoStageOutput("partial"), "artifacts": []any{}})
	res.Body.Close()
	var rev uuid.UUID
	var rf int
	_ = e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'review'`).Scan(&rev, &rf)
	res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
		"output": map[string]any{
			"decision": "approved", "reviewer": map[string]any{"telegram_user_id": 1},
			"decided_at": "2026-01-01T00:00:00Z", "round": 1,
		},
		"artifacts": []any{},
	})
	res.Body.Close()
	var pubJob uuid.UUID
	var pf int
	_ = e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'publish'`).Scan(&pubJob, &pf)
	var i1, i2 uuid.UUID
	rows, _ := e.pool.Query(e.ctx, `SELECT id, platform_account_id FROM publish_intents ORDER BY platform_account_id`)
	defer rows.Close()
	for rows.Next() {
		var id, acc uuid.UUID
		_ = rows.Scan(&id, &acc)
		if acc == a1 {
			i1 = id
		} else {
			i2 = id
		}
	}
	at := time.Now().UTC().Format(time.RFC3339)
	output := map[string]any{"publications": []any{
		map[string]any{
			"platform": "instagram", "platform_account_id": a1.String(), "status": "published",
			"external_post_id": "ok", "url": "https://www.instagram.com/reel/ok/", "published_at": at, "intent_id": i1.String(),
		},
		map[string]any{
			"platform": "instagram", "platform_account_id": a2.String(), "status": "failed",
			"error": "rate", "error_detail": map[string]any{"code": "rate_limited", "retryable": true},
			"intent_id": i2.String(),
		},
	}}
	res = e.postCallback(srv, "pubmod", "result", pubJob, pf, map[string]any{"output": output, "artifacts": []any{}})
	if res.StatusCode != 200 {
		t.Fatalf("publish: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM variants WHERE attention->>'reason' = 'publish_partial'`); n != 1 {
		t.Fatal("expected publish_partial attention")
	}
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE status = 'failed' AND last_error->>'code' = 'rate_limited'`); n != 1 {
		t.Fatal("failed intent last_error missing")
	}
	var body []byte
	_ = e.pool.QueryRow(e.ctx, `SELECT body FROM outbox WHERE routing_key = 'notify.revmod'`).Scan(&body)
	var env messaging.Envelope
	_ = json.Unmarshal(body, &env)
	var payload map[string]any
	_ = json.Unmarshal(env.Payload, &payload)
	if payload["status"] != "partial" {
		t.Fatalf("status=%v", payload["status"])
	}
}

func TestPublishFailBlockedMarksUnknown(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	account := uuid.Must(uuid.NewV7())
	e.exec(`INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled)
		VALUES ($1, 'itim', 'instagram', '@itim', true)`, account)
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{"output": videoStageOutput("blk"), "artifacts": []any{}})
	res.Body.Close()
	var rev uuid.UUID
	var rf int
	_ = e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'review'`).Scan(&rev, &rf)
	res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
		"output": map[string]any{
			"decision": "approved", "reviewer": map[string]any{"telegram_user_id": 1},
			"decided_at": "2026-01-01T00:00:00Z", "round": 1,
		},
		"artifacts": []any{},
	})
	res.Body.Close()
	var pubJob uuid.UUID
	var pf int
	_ = e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'publish'`).Scan(&pubJob, &pf)
	// Exhaust retries: max_attempts for publish is 3 — send blocked so no retry.
	res = e.postCallback(srv, "pubmod", "fail", pubJob, pf, map[string]any{
		"class": "blocked", "message": "instagram timeout unknown",
	})
	if res.StatusCode != 200 {
		t.Fatalf("fail: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE status = 'unknown'`); n != 1 {
		t.Fatal("intent not unknown")
	}
	if n := e.count(`SELECT count(*) FROM variants WHERE attention->>'reason' = 'publish_outcome_unknown'`); n != 1 {
		t.Fatal("attention missing")
	}
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'notify.revmod'`); n != 1 {
		t.Fatal("notify missing on fail")
	}
}
