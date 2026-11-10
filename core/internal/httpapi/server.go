// Package httpapi serves probes and the module-facing internal API (core-04 §3–§4 subset).
package httpapi

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/auth"
	"github.com/t1menar/manufacture/core/internal/credentials"
	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/modules"
	"github.com/t1menar/manufacture/core/internal/publish"
	"github.com/t1menar/manufacture/core/internal/settings"
)

// Check reports whether one dependency is usable.
type Check func(ctx context.Context) error

type Server struct {
	Checks      map[string]Check
	Auth        *auth.Authenticator
	Engine      *engine.Engine
	Settings    *settings.Store
	Modules     *modules.Registry
	Credentials *credentials.Store
	Publish     *publish.Store
	MaxBody     int64
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
	mux.HandleFunc("POST /internal/v1/modules/self/heartbeat", s.requireModule(s.heartbeat))
	mux.HandleFunc("PUT /internal/v1/modules/{id}/settings", s.requireAdmin(s.putSettings))
	mux.HandleFunc("GET /internal/v1/modules/{id}/settings", s.requireAdmin(s.getSettings))
	mux.HandleFunc("POST /internal/v1/modules", s.requireAdmin(s.registerModule))
	mux.HandleFunc("POST /internal/v1/modules/{id}/token", s.requireAdmin(s.rotateToken))
	mux.HandleFunc("POST /internal/v1/modules/{id}/activate", s.requireAdmin(s.activateModule))
	mux.HandleFunc("GET /internal/v1/credentials/{ref}", s.requireModule(s.readCredential))
	mux.HandleFunc("POST /internal/v1/publish-intents/{id}/republish", s.requireAdmin(s.republish))
	mux.HandleFunc("POST /internal/v1/modules/{id}/deactivate", s.requireAdmin(s.deactivateModule))
	mux.HandleFunc("POST /internal/v1/variants/{id}/retry", s.requireAdmin(s.retryVariant))
	mux.HandleFunc("POST /internal/v1/variants/{id}/skip", s.requireAdmin(s.skipVariant))
	mux.HandleFunc("GET /internal/v1/modules", s.requireAdmin(s.listModules))
	mux.HandleFunc("GET /internal/v1/modules/{id}", s.requireAdmin(s.getModule))
	mux.HandleFunc("GET /internal/v1/overview", s.requireAdmin(s.overview))
	mux.HandleFunc("GET /internal/v1/productions", s.requireAdmin(s.listProductions))
	mux.HandleFunc("GET /internal/v1/productions/{id}", s.requireAdmin(s.getProduction))
	mux.HandleFunc("GET /internal/v1/jobs/{id}", s.requireAdmin(s.getJob))
	mux.HandleFunc("POST /internal/v1/jobs/{id}/cancel", s.requireAdmin(s.cancelJob))

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

func (s *Server) heartbeat(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	if err := s.Modules.Heartbeat(r.Context(), principal(r).ModuleID); err != nil {
		problem(w, http.StatusNotFound, "not_found", "module not found")
		return
	}
	writeJSON(w, 200, map[string]any{"status": "ok"})
}

func (s *Server) registerModule(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	var body struct {
		ID       string        `json:"id"`
		Name     string        `json:"name"`
		Stage    string        `json:"stage"`
		Endpoint string        `json:"endpoint"`
		Enabled  *bool         `json:"enabled"`
		Manifest *modules.Info `json:"manifest"`
	}
	if !s.readJSON(w, r, &body) {
		return
	}
	m, err := s.Modules.Register(r.Context(), modules.RegisterOpts{
		ID: body.ID, Name: body.Name, Stage: body.Stage, Endpoint: body.Endpoint,
		Enabled: body.Enabled, Manifest: body.Manifest,
	})
	switch {
	case errors.Is(err, modules.ErrValidation):
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "invalid module registration")
	case errors.Is(err, modules.ErrAlreadyExists):
		problem(w, http.StatusConflict, "already_exists", "module id exists with different endpoint or stage")
	case errors.Is(err, modules.ErrStageMismatch):
		problem(w, http.StatusUnprocessableEntity, "module_stage_mismatch", "stage not listed in manifest")
	case errors.Is(err, modules.ErrContract):
		problem(w, http.StatusUnprocessableEntity, "module_contract_unsupported", "unsupported contract version")
	case err != nil:
		problem(w, http.StatusInternalServerError, "internal", "registration failed")
	default:
		status := 201
		if m.Token == "" {
			status = 200 // idempotent replay
		}
		writeJSON(w, status, m)
	}
}

