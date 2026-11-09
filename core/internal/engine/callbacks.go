package engine

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/t1menar/manufacture/core/internal/db"
	"github.com/t1menar/manufacture/core/internal/messaging"
)

// Callback errors map to HTTP problem codes (core-04 §3, §10).
var (
	ErrJobNotCurrent = errors.New("job_not_current")
	ErrJobTerminal   = errors.New("job_terminal")
	ErrOutputInvalid = errors.New("output_invalid")
	ErrValidation    = errors.New("validation_failed")
	ErrForbiddenJob  = errors.New("forbidden")
)

var nonWS = regexp.MustCompile(`\S`)

type ProgressBody struct {
	Percent int    `json:"percent"`
	Step    string `json:"step"`
	Message string `json:"message,omitempty"`
}

type ResultBody struct {
	Output    json.RawMessage `json:"output"`
	Artifacts []any           `json:"artifacts"`
	Metrics   map[string]any  `json:"metrics,omitempty"`
}

type FailBody struct {
	Class   string         `json:"class"`
	Message string         `json:"message"`
	Details map[string]any `json:"details,omitempty"`
}

type CallbackOutcome struct {
	CancelRequested bool
	WillRetry       bool
	Duplicate       bool
}

// ApplyProgress handles POST .../progress. First progress moves dispatched → running.
func (e *Engine) ApplyProgress(ctx context.Context, moduleID string, jobID uuid.UUID, fence int, body ProgressBody) (CallbackOutcome, error) {
	if body.Percent < 0 || body.Percent > 100 || strings.TrimSpace(body.Step) == "" || len(body.Step) > 64 {
		return CallbackOutcome{}, ErrValidation
	}
	raw, _ := json.Marshal(body)
	var out CallbackOutcome
	err := db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		j, err := e.lockJob(ctx, tx, jobID)
		if err != nil {
			return err
		}
		if err := e.gateCallback(j, moduleID, fence); err != nil {
			return err
		}
		msgID := callbackMessageID(jobID, "progress", raw)
		dup, err := insertInbox(ctx, tx, "http.callbacks", msgID, "job.progress")
		if err != nil {
			return err
		}
		if dup {
			out.Duplicate = true
			out.CancelRequested = j.cancelRequested
			return nil
		}
		started := ""
		if j.status == "dispatched" || j.status == "queued" || j.status == "dispatching" {
			started = `, started_at = coalesce(started_at, now())`
		}
		q := fmt.Sprintf(`UPDATE jobs SET status = 'running', progress = $2, rev = rev + 1, updated_at = now()%s WHERE id = $1`, started)
		if _, err := tx.Exec(ctx, q, j.id, raw); err != nil {
			return err
		}
		out.CancelRequested = j.cancelRequested
		return e.event(ctx, tx, j.liveJob, "job.progress", map[string]any{"step": body.Step})
	})
	return out, err
}

// ApplyResult handles POST .../result. Invalid output → ErrOutputInvalid (job stays live).
func (e *Engine) ApplyResult(ctx context.Context, moduleID string, jobID uuid.UUID, fence int, body ResultBody) (CallbackOutcome, error) {
	if len(body.Output) == 0 || body.Output[0] != '{' {
		return CallbackOutcome{}, ErrOutputInvalid
	}
	if body.Artifacts == nil {
		return CallbackOutcome{}, ErrValidation
	}
	raw, _ := json.Marshal(body)
	var out CallbackOutcome
	err := db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		j, err := e.lockJob(ctx, tx, jobID)
		if err != nil {
			return err
		}
		// Terminal job: identical body → 200; different → 409 job_terminal.
		if !liveStatuses[j.status] {
			if j.terminalBodyEqual(raw) {
				out.Duplicate = true
				return nil
			}
			return ErrJobTerminal
		}
		if err := e.gateCallback(j, moduleID, fence); err != nil {
			return err
		}
		if err := e.validateResultOutput(ctx, tx, j, body.Output); err != nil {
			return err
		}
		msgID := callbackMessageID(jobID, "result", raw)
		dup, err := insertInbox(ctx, tx, "http.callbacks", msgID, "job.succeeded")
		if err != nil {
			return err
		}
		if dup {
			out.Duplicate = true
			return nil
		}
		if _, err := tx.Exec(ctx, `UPDATE jobs SET status = 'succeeded', output = $2, finished_at = now(), rev = rev + 1, updated_at = now() WHERE id = $1`,
			j.id, body.Output); err != nil {
			return err
		}
		if err := e.event(ctx, tx, j.liveJob, "job.succeeded", nil); err != nil {
			return err
		}
		return e.afterSuccess(ctx, tx, j, body.Output)
	})
	return out, err
}

