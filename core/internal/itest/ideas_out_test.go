package itest

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/google/uuid"
	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/t1menar/manufacture/core/internal/messaging"
)

func TestIdeaReadyOverAMQPDuplicateAndDone(t *testing.T) {
	e := setup(t)
	const id, rev int64 = 4242, 3
	payload, _ := json.Marshal(map[string]any{
		"idea_ref": map[string]any{"id": id, "rev": rev},
		"language": "en", "pipeline_id": nil, "priority": 5,
	})
	msgID := messaging.IdeaReadyMessageID(id, int(rev))
	body, _ := json.Marshal(messaging.Envelope{
		MessageID: msgID, Type: "idea.ready", SchemaVersion: 1, OccurredAt: time.Now().UTC(),
		Producer: "module:video", Payload: payload,
	})

	publishIdea := func() {
		e.t.Helper()
		ch, err := e.conn.Channel()
		if err != nil {
			t.Fatal(err)
		}
		defer ch.Close()
		if err := ch.Confirm(false); err != nil {
			t.Fatal(err)
		}
		dc, err := ch.PublishWithDeferredConfirmWithContext(e.ctx, e.topo.Events(), "idea.ready", true, false,
			amqp.Publishing{MessageId: msgID.String(), DeliveryMode: amqp.Persistent, ContentType: "application/json", Body: body})
		if err != nil {
			t.Fatal(err)
		}
		if ok, err := dc.WaitContext(e.ctx); !ok || err != nil {
			t.Fatalf("confirm: %v", err)
		}
	}

	publishIdea()
	publishIdea() // duplicate delivery
	c := e.consumer()
	if err := e.consumeUntil(c, func() bool {
		return e.count(`SELECT count(*) FROM productions WHERE idea_ref = $1`, messaging.FormatIdeaRef(id, int(rev))) == 1
	}); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM productions`); n != 1 {
		t.Fatalf("productions=%d", n)
	}
	if n := e.count(`SELECT count(*) FROM jobs`); n != 1 {
		t.Fatalf("jobs=%d", n)
	}

	// Finish pipeline enough to emit idea.done: mark production done via complete path.
	// Drive video→review approve→publish published using existing helpers pattern.
	var jobID uuid.UUID
	var fence int
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs`).Scan(&jobID, &fence); err != nil {
		t.Fatal(err)
	}
	// Seed platform account for publish intents (same as other tests).
	account := uuid.Must(uuid.NewV7())
	e.exec(`INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled)
		VALUES ($1, 'itim', 'instagram', '@itim', true)`, account)

	apply := func(module, stage string, output any) {
		t.Helper()
		e.moduleEvent(module, "job.succeeded", jobID, fence, map[string]any{"output": output})
		if err := e.consumeUntil(e.consumer(), func() bool {
			return e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'succeeded'`, jobID) == 1
		}); err != nil {
			t.Fatal(err)
		}
		// next job if any
		_ = e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE status IN ('queued','dispatched','running') ORDER BY created_at DESC LIMIT 1`).Scan(&jobID, &fence)
	}
	apply("vidmod", "video", videoStageOutput("amqp"))
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'review' ORDER BY created_at DESC LIMIT 1`).Scan(&jobID, &fence); err != nil {
		t.Fatal(err)
	}
	apply("revmod", "review", map[string]any{
		"decision": "approved", "reviewer": map[string]any{"telegram_user_id": 1},
		"decided_at": "2026-01-01T00:00:00Z", "round": 1,
	})
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'publish' ORDER BY created_at DESC LIMIT 1`).Scan(&jobID, &fence); err != nil {
		t.Fatal(err)
	}
	apply("pubmod", "publish", map[string]any{"publications": []any{map[string]any{
		"platform": "instagram", "platform_account_id": account.String(), "handle": "@itim",
		"external_post_id": "1", "url": "https://www.instagram.com/reel/x/",
		"published_at": "2026-11-09T12:00:00Z", "status": "published",
	}}})

	if n := e.count(`SELECT count(*) FROM productions WHERE status = 'done'`); n != 1 {
		t.Fatal("production not done")
	}
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'idea.done'`); n != 1 {
		t.Fatal("idea.done missing")
	}
	// job input carries idea_ref, not text
	var req []byte
	if err := e.pool.QueryRow(e.ctx, `SELECT request FROM jobs WHERE stage_id = 'video'`).Scan(&req); err != nil {
		t.Fatal(err)
	}
	var parsed map[string]any
	_ = json.Unmarshal(req, &parsed)
	input, _ := parsed["input"].(map[string]any)
	if _, ok := input["idea"]; ok {
		t.Fatal("legacy input.idea must not be present")
	}
	ref, _ := input["idea_ref"].(map[string]any)
	if int(ref["id"].(float64)) != int(id) || int(ref["rev"].(float64)) != int(rev) {
		t.Fatalf("idea_ref=%v", ref)
	}
	chs, _ := input["channels"].([]any)
	if len(chs) == 0 {
		t.Fatal("job input.channels must be non-empty for module-video")
	}
	ch0, _ := chs[0].(map[string]any)
	if ch0["id"] != "itim" || ch0["language"] != "en" {
		t.Fatalf("channels[0]=%v", ch0)
	}
}
