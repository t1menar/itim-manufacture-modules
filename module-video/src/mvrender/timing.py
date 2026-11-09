"""Shared timing: how long things take on screen.

Used by the validator (to estimate the length of a script before anything is rendered) and by the
renderer's timeline (to place every event), so both always agree on duration. The formulas port the
reference `create-database-video/render.py` (`note_time`, `Step.dur`, `seq_notes`, `Term`), with the
reference constants taken from settings `timing` and `reading_wps`.

All times are seconds. Functions take plain dictionaries (the parsed script) and a `Timing`; this
module imports nothing from `mvideo`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields
from typing import Any

# Constants that are part of the reference look and are not (yet) settings.
TERM_START_S = 0.4  # first terminal event of a scene
DEBUGGER_ENTER_DELAY_S = 0.5  # pause between the command that starts the debugger and the first step
DEBUGGER_RESUME_PAD_S = 0.4  # pause after the last debugger step before the terminal resumes
STEP_LEAD_S = 0.6  # a step shows its first line this long after it starts
NOTE_START_DELAY_S = 0.3  # notes of a debugger step start this long after the step
NOTE_GAP_S = 0.1  # a note disappears this long before the next one appears
DEFAULT_NOTES_START_S = 1.0  # first note of a scene without an explicit anchor
DEFAULT_GAP_S = 0.045  # delay between printed output lines


@dataclass(frozen=True, slots=True)
class Timing:
    """Settings `timing` (04 section 10)."""

    read_base_s: float = 1.0
    read_min_s: float = 2.6
    default_cps: float = 24.0
    step_tail_s: float = 1.0
    step_notes_pad_s: float = 0.6
    default_hold_s: float = 1.4
    scene_tail_s: float = 1.5
    fast_line_s: float = 0.14
    fade_s: float = 0.35
    dissolve_s: float = 0.18

    @classmethod
    def from_settings(cls, values: Mapping[str, Any] | None) -> Timing:
        names = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in (values or {}).items() if k in names})


DEFAULT_READING_WPS = 4.5  # words per second a viewer reads (channel setting `reading_wps`)


class TimingError(ValueError):
    """A script refers to something the timeline cannot place (unknown mark, bad range)."""


# ---- reading and typing ------------------------------------------------------------------------


def word_count(text: str) -> int:
    return len(text.split())


def note_time(term: str, text: str, timing: Timing, reading_wps: float = DEFAULT_READING_WPS) -> float:
    """How long a glossary note stays: fade-in plus reading time, never below the minimum."""
    return max(timing.read_min_s, timing.read_base_s + word_count(f"{term} {text}") / reading_wps)


def typing_s(text: str, cps: float) -> float:
    return len(text) / cps if cps > 0 else 0.0


# ---- terminal ----------------------------------------------------------------------------------


@dataclass(slots=True)
class TermEvent:
    t: float
    kind: str  # cmd | out | annotation | wait | mark
    ref: str = ""  # command id or mark name
    dur: float = 0.0  # typing time for cmd
    payload: Any = None  # the script event (cmd), (command id, line index) (out) or the line (annotation)


@dataclass(slots=True)
class TerminalTiming:
    start: float
    end: float
    marks: dict[str, float] = field(default_factory=dict)
    events: list[TermEvent] = field(default_factory=list)
    typing: list[tuple[float, float]] = field(default_factory=list)  # (from, to) while keys are typed


def output_line_count(event: Mapping[str, Any]) -> int:
    """Lines a command prints, from `output.lines = [first, last]` (inclusive) unless hidden."""
    out = event.get("output") or {}
    if out.get("hidden") or "lines" not in out:
        return 0
    first, last = out["lines"]
    return max(0, int(last) - int(first) + 1)


def run_terminal(
    events: Sequence[Mapping[str, Any]],
    timing: Timing,
    *,
    start: float = TERM_START_S,
    stop_after: str | None = None,
    line_counts: Mapping[str, int] | None = None,
    state: TerminalTiming | None = None,
) -> tuple[TerminalTiming, int]:
    """Play terminal events from `start`; returns the timing and how many events were consumed.

    With `stop_after` (a command id) playback stops once that command is typed and its `post_s`
    has passed, before its output; the caller resumes with the remaining events and `state`.
    """
    tt = state or TerminalTiming(start=start, end=start)
    t = tt.end
    consumed = 0
    for ev in events:
        consumed += 1
        if "cmd" in ev:
            cid = str(ev["cmd"])
            t += float(ev.get("pre_s", 0.35))
            dur = typing_s(str(ev["text"]), float(ev.get("cps", timing.default_cps)))
            tt.events.append(TermEvent(t, "cmd", cid, dur, ev))
            tt.typing.append((t, t + dur))
            tt.marks[f"{cid}.typed"] = t + dur
            t += dur + float(ev.get("post_s", 0.25))
            if stop_after == cid:
                tt.end = t
                return tt, consumed
            n = (line_counts or {}).get(cid, output_line_count(ev))
            out = ev.get("output") or {}
            gap = float(out.get("gap_s", DEFAULT_GAP_S))
            tt.marks[f"{cid}.output"] = t
            for k in range(n):
                tt.events.append(TermEvent(t, "out", cid, 0.0, (cid, k)))
                t += gap
        elif "wait_s" in ev:
            tt.events.append(TermEvent(t, "wait"))
            t += float(ev["wait_s"])
        elif "mark" in ev:
            tt.marks[str(ev["mark"])] = t
            tt.events.append(TermEvent(t, "mark", str(ev["mark"])))
        elif "annotation" in ev:
            for line in ev["annotation"]:
                tt.events.append(TermEvent(t, "annotation", "", 0.0, line))
                t += DEFAULT_GAP_S
    tt.end = t
    return tt, consumed


# ---- debugger steps ---------------------------------------------------------------------------


def line_holds(
    step: Mapping[str, Any], timing: Timing, iterations: int | None = None
) -> list[tuple[int, float, str]]:
    """The sequence of (source line, seconds shown, mark suffix) of one step, loops expanded.

    A loop shows its `first` lines with their holds for `full` iterations (default 1), then every
    remaining iteration flashes the `rest` lines at `fast_line_s` each.
    """
    seq: list[tuple[int, float, str]] = []
    visits: dict[int, int] = {}

    def add(n: int, hold: float) -> None:
        visits[n] = visits.get(n, 0) + 1
        k = visits[n]
        seq.append((n, hold, f"line.{n}" if k == 1 else f"line.{n}.{k}"))

    for item in step.get("seq", []):
        add(int(item["n"]), float(item.get("hold_s", timing.default_hold_s)))
    loop = step.get("loop")
    if loop:
        total = iterations if iterations is not None else 1
        full = min(int(loop.get("full", 1)), max(total, 0))
        fast = float(loop.get("fast_line_s", timing.fast_line_s))
        for i in range(total):
            if i < full:
                for item in loop["first"]:
                    add(int(item["n"]), float(item.get("hold_s", timing.default_hold_s)))
            else:
                for item in loop["rest"]:
                    add(int(item["n"]), fast)
            seq.append((0, 0.0, f"loop.{i}"))
    return seq


def step_duration(
    step: Mapping[str, Any],
    timing: Timing,
    reading_wps: float = DEFAULT_READING_WPS,
    iterations: int | None = None,
) -> float:
    """Seconds a debugger step stays on screen: its line holds or all its notes, whichever is longer."""
    seq_total = sum(h for n, h, _ in line_holds(step, timing, iterations) if n)
    notes = sum(note_time(n["term"], n["text"], timing, reading_wps) for n in step.get("notes", []))
    return max(seq_total + timing.step_tail_s, notes + timing.step_notes_pad_s if step.get("notes") else 0.0)


@dataclass(slots=True)
class StepTiming:
    id: str
    start: float
    dur: float
    marks: dict[str, float]


# ---- notes -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NoteWindow:
    term: str
    text: str
    start: float
    end: float


def note_windows(
    notes: Sequence[Mapping[str, Any]],
    start: float,
    timing: Timing,
    reading_wps: float,
    *,
    total: float | None = None,
    marks: Mapping[str, float] | None = None,
) -> list[NoteWindow]:
    """Glossary notes one after another; each stays as long as it takes to read.

    With `total`, the durations are stretched to fill that span. A note with an `at` anchor starts
    there instead of right after the previous one.
    """
    durs = [note_time(n["term"], n["text"], timing, reading_wps) for n in notes]
    if total and durs:
        factor = max(1.0, total / sum(durs))
        durs = [d * factor for d in durs]
    out: list[NoteWindow] = []
    t = start
    for n, d in zip(notes, durs, strict=True):
        if n.get("at") is not None:
            t = anchor_time(n["at"], marks or {})
        out.append(NoteWindow(n["term"], n["text"], t, t + d - NOTE_GAP_S))
        t += d
    return out


def anchor_time(anchor: Mapping[str, Any] | None, marks: Mapping[str, float], default: float = 0.0) -> float:
    """Resolve `{"at": mark, "offset": s}` or `{"at_s": s}` to scene-relative seconds."""
    if not anchor:
        return default
    if "at_s" in anchor:
        return float(anchor["at_s"])
    mark = str(anchor["at"])
    if mark not in marks:
        raise TimingError(f"unknown mark {mark!r}")
    return marks[mark] + float(anchor.get("offset", 0.0))


# ---- scenes ------------------------------------------------------------------------------------


@dataclass(slots=True)
class SceneTiming:
    id: str
    duration: float
    marks: dict[str, float]
    notes: list[NoteWindow]
    terminal: TerminalTiming | None = None
    steps: list[StepTiming] = field(default_factory=list)
    debugger_enter: float | None = None
    debugger_resume: float | None = None


def scene_timing(
    scene: Mapping[str, Any],
    timing: Timing,
    reading_wps: float = DEFAULT_READING_WPS,
    captures: Mapping[str, Any] | None = None,
    line_counts: Mapping[str, int] | None = None,
) -> SceneTiming:
    """Timeline of one scene: terminal events, debugger steps, notes and the scene's own length."""
    kind = scene["kind"]
    marks: dict[str, float] = {}
    term: TerminalTiming | None = None
    steps: list[StepTiming] = []
    enter: float | None = None
    resume: float | None = None
    notes: list[NoteWindow] = []
    content_end = 0.0

    if kind in ("terminal", "debugger"):
        events = scene["terminal"]["events"]
        if kind == "debugger":
            dbg = scene["debugger"]
            term, used = run_terminal(events, timing, stop_after=dbg["after"], line_counts=line_counts)
            enter = term.end + DEBUGGER_ENTER_DELAY_S
            marks["debugger.enter"] = enter
            t = enter
            for step in dbg["steps"]:
                iters = _iterations(step, captures)
                dur = step_duration(step, timing, reading_wps, iters)
                st = StepTiming(step["id"], t, dur, {f"{step['id']}.start": t})
                lt = t + STEP_LEAD_S
                for _n, hold, name in line_holds(step, timing, iters):
                    st.marks.setdefault(f"{step['id']}.{name}", lt)
                    lt += hold
                marks.update(st.marks)
                notes += note_windows(
                    step.get("notes", []), t + NOTE_START_DELAY_S, timing, reading_wps, total=dur - 0.4
                )
                steps.append(st)
                t += dur
            resume = t + DEBUGGER_RESUME_PAD_S
            marks["debugger.resume"] = resume
            term.end = resume
            term, _ = run_terminal(events[used:], timing, line_counts=line_counts, state=term)
        else:
            term, _ = run_terminal(events, timing, line_counts=line_counts)
        marks.update(term.marks)
        content_end = term.end
    elif kind == "title":
        lines = scene["title"]["lines"]
        content_end = 0.4 + (
            1.2 * min(len(lines) - 1, 2) if scene["title"].get("reveal") == "by_line" else 0.0
        )
    elif kind == "diagram":
        content_end = _diagram_end(scene["diagram"], marks)

    scene_notes = scene.get("notes", [])
    if scene_notes:
        first = scene_notes[0].get("at")
        start = anchor_time(first, marks, DEFAULT_NOTES_START_S) if first else DEFAULT_NOTES_START_S
        notes += note_windows(scene_notes, start, timing, reading_wps, marks=marks)
    notes_end = max((w.end for w in notes), default=0.0) if scene_notes else 0.0

    tail = float(scene.get("tail_s", timing.scene_tail_s))
    duration = max(
        content_end + tail,
        notes_end + timing.step_notes_pad_s if scene_notes else 0.0,
        float(scene.get("min_duration_s", 0.0)),
    )
    return SceneTiming(scene["id"], duration, marks, notes, term, steps, enter, resume)


