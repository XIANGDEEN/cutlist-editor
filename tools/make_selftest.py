#!/usr/bin/env python3
"""make_selftest.py -- build a runnable demo under _selftest/.

`examples/` is a *template*: its media paths are fictional, so running it gives
"素材不存在" errors (correctly).  This script materialises a synthetic clip plus
a cut list that points at it, so every README command can be run for real.

    python tools/make_selftest.py
    python scripts/preflight.py   _selftest/镜头表.csv --project _selftest/项目.csv
    python scripts/check_cutlist.py _selftest/镜头表.csv --project _selftest/项目.csv
    python scripts/render.py      _selftest/镜头表.csv --project _selftest/项目.csv --out _selftest/out --preview
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
try:                                        # Windows consoles default to a non-UTF-8 code page
    sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
except Exception:                          # pragma: no cover
    pass
import make_fixture                        # noqa: E402  (same folder)

OUT = ROOT / "_selftest"
SECONDS = 20.0

PROJECT = """字段,值
片名,自测片
画幅,竖屏
帧率,30
素材文件夹,{media}
目标时长,不限
原声处理,保留
字幕字体,微软雅黑
音效目录,{media}\\assets\\sfx
输出目录,{media}\\out
"""

CUTLIST = """序号,素材,入点,出点,速度,画面,转场,字幕,字幕样式,声音,音效
1,fixture.mp4,0,3,1,推近,硬切,第一镜,预设,原声,呼呼
2,fixture.mp4,5,9,0.5,局部放大:中,叠化 0.3,慢放三杀,强调,原声,重击:0.7
3,fixture.mp4,12,15,1,原样,硬切,第三镜,小字,压低,
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = OUT / "fixture.mp4"
    if not fixture.exists() or fixture.stat().st_size == 0:
        rc = make_fixture.main([str(fixture), "--seconds", str(SECONDS), "--size", "960x540"])
        if rc:
            return rc
    media = str(OUT).replace("/", "\\")
    (OUT / "项目.csv").write_text(PROJECT.format(media=media), encoding="utf-8-sig")
    (OUT / "镜头表.csv").write_text(CUTLIST, encoding="utf-8-sig")
    print(f"\nready: {OUT}")
    print("  python scripts/preflight.py    _selftest/镜头表.csv --project _selftest/项目.csv")
    print("  python scripts/check_cutlist.py _selftest/镜头表.csv --project _selftest/项目.csv")
    print("  python scripts/render.py       _selftest/镜头表.csv --project _selftest/项目.csv --out _selftest/out --preview")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
