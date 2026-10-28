#!/usr/bin/env python3
"""export_jianying_spec.py -- cut list -> JianYing draft spec (the 11.5 fork format).

We do not write JianYing drafts ourselves: the draft container is natively
encrypted since 6.0 and only the official DLL knows how to encode it.  What we
CAN do is hand a precise machine spec to a tool that owns that DLL
(`jjjane233/jianying-editor-skill-11.5`: `jianying.py build spec.json`).

This script is therefore a *lossy bridge*, and it says so: everything the spec
format cannot express (transitions, speed, framing moves, sound effects) is
listed in the .notes.md sidecar instead of being silently dropped.

Usage:
    python export_jianying_spec.py 镜头表.csv --project 项目.csv --out spec.json
    python export_jianying_spec.py 镜头表.csv --out spec.json --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:                                        # Windows consoles default to a non-UTF-8 code page
    sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
except Exception:                          # pragma: no cover
    pass
from check_cutlist import (  # noqa: E402
    CutListError, load_cutlist, load_project, load_probe, shot_visual_duration, validate,
)

# 剪映 spec 里字幕 size 是"字号档"，不是像素；按我们的三档映射过去。
CAPTION_SIZE = {"preset": 9, "strong": 12, "small": 6}
CAPTION_Y = {"preset": -0.55, "strong": -0.55, "small": -0.72}


def rel_to_material(path: Path, material: Path) -> str:
    """Spec paths are relative to material_dir; fall back to the bare filename."""
    try:
        return path.resolve().relative_to(material.resolve()).as_posix()
    except ValueError:
        return path.name


def build(cutlist: Path, project: dict, probe_index: dict) -> tuple[dict, list[str], dict]:
    rows = load_cutlist(cutlist)
    errors, warnings = validate(rows, project, probe_index)
    if errors:
        raise CutListError("剪映导出前必须先修好剪辑单:\n  " + "\n  ".join(errors))

    material = Path(project.get("media_dir") or ".")
    video: list[dict] = []
    text: list[dict] = []
    losses: list[str] = []
    cursor = 0.0
    for row in rows:
        duration = shot_visual_duration(row)
        src = Path(row["source"])
        video.append({
            "path": rel_to_material(src, material) if src.is_absolute() else src.as_posix(),
            "source_start": round(row["start_sec"], 3),
            "start": round(cursor, 3),
            "duration": round(duration, 3),
        })
        caption = (row.get("caption") or "").strip()
        style = row["caption_style"]
        if caption and style != "none":
            text.append({
                "text": caption,
                "start": round(cursor, 3),
                "duration": round(duration, 3),
                "size": CAPTION_SIZE.get(style, 9),
                "x": 0,
                "y": CAPTION_Y.get(style, -0.55),
            })
        if row["speed"] != 1.0:
            losses.append(f"#{row['index']} 变速 x{row['speed']} → spec 无速度字段，已按时长折算，画面速度需在剪映里补")
        if row["transition_kind"] not in {"cut", "unknown"}:
            losses.append(f"#{row['index']} 转场「{row['transition_kind']} {row['transition_sec']}s」→ spec 无转场字段，需在剪映里加")
        if row["framing_kind"] not in {"plain"}:
            losses.append(f"#{row['index']} 画面「{row['framing_kind']} {row['framing_arg']}」→ spec 无运镜字段，需在剪映里加")
        kind = (row.get("sfx_kind") or "").strip()
        if kind and kind != "unknown":
            losses.append(f"#{row['index']} 音效「{kind}」→ spec 无音效轨，需在剪映里加（我们自己的 ffmpeg 管线支持）")
        if row["audio_mode"] == "lower":
            losses.append(f"#{row['index']} 原声压低 → spec 无音量曲线，用剪映「音量-6dB」或直接接受原声")
        cursor += duration

    spec = {
        "name": project.get("title") or cutlist.stem,
        "material_dir": str(material.resolve()).replace("\\", "/"),
        "width": project["width"],
        "height": project["height"],
        "fps": project["fps"],
        "video": video,
        "audio": [],
        "text": text,
    }
    bgm = (project.get("bgm") or "").strip()
    if bgm:
        losses.append(f"BGM「{bgm}」→ spec 的 audio 段格式未在对方文档中定义，未写入，请用剪映音乐轨或它的 cloud-get")

    stats = {"shots": len(video), "texts": len(text), "timeline": round(cursor, 3), "warnings": warnings}
    return spec, losses, stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="把剪辑单导出成剪映 11.5 分支可用的 spec.json")
    ap.add_argument("cutlist", help="镜头表 CSV")
    ap.add_argument("--project", help="项目 CSV (字段,值) 或 TOML")
    ap.add_argument("--probe", help="probe.json from probe.py")
    ap.add_argument("--out", default="spec.json", help="输出的 spec.json")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args(argv)

    try:
        project = load_project(args.project)
        probe_index = load_probe(args.probe)
        spec, losses, stats = build(Path(args.cutlist), project, probe_index)
    except CutListError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for item in stats["warnings"]:
        print(f"warn: {item}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(spec, ensure_ascii=False, indent=2))
        for item in losses:
            print(f"loss: {item}", file=sys.stderr)
        return 0

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")

    notes = out.with_suffix(".notes.md")
    lines = [f"# 剪映草稿规格笔记 — {spec['name']}", "",
             f"- 规格：{spec['width']}x{spec['height']} @ {spec['fps']}fps",
             f"- 镜头 {stats['shots']} 个 / 文字 {stats['texts']} 条 / 时间线 {stats['timeline']}s",
             f"- 素材目录：{spec['material_dir']}", "",
             "## 本格式表达不了的部分（需在剪映里补）", ""]
    lines += [f"- {item}" for item in losses] or ["- （无，剪辑单只用到了硬切 + 原样画面）"]
    notes.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"done: {out}")
    print(f"  {stats['shots']} 镜头 / {stats['texts']} 文字 / {stats['timeline']}s；落差 {len(losses)} 条 → {notes.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
