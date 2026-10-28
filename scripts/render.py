#!/usr/bin/env python3
"""render.py -- turn a cut list into a video.

Pure stdlib + ffmpeg. Reads the same CSV that check_cutlist.py validates,
renders one intermediate per shot, then either concatenates (all hard cuts,
fast path) or cross-fades (any transition, re-encode path).

Usage:
    python render.py 镜头表.csv --project 项目.csv --out out/ --preview
    python render.py 镜头表.csv --dry-run
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
from check_cutlist import (  # noqa: E402  (same-folder helper)
    CutListError, load_cutlist, load_project, load_probe, shot_visual_duration, validate,
)

CUT_OVERLAP = 0.05          # a "hard cut" inside the xfade path: 1.5 frames at 30fps
TRANSITION_MAP = {"fade": "fade", "white": "white", "wipe": "wipeleft", "cut": "fade", "unknown": "fade"}
DEGRADE = {"shake": "plain", "unknown": "plain"}


# ---------------------------------------------------------------- helpers

def ffmpeg_bin() -> str:
    found = shutil.which("ffmpeg")
    if not found:
        raise SystemExit("ffmpeg not found on PATH")
    return found


def run(cmd: list[str], log: Path | None, dry: bool, cwd: Path | None = None) -> None:
    printable = " ".join(f'"{c}"' if " " in c or "\u4e00" <= c[0] <= "\u9fff" else c for c in cmd)
    if dry:
        print(printable)
        return
    if log:
        log.write_text(printable + "\n", encoding="utf-8")
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        lines = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        tail = lines[-15:] or ["(no stderr)"]
        raise RuntimeError("ffmpeg failed:\n" + "\n".join(tail))


def probe_media(path: Path) -> dict:
    ffprobe = shutil.which("ffprobe") or "ffprobe"
    proc = subprocess.run([ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        return {}
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {"duration": float((data.get("format") or {}).get("duration") or 0.0),
            "width": v.get("width"), "height": v.get("height")}


# ---------------------------------------------------------------- captions

def ass_clock(seconds: float) -> str:
    hours, rest = divmod(max(0.0, seconds), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def write_ass(path: Path, text: str, duration: float, project: dict) -> None:
    width, height = project["width"], project["height"]
    font = project.get("font") or "微软雅黑"
    body = text.replace("\\n", "\\N").replace("{", "｛").replace("}", "｝")
    size = {"strong": height * 0.075, "small": height * 0.040}.get(project.get("_style", "preset"), height * 0.058)
    margin = int(height * (0.05 if project.get("_style") == "small" else 0.12))
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: {w}\nPlayResY: {h}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,"
        " Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline,"
        " Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Main,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        "{outline},1,2,60,60,{margin},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,{t0},{t1},Main,,0,0,0,,{body}\n".format(
            w=width, h=height, font=font, size=int(size), outline=max(2, int(height * 0.004)),
            margin=margin, t0=ass_clock(0.0), t1=ass_clock(max(0.2, duration)), body=body),
        encoding="utf-8")


# ---------------------------------------------------------------- filters

def video_filters(row: dict, project: dict, duration: float, has_caption: bool) -> str:
    width, height = project["width"], project["height"]
    fps = project["fps"]
    framing, arg = row["framing_kind"], row["framing_arg"]
    if framing in DEGRADE:
        framing = DEGRADE[framing]
    chain: list[str] = []
    if framing == "zoom_crop":                      # 局部放大:left|center|right
        side = arg.lower() if arg else "center"
        crop_w = f"ih*{width}/{height}"
        xexpr = {"left": "0", "right": f"iw-{crop_w}", "center": f"(iw-{crop_w})/2"}.get(side, f"(iw-{crop_w})/2")
        chain.append(f"crop={crop_w}:ih:{xexpr}:0")
        chain.append(f"scale={width}:{height}:flags=lanczos")
    else:
        chain.append(f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos")
        chain.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")
    chain.append("setsar=1")
    if framing == "zoom_in":
        chain.append(f"zoompan=z='min(1+0.0012*on\\,1.18)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}")
    elif framing == "zoom_out":
        chain.append(f"zoompan=z='max(1.18-0.0012*on\\,1.0)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}")
    chain.append(f"fps={fps}")
    if row["speed"] != 1.0:
        chain.append(f"setpts=PTS/{row['speed']}")
    if has_caption:
        chain.append("ass=cap.ass")
    return ",".join(chain)


def atempo_chain(speed: float) -> str:
    factors: list[float] = []
    remaining = speed
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(round(remaining, 6))
    return ",".join(f"atempo={f}" for f in factors)


def audio_filters(row: dict, project: dict, has_audio: bool) -> str:
    mode = row["audio_mode"] or project.get("audio") or "keep"
    chain: list[str] = []
    if row["speed"] != 1.0:
        chain.append(atempo_chain(row["speed"]))
    if mode == "lower":
        chain.append("volume=0.45")
    return ",".join(c for c in chain if c)


# ---------------------------------------------------------------- main flow

def render_shot(row: dict, project: dict, workdir: Path, probe_index: dict, preset: str, crf: int, dry: bool) -> dict:
    src = Path(row["source"])
    if not src.is_absolute():
        src = Path(project.get("media_dir") or ".") / src
    src = src.resolve()
    info = probe_index.get(str(src), {})
    start, end = row["start_sec"], row["end_sec"]
    visual = shot_visual_duration(row)
    caption = (row.get("caption") or "").strip()
    style = row["caption_style"]
    project_local = dict(project, _style=style)
    shot_dir = workdir / f"shot{int(row['index']):02d}"
    shot_dir.mkdir(parents=True, exist_ok=True)
    out = shot_dir / "clip.mp4"

    if caption and style != "none":
        write_ass(shot_dir / "cap.ass", caption, visual, project_local)

    has_audio = bool(info.get("has_audio", True)) and (row["audio_mode"] or project.get("audio")) != "mute"
    cmd = [ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{start}", "-t", f"{end - start}", "-i", str(src)]
    if not has_audio:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-vf", video_filters(row, project, visual, bool(caption and style != "none")), "-map", "0:v:0"]
    if has_audio:
        af = audio_filters(row, project, True)
        cmd += ["-map", "0:a:0"] + (["-af", af] if af else [])
    else:
        cmd += ["-map", "1:a:0"]
    cmd += ["-t", f"{max(0.1, visual):.3f}",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-r", str(project["fps"]), "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(out)]
    try:
        run(cmd, shot_dir / "ffmpeg.log", dry, cwd=shot_dir)
    except RuntimeError:
        if not has_audio:
            raise
        # probe lied (or no probe was supplied): rebuild the shot with silent audio
        silent = [ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{start}", "-t", f"{end - start}",
                  "-i", str(src), "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
                  "-vf", video_filters(row, project, visual, bool(caption and style != "none")),
                  "-map", "0:v:0", "-map", "1:a:0", "-t", f"{max(0.1, visual):.3f}",
                  "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                  "-r", str(project["fps"]), "-c:a", "aac", "-b:a", "128k",
                  "-movflags", "+faststart", str(out)]
        run(silent, shot_dir / "ffmpeg.log", dry, cwd=shot_dir)
    actual = probe_media(out).get("duration", 0.0) if (not dry and out.exists()) else visual
    return {"index": row["index"], "source": src.name, "start": start, "end": end,
            "speed": row["speed"], "planned": visual, "actual": round(actual, 3),
            "framing": row["framing_kind"], "transition": row["transition_kind"],
            "degraded": [k for k in (row["framing_kind"], row["transition_kind"]) if k in {"shake", "unknown"}],
            "caption": caption}


def concat_hard(clips: list[Path], out: Path, workdir: Path, dry: bool) -> None:
    listing = workdir / "concat.txt"
    listing.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    run([ffmpeg_bin(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c", "copy", "-movflags", "+faststart", str(out)], workdir / "concat.log", dry)


def concat_xfade_clips(shots: list[dict], rows: list[dict], clips: list[Path], out: Path,
                       workdir: Path, project: dict, preset: str, crf: int, dry: bool) -> float:
    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]
    durations = [s["planned"] for s in shots]
    graph: list[str] = []
    last_v, last_a = "[0:v]", "[0:a]"
    cursor = durations[0]
    for i in range(1, len(clips)):
        prev_row = rows[i - 1]
        kind = prev_row["transition_kind"]
        overlap = CUT_OVERLAP if kind in {"cut", "unknown"} else prev_row["transition_sec"]
        effect = TRANSITION_MAP.get(kind, "fade")
        offset = max(0.0, cursor - overlap)
        v_out, a_out = f"[v{i}]", f"[a{i}]"
        graph.append(f"{last_v}[{i}:v]xfade=transition={effect}:duration={overlap}:offset={offset:.3f}{v_out}")
        graph.append(f"{last_a}[{i}:a]acrossfade=d={overlap}{a_out}")
        last_v, last_a = v_out, a_out
        cursor = cursor + durations[i] - overlap
    run([ffmpeg_bin(), "-y", "-v", "error", *inputs, "-filter_complex", ";".join(graph),
         "-map", last_v, "-map", last_a, "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-r", str(project["fps"]), "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(out)], workdir / "xfade.log", dry)
    return round(cursor, 3)


def mix_bgm(video: Path, bgm: Path, out: Path, project: dict, workdir: Path, dry: bool) -> None:
    volume = float(project.get("bgm_volume") or 0.6)
    main_chain = "[0:a]volume=0.45[main]" if project.get("audio") == "lower" else "[0:a]anull[main]"
    graph = f"[1:a]volume={volume}[bg];{main_chain};[main][bg]amix=inputs=2:duration=first:dropout_transition=0[a]"
    run([ffmpeg_bin(), "-y", "-v", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(bgm),
         "-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out)],
        workdir / "bgm.log", dry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a cut list into a video.")
    ap.add_argument("cutlist")
    ap.add_argument("--project")
    ap.add_argument("--probe")
    ap.add_argument("--out", default="out")
    ap.add_argument("--preset", default="medium")
    ap.add_argument("--crf", type=int, default=19)
    ap.add_argument("--preview", action="store_true", help="fast/lossy preview settings")
    ap.add_argument("--no-bgm", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print ffmpeg commands only")
    args = ap.parse_args(argv)

    preset = "veryfast" if args.preview else args.preset
    crf = 28 if args.preview else args.crf
    try:
        project = load_project(args.project)
        rows = load_cutlist(args.cutlist)
        probe_index = load_probe(args.probe)
    except CutListError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    errors, warnings = validate(rows, project, probe_index)
    if errors:
        for item in errors:
            print(f"ERROR: {item}", file=sys.stderr)
        print("aborted: fix the cut list first (see check_cutlist.py)", file=sys.stderr)
        return 1
    for item in warnings:
        print(f"warn: {item}", file=sys.stderr)

    out_dir = Path(args.out).resolve()          # absolute from here on: shot renders switch cwd
    workdir = out_dir / "_work"
    workdir.mkdir(parents=True, exist_ok=True)
    title = project.get("title") or Path(rows[0]["source"]).stem
    final = out_dir / f"{title}.mp4"

    shots = [render_shot(row, project, workdir, probe_index, preset, crf, args.dry_run) for row in rows]
    clips = [workdir / f"shot{int(r['index']):02d}" / "clip.mp4" for r in rows]
    transitions = [r for r in rows[:-1] if r["transition_kind"] not in {"cut"}]

    if transitions:
        total = concat_xfade_clips(shots, rows, clips, workdir / "joined.mp4", workdir, project, preset, crf, args.dry_run)
        joined = workdir / "joined.mp4"
    else:
        concat_hard(clips, workdir / "joined.mp4", workdir, args.dry_run)
        joined = workdir / "joined.mp4"
        total = sum(s["planned"] for s in shots)

    bgm = project.get("bgm") or ""
    if bgm and not args.no_bgm:
        bgm_path = Path(bgm)
        if not bgm_path.is_absolute():
            bgm_path = Path(project.get("media_dir") or ".") / bgm_path
        bgm_path = bgm_path.resolve()
        if bgm_path.exists():
            mix_bgm(joined, bgm_path, final, project, workdir, args.dry_run)
        else:
            warnings.append(f"BGM 文件不存在: {bgm_path}，已跳过混音")
            shutil.copyfile(joined, final)
    else:
        shutil.copyfile(joined, final)

    report = {
        "title": title, "output": str(final), "size": f"{project['width']}x{project['height']}",
        "fps": project["fps"], "shots": len(rows), "planned_total": round(total, 3),
        "shots_detail": shots, "warnings": warnings,
        "degraded": [s["index"] for s in shots if s["degraded"]],
        "path": "xfade" if transitions else "concat-copy",
        "bgm": bool(bgm and not args.no_bgm),
    }
    if not args.dry_run:
        if final.exists():
            info = probe_media(final)
            report["actual_total"] = round(info.get("duration", 0.0), 3)
            report["actual_size"] = f"{info.get('width')}x{info.get('height')}"
        (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"done: {final}")
        print(f"  {report.get('actual_size')} {report['fps']}fps {report.get('actual_total')}s "
              f"({report['path']}, {report['shots']} shots)")
        if report["degraded"]:
            print(f"  degraded shots: {report['degraded']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