// ApplyFail handles POST .../fail.
func (e *Engine) ApplyFail(ctx context.Context, moduleID string, jobID uuid.UUID, fence int, body FailBody) (CallbackOutcome, error) {
	if body.Class != "transient" && body.Class != "fatal" && body.Class != "blocked" {
		return CallbackOutcome{}, ErrValidation
	}
	if strings.TrimSpace(body.Message) == "" || len(body.Message) > 2000 {
		return CallbackOutcome{}, ErrValidation
	}
	raw, _ := json.Marshal(body)
	var out CallbackOutcome
	err := db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		j, err := e.lockJob(ctx, tx, jobID)
		if err != nil {
			return err
		}
		if !liveStatuses[j.status] {
			if j.terminalBodyEqual(raw) {
				out.Duplicate = true
				return nil
			}
			return ErrJobTerminal
		}
		if err := e.gateCallback(j, moduleID, fence); err != nil {
			return err
		}
		msgID := callbackMessageID(jobID, "fail", raw)
		dup, err := insertInbox(ctx, tx, "http.callbacks", msgID, "job.failed")
		if err != nil {
			return err
		}
		if dup {
			out.Duplicate = true
			out.WillRetry = body.Class == "transient" && j.try < j.maxTries
			return nil
		}
		if _, err := tx.Exec(ctx, `UPDATE jobs SET status = 'failed', error = $2, finished_at = now(), rev = rev + 1, updated_at = now() WHERE id = $1`,
			j.id, raw); err != nil {
			return err
		}
		if err := e.event(ctx, tx, j.liveJob, "job.failed", map[string]any{"class": body.Class}); err != nil {
			return err
		}
		out.WillRetry = body.Class == "transient" && j.try < j.maxTries
		return e.onFailure(ctx, tx, j.liveJob, body.Class)
	})
	return out, err
}

type jobRow struct {
	liveJob
	cancelRequested bool
	round           int
	mode            string
	errorJSON       []byte
	outputJSON      []byte
}

func (j jobRow) terminalBodyEqual(raw []byte) bool {
	// Fail callbacks store the full body in jobs.error.
	if len(j.errorJSON) > 0 {
		return jsonEqual(j.errorJSON, raw)
	}
	// Result callbacks store only the output object in jobs.output.
	if len(j.outputJSON) > 0 {
		var incoming ResultBody
		if err := json.Unmarshal(raw, &incoming); err != nil {
			return false
		}
		return jsonEqual(j.outputJSON, incoming.Output)
	}
	return false
}

func jsonEqual(a, b []byte) bool {
	var x, y any
	if json.Unmarshal(a, &x) != nil || json.Unmarshal(b, &y) != nil {
		return false
	}
	ab, _ := json.Marshal(x)
	bb, _ := json.Marshal(y)
	return string(ab) == string(bb)
}

