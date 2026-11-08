package itest

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/httpapi"
	"github.com/t1menar/manufacture/core/internal/messaging"
)

func TestDuplicateScheduleCreatesOneProduction(t *testing.T) {
	e := setup(t)
	e.idea("one idea")
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := e.eng.Tick(e.ctx); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if _, err := e.eng.Tick(e.ctx); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM productions`); n != 1 {
		t.Fatalf("productions = %d, want 1", n)
	}
	if n := e.count(`SELECT count(*) FROM jobs`); n != 1 {
		t.Fatalf("jobs = %d, want 1", n)
	}
	if n := e.count(`SELECT count(*) FROM outbox`); n != 1 {
		t.Fatalf("outbox = %d, want 1", n)
	}
	// State and outbox are one transaction: the job request and the outbox body agree.
	if n := e.count(`SELECT count(*) FROM outbox o JOIN jobs j ON (o.body->'job'->>'job_id')::uuid = j.id AND (o.body->'job'->>'fence')::int = j.fence`); n != 1 {
		t.Fatal("outbox row does not match the job")
	}
}

func TestDBRejectsSecondRunningProductionAndSecondLiveJob(t *testing.T) {
	e := setup(t)
	e.startedJob()
	_, err := e.pool.Exec(e.ctx, `INSERT INTO productions (id, idea_id, run_no, pipeline_id, pipeline_snapshot, language, status)
		SELECT gen_random_uuid(), idea_id, run_no + 1, pipeline_id, pipeline_snapshot, language, 'running' FROM productions`)
	if !db.IsUniqueViolation(err, "productions_live_uq") {
		t.Fatalf("want productions_live_uq violation, got %v", err)
	}
	_, err = e.pool.Exec(e.ctx, `INSERT INTO jobs (id, production_id, stage_id, position, attempt, chain_id, try, max_attempts, timeout_s, status)
		SELECT gen_random_uuid(), production_id, stage_id, position, attempt + 1, gen_random_uuid(), 1, max_attempts, timeout_s, 'queued' FROM jobs`)
	if !db.IsUniqueViolation(err, "jobs_production_live_uq") {
		t.Fatalf("want jobs_production_live_uq violation, got %v", err)
	}
}

func TestTwoWorkersRaceOnOneVariant(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	e.moduleEvent("vidmod", "job.failed", job, fence, map[string]any{"class": "blocked", "message": "needs a human"})
	if err := e.consumeUntil(e.consumer(), func() bool {
		return e.count(`SELECT count(*) FROM variants WHERE status = 'needs_attention'`) == 1
	}); err != nil {
		t.Fatal(err)
	}
	var variant uuid.UUID
	_ = e.pool.QueryRow(e.ctx, `SELECT id FROM variants`).Scan(&variant)

	var ok, invalid atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			err := db.WithTx(e.ctx, e.pool, func(tx pgx.Tx) error {
				_, err := e.eng.RetryVariant(e.ctx, tx, variant)
				return err
			})
			switch {
			case err == nil:
				ok.Add(1)
			case errors.Is(err, engine.ErrInvalidState):
				invalid.Add(1)
			default:
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if ok.Load() != 1 || invalid.Load() != 1 {
		t.Fatalf("ok=%d invalid=%d, want 1/1", ok.Load(), invalid.Load())
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE status IN ('queued','dispatching','dispatched','running')`); n != 1 {
		t.Fatalf("live jobs = %d, want 1", n)
	}
}

func TestHappyPathThroughBroker(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	// relay publishes job.requested to the module queue
	if n, err := e.relay("w1").RunOnce(e.ctx, e.conn); err != nil || n != 1 {
		t.Fatalf("relay: n=%d err=%v", n, err)
	}
	d := e.get(e.topo.ModuleQueue("vidmod"))
	var outboxID string
	_ = e.pool.QueryRow(e.ctx, `SELECT message_id::text FROM outbox WHERE status = 'sent'`).Scan(&outboxID)
	if d.MessageId != outboxID {
		t.Fatalf("AMQP message_id %q != outbox %q", d.MessageId, outboxID)
	}
	c := e.consumer()
	step := func(module, stage string) {
		var id uuid.UUID
		var f int
		if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = $1 AND status = 'queued'`, stage).Scan(&id, &f); err != nil {
			t.Fatalf("no queued %s job: %v", stage, err)
		}
		e.moduleEvent(module, "job.progress", id, f, map[string]any{"percent": 50})
		e.moduleEvent(module, "job.succeeded", id, f, map[string]any{"output": map[string]any{"ok": true}})
		if err := e.consumeUntil(c, func() bool {
			return e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'succeeded'`, id) == 1
		}); err != nil {
			t.Fatalf("%s: %v", stage, err)
		}
	}
	_ = job
	_ = fence
	step("vidmod", "video")
	step("revmod", "review")
	step("pubmod", "publish")
	if n := e.count(`SELECT count(*) FROM productions WHERE status = 'done'`); n != 1 {
		t.Fatal("production not done")
	}
	if n := e.count(`SELECT count(*) FROM ideas WHERE status = 'done'`); n != 1 {
		t.Fatal("idea not done")
	}
	if n := e.count(`SELECT count(*) FROM variants WHERE status = 'published'`); n != 1 {
		t.Fatal("variant not published")
	}
}

