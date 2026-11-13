# module-reels-studio (`mstudio`)

Manufacture stages `studio-script` and `studio-video`: Claude Code (Opus 5.5) on the Mac researches an idea, writes the
script, then builds the whole Reel (real data in a sandbox, Blender, the overlay, the music, the cover) the same way the
videos in `~/itim/Reels` were made by hand. The playbook it follows is `~/itim/Reels/CLAUDE.md`.

Runs **natively on the laptop** (runtime `external`): Blender, Docker and the user's Claude Code login live there.

## How a step runs
1. The core sends the step (`config: {mode: script|video}`). The handler stores a job in SQLite
   (`~/.local/state/reels-studio/studio.db`) and parks the attempt with `ctx.wait(reason="external")`.
2. The worker takes jobs one at a time:
   - **usage gate**: reads the 5-hour and 7-day subscription windows from Claude Code's `rate_limit_event`s (a tiny Haiku
     probe when the data is older than 10 min). Less than 30% left (`MSTUDIO_MIN_LEFT`) or exhausted → a Telegram notice
     and a sleep until the window resets;
   - runs `claude -p` (stream-json, `--permission-mode auto`) in the episode folder `~/itim/Reels/<Series>/NN-slug/`.
     Revisions resume the stage's stored session with the reviewer's comment, so only the needed parts are redone;
   - a usage limit mid-run → notice, sleep until the reset, resume the same session ("continue");
   - an error or an invalid result file → resume with the error, up to `MSTUDIO_MAX_ATTEMPTS` (3); then a Telegram
     error, a wait until the next 5-hour reset and another round (`MSTUDIO_ERROR_ROUNDS`, 2); then the step fails as
     `attention` (retry it in the core after fixing the cause);
   - validates `factory/script_result.json` / `factory/post_result.json`, uploads the video and cover to MinIO and
     finishes the attempt with `app.complete`.
3. A retried attempt of a finished visit gets the stored output at once (`step_key`).

Output: script → `{title, scenario: {script: {meta, scenes, path}, post}, episode}`;
video → `{title, variant: {video: {ref, duration_s, size}, cover: {ref}, post: {caption, hashtags}, metadata}, episode}`
(the shapes `telegram-review` and `instagram-publisher` read).

## Secrets
Claude Code runs with the user's own login. The child process gets the environment **without** `MF_*`, `S3_*`, `MTGR_*`,
`MIPUB_*`, `MIDEA_*`, `RABBITMQ_*`, `POSTGRES_*`, `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN` and AWS keys. The module
never logs tokens; the playbook forbids reading `.env` files.

## Settings (`MSTUDIO_*`)
`REELS_DIR` (~/itim/Reels), `STATE_DIR`, `CLAUDE_BIN`, `MODEL` (claude-opus-5-5), `EFFORT` (high), `PROBE_MODEL` (haiku),
`PERMISSION_MODE` (auto), `MIN_LEFT` (0.30), `MAX_ATTEMPTS`, `ERROR_ROUNDS`, `TG_TOKEN`/`TG_CHATS` (default: the review
bot's `MTGR_BOT_TOKEN`/`MTGR_OWNERS`), `S3_ENDPOINT`/`S3_SECURE` (MinIO as seen from the laptop), `BLOB_PREFIX`.

## Run
```bash
make venv        # python3.12 venv with the SDK and mf-storage
make test
deploy/install.sh  # launchd agent: starts at login, restarts on crash, keeps the Mac awake while running
.venv/bin/mstudio status   # the last jobs
```
Logs: `~/.local/state/reels-studio/logs/` (`<run>-<mode>.jsonl` is the full Claude Code stream; `mstudio.log`).
