package itest

import (
	"context"
	"encoding/json"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/messaging"
	"github.com/t1menar/manufacture/core/internal/publish"
)

func (e *env) publishStore() *publish.Store {
	return &publish.Store{
		Pool: e.pool,
		OnIntentCreated: func(ctx context.Context, tx pgx.Tx, intent publish.Intent) error {
			_, err := e.eng.CreateRepublishJob(ctx, tx, intent.VariantID, intent.ID, intent.ContentRevisionID, intent.Generation)
			return err
		},
	}
}

func (e *env) seedAccount() (variant, account uuid.UUID, job uuid.UUID) {
	e.t.Helper()
	job, _ = e.startedJob()
	_ = e.pool.QueryRow(e.ctx, `SELECT id FROM variants`).Scan(&variant)
	account = uuid.Must(uuid.NewV7())
	e.exec(`INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled)
		VALUES ($1, 'itim', 'instagram', '@itim', true)`, account)
	return variant, account, job
}

func TestConcurrentIntentCreationOneRow(t *testing.T) {
	e := setup(t)
	variant, _, job := e.seedAccount()
	body, _ := json.Marshal(map[string]any{
		"metadata": map[string]any{"title": "t", "description": "d", "topics": []string{"pg"},
			"platforms": map[string]any{"instagram": map[string]any{"caption": "c", "hashtags": []string{"#pg"}}}},
		"video": map[string]any{"ref": "s3://manufacture/x", "sha256": "aa"},
	})
	rev, err := e.publishStore().CreateRevision(e.ctx, variant, job, body)
	if err != nil {
		t.Fatal(err)
	}
	var ok atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			ints, err := e.publishStore().ApproveAndCreateIntents(e.ctx, rev.ID, 1)
			if err != nil {
				t.Error(err)
				return
			}
			if len(ints) == 1 {
				ok.Add(1)
			}
		}()
	}
	wg.Wait()
	if ok.Load() != 8 {
		t.Fatalf("successful callers = %d", ok.Load())
	}
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE variant_id = $1 AND generation = 1`, variant); n != 1 {
		t.Fatalf("intents = %d, want 1", n)
	}
}

func TestDuplicatePublishedCallbackOnce(t *testing.T) {
	e := setup(t)
	variant, account, job := e.seedAccount()
	body := json.RawMessage(`{"video":{"ref":"s3://x","sha256":"ab"},"metadata":{"title":"t","description":"d","topics":[],"platforms":{}}}`)
	rev, _ := e.publishStore().CreateRevision(e.ctx, variant, job, body)
	ints, err := e.publishStore().ApproveAndCreateIntents(e.ctx, rev.ID, 1)
	if err != nil || len(ints) != 1 {
		t.Fatalf("%v %#v", err, ints)
	}
	id := ints[0].ID
	at := time.Now().UTC()
	if err := e.publishStore().ApplyPublished(e.ctx, id, "ext-1", "https://ig/p/1", at); err != nil {
		t.Fatal(err)
	}
	if err := e.publishStore().ApplyPublished(e.ctx, id, "ext-1", "https://ig/p/1", at); err != nil {
		t.Fatalf("identical duplicate: %v", err)
	}
	if err := e.publishStore().ApplyPublished(e.ctx, id, "ext-OTHER", "https://ig/p/2", at); err == nil {
		t.Fatal("different external_id on published intent must conflict")
	}
	_ = account
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE id = $1 AND status = 'published'`, id); n != 1 {
		t.Fatal("not published")
	}
}

func TestUnknownOutcomeNeedsAttentionNoResend(t *testing.T) {
	e := setup(t)
	variant, _, job := e.seedAccount()
	rev, _ := e.publishStore().CreateRevision(e.ctx, variant, job, json.RawMessage(`{"x":1}`))
	ints, _ := e.publishStore().ApproveAndCreateIntents(e.ctx, rev.ID, 1)
	id := ints[0].ID
	e.exec(`UPDATE publish_intents SET status = 'in_progress' WHERE id = $1`, id)
	// timeout path: reconcile failed → unknown (never blind republish)
	if err := e.eng.ApplyPublishOutcomeUnknown(e.ctx, id, variant); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE id = $1 AND status = 'unknown'`, id); n != 1 {
		t.Fatal("intent not unknown")
	}
	if n := e.count(`SELECT count(*) FROM variants WHERE id = $1 AND attention->>'reason' = 'publish_outcome_unknown'`, variant); n != 1 {
		t.Fatal("variant attention missing")
	}
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE variant_id = $1 AND generation = 2`, variant); n != 0 {
		t.Fatal("must not auto-create generation 2")
	}
}

func TestReconcileFoundPublishes(t *testing.T) {
	e := setup(t)
	variant, _, job := e.seedAccount()
	rev, _ := e.publishStore().CreateRevision(e.ctx, variant, job, json.RawMessage(`{"x":1}`))
	ints, _ := e.publishStore().ApproveAndCreateIntents(e.ctx, rev.ID, 1)
	id := ints[0].ID
	e.exec(`UPDATE publish_intents SET status = 'unknown' WHERE id = $1`, id)
	at := time.Now().UTC()
	if err := e.publishStore().ReconcileFound(e.ctx, id, "found-1", "https://ig/found", at); err != nil {
		t.Fatal(err)
	}
	got, err := e.publishStore().Get(e.ctx, id)
	if err != nil || got.Status != "published" || got.ExternalPostID == nil || *got.ExternalPostID != "found-1" {
		t.Fatalf("%+v %v", got, err)
	}
}

