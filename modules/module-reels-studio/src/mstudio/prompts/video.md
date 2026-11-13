AUTONOMOUS RUN (reels studio), stage 2 of 2: build the video from the approved script.

Episode folder (your working directory): {{episode}}
Series: {{series}} (archive root: {{reels}})

The idea:
```json
{{idea}}
```

The author approved `script/script.md` in this folder (with `research/facts.md`). Now:
1. Re-read `{{reels}}/CLAUDE.md`, the series STYLE.md, WORKFLOW.md Parts 5-15 and the latest episode's `source/` of this series.
   Reuse that source as the starting point (copy it into this episode's `source/` and adapt). The lessons in CLAUDE.md
   (pace, clean design, cover, quality, music) win over the look of older episodes.
2. Build the stage, the 2D overlay, the timeline, a new music track for this video (CLAUDE.md: same patterns, new tempo,
   key, groove and sounds; an SFX for every animation) and a cover that shows the topic itself.
3. Render all frames in the background (resumable ranges), assemble, mux with the loudness chain from TOOLS.md.
4. Verify (WORKFLOW Part 12): frame count, duration <= 90 s, a contact sheet you actually look at (overlaps, legibility,
   the safe band), 100% crops of small text in the final encoded file (x264 crf 14), every on-screen number against the facts, loudness about -14 LUFS, peak about -1 dBFS.
   Fix what fails and re-render only the affected frames.
5. Finish `description.md` (caption with at most 5 hashtags, alt text), the episode `README.md` (build steps, honesty
   notes) and add the episode's row to the series README.
Keep notes of progress in `factory/progress.md` (a run may be paused by usage limits and resumed).

Finish by writing `factory/post_result.json` (paths relative to the episode folder):
```json
{"title": "<the Reel title>", "video": "<name>.mp4", "cover": "<name>_cover.png",
 "caption": "<the full Instagram caption WITHOUT the hashtags, 20..2000 chars>", "hashtags": ["<up to 5, without #>"],
 "duration_s": 87.5, "changed": [], "summary": "<two sentences: what the video shows, anything you could not verify>"}
```
The video must be H.264 1080x1920 60 fps with AAC audio and under 50 MB (the Telegram review limit); if it is larger,
re-encode with a higher crf and say so in `summary`.
