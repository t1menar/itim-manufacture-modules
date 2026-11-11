# module-video-generation

Manufacture stage `video`: turns an approved scenario (`script`, `post`, `research`) into a finished post
(1080×1920 mp4 with sound, cover, contact sheet, caption, hashtags). Package `mvgen`, env `MVGEN_*`.

```
capture (planner agent proposes a plan, sandbox runner records the real output, values checked)
  → render (resolve script + capture, glyph/safe-zone/duration checks, frames, sound cues, contact sheet)
  → package (loudness-closed mux, cover frame, format/size/post-limit checks, caption + hashtags)
```

Everything about the look comes from the **idea**: `palette` (token → #RRGGBB), `constraints`
(`duration_s{min,max}`, `reading_wps`, `fps`/`crf`/…, `max_cost_usd`, `max_caption_chars`, `max_hashtags`,
`max_size_mb`, `capture_fix_rounds`), `video_brief`, `design_notes`, `instructions.video`, `must_show`,
`must_avoid`. Defaults live only in `settings.py`.

## Boundaries

- Real adapters are included: `ClaudeCapturePlanner` (Claude Agent SDK, no tools, resumes its session on fix rounds),
  `DockerCaptureRunner` (`sandbox/`: network-less, read-only, capability-dropped containers, images pinned by digest,
  catalog in JSON, see `sandbox-catalog.example.json`), `GitTrees` (pinned commit, fetched once) and `LocalStore`.
  `ArtifactStore` for S3 is not written yet.
- Platform: `adapter.py` is the Manufacture SDK step (`mf-module run mvgen.adapter:app`); env `MVGEN_DATABASE_URL`,
  `MVGEN_SANDBOX_CATALOG`, `MVGEN_STORE_DIR`, `MVGEN_MODEL`. Failed checks → `fatal`; unreproducible capture, version
  mismatch, budget → `attention`; store problems → `transient`.
- Numbers on screen come from the recorded capture, never from the model.
- A failed check (resolve, duration, glyphs, safe zone, frames, cues, loudness, format, size, post limits)
  is final: the result is stored as `manufacture.video.failed/1`, not retried.
- Result per `step_key` is stored (`generation_results`); a retried step spends nothing. A recorded capture is
  cached by hash of (plan, commands, image); a revision with unchanged commands (`Previous`) reuses it with
  no planner call and no sandbox.
- Cost: only the planner is paid, bounded by `constraints.max_cost_usd` of the idea.

## Develop

```bash
uv sync && make check            # ruff, mypy strict, pytest
MVGEN_TEST_DATABASE_URL=postgresql+asyncpg://… make test   # on Postgres
```

`test_full_run_on_the_reference` renders 120 frames of the reference scenario and needs ffmpeg (skipped when absent).
`pytest -m docker` with `MVGEN_DOCKER_IMAGE=<postgres@sha256:…>` records a real capture in a sandbox.