func (e *Engine) lockJob(ctx context.Context, tx pgx.Tx, jobID uuid.UUID) (jobRow, error) {
	var j jobRow
	var snap []byte
	err := tx.QueryRow(ctx, `SELECT j.id, j.production_id, j.variant_id, j.stage_id, j.module_id, j.position, j.chain_id, j.try, j.max_attempts,
			j.fence, j.status, j.cancel_requested, j.round, j.mode, coalesce(j.error, 'null'::jsonb), coalesce(j.output, 'null'::jsonb),
			p.pipeline_snapshot, i.id, i.text, p.language
		FROM jobs j JOIN productions p ON p.id = j.production_id JOIN ideas i ON i.id = p.idea_id
		WHERE j.id = $1 FOR UPDATE OF j`, jobID).
		Scan(&j.id, &j.production, &j.variant, &j.stageID, &j.moduleID, &j.position, &j.chain, &j.try, &j.maxTries,
			&j.fence, &j.status, &j.cancelRequested, &j.round, &j.mode, &j.errorJSON, &j.outputJSON,
			&snap, &j.ideaID, &j.ideaText, &j.language)
	if errors.Is(err, pgx.ErrNoRows) {
		return j, ErrJobNotCurrent
	}
	if err != nil {
		return j, err
	}
	if err := json.Unmarshal(snap, &j.snapshot); err != nil {
		return j, err
	}
	if string(j.errorJSON) == "null" {
		j.errorJSON = nil
	}
	if string(j.outputJSON) == "null" {
		j.outputJSON = nil
	}
	return j, nil
}

func (e *Engine) gateCallback(j jobRow, moduleID string, fence int) error {
	if j.moduleID == nil || *j.moduleID != moduleID {
		return ErrForbiddenJob
	}
	if fence != j.fence || !liveStatuses[j.status] {
		return ErrJobNotCurrent
	}
	return nil
}

func insertInbox(ctx context.Context, tx pgx.Tx, consumer string, id uuid.UUID, typ string) (duplicate bool, err error) {
	tag, err := tx.Exec(ctx, `INSERT INTO inbox (consumer, message_id, type, outcome) VALUES ($1, $2, $3, 'applied') ON CONFLICT DO NOTHING`,
		consumer, id, typ)
	if err != nil {
		return false, err
	}
	return tag.RowsAffected() == 0, nil
}

func callbackMessageID(jobID uuid.UUID, kind string, body []byte) uuid.UUID {
	sum := sha256.Sum256(append(append(jobID[:], kind...), body...))
	return uuid.NewSHA1(uuid.NameSpaceOID, sum[:])
}

func (e *Engine) validateResultOutput(ctx context.Context, tx pgx.Tx, j jobRow, output json.RawMessage) error {
	// Stage-specific checks for this slice. Full JSON Schema validation is a later slice.
	if j.stageID == "review" {
		var o struct {
			Decision string  `json:"decision"`
			Reason   *string `json:"reason"`
			Round    int     `json:"round"`
		}
		if err := json.Unmarshal(output, &o); err != nil || (o.Decision != "approved" && o.Decision != "rejected") {
			return ErrOutputInvalid
		}
		if o.Decision == "rejected" {
			if o.Reason == nil || !nonWS.MatchString(*o.Reason) {
				return ErrOutputInvalid
			}
		}
		wantRound := j.round
		if wantRound == 0 {
			wantRound = 1
		}
		if o.Round != 0 && o.Round != wantRound {
			return ErrOutputInvalid
		}
	}
	return nil
}

// afterSuccess advances the pipeline, or runs the review revise loop when decision=rejected.
func (e *Engine) afterSuccess(ctx context.Context, tx pgx.Tx, j jobRow, output json.RawMessage) error {
	if j.stageID == "review" {
		return e.afterReview(ctx, tx, j, output)
	}
	// A revise video job succeeding should create a new review round, not skip ahead.
	if j.mode == "revise" {
		return e.afterRevise(ctx, tx, j)
	}
	return e.advance(ctx, tx, j.liveJob)
}

