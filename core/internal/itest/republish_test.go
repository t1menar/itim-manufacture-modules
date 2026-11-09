package itest

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/google/uuid"

	"github.com/t1menar/manufacture/core/internal/httpapi"
)

func (e *env) republishURL() (*httptest.Server, func(intent uuid.UUID, body any, token string, headers map[string]string) *http.Response) {
	e.t.Helper()
	srv := httptest.NewServer((&httpapi.Server{
		Auth: e.auth, Engine: e.eng, Settings: e.settings, Modules: e.reg, Credentials: e.creds,
		Publish: e.publishStore(),
	}).Handler())
	e.t.Cleanup(srv.Close)
	do := func(intent uuid.UUID, body any, token string, headers map[string]string) *http.Response {
		e.t.Helper()
		b, _ := json.Marshal(body)
		req, _ := http.NewRequest(http.MethodPost, srv.URL+"/internal/v1/publish-intents/"+intent.String()+"/republish", bytes.NewReader(b))
		req.Header.Set("Content-Type", "application/json")
		if token != "" {
			req.Header.Set("Authorization", "Bearer "+token)
		}
		for k, v := range headers {
			req.Header.Set(k, v)
		}
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			e.t.Fatal(err)
		}
		return res
	}
	return srv, do
}

func (e *env) seedPublishedIntent() (intentID uuid.UUID, generation int) {
	e.t.Helper()
	variant, _, job := e.seedAccount()
	rev, err := e.publishStore().CreateRevision(e.ctx, variant, job, json.RawMessage(`{"title":"v1"}`))
	if err != nil {
		e.t.Fatal(err)
	}
	ints, err := e.publishStore().ApproveAndCreateIntents(e.ctx, rev.ID, 1)
	if err != nil || len(ints) != 1 {
		e.t.Fatalf("%v %#v", err, ints)
	}
	id := ints[0].ID
	e.exec(`UPDATE publish_intents SET status='published', external_post_id='ext-1', url='https://ig/1', published_at=now() WHERE id=$1`, id)
	// Release jobs_variant_live_uq so republish can enqueue a publish job.
	e.exec(`UPDATE jobs SET status = 'succeeded', finished_at = now() WHERE variant_id = (SELECT variant_id FROM publish_intents WHERE id = $1) AND status IN ('queued','dispatching','dispatched','running')`, id)
	return id, 1
}

func TestRepublishValidationAndAuth(t *testing.T) {
	e := setup(t)
	id, gen := e.seedPublishedIntent()
	_, do := e.republishURL()

	res := do(id, map[string]any{"reason": "  \t ", "base_generation": gen}, "mfa_test_admin_token_xxxxxxxx", nil)
	if res.StatusCode != 422 || problemCode(t, res) != "validation_failed" {
		t.Fatalf("whitespace reason: %d", res.StatusCode)
	}
	res = do(id, map[string]any{"reason": "fix", "base_generation": gen}, "", nil)
	if res.StatusCode != 401 {
		t.Fatalf("no auth: %d", res.StatusCode)
	}
	res = do(id, map[string]any{"reason": "fix", "base_generation": gen}, e.tokens["vidmod"], nil)
	if res.StatusCode != 403 || problemCode(t, res) != "forbidden" {
		t.Fatalf("module token: %d %s", res.StatusCode, problemCode(t, res))
	}
}

