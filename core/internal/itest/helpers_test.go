// Package itest holds integration tests against real PostgreSQL and RabbitMQ.
// They run when MF_TEST_DATABASE_URL and MF_TEST_AMQP_URL are set and are skipped otherwise;
// CI sets both (service containers), so a skip there is a failure of the CI setup, not a pass.
package itest

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	amqp "github.com/rabbitmq/amqp091-go"

	"github.com/t1menar/manufacture/core/internal/auth"
	"github.com/t1menar/manufacture/core/internal/credentials"
	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/messaging"
	"github.com/t1menar/manufacture/core/internal/modules"
	"github.com/t1menar/manufacture/core/internal/prompts"
	"github.com/t1menar/manufacture/core/internal/settings"
)

type env struct {
	t         *testing.T
	ctx       context.Context
	pool      *pgxpool.Pool
	conn      *amqp.Connection
	topo      messaging.Topology
	eng       *engine.Engine
	log       *slog.Logger
	settings  *settings.Store
	auth      *auth.Authenticator
	tokens    map[string]string
	reg       *modules.Registry
	creds     *credentials.Store
	prompts   *prompts.Store
	masterKey []byte
}

func setup(t *testing.T) *env {
	t.Helper()
	dbURL, amqpURL := os.Getenv("MF_TEST_DATABASE_URL"), os.Getenv("MF_TEST_AMQP_URL")
	if dbURL == "" || amqpURL == "" {
		t.Skip("MF_TEST_DATABASE_URL / MF_TEST_AMQP_URL not set")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	t.Cleanup(cancel)

	admin, err := pgx.Connect(ctx, dbURL)
	if err != nil {
		t.Fatal(err)
	}
	name := "mf_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	if _, err := admin.Exec(ctx, "CREATE DATABASE "+name); err != nil {
		t.Fatal(err)
	}
	u, _ := url.Parse(dbURL)
	u.Path = "/" + name
	pool, err := db.Open(ctx, u.String())
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		pool.Close()
		_, _ = admin.Exec(context.Background(), "DROP DATABASE IF EXISTS "+name+" WITH (FORCE)")
		_ = admin.Close(context.Background())
	})
	if err := db.Migrate(ctx, pool); err != nil {
		t.Fatal(err)
	}

	conn, err := amqp.Dial(amqpURL)
	if err != nil {
		t.Fatal(err)
	}
	topo := messaging.Topology{Prefix: "t" + strings.ReplaceAll(uuid.NewString(), "-", "")[:10] + ".", DeliveryLimit: 2}
	ch, _ := conn.Channel()
	if err := topo.DeclareCore(ch); err != nil {
		t.Fatal(err)
	}
	if err := topo.DeclareModule(ch, "vidmod"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		c, err := conn.Channel()
		if err == nil {
			for _, q := range []string{topo.CoreEvents(), topo.ModuleQueue("vidmod")} {
				_, _ = c.QueueDelete(q, false, false, false)
				_, _ = c.QueueDelete(q+".dlq", false, false, false)
			}
			for _, x := range []string{topo.Commands(), topo.Events(), topo.DLX()} {
				_ = c.ExchangeDelete(x, false, false)
			}
		}
		_ = conn.Close()
	})
	_ = ch.Close()

	log := slog.New(slog.NewTextHandler(io.Discard, nil))
	if testing.Verbose() {
		log = slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
	}
	store := &settings.Store{Pool: pool}
	key := make([]byte, 32)
	for i := range key {
		key[i] = byte(i + 1)
	}
	mk := modules.MasterKey{Version: 1, Key: key}
	promptStore := &prompts.Store{Pool: pool}
	e := &env{t: t, ctx: ctx, pool: pool, conn: conn, topo: topo, log: log,
		eng:      &engine.Engine{Pool: pool, Topo: topo, Log: log, CallbackBaseURL: "http://core.test", Settings: store, Prompts: promptStore},
		settings: store, prompts: promptStore, masterKey: key,
		reg:   &modules.Registry{Pool: pool, Key: mk, Grace: time.Second},
		creds: &credentials.Store{Pool: pool, Key: credentials.MasterKey{Version: 1, Key: key}},
		auth:  &auth.Authenticator{Pool: pool, AdminTokenHash: auth.HashToken("mfa_test_admin_token_xxxxxxxx")},
		tokens: map[string]string{
			"vidmod":  "mft_vidmod_test_token_xxxxxxxx",
			"vidmod2": "mft_vidmod2_test_token_xxxxxxx",
			"revmod":  "mft_revmod_test_token_xxxxxxxx",
			"pubmod":  "mft_pubmod_test_token_xxxxxxxx",
		}}
	e.exec(`INSERT INTO modules (id, name, stage_id, endpoint, active, health, last_seen_at) VALUES
		('vidmod', 'Video', 'video', 'http://127.0.0.1:9/vidmod', true, 'up', now()),
		('vidmod2', 'Video2', 'video', 'http://127.0.0.1:9/vidmod2', false, 'up', now()),
		('revmod', 'Review', 'review', 'http://127.0.0.1:9/revmod', true, 'up', now()),
		('pubmod', 'Publish', 'publish', 'http://127.0.0.1:9/pubmod', true, 'up', now())`)
	for id, tok := range e.tokens {
		if err := auth.SetModuleToken(ctx, pool, id, tok); err != nil {
			t.Fatal(err)
		}
	}
	return e
}

