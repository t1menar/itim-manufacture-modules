// Package httpapi serves the probes. The internal API of core-04 §2-§4 is not implemented in
// this slice; its routes answer 501 not_implemented instead of pretending to work.
package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"time"
)

// Check reports whether one dependency is usable.
type Check func(ctx context.Context) error

type Server struct {
	Checks map[string]Check
}

func problem(w http.ResponseWriter, status int, code, title string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"type": "urn:manufacture:problem:" + code, "title": title, "status": status, "code": code})
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.HandleFunc("GET /ready", s.ready)
	mux.HandleFunc("/internal/", func(w http.ResponseWriter, _ *http.Request) {
		problem(w, http.StatusNotImplemented, "not_implemented", "This endpoint is specified in core-04 but not implemented yet")
	})
	return mux
}

func (s *Server) ready(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	checks := map[string]string{}
	ok := true
	for name, c := range s.Checks {
		if err := c(ctx); err != nil {
			checks[name] = "unavailable"
			ok = false
		} else {
			checks[name] = "ok"
		}
	}
	w.Header().Set("Content-Type", "application/json")
	body := map[string]any{"status": "ready", "checks": checks}
	if !ok {
		body["status"] = "not_ready"
		w.WriteHeader(http.StatusServiceUnavailable)
	}
	_ = json.NewEncoder(w).Encode(body)
}