func TestRepublishConcurrentOneGeneration(t *testing.T) {
	e := setup(t)
	id, gen := e.seedPublishedIntent()
	_, do := e.republishURL()
	var ok, conflict atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			res := do(id, map[string]any{"reason": fmt.Sprintf("retry %d", i), "base_generation": gen},
				"mfa_test_admin_token_xxxxxxxx", map[string]string{"X-Admin-Actor": "alice"})
			code := problemCode(t, res)
			if res.StatusCode == 201 {
				ok.Add(1)
			} else if res.StatusCode == 409 && (code == "generation_conflict" || code == "invalid_state") {
				conflict.Add(1)
			} else {
				t.Errorf("status=%d code=%s", res.StatusCode, code)
			}
		}(i)
	}
	wg.Wait()
	if ok.Load() != 1 {
		t.Fatalf("created=%d conflict=%d", ok.Load(), conflict.Load())
	}
	if n := e.count(`SELECT count(*) FROM publish_intents`); n != 2 {
		t.Fatalf("intents=%d want 2 (gen1+gen2)", n)
	}
	if n := e.count(`SELECT count(*) FROM events WHERE type = 'publish.republish_requested'`); n != 1 {
		t.Fatalf("audit events=%d", n)
	}
}

func TestRepublishInProgressConflict(t *testing.T) {
	e := setup(t)
	id, gen := e.seedPublishedIntent()
	e.exec(`UPDATE publish_intents SET status = 'in_progress' WHERE id = $1`, id)
	_, do := e.republishURL()
	res := do(id, map[string]any{"reason": "nope", "base_generation": gen}, "mfa_test_admin_token_xxxxxxxx", nil)
	if res.StatusCode != 409 || problemCode(t, res) != "invalid_state" {
		t.Fatalf("%d %s", res.StatusCode, problemCode(t, res))
	}
}

func TestRepublishUnknownNeedsAckThenCreates(t *testing.T) {
	e := setup(t)
	id, gen := e.seedPublishedIntent()
	e.exec(`UPDATE publish_intents SET status = 'unknown' WHERE id = $1`, id)
	_, do := e.republishURL()
	res := do(id, map[string]any{"reason": "force", "base_generation": gen}, "mfa_test_admin_token_xxxxxxxx", nil)
	if res.StatusCode != 409 || problemCode(t, res) != "unknown_needs_ack" {
		t.Fatalf("%d %s", res.StatusCode, problemCode(t, res))
	}
	res = do(id, map[string]any{"reason": "force with ack", "base_generation": gen, "acknowledge_unknown_risk": true},
		"mfa_test_admin_token_xxxxxxxx", map[string]string{"X-Admin-Actor": "bob"})
	if res.StatusCode != 201 {
		t.Fatalf("%d %s", res.StatusCode, problemCode(t, res))
	}
	var body struct {
		Generation int    `json:"generation"`
		Reason     string `json:"reason"`
		Actor      string `json:"authorized_by"`
	}
	_ = json.NewDecoder(res.Body).Decode(&body)
	res.Body.Close()
	if body.Generation != 2 || body.Actor != "user:bob" {
		t.Fatalf("%+v", body)
	}
	if n := e.count(`SELECT count(*) FROM events WHERE type='publish.republish_requested' AND payload->>'reason' = 'force with ack'`); n != 1 {
		t.Fatal("audit missing")
	}
}

func TestRepublishAfterPublishedCreatesGen2AndOneMessage(t *testing.T) {
	e := setup(t)
	id, gen := e.seedPublishedIntent()
	before := e.count(`SELECT count(*) FROM outbox WHERE routing_key LIKE 'job.publish.%'`)
	_, do := e.republishURL()
	res := do(id, map[string]any{"reason": "manual again", "base_generation": gen}, "mfa_test_admin_token_xxxxxxxx",
		map[string]string{"X-Admin-Actor": "carol"})
	if res.StatusCode != 201 {
		t.Fatalf("%d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE generation = 2 AND status = 'pending'`); n != 1 {
		t.Fatal("gen2 missing")
	}
	after := e.count(`SELECT count(*) FROM outbox WHERE routing_key LIKE 'job.publish.%'`)
	if after-before != 1 {
		t.Fatalf("outbox publish messages delta=%d want 1", after-before)
	}
	if n := e.count(`SELECT count(*) FROM events WHERE type = 'publish.republish_requested' AND actor = 'user:carol'`); n != 1 {
		t.Fatal("audit missing")
	}
}
