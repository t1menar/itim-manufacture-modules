package httpapi

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"io"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/t1menar/manufacture/admin-api/internal/audit"
	"github.com/t1menar/manufacture/admin-api/internal/bootstrap"
	"github.com/t1menar/manufacture/admin-api/internal/problem"
	"github.com/t1menar/manufacture/admin-api/internal/upstream"
)

type Server struct {
	Cfg   bootstrap.Config
	Up    *upstream.Client
	Audit audit.Sink
	Log   *slog.Logger
	Ready func() error
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", s.health)
	mux.HandleFunc("GET /ready", s.ready)
	mux.HandleFunc("GET /api/v1/openapi.json", s.openapi)

	// core-backed
	mux.HandleFunc("GET /api/v1/overview", s.getCore("/internal/v1/overview"))
	mux.HandleFunc("GET /api/v1/modules", s.getCore("/internal/v1/modules"))
	mux.HandleFunc("GET /api/v1/modules/{id}", s.getCoreID("/internal/v1/modules/"))
	mux.HandleFunc("GET /api/v1/productions", s.getCore("/internal/v1/productions"))
	mux.HandleFunc("GET /api/v1/productions/{id}", s.getCoreID("/internal/v1/productions/"))
	mux.HandleFunc("GET /api/v1/jobs/{id}", s.getCoreID("/internal/v1/jobs/"))
	mux.HandleFunc("POST /api/v1/jobs/{id}/cancel", s.postCoreID("/internal/v1/jobs/", "/cancel", "job.cancel"))
	mux.HandleFunc("POST /api/v1/variants/{id}/retry", s.postCoreID("/internal/v1/variants/", "/retry", "variant.retry"))
	mux.HandleFunc("POST /api/v1/variants/{id}/skip", s.postCoreID("/internal/v1/variants/", "/skip", "variant.skip"))
	mux.HandleFunc("POST /api/v1/publish-intents/{id}/republish", s.postCoreID("/internal/v1/publish-intents/", "/republish", "intent.republish"))

	// video — existing + documented ideas/topics contract
	s.moduleProxy(mux, "video", []proxyRoute{
		{"GET", "/api/v1/video/prompts", "/admin/v1/prompts", "video.prompts.read"},
		{"GET", "/api/v1/video/prompts/audit", "/admin/v1/prompts/audit", "video.prompts.audit"},
		{"GET", "/api/v1/video/prompts/{step}/{version}", "/admin/v1/prompts/{step}/{version}", "video.prompts.read"},
		{"POST", "/api/v1/video/prompts/{step}", "/admin/v1/prompts/{step}", "video.prompts.write"},
		{"PUT", "/api/v1/video/prompts/{step}/active", "/admin/v1/prompts/{step}/active", "video.prompts.activate"},
		{"GET", "/api/v1/video/credentials", "/admin/v1/credentials", "video.credentials.read"},
		{"PUT", "/api/v1/video/credentials/{ref}", "/admin/v1/credentials/{ref}", "video.credentials.write"},
		{"DELETE", "/api/v1/video/credentials/{ref}", "/admin/v1/credentials/{ref}", "video.credentials.delete"},
		{"GET", "/api/v1/topics", "/admin/v1/topics", "topics.read"},
		{"POST", "/api/v1/topics", "/admin/v1/topics", "topics.write"},
		{"GET", "/api/v1/topics/{id}", "/admin/v1/topics/{id}", "topics.read"},
		{"PATCH", "/api/v1/topics/{id}", "/admin/v1/topics/{id}", "topics.write"},
		{"DELETE", "/api/v1/topics/{id}", "/admin/v1/topics/{id}", "topics.delete"},
		{"GET", "/api/v1/ideas", "/admin/v1/ideas", "ideas.read"},
		{"POST", "/api/v1/ideas", "/admin/v1/ideas", "ideas.write"},
		{"GET", "/api/v1/ideas/{id}", "/admin/v1/ideas/{id}", "ideas.read"},
		{"PATCH", "/api/v1/ideas/{id}", "/admin/v1/ideas/{id}", "ideas.write"},
		{"DELETE", "/api/v1/ideas/{id}", "/admin/v1/ideas/{id}", "ideas.delete"},
		{"POST", "/api/v1/ideas/{id}/ready", "/admin/v1/ideas/{id}/ready", "ideas.ready"},
		{"POST", "/api/v1/ideas/{id}/queue", "/admin/v1/ideas/{id}/queue", "ideas.queue"},
	})

	s.moduleProxy(mux, "review", []proxyRoute{
		{"GET", "/api/v1/review/secrets", "/admin/v1/secrets", "review.secrets.read"},
		{"PUT", "/api/v1/review/secrets/{key}", "/admin/v1/secrets/{key}", "review.secrets.write"},
		{"DELETE", "/api/v1/review/secrets/{key}", "/admin/v1/secrets/{key}", "review.secrets.delete"},
		{"GET", "/api/v1/review/runs", "/admin/v1/runs", "review.runs.read"},
		{"GET", "/api/v1/review/pending", "/admin/v1/pending", "review.pending.read"},
	})

	s.moduleProxy(mux, "publish", []proxyRoute{
		{"GET", "/api/v1/publish/accounts", "/admin/v1/accounts", "publish.accounts.read"},
		{"POST", "/api/v1/publish/accounts", "/admin/v1/accounts", "publish.accounts.write"},
		{"PATCH", "/api/v1/publish/accounts/{id}", "/admin/v1/accounts/{id}", "publish.accounts.write"},
		{"PUT", "/api/v1/publish/accounts/{id}/token", "/admin/v1/accounts/{id}/token", "publish.accounts.token"},
		{"GET", "/api/v1/publish/intents", "/admin/v1/intents", "publish.intents.read"},
		{"GET", "/api/v1/publish/intents/{id}", "/admin/v1/intents/{id}", "publish.intents.read"},
		{"GET", "/api/v1/publish/secrets", "/admin/v1/secrets", "publish.secrets.read"},
		{"PUT", "/api/v1/publish/secrets/{key}", "/admin/v1/secrets/{key}", "publish.secrets.write"},
		{"DELETE", "/api/v1/publish/secrets/{key}", "/admin/v1/secrets/{key}", "publish.secrets.delete"},
	})

	mux.HandleFunc("GET /api/v1/audit", s.listAudit)
	if s.Cfg.UIDir != "" {
		mux.Handle("/", s.spa(s.Cfg.UIDir))
	} else {
		mux.HandleFunc("/", s.notFound)
	}

	return s.wrap(mux)
}

