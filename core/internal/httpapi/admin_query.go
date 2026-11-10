package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/engine"
	"github.com/t1menar/manufacture/core/internal/modules"
)

func (s *Server) listModules(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	list, err := s.Modules.List(r.Context())
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "list modules failed")
		return
	}
	if list == nil {
		list = []modules.Module{}
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": list})
}

func (s *Server) getModule(w http.ResponseWriter, r *http.Request) {
	if s.Modules == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "module registry not configured")
		return
	}
	m, err := s.Modules.Get(r.Context(), r.PathValue("id"))
	if errors.Is(err, modules.ErrNotFound) {
		problem(w, http.StatusNotFound, "not_found", "module not found")
		return
	}
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "get module failed")
		return
	}
	writeJSON(w, http.StatusOK, m)
}

func (s *Server) overview(w http.ResponseWriter, r *http.Request) {
	if s.Engine == nil || s.Engine.Pool == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "engine not configured")
		return
	}
	ctx := r.Context()
	pool := s.Engine.Pool
	counts := func(table string) (map[string]int, error) {
		rows, err := pool.Query(ctx, `SELECT status, count(*) FROM `+table+` GROUP BY status`)
		if err != nil {
			return nil, err
		}
		defer rows.Close()
		out := map[string]int{}
		for rows.Next() {
			var st string
			var n int
			if err := rows.Scan(&st, &n); err != nil {
				return nil, err
			}
			out[st] = n
		}
		return out, rows.Err()
	}
	productions, err := counts("productions")
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "overview failed")
		return
	}
	jobs, err := counts("jobs")
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "overview failed")
		return
	}
	variants, err := counts("variants")
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "overview failed")
		return
	}
	var pendingOutbox int
	_ = pool.QueryRow(ctx, `SELECT count(*) FROM outbox WHERE status = 'pending'`).Scan(&pendingOutbox)
	var mods []modules.Module
	if s.Modules != nil {
		mods, err = s.Modules.List(ctx)
		if err != nil {
			problem(w, http.StatusInternalServerError, "internal", "overview failed")
			return
		}
	}
	if mods == nil {
		mods = []modules.Module{}
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"productions":    productions,
		"jobs":           jobs,
		"variants":       variants,
		"outbox_pending": pendingOutbox,
		"modules":        mods,
	})
}

func (s *Server) listProductions(w http.ResponseWriter, r *http.Request) {
	if s.Engine == nil || s.Engine.Pool == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "engine not configured")
		return
	}
	q := r.URL.Query()
	limit := 50
	if v := q.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 200 {
			problem(w, http.StatusUnprocessableEntity, "validation_failed", "limit must be 1–200")
			return
		}
		limit = n
	}
	status := strings.TrimSpace(q.Get("status"))
	cursor := strings.TrimSpace(q.Get("cursor"))
	args := []any{}
	where := []string{"true"}
	if status != "" {
		args = append(args, status)
		where = append(where, "status = $"+strconv.Itoa(len(args)))
	}
	if cursor != "" {
		id, err := uuid.Parse(cursor)
		if err != nil {
			problem(w, http.StatusUnprocessableEntity, "validation_failed", "cursor must be a uuid")
			return
		}
		args = append(args, id)
		where = append(where, "id < $"+strconv.Itoa(len(args)))
	}
	args = append(args, limit+1)
	sql := `SELECT id, idea_id, idea_ref, idea_rev, run_no, pipeline_id, status, language, started_at, finished_at, rev
		FROM productions WHERE ` + strings.Join(where, " AND ") + `
		ORDER BY started_at DESC, id DESC LIMIT $` + strconv.Itoa(len(args))
	rows, err := s.Engine.Pool.Query(r.Context(), sql, args...)
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "list productions failed")
		return
	}
	defer rows.Close()
	items := make([]map[string]any, 0)
	for rows.Next() {
		var id uuid.UUID
		var ideaID int64
		var ideaRef, pipelineID, status, language string
		var ideaRev, runNo, rev int
		var started, finished any
		if err := rows.Scan(&id, &ideaID, &ideaRef, &ideaRev, &runNo, &pipelineID, &status, &language, &started, &finished, &rev); err != nil {
			problem(w, http.StatusInternalServerError, "internal", "list productions failed")
			return
		}
		items = append(items, map[string]any{
			"id": id, "idea_id": ideaID, "idea_ref": ideaRef, "idea_rev": ideaRev,
			"run_no": runNo, "pipeline_id": pipelineID, "status": status, "language": language,
			"started_at": started, "finished_at": finished, "rev": rev,
		})
	}
	if err := rows.Err(); err != nil {
		problem(w, http.StatusInternalServerError, "internal", "list productions failed")
		return
	}
	var next any
	if len(items) > limit {
		items = items[:limit]
		next = items[len(items)-1]["id"]
	}
	writeJSON(w, http.StatusOK, map[string]any{"items": items, "next_cursor": next})
}

