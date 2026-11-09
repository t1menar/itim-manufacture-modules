"""Timeline of the resolved scenario: scene starts, marks and the events the renderer reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from mvrender import timing as tm


@dataclass(slots=True)
class Timeline:
    fps: int
    total_s: float
    frames: int
    scenes: list[tm.SceneTiming]
    starts: list[float]

    def locate(self, t: float) -> tuple[int, float]:
        """Scene index and scene-local time for absolute time `t`."""
        t = max(0.0, t)
        idx = len(self.scenes) - 1
        for i, s in enumerate(self.starts):
            if s <= t:
                idx = i
        return idx, t - self.starts[idx]

    def as_json(self) -> dict[str, Any]:
        marks: dict[str, float] = {}
        events: list[dict[str, Any]] = []
        for sc, start in zip(self.scenes, self.starts, strict=True):
            for name, at in sc.marks.items():
                marks[f"{sc.id}.{name}"] = round(start + at, 4)
            if sc.terminal:
                for ev in sc.terminal.events:
                    events.append({"t": round(start + ev.t, 4), "kind": ev.kind, "ref": ev.ref or sc.id})
        return {
            "format": "manufacture.timeline/1",
            "fps": self.fps,
            "frames": self.frames,
            "total_s": round(self.total_s, 4),
            "scenes": [
                {"id": s.id, "start": round(a, 4), "dur": round(s.duration, 4)}
                for s, a in zip(self.scenes, self.starts, strict=True)
            ],
            "marks": marks,
            "events": events,
            "cues": [],
        }


def build(
    resolved: Mapping[str, Any],
    timing: tm.Timing | None = None,
    reading_wps: float = tm.DEFAULT_READING_WPS,
    fps: int = 60,
) -> Timeline:
    captures = {k: {"value": v} for k, v in resolved.get("captures", {}).items()}
    counts: dict[str, int] = {}
    for scene in resolved["scenes"]:
        for ev in (scene.get("terminal") or {}).get("events", []):
            if "cmd" in ev:
                counts[ev["cmd"]] = len(ev.get("rows", []))
    est = tm.estimate(resolved, timing or tm.Timing(), reading_wps, captures, counts)
    return Timeline(fps, est.total_s, tm.frames(est.total_s, fps), est.scenes, est.starts)