func (s *Server) wrap(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		setSecurityHeaders(w)
		reqID := r.Header.Get("X-Request-Id")
		if reqID == "" {
			reqID = newID()
		}
		w.Header().Set("X-Request-Id", reqID)
		r = r.WithContext(context.WithValue(r.Context(), ctxReqID, reqID))

		if r.URL.Path != "/health" && r.URL.Path != "/ready" {
			if !s.hostAllowed(r.Host) {
				problem.Write(w, http.StatusForbidden, "forbidden_host", "Host is not allowed", r.Host, reqID)
				return
			}
			if origin := r.Header.Get("Origin"); origin != "" && !s.originAllowed(origin) {
				problem.Write(w, http.StatusForbidden, "csrf_invalid", "Origin is not allowed", "", reqID)
				s.audit(r, "security.origin_denied", "denied", 403, "csrf_invalid")
				return
			}
		}
		// Never emit CORS * (and no CORS headers at all).
		next.ServeHTTP(w, r)
	})
}

type ctxKey int

const ctxReqID ctxKey = 1

func requestID(r *http.Request) string {
	if v, ok := r.Context().Value(ctxReqID).(string); ok {
		return v
	}
	return ""
}

func setSecurityHeaders(w http.ResponseWriter) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
	w.Header().Set("Referrer-Policy", "no-referrer")
}

func (s *Server) hostAllowed(host string) bool {
	h, _, err := net.SplitHostPort(host)
	if err != nil {
		h = host
	}
	h = strings.Trim(strings.ToLower(h), "[]")
	for _, a := range s.Cfg.AllowedHosts {
		aa := strings.Trim(strings.ToLower(a), "[]")
		if h == aa {
			return true
		}
	}
	return false
}

func (s *Server) originAllowed(origin string) bool {
	// origin is scheme://host[:port]
	origin = strings.TrimRight(origin, "/")
	if i := strings.Index(origin, "://"); i >= 0 {
		return s.hostAllowed(origin[i+3:])
	}
	return false
}