func (s *Server) getProduction(w http.ResponseWriter, r *http.Request) {
	if s.Engine == nil || s.Engine.Pool == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "engine not configured")
		return
	}
	id, err := uuid.Parse(r.PathValue("id"))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "id must be a uuid")
		return
	}
	ctx := r.Context()
	row := s.Engine.Pool.QueryRow(ctx, `SELECT id, idea_id, idea_ref, idea_rev, run_no, pipeline_id, status, language,
		started_at, finished_at, rev, pipeline_snapshot FROM productions WHERE id = $1`, id)
	var prod map[string]any
	{
		var pid uuid.UUID
		var ideaID int64
		var ideaRef, pipelineID, status, language string
		var ideaRev, runNo, rev int
		var started, finished, snap any
		if err := row.Scan(&pid, &ideaID, &ideaRef, &ideaRev, &runNo, &pipelineID, &status, &language, &started, &finished, &rev, &snap); err != nil {
			if errors.Is(err, pgx.ErrNoRows) {
				problem(w, http.StatusNotFound, "not_found", "production not found")
				return
			}
			problem(w, http.StatusInternalServerError, "internal", "get production failed")
			return
		}
		prod = map[string]any{
			"id": pid, "idea_id": ideaID, "idea_ref": ideaRef, "idea_rev": ideaRev,
			"run_no": runNo, "pipeline_id": pipelineID, "status": status, "language": language,
			"started_at": started, "finished_at": finished, "rev": rev, "pipeline_snapshot": snap,
		}
	}
	vrows, err := s.Engine.Pool.Query(ctx, `SELECT id, language, status, position, channels, attention, rev
		FROM variants WHERE production_id = $1 ORDER BY position, id`, id)
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "get production failed")
		return
	}
	variants := []map[string]any{}
	for vrows.Next() {
		var vid uuid.UUID
		var lang, status string
		var pos, rev int
		var channels, attention any
		if err := vrows.Scan(&vid, &lang, &status, &pos, &channels, &attention, &rev); err != nil {
			vrows.Close()
			problem(w, http.StatusInternalServerError, "internal", "get production failed")
			return
		}
		variants = append(variants, map[string]any{
			"id": vid, "language": lang, "status": status, "position": pos,
			"channels": channels, "attention": attention, "rev": rev,
		})
	}
	vrows.Close()
	jrows, err := s.Engine.Pool.Query(ctx, `SELECT id, variant_id, stage_id, module_id, position, attempt, status,
		mode, fence, cancel_requested, error, progress, created_at, updated_at, finished_at, rev
		FROM jobs WHERE production_id = $1 ORDER BY position, attempt, id`, id)
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "get production failed")
		return
	}
	jobs := []map[string]any{}
	for jrows.Next() {
		var jid uuid.UUID
		var variant, module any
		var stage, status, mode string
		var pos, attempt, fence, rev int
		var cancel bool
		var errBody, progress, created, updated, finished any
		if err := jrows.Scan(&jid, &variant, &stage, &module, &pos, &attempt, &status, &mode, &fence, &cancel, &errBody, &progress, &created, &updated, &finished, &rev); err != nil {
			jrows.Close()
			problem(w, http.StatusInternalServerError, "internal", "get production failed")
			return
		}
		jobs = append(jobs, map[string]any{
			"id": jid, "variant_id": variant, "stage_id": stage, "module_id": module,
			"position": pos, "attempt": attempt, "status": status, "mode": mode, "fence": fence,
			"cancel_requested": cancel, "error": errBody, "progress": progress,
			"created_at": created, "updated_at": updated, "finished_at": finished, "rev": rev,
		})
	}
	jrows.Close()
	erows, err := s.Engine.Pool.Query(ctx, `SELECT id, variant_id, job_id, type, actor, payload, at
		FROM events WHERE production_id = $1 ORDER BY id DESC LIMIT 100`, id)
	if err != nil {
		problem(w, http.StatusInternalServerError, "internal", "get production failed")
		return
	}
	events := []map[string]any{}
	for erows.Next() {
		var eid int64
		var typ, actor string
		var variantID, jobID, payload, at any
		if err := erows.Scan(&eid, &variantID, &jobID, &typ, &actor, &payload, &at); err != nil {
			erows.Close()
			problem(w, http.StatusInternalServerError, "internal", "get production failed")
			return
		}
		events = append(events, map[string]any{
			"id": eid, "variant_id": variantID, "job_id": jobID, "type": typ, "actor": actor, "payload": payload, "at": at,
		})
	}
	erows.Close()
	prod["variants"] = variants
	prod["jobs"] = jobs
	prod["events"] = events
	writeJSON(w, http.StatusOK, prod)
}

