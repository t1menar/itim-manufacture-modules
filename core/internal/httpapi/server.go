// Package httpapi serves probes and the module-facing internal API (core-04 §3–§4 subset).
package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/t1menar/manufacture/core/internal/auth"
	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/settings"
)

// Check reports whether one dependency is usable.
type Check func(ctx context.Context) error

type Server struct {
	Checks   map[string]Check
	Auth     *auth.Authenticator
	Engine   *engine.Engine
	Settings *settings.Store
	MaxBody  int64
}

func problem(w http.ResponseWriter, status int, code, title string) {
	w.Header().Set("Content-Type", "application/problem+json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"type": "urn:manufacture:problem:" + code, "title": title, "status": status, "code": code,
	})
}

func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	mux.HandleFunc("GET /ready", s.ready)

	mux.HandleFunc("POST /internal/v1/jobs/{job_id}/progress", s.requireModule(s.progress))
	mux.HandleFunc("POST /internal/v1/jobs/{job_id}/result", s.requireModule(s.result))
	mux.HandleFunc("POST /internal/v1/jobs/{job_id}/fail", s.requireModule(s.fail))
	mux.HandleFunc("GET /internal/v1/modules/self/settings", s.requireModule(s.ownSettings))
	mux.HandleFunc("PUT /internal/v1/modules/{id}/settings", s.requireAdmin(s.putSettings))
	mux.HandleFunc("GET /internal/v1/modules/{id}/settings", s.requireAdmin(s.getSettings))

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

type ctxKey int

const principalKey ctxKey = 1

func (s *Server) requireModule(next http.HandlerFunc) http.HandlerFunc {
	return s.require(next, true, false)
}
func (s *Server) requireAdmin(next http.HandlerFunc) http.HandlerFunc {
	return s.require(next, false, true)
}

func (s *Server) require(next http.HandlerFunc, allowModule, allowAdmin bool) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if s.Auth == nil {
			problem(w, http.StatusServiceUnavailable, "not_ready", "auth not configured")
			return
		}
		p, err := s.Auth.FromRequest(r.Context(), r.Header.Get("Authorization"))
		if errors.Is(err, auth.ErrUnauthorized) {
			problem(w, http.StatusUnauthorized, "unauthorized", "missing or unknown token")
			return
		}
		if err != nil {
			problem(w, http.StatusInternalServerError, "internal", "auth lookup failed")
			return
		}
		if p.Kind == auth.KindAdmin && !allowAdmin {
			problem(w, http.StatusForbidden, "forbidden", "admin token is not allowed on this route")
			return
		}
		if p.Kind == auth.KindModule && !allowModule {
			problem(w, http.StatusForbidden, "forbidden", "module token is not allowed on this route")
			return
		}
		next(w, r.WithContext(context.WithValue(r.Context(), principalKey, p)))
	}
}

func principal(r *http.Request) auth.Principal {
	p, _ := r.Context().Value(principalKey).(auth.Principal)
	return p
}

func (s *Server) readJSON(w http.ResponseWriter, r *http.Request, dst any) bool {
	max := s.MaxBody
	if max <= 0 {
		max = 256 << 10
	}
	r.Body = http.MaxBytesReader(w, r.Body, max)
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	if err := dec.Decode(dst); err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "request body is invalid")
		return false
	}
	// reject trailing junk
	if err := dec.Decode(&struct{}{}); err != io.EOF {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "request body is invalid")
		return false
	}
	return true
}

func (s *Server) parseJobFence(w http.ResponseWriter, r *http.Request) (uuid.UUID, int, bool) {
	id, err := uuid.Parse(r.PathValue("job_id"))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "job_id must be a uuid")
		return uuid.Nil, 0, false
	}
	raw := r.Header.Get("X-Fence")
	if raw == "" {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "X-Fence header is required")
		return uuid.Nil, 0, false
	}
	fence, err := strconv.Atoi(raw)
	if err != nil || fence < 1 {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "X-Fence must be a positive integer")
		return uuid.Nil, 0, false
	}
	return id, fence, true
}

func (s *Server) mapCallbackErr(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, engine.ErrForbiddenJob):
		problem(w, http.StatusForbidden, "forbidden", "module does not own this job")
	case errors.Is(err, engine.ErrJobNotCurrent):
		problem(w, http.StatusConflict, "job_not_current", "job is not current for this callback")
	case errors.Is(err, engine.ErrJobTerminal):
		problem(w, http.StatusConflict, "job_terminal", "job already has a different terminal callback")
	case errors.Is(err, engine.ErrOutputInvalid):
		problem(w, http.StatusUnprocessableEntity, "output_invalid", "result does not match stage output schema or job checks")
	case errors.Is(err, engine.ErrValidation):
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "request body is invalid")
	default:
		problem(w, http.StatusInternalServerError, "internal", "callback failed")
	}
}

