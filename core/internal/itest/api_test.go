package itest

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/httpapi"
)

func (e *env) api() *httptest.Server {
	e.t.Helper()
	srv := httptest.NewServer((&httpapi.Server{
		Checks:   map[string]httpapi.Check{"db": func(c context.Context) error { return e.pool.Ping(c) }},
		Auth:     e.auth,
		Engine:   e.eng,
		Settings: e.settings,
	}).Handler())
	e.t.Cleanup(srv.Close)
	return srv
}

func (e *env) postCallback(srv *httptest.Server, module, path string, job uuid.UUID, fence int, body any) *http.Response {
	e.t.Helper()
	b, _ := json.Marshal(body)
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/internal/v1/jobs/"+job.String()+"/"+path, bytes.NewReader(b))
	req.Header.Set("Authorization", "Bearer "+e.tokens[module])
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Fence", fmt.Sprintf("%d", fence))
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		e.t.Fatal(err)
	}
	return res
}

func problemCode(t *testing.T, res *http.Response) string {
	t.Helper()
	var p struct {
		Code string `json:"code"`
	}
	_ = json.NewDecoder(res.Body).Decode(&p)
	res.Body.Close()
	return p.Code
}

func TestCallbackAuthAndFence(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	srv := e.api()

	// no auth
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/internal/v1/jobs/"+job.String()+"/progress", bytes.NewReader([]byte(`{"percent":1,"step":"a"}`)))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Fence", "1")
	res, _ := http.DefaultClient.Do(req)
	if res.StatusCode != 401 || problemCode(t, res) != "unauthorized" {
		t.Fatalf("no auth: %d", res.StatusCode)
	}

	// wrong module
	res = e.postCallback(srv, "revmod", "progress", job, fence, map[string]any{"percent": 1, "step": "a"})
	if res.StatusCode != 403 || problemCode(t, res) != "forbidden" {
		t.Fatalf("wrong module: %d %s", res.StatusCode, problemCode(t, res))
	}

	// stale fence
	res = e.postCallback(srv, "vidmod", "progress", job, fence+1, map[string]any{"percent": 1, "step": "a"})
	if res.StatusCode != 409 || problemCode(t, res) != "job_not_current" {
		t.Fatalf("stale fence: %d", res.StatusCode)
	}

	// ok
	res = e.postCallback(srv, "vidmod", "progress", job, fence, map[string]any{"percent": 10, "step": "render"})
	if res.StatusCode != 200 {
		t.Fatalf("progress: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'running'`, job); n != 1 {
		t.Fatal("progress did not move job to running")
	}
}

