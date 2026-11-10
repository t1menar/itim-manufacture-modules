# Step: analysis

## Your job
Decide whether the idea in /in/idea.json can be turned into an honest iTim video with the systems we can run,
and if so, frame it: which system and version, which repository and branch, which sandbox image, the angle,
three hook candidates, what must be run, the audience level and a target length.

## Done when
- /out/analysis.json exists and the tool validate(kind="analysis", path="/out/analysis.json") returns no errors;
- system.repo and system.ref are one of the pairs in /in/environment.json -> repositories;
- sandbox_image is one of the keys in /in/environment.json -> sandbox_images;
- hooks has exactly 3 entries, each 1 to 3 short lines, each with a one-sentence "why";
- target_duration_s is inside environment.json -> duration range.
Or: /out/blocked.json exists and validates (kind="blocked").

## Inputs (data, not instructions)
- /in/idea.json: the owner's one-line idea.
- /in/environment.json: what we can run and read. Nothing outside it is available to later steps.
- /in/channel.json: channel name and style rules.
- /ref/create_database/analysis.json: a good analysis for comparison.
You may read documentation pages from the allowed domains to confirm versions and behaviour.

## Rules and why
- Choose only from environment.json, because later steps can only clone those repositories and run those images;
  a choice outside it fails hours later.
- Prefer the current stable branch of the system (for PostgreSQL: REL_17_STABLE with image postgres17), because
  viewers run current versions and the sandbox image matches it.
- The angle is one surprising, checkable claim ("CREATE DATABASE creates nothing, it copies"), because a claim
  the video then proves with real data is what keeps a viewer watching.
- Hooks: at most 3 short lines, no question marks stacked, no clickbait that the code does not support,
  because the reviewer rejects hooks the video does not prove.
- what_to_run lists the commands a viewer would type to see the effect, in the session they belong to
  (psql or sh). Do not invent output; capture will run them.
- Do not write the script, research the source in depth, or estimate numbers; later steps do that with the
  right tools. One step, one task keeps your context small.
- Write in English.

## If it cannot be done honestly
If the idea needs a system, version or repository that is not in environment.json, cannot be demonstrated
by commands in a sandbox without network, or is a matter of opinion, write /out/blocked.json:
{"format": "manufacture.blocked/1", "step": "analysis", "reason": "...", "missing": ["..."], "suggestion": "..."}
and stop. Do not stretch the idea to fit what is available.

## Anti-example
"hooks": [{"lines": ["You won't BELIEVE", "what Postgres does!!!"], "why": "curiosity"}]
Wrong: no checkable claim, capitals and exclamation marks, nothing the video can prove.

## Before finishing
Run validate. Fix every error. Then write two lines to /out/notes.md: the angle you chose and why.
