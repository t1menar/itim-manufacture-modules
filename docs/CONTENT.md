# Content strategy (decided 2026-11-10, owner + assistant discussion)

Status: **ideas are not changed for now; module development continues.** This file records the direction for the audience test.

## Problem with current videos
Too long (≈160 s), too deep and jargon-heavy; one video tries to explain a whole topic. Simple animated explainers exist everywhere and prove nothing.
Our differentiator: **real recorded commands with real output** (numbers come from the sandbox record, never from the model).

## Target format (to implement later, in code/settings, not in prompt text)
- **No voice**, English on-screen text, sound effects kept. Duration 30–45 s (race / predict-the-output) up to 60 s.
- One idea = one sentence; max 4–5 scenes, 1–2 commands, ≤3 lines on screen, key number large.
- Scenario template: hook (0–3 s) → plain-words setup/analogy (3–15) → live demo (15–45) → "why" (45–55) → loop ending.
- Enforce with settings/validation: max duration, max scenes, word and term limits.

## Series (rubrics)
1. Race (same task two ways, timer) 2. Predict the output (3 s to guess, reveal) 3. Break it (surprising result) 4. Myth vs reality 5. What does it cost (one number).

## Topics: deep vs broad (the experiment)
Broad: SQL/Postgres basics, Git, Linux/bash, Docker/HTTP/curl, Python/JS gotchas. Deep: Kafka and Postgres internals. Depth is controlled per module/topic by the owner.
Hypothesis: broad wins views, deep wins follower quality (backend engineers, sponsors). Compare by saves and follows per 1000 views, not raw views.

## Audience test
30–40 videos over 2–3 weeks, 2 per day, 4–5 rubrics × 6–8 videos, same posting time (US/EU evening), unchanged visual style.
Metrics per video: completion/average watch time, saves, shares, follows per 1000 views. Duplicate to YouTube Shorts (devs live there) to separate "topic" from "platform" (module-publish only supports Instagram; upload manually).
Rules of thumb (not facts): continue if several videos reach ≈10–20k views from a cold account, saves ≥2–3 % of views, follows >3 per 1000 views; change format if retention is good only for some rubrics; stop/change platform if everything stays at 1–2k across hooks and platforms.

## Later: owner involvement
(1) Approve the script text in Telegram before capture/render (review gate after `script`). (2) Owner voice-over: pipeline exports script with timestamps, owner records, system muxes and levels to −16 LUFS. (3) Owner on camera for intro/outro. (4) Owner submits ideas, agent turns them into scenarios.
