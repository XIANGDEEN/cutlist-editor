#!/usr/bin/env python3
"""make_fixture.py -- generate a synthetic clip for trying the pipeline without real footage."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate a test video (color bars + beeps).")
    ap.add_argument("output", nargs="?", default="fixture.mp4")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--size", default="960x540")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--loud-every", type=float, default=5.0, help="seconds between loud bursts")
    args = ap.parse_args(argv)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("error: ffmpeg not found on PATH", file=sys.stderr)
        return 2
    beep = f"0.6*sin(2*PI*990*t)*(0.5+0.5*sin(2*PI*(1/{args.loud_every})*t))"
    cmd = [ffmpeg, "-y", "-v", "error",
           "-f", "lavfi", "-i", f"testsrc2=size={args.size}:rate={args.fps}:duration={args.seconds}",
           "-f", "lavfi", "-i", f"aevalsrc={beep}:s=48000:d={args.seconds}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-shortest", args.output]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print((proc.stderr or "").strip()[-500:], file=sys.stderr)
        return 1
    print(f"wrote {args.output} ({args.size}, {args.seconds}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
