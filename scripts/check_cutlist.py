#!/usr/bin/env python3
"""check_cutlist.py -- parse and validate a cut list before rendering.

Also the shared parser used by render.py (time codes, transitions, framing).

Usage:
    python check_cutlist.py 镜头表.csv --project 项目.csv --probe probe.json
    python check_cutlist.py 镜头表.csv --json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:                                        # Windows consoles default to a non-UTF-8 code page
    sys.stdout.reconfigure(encoding="utf-8")   # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[attr-defined]
except Exception:                          # pragma: no cover - very old Python
    pass

# ---------------------------------------------------------------- vocabulary

COLUMNS = {
    "序号": "index", "index": "index", "#": "index",
    "素材": "source", "source": "source", "src": "source",
    "入点": "start", "in": "start", "start": "start",
    "出点": "end", "out": "end", "end": "end",
    "时长": "duration", "duration": "duration",
    "速度": "speed", "speed": "speed",
    "画面": "framing", "framing": "framing",
    "转场": "transition", "transition": "transition",
    "字幕": "caption", "caption": "caption",
    "字幕样式": "caption_style", "caption_style": "caption_style",
    "声音": "audio", "audio": "audio",
    "音效": "sfx", "sfx": "sfx", "SFX": "sfx",
    "备注": "note", "note": "note",
}

TRANSITIONS = {"硬切": "cut", "cut": "cut", "叠化": "fade", "fade": "fade",
               "闪白": "white", "white": "white", "划像": "wipe", "wipe": "wipe", "推拉": "wipe"}
FRAMING = {"原样": "plain", "plain": "plain", "推近": "zoom_in", "zoom_in": "zoom_in",
           "拉远": "zoom_out", "zoom_out": "zoom_out", "抖动": "shake", "shake": "shake",
           "局部放大": "zoom_crop", "zoom_crop": "zoom_crop"}
CAPTION_STYLE = {"预设": "preset", "preset": "preset", "强调": "strong", "strong": "strong",
                 "小字": "small", "small": "small", "无": "none", "none": "none"}
AUDIO_MODE = {"原声": "keep", "keep": "keep", "静音": "mute", "mute": "mute",
              "压低": "lower", "lower": "lower"}
SFX = {"无": "", "none": "", "": "",
       "whoosh": "whoosh", "呼呼": "whoosh", "转场音": "whoosh",
       "boom": "boom", "重击": "boom", "落点": "boom",
       "click": "click", "咔": "click",
       "pop": "pop", "弹出": "pop",
       "riser": "riser", "上升": "riser"}


class CutListError(ValueError):
    """Raised when the cut list cannot be parsed at all."""


# ---------------------------------------------------------------- primitives

_SCALES = (3600, 60, 1)


def parse_time(value: str | float | int | None) -> float:
    """Accept 750.5, 12:30.5, 01:02:03.400. Integers are seconds.

    Segments are interpreted right-to-left (seconds, minutes, hours), so
    "12:30.5" is 12m30.5s -- never 12h.  (An optional-groups regex cannot tell
    those apart: it greedily reads the first number as hours.)
    """
    if value is None:
        raise CutListError("empty time")
    if isinstance(value, (int, float)):
        return round(float(value), 3)
    text = str(value).strip()
    if not text:
        raise CutListError("empty time")
    try:
        return round(float(text), 3)
    except ValueError:
        pass
    parts = text.split(":")
    if not 1 <= len(parts) <= 3:
        raise CutListError(f"cannot parse time: {text!r} (use mm:ss.s, hh:mm:ss.mmm or seconds)")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise CutListError(f"cannot parse time: {text!r} (use mm:ss.s, hh:mm:ss.mmm or seconds)") from None
    total = 0.0
    for number, scale in zip(numbers, _SCALES[len(_SCALES) - len(numbers):]):
        total += number * scale
    return round(total, 3)


def fmt_time(seconds: float) -> str:
    minutes, rest = divmod(max(0.0, float(seconds)), 60)
    return f"{int(minutes)}:{rest:06.3f}"


def parse_transition(text: str) -> tuple[str, float]:
    """'叠化 0.3' / '闪白,0.15' / '硬切' -> (kind, seconds)."""
    raw = (text or "").strip()
    if not raw:
        return "cut", 0.0
    parts = re.split(r"[\s,，]+", raw)
    kind = TRANSITIONS.get(parts[0], None)
    if kind is None:
        return "unknown", 0.0
    duration = 0.0
    if len(parts) > 1:
        try:
            duration = float(parts[1].rstrip("s秒"))
        except ValueError:
            duration = 0.0
    if kind != "cut" and not duration:
        duration = 0.3
    return kind, round(min(max(duration, 0.1), 1.0), 3) if kind != "cut" else 0.0


def parse_framing(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "plain", ""
    head, _, arg = raw.partition(":")
    if not arg:
        head, _, arg = raw.partition("：")
    kind = FRAMING.get(head.strip(), None)
    if kind is None:
        return "unknown", ""
    return kind, arg.strip()


def parse_sfx(text: str) -> tuple[str, float]:
    """'whoosh' / '重击:0.6' / '无' -> (kind, volume). Empty kind means silent."""
    raw = (text or "").strip()
    if not raw:
        return "", 0.0
    head, _, arg = raw.partition(":")
    if not arg:
        head, _, arg = raw.partition("：")
    key = head.strip().lower()
    if key not in SFX:
        return "unknown", 0.0
    kind = SFX[key]
    if not kind:
        return "", 0.0
    volume = 0.8
    if arg.strip():
        try:
            volume = float(arg.strip())
        except ValueError:
            volume = 0.8
    return kind, round(min(max(volume, 0.0), 2.0), 2)


# ---------------------------------------------------------------- loading

def _normalise_keys(row: dict) -> dict:
    out = {}
    for key, value in row.items():
        if key is None:
            continue
        mapped = COLUMNS.get(key.strip(), COLUMNS.get(key.strip().lower()))
        if mapped:
            out[mapped] = (value if value is not None else "").strip()
    return out


def load_project(path: str | Path | None) -> dict:
    """Global settings from a two-column CSV (字段,值) or a TOML file."""
    defaults = {"title": "", "width": 1080, "height": 1920, "fps": 30, "target_duration": 0.0,
                "media_dir": "", "bgm": "", "bgm_volume": 0.6, "audio": "keep",
                "sfx_dir": "assets/sfx", "sfx_volume": 0.8,
                "intro": 0.0, "outro": 0.0, "font": "微软雅黑", "out_dir": "out"}
    if not path:
        return defaults
    p = Path(path)
    if not p.exists():
        raise CutListError(f"project file not found: {p}")
    data: dict[str, str] = {}
    if p.suffix.lower() == ".toml":
        try:
            import tomllib
        except ModuleNotFoundError as exc:                     # <3.11
            raise CutListError("TOML needs Python 3.11+; use a CSV instead") from exc
        with p.open("rb") as handle:
            data = {k: str(v) for k, v in tomllib.load(handle).items()}
    else:
        with p.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                if not row or row[0].startswith("#"):
                    continue
                if len(row) >= 2:
                    data[row[0].strip()] = row[1].strip()
    aliases = {"片名": "title", "title": "title", "画幅": "aspect", "aspect": "aspect",
               "帧率": "fps", "fps": "fps", "目标时长": "target_duration",
               "素材文件夹": "media_dir", "media_dir": "media_dir", "bgm": "bgm", "BGM 文件": "bgm",
               "bgm_volume": "bgm_volume", "BGM 音量": "bgm_volume", "原声处理": "audio", "audio": "audio",
               "音效目录": "sfx_dir", "sfx_dir": "sfx_dir", "音效音量": "sfx_volume", "sfx_volume": "sfx_volume",
               "片头": "intro", "intro": "intro", "片尾": "outro", "outro": "outro",
               "字幕字体": "font", "font": "font", "输出目录": "out_dir", "out_dir": "out_dir"}
    merged = dict(defaults)
    for key, value in data.items():
        mapped = aliases.get(key) or aliases.get(key.strip().lower())
        if not mapped or value == "":
            continue
        if mapped == "aspect":
            preset = {"竖屏": (1080, 1920), "横屏": (1920, 1080), "方形": (1080, 1080)}
            if value in preset:
                merged["width"], merged["height"] = preset[value]
            elif "x" in value.lower():
                w, _, h = value.lower().partition("x")
                merged["width"], merged["height"] = int(w), int(h)
            continue
        if mapped in {"intro", "outro"}:
            text = value.replace(" ", "")
            if text in {"无", "none", "-", ""}:
                merged[mapped] = 0.0
                continue
            if text.startswith("有"):
                _, _, tail = text.partition(",")
                text = tail or "0.8"
            try:
                merged[mapped] = float(text.rstrip("s秒"))
            except ValueError:
                raise CutListError(f"片头/片尾要写「无」或「有,0.8」，读到 {value!r}") from None
            continue
        if mapped == "target_duration" and value in {"不限", "none", "-"}:
            merged[mapped] = 0.0
            continue
        if mapped in {"fps", "target_duration"}:
            try:
                value = int(float(value)) if mapped == "fps" else float(value.rstrip("s秒"))
            except ValueError:
                raise CutListError(f"bad number for {key}: {value!r}") from None
        if mapped == "bgm_volume":
            value = float(value)
        if mapped == "sfx_volume":
            value = float(value)
        merged[mapped] = value
    return merged


def load_cutlist(path: str | Path) -> list[dict]:
    """Rows with parsed numbers; raises CutListError on structural problems."""
    p = Path(path)
    if not p.exists():
        raise CutListError(f"cut list not found: {p}")
    rows: list[dict] = []
    with p.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CutListError("cut list is empty")
        for lineno, raw in enumerate(reader, start=2):
            if not any((v or "").strip() for v in raw.values()):
                continue
            if (raw.get(reader.fieldnames[0]) or "").strip().startswith("#"):
                continue
            row = _normalise_keys(raw)
            if not row.get("source"):
                continue
            row["line"] = lineno
            row["index"] = (row.get("index") or str(len(rows) + 1)).strip()
            row["start_sec"] = parse_time(row.get("start"))
            row["end_sec"] = parse_time(row.get("end"))
            row["speed"] = float(row.get("speed") or 1.0)
            row["transition_kind"], row["transition_sec"] = parse_transition(row.get("transition", ""))
            row["framing_kind"], row["framing_arg"] = parse_framing(row.get("framing", ""))
            row["sfx_kind"], row["sfx_volume"] = parse_sfx(row.get("sfx", ""))
            row["caption_style"] = CAPTION_STYLE.get((row.get("caption_style") or "").strip(), "preset")
            row["audio_mode"] = AUDIO_MODE.get((row.get("audio") or "").strip(), "")
            rows.append(row)
    if not rows:
        raise CutListError("no shot rows found")
    return rows


def shot_visual_duration(row: dict) -> float:
    return round(max(0.0, row["end_sec"] - row["start_sec"]) / (row["speed"] or 1.0), 3)


def timeline_duration(rows: list[dict]) -> float:
    """Sum of shots minus every transition overlap."""
    total = sum(shot_visual_duration(r) for r in rows)
    for row in rows[:-1]:
        if row["transition_kind"] not in {"cut", "unknown"}:
            total -= row["transition_sec"]
    return round(total, 3)


# ---------------------------------------------------------------- validation

def validate(rows: list[dict], project: dict, probe_index: dict[str, dict] | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    media_dir = Path(project.get("media_dir") or ".")
    for row in rows:
        tag = f"#{row['index']} (第 {row['line']} 行)"
        if row["start_sec"] < 0:
            errors.append(f"{tag} 入点为负")
        if row["end_sec"] <= row["start_sec"]:
            errors.append(f"{tag} 出点({row['end_sec']}) 不晚于入点({row['start_sec']})")
        if not 0.25 <= row["speed"] <= 4.0:
            errors.append(f"{tag} 速度 {row['speed']} 超出 0.25–4.0")
        if row["transition_kind"] == "unknown":
            warnings.append(f"{tag} 转场值无法识别，将降级为硬切")
        if row["framing_kind"] == "unknown":
            warnings.append(f"{tag} 画面值无法识别，将降级为原样")
        if row.get("sfx_kind") == "unknown":
            warnings.append(f"{tag} 音效值无法识别，将不配音效")
        if shot_visual_duration(row) < 0.3:
            warnings.append(f"{tag} 单镜仅 {shot_visual_duration(row):.2f}s，可能误填")
        src = Path(row["source"])
        if not src.is_absolute():
            src = media_dir / src
        if not src.exists():
            errors.append(f"{tag} 素材不存在: {src}")
            continue
        info = (probe_index or {}).get(str(src.resolve()))
        if info and info.get("duration"):
            if row["end_sec"] > info["duration"] + 0.05:
                errors.append(f"{tag} 出点 {row['end_sec']}s 超过素材时长 {info['duration']}s")
    target = float(project.get("target_duration") or 0)
    last = rows[-1]
    if last["transition_kind"] not in {"cut", "unknown"}:
        warnings.append(f"#{last['index']} 是最后一镜，转场没有下一镜可切，已忽略")
    if target > 0:
        total = timeline_duration(rows)
        if abs(total - target) / target > 0.2:
            warnings.append(f"总长 {total:.1f}s 偏离目标 {target:.1f}s 超过 20%")
    return errors, warnings


def load_probe(path: str | Path | None) -> dict[str, dict]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise CutListError(f"probe file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(Path(rec["path"]).resolve()): rec for rec in data.get("files", []) if "error" not in rec}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a cut list before rendering.")
    ap.add_argument("cutlist", help="镜头表 CSV")
    ap.add_argument("--project", help="项目 CSV (字段,值) 或 TOML")
    ap.add_argument("--probe", help="probe.json from probe.py")
    ap.add_argument("--json", action="store_true", help="machine readable output")
    args = ap.parse_args(argv)

    try:
        project = load_project(args.project)
        rows = load_cutlist(args.cutlist)
        probe_index = load_probe(args.probe)
    except CutListError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    errors, warnings = validate(rows, project, probe_index)
    stats = {"shots": len(rows), "timeline": timeline_duration(rows),
             "raw": round(sum(shot_visual_duration(r) for r in rows), 3)}

    if args.json:
        print(json.dumps({"ok": not errors, "stats": stats, "errors": errors, "warnings": warnings},
                         ensure_ascii=False, indent=2))
    else:
        print(f"镜头 {stats['shots']} 个，实际时间线 {stats['timeline']}s（原始素材 {stats['raw']}s）")
        print(f"输出规格：{project['width']}x{project['height']} @ {project['fps']}fps")
        for row in rows:
            print(f"  #{row['index']:<3} {Path(row['source']).name:<16} {fmt_time(row['start_sec'])}"
                  f" → {fmt_time(row['end_sec'])}  x{row['speed']}  {row['framing_kind']}"
                  f"  {row['transition_kind']}  {row['caption'][:12]}")
        for item in warnings:
            print(f"warn: {item}")
        for item in errors:
            print(f"ERROR: {item}")
        print("preflight: " + ("FAILED" if errors else "ok"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