def _iterations(step: Mapping[str, Any], captures: Mapping[str, Any] | None) -> int | None:
    loop = step.get("loop")
    if not loop:
        return None
    name = loop["iterations"]["capture"]
    if captures is None or name not in captures:
        return 1
    raw = captures[name]
    value = raw.get("value") if isinstance(raw, Mapping) else raw
    return max(0, int(float(str(value))))


def _diagram_end(diagram: Mapping[str, Any], marks: Mapping[str, float]) -> float:
    end = 0.0
    for el in diagram.get("elements", []):
        for key in ("appear", "disappear"):
            if el.get(key):
                end = max(end, anchor_time(el[key], marks))
    return end


# ---- whole script ------------------------------------------------------------------------------


@dataclass(slots=True)
class Estimate:
    total_s: float
    scenes: list[SceneTiming]
    starts: list[float]


def estimate(
    script: Mapping[str, Any],
    timing: Timing | None = None,
    reading_wps: float = DEFAULT_READING_WPS,
    captures: Mapping[str, Any] | None = None,
    line_counts: Mapping[str, int] | None = None,
) -> Estimate:
    """Total length and per-scene timeline of a script."""
    timing = timing or Timing()
    scenes = [scene_timing(s, timing, reading_wps, captures, line_counts) for s in script["scenes"]]
    starts: list[float] = []
    acc = 0.0
    for s in scenes:
        starts.append(acc)
        acc += s.duration
    return Estimate(acc, scenes, starts)


def frames(total_s: float, fps: int) -> int:
    """Frame count of the finished video: `round(total_s * fps)` (half up, like the reference)."""
    return math.floor(total_s * fps + 0.5)