func (e *Engine) afterReview(ctx context.Context, tx pgx.Tx, j jobRow, output json.RawMessage) error {
	var o struct {
		Decision  string          `json:"decision"`
		Reason    *string         `json:"reason"`
		Reviewer  json.RawMessage `json:"reviewer"`
		DecidedAt time.Time       `json:"decided_at"`
		Round     int             `json:"round"`
	}
	if err := json.Unmarshal(output, &o); err != nil {
		return err
	}
	round := o.Round
	if round == 0 {
		round = j.round
		if round == 0 {
			round = 1
		}
	}
	if j.variant == nil {
		return fmt.Errorf("review job without variant")
	}
	rid, _ := uuid.NewV7()
	var reason any
	if o.Reason != nil {
		reason = *o.Reason
	}
	reviewer := o.Reviewer
	if len(reviewer) == 0 {
		reviewer = []byte(`{}`)
	}
	decided := o.DecidedAt
	if decided.IsZero() {
		decided = time.Now().UTC()
	}
	if _, err := tx.Exec(ctx, `INSERT INTO review_rounds (id, variant_id, job_id, round, decision, reason, reviewer, decided_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`, rid, *j.variant, j.id, round, o.Decision, reason, reviewer, decided); err != nil {
		return err
	}
	if o.Decision == "approved" {
		if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'approved', rev = rev + 1 WHERE id = $1`, *j.variant); err != nil {
			return err
		}
		return e.advance(ctx, tx, j.liveJob)
	}
	// rejected → revise or needs_attention max_rounds
	var reviewRound, extra, maxOverride *int
	if err := tx.QueryRow(ctx, `SELECT review_round, extra_rounds, max_rounds FROM variants WHERE id = $1 FOR UPDATE`, *j.variant).
		Scan(&reviewRound, &extra, &maxOverride); err != nil {
		return err
	}
	_ = reviewRound
	limit := e.reviewMaxRounds
	if e.Settings != nil {
		if r, err := e.Settings.ReviewMaxRounds(ctx); err == nil && r > 0 {
			limit = r
		}
	}
	if maxOverride != nil {
		limit = *maxOverride
	}
	// Snapshot stage may also carry max_rounds.
	stage := j.snapshot[j.position-1]
	if stage.MaxRounds != nil {
		limit = *stage.MaxRounds
	}
	if extra != nil {
		limit += *extra
	}
	if round >= limit {
		attention, _ := json.Marshal(map[string]any{"reason": "max_rounds", "job_id": j.id, "round": round})
		_, err := tx.Exec(ctx, `UPDATE variants SET status = 'needs_attention', attention = $2, rev = rev + 1 WHERE id = $1`, *j.variant, attention)
		return err
	}
	// Create revise job on revise_target.
	if stage.ReviseTarget == nil {
		return fmt.Errorf("review stage has no revise_target")
	}
	var target *StageRow
	for i := range j.snapshot {
		if j.snapshot[i].StageID == *stage.ReviseTarget {
			target = &j.snapshot[i]
			break
		}
	}
	if target == nil {
		return fmt.Errorf("revise_target %s not in snapshot", *stage.ReviseTarget)
	}
	if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'revising', rev = rev + 1 WHERE id = $1`, *j.variant); err != nil {
		return err
	}
	s := j.spec(*target, j.variant)
	s.mode = "revise"
	s.round = round // the rejected round; next review will be round+1
	_, err := e.createJob(ctx, tx, s)
	return err
}

func (e *Engine) afterRevise(ctx context.Context, tx pgx.Tx, j jobRow) error {
	if j.variant == nil {
		return fmt.Errorf("revise without variant")
	}
	// Find the review stage (the one that pointed revise_target at this stage).
	var review *StageRow
	for i := range j.snapshot {
		s := j.snapshot[i]
		if s.ReviseTarget != nil && *s.ReviseTarget == j.stageID {
			review = &s
			break
		}
	}
	if review == nil {
		return e.advance(ctx, tx, j.liveJob)
	}
	nextRound := j.round + 1
	if nextRound < 1 {
		nextRound = 1
	}
	if _, err := tx.Exec(ctx, `UPDATE variants SET status = 'in_review', review_round = $2, rev = rev + 1 WHERE id = $1`, *j.variant, nextRound); err != nil {
		return err
	}
	s := j.spec(*review, j.variant)
	s.round = nextRound
	_, err := e.createJob(ctx, tx, s)
	return err
}

