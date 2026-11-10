# module-instagram-publisher

Manufacture stage `publish`: publishes an approved post (video, cover, caption, hashtags) as an Instagram Reel.
Package `mipub`, env `MIPUB_*`. Successor of `module-publish` without the legacy-core protocol.

```
PublishService.publish(PublishRequest, confirm)
  ledger (account, content hash) → host (public https URL) → container → poll → arm ledger + confirm
  → media_publish (never retried) → permalink → ledger `published`
```

## Guarantees

- No double posts: a `published` ledger row is returned as is, also for a new run with the same content.
- `publishing` / `unknown` rows are reconciled (container status, recent media by caption and time) and never
  resent; still unknown → `Outcome.attention=True` for the operator.
- `confirm(container_id)` is called right before the irreversible call (the platform checks the attempt lease
  and that the review approval still stands). "No" → `cancelled`, retryable later with a fresh container.
- Errors carry `retryable` (rate limit, 5xx, host failure) or are permanent (auth, invalid request, dead container).
- Tokens live behind `TokenProvider` (never in the DB, never logged); accounts hold only `ig_user_id` and handle.

## Boundaries (Protocols)

`Instagram` (real: `GraphClient`, url upload only), `MediaHost` (real: `SftpHost`, copies the file to a web host
Meta can fetch), `TokenProvider`. Graph base `https://graph.facebook.com` for system-user tokens (`EAA…`),
API `v27.0`; Meta's resumable upload accepts ≈1.7 MB per request, so direct upload is not offered.

Not done: platform/SDK adapter (`step_key`, lease `confirm`, `attention`), S3 loader for `SftpHost`, account admin API.

## Develop

```bash
uv sync && make check      # ruff, mypy strict, pytest (Graph mocked with httpx.MockTransport, never calls Meta)
MIPUB_TEST_DATABASE_URL=postgresql+asyncpg://… make test
```