func TestCrashAfterConfirmResendsSameMessageID(t *testing.T) {
	e := setup(t)
	e.startedJob()
	r1 := e.relay("w1")
	r1.AfterConfirm = func(uuid.UUID) error { return errors.New("crash") }
	if _, err := r1.RunOnce(e.ctx, e.conn); err == nil {
		t.Fatal("expected simulated crash")
	}
	if n := e.count(`SELECT count(*) FROM outbox WHERE status = 'pending'`); n != 1 {
		t.Fatal("row must stay pending after a crash before mark-sent")
	}
	// a second relay cannot steal the row while the lease is valid ...
	if n, _ := e.relay("w2").RunOnce(e.ctx, e.conn); n != 0 {
		t.Fatal("lease not respected")
	}
	time.Sleep(2100 * time.Millisecond) // ... but takes it over once the lease expired (restart recovery)
	if n, err := e.relay("w2").RunOnce(e.ctx, e.conn); err != nil || n != 1 {
		t.Fatalf("recovery: n=%d err=%v", n, err)
	}
	q := e.topo.ModuleQueue("vidmod")
	e.waitQueue(q, 2)
	a, b := e.get(q), e.get(q)
	if a.MessageId != b.MessageId || a.MessageId == "" {
		t.Fatalf("message ids differ: %q %q", a.MessageId, b.MessageId)
	}
	var fa, fb messaging.Envelope
	_ = json.Unmarshal(a.Body, &fa)
	_ = json.Unmarshal(b.Body, &fb)
	if fa.Job.Fence != fb.Job.Fence {
		t.Fatal("resend changed the fence")
	}
}

func TestDuplicateEventAppliedOnce(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	id := uuid.Must(uuid.NewV7())
	var prod uuid.UUID
	_ = e.pool.QueryRow(e.ctx, `SELECT production_id FROM jobs`).Scan(&prod)
	body := mustJSON(messaging.Envelope{MessageID: id, Type: "job.succeeded", SchemaVersion: 1, OccurredAt: time.Now().UTC(),
		Producer: "module:vidmod", ProductionID: &prod, Job: &messaging.JobRef{JobID: job, Fence: fence},
		Payload: json.RawMessage(`{"output":{"ok":true}}`)})
	e.publishRaw(id.String(), body)
	e.publishRaw(id.String(), body)
	if err := e.consumeUntil(e.consumer(), func() bool { return e.queueLen(e.topo.CoreEvents()) == 0 }); err != nil {
		t.Fatal(err)
	}
	time.Sleep(200 * time.Millisecond)
	if n := e.count(`SELECT count(*) FROM events WHERE type = 'job.succeeded'`); n != 1 {
		t.Fatalf("job.succeeded events = %d", n)
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE stage_id = 'review'`); n != 1 {
		t.Fatalf("review jobs = %d, want 1", n)
	}
}

func TestConsumerCrashBeforeCommitRedelivers(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	e.moduleEvent("vidmod", "job.succeeded", job, fence, map[string]any{"output": map[string]any{}})
	c := e.consumer()
	c.BeforeCommit = func(messaging.Envelope) error { return errors.New("crash") }
	if err := c.Consume(e.ctx, e.conn); err == nil {
		t.Fatal("expected crash")
	}
	if n := e.count(`SELECT count(*) FROM inbox`); n != 0 {
		t.Fatal("rolled-back message left an inbox row")
	}
	if err := e.consumeUntil(e.consumer(), func() bool { return e.count(`SELECT count(*) FROM inbox`) == 1 }); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE stage_id = 'review'`); n != 1 {
		t.Fatal("redelivery not applied")
	}
}