// MarkDispatched is called by the outbox relay after a job.requested confirm.
func (e *Engine) MarkDispatched(ctx context.Context, body []byte) error {
	var env messaging.Envelope
	if err := json.Unmarshal(body, &env); err != nil || env.Type != "job.requested" || env.Job == nil {
		return nil
	}
	_, err := e.Pool.Exec(ctx, `UPDATE jobs SET status = 'dispatched', dispatched_at = coalesce(dispatched_at, now()),
		deadline = coalesce(deadline, now() + make_interval(secs => timeout_s)), rev = rev + 1, updated_at = now()
		WHERE id = $1 AND fence = $2 AND status IN ('queued', 'dispatching')`, env.Job.JobID, env.Job.Fence)
	return err
}

// SweepTimeouts marks overdue live jobs timed_out (core-05 §7). Concurrent sweepers use SKIP LOCKED.
func (e *Engine) SweepTimeouts(ctx context.Context, limit int) (int, error) {
	e.defaults()
	if limit <= 0 {
		limit = 32
	}
	n := 0
	err := db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		rows, err := tx.Query(ctx, `SELECT id FROM jobs
			WHERE status IN ('dispatched', 'running') AND deadline IS NOT NULL AND deadline < now()
			ORDER BY deadline LIMIT $1 FOR UPDATE SKIP LOCKED`, limit)
		if err != nil {
			return err
		}
		ids, err := pgx.CollectRows(rows, pgx.RowTo[uuid.UUID])
		if err != nil {
			return err
		}
		for _, id := range ids {
			j, err := e.lockJob(ctx, tx, id)
			if err != nil {
				continue
			}
			if j.status != "dispatched" && j.status != "running" {
				continue
			}
			errBody, _ := json.Marshal(map[string]any{"class": "transient", "message": "deadline exceeded", "details": map[string]any{"code": "timeout"}})
			if _, err := tx.Exec(ctx, `UPDATE jobs SET status = 'timed_out', error = $2, finished_at = now(), rev = rev + 1, updated_at = now() WHERE id = $1`,
				j.id, errBody); err != nil {
				return err
			}
			if err := e.event(ctx, tx, j.liveJob, "job.timed_out", nil); err != nil {
				return err
			}
			// Transient retry rules apply; review (max_attempts=1) ends in needs_attention timeout.
			if err := e.onFailure(ctx, tx, j.liveJob, "transient"); err != nil {
				return err
			}
			// If onFailure left the scope without a new job and without failed, ensure attention reason=timeout.
			if j.variant != nil {
				_, _ = tx.Exec(ctx, `UPDATE variants SET attention = jsonb_set(coalesce(attention, '{}'::jsonb), '{reason}', '"timeout"')
					WHERE id = $1 AND status = 'needs_attention' AND (attention->>'reason') = 'retries_exhausted'`, *j.variant)
			}
			n++
		}
		return nil
	})
	return n, err
}

// CancelJob cancels one live job; its scope becomes needs_attention cancelled_by_admin.
func (e *Engine) CancelJob(ctx context.Context, jobID uuid.UUID, reason string) error {
	e.defaults()
	return db.WithTx(ctx, e.Pool, func(tx pgx.Tx) error {
		j, err := e.lockJob(ctx, tx, jobID)
		if err != nil {
			return ErrInvalidState
		}
		if !liveStatuses[j.status] {
			return ErrInvalidState
		}
		if _, err := tx.Exec(ctx, `UPDATE jobs SET status = 'cancelled', cancel_requested = true, finished_at = now(), rev = rev + 1, updated_at = now() WHERE id = $1`, j.id); err != nil {
			return err
		}
		attention, _ := json.Marshal(map[string]any{"reason": "cancelled_by_admin", "job_id": j.id, "message": reason})
		vars, err := e.scopeVariants(ctx, tx, j.liveJob)
		if err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `UPDATE variants SET status = 'needs_attention', attention = $2, rev = rev + 1 WHERE id = ANY($1)`, vars, attention)
		return err
	})
}
