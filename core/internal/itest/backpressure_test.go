package itest

import (
	"context"
	"encoding/json"
	"errors"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/messaging"
)

// publishIdeaReady publishes idea.ready over AMQP as module-video does (stable message id).
func (e *env) publishIdeaReady(id int64, rev int, priority int) uuid.UUID {
	e.t.Helper()
	payload, _ := json.Marshal(map[string]any{
		"idea_ref": map[string]any{"id": id, "rev": rev}, "language": "en", "pipeline_id": nil, "priority": priority,
	})
	msgID := messaging.IdeaReadyMessageID(id, rev)
	body, _ := json.Marshal(messaging.Envelope{
		MessageID: msgID, Type: "idea.ready", SchemaVersion: 1, OccurredAt: time.Now().UTC(),
		Producer: "module:video", Payload: payload,
	})
	e.publishRaw(msgID.String(), body)
	return msgID
}

// B5: more idea.ready than max_concurrent_productions → the extra ideas are parked (acked, not
// dead-lettered), other events keep flowing, and every idea starts once slots free up.
func TestIdeaReadyBackpressureParksAndStartsAll(t *testing.T) {
	e := setup(t)
	const ideas = 5 // max_concurrent_productions defaults to 2
	base := atomic.AddInt64(&testIdeaSeq, 100)
	for i := range ideas {
		e.publishIdeaReady(base+int64(i), 1, 0)
	}
	if err := e.consumeUntil(e.consumer(), func() bool {
		return e.count(`SELECT count(*) FROM inbox WHERE type = 'idea.ready'`) == ideas
	}); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM productions WHERE status = 'running'`); n != 2 {
		t.Fatalf("running productions = %d, want 2 (the limit)", n)
	}
	if n := e.count(`SELECT count(*) FROM pending_ideas`); n != ideas-2 {
		t.Fatalf("parked = %d, want %d", n, ideas-2)
	}
	if n := e.queueLen(e.topo.CoreEvents() + ".dlq"); n != 0 {
		t.Fatalf("dlq = %d, idea.ready must not be dead-lettered", n)
	}

	// Duplicate delivery of a parked idea is a no-op (inbox dedup on message id).
	e.publishIdeaReady(base+4, 1, 0)
	// Other events are processed while ideas wait: progress on a running job.
	var job uuid.UUID
	var fence int
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs ORDER BY created_at LIMIT 1`).Scan(&job, &fence); err != nil {
		t.Fatal(err)
	}
	e.moduleEvent("vidmod", "job.progress", job, fence, map[string]any{"percent": 10})
	if err := e.consumeUntil(e.consumer(), func() bool {
		return e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'running'`, job) == 1 && e.queueLen(e.topo.CoreEvents()) == 0
	}); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM pending_ideas`); n != ideas-2 {
		t.Fatalf("duplicate changed parked ideas: %d", n)
	}

	// Free the slots: each finished production lets the scheduler start the next parked idea.
	for round := 0; round < ideas && e.count(`SELECT count(*) FROM pending_ideas`) > 0; round++ {
		e.exec(`UPDATE productions SET status = 'done', finished_at = now() WHERE status = 'running'`)
		if _, err := e.eng.StartParked(e.ctx); err != nil {
			t.Fatal(err)
		}
		if n := e.count(`SELECT count(*) FROM productions WHERE status = 'running'`); n > 2 {
			t.Fatalf("running = %d exceeds the limit", n)
		}
	}
	if n := e.count(`SELECT count(*) FROM productions`); n != ideas {
		t.Fatalf("productions = %d, want %d (every idea started)", n, ideas)
	}
	if n := e.count(`SELECT count(*) FROM pending_ideas`); n != 0 {
		t.Fatalf("parked left = %d", n)
	}
	if n := e.queueLen(e.topo.CoreEvents() + ".dlq"); n != 0 {
		t.Fatalf("dlq = %d", n)
	}
	// Each started idea told module-video it is in production.
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'idea.in_production'`); n != ideas {
		t.Fatalf("idea.in_production = %d", n)
	}
}

// Parked ideas start in priority order, then arrival order; a new idea does not overtake them.
func TestParkedIdeasKeepOrder(t *testing.T) {
	e := setup(t)
	base := atomic.AddInt64(&testIdeaSeq, 100)
	e.ideaReady(base, 1)
	e.ideaReady(base+1, 1)
	for i, prio := range []int{0, 9, 0} {
		if err := e.applyIdeaReadyPrio(base+2+int64(i), 1, prio); err != nil {
			t.Fatal(err)
		}
	}
	e.exec(`UPDATE productions SET status = 'done', finished_at = now() WHERE idea_id = $1`, base)
	// A slot is free, but parked ideas exist: a new idea is parked and the oldest high-priority starts.
	if err := e.applyIdeaReadyPrio(base+9, 1, 0); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM productions WHERE idea_id = $1`, base+3); n != 1 {
		t.Fatal("priority 9 idea should start first")
	}
	e.exec(`UPDATE productions SET status = 'done', finished_at = now() WHERE status = 'running'`)
	if _, err := e.eng.StartParked(e.ctx); err != nil {
		t.Fatal(err)
	}
	if e.count(`SELECT count(*) FROM productions WHERE idea_id = $1`, base+2) != 1 ||
		e.count(`SELECT count(*) FROM productions WHERE idea_id = $1`, base+4) != 1 {
		t.Fatal("arrival order not kept")
	}
	if e.count(`SELECT count(*) FROM pending_ideas WHERE idea_id = $1`, base+9) != 1 {
		t.Fatal("the new idea must wait behind the parked ones")
	}
}

// A failing message waits for its requeue on a timer, not by blocking the consumer.
func TestFailingMessageDoesNotBlockOthers(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	bad := e.moduleEvent("vidmod", "job.progress", job, fence, map[string]any{"percent": 1})
	good := e.moduleEvent("vidmod", "job.progress", job, fence, map[string]any{"percent": 2})
	c := e.consumer()
	c.RetryDelay = func(int64) time.Duration { return 3 * time.Second }
	inner := c.Handler
	c.Handler = func(ctx context.Context, tx pgx.Tx, env messaging.Envelope) (string, error) {
		if env.MessageID == bad {
			return "", errors.New("transient")
		}
		return inner(ctx, tx, env)
	}
	start := time.Now()
	if err := e.consumeUntil(c, func() bool {
		return e.count(`SELECT count(*) FROM inbox WHERE message_id = $1`, good) == 1
	}); err != nil {
		t.Fatal(err)
	}
	if d := time.Since(start); d > 2*time.Second {
		t.Fatalf("good message waited %s behind the failing one", d)
	}
}
