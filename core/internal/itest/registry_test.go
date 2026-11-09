package itest

import (
	"bytes"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/t1menar/manufacture/core/internal/auth"
	"github.com/t1menar/manufacture/core/internal/credentials"
	"github.com/t1menar/manufacture/core/internal/crypto"
	"github.com/t1menar/manufacture/core/internal/httpapi"
	"github.com/t1menar/manufacture/core/internal/modules"
	"github.com/t1menar/manufacture/core/internal/prompts"
)

func (e *env) apiFull() *httptest.Server {
	e.t.Helper()
	srv := httptest.NewServer((&httpapi.Server{
		Auth: e.auth, Engine: e.eng, Settings: e.settings, Modules: e.reg, Credentials: e.creds,
	}).Handler())
	e.t.Cleanup(srv.Close)
	return srv
}

func TestRegisterIdempotentAndTokenRotate(t *testing.T) {
	e := setup(t)
	srv := e.apiFull()
	manifest := modules.Info{Name: "Video", Version: "0.1.0", Contract: 1, Stages: []string{"video"}, SettingsSchema: map[string]any{}}
	body := map[string]any{"id": "video-new", "name": "Video", "stage": "video", "endpoint": "http://127.0.0.1:9/video-new", "manifest": manifest}
	post := func() *http.Response {
		b, _ := json.Marshal(body)
		req, _ := http.NewRequest(http.MethodPost, srv.URL+"/internal/v1/modules", bytes.NewReader(b))
		req.Header.Set("Authorization", "Bearer mfa_test_admin_token_xxxxxxxx")
		req.Header.Set("Content-Type", "application/json")
		res, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		return res
	}
	res := post()
	if res.StatusCode != 201 {
		t.Fatalf("register: %d %s", res.StatusCode, problemCode(t, res))
	}
	var first struct{ Token string }
	_ = json.NewDecoder(res.Body).Decode(&first)
	res.Body.Close()
	if !strings.HasPrefix(first.Token, "mft_") {
		t.Fatal("token missing")
	}
	res = post()
	if res.StatusCode != 200 {
		t.Fatalf("idempotent: %d", res.StatusCode)
	}
	var second struct{ Token string }
	_ = json.NewDecoder(res.Body).Decode(&second)
	res.Body.Close()
	if second.Token != "" {
		t.Fatal("idempotent replay must not re-issue token")
	}
	req, _ := http.NewRequest(http.MethodPost, srv.URL+"/internal/v1/modules/video-new/token", nil)
	req.Header.Set("Authorization", "Bearer mfa_test_admin_token_xxxxxxxx")
	res, _ = http.DefaultClient.Do(req)
	var rot struct {
		Token string `json:"token"`
	}
	_ = json.NewDecoder(res.Body).Decode(&rot)
	res.Body.Close()
	if res.StatusCode != 200 || rot.Token == "" || rot.Token == first.Token {
		t.Fatalf("rotate: %d", res.StatusCode)
	}
	if _, err := e.auth.FromRequest(e.ctx, "Bearer "+first.Token); err != nil {
		t.Fatalf("old token during grace: %v", err)
	}
	time.Sleep(1100 * time.Millisecond)
	if _, err := e.auth.FromRequest(e.ctx, "Bearer "+first.Token); !errors.Is(err, auth.ErrUnauthorized) {
		t.Fatalf("old token after grace: %v", err)
	}
	if _, err := e.auth.FromRequest(e.ctx, "Bearer "+rot.Token); err != nil {
		t.Fatal(err)
	}
}

func TestHeartbeatTimeoutBlocksDispatch(t *testing.T) {
	e := setup(t)
	e.exec(`UPDATE modules SET last_seen_at = now() - interval '5 minutes', health = 'up' WHERE id = 'vidmod'`)
	n, err := e.reg.MarkOffline(e.ctx, 90*time.Second)
	if err != nil || n < 1 {
		t.Fatalf("mark offline: n=%d err=%v", n, err)
	}
	if e.count(`SELECT count(*) FROM modules WHERE id = 'vidmod' AND health = 'down'`) != 1 {
		t.Fatal("not down")
	}
	e.idea("offline module")
	if created, err := e.eng.Tick(e.ctx); err != nil || created != 1 {
		t.Fatalf("tick: %d %v", created, err)
	}
	if e.count(`SELECT count(*) FROM jobs WHERE status = 'queued' AND module_id IS NULL`) != 1 {
		t.Fatalf("expected queued job without module")
	}
	if e.count(`SELECT count(*) FROM outbox`) != 0 {
		t.Fatal("must not dispatch to down module")
	}
}