func (s *Server) health(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"status":"ok"}`))
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	if s.Ready != nil {
		if err := s.Ready(); err != nil {
			problem.Write(w, http.StatusServiceUnavailable, "not_ready", "not ready", err.Error(), requestID(r))
			return
		}
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write([]byte(`{"ready":true}`))
}

func (s *Server) notFound(w http.ResponseWriter, r *http.Request) {
	problem.Write(w, http.StatusNotFound, "not_found", "not found", r.URL.Path, requestID(r))
}

func (s *Server) listAudit(w http.ResponseWriter, r *http.Request) {
	if s.Audit == nil {
		problem.Write(w, http.StatusServiceUnavailable, "audit_unavailable", "audit store is not configured", "", requestID(r))
		return
	}
	limit := 50
	items, err := s.Audit.List(r.Context(), limit)
	if err != nil {
		problem.Write(w, http.StatusServiceUnavailable, "audit_unavailable", "audit query failed", "", requestID(r))
		return
	}
	writeJSON(w, 200, map[string]any{"items": items})
	s.audit(r, "audit.read", "ok", 200, "")
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func newID() string {
	var b [8]byte
	_, _ = rand.Read(b[:])
	return hex.EncodeToString(b[:])
}

func (s *Server) audit(r *http.Request, action, outcome string, status int, code string) {
	if s.Audit == nil {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = s.Audit.Write(ctx, audit.Row{
		Actor: s.Cfg.Actor, Action: action, Outcome: outcome,
		HTTPStatus: status, ProblemCode: code, RequestID: requestID(r),
		ResourceType: resourceType(r),
		ResourceID:   resourceID(r),
	})
}

func resourceType(r *http.Request) string {
	parts := strings.Split(strings.Trim(strings.TrimPrefix(r.URL.Path, "/api/v1/"), "/"), "/")
	if len(parts) >= 2 {
		return parts[1]
	}
	if len(parts) == 1 {
		return parts[0]
	}
	return ""
}

func resourceID(r *http.Request) string {
	return r.PathValue("id") + r.PathValue("ref") + r.PathValue("key") + r.PathValue("step")
}

func (s *Server) auditOrFail(w http.ResponseWriter, r *http.Request, action string) bool {
	if s.Audit == nil {
		return true
	}
	if err := s.Audit.Write(r.Context(), audit.Row{
		Actor: s.Cfg.Actor, Action: action, Outcome: "ok", HTTPStatus: 0, RequestID: requestID(r),
		ResourceType: resourceType(r),
		ResourceID:   resourceID(r),
		// Details stay empty: secret values must never enter the audit log.
	}); err != nil {
		problem.Write(w, http.StatusServiceUnavailable, "audit_unavailable", "cannot record audit", "", requestID(r))
		return false
	}
	return true
}

type proxyRoute struct {
	Method, Public, Upstream, Action string
}

func (s *Server) moduleProxy(mux *http.ServeMux, stage string, routes []proxyRoute) {
	for _, rt := range routes {
		rt := rt
		mux.HandleFunc(rt.Method+" "+rt.Public, func(w http.ResponseWriter, r *http.Request) {
			path := expandPath(rt.Upstream, r)
			if r.URL.RawQuery != "" {
				path += "?" + r.URL.RawQuery
			}
			var body []byte
			if r.Body != nil && r.Method != http.MethodGet {
				body, _ = io.ReadAll(io.LimitReader(r.Body, 1<<20))
			}
			if r.Method != http.MethodGet && r.Method != http.MethodHead {
				if !s.auditOrFail(w, r, rt.Action) {
					return
				}
			}
			res := s.Up.DoModule(r.Context(), stage, r.Method, path, body, nil)
			s.forward(w, r, res, stage, rt.Action)
		})
	}
}

func (s *Server) getCore(path string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		p := path
		if r.URL.RawQuery != "" {
			p += "?" + r.URL.RawQuery
		}
		res := s.Up.DoCore(r.Context(), http.MethodGet, p, nil, nil)
		s.forward(w, r, res, "core", "core.read")
	}
}

func (s *Server) getCoreID(prefix string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		res := s.Up.DoCore(r.Context(), http.MethodGet, prefix+r.PathValue("id"), nil, nil)
		s.forward(w, r, res, "core", "core.read")
	}
}

func (s *Server) postCoreID(prefix, suffix, action string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !s.auditOrFail(w, r, action) {
			return
		}
		body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
		res := s.Up.DoCore(r.Context(), http.MethodPost, prefix+r.PathValue("id")+suffix, body, nil)
		s.forward(w, r, res, "core", action)
	}
}

func (s *Server) forward(w http.ResponseWriter, r *http.Request, res upstream.Result, upstreamName, action string) {
	reqID := requestID(r)
	if res.Unavailable {
		problem.WriteUpstream(w, http.StatusServiceUnavailable, "upstream_unavailable", "upstream is unavailable", "", reqID, upstreamName)
		s.audit(r, action, "error", 503, "upstream_unavailable")
		return
	}
	if res.Err != nil {
		problem.WriteUpstream(w, http.StatusGatewayTimeout, "upstream_timeout", "upstream call failed", "", reqID, upstreamName)
		s.audit(r, action, "error", 504, "upstream_timeout")
		return
	}
	ct := "application/json"
	if res.Header != nil {
		if v := res.Header.Get("Content-Type"); v != "" {
			ct = v
		}
	}
	// Map unexpected 401/403 from core/modules (misconfigured token) to 502, not user auth.
	if res.Status == http.StatusUnauthorized || res.Status == http.StatusForbidden {
		problem.WriteUpstream(w, http.StatusBadGateway, "upstream_error", "upstream rejected the admin-api credentials", "", reqID, upstreamName)
		s.audit(r, action, "error", 502, "upstream_error")
		return
	}
	w.Header().Set("Content-Type", ct)
	w.WriteHeader(res.Status)
	_, _ = w.Write(res.Body)
	outcome := "ok"
	if res.Status >= 400 {
		outcome = "error"
	}
	s.audit(r, action, outcome, res.Status, "")
}

func expandPath(tmpl string, r *http.Request) string {
	out := tmpl
	for _, name := range []string{"id", "ref", "key", "step", "version"} {
		if v := r.PathValue(name); v != "" {
			out = strings.ReplaceAll(out, "{"+name+"}", v)
		}
	}
	return out
}

func (s *Server) openapi(w http.ResponseWriter, r *http.Request) {
	body, err := OpenAPIJSON()
	if err != nil {
		problem.Write(w, http.StatusInternalServerError, "internal", "openapi unavailable", "", requestID(r))
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(body)
}
