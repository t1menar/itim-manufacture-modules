"""C syntax highlighting on the dark window (ported unchanged from the reference)."""

from __future__ import annotations

import re

from mvrender.palette import CODE_FG, CODE_PUNCT, RGB, Palette

C_KEYWORDS = frozenset(
    [
        "if",
        "else",
        "for",
        "while",
        "do",
        "return",
        "static",
        "void",
        "char",
        "int",
        "bool",
        "const",
        "sizeof",
        "case",
        "break",
        "true",
        "false",
        "NULL",
    ]
)

Segments = list[tuple[str, RGB]]


def highlight_c(text: str, in_comment: bool, pal: Palette) -> tuple[Segments, bool]:
    """Colour verbatim source text (tabs already expanded); returns the segments and whether a
    block comment is still open at the end of the line."""
    segs: Segments = []
    i = 0
    s = text.lstrip()
    if in_comment or s.startswith("* ") or s == "*" or s.startswith("*/"):
        end = text.find("*/")
        if end < 0:
            return [(text, pal.c_comment)], True
        segs.append((text[: end + 2], pal.c_comment))
        i = end + 2
    while i < len(text):
        rest = text[i:]
        if rest.startswith("/*"):
            end = rest.find("*/", 2)
            if end < 0:
                segs.append((rest, pal.c_comment))
                return segs, True
            segs.append((rest[: end + 2], pal.c_comment))
            i += end + 2
            continue
        m = re.match(r'"(?:\\.|[^"\\])*"', rest)
        if m:
            segs.append((m.group(0), pal.c_str))
            i += len(m.group(0))
            continue
        m = re.match(r"[A-Za-z_][A-Za-z_0-9]*", rest)
        if m:
            w = m.group(0)
            after = rest[len(w) :].lstrip()
            if w in C_KEYWORDS:
                col = pal.c_kw
            elif after.startswith("("):
                col = pal.c_fn
            elif re.fullmatch(r"[A-Z][A-Z0-9_]+", w):
                col = pal.c_macro
            elif re.fullmatch(r"[A-Z][a-z]+[A-Za-z0-9]*", w):
                col = pal.c_type
            else:
                col = CODE_FG
            segs.append((w, col))
            i += len(w)
            continue
        m = re.match(r"\d+", rest)
        if m:
            segs.append((m.group(0), pal.c_num))
            i += len(m.group(0))
            continue
        segs.append((rest[0], CODE_PUNCT))
        i += 1
    return segs, False
