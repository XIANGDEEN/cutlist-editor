#!/usr/bin/env python3
"""preflight.py -- can this machine render this cut list, right now?

Checks the things that otherwise fail ten minutes into a render: ffmpeg present
and new enough, the exact filters we use, a CJK font for burned-in captions,
free disk space, and the cut list itself.  Every check prints a pass/fail line
and a one-line reason; exit code 1 means "fix this before rendering".

Usage:
    python preflight.py 镜头表.csv --project 项目.csv --probe probe.json
    python preflight.py 镜头表.csv --json
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:                                        # Windows consoles default to a non-UTF-8 code page
    sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
except Exception:                          # pragma: no cover
    pass
from check_cutlist import (  # noqa: E402
    CutListError, load_cutlist, load_project, load_probe, timeline_duration, validate,
)

MIN_PYTHON = (3, 10)
MIN_FREE_GB = 2.0
CJK_FONT_CANDIDATES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "SourceHanSansSC-Regular.otf")
# The 剪映 draft route (spec.json → 草稿) is coupled to one exact build: the DLL
# exports and the draft schema move with it.  The ffmpeg route does not care.
JY_VERIFIED = "11.5.0.14471"


def _out(*args) -> str:
    """Run a command and return stdout+stderr, or '' when it is missing."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return (proc.stdout or "") + (proc.stderr or "")


def check_python() -> dict:
    ok = sys.version_info[:2] >= MIN_PYTHON
    return {"name": "Python", "ok": ok, "detail": f"{sys.version.split()[0]} (需要 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]})"}


def check_binary(name: str) -> dict:
    found = shutil.which(name)
    if not found:
        return {"name": name, "ok": False, "detail": "未找到，请装 ffmpeg 并加入 PATH"}
    text = _out(found, "-version")
    version = text.splitlines()[0] if text else "?"
    return {"name": name, "ok": True, "detail": version[:90]}


def check_filter(filter_name: str, needle: str | None = None) -> dict:
    listing = _out("ffmpeg", "-hide_banner", "-filters")
    present = f" {filter_name} " in listing
    detail = "可用" if present else "该 ffmpeg 不支持，相关镜头会降级"
    if present and needle:
        help_text = _out("ffmpeg", "-hide_banner", "-h", f"filter={filter_name}")
        present = needle in help_text
        detail = f"可用（{needle} {'支持' if present else '不支持'}）"
    return {"name": f"滤镜 {filter_name}", "ok": present, "detail": detail}


def check_font() -> dict:
    fonts_dir = Path("C:/Windows/Fonts")
    for name in CJK_FONT_CANDIDATES:
        if (fonts_dir / name).exists():
            return {"name": "中文字幕字体", "ok": True, "detail": name}
    return {"name": "中文字幕字体", "ok": False, "detail": "未找到常见中文字体，烧字幕会显示方块"}


def check_disk(path: Path) -> dict:
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free_gb = shutil.disk_usage(probe).free / (1024 ** 3)
    except OSError as exc:
        return {"name": "磁盘空间", "ok": False, "detail": f"无法读取 {probe}: {exc}"}
    return {"name": "磁盘空间", "ok": free_gb >= MIN_FREE_GB,
            "detail": f"{probe} 剩余 {free_gb:.1f} GB（建议 ≥ {MIN_FREE_GB:.0f} GB）"}


