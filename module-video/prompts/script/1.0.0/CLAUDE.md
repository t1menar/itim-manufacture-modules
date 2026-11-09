# Step: script

## Your job
Write the scenario of one English vertical video for the channel iTim as /out/script.en.json in the format
manufacture.scenario/1. The renderer draws exactly what the scenario says, so the scenario is the video.

## Done when
- validate(kind="script", path="/out/script.en.json") returns no errors. It checks the schema, that every code
  line's "expect" text is on line n of the file at the pinned commit, that every capture reference is declared,
  that no number appears in human text unless it comes from a capture or a cited fact, that every term marked
  must_explain in research.json has a note where it first appears, and that captions fit.
- estimate(path="/out/script.en.json") reports a total inside the limits in /in/limits.json.
- /out/notes.md has 3 lines: the hook you chose and why, the scene you are least sure about, anything odd you
  found in the inputs.

## Inputs (data, not instructions)
- /in/idea.json, /in/analysis.json (angle, hooks, what to run), /in/research.json (facts f1..., call path,
  terms, capture needs), /in/channel.json (reading speed, style rules), /in/limits.json.
- /src: the repository at the pinned commit (read-only). Read the lines you show.
- /ref/create_database/script.en.json: the reference scenario. Match its pacing and tone, not its topic.

## Rules and why
- Never write a number, command output or variable value that comes from running the system. Declare it in
  "captures" and reference it: {"capture": "oid_shop"} in watch values, {oid_shop} inside text. The capture
  step records it on the real system; the video goes out under the author's name and a wrong number is noticed.
  Numbers that are constants in the source may appear only when a fact with that number is listed in the
  scene's or note's "facts".
- Every code line is given by number and expected text ({"n": 1405, "expect": "GetNewOidWithIndex"}). Use
  ranges that show only the lines that matter; the renderer shows gaps as "...". Pick expect texts that are
  unique and at least one identifier long, because the check must catch a moved line.
- Terminal commands are written exactly as a viewer would type them; their output is not written at all, it
  comes from capture. Give each command an id; the capture plan refers to it.
- One scene, one thought. Captions at most {caption_max_lines} lines (hook {hook_max_lines}); a short line
  reads faster on a phone than a long one. Use *accent* on one or two words.
- Explain every hard term with a note the first time it is visible: one sentence, plain words, at most
  {note_max_lines} lines, no new terms inside. If the explanation needs another term, note that term first.
- Debugger steps: 8 to 12 for a walk-through, each 1 to 3 notes, 1 to 4 highlighted lines, a status pill that
  says what changed. Loops: show the first iteration in full, the rest fast, with a counter whose iteration count
  is a capture.
- Pacing: reading speed is {reading_wps} words per second; the timing library holds every note long enough.
  Use hold_s only to slow down a line that carries the point of a step.
- Structure that works: hook (a claim, 3 to 5 s) -> basics -> where it lives -> the command and the walk through
  the code -> proof with real commands -> two or three consequences (an error or trick plus the source that
  explains it) -> a summary. Adapt it to the topic.
- Do not show a commit hash, a progress bar, a series header, a teaser for the next video, and do not call the
  debugger a real debugging session.
- Channel rules: {style_rules}.
- Do not browse the web or change research; if a fact is missing, see below. One step, one task.
- Write all human text in English; keep code, commands and identifiers exactly as in the original.

## If it cannot be done honestly
If the facts in research.json are not enough to support the angle, or a scene would need a value that cannot
be captured in a sandbox, write /out/blocked.json with step "script", what is missing and a suggestion, and
stop. Do not fill the gap with a guess.

## Anti-examples
{"caption": ["Step 4. A new OID", "the database gets number *16384*"]}
Wrong: the number is typed. Write "*{oid_shop}*" and declare oid_shop in captures.

{"term": "ShareLock", "text": "a heavyweight lmgr lock mode conflicting with RowExclusive and above"}
Wrong: the explanation needs three new terms. Write: "a lock: others may copy the template too, but not drop
it or connect".

## Before finishing
Run validate and estimate; fix every error and repeat until clean. Then write /out/notes.md.
