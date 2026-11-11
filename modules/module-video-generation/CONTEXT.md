# module-video-generation: context

- Port of module-video's `capture`, `render`, `package` steps. Render/sound/mux/cover come from
  `packages/mvrender` (path dependency, `render` extra); the logic of the old steps is in `render.py`,
  `package.py`, `capture.py`, `post.py` without the legacy pipeline/context classes.
- `service.GenerationService.run(idea, scenario, step_key, channel=None, previous=None)` is the entry point.
  `scenario` = `{research, script, post}` as produced by module-scenario; `research.system/commit` pick the
  source tree for the code citations on screen.
- Done: Claude planner, Docker runner (ported from `module-video/src/mvideo/sandbox`, verified with postgres:17), git trees,
  SDK adapter. Not done: S3 `ArtifactStore` (`packages/mf-storage`), metrics, artifact retention.
- Gotchas: render workers must share `reading_wps` with the parent (handled by `render_video(reading_wps=…)`);
  palette tokens must exist in `mvrender/palette.py DEFAULTS`; loudness target is closed around the AAC file.