func TestConsumerCrashAfterCommitBeforeAckDedups(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	e.moduleEvent("vidmod", "job.succeeded", job, fence, map[string]any{"output": map[string]any{}})
	c := e.consumer()
	c.AfterCommit = func(messaging.Envelope) error { return errors.New("crash") }
	if err := c.Consume(e.ctx, e.conn); err == nil {
		t.Fatal("expected crash")
	}
	e.waitQueue(e.topo.CoreEvents(), 1) // not acked: back in the queue
	if err := e.consumeUntil(e.consumer(), func() bool { return e.queueLen(e.topo.CoreEvents()) == 0 }); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE stage_id = 'review'`); n != 1 {
		t.Fatalf("review jobs = %d, want 1", n)
	}
	if n := e.count(`SELECT count(*) FROM events WHERE type = 'job.succeeded'`); n != 1 {
		t.Fatal("effect applied twice")
	}
}

func TestTakeoverFencesStaleEvents(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	e.exec(`UPDATE modules SET active = false WHERE id = 'vidmod'`)
	e.exec(`UPDATE modules SET active = true WHERE id = 'vidmod2'`)
	newFence, err := e.eng.Takeover(e.ctx, job, "vidmod2")
	if err != nil || newFence != fence+1 {
		t.Fatalf("takeover: fence=%d err=%v", newFence, err)
	}
	if n := e.count(`SELECT count(DISTINCT message_id) FROM outbox`); n != 2 {
		t.Fatal("takeover must enqueue a new request")
	}
	old := e.moduleEvent("vidmod", "job.succeeded", job, fence, map[string]any{"output": map[string]any{}})
	stale := e.moduleEvent("vidmod2", "job.succeeded", job, fence, map[string]any{"output": map[string]any{}})
	if err := e.consumeUntil(e.consumer(), func() bool { return e.count(`SELECT count(*) FROM inbox`) == 2 }); err != nil {
		t.Fatal(err)
	}
	var o1, o2 string
	_ = e.pool.QueryRow(e.ctx, `SELECT outcome FROM inbox WHERE message_id = $1`, old).Scan(&o1)
	_ = e.pool.QueryRow(e.ctx, `SELECT outcome FROM inbox WHERE message_id = $1`, stale).Scan(&o2)
	if o1 != "conflict" || o2 != "stale" {
		t.Fatalf("outcomes = %s, %s; want conflict, stale", o1, o2)
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE status = 'succeeded'`); n != 0 {
		t.Fatal("stale event changed state")
	}
}

func TestPoisonMessageGoesToDLQ(t *testing.T) {
	e := setup(t)
	e.publishRaw(uuid.NewString(), []byte(`{"not":"an envelope"`))
	c := e.consumer()
	if err := e.consumeUntil(c, func() bool { return e.queueLen(e.topo.CoreEvents()+".dlq") == 1 }); err != nil {
		t.Fatal(err)
	}
}

func TestFailingHandlerIsBoundedAndDeadLettered(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	e.moduleEvent("vidmod", "job.progress", job, fence, map[string]any{"percent": 1})
	var calls atomic.Int32
	c := e.consumer()
	c.MaxAttempts = 3
	c.Handler = func(context.Context, pgx.Tx, messaging.Envelope) (string, error) {
		calls.Add(1)
		return "", errors.New("database says no")
	}
	if err := e.consumeUntil(c, func() bool { return e.queueLen(e.topo.CoreEvents()+".dlq") == 1 }); err != nil {
		t.Fatal(err)
	}
	if n := calls.Load(); n != 3 {
		t.Fatalf("handler calls = %d; MaxAttempts 3 must bound retries", n)
	}
	if n := e.count(`SELECT count(*) FROM inbox`); n != 0 {
		t.Fatal("failed message left inbox row")
	}
}

func TestUnroutableMessageIsNotMarkedSent(t *testing.T) {
	e := setup(t)
	err := db.WithTx(e.ctx, e.pool, func(tx pgx.Tx) error {
		return messaging.Enqueue(e.ctx, tx, messaging.OutboxMessage{Exchange: e.topo.Commands(), RoutingKey: "job.video.nobody",
			Envelope: messaging.Envelope{Type: "job.requested", Producer: "core", Payload: json.RawMessage(`{}`)}})
	})
	if err != nil {
		t.Fatal(err)
	}
	if n, _ := e.relay("w1").RunOnce(e.ctx, e.conn); n != 0 {
		t.Fatal("unroutable message counted as sent")
	}
	var status, lastErr string
	var attempts int
	_ = e.pool.QueryRow(e.ctx, `SELECT status, publish_attempts, coalesce(last_error,'') FROM outbox`).Scan(&status, &attempts, &lastErr)
	if status != "pending" || attempts != 1 || !strings.Contains(lastErr, "unroutable") {
		t.Fatalf("status=%s attempts=%d err=%q", status, attempts, lastErr)
	}
	if n, _ := e.relay("w1").RunOnce(e.ctx, e.conn); n != 0 {
		t.Fatal("backoff not respected")
	}
}

func TestReadinessReportsUnavailableBroker(t *testing.T) {
	e := setup(t)
	broken := &messaging.Conn{URL: "amqp://guest:guest@127.0.0.1:1/", Log: e.log} // never connected
	srv := httptest.NewServer((&httpapi.Server{Checks: map[string]httpapi.Check{
		"db": func(c context.Context) error { return e.pool.Ping(c) }, "broker": broken.Check}}).Handler())
	defer srv.Close()
	res, err := http.Get(srv.URL + "/ready")
	if err != nil {
		t.Fatal(err)
	}
	var body struct {
		Status string            `json:"status"`
		Checks map[string]string `json:"checks"`
	}
	_ = json.NewDecoder(res.Body).Decode(&body)
	res.Body.Close()
	if res.StatusCode != 503 || body.Checks["broker"] != "unavailable" || body.Checks["db"] != "ok" {
		t.Fatalf("ready: %d %+v", res.StatusCode, body)
	}
	res, _ = http.Get(srv.URL + "/internal/v1/jobs/x/events")
	res.Body.Close()
	if res.StatusCode != 501 {
		t.Fatalf("unimplemented route answered %d", res.StatusCode)
	}
}