func TestCredentialsAccessControlAndCrypto(t *testing.T) {
	e := setup(t)
	var buf strings.Builder
	e.eng.Log = slog.New(slog.NewTextHandler(&buf, nil))
	secret := "super-secret-credential-value-xyz"
	_, err := e.creds.Put(e.ctx, credentials.PutOpts{
		Ref: "cred:test-key", Name: "Test", Kind: "api_key", Access: "module",
		AllowedModules: []string{"vidmod"}, Value: secret,
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, _, err := e.creds.Read(e.ctx, "cred:test-key", "revmod", nil); !errors.Is(err, credentials.ErrNotAllowed) {
		t.Fatalf("wrong module: %v", err)
	}
	val, _, err := e.creds.Read(e.ctx, "cred:test-key", "vidmod", nil)
	if err != nil || val != secret {
		t.Fatalf("read: %v %q", err, val)
	}
	if strings.Contains(buf.String(), secret) {
		t.Fatal("secret leaked into logs")
	}
	// tamper ciphertext
	var ct []byte
	_ = e.pool.QueryRow(e.ctx, `SELECT ciphertext FROM credentials WHERE ref = 'cred:test-key'`).Scan(&ct)
	ct[0] ^= 0xff
	e.exec(`UPDATE credentials SET ciphertext = $1 WHERE ref = 'cred:test-key'`, ct)
	_, _, err = e.creds.Read(e.ctx, "cred:test-key", "vidmod", nil)
	if err == nil || !errors.Is(err, crypto.ErrDecrypt) {
		t.Fatalf("want decrypt error, got %v", err)
	}
}

func TestPromptSnapshotAndActivation(t *testing.T) {
	e := setup(t)
	v1, err := e.prompts.Create(e.ctx, "vidmod", "script.main", "Hello {{name}}", "system", "v1", nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := e.prompts.Activate(e.ctx, "vidmod", "script.main", v1.Version, 0); err != nil {
		t.Fatal(err)
	}
	job, _ := e.startedJob()
	var snap []byte
	_ = e.pool.QueryRow(e.ctx, `SELECT request->'prompts' FROM jobs WHERE id = $1`, job).Scan(&snap)
	if !strings.Contains(string(snap), `"version": 1`) && !strings.Contains(string(snap), `"version":1`) {
		t.Fatalf("snapshot missing v1: %s", snap)
	}
	v2, err := e.prompts.Create(e.ctx, "vidmod", "script.main", "Hi {{name}}", "system", "v2", nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := e.prompts.Activate(e.ctx, "vidmod", "script.main", v2.Version, v1.Version); err != nil {
		t.Fatal(err)
	}
	// old job unchanged
	var snap2 []byte
	_ = e.pool.QueryRow(e.ctx, `SELECT request->'prompts' FROM jobs WHERE id = $1`, job).Scan(&snap2)
	if string(snap) != string(snap2) {
		t.Fatal("activating a new version rewrote an existing job snapshot")
	}
	// concurrent activation → one active
	v3, _ := e.prompts.Create(e.ctx, "vidmod", "script.main", "Hey {{name}}", "system", "v3", nil)
	v4, _ := e.prompts.Create(e.ctx, "vidmod", "script.main", "Yo {{name}}", "system", "v4", nil)
	var wg sync.WaitGroup
	for _, ver := range []int{v3.Version, v4.Version} {
		wg.Add(1)
		go func(ver int) {
			defer wg.Done()
			_ = e.prompts.Activate(e.ctx, "vidmod", "script.main", ver, 0)
		}(ver)
	}
	wg.Wait()
	if e.count(`SELECT count(*) FROM prompts WHERE owner_module = 'vidmod' AND prompt_id = 'script.main' AND active`) != 1 {
		t.Fatal("more than one active prompt version")
	}
	if _, err := prompts.Render("Hello {{name}}", map[string]string{}); !errors.Is(err, prompts.ErrUnknownVar) {
		t.Fatalf("unknown var: %v", err)
	}
	out, err := prompts.Render("Hello {{name}}", map[string]string{"name": "Tim"})
	if err != nil || out != "Hello Tim" {
		t.Fatalf("render: %q %v", out, err)
	}
	// If-Match style conflict
	cur, _ := e.prompts.Active(e.ctx, "vidmod", "script.main")
	if err := e.prompts.Activate(e.ctx, "vidmod", "script.main", v1.Version, cur.Version+99); !errors.Is(err, prompts.ErrVersionConflict) {
		t.Fatalf("want version conflict, got %v", err)
	}
}
