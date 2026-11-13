AUTONOMOUS RUN (reels studio), stage 1 of 2: research and script.

Episode folder (your working directory): {{episode}}
Series: {{series}} (archive root: {{reels}})

The idea from the author's backlog (title, their vision, notes):
```json
{{idea}}
```

Do this:
1. Read `{{reels}}/CLAUDE.md` and everything it lists under "Read first" for this series. If the series is new, base it on
   the shared rules and pick a palette as the workflow says.
2. Frame the topic: one question the video answers. Follow the author's vision in the idea; where it is vague, choose
   the simplest framing for everyday backend developers.
3. Capture the real data yourself in a sandbox (Docker or a venv inside `research/`): scripts in `research/`, raw output
   and a `research/facts.md` summary. Every number you plan to show must be in the facts.
4. Write the script (`script/script.md`) as the workflow's scene table: at most 90 s and 6-8 scenes (CLAUDE.md lessons:
   slow pace, one running concrete example, a practical use at the end), overview first, every term explained,
   legends for tables/colours, the hook, the payoff. Run the script checklist (WORKFLOW 4.9) and fix what fails.
5. Draft the publishing copy in `description.md` (WORKFLOW Part 14 and the series STYLE: at most 5 hashtags).
6. Start `README.md` for the episode (what it is, the framing decisions you made and why).

Do NOT build the stage or render anything yet: the author approves the script in Telegram first.

Finish by writing `factory/script_result.json` (paths relative to the episode folder):
```json
{"title": "<the hook title, < 60 chars>", "hook": "<the first-second hook line>", "takeaway": "<the one thing viewers learn>",
 "duration_s": 88.0, "scenes": [{"title": "<scene headline>", "narration": "<what the scene shows and says, one or two sentences>"}],
 "caption": "<the Instagram caption draft>", "hashtags": ["<up to 5, without #>"], "script_path": "script/script.md"}
```
The `scenes` list is what the author reads in Telegram: one entry per scene, short and concrete, real numbers included.
