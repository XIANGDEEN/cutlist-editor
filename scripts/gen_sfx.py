#!/usr/bin/env python3
"""gen_sfx.py -- synthesise small sound effects with the standard library only.

No samples, no downloads, no licences to check: every sound is computed here, so
the output is yours to use. Quality is "utility", not "record label".

Usage:
    python gen_sfx.py --out assets/sfx            # make the whole set
    python gen_sfx.py --out assets/sfx --only whoosh boom
    python gen_sfx.py --list
"""
from __future__ import annotations

import argparse
import math
import random
import struct
import sys
import wave
from pathlib import Path

SR = 48_000
KINDS = ("whoosh", "boom", "click", "pop", "riser")


def _samples(kind: str, seconds: float) -> list[float]:
    """Mono float samples in [-1, 1]."""
    total = int(SR * seconds)
    out: list[float] = []
    rnd = random.Random(hash(kind) & 0xFFFF)
    if kind == "whoosh":
        # filtered noise with a fast swell: reads as "swoosh past the camera"
        prev = 0.0
        for i in range(total):
            t = i / total
            env = math.sin(math.pi * t) ** 2                 # swell then fall
            noise = rnd.uniform(-1.0, 1.0)
            prev = prev * 0.82 + noise * 0.18                # one-pole low-pass
            out.append(prev * env * 0.9)
    elif kind == "boom":
        # pitch-dropping sine plus a transient: "impact"
        for i in range(total):
            t = i / SR
            freq = 150.0 * math.exp(-t * 6.0) + 45.0
            env = math.exp(-t * 5.0)
            body = math.sin(2 * math.pi * freq * t) * env
            click = rnd.uniform(-1, 1) * math.exp(-t * 120.0) * 0.5
            out.append((body + click) * 0.95)
    elif kind == "click":
        for i in range(total):
            t = i / SR
            out.append(rnd.uniform(-1, 1) * math.exp(-t * 260.0) * 0.8)
    elif kind == "pop":
        for i in range(total):
            t = i / SR
            freq = 900.0 * math.exp(-t * 18.0) + 180.0
            out.append(math.sin(2 * math.pi * freq * t) * math.exp(-t * 26.0) * 0.85)
    elif kind == "riser":
        prev = 0.0
        for i in range(total):
            t = i / total
            noise = rnd.uniform(-1.0, 1.0)
            prev = prev * 0.9 + noise * 0.1
            tone = math.sin(2 * math.pi * (200.0 + 1400.0 * t * t) * (i / SR))
            out.append((prev * 0.5 + tone * 0.35) * (t ** 1.5))
    else:                                                   # pragma: no cover
        raise SystemExit(f"unknown kind: {kind}")
    peak = max(1e-9, max(abs(s) for s in out))
    return [s / peak * 0.85 for s in out]                    # normalise, leave headroom


def write_wav(path: Path, samples: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
    stereo = b"".join(frames[i:i + 2] * 2 for i in range(0, len(frames), 2))
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(SR)
        handle.writeframes(stereo)


LENGTHS = {"whoosh": 0.55, "boom": 0.75, "click": 0.06, "pop": 0.12, "riser": 1.20}


def generate(kinds: list[str], out_dir: Path) -> list[Path]:
    made: list[Path] = []
    for kind in kinds:
        target = out_dir / f"{kind}.wav"
        write_wav(target, _samples(kind, LENGTHS[kind]))
        made.append(target)
    return made


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")             # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
    except Exception:                                        # pragma: no cover
        pass
    ap = argparse.ArgumentParser(description="Synthesise sound effects (stdlib only).")
    ap.add_argument("--out", default="assets/sfx", help="output folder")
    ap.add_argument("--only", nargs="*", choices=KINDS, help="subset to generate")
    ap.add_argument("--list", action="store_true", help="show available kinds")
    args = ap.parse_args(argv)
    if args.list:
        for kind in KINDS:
            print(f"{kind:<8} {LENGTHS[kind]:.2f}s")
        return 0
    kinds = args.only or list(KINDS)
    for path in generate(kinds, Path(args.out)):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