func (s *Server) rotateToken(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	raw, prefix, exp, err := s.Modules.RotateToken(r.Context(), r.PathValue("id"))
	if errors.Is(err, modules.ErrNotFound) {
		problem(w, http.StatusNotFound, "not_found", "module not found")
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "token rotation failed")
		return
	}
	writeJSON(w, 200, map[string]any{"token": raw, "token_prefix": prefix, "prev_token_expires_at": exp.UTC().Format(time.RFC3339)})
}

func (s *Server) activateModule(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	var body struct {
		Replace bool `json:"replace"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	if err := s.Modules.Activate(r.Context(), r.PathValue("id"), body.Replace); err != nil {
		if errors.Is(err, modules.ErrNotFound) {
			problem(w, http.StatusNotFound, "not_found", "module not found")
			return
		}
		problem(w, http.StatusConflict, "module_not_ready", err.Error())
		return
	}
	writeJSON(w, 200, map[string]any{"id": r.PathValue("id"), "active": true})
}

func (s *Server) readCredential(w http.ResponseWriter, r *http.Request) {
	if s.Credentials == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "credentials not configured")
		return
	}
	ref := r.PathValue("ref")
	var jobID *uuid.UUID
	if raw := r.Header.Get("X-Job-Id"); raw != "" {
		id, err := uuid.Parse(raw)
		if err != nil {
			problem(w, http.StatusUnprocessableEntity, "validation_failed", "X-Job-Id must be a uuid")
			return
		}
		jobID = &id
	}
	value, meta, err := s.Credentials.Read(r.Context(), ref, principal(r).ModuleID, jobID)
	switch {
	case errors.Is(err, credentials.ErrNotFound):
		problem(w, http.StatusNotFound, "credential_not_found", "unknown credential ref")
	case errors.Is(err, credentials.ErrNotAllowed):
		problem(w, http.StatusForbidden, "credential_not_allowed", "module is not allowed to read this credential")
	case err != nil:
		problem(w, http.StatusInternalServerError, "internal", "credential read failed")
	default:
		var exp any
		if meta.ExpiresAt != nil {
			exp = meta.ExpiresAt.UTC().Format(time.RFC3339)
		}
		writeJSON(w, 200, map[string]any{"ref": meta.Ref, "kind": meta.Kind, "value": value, "expires_at": exp})
	}
}

func (s *Server) republish(w http.ResponseWriter, r *http.Request) {
	if s.Publish == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "publish intents not configured")
		return
	}
	intentID, err := uuid.Parse(r.PathValue("id"))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "id must be a uuid")
		return
	}
	var body struct {
		Reason                 string     `json:"reason"`
		BaseGeneration         int        `json:"base_generation"`
		AcknowledgeUnknownRisk bool       `json:"acknowledge_unknown_risk"`
		ContentRevisionID      *uuid.UUID `json:"content_revision_id"`
	}
	raw, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 64<<10))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "request body is invalid")
		return
	}
	if err := json.Unmarshal(raw, &body); err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "request body is invalid")
		return
	}
	sum := sha256.Sum256(raw)
	actor := "admin-api"
	if a := r.Header.Get("X-Admin-Actor"); a != "" {
		actor = "user:" + a
	}
	res, err := s.Publish.Republish(r.Context(), publish.RepublishOpts{
		IntentID: intentID, Reason: body.Reason, BaseGeneration: body.BaseGeneration,
		AcknowledgeUnknownRisk: body.AcknowledgeUnknownRisk, ContentRevisionID: body.ContentRevisionID,
		Actor: actor, IdempotencyKey: r.Header.Get("Idempotency-Key"),
		IdempotencyPath: r.URL.Path, IdempotencyBodyHash: sum[:],
	})
	switch {
	case errors.Is(err, publish.ErrValidation):
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "reason is required (non-whitespace, max 2000) and base_generation must be set")
	case errors.Is(err, publish.ErrNotFound):
		problem(w, http.StatusNotFound, "not_found", "publish intent not found")
	case errors.Is(err, publish.ErrGenerationConflict):
		problem(w, http.StatusConflict, "generation_conflict", "base_generation is not current")
	case errors.Is(err, publish.ErrInvalidState):
		problem(w, http.StatusConflict, "invalid_state", "current intent is pending or in_progress")
	case errors.Is(err, publish.ErrUnknownNeedsAck):
		problem(w, http.StatusConflict, "unknown_needs_ack", "acknowledge_unknown_risk is required when current status is unknown")
	case errors.Is(err, publish.ErrIdempotencyReuse):
		problem(w, http.StatusUnprocessableEntity, "idempotency_key_reused", "Idempotency-Key was used with a different body")
	case err != nil:
		problem(w, http.StatusInternalServerError, "internal", "republish failed")
	default:
		if res.Idempotent {
			w.Header().Set("Idempotent-Replayed", "true")
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(res.HTTPStatus)
			_, _ = w.Write(res.HTTPResponse)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(201)
		_, _ = w.Write(res.HTTPResponse)
	}
}

func (s *Server) deactivateModule(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	if err := s.Modules.Deactivate(r.Context(), r.PathValue("id")); err != nil {
		if errors.Is(err, modules.ErrNotFound) {
			problem(w, http.StatusNotFound, "not_found", "module not found")
			return
		}
		problem(w, http.StatusInternalServerError, "internal", "deactivate failed")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (s *Server) retryVariant(w http.ResponseWriter, r *http.Request) {
	if s.Engine == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "engine not configured")
		return
	}
	id, err := uuid.Parse(r.PathValue("id"))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "id must be a uuid")
		return
	}
	actor := r.Header.Get("X-Admin-Actor")
	var jobID uuid.UUID
	err = db.WithTx(r.Context(), s.Engine.Pool, func(tx pgx.Tx) error {
		var e error
		jobID, e = s.Engine.RetryVariant(r.Context(), tx, id)
		if e != nil {
			return e
		}
		_, e = tx.Exec(r.Context(), `INSERT INTO events (production_id, variant_id, job_id, type, actor, payload)
			SELECT production_id, $1::uuid, $2::uuid, 'variant.retry_requested', $3::text,
				jsonb_build_object('variant_id', $4::text)
			FROM variants WHERE id = $1::uuid`, id, jobID, adminActor(actor), id.String())
		return e
	})
	if errors.Is(err, engine.ErrInvalidState) {
		problem(w, http.StatusConflict, "invalid_state", "variant is not needs_attention")
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "retry failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"job_id": jobID})
}

func (s *Server) skipVariant(w http.ResponseWriter, r *http.Request) {
	if s.Engine == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "engine not configured")
		return
	}
	id, err := uuid.Parse(r.PathValue("id"))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "id must be a uuid")
		return
	}
	var body struct {
		Reason string `json:"reason"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	reason := strings.TrimSpace(body.Reason)
	if reason == "" {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "reason is required")
		return
	}
	actor := r.Header.Get("X-Admin-Actor")
	err = db.WithTx(r.Context(), s.Engine.Pool, func(tx pgx.Tx) error {
		if err := s.Engine.SkipVariant(r.Context(), tx, id, reason); err != nil {
			return err
		}
		_, err := tx.Exec(r.Context(), `INSERT INTO events (production_id, variant_id, type, actor, payload)
			SELECT production_id, $1::uuid, 'variant.skip_requested', $2::text, jsonb_build_object('reason', $3::text)
			FROM variants WHERE id = $1::uuid`, id, adminActor(actor), reason)
		return err
	})
	if errors.Is(err, engine.ErrInvalidState) {
		problem(w, http.StatusConflict, "invalid_state", "variant is not needs_attention")
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "skip failed")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func adminActor(raw string) string {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "admin"
	}
	for _, pfx := range []string{"user:", "tg:", "local:", "deploy:"} {
		if strings.HasPrefix(raw, pfx) {
			return raw
		}
	}
	return "user:" + raw
}