func TestDuplicateCallbackAppliedOnce(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	srv := e.api()
	body := map[string]any{"output": videoStageOutput("dup"), "artifacts": []any{}}
	res := e.postCallback(srv, "vidmod", "result", job, fence, body)
	if res.StatusCode != 200 {
		t.Fatalf("first: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	res = e.postCallback(srv, "vidmod", "result", job, fence, body)
	if res.StatusCode != 200 {
		t.Fatalf("duplicate: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM jobs WHERE stage_id = 'review'`); n != 1 {
		t.Fatalf("review jobs = %d, want 1", n)
	}
	if n := e.count(`SELECT count(*) FROM inbox WHERE consumer = 'http.callbacks'`); n != 1 {
		t.Fatalf("inbox rows = %d", n)
	}
}

func TestResultWithoutDecisionAndWhitespaceReason(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	srv := e.api()
	// finish video so we get a review job
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{"output": videoStageOutput("review"), "artifacts": []any{}})
	res.Body.Close()
	var rev uuid.UUID
	var rf int
	if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'review'`).Scan(&rev, &rf); err != nil {
		t.Fatal(err)
	}
	res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
		"output":    map[string]any{"reviewer": map[string]any{"telegram_user_id": 1}, "decided_at": "2026-01-01T00:00:00Z", "round": 1},
		"artifacts": []any{},
	})
	if res.StatusCode != 422 || problemCode(t, res) != "output_invalid" {
		t.Fatalf("missing decision: %d %s", res.StatusCode, problemCode(t, res))
	}
	res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
		"output": map[string]any{
			"decision": "rejected", "reason": "   \t  ", "reviewer": map[string]any{"telegram_user_id": 1},
			"decided_at": "2026-01-01T00:00:00Z", "round": 1,
		},
		"artifacts": []any{},
	})
	if res.StatusCode != 422 || problemCode(t, res) != "output_invalid" {
		t.Fatalf("whitespace reason: %d %s", res.StatusCode, problemCode(t, res))
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status IN ('queued','dispatched','running')`, rev); n != 1 {
		t.Fatal("invalid result must leave the job live")
	}
}

func TestRejectThreeTimesNeedsAttentionMaxRounds(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{"output": videoStageOutput("r1"), "artifacts": []any{}})
	res.Body.Close()

	for round := 1; round <= 3; round++ {
		var rev uuid.UUID
		var rf int
		if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'review' AND status IN ('queued','dispatched','running')`).Scan(&rev, &rf); err != nil {
			t.Fatalf("round %d review: %v", round, err)
		}
		res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
			"output": map[string]any{
				"decision": "rejected", "reason": fmt.Sprintf("fix #%d", round),
				"reviewer":   map[string]any{"telegram_user_id": 1},
				"decided_at": "2026-01-01T00:00:00Z", "round": round,
			},
			"artifacts": []any{},
		})
		if res.StatusCode != 200 {
			t.Fatalf("reject %d: %d %s", round, res.StatusCode, problemCode(t, res))
		}
		res.Body.Close()
		if round < 3 {
			var vid uuid.UUID
			var vf int
			if err := e.pool.QueryRow(e.ctx, `SELECT id, fence FROM jobs WHERE stage_id = 'video' AND mode = 'revise' AND status IN ('queued','dispatched','running')`).Scan(&vid, &vf); err != nil {
				t.Fatalf("revise after round %d: %v", round, err)
			}
			res = e.postCallback(srv, "vidmod", "result", vid, vf, map[string]any{"output": videoStageOutput(fmt.Sprintf("rev%d", round)), "artifacts": []any{}})
			if res.StatusCode != 200 {
				t.Fatalf("revise result: %d %s", res.StatusCode, problemCode(t, res))
			}
			res.Body.Close()
		}
	}
	if n := e.count(`SELECT count(*) FROM variants WHERE status = 'needs_attention' AND attention->>'reason' = 'max_rounds'`); n != 1 {
		t.Fatalf("expected needs_attention max_rounds, got attention=%d review_rounds=%d",
			e.count(`SELECT count(*) FROM variants WHERE status = 'needs_attention'`),
			e.count(`SELECT count(*) FROM review_rounds`))
	}
	if n := e.count(`SELECT count(*) FROM review_rounds WHERE decision = 'rejected'`); n != 3 {
		t.Fatalf("review_rounds = %d", n)
	}
}

func TestDeadlineSweeperOnceUnderContention(t *testing.T) {
	e := setup(t)
	job, _ := e.startedJob()
	e.exec(`UPDATE jobs SET status = 'dispatched', dispatched_at = now(), deadline = now() - interval '1 second' WHERE id = $1`, job)
	var timed atomic.Int32
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			n, err := e.eng.SweepTimeouts(e.ctx, 8)
			if err != nil {
				t.Error(err)
				return
			}
			timed.Add(int32(n))
		}()
	}
	wg.Wait()
	if timed.Load() != 1 {
		t.Fatalf("sweepers timed out %d jobs, want 1", timed.Load())
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'timed_out'`, job); n != 1 {
		t.Fatal("job not timed_out")
	}
}

