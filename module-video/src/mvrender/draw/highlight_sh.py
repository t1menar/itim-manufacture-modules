"""Terminal text colouring: typed commands and printed output."""

from __future__ import annotations

import re

from mvrender.draw.highlight_c import Segments
from mvrender.palette import OUT_FG, SQL_KW, Palette

# Keyword and tool tables: these are vocabulary of the terminal look, not content of any video.
SQL_KEYWORDS = frozenset(
    [
        "SELECT",
        "FROM",
        "WHERE",
        "CREATE",
        "DROP",
        "ALTER",
        "DATABASE",
        "TABLE",
        "INDEX",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "EXTENSION",
        "INSERT",
        "INTO",
        "UPDATE",
        "DELETE",
        "VALUES",
        "AS",
        "ORDER",
        "BY",
        "GROUP",
        "LIMIT",
        "JOIN",
        "ON",
        "SHOW",
        "SET",
    ]
)
TOOLS = frozenset(
    ["psql", "ls", "wc", "diff", "head", "tail", "cat", "grep", "sort", "uniq", "cd", "pwd", "echo"]
)
TOKEN = re.compile(r'"[^"]*"?|\$[A-Za-z_]+|<\(|\s+|[A-Za-z_][A-Za-z_0-9]*|\d+|.')


def highlight_cmd(text: str, pal: Palette) -> Segments:
    segs: Segments = []
    for tok in TOKEN.findall(text):
        if tok.startswith('"'):
            segs.append(('"', pal.c_str))
            segs += highlight_cmd(tok.strip('"'), pal)
            if tok.endswith('"') and len(tok) > 1:
                segs.append(('"', pal.c_str))
        elif tok.upper() in SQL_KEYWORDS and tok.isupper():
            segs.append((tok, SQL_KW))
        elif tok.startswith("$"):
            segs.append((tok, pal.c_type))
        elif tok in TOOLS:
            segs.append((tok, pal.accent))
        elif tok.startswith("-") or tok in ("|", "<("):
            segs.append((tok, pal.win_muted))
        else:
            segs.append((tok, pal.win_fg))
    return segs


def output_row(text: str, highlights: list[str], pal: Palette, continuation: str = "") -> Segments:
    """One printed line; `highlights` are substrings shown in the accent colour."""
    if continuation == "E":
        return [(text, pal.err_cont)]
    if continuation == "D":
        return [(text, pal.win_muted)]
    if text.startswith("ERROR:"):
        return [("ERROR:", pal.err), (text[6:], pal.err_cont)]
    if text.startswith("DETAIL:"):
        return [("DETAIL:", pal.detail), (text[7:], pal.win_muted)]
    if text.startswith("--"):
        return [(text, pal.win_muted)]
    spans: list[tuple[int, int]] = []
    for h in highlights:
        start = text.find(h) if h else -1
        if start >= 0:
            spans.append((start, start + len(h)))
    segs: Segments = []
    pos = 0
    for a, b in sorted(spans):
        if a < pos:
            continue
        if a > pos:
            segs.append((text[pos:a], OUT_FG))
        segs.append((text[a:b], pal.accent))
        pos = b
    if pos < len(text):
        segs.append((text[pos:], OUT_FG))
    return segs


def wrap_output(text: str, cols: int) -> list[tuple[str, str]]:
    """Soft-wrap a printed line at `cols`; returns (text, continuation kind) pairs."""
    kind = "E" if text.startswith("ERROR") else "D"
    out: list[tuple[str, str]] = []
    first = True
    while len(text) > cols:
        cut = text.rfind(" ", 0, cols)
        cut = cut if cut > 10 else cols
        out.append((text[:cut], "" if first else kind))
        text = "  " + text[cut:].lstrip()
        first = False
    out.append((text, "" if first else kind))
    return out
