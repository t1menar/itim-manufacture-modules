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
    rd = sub.add_parser("render", help="render, mix and package the finished video")
    rd.add_argument("directory")
    rd.add_argument("--src", required=True)
    rd.add_argument("--fonts")
    rd.add_argument("--settings")
    rd.add_argument("--out", default="out", help="output directory (video.en.mp4, cover.en.jpg, ...)")
    rd.add_argument("--workers", type=int, default=0)
    rd.add_argument("--limit-frames", type=int, default=0, help="render only the first frames (smoke test)")
    args = ap.parse_args(argv)

    root = Path(args.directory)
    resolved = resolve(
        load_scenario(root / "script.en.json"), load_capture(root / "capture.json"), DirSource(Path(args.src))
    )
    settings = json.loads(Path(args.settings).read_text()) if args.settings else None
    if args.cmd == "render":
        return _render(args, resolved, settings)
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


def _render(args: argparse.Namespace, resolved: dict[str, object], settings: dict[str, object] | None) -> int:
    from mvrender.encode import render_video
    from mvrender.fonts import FontSet
    from mvrender.package import AudioSettings, extract_cover, mux_final, render_sound

    settings = dict(settings or {})
    if args.workers:
        settings["render"] = {**settings.get("render", {}), "workers": args.workers}  # type: ignore[dict-item]
    fonts = args.fonts or str(FontSet().directory)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    silent = out / "video.en.silent.mp4"
    stats = render_video(
        resolved, silent, out / "chunks", fonts_dir=fonts, settings=settings,
        limit_frames=args.limit_frames or None,
    )  # fmt: skip
    ctx = make_context(resolved, fonts, settings)
    audio = AudioSettings.from_settings(settings)
    wav = out / "sfx.en.wav"
    render_sound(ctx, wav, audio)
    loud = mux_final(silent, wav, out / "video.en.mp4", audio)
    extract_cover(ctx, 2.4, out / "cover.en.jpg")
    sys.stdout.write(
        f"frames {stats.frames} chunks {stats.chunks} workers {stats.workers} "
        f"wall {stats.wall_s:.1f}s ({stats.seconds_per_video_second:.2f} s per video s) "
        f"loudness {loud.integrated:.1f} LUFS tp {loud.true_peak:.1f} dBTP\n"
    )
    return 0
