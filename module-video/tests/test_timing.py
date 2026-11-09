from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mvrender import timing as tm
from tests import refdata

T = tm.Timing()
WPS = tm.DEFAULT_READING_WPS


def test_note_time_matches_the_reference_formula() -> None:
    # reference: max(2.6, 1.0 + 0.22 * words); 4.5 words per second is 0.222 s per word
    text = "a BEGIN … COMMIT group of commands: applied as a whole or rolled back as a whole"
    words = len(("Transaction " + text).split())
    assert tm.note_time("Transaction", text, T, WPS) == pytest.approx(max(2.6, 1.0 + 0.22 * words), rel=0.02)


def test_short_notes_stay_at_the_minimum() -> None:
    assert tm.note_time("OID", "an id", T, WPS) == T.read_min_s


@given(st.integers(0, 60), st.integers(0, 60))
def test_note_time_is_monotonic_in_word_count(a: int, b: int) -> None:
    ta = tm.note_time("t", " ".join(["w"] * a), T, WPS)
    tb = tm.note_time("t", " ".join(["w"] * b), T, WPS)
    assert (ta <= tb) == (a <= b) or ta == tb  # equal only inside the minimum plateau


@given(st.integers(0, 40), st.floats(0.0, 3.0))
def test_step_duration_grows_with_notes_and_holds(n_notes: int, hold: float) -> None:
    def step(notes: int, h: float) -> dict[str, object]:
        return {
            "seq": [{"n": 1, "expect": "x", "hold_s": h}],
            "notes": [{"term": "t", "text": "word " * 10}] * notes,
        }

    assert tm.step_duration(step(n_notes, hold), T, WPS) <= tm.step_duration(step(n_notes + 1, hold), T, WPS)
    assert tm.step_duration(step(n_notes, hold), T, WPS) <= tm.step_duration(step(n_notes, hold + 1), T, WPS)


@given(st.text(min_size=1, max_size=80), st.text(min_size=0, max_size=40))
def test_typing_is_monotonic_in_length(a: str, extra: str) -> None:
    assert tm.typing_s(a, 24) <= tm.typing_s(a + extra, 24)


def test_terminal_timeline_and_marks() -> None:
    events = [
        {"cmd": "c1", "text": "x" * 24, "cps": 24, "output": {"lines": [0, 2], "gap_s": 0.1}},
        {"wait_s": 1.0},
        {"mark": "m"},
    ]
    tt, used = tm.run_terminal(events, T)
    assert used == 3
    assert tt.marks["c1.typed"] == pytest.approx(0.4 + 0.35 + 1.0)
    assert tt.marks["c1.output"] == pytest.approx(0.4 + 0.35 + 1.0 + 0.25)
    assert tt.marks["m"] == pytest.approx(tt.marks["c1.output"] + 0.3 + 1.0)
    assert tt.end == tt.marks["m"]


def test_stop_after_cuts_before_the_output() -> None:
    events = [{"cmd": "c1", "text": "abc", "output": {"lines": [0, 4]}}, {"cmd": "c2", "text": "d"}]
    tt, used = tm.run_terminal(events, T, stop_after="c1")
    assert used == 1 and "c1.output" not in tt.marks


def test_loop_expands_with_fast_iterations() -> None:
    step = {
        "loop": {
            "iterations": {"capture": "n"},
            "first": [{"n": 5, "expect": "x", "hold_s": 1.0}, {"n": 6, "expect": "y", "hold_s": 1.0}],
            "rest": [{"n": 5, "expect": "x"}],
            "fast_line_s": 0.2,
            "counter": "i",
        }
    }
    assert tm.step_duration(step, T, WPS, iterations=1) == pytest.approx(2.0 + T.step_tail_s)
    assert tm.step_duration(step, T, WPS, iterations=11) == pytest.approx(2.0 + 10 * 0.2 + T.step_tail_s)


def test_unknown_anchor_mark_is_an_error() -> None:
    with pytest.raises(tm.TimingError):
        tm.anchor_time({"at": "nope"}, {})


def test_frames_rounds_half_up() -> None:
    assert tm.frames(10.0, 60) == 600
    assert tm.frames(1.0083, 60) == 60  # 60.498 rounds down
    assert tm.frames(1.0084, 60) == 61  # 60.504 rounds up


def test_estimate_of_the_reference_is_within_three_percent() -> None:
    script = refdata.load("script.en.json")
    ref = json.loads((refdata.REFERENCE / "reference_durations.json").read_text())
    est = tm.estimate(script, T, WPS, captures={"n_pages": {"value": 14}})
    assert abs(est.total_s / ref["total"] - 1) < 0.03
    for scene, expected in zip(est.scenes, ref["scenes"], strict=True):
        assert abs(scene.duration - expected["dur"]) < 1.0, scene.id


def test_reference_debugger_steps_match() -> None:
    script = refdata.load("script.en.json")
    ref = json.loads((refdata.REFERENCE / "reference_durations.json").read_text())
    est = tm.estimate(script, T, WPS, captures={"n_pages": {"value": 14}})
    got = [s.dur for s in est.scenes[4].steps]
    for g, r in zip(got, ref["steps"], strict=True):
        assert abs(g - r["dur"]) / r["dur"] < 0.04


def test_line_marks_follow_the_visits() -> None:
    script = refdata.load("script.en.json")
    est = tm.estimate(script, T, WPS, captures={"n_pages": {"value": 14}})
    marks = est.scenes[4].marks
    assert marks["debugger.enter"] == marks["s0-entry.start"]
    assert marks["s2-template.line.981"] > marks["s2-template.line.978"]
    assert marks["s9-pages.loop.13"] > marks["s9-pages.loop.0"]
    assert marks["debugger.resume"] > marks["s9-pages.start"]