func (s *Server) progress(w http.ResponseWriter, r *http.Request) {
	jobID, fence, ok := s.parseJobFence(w, r)
	if !ok {
		return
	}
	var body engine.ProgressBody
	if !s.readJSON(w, r, &body) {
		return
	}
	out, err := s.Engine.ApplyProgress(r.Context(), principal(r).ModuleID, jobID, fence, body)
	if err != nil {
		s.mapCallbackErr(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"cancel_requested": out.CancelRequested})
}

func (s *Server) result(w http.ResponseWriter, r *http.Request) {
	jobID, fence, ok := s.parseJobFence(w, r)
	if !ok {
		return
	}
	var body engine.ResultBody
	if !s.readJSON(w, r, &body) {
		return
	}
	_, err := s.Engine.ApplyResult(r.Context(), principal(r).ModuleID, jobID, fence, body)
	if err != nil {
		s.mapCallbackErr(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"status": "accepted"})
}

func (s *Server) fail(w http.ResponseWriter, r *http.Request) {
	jobID, fence, ok := s.parseJobFence(w, r)
	if !ok {
		return
	}
	var body engine.FailBody
	if !s.readJSON(w, r, &body) {
		return
	}
	out, err := s.Engine.ApplyFail(r.Context(), principal(r).ModuleID, jobID, fence, body)
	if err != nil {
		s.mapCallbackErr(w, err)
		return
	}
	writeJSON(w, 200, map[string]any{"status": "accepted", "will_retry": out.WillRetry})
}

func (s *Server) ownSettings(w http.ResponseWriter, r *http.Request) {
	p := principal(r)
	cur, err := s.Settings.GetModule(r.Context(), p.ModuleID)
	if errors.Is(err, settings.ErrNotFound) {
		// Modules without a saved version get an empty valid document at version 0.
		writeJSON(w, 200, map[string]any{"module_id": p.ModuleID, "version": 0, "values": map[string]any{}, "valid": true})
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "settings read failed")
		return
	}
	etag := strconv.Quote(strconv.Itoa(cur.Version))
	if match := r.Header.Get("If-None-Match"); match != "" && strings.Contains(match, etag) {
		w.WriteHeader(http.StatusNotModified)
		return
	}
	w.Header().Set("ETag", etag)
	writeJSON(w, 200, map[string]any{"module_id": cur.Owner, "version": cur.Version, "values": json.RawMessage(cur.Values), "valid": cur.Valid, "created_at": cur.CreatedAt})
}

func (s *Server) getSettings(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var cur settings.Current
	var err error
	if id == "core" || id == "admin-api" {
		cur, err = s.Settings.GetCore(r.Context())
		if id == "admin-api" {
			problem(w, http.StatusNotImplemented, "not_implemented", "admin-api settings not implemented yet")
			return
		}
	} else {
		cur, err = s.Settings.GetModule(r.Context(), id)
	}
	if errors.Is(err, settings.ErrNotFound) {
		problem(w, http.StatusNotFound, "not_found", "settings not found")
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "settings read failed")
		return
	}
	w.Header().Set("ETag", strconv.Quote(strconv.Itoa(cur.Version)))
	writeJSON(w, 200, map[string]any{"owner": cur.Owner, "version": cur.Version, "values": json.RawMessage(cur.Values), "valid": cur.Valid})
}

func (s *Server) putSettings(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id != "core" {
		problem(w, http.StatusNotImplemented, "not_implemented", "only core settings writes are implemented in this slice")
		return
	}
	var body struct {
		Values      json.RawMessage `json:"values"`
		BaseVersion int             `json:"base_version"`
		Comment     string          `json:"comment"`
	}
	if !s.readJSON(w, r, &body) {
		return
	}
	if len(body.Values) == 0 || body.Values[0] != '{' {
		problem(w, http.StatusUnprocessableEntity, "settings_invalid", "values must be an object")
		return
	}
	// C34: If-Match mismatch → 412 (settings also keep base_version → 409).
	if im := r.Header.Get("If-Match"); im != "" {
		cur, err := s.Settings.GetCore(r.Context())
		if err != nil {
			problem(w, http.StatusInternalServerError, "internal", "settings read failed")
			return
		}
		want := strconv.Quote(strconv.Itoa(cur.Version))
		if im != want && im != strconv.Itoa(cur.Version) {
			problem(w, http.StatusPreconditionFailed, "version_mismatch", "If-Match does not match current rev")
			return
		}
	}
	cur, err := s.Settings.PutCore(r.Context(), body.Values, body.BaseVersion, "admin-api", body.Comment)
	if errors.Is(err, settings.ErrVersionConflict) {
		problem(w, http.StatusConflict, "settings_version_conflict", "base_version is not current")
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "settings write failed")
		return
	}
	w.Header().Set("ETag", strconv.Quote(strconv.Itoa(cur.Version)))
	writeJSON(w, 201, map[string]any{"owner": cur.Owner, "version": cur.Version, "values": json.RawMessage(cur.Values), "valid": cur.Valid})
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
