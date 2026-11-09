"""`mvrender preview DIR --at 2 12 40`: write PNG stills of a job directory."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mvrender.frame import make_context, render_frame
from mvrender.resolve import resolve
from mvrender.scenario import load_capture, load_scenario


class DirSource:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _find(self, path: str) -> Path | None:
        for cand in (self.root / path, self.root / Path(path).name):
            if cand.is_file():
                return cand
        return None

    def exists(self, path: str) -> bool:
        return self._find(path) is not None

    def line(self, path: str, n: int) -> str | None:
        f = self._find(path)
        if f is None:
            return None
        lines = f.read_text(encoding="utf-8", errors="replace").split("\n")
        return lines[n - 1] if 1 <= n <= len(lines) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mvrender")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pv = sub.add_parser("preview", help="write PNG stills at the given times (seconds)")
    pv.add_argument("directory", help="holds script.en.json and capture.json")
    pv.add_argument("--src", required=True, help="source tree for the explained system")
    pv.add_argument(
        "--fonts", help="directory with Inter and JetBrains Mono (default /usr/share/fonts/manufacture)"
    )
    pv.add_argument("--settings", help="settings values JSON")
    pv.add_argument("--at", nargs="+", type=float, required=True)
    pv.add_argument("--out", default=".", help="output directory")
    sh = sub.add_parser("sheet", help="contact sheet with the safe-zone overlay")
    for a in (sh,):
        a.add_argument("directory")
        a.add_argument("--src", required=True)
        a.add_argument("--fonts")
        a.add_argument("--settings")
        a.add_argument("--every", type=float, default=10.0, help="seconds between thumbnails")
        a.add_argument("--out", default="sheet.png")
    args = ap.parse_args(argv)

    root = Path(args.directory)
    resolved = resolve(
        load_scenario(root / "script.en.json"), load_capture(root / "capture.json"), DirSource(Path(args.src))
    )
    settings = json.loads(Path(args.settings).read_text()) if args.settings else None
    ctx = make_context(resolved, args.fonts, settings)
    if args.cmd == "sheet":
        from mvrender.sheet import build_sheet

        times = [i * args.every for i in range(int(ctx.timeline.total_s // args.every) + 1)]
        build_sheet(ctx, times).save(args.out)
        sys.stdout.write(f"{args.out}\n")
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for t in args.at:
        img, _ = render_frame(ctx, t)
        path = out / f"frame_{t:07.2f}.png"
        img.save(path)
        sys.stdout.write(f"{path}\n")
    sys.stdout.write(f"total {ctx.timeline.total_s:.2f} s, {ctx.timeline.frames} frames\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