func (e *env) exec(sql string, args ...any) {
	e.t.Helper()
	if _, err := e.pool.Exec(e.ctx, sql, args...); err != nil {
		e.t.Fatalf("%s: %v", sql, err)
	}
}

func (e *env) count(sql string, args ...any) int {
	e.t.Helper()
	var n int
	if err := e.pool.QueryRow(e.ctx, sql, args...).Scan(&n); err != nil {
		e.t.Fatalf("%s: %v", sql, err)
	}
	return n
}

func (e *env) idea(text string) int64 {
	e.t.Helper()
	var id int64
	if err := e.pool.QueryRow(e.ctx, `INSERT INTO ideas (text, status, queued_at) VALUES ($1, 'queued', now()) RETURNING id`, text).Scan(&id); err != nil {
		e.t.Fatal(err)
	}
	return id
}

func (e *env) relay(worker string) *messaging.Relay {
	return &messaging.Relay{Pool: e.pool, Worker: worker, Lease: 2 * time.Second, Log: e.log}
}

func (e *env) consumer() *messaging.Consumer {
	return &messaging.Consumer{Pool: e.pool, Name: "core.job-events", Queue: e.topo.CoreEvents(), Handler: e.eng.HandleJobEvent,
		Log: e.log, RetryDelay: func(int64) time.Duration { return 50 * time.Millisecond }}
}

// startedJob runs one scheduler tick and returns the first (video) job.
func (e *env) startedJob() (jobID uuid.UUID, fence int) {
	e.t.Helper()
	e.idea("an idea")
	if n, err := e.eng.Tick(e.ctx); err != nil || n != 1 {
		e.t.Fatalf("tick: n=%d err=%v", n, err)
	}
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs`).Scan(&jobID, &fence); err != nil {
		e.t.Fatal(err)
	}
	return
}

// moduleEvent publishes a job event as a module would (directly, not through the outbox).
func (e *env) moduleEvent(module, typ string, job uuid.UUID, fence int, payload any) uuid.UUID {
	e.t.Helper()
	var prod uuid.UUID
	_ = e.pool.QueryRow(e.ctx, `SELECT production_id FROM jobs WHERE id = $1`, job).Scan(&prod)
	p, _ := json.Marshal(payload)
	id := uuid.Must(uuid.NewV7())
	env := messaging.Envelope{MessageID: id, Type: typ, SchemaVersion: 1, OccurredAt: time.Now().UTC(),
		Producer: "module:" + module, ProductionID: &prod, Job: &messaging.JobRef{JobID: job, Fence: fence}, Payload: p}
	e.publishRaw(id.String(), mustJSON(env))
	return id
}

func (e *env) publishRaw(messageID string, body []byte) {
	e.t.Helper()
	ch, err := e.conn.Channel()
	if err != nil {
		e.t.Fatal(err)
	}
	defer ch.Close()
	if err := ch.Confirm(false); err != nil {
		e.t.Fatal(err)
	}
	dc, err := ch.PublishWithDeferredConfirmWithContext(e.ctx, e.topo.Events(), "job.event", true, false,
		amqp.Publishing{MessageId: messageID, DeliveryMode: amqp.Persistent, ContentType: "application/json", Body: body})
	if err != nil {
		e.t.Fatal(err)
	}
	if ok, err := dc.WaitContext(e.ctx); !ok || err != nil {
		e.t.Fatalf("publish not confirmed: %v", err)
	}
}

func mustJSON(v any) []byte {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}

// consumeUntil runs a consumer until cond is true or the deadline passes.
func (e *env) consumeUntil(c *messaging.Consumer, cond func() bool) error {
	e.t.Helper()
	ctx, cancel := context.WithTimeout(e.ctx, 10*time.Second)
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- c.Consume(ctx, e.conn) }()
	for ctx.Err() == nil {
		if cond() {
			cancel()
			<-done
			return nil
		}
		select {
		case err := <-done:
			return err
		case <-time.After(30 * time.Millisecond):
		}
	}
	return fmt.Errorf("condition not met: %w", <-done)
}

func (e *env) queueLen(q string) int {
	e.t.Helper()
	ch, err := e.conn.Channel()
	if err != nil {
		e.t.Fatal(err)
	}
	defer ch.Close()
	st, err := ch.QueueDeclarePassive(q, true, false, false, false, amqp.Table{"x-queue-type": "quorum"})
	if err != nil {
		e.t.Fatal(err)
	}
	return st.Messages
}

func (e *env) waitQueue(q string, n int) {
	e.t.Helper()
	deadline := time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		if e.queueLen(q) == n {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	e.t.Fatalf("queue %s: want %d messages, have %d", q, n, e.queueLen(q))
}

// get fetches one message from a queue (basic.get) and acks it.
func (e *env) get(q string) amqp.Delivery {
	e.t.Helper()
	ch, err := e.conn.Channel()
	if err != nil {
		e.t.Fatal(err)
	}
	defer ch.Close()
	d, ok, err := ch.Get(q, true)
	if err != nil || !ok {
		e.t.Fatalf("get %s: ok=%v err=%v", q, ok, err)
	}
	return d
}
