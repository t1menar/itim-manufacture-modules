AUTONOMOUS RUN (reels studio): the author rejected the finished video (round {{round}}) and wrote:

> {{comment}}

First re-read `{{reels}}/CLAUDE.md` and the series `_series/STYLE.md`: the author's rules may have changed since
your last turn (new lessons are added after each review). Apply them together with the comment.

Redo only what the comment needs:
- only the caption, hashtags or title → edit `description.md` and the result file; do not touch the video or cover;
- the cover → re-render only the cover;
- something in the video → fix the source and re-render only the affected frames (or the audio), then re-assemble and
  re-verify (WORKFLOW Part 12);
- the story itself → update the script first, then the video.
Apply every point; keep what the author did not mention. Add a "Changes after review" section to the episode README.

Then write `factory/post_result.json` again in the same shape, with `changed` listing what you redid
(any of "caption", "hashtags", "title", "cover", "video", "audio", "script") and `summary` saying how each point was applied.
