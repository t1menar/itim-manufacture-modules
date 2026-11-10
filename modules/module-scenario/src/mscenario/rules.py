"""Rules beyond the JSON Schema for the script (ported from module-video; research rules live in verify.py).

Every rule returns `Issue`s and never raises on bad content; the schema is checked first, so
these functions may assume the documents have the right shape (they still avoid crashing on the
missing optional parts).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from mvrender import timing as tm

from mscenario.issues import Issue
from mscenario.sources import SourceTree

PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]{0,47})\}")
# A number as the viewer reads it: not glued to letters or underscores ("template1", "REL_17_STABLE"
# are names, not numbers), may contain decimal and thousands separators.
NUMBER = re.compile(r"(?<![A-Za-z_\d])\d+(?:[.,]\d+)*(?![A-Za-z_\d])")
STEP_NUMBER = re.compile(r"^\s*Step\s+\d+\.")
MARKUP = "*"

# Width of the caption area at the minimum caption size; the real glyph metrics arrive with the
# renderer (B4). Inter Bold averages about 0.55 em per character on mixed text.
CAPTION_WIDTH_PX = 960
AVG_EM = 0.55
NOTE_CHARS_PER_LINE = 80


@dataclass(slots=True)
class RuleConfig:
    """The settings the rules read (a subset of the job's settings snapshot)."""

    allowed_symbols: str = "…—–→≈×=·%/()[]{}<>:;,.!?'\"*+-_#@&"
    forbidden_patterns: Sequence[str] = (
        "(?i)gdb session",
        "(?i)next video",
        r"(?i)part \d+ of",
        r"\b[0-9a-f]{12,40}\b",
    )
    caption_min_px: int = 44
    caption_max_lines: int = 2
    hook_max_lines: int = 3
    note_max_lines: int = 2
    duration_min_s: float = 10.0  # permissive: the idea's constraints narrow it
    duration_max_s: float = 180.0
    timing: tm.Timing = field(default_factory=tm.Timing)
    reading_wps: float = tm.DEFAULT_READING_WPS
    research_hosts: Sequence[str] = ()  # empty: any https host passes
    sandbox_images: Sequence[str] = ()  # empty: image keys are not checked

    @classmethod
    def from_idea(cls, idea: Mapping[str, Any] | None) -> RuleConfig:
        """The idea's `constraints` override the defaults; there are no hard limits of this module's own."""
        c = (idea or {}).get("constraints") or {}
        cfg = cls()
        dur = c.get("duration_s") or {}
        cfg.duration_min_s = float(dur.get("min", cfg.duration_min_s))
        cfg.duration_max_s = float(dur.get("max", cfg.duration_max_s))
        for name in ("hook_max_lines", "caption_max_lines", "note_max_lines"):
            if c.get(name):
                setattr(cfg, name, int(c[name]))
        if c.get("reading_wps"):
            cfg.reading_wps = float(c["reading_wps"])
        cfg.research_hosts = tuple(c.get("allowed_domains") or ())
        return cfg


# ---- text inventory ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Piece:
    """One piece of on-screen text and where it lives."""

    path: str
    text: str
    kind: str  # caption note status label footer title heading command highlight annotation
    scene: int
    facts: tuple[str, ...] = ()

    @property
    def human(self) -> bool:
        return self.kind not in ("command", "highlight", "annotation")


def pieces(script: Mapping[str, Any]) -> Iterator[Piece]:
    """Every string a viewer sees, with its JSON pointer and the facts that may source its numbers."""
    for si, scene in enumerate(script.get("scenes", [])):
        base = f"/scenes/{si}"
        sfacts = tuple(scene.get("facts", []))
        for ci, cap in enumerate(scene.get("captions", [])):
            for li, line in enumerate(cap.get("lines", [])):
                yield Piece(f"{base}/captions/{ci}/lines/{li}", line, "caption", si, sfacts)
        yield from _notes(scene.get("notes", []), f"{base}/notes", si, sfacts)
        title = scene.get("title") or {}
        for li, line in enumerate(title.get("lines", [])):
            yield Piece(f"{base}/title/lines/{li}", line, "title", si, sfacts)
        if title.get("footer"):
            yield Piece(f"{base}/title/footer", title["footer"], "footer", si, sfacts)
        for key in ("diagram", "panel"):
            yield from _diagram(scene.get(key), f"{base}/{key}", si, sfacts)
        for ei, ev in enumerate((scene.get("terminal") or {}).get("events", [])):
            ep = f"{base}/terminal/events/{ei}"
            if "cmd" in ev:
                yield Piece(f"{ep}/text", ev["text"], "command", si, sfacts)
                for hi, h in enumerate((ev.get("output") or {}).get("highlight", [])):
                    yield Piece(f"{ep}/output/highlight/{hi}", h, "highlight", si, sfacts)
            for ai, a in enumerate(ev.get("annotation", [])):
                yield Piece(f"{ep}/annotation/{ai}", a, "annotation", si, sfacts)
        for ti, step in enumerate((scene.get("debugger") or {}).get("steps", [])):
            sp = f"{base}/debugger/steps/{ti}"
            stf = sfacts + tuple(step.get("facts", []))
            for li, line in enumerate(step.get("caption", [])):
                yield Piece(f"{sp}/caption/{li}", line, "caption", si, stf)
            yield from _notes(step.get("notes", []), f"{sp}/notes", si, stf)
            if step.get("status"):
                yield Piece(f"{sp}/status", step["status"], "status", si, stf)


def _notes(notes: Sequence[Mapping[str, Any]], base: str, si: int, facts: tuple[str, ...]) -> Iterator[Piece]:
    for ni, n in enumerate(notes):
        nf = facts + tuple(n.get("facts", []))
        yield Piece(f"{base}/{ni}/term", n["term"], "note", si, nf)
        yield Piece(f"{base}/{ni}/text", n["text"], "note", si, nf)


def _diagram(d: Mapping[str, Any] | None, base: str, si: int, facts: tuple[str, ...]) -> Iterator[Piece]:
    if not d:
        return
    if d.get("heading"):
        yield Piece(f"{base}/heading", d["heading"], "heading", si, facts)
    if d.get("footer"):
        yield Piece(f"{base}/footer", d["footer"], "footer", si, facts)
    for ei, el in enumerate(d.get("elements", [])):
        for key in ("label", "name", "sub", "text"):
            if el.get(key):
                yield Piece(f"{base}/elements/{ei}/{key}", el[key], "label", si, facts)


def strip_markup(text: str) -> str:
    return text.replace(MARKUP, "")


# ---- anchors, ids, marks -----------------------------------------------------------------------


def _anchors(script: Mapping[str, Any]) -> Iterator[tuple[str, int, Mapping[str, Any]]]:
    """(pointer, scene index, anchor) for every anchor in the script."""
    for si, scene in enumerate(script.get("scenes", [])):
        base = f"/scenes/{si}"
        for ci, cap in enumerate(scene.get("captions", [])):
            if cap.get("at"):
                yield f"{base}/captions/{ci}/at", si, cap["at"]
        for ni, n in enumerate(scene.get("notes", [])):
            if n.get("at"):
                yield f"{base}/notes/{ni}/at", si, n["at"]
        for key in ("diagram", "panel"):
            d = scene.get(key)
            if not d:
                continue
            if d.get("footer_at"):
                yield f"{base}/{key}/footer_at", si, d["footer_at"]
            for ei, el in enumerate(d.get("elements", [])):
                for ak in ("appear", "disappear"):
                    if el.get(ak):
                        yield f"{base}/{key}/elements/{ei}/{ak}", si, el[ak]
        for ti, step in enumerate((scene.get("debugger") or {}).get("steps", [])):
            for ni, n in enumerate(step.get("notes", [])):
                if n.get("at"):
                    yield f"{base}/debugger/steps/{ti}/notes/{ni}/at", si, n["at"]
    cover = (script.get("meta") or {}).get("cover") or {}
    if cover.get("at"):
        yield "/meta/cover/at", -1, cover["at"]


def scene_marks(script: Mapping[str, Any], cfg: RuleConfig) -> list[dict[str, float]]:
    """Marks each scene's terminal and debugger generate (anchors and notes stripped out)."""
    out: list[dict[str, float]] = []
    for scene in script.get("scenes", []):
        bare = {k: v for k, v in scene.items() if k not in ("notes", "diagram", "panel", "captions")}
        bare["captions"] = []
        try:
            out.append(tm.scene_timing(bare, cfg.timing, cfg.reading_wps).marks)
        except (tm.TimingError, KeyError, TypeError, ValueError):
            out.append({})
    return out


def check_ids_unique(script: Mapping[str, Any], cfg: RuleConfig, file: str = "") -> list[Issue]:
    issues: list[Issue] = []

    def uniq(kind: str, items: Iterator[tuple[str, str]]) -> None:
        seen: dict[str, str] = {}
        for ident, ptr in items:
            if ident in seen:
                issues.append(Issue("ids_unique", ptr, f"{kind} id {ident!r} already used at {seen[ident]}", file))
            else:
                seen[ident] = ptr

    scenes = script.get("scenes", [])
    uniq("scene", ((s["id"], f"/scenes/{i}/id") for i, s in enumerate(scenes)))
    cmds = (
        (e["cmd"], f"/scenes/{i}/terminal/events/{j}/cmd")
        for i, s in enumerate(scenes)
        for j, e in enumerate((s.get("terminal") or {}).get("events", []))
        if "cmd" in e
    )
    uniq("command", cmds)
    uniq(
        "step",
        (
            (st["id"], f"/scenes/{i}/debugger/steps/{k}/id")
            for i, s in enumerate(scenes)
            for k, st in enumerate((s.get("debugger") or {}).get("steps", []))
        ),
    )
    uniq(
        "element",
        (
            (el["id"], f"/scenes/{i}/{key}/elements/{k}/id")
            for i, s in enumerate(scenes)
            for key in ("diagram", "panel")
            for k, el in enumerate((s.get(key) or {}).get("elements", []))
        ),
    )
    for i, s in enumerate(scenes):
        dbg = s.get("debugger")
        if dbg:
            own = {e["cmd"] for e in (s.get("terminal") or {}).get("events", []) if "cmd" in e}
            if dbg["after"] not in own:
                issues.append(
                    Issue(
                        "ids_unique",
                        f"/scenes/{i}/debugger/after",
                        f"{dbg['after']!r} is not a command of this scene",
                        file,
                    )
                )
    # sessions used by commands exist: session names are only names, nothing to look up here
    marks = scene_marks(script, cfg)
    for ptr, si, anchor in _anchors(script):
        if "at" not in anchor:
            continue
        name = anchor["at"]
        known = marks[si] if 0 <= si < len(marks) else {}
        if si == -1:
            known = {}
            scene_id = (script.get("meta", {}).get("cover") or {}).get("scene")
            for k, sc in enumerate(scenes):
                if sc["id"] == scene_id:
                    known = marks[k]
        if name not in known:
            issues.append(Issue("ids_unique", ptr, f"anchor mark {name!r} does not exist in this scene", file))
    for i, sc in enumerate(scenes):
        for ei, el in enumerate(
            (sc.get("diagram") or {}).get("elements", []) + (sc.get("panel") or {}).get("elements", [])
        ):
            step = (el.get("follow") or {}).get("step")
            if step and step not in {st["id"] for st in (sc.get("debugger") or {}).get("steps", [])}:
                issues.append(
                    Issue("ids_unique", f"/scenes/{i}/elements/{ei}/follow/step", f"unknown step {step!r}", file)
                )
    cover = (script.get("meta") or {}).get("cover") or {}
    if cover and cover.get("scene") not in {s["id"] for s in scenes}:
        issues.append(Issue("ids_unique", "/meta/cover/scene", f"unknown scene {cover.get('scene')!r}", file))
    return issues


# ---- sources and expectations ------------------------------------------------------------------


def _line_refs(script: Mapping[str, Any]) -> Iterator[tuple[str, str, int, str, list[list[int]] | None]]:
    """(pointer, file alias, line, expect, step ranges or None for code cards)."""
    for si, scene in enumerate(script.get("scenes", [])):
        for ti, step in enumerate((scene.get("debugger") or {}).get("steps", [])):
            base = f"/scenes/{si}/debugger/steps/{ti}"
            ranges = step.get("ranges", [])
            for li, ln in enumerate(step.get("seq", [])):
                yield f"{base}/seq/{li}", step["file"], ln["n"], ln["expect"], ranges
            loop = step.get("loop") or {}
            for part in ("first", "rest"):
                for li, ln in enumerate(loop.get(part, [])):
                    yield f"{base}/loop/{part}/{li}", step["file"], ln["n"], ln["expect"], ranges
        for key in ("diagram", "panel"):
            for ei, el in enumerate((scene.get(key) or {}).get("elements", [])):
                if el.get("type") != "code_card":
                    continue
                for num, exp in (el.get("expect") or {}).items():
                    yield (
                        f"/scenes/{si}/{key}/elements/{ei}/expect/{num}",
                        el.get("file", ""),
                        int(num),
                        exp,
                        None,
                    )


def check_sources(script: Mapping[str, Any], source: SourceTree | None, file: str = "") -> list[Issue]:
    """`sources_known` and `expect_match`."""
    issues: list[Issue] = []
    aliases: Mapping[str, str] = script.get("sources", {})

    def path_of(alias: str) -> str | None:
        return aliases.get(alias)

    for si, scene in enumerate(script.get("scenes", [])):
        for ti, step in enumerate((scene.get("debugger") or {}).get("steps", [])):
            ptr = f"/scenes/{si}/debugger/steps/{ti}/file"
            if step["file"] not in aliases:
                issues.append(Issue("sources_known", ptr, f"file alias {step['file']!r} is not in sources", file))
        for key in ("diagram", "panel"):
            for ei, el in enumerate((scene.get(key) or {}).get("elements", [])):
                if el.get("type") == "code_card" and el.get("file") not in aliases:
                    issues.append(
                        Issue(
                            "sources_known",
                            f"/scenes/{si}/{key}/elements/{ei}/file",
                            f"file alias {el.get('file')!r} is not in sources",
                            file,
                        )
                    )
    if source is not None:
        for alias, path in aliases.items():
            if not source.exists(path):
                issues.append(
                    Issue(
                        "sources_known",
                        f"/sources/{alias}",
                        f"path {path!r} does not exist at the pinned commit",
                        file,
                    )
                )

    for ptr, alias, n, expect, ranges in _line_refs(script):
        if ranges is not None and not any(a <= n <= b for a, b in ranges):
            issues.append(Issue("expect_match", ptr, f"line {n} is outside the step's ranges {ranges}", file))
        cited = path_of(alias)
        if source is None or cited is None or not source.exists(cited):
            continue
        actual = source.line(cited, n)
        if actual is None:
            issues.append(Issue("expect_match", ptr, f"{cited} has no line {n}", file))
        elif expect not in actual:
            issues.append(
                Issue(
                    "expect_match",
                    ptr,
                    f"{path}:{n} does not contain {expect!r}; the line is {actual.strip()!r}",
                    file,
                )
            )
    return issues


# ---- captures ----------------------------------------------------------------------------------


def _capture_uses(script: Mapping[str, Any]) -> dict[str, list[str]]:
    uses: dict[str, list[str]] = {}

    def add(name: str, ptr: str) -> None:
        uses.setdefault(name, []).append(ptr)

    for pc in pieces(script):
        if pc.kind in ("command", "annotation"):
            continue
        for m in PLACEHOLDER.finditer(pc.text):
            add(m.group(1), pc.path)

    def walk(node: Any, ptr: str) -> None:
        if isinstance(node, dict):
            if "capture" in node and isinstance(node["capture"], str):
                add(node["capture"], ptr + "/capture")
            for k, v in node.items():
                walk(v, f"{ptr}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{ptr}/{i}")

    walk(script.get("scenes", []), "/scenes")
    for pc in pieces(script):
        if pc.kind == "annotation":
            for m in PLACEHOLDER.finditer(pc.text):
                add(m.group(1), pc.path)
    return uses


def check_captures(script: Mapping[str, Any], file: str = "") -> list[Issue]:
    declared = set(script.get("captures", {}))
    uses = _capture_uses(script)
    issues = [
        Issue("captures_declared", ptrs[0], f"capture {name!r} is used but not declared in captures", file)
        for name, ptrs in sorted(uses.items())
        if name not in declared
    ]
    issues += [
        Issue("captures_declared", f"/captures/{name}", f"capture {name!r} is declared but never used", file)
        for name in sorted(declared - set(uses))
    ]
    return issues


# ---- numbers ----------------------------------------------------------------------------------


def numbers_in(text: str) -> list[str]:
    cleaned = PLACEHOLDER.sub(" ", strip_markup(text))
    cleaned = STEP_NUMBER.sub(" ", cleaned)
    return NUMBER.findall(cleaned)


def check_numbers(script: Mapping[str, Any], research: Mapping[str, Any] | None, file: str = "") -> list[Issue]:
    """`numbers_sourced`: every number on screen comes from capture, a listed fact or the system version."""
    if research is None:
        return []
    fact_numbers = {f["id"]: set(NUMBER.findall(f["text"])) for f in research.get("facts", [])}
    version = str(((script.get("meta") or {}).get("system") or {}).get("version", ""))
    allowed_always = set(NUMBER.findall(version))
    paths = " ".join(script.get("sources", {}).values()) + " " + " ".join(script.get("sources", {}))
    issues: list[Issue] = []
    for pc in pieces(script):
        if not pc.human:
            continue
        nums = numbers_in(pc.text)
        if not nums:
            continue
        ok: set[str] = set(allowed_always)
        for fid in pc.facts:
            ok |= fact_numbers.get(fid, set())
        for num in nums:
            if num in ok or num in NUMBER.findall(paths):
                continue
            issues.append(
                Issue(
                    "numbers_sourced",
                    pc.path,
                    f"number {num!r} in {pc.text!r} has no capture placeholder or listed fact that contains it",
                    file,
                )
            )
    return issues


# ---- terms -------------------------------------------------------------------------------------


def _term_regex(term: str) -> re.Pattern[str]:
    flags = 0 if term.isupper() and len(term) > 1 else re.IGNORECASE  # acronyms match exactly
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", flags)


def check_terms(script: Mapping[str, Any], research: Mapping[str, Any] | None, file: str = "") -> list[Issue]:
    """`terms_noted`: a must_explain term needs a note in the first scene where it is visible, or earlier."""
    if research is None:
        return []
    issues: list[Issue] = []
    all_pieces = list(pieces(script))
    for term in research.get("terms", []):
        if not term.get("must_explain"):
            continue
        names = [term["term"], *term.get("aliases", [])]
        regexes = [_term_regex(n) for n in names]
        first = next(
            (pc for pc in all_pieces if any(r.search(strip_markup(PLACEHOLDER.sub("", pc.text))) for r in regexes)),
            None,
        )
        if first is None:
            continue
        noted = [
            pc
            for pc in all_pieces
            if pc.kind == "note"
            and pc.path.endswith("/term")
            and pc.scene <= first.scene
            and any(pc.text.casefold() == n.casefold() for n in names)
        ]
        if not noted:
            issues.append(
                Issue(
                    "terms_noted",
                    first.path,
                    f"term {term['term']!r} is visible in scene {first.scene} but no note explains it by then",
                    file,
                )
            )
    return issues


# ---- fit, forbidden text, language, hook, duration ---------------------------------------------


def _placeholder_width(text: str) -> str:
    return PLACEHOLDER.sub("00000", strip_markup(text))


def check_fit(script: Mapping[str, Any], cfg: RuleConfig, file: str = "") -> list[Issue]:
    """`caption_fit` and `note_fit`, with an estimated glyph width (exact metrics: renderer, B4)."""
    issues: list[Issue] = []
    for si, scene in enumerate(script.get("scenes", [])):
        limit = cfg.hook_max_lines if si == 0 else cfg.caption_max_lines
        for ci, cap in enumerate(scene.get("captions", [])):
            lines = cap.get("lines", [])
            if len(lines) > limit:
                issues.append(
                    Issue(
                        "caption_fit",
                        f"/scenes/{si}/captions/{ci}/lines",
                        f"{len(lines)} lines, at most {limit} allowed",
                        file,
                    )
                )
            for li, line in enumerate(lines):
                width = len(_placeholder_width(line)) * cfg.caption_min_px * AVG_EM
                if width > CAPTION_WIDTH_PX:
                    issues.append(
                        Issue(
                            "caption_fit",
                            f"/scenes/{si}/captions/{ci}/lines/{li}",
                            f"{line!r} needs about {width:.0f} px at {cfg.caption_min_px} px, the area is {CAPTION_WIDTH_PX} px",
                            file,
                        )
                    )
        notes = list(enumerate(scene.get("notes", [])))
        paths = [f"/scenes/{si}/notes/{i}" for i, _ in notes]
        for ti, step in enumerate((scene.get("debugger") or {}).get("steps", [])):
            for ci, line in enumerate(step.get("caption", [])):
                width = len(_placeholder_width(line)) * cfg.caption_min_px * AVG_EM
                if width > CAPTION_WIDTH_PX:
                    issues.append(
                        Issue(
                            "caption_fit",
                            f"/scenes/{si}/debugger/steps/{ti}/caption/{ci}",
                            f"{line!r} needs about {width:.0f} px, the area is {CAPTION_WIDTH_PX} px",
                            file,
                        )
                    )
            for ni, n in enumerate(step.get("notes", [])):
                notes.append((ni, n))
                paths.append(f"/scenes/{si}/debugger/steps/{ti}/notes/{ni}")
        for (_, n), ptr in zip(notes, paths, strict=True):
            chars = len(_placeholder_width(n["term"])) + 2 + len(_placeholder_width(n["text"]))
            if chars > cfg.note_max_lines * NOTE_CHARS_PER_LINE:
                issues.append(
                    Issue(
                        "note_fit",
                        ptr,
                        f"term and text need about {chars} characters, {cfg.note_max_lines} lines hold {cfg.note_max_lines * NOTE_CHARS_PER_LINE}",
                        file,
                    )
                )
    return issues


def check_forbidden(script: Mapping[str, Any], cfg: RuleConfig, file: str = "") -> list[Issue]:
    patterns = [re.compile(p) for p in cfg.forbidden_patterns]
    issues: list[Issue] = []
    for pc in pieces(script):
        for p in patterns:
            if p.search(pc.text):
                issues.append(
                    Issue(
                        "no_forbidden",
                        pc.path,
                        f"{pc.text!r} matches the forbidden pattern {p.pattern!r}",
                        file,
                    )
                )
    return issues


def _allowed_char(ch: str, symbols: str) -> bool:
    if ch.isspace() or ch.isdigit() or ch in symbols:
        return True
    o = ord(ch)
    return ch.isalpha() and (o < 0x250 or 0x1E00 <= o <= 0x1EFF)  # Latin letters only


def check_english(script: Mapping[str, Any], cfg: RuleConfig, file: str = "") -> list[Issue]:
    issues: list[Issue] = []
    for pc in pieces(script):
        if not pc.human:
            continue
        bad = sorted({c for c in pc.text if not _allowed_char(c, cfg.allowed_symbols)})
        if bad:
            shown = ", ".join(f"{c!r} U+{ord(c):04X}" for c in bad)
            issues.append(
                Issue(
                    "english_only",
                    pc.path,
                    f"characters outside Latin script and allowed symbols: {shown}",
                    file,
                )
            )
    return issues


def check_hook(script: Mapping[str, Any], file: str = "") -> list[Issue]:
    scenes = script.get("scenes", [])
    if not scenes:
        return []
    first = scenes[0]
    if "hook" not in first:
        return [Issue("hook_first", "/scenes/0/hook", "scene 0 has no hook", file)]
    caps = first.get("captions", [])
    at = (caps[0].get("at") if caps else None) or {}
    if not caps or at.get("at") is not None or float(at.get("at_s", 0.0)) > 0:
        return [
            Issue(
                "hook_first",
                "/scenes/0/captions/0/at",
                "the first caption of scene 0 must be visible from t = 0",
                file,
            )
        ]
    return []


def check_duration(script: Mapping[str, Any], cfg: RuleConfig, file: str = "") -> list[Issue]:
    try:
        est = tm.estimate(script, cfg.timing, cfg.reading_wps, captures=_estimate_captures(script))
    except (tm.TimingError, KeyError, TypeError, ValueError) as exc:
        return [Issue("duration", "/scenes", f"duration cannot be estimated: {exc}", file)]
    issues: list[Issue] = []
    total = est.total_s
    if not cfg.duration_min_s <= total <= cfg.duration_max_s:
        issues.append(
            Issue(
                "duration",
                "/scenes",
                f"estimated {total:.1f} s, allowed {cfg.duration_min_s:g} to {cfg.duration_max_s:g} s",
                file,
            )
        )
    target = (script.get("meta") or {}).get("target_duration_s")
    if target and abs(total - float(target)) > 0.2 * float(target):
        issues.append(
            Issue(
                "duration",
                "/meta/target_duration_s",
                f"estimated {total:.1f} s is more than 20 % away from the target {target} s",
                file,
            )
        )
    return issues


def _estimate_captures(script: Mapping[str, Any]) -> dict[str, Any]:
    """Loop iteration counts are unknown before capture; assume a modest loop for the estimate."""
    return {name: {"value": "10"} for name, c in script.get("captures", {}).items() if c.get("kind") == "number"}


# ---- entry ------------------------------------------------------------------------------------

ScriptRule = Callable[..., list[Issue]]


def check_script(
    script: Mapping[str, Any],
    *,
    research: Mapping[str, Any] | None = None,
    source: SourceTree | None = None,
    cfg: RuleConfig | None = None,
    file: str = "script.en.json",
) -> list[Issue]:
    """Run every script rule of 04 section 4.3."""
    cfg = cfg or RuleConfig()
    issues = check_ids_unique(script, cfg, file)
    issues += check_sources(script, source, file)
    issues += check_captures(script, file)
    issues += check_numbers(script, research, file)
    issues += check_terms(script, research, file)
    issues += check_fit(script, cfg, file)
    issues += check_forbidden(script, cfg, file)
    issues += check_english(script, cfg, file)
    issues += check_hook(script, file)
    if not any(i.rule == "ids_unique" for i in issues):
        issues += check_duration(script, cfg, file)
    return issues