func TestContentChangeDoesNotMutateRevision(t *testing.T) {
	e := setup(t)
	variant, _, job := e.seedAccount()
	orig := json.RawMessage(`{"title":"original","tags":["a"]}`)
	rev, err := e.publishStore().CreateRevision(e.ctx, variant, job, orig)
	if err != nil {
		t.Fatal(err)
	}
	ints, _ := e.publishStore().ApproveAndCreateIntents(e.ctx, rev.ID, 1)
	// "edit content" by inserting a newer revision — old intent still points at old body
	newer := json.RawMessage(`{"title":"edited","tags":["b"]}`)
	_, err = e.publishStore().CreateRevision(e.ctx, variant, job, newer)
	if err != nil {
		t.Fatal(err)
	}
	body, err := e.publishStore().RevisionBody(e.ctx, ints[0].ContentRevisionID)
	if err != nil {
		t.Fatal(err)
	}
	var a, b any
	_ = json.Unmarshal(orig, &a)
	_ = json.Unmarshal(body, &b)
	ab, _ := json.Marshal(a)
	bb, _ := json.Marshal(b)
	if string(ab) != string(bb) {
		t.Fatalf("revision mutated: %s", body)
	}
	if e.count(`SELECT count(*) FROM publish_intents WHERE variant_id = $1`, variant) != 1 {
		t.Fatal("new revision must not create intents without approval/republish")
	}
}

func TestCancelEnqueuesOneStableMessage(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	if err := e.eng.CancelJob(e.ctx, job, "stop"); err != nil {
		t.Fatal(err)
	}
	// second cancel must not enqueue another row
	if err := e.eng.CancelJob(e.ctx, job, "again"); err == nil {
		t.Fatal("second cancel should fail")
	}
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'cancel.vidmod'`); n != 1 {
		t.Fatalf("outbox cancel rows = %d", n)
	}
	var msgID uuid.UUID
	var body []byte
	_ = e.pool.QueryRow(e.ctx, `SELECT message_id, body FROM outbox WHERE routing_key = 'cancel.vidmod'`).Scan(&msgID, &body)
	var env messaging.Envelope
	_ = json.Unmarshal(body, &env)
	if env.Type != "job.cancel_requested" || env.Job == nil || env.Job.JobID != job || env.Job.Fence != fence {
		t.Fatalf("bad envelope: %+v", env)
	}
	// stable id: recompute
	want := uuid.NewSHA1(uuid.NameSpaceOID, append(job[:], []byte("cancel")...))
	if msgID != want || env.MessageID != want {
		t.Fatalf("message_id not stable: %s want %s", msgID, want)
	}
	r := e.relay("w1")
	if n, err := r.RunOnce(e.ctx, e.conn); err != nil || n != 1 {
		// may also send job.requested from start — claim both
		t.Logf("first relay n=%d err=%v", n, err)
	}
	// drain remaining
	for i := 0; i < 3; i++ {
		_, _ = r.RunOnce(e.ctx, e.conn)
	}
	q := e.topo.ModuleQueue("vidmod")
	// module queue binds cancel.<module>
	found := 0
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		ch, err := e.conn.Channel()
		if err != nil {
			t.Fatal(err)
		}
		d, ok, err := ch.Get(q, true)
		_ = ch.Close()
		if err != nil {
			t.Fatal(err)
		}
		if !ok {
			time.Sleep(50 * time.Millisecond)
			continue
		}
		var env2 messaging.Envelope
		_ = json.Unmarshal(d.Body, &env2)
		if env2.Type == "job.cancel_requested" {
			found++
			if d.MessageId != want.String() {
				t.Fatalf("amqp message_id %s", d.MessageId)
			}
		}
	}
	if found != 1 {
		t.Fatalf("cancel deliveries = %d, want 1", found)
	}
}

func TestNotifyEnqueue(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	var prod uuid.UUID
	_ = e.pool.QueryRow(e.ctx, `SELECT production_id FROM jobs WHERE id = $1`, job).Scan(&prod)
	payload := json.RawMessage(`{"notification_id":"` + uuid.Must(uuid.NewV7()).String() + `","production_id":"` + prod.String() + `","variant_id":"` + uuid.Must(uuid.NewV7()).String() + `","language":"en","status":"published","channel":{"id":"itim","name":"iTim","language":"en"},"publications":[]}`)
	err := db.WithTx(e.ctx, e.pool, func(tx pgx.Tx) error {
		return e.eng.EnqueueNotify(e.ctx, tx, "revmod", payload, prod, job, fence)
	})
	if err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM outbox WHERE routing_key = 'notify.revmod'`); n != 1 {
		t.Fatalf("notify outbox = %d", n)
	}
}
