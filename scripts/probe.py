#!/usr/bin/env python3
"""probe.py -- list media files with the facts a cut list needs.

Pure stdlib. Requires ffprobe on PATH (or set --ffprobe).

Usage:
    python probe.py D:\\game\\session1 --out probe.json
    python probe.py a.mp4 b.mp4 --format table
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:                                        # Windows consoles default to a non-UTF-8 code page
    sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
except Exception:                          # pragma: no cover
    pass

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".flv", ".wmv", ".webm", ".ts", ".mts", ".mpg", ".mpeg"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def _ffprobe(explicit: str | None) -> str:
    if explicit:
        return explicit
    found = shutil.which("ffprobe")
    if not found:
        raise SystemExit("ffprobe not found on PATH; install ffmpeg or pass --ffprobe")
    return found


def _rate(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    num, _, den = value.partition("/")
    try:
        n = float(num)
        d = float(den) if den else 1.0
    except ValueError:
        return None
    return round(n / d, 3) if d else None


def probe_one(path: Path, ffprobe: str) -> dict:
    """Return one media record; never raises, carries an ``error`` field instead."""
    record: dict = {"name": path.stem, "path": str(path.resolve()), "bytes": path.stat().st_size}
    try:
        proc = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError as exc:                       # ffprobe missing/unexecutable
        record["error"] = f"cannot run ffprobe: {exc}"
        return record
    if proc.returncode != 0:
        record["error"] = (proc.stderr or "ffprobe failed").strip()[-300:]
        return record
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        record["error"] = f"unreadable ffprobe output: {exc}"
        return record

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    try:
        record["duration"] = round(float(fmt.get("duration") or 0.0), 3)
    except (TypeError, ValueError):
        record["duration"] = 0.0
    if video:
        record.update(
            width=video.get("width"), height=video.get("height"),
            fps=_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            vcodec=video.get("codec_name"),
        )
    record["has_audio"] = audio is not None
    record["acodec"] = (audio or {}).get("codec_name")
    return record


def collect(paths: list[str], extensions: set[str] | None = None) -> list[Path]:
    """Expand files/directories into a de-duplicated, sorted media list."""
    exts = {e.lower() for e in (extensions or (VIDEO_EXT | AUDIO_EXT))}
    found: dict[str, Path] = {}
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and child.suffix.lower() in exts:
                    found[str(child.resolve())] = child
        elif p.is_file():
            found[str(p.resolve())] = p
        else:
            print(f"warn: not found: {p}", file=sys.stderr)
    return [found[k] for k in sorted(found)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inspect media files and write a JSON manifest.")
    ap.add_argument("paths", nargs="+", help="files or directories")
    ap.add_argument("--out", help="write JSON here (default: stdout)")
    ap.add_argument("--ext", help="comma separated extensions, e.g. .mp4,.mov")
    ap.add_argument("--ffprobe", help="path to ffprobe")
    ap.add_argument("--format", choices=["json", "table"], default="json")
    args = ap.parse_args(argv)

    exts = {e if e.startswith(".") else f".{e}" for e in args.ext.split(",")} if args.ext else None
    targets = collect(args.paths, exts)
    if not targets:
        print("error: no media files found", file=sys.stderr)
        return 2

    ffprobe = _ffprobe(args.ffprobe)
    records = [probe_one(p, ffprobe) for p in targets]
    payload = {"version": 1, "count": len(records), "files": records}

    if args.format == "table":
        print(f"{'name':<24}{'duration':>10}{'size':>12}{'fps':>7}{'audio':>7}")
        for r in records:
            if r.get("error"):
                print(f"{Path(r['path']).name:<24}{'ERROR':>40}  {r['error'][:40]}")
                continue
            print(f"{r['name'][:23]:<24}{r['duration']:>10.2f}{(r.get('width') or 0)}x{(r.get('height') or 0):<7}"
                  f"{r.get('fps') or 0:>7}{'yes' if r['has_audio'] else 'no':>7}")
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.out} ({len(records)} file(s))")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all("error" not in r for r in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