def _jy_roots() -> list[Path]:
    """Install roots of 剪映, from the uninstall registry; empty list when unknown."""
    roots: list[Path] = []
    if sys.platform != "win32":
        return roots
    try:
        import winreg
    except ImportError:                     # pragma: no cover
        return roots
    hives = [(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, sub in hives:
        try:
            root = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        with root:
            for index in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                        name = str(winreg.QueryValueEx(key, "DisplayName")[0])
                        if "剪映" not in name and "JianyingPro" not in name:
                            continue
                        try:
                            location = str(winreg.QueryValueEx(key, "InstallLocation")[0]).strip('" ')
                        except OSError:
                            location = ""
                        if not location:
                            icon = str(winreg.QueryValueEx(key, "DisplayIcon")[0])
                            location = str(Path(icon.strip('"').split(",")[0]).parent)
                        if location and Path(location).exists():
                            roots.append(Path(location))
                except OSError:
                    continue
    return roots


def check_jianying() -> tuple[dict, str | None]:
    """Is the 剪映 draft route usable here? Advisory only -- ffmpeg needs none of it."""
    name = "剪映草稿路线（可选）"
    expected = Path.home() / "AppData/Local" / "JianyingPro" / "Apps" / JY_VERIFIED / "videoeditor.dll"
    if sys.platform != "win32":
        return {"name": name, "ok": True, "detail": "非 Windows，不支持"}, None
    if expected.is_file():
        return {"name": name, "ok": True, "detail": f"{JY_VERIFIED} ✓ {expected}"}, None

    roots = _jy_roots()
    if not roots:
        return {"name": name, "ok": True, "detail": "未装剪映；ffmpeg 路线不需要它"}, None
    found: list[tuple[str, Path]] = []
    for root in roots:
        for dll in sorted(root.glob("*/videoeditor.dll")):
            found.append((dll.parent.name, dll.parent))
    if not found:
        return {"name": name, "ok": True,
                "detail": f"剪映在 {roots[0]}，但没找到 videoeditor.dll；ffmpeg 路线不受影响"}, None
    versions = ", ".join(v for v, _ in found)
    match = next(((v, p) for v, p in found if v == JY_VERIFIED), None)
    if match:
        hint = (f'mklink /J "%LOCALAPPDATA%\\JianyingPro\\Apps\\{JY_VERIFIED}" "{match[1]}"')
        return ({"name": name, "ok": True, "detail": f"{JY_VERIFIED} ✓ 在 {match[1]}（需建 junction 才被草稿路线认到）"},
                f"草稿路线只认 %LOCALAPPDATA%\\JianyingPro\\Apps\\{JY_VERIFIED}\\videoeditor.dll；建链：{hint}")
    return ({"name": name, "ok": True, "detail": f"装的是 {versions}，与已验证的 {JY_VERIFIED} 不符；草稿路线不可用，ffmpeg 路线不受影响"},
            f"草稿路线钉死 {JY_VERIFIED}（编解码 ABI 随版本变）；要它请装该版本，或继续用 ffmpeg 直出")


def check_cutlist(cutlist: Path, project: dict, probe_index: dict) -> tuple[list[dict], list[str]]:
    try:
        rows = load_cutlist(cutlist)
    except CutListError as exc:
        return [{"name": "剪辑单", "ok": False, "detail": str(exc)}], []
    errors, warnings = validate(rows, project, probe_index)
    detail = f"{len(rows)} 镜头 / 时间线 {timeline_duration(rows)}s"
    if errors:
        detail += f"；{len(errors)} 个错误"
    checks = [{"name": "剪辑单", "ok": not errors, "detail": detail}]
    return checks, warnings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="渲染前环境自检")
    ap.add_argument("cutlist")
    ap.add_argument("--project")
    ap.add_argument("--probe")
    ap.add_argument("--out-dir", default="out", help="输出目录（用于检查磁盘空间）")
    ap.add_argument("--no-jianying", action="store_true", help="跳过剪映草稿路线探测")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        project = load_project(args.project)
        probe_index = load_probe(args.probe)
    except CutListError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    checks = [check_python(), check_binary("ffmpeg"), check_binary("ffprobe")]
    checks += [check_filter("xfade", "fadewhite"), check_filter("ass"), check_filter("zoompan"), check_filter("amix")]
    checks += [check_font(), check_disk(Path(args.out_dir))]
    cut_checks, warnings = check_cutlist(Path(args.cutlist), project, probe_index)
    checks += cut_checks
    if not args.no_jianying:
        jy_check, jy_warning = check_jianying()
        checks.append(jy_check)
        if jy_warning:
            warnings.append(jy_warning)

    failed = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"ok": not failed, "checks": checks, "warnings": warnings}, ensure_ascii=False, indent=2))
    else:
        width = max(len(c["name"]) for c in checks)
        for c in checks:
            print(f"{'OK  ' if c['ok'] else 'FAIL'}  {c['name']:<{width}}  {c['detail']}")
        for item in warnings:
            print(f"warn: {item}")
        print("preflight: " + ("FAILED" if failed else "ok"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