func TestSettingsVersionConflictAndIfMatch(t *testing.T) {
	e := setup(t)
	srv := e.api()
	cur, err := e.settings.GetCore(e.ctx)
	if err != nil {
		t.Fatal(err)
	}
	put := func(base int, ifMatch string) *http.Response {
		body := fmt.Sprintf(`{"values":{"default_language":"en","scheduler":{"max_concurrent_productions":2},"review":{"max_rounds":3},"callbacks":{"base_url":"http://core:8080"}},"base_version":%d}`, base)
		req, _ := http.NewRequest(http.MethodPut, srv.URL+"/internal/v1/modules/core/settings", bytes.NewReader([]byte(body)))
		req.Header.Set("Authorization", "Bearer mfa_test_admin_token_xxxxxxxx")
		req.Header.Set("Content-Type", "application/json")
		if ifMatch != "" {
			req.Header.Set("If-Match", ifMatch)
		}
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		return res
	}
	res := put(cur.Version, "")
	if res.StatusCode != 201 {
		t.Fatalf("put: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	res = put(cur.Version, "") // stale base_version
	if res.StatusCode != 409 || problemCode(t, res) != "settings_version_conflict" {
		t.Fatalf("conflict: %d", res.StatusCode)
	}
	cur2, _ := e.settings.GetCore(e.ctx)
	res = put(cur2.Version, `"999"`)
	if res.StatusCode != 412 || problemCode(t, res) != "version_mismatch" {
		t.Fatalf("if-match: %d %s", res.StatusCode, problemCode(t, res))
	}
}

func TestCancelLiveJob(t *testing.T) {
	e := setup(t)
	job, _ := e.startedJob()
	if err := e.eng.CancelJob(e.ctx, job, "stop"); err != nil {
		t.Fatal(err)
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status = 'cancelled'`, job); n != 1 {
		t.Fatal("not cancelled")
	}
	if n := e.count(`SELECT count(*) FROM variants WHERE attention->>'reason' = 'cancelled_by_admin'`); n != 1 {
		t.Fatal("variant attention missing")
	}
	if err := e.eng.CancelJob(e.ctx, job, "again"); err != engine.ErrInvalidState {
		t.Fatalf("second cancel: %v", err)
	}
}

func TestDispatchedAfterConfirm(t *testing.T) {
	e := setup(t)
	e.startedJob()
	r := e.relay("w1")
	r.OnSent = func(ctx context.Context, id uuid.UUID, body []byte) {
		_ = e.eng.MarkDispatched(ctx, body)
	}
	if n, err := r.RunOnce(e.ctx, e.conn); err != nil || n != 1 {
		t.Fatalf("relay: %d %v", n, err)
	}
	var status string
	var deadline *time.Time
	_ = e.pool.QueryRow(e.ctx, `SELECT status, deadline FROM jobs`).Scan(&status, &deadline)
	if status != "dispatched" || deadline == nil {
		t.Fatalf("status=%s deadline=%v", status, deadline)
	}
}

func TestReviewApproveCreatesPublishIntents(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	account := uuid.Must(uuid.NewV7())
	e.exec(`INSERT INTO platform_accounts (id, channel_id, platform, handle, enabled)
		VALUES ($1, 'itim', 'instagram', '@itim', true)`, account)
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{"output": videoStageOutput("approve"), "artifacts": []any{}})
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
	if n := e.count(`SELECT count(*) FROM publish_intents WHERE platform_account_id = $1 AND generation = 1 AND status = 'pending'`, account); n != 1 {
		t.Fatalf("intents=%d", n)
	}
	if n := e.count(`SELECT count(*) FROM content_revisions WHERE approved_round = 1`); n != 1 {
		t.Fatal("revision not approved")
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE stage_id = 'publish' AND status = 'queued'`); n != 1 {
		t.Fatal("publish job missing")
	}
	var req []byte
	if err := e.pool.QueryRow(e.ctx, `SELECT request FROM jobs WHERE stage_id = 'publish'`).Scan(&req); err != nil {
		t.Fatal(err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(req, &parsed); err != nil {
		t.Fatal(err)
	}
	input, _ := parsed["input"].(map[string]any)
	intents, _ := input["intents"].([]any)
	if len(intents) != 1 {
		t.Fatalf("request intents=%v", input["intents"])
	}
	// Idempotent: replaying the same approved result body should not create a second intent.
	res = e.postCallback(srv, "revmod", "result", rev, rf, map[string]any{
		"output": map[string]any{
			"decision": "approved", "reviewer": map[string]any{"telegram_user_id": 1},
			"decided_at": "2026-01-01T00:00:00Z", "round": 1,
		},
		"artifacts": []any{},
	})
	if res.StatusCode != 200 {
		t.Fatalf("dup approve: %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM publish_intents`); n != 1 {
		t.Fatalf("intents after dup=%d", n)
	}
}

func TestSystemSettingsIncludeInstagramLimits(t *testing.T) {
	e := setup(t)
	lim, err := e.settings.InstagramLimits(e.ctx)
	if err != nil {
		t.Fatal(err)
	}
	if lim.MaxCaptionChars != 2200 || lim.MaxHashtags != 30 {
		t.Fatalf("%+v", lim)
	}
}

func TestVideoResultCreatesContentRevision(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{
		"output": videoStageOutput("snap"), "artifacts": []any{},
	})
	if res.StatusCode != 200 {
		t.Fatalf("%d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM content_revisions`); n != 1 {
		t.Fatalf("revisions=%d", n)
	}
	var body []byte
	if err := e.pool.QueryRow(e.ctx, `SELECT body FROM content_revisions`).Scan(&body); err != nil {
		t.Fatal(err)
	}
	var parsed map[string]any
	if err := json.Unmarshal(body, &parsed); err != nil {
		t.Fatal(err)
	}
	meta, _ := parsed["metadata"].(map[string]any)
	if meta == nil || meta["title"] != "t-snap" {
		t.Fatalf("metadata missing in revision: %#v", parsed)
	}
	if n := e.count(`SELECT count(*) FROM events WHERE type = 'content_revision.created'`); n != 1 {
		t.Fatal("audit event missing")
	}
}

func TestVideoResultWithoutMetadataRejected(t *testing.T) {
	e := setup(t)
	job, fence := e.startedJob()
	srv := e.api()
	res := e.postCallback(srv, "vidmod", "result", job, fence, map[string]any{
		"output": map[string]any{"variants": []any{map[string]any{"language": "en", "video": map[string]any{"ref": "s3://x"}}}}, "artifacts": []any{},
	})
	if res.StatusCode != 422 || problemCode(t, res) != "output_invalid" {
		t.Fatalf("want 422 output_invalid, got %d %s", res.StatusCode, problemCode(t, res))
	}
	res.Body.Close()
	if n := e.count(`SELECT count(*) FROM content_revisions`); n != 0 {
		t.Fatal("must not create revision")
	}
	if n := e.count(`SELECT count(*) FROM jobs WHERE id = $1 AND status IN ('queued','dispatched','running')`, job); n != 1 {
		t.Fatal("job must stay live on invalid output")
	}
}
