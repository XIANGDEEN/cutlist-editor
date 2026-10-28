#!/usr/bin/env python3
"""Self-tests for the skill's pure-stdlib half (parsing, validation, spec export).

No ffmpeg needed: rendering is covered by the manual smoke run in README
(`render --preview`).  Run with:

    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_cutlist as cc          # noqa: E402
import export_jianying_spec as ej   # noqa: E402

# Scratch space stays inside the repo: %TEMP% is not reliably writable here
# (mkdir succeeds, then opening files inside it raises PermissionError/WinError 5).
SCRATCH = ROOT / "_test" / "_unit"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8-sig")
    return path


class Scratch(unittest.TestCase):
    """Each test gets its own folder under _test/_unit (tempfile is unusable here)."""

    def setUp(self):
        self.tmp = SCRATCH / uuid.uuid4().hex[:8]
        self.tmp.mkdir(parents=True)

    def tearDown(self):
        for child in sorted(self.tmp.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                child.unlink() if child.is_file() else child.rmdir()
            except OSError:
                pass
        try:
            self.tmp.rmdir()
        except OSError:
            pass


class TimeParsing(unittest.TestCase):
    def test_seconds_plain(self):
        self.assertEqual(cc.parse_time("750.5"), 750.5)

    def test_mm_ss(self):
        self.assertEqual(cc.parse_time("12:30.5"), 750.5)

    def test_hh_mm_ss(self):
        self.assertEqual(cc.parse_time("01:02:03.400"), 3723.4)

    def test_number_passthrough(self):
        self.assertEqual(cc.parse_time(12), 12.0)

    def test_garbage_raises(self):
        with self.assertRaises(cc.CutListError):
            cc.parse_time("一分半")


class ValueParsing(unittest.TestCase):
    def test_transition_with_duration(self):
        self.assertEqual(cc.parse_transition("叠化 0.3"), ("fade", 0.3))

    def test_transition_default_duration(self):
        self.assertEqual(cc.parse_transition("闪白"), ("white", 0.3))

    def test_hard_cut_has_no_overlap(self):
        self.assertEqual(cc.parse_transition("硬切"), ("cut", 0.0))

    def test_unknown_transition(self):
        self.assertEqual(cc.parse_transition("旋涡"), ("unknown", 0.0))

    def test_framing_arg(self):
        self.assertEqual(cc.parse_framing("局部放大:left"), ("zoom_crop", "left"))

    def test_sfx_default_volume(self):
        self.assertEqual(cc.parse_sfx("whoosh"), ("whoosh", 0.8))

    def test_sfx_volume_override_and_clamp(self):
        self.assertEqual(cc.parse_sfx("重击:5"), ("boom", 2.0))

    def test_sfx_silent(self):
        self.assertEqual(cc.parse_sfx("无"), ("", 0.0))


class Loading(Scratch):
    def test_fixture_cutlist_roundtrip(self):
        media = self.tmp / "media"
        media.mkdir()
        (media / "a.mp4").write_bytes(b"\x00")
        cut = write(self.tmp / "镜头表.csv",
                    "序号,素材,入点,出点,速度,画面,转场,字幕,字幕样式,音效\n"
                    "1,a.mp4,0,4,1,推近,叠化 0.3,开头,预设,\n"
                    "2,a.mp4,4,9,0.5,原样,硬切,中间,强调,boom\n")
        project = cc.load_project(None)
        project["media_dir"] = str(media)
        rows = cc.load_cutlist(cut)
        self.assertEqual(len(rows), 2)
        self.assertEqual(cc.shot_visual_duration(rows[1]), 10.0)   # 5s / 0.5
        self.assertAlmostEqual(cc.timeline_duration(rows), 14 - 0.3, places=3)
        errors, _ = cc.validate(rows, project, {})
        self.assertEqual(errors, [])

    def test_missing_source_is_an_error(self):
        cut = write(self.tmp / "镜头表.csv", "素材,入点,出点\nghost.mp4,0,3\n")
        rows = cc.load_cutlist(cut)
        errors, _ = cc.validate(rows, {"media_dir": str(self.tmp)}, {})
        self.assertTrue(any("素材不存在" in e for e in errors))

    def test_out_point_before_in_point(self):
        (self.tmp / "a.mp4").write_bytes(b"\x00")
        cut = write(self.tmp / "镜头表.csv", "素材,入点,出点\na.mp4,5,2\n")
        rows = cc.load_cutlist(cut)
        errors, _ = cc.validate(rows, {"media_dir": str(self.tmp)}, {})
        self.assertTrue(any("不晚于入点" in e for e in errors))

    def test_last_shot_transition_is_declared_pointless(self):
        (self.tmp / "a.mp4").write_bytes(b"\x00")
        cut = write(self.tmp / "镜头表.csv", "素材,入点,出点,转场\na.mp4,0,3,叠化 0.3\n")
        rows = cc.load_cutlist(cut)
        _, warnings = cc.validate(rows, {"media_dir": str(self.tmp)}, {})
        self.assertTrue(any("最后一镜" in w for w in warnings))


class ProjectParsing(Scratch):
    def test_intro_accepts_wu(self):
        path = write(self.tmp / "项目.csv", "字段,值\n片头,无\n片尾,无\n目标时长,不限\n")
        project = cc.load_project(path)
        self.assertEqual((project["intro"], project["outro"], project["target_duration"]), (0.0, 0.0, 0.0))

    def test_intro_accepts_you_with_seconds(self):
        path = write(self.tmp / "项目.csv", "片头,有,0.8\n片尾,有\n")
        project = cc.load_project(path)
        self.assertEqual(project["intro"], 0.8)
        self.assertEqual(project["outro"], 0.8)          # 「有」不带秒数按 0.8s

    def test_bad_intro_is_explained(self):
        path = write(self.tmp / "项目.csv", "片头,随便\n")
        with self.assertRaises(cc.CutListError) as ctx:
            cc.load_project(path)
        self.assertIn("片头", str(ctx.exception))


class JianyingExport(Scratch):
    def setUp(self):
        super().setUp()
        self.media = self.tmp / "media"
        self.media.mkdir()
        (self.media / "a.mp4").write_bytes(b"\x00")
        self.cut = write(self.tmp / "镜头表.csv",
                         "序号,素材,入点,出点,速度,画面,转场,字幕,字幕样式,音效\n"
                         "1,a.mp4,0,4,1,原样,叠化 0.3,第一镜,预设,\n"
                         "2,a.mp4,4,9,0.5,推近,硬切,三杀,强调,boom\n")
        self.project = cc.load_project(None)
        self.project["media_dir"] = str(self.media)
        self.project["title"] = "测试片"

    def test_spec_shape(self):
        spec, losses, stats = ej.build(self.cut, self.project, {})
        self.assertEqual(spec["name"], "测试片")
        self.assertEqual((spec["width"], spec["height"], spec["fps"]), (1080, 1920, 30))
        self.assertEqual(len(spec["video"]), 2)
        self.assertEqual(spec["video"][0]["path"], "a.mp4")
        self.assertEqual(spec["video"][0]["start"], 0.0)
        self.assertEqual(spec["video"][1]["start"], 4.0)          # sequential, no overlap
        self.assertEqual(spec["video"][1]["source_start"], 4.0)
        self.assertEqual(spec["video"][1]["duration"], 10.0)      # 5s at 0.5x
        self.assertEqual(len(spec["text"]), 2)
        self.assertEqual(spec["text"][1]["size"], 12)             # 强调
        self.assertEqual(spec["text"][1]["start"], 4.0)
        self.assertEqual(stats["shots"], 2)

    def test_losses_are_declared_not_dropped(self):
        _, losses, _ = ej.build(self.cut, self.project, {})
        joined = "\n".join(losses)
        for expected in ("变速", "转场", "画面", "音效"):
            self.assertIn(expected, joined)

    def test_clean_cutlist_has_no_losses(self):
        clean = write(self.tmp / "clean.csv", "素材,入点,出点\na.mp4,0,3\n")
        _, losses, _ = ej.build(clean, self.project, {})
        self.assertEqual(losses, [])


if __name__ == "__main__":
    unittest.main()