func (s *Server) getJob(w http.ResponseWriter, r *http.Request) {
	if s.Engine == nil || s.Engine.Pool == nil {
		problem(w, http.StatusNotImplemented, "not_implemented", "engine not configured")
		return
	}
	id, err := uuid.Parse(r.PathValue("id"))
	if err != nil {
		problem(w, http.StatusUnprocessableEntity, "validation_failed", "id must be a uuid")
		return
	}
	row := s.Engine.Pool.QueryRow(r.Context(), `SELECT id, production_id, variant_id, stage_id, module_id, position, attempt,
		chain_id, try, max_attempts, mode, status, fence, timeout_s, cancel_requested, request, output, error, progress,
		created_at, updated_at, finished_at, rev FROM jobs WHERE id = $1`, id)
	var jid, prod, chain uuid.UUID
	var variant, module, request, output, errBody, progress, created, updated, finished any
	var stage, mode, status string
	var pos, attempt, tryN, maxA, fence, timeout, rev int
	var cancel bool
	if err := row.Scan(&jid, &prod, &variant, &stage, &module, &pos, &attempt, &chain, &tryN, &maxA, &mode, &status, &fence, &timeout, &cancel, &request, &output, &errBody, &progress, &created, &updated, &finished, &rev); err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			problem(w, http.StatusNotFound, "not_found", "job not found")
			return
		}
		problem(w, http.StatusInternalServerError, "internal", "get job failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"id": jid, "production_id": prod, "variant_id": variant, "stage_id": stage, "module_id": module,
		"position": pos, "attempt": attempt, "chain_id": chain, "try": tryN, "max_attempts": maxA,
		"mode": mode, "status": status, "fence": fence, "timeout_s": timeout, "cancel_requested": cancel,
		"request": request, "output": output, "error": errBody, "progress": progress,
		"created_at": created, "updated_at": updated, "finished_at": finished, "rev": rev,
	})
}

func (s *Server) cancelJob(w http.ResponseWriter, r *http.Request) {
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
	_ = readJSONAllowEmpty(r, &body)
	reason := strings.TrimSpace(body.Reason)
	if reason == "" {
		reason = "cancelled by admin"
	}
	if err := s.Engine.CancelJob(r.Context(), id, reason); err != nil {
		if errors.Is(err, engine.ErrInvalidState) {
			problem(w, http.StatusConflict, "invalid_state", "job is not live")
			return
		}
		problem(w, http.StatusInternalServerError, "internal", "cancel failed")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func readJSONAllowEmpty(r *http.Request, dst any) error {
	if r.Body == nil {
		return nil
	}
	dec := json.NewDecoder(r.Body)
	if err := dec.Decode(dst); err != nil && !errors.Is(err, io.EOF) {
		return err
	}
	return nil
}
