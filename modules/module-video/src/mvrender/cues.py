"""Sound cues derived from the animation events of the timeline (03 section 4.4).

`animation_events` lists every event that has a sound rule; `from_events` turns each into one cue.
Because the cue list comes from the same events as the picture, sound cannot drift from it, and
`check_cues_match` proves it: exactly one cue per event within one frame, and no orphan cues.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mvrender import timing as tm
from mvrender.draw.debugger import _iters  # loop iteration count from captures
from mvrender.timeline import Timeline

DEFAULT_SOUND = {"folder": "pop", "pill": "pop", "cylinder": "pop", "code_card": "pop"}


@dataclass(frozen=True, slots=True)
class AnimEvent:
    t: float
    kind: str  # the cue kind this event triggers
    ref: str  # stable id of the event
    p: float = 1.0  # cue parameter (pitch / level)


@dataclass(frozen=True, slots=True)
class Cue:
    t: float
    kind: str
    p: float
    event: str


def animation_events(
    resolved: Mapping[str, Any], tl: Timeline, timing: tm.Timing | None = None
) -> list[AnimEvent]:
    timing = timing or tm.Timing()
    captures: dict[str, str] = dict(resolved.get("captures", {}))
    out: list[AnimEvent] = []
    for idx, (scene, st, start) in enumerate(zip(resolved["scenes"], tl.scenes, tl.starts, strict=True)):
        sid = scene["id"]
        if idx:
            out.append(AnimEvent(start, "whoosh", f"{sid}:start", 0.6))
        hook = scene.get("hook")
        if idx == 0 and hook:
            step = float(hook.get("line_step_s", 1.2))
            out.append(
                AnimEvent(
                    start + min(int(hook.get("impact_line", 0)), 2) * step, "impact", f"{sid}:hook", 1.0
                )
            )
        if st.terminal:
            _terminal_events(out, scene, st, start, idx)
        if scene["kind"] == "debugger" and st.debugger_enter is not None and st.debugger_resume is not None:
            out.append(AnimEvent(start + st.debugger_enter - 0.2, "tape_stop", f"{sid}:enter"))
            out.append(AnimEvent(start + st.debugger_resume - 0.25, "tape_start", f"{sid}:resume"))
            _debugger_events(out, scene, st, start, timing, captures)
        for key in ("diagram", "panel"):
            for el in (scene.get(key) or {}).get("elements", []):
                ev = _element_event(el, st, start, sid)
                if ev:
                    out.append(ev)
    return sorted(out, key=lambda e: (e.t, e.ref))


def _terminal_events(
    out: list[AnimEvent], scene: dict[str, Any], st: tm.SceneTiming, start: float, idx: int
) -> None:
    sid = scene["id"]
    assert st.terminal is not None  # noqa: S101
    seen_out: set[str] = set()
    for ev in st.terminal.events:
        if ev.kind == "cmd":
            text = str(ev.payload["text"])
            for i, ch in enumerate(text):
                if ch != " ":
                    out.append(
                        AnimEvent(
                            start + ev.t + i * ev.dur / len(text),
                            "key",
                            f"{sid}:{ev.ref}:key:{i}",
                            (i * 37) % 100 / 100,
                        )
                    )
            if idx:
                out.append(AnimEvent(start + ev.t + ev.dur + 0.08, "enter", f"{sid}:{ev.ref}:enter"))
        elif ev.kind == "out":
            cid, k = ev.payload
            spec = next(e for e in st.terminal.events if e.kind == "cmd" and e.ref == cid).payload
            row = str(spec["rows"][k])
            if row.startswith("ERROR"):
                out.append(AnimEvent(start + ev.t, "error", f"{sid}:{cid}:error:{k}"))
            elif cid not in seen_out and row.strip() and not row.startswith("--"):
                out.append(AnimEvent(start + ev.t, "blip", f"{sid}:{cid}:blip"))
            seen_out.add(cid)


def _debugger_events(
    out: list[AnimEvent],
    scene: dict[str, Any],
    st: tm.SceneTiming,
    start: float,
    timing: tm.Timing,
    captures: dict[str, str],
) -> None:
    sid = scene["id"]
    for k, (step, stt) in enumerate(zip(scene["debugger"]["steps"], st.steps, strict=True)):
        out.append(AnimEvent(start + stt.start, "ding", f"{sid}:{step['id']}:ding", 1 + (k % 5) * 0.125))
        iters = _iters(step, captures)
        t = stt.start + tm.STEP_LEAD_S
        prev: int | None = None
        for i, (n, hold, _name) in enumerate(tm.line_holds(step, timing, iters)):
            if n and n != prev:
                fast = hold <= float((step.get("loop") or {}).get("fast_line_s", timing.fast_line_s)) + 1e-9
                out.append(
                    AnimEvent(
                        start + t,
                        "tick",
                        f"{sid}:{step['id']}:tick:{i}",
                        0.5 if fast and step.get("loop") else 1.0,
                    )
                )
            prev = n or prev
            t += hold
        if step.get("loop"):
            first = stt.start + tm.STEP_LEAD_S
            begin = first
            for i in range(iters or 0):
                end = stt.marks.get(f"{step['id']}.loop.{i}", begin)
                out.append(AnimEvent(start + begin, "whoosh", f"{sid}:{step['id']}:loop:{i}:start", 0.15))
                out.append(AnimEvent(start + end, "block", f"{sid}:{step['id']}:loop:{i}:end", (i % 4) / 3))
                begin = end


def _element_event(el: Mapping[str, Any], st: tm.SceneTiming, start: float, sid: str) -> AnimEvent | None:
    if not el.get("appear"):
        return None
    kind = "chime" if el.get("success") else el.get("sound") or DEFAULT_SOUND.get(el["type"], "none")
    if kind == "none":
        return None
    t = start + tm.anchor_time(el["appear"], st.marks)
    p = 1 + 0.12 * int(el.get("slot", 0)) if kind == "pop" else 1.0
    return AnimEvent(t, kind, f"{sid}:{el['id']}:appear", p)


def from_events(events: list[AnimEvent]) -> list[Cue]:
    return [Cue(round(e.t, 4), e.kind, e.p, e.ref) for e in events]


def from_timeline(resolved: Mapping[str, Any], tl: Timeline, timing: tm.Timing | None = None) -> list[Cue]:
    return from_events(animation_events(resolved, tl, timing))


def check_cues_match(cues: list[Cue], events: list[AnimEvent], fps: int) -> list[str]:
    """`cues_match_animations`: one cue per event within one frame; no orphan cues."""
    problems: list[str] = []
    by_ref: dict[str, list[Cue]] = {}
    for c in cues:
        by_ref.setdefault(c.event, []).append(c)
    refs = {e.ref for e in events}
    for e in events:
        found = by_ref.get(e.ref, [])
        if len(found) != 1:
            problems.append(f"event {e.ref}: {len(found)} cues, expected 1")
        elif abs(found[0].t - e.t) > 1 / fps or found[0].kind != e.kind:
            problems.append(
                f"event {e.ref}: cue {found[0].kind}@{found[0].t:.3f} does not match {e.kind}@{e.t:.3f}"
            )
    problems += [f"orphan cue {c.kind}@{c.t:.3f} ({c.event})" for c in cues if c.event not in refs]
    return problems
