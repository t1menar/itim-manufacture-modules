# Manufacture — module / service status

_Last updated: 2026-11-10 (Europe/Stockholm)._

## On main

#7–#23 merged (Telegram #20, Instagram #21, module DB secrets #22, MinIO/presigned #23).

## Accepted decisions

| # | Decision |
|---|----------|
| D18–D24 | See prior rows; module-owned secrets; MinIO via `mf-storage`. |

## Open PRs

| PR | Content | Merge? |
|----|---------|--------|
| (this) | `deploy/` local stack (`up.sh` + animated logs) | owner — wait (**do not merge**) |

## Local deploy

- Entry: `./deploy/up.sh` — PG / RabbitMQ / MinIO / core / video / review / publish, register+activate modules, smoke.
- Animated logs: `deploy/lib/log.sh` (spinners, `[n/N]`, timers, `.logs/`).
- Fake TG/IG by default. MinIO default `http://127.0.0.1:56000`; live IG → cloudflared/ngrok tunnel.

## module-video

Not modified by deploy PR. Needs `DOCKER_HOST` + `VIDEO_AGENT_NETWORK` (created by `up.sh`) for agent containers; ideas paused by default (`VIDEO_IDEAS_PAUSED=1`).

## Live verify (agent box, 2026-11-10)

`up.sh` → healthy + modules active; повторный `up.sh` идемпотентен; `down.sh` OK. Логи: `deploy/.logs/20261110-032400.log`, `…032709.log`. На этой машине: MinIO из GitHub release (Hub blocked), `bridge-nf-call-iptables=0`, static IPs из‑за broken embedded DNS.
