package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/t1menar/manufacture/admin-api/internal/bootstrap"
	"github.com/t1menar/manufacture/admin-api/internal/upstream"
)

func testServer(t *testing.T, core, video http.Handler) *httpapiServer {
	t.Helper()
	var coreURL, videoURL string
	if core != nil {
		s := httptest.NewServer(core)
		t.Cleanup(s.Close)
		coreURL = s.URL
	}
	if video != nil {
		s := httptest.NewServer(video)
		t.Cleanup(s.Close)
		videoURL = s.URL
	}
	cfg := bootstrap.Config{
		AllowedHosts:    []string{"localhost", "127.0.0.1"},
		Actor:           "local:admin",
		UpstreamTimeout: 2 * time.Second,
	}
	up := upstream.New(coreURL, "mfa_test_admin_token_xxxxxxxx", "local:admin", 2*time.Second)
	up.SetModule("video", videoURL, "mft_video_test")
	return &httpapiServer{Srv: &Server{Cfg: cfg, Up: up}}
}

type httpapiServer struct{ Srv *Server }

func (h *httpapiServer) do(t *testing.T, method, path, host, origin, body string) *httptest.ResponseRecorder {
	t.Helper()
	var rdr io.Reader
	if body != "" {
		rdr = strings.NewReader(body)
	}
	req := httptest.NewRequest(method, path, rdr)
	if host != "" {
		req.Host = host
	}
	if origin != "" {
		req.Header.Set("Origin", origin)
	}
	if body != "" {
		req.Header.Set("Content-Type", "application/json")
	}
	rec := httptest.NewRecorder()
	h.Srv.Handler().ServeHTTP(rec, req)
	return rec
}

func TestHealthAndHostAllowlist(t *testing.T) {
	h := testServer(t, nil, nil)
	rec := h.do(t, "GET", "/health", "evil.example", "", "")
	if rec.Code != 200 {
		t.Fatalf("health must skip host check, got %d", rec.Code)
	}
	rec = h.do(t, "GET", "/api/v1/overview", "evil.example", "", "")
	if rec.Code != 403 {
		t.Fatalf("want 403 forbidden_host, got %d %s", rec.Code, rec.Body.String())
	}
	var p map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &p)
	if p["code"] != "forbidden_host" {
		t.Fatalf("code=%v", p["code"])
	}
	if rec.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatal("must not send CORS headers")
	}
	rec = h.do(t, "GET", "/api/v1/overview", "127.0.0.1:58084", "http://evil.example", "")
	if rec.Code != 403 {
		t.Fatalf("want 403 csrf, got %d %s", rec.Code, rec.Body.String())
	}
}

func TestProxyOverviewAndIdeasStub(t *testing.T) {
	core := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer mfa_test_admin_token_xxxxxxxx" {
			w.WriteHeader(401)
			return
		}
		if r.Header.Get("X-Admin-Actor") != "local:admin" {
			t.Errorf("missing actor")
		}
		if r.URL.Path != "/internal/v1/overview" {
			t.Errorf("path %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"jobs":{"running":1}}`))
	})
	video := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer mft_video_test" {
			w.WriteHeader(401)
			return
		}
		if r.URL.Path != "/admin/v1/ideas" {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"items":[{"id":1,"status":"draft"}]}`))
	})
	h := testServer(t, core, video)
	rec := h.do(t, "GET", "/api/v1/overview", "127.0.0.1:58084", "", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"running":1`) {
		t.Fatalf("overview: %d %s", rec.Code, rec.Body.String())
	}
	rec = h.do(t, "GET", "/api/v1/ideas", "localhost", "", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), `"draft"`) {
		t.Fatalf("ideas stub: %d %s", rec.Code, rec.Body.String())
	}
}

func TestDegradedModule(t *testing.T) {
	h := testServer(t, http.NotFoundHandler(), nil) // no video
	rec := h.do(t, "GET", "/api/v1/ideas", "127.0.0.1", "", "")
	if rec.Code != 503 {
		t.Fatalf("want 503, got %d %s", rec.Code, rec.Body.String())
	}
	var p map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &p)
	if p["code"] != "upstream_unavailable" || p["upstream"] != "video" {
		t.Fatalf("problem=%v", p)
	}
}

func TestLocalhostOriginAllowed(t *testing.T) {
	core := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(204)
	})
	h := testServer(t, core, nil)
	rec := h.do(t, "POST", "/api/v1/jobs/01900000-0000-7000-8000-000000000001/cancel", "127.0.0.1:58084", "http://127.0.0.1:58084", `{"reason":"x"}`)
	if rec.Code != 204 {
		t.Fatalf("cancel proxy: %d %s", rec.Code, rec.Body.String())
	}
}

func TestOpenAPIJSON(t *testing.T) {
	h := testServer(t, nil, nil)
	rec := h.do(t, "GET", "/api/v1/openapi.json", "127.0.0.1", "", "")
	if rec.Code != 200 {
		t.Fatalf("openapi: %d %s", rec.Code, rec.Body.String())
	}
	var doc map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &doc); err != nil {
		t.Fatal(err)
	}
	if doc["openapi"] != "3.0.3" {
		t.Fatalf("openapi field=%v", doc["openapi"])
	}
	paths, _ := doc["paths"].(map[string]any)
	if _, ok := paths["/api/v1/overview"]; !ok {
		t.Fatal("missing /api/v1/overview in openapi")
	}
}

func TestSPAServesIndexAndKeepsAPI404(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(dir+"/index.html", []byte("<!doctype html><title>panel</title>"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(dir+"/assets", 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(dir+"/assets/app.js", []byte("console.log(1)"), 0o644); err != nil {
		t.Fatal(err)
	}
	h := testServer(t, nil, nil)
	h.Srv.Cfg.UIDir = dir

	rec := h.do(t, "GET", "/", "127.0.0.1:58084", "", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "panel") {
		t.Fatalf("index: %d %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Header().Get("Content-Security-Policy"), "script-src 'self'") {
		t.Fatalf("csp=%s", rec.Header().Get("Content-Security-Policy"))
	}
	rec = h.do(t, "GET", "/ideas", "127.0.0.1:58084", "", "")
	if rec.Code != 200 || !strings.Contains(rec.Body.String(), "panel") {
		t.Fatalf("spa fallback: %d %s", rec.Code, rec.Body.String())
	}
	rec = h.do(t, "GET", "/assets/app.js", "127.0.0.1:58084", "", "")
	if rec.Code != 200 || rec.Body.String() != "console.log(1)" {
		t.Fatalf("asset: %d %s", rec.Code, rec.Body.String())
	}
	if rec.Header().Get("Cache-Control") != "public, max-age=31536000, immutable" {
		t.Fatalf("asset cache=%s", rec.Header().Get("Cache-Control"))
	}
	rec = h.do(t, "GET", "/api/v1/does-not-exist", "127.0.0.1:58084", "", "")
	if rec.Code != 404 {
		t.Fatalf("api 404: %d %s", rec.Code, rec.Body.String())
	}
	var p map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &p)
	if p["code"] != "not_found" {
		t.Fatalf("problem=%v", p)
	}
	rec = h.do(t, "GET", "/", "evil.example", "", "")
	if rec.Code != 403 {
		t.Fatalf("ui host check: %d", rec.Code)
	}
}
