# module-reels-studio: context and gotchas

- **Why native, not a container:** Claude Code uses the owner's login (keychain), Blender renders on the Mac's GPU, and the
  real-data sandboxes are the Mac's Docker. The module joins the stack over RabbitMQ published on 127.0.0.1:5672.
- **Why `ctx.wait` instead of a long handler:** a video takes hours and may sleep through a usage-limit reset; a parked
  attempt has no lease and no execution timeout, only the pipeline's `wait.timeout` (4-7 days).
- **The core does not fire `trigger.schedule` yet** (validated, never run). The feeder posts
  `POST /api/v1/pipelines/reels/runs` without data every 5 min (needs `MF_ADMIN_TOKEN`); the idea source decides.
- **Idea codes** match `^[a-z][a-z0-9_]{1,63}$` (underscores). Queueing needs a rubric, an environment, a takeaway and a
  description of 8+ words: the feeder and Telegram `/idea` fill them (`reels`, `mac_reels_studio`).
- **Buckets:** `ctx.blob_prefix` names the core's bucket (`MF_S3_BUCKET`); the modules' storage client is bound to
  `S3_BUCKET`. Upload by key into the client's bucket.
- **`.env` has inline `# comments`**; the loader strips them like docker compose. Values are never logged.
- **Usage windows** come from `rate_limit_event` in the stream-json output (`unifiedWindows.five_hour/seven_day`,
  `utilization` 0..1, `resetsAt` unix seconds). A Haiku probe reads them when the last reading is older than 10 min.
- **Claude Code permissions:** `--permission-mode auto`. If the auto-mode classifier blocks a needed step, the run fails,
  the error goes to Telegram and the next attempt resumes with the error text.
- **Dry run:** `docs/pipeline.reels-dry.yaml` (studio stages only) with `MSTUDIO_CLAUDE_BIN=tests/fake_claude.py`,
  `MSTUDIO_TG_TOKEN=off`, `MSTUDIO_FEED=off`, a scratch `MSTUDIO_REELS_DIR`. Stop it before starting the real agent:
  two replicas would share jobs.
