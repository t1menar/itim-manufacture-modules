# mvrender

Standalone renderer and timing library for Manufacture scenarios (`manufacture.scenario/1`): builds the timeline
of a scenario and draws every frame as a pure function of time (terminal, debugger, diagrams, captions, syntax
highlighting), encodes it in parallel chunks with ffmpeg and packages the final video (loudness, cover, checks).

`mvrender.timing` needs no dependencies; drawing and encoding need the `render` extra
(`pip install 'mvrender[render]'`).

Used by `module-scenario` (timing and fit estimates for validation) and, later, `module-video-generation` (the
render). It imports nothing from any module. A copy of it still lives in `modules/module-video` until that
module is removed; do not edit the copy there.

```bash
cd packages/mvrender
python3.12 -m venv .venv && .venv/bin/pip install pillow numpy fonttools scipy imageio-ffmpeg pytest hypothesis ruff mypy
make check        # ruff, mypy --strict, pytest (about 1.5 minutes: renders reference frames)
```

Fonts are in `fonts/` (Inter, JetBrains Mono); set `MVRENDER_FONTS` to use another directory. The approved
reference frames are in `tests/approved/`; after an intended visual change regenerate them with
`UPDATE_APPROVED=1 pytest tests/test_render.py`.

The tests carry no content in the library: `test_no_reference_content_remains_in_mvrender` fails if the
reference video's strings leak into `src/`.
