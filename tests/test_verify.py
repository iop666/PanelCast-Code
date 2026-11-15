"""S9 验收测试：纯测量函数 + 一条真实小片的 13 条跑通。"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from panelcast.verify import (
    _ass_ts,
    _parse_fps,
    band_rows,
    check_layout,
    parse_ass,
    row_content_frac,
    verify_run,
)

W, H = 1080, 1920


def blank_frame(value=255):
    return bytearray([value] * (W * H))


def fill_rows(frame, y0, y1, x0, x1, value):
    for y in range(y0, y1):
        base = y * W
        for x in range(x0, x1):
            frame[base + x] = value


def synthetic_frame():
    """标签 18..48 / 漫画 72..1693 / 字幕 1747..1821 的白底帧。"""
    frame = blank_frame()
    fill_rows(frame, 18, 49, 700, 900, 153)       # 章节标签（浅灰）
    fill_rows(frame, 72, 1694, 100, 980, 200)     # 漫画（<240）
    fill_rows(frame, 1747, 1822, 300, 780, 40)    # 字幕描边（<60）
    fill_rows(frame, 1752, 1817, 320, 760, 255)   # 字幕白字
    return bytes(frame)


class TestParseFps(unittest.TestCase):
    def test_fraction(self):
        self.assertEqual(_parse_fps("30/1"), 30.0)

    def test_ntsc(self):
        self.assertAlmostEqual(_parse_fps("30000/1001"), 29.97, 2)

    def test_garbage(self):
        self.assertEqual(_parse_fps("N/A"), 0.0)
        self.assertEqual(_parse_fps(""), 0.0)
        self.assertEqual(_parse_fps("1/0"), 0.0)


class TestBandRows(unittest.TestCase):
    def test_finds_rows_with_enough_hits(self):
        frame = synthetic_frame()
        rows = band_rows(frame, W, 0, 80, lambda b: b == 153, 4)
        self.assertEqual(rows, (18, 48))

    def test_returns_none_when_absent(self):
        frame = blank_frame()
        self.assertIsNone(band_rows(frame, W, 0, 80, lambda b: b == 153, 4))

    def test_hit_threshold_matters(self):
        frame = synthetic_frame()
        self.assertIsNone(band_rows(frame, W, 0, 80, lambda b: b == 153, 500))


class TestCheckLayout(unittest.TestCase):
    def test_synthetic_frame_passes_all_subchecks(self):
        layout = check_layout(synthetic_frame(), W, H)
        self.assertEqual(layout["label"], (18, 48))
        self.assertEqual(layout["subtitle"], (1747, 1821))
        self.assertTrue(layout["ok"], layout["checks"])

    def test_blank_frame_fails(self):
        layout = check_layout(blank_frame(), W, H)
        self.assertFalse(layout["ok"])
        self.assertFalse(layout["checks"]["label_in_band"])
        self.assertFalse(layout["checks"]["subtitle_in_band"])

    def test_content_in_the_gutter_is_caught(self):
        """漫画压到字幕带（gutter 不干净）必须被抓出来。"""
        frame = bytearray(synthetic_frame())
        fill_rows(frame, 1720, 1730, 0, W, 30)   # 往 gutter 里塞墨
        layout = check_layout(bytes(frame), W, H)
        self.assertFalse(layout["checks"]["gutter_comic_subtitle"])
        self.assertFalse(layout["ok"])

    def test_subtitle_shifted_down_is_caught(self):
        frame = bytearray(blank_frame())
        fill_rows(frame, 18, 49, 700, 900, 153)
        fill_rows(frame, 72, 1694, 100, 980, 200)
        fill_rows(frame, 1850, 1900, 300, 780, 40)   # 字幕跑到底边
        layout = check_layout(bytes(frame), W, H)
        self.assertFalse(layout["checks"]["subtitle_in_band"])

    def test_row_content_frac(self):
        frame = synthetic_frame()
        self.assertGreater(row_content_frac(frame, W, 100), 0.5)
        self.assertEqual(row_content_frac(frame, W, 5), 0.0)


class TestParseAss(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "x.ass"

    def write(self, text):
        self.path.write_text(text, encoding="utf-8")
        return parse_ass(self.path)

    STYLE = ("Style: Chapter,Microsoft YaHei,40,&H00999999,&H00999999,"
             "&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,9,32,32,12,1\n")

    def test_good_chapter_style(self):
        info = self.write(
            "[V4+ Styles]\n" + self.STYLE +
            "\n[Events]\nDialogue: 1,0:00:00.00,0:06:56.60,Chapter,,0,0,0,,第一章\n"
        )
        self.assertTrue(info["has_style"])
        self.assertTrue(info["grey"])
        self.assertTrue(info["top_right"])
        self.assertAlmostEqual(info["end"], 416.6, 2)

    def test_bold_chapter_style_is_flagged(self):
        bad = self.STYLE.replace("&H00999999,&H00999999", "&H000000FF,&H000000FF")
        info = self.write("[V4+ Styles]\n" + bad)
        self.assertFalse(info["grey"])

    def test_bottom_alignment_is_flagged(self):
        bad = self.STYLE.replace(",0,0,9,", ",0,0,2,")
        info = self.write("[V4+ Styles]\n" + bad)
        self.assertFalse(info["top_right"])

    def test_missing_style(self):
        info = self.write("[Events]\nDialogue: 1,0:00:00.00,0:00:10.00,Chapter,,0,0,0,,x\n")
        self.assertFalse(info["has_style"])
        self.assertTrue(info["has_line"])

    def test_ass_timestamp(self):
        self.assertAlmostEqual(_ass_ts("0:06:56.60"), 416.6, 2)
        self.assertAlmostEqual(_ass_ts("1:00:00.00"), 3600.0, 2)


def _ffmpeg():
    try:
        from panelcast.panels import find_ffmpeg, find_ffprobe
        return find_ffmpeg(), find_ffprobe()
    except RuntimeError:
        return None, None


class TestVerifyRun(unittest.TestCase):
    """拿一条真实小片把 13 条全跑一遍，确认没有一条会崩。"""

    @classmethod
    def setUpClass(cls):
        cls.ffmpeg, cls.ffprobe = _ffmpeg()
        if not cls.ffmpeg:
            raise unittest.SkipTest("ffmpeg not available")
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.work = cls.dir / "work"
        cls.out = cls.dir / "out"
        (cls.work).mkdir()
        cls.out.mkdir()
        cls.video = cls.out / "t.mp4"
        subprocess.run(
            [str(cls.ffmpeg), "-v", "error", "-y",
             "-f", "lavfi", "-i", f"color=c=white:s={W}x{H}:d=4:r=30",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
             "-c:v", "libx264", "-crf", "30", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-t", "4", str(cls.video)],
            check=True, capture_output=True, timeout=180,
        )
        (cls.out / "t.ass").write_text(
            "[V4+ Styles]\n"
            "Style: Chapter,Microsoft YaHei,40,&H00999999,&H00999999,"
            "&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,9,32,32,12,1\n"
            "[Events]\n"
            "Dialogue: 1,0:00:00.00,0:00:04.00,Chapter,,0,0,0,,第一章\n",
            encoding="utf-8",
        )
        (cls.work / "timeline.json").write_text(json.dumps({
            "total_duration": 4.0,
            "segments": [{"id": "seg_0001", "text": "测试", "audio": "a.wav",
                          "duration": 4.0, "start": 0.0, "end": 4.0,
                          "pages": ["page_0001"], "sentences": []}],
        }), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_thirteen_checks_run(self):
        report = verify_run(self.work, self.out, "t", 4.0, ["page_0001"],
                            ffmpeg=self.ffmpeg, ffprobe=self.ffprobe)
        self.assertEqual([c["id"] for c in report["checks"]], list(range(1, 14)))
        self.assertEqual(report["schema"], "run-report/v1")

    def test_structural_checks_pass_on_a_clean_render(self):
        report = verify_run(self.work, self.out, "t", 4.0, ["page_0001"],
                            ffmpeg=self.ffmpeg, ffprobe=self.ffprobe)
        by_id = {c["id"]: c for c in report["checks"]}
        for idx in (1, 2, 3, 4, 5, 6):
            self.assertTrue(by_id[idx]["pass"], by_id[idx])

    def test_blank_frame_fails_visual_checks(self):
        """纯白帧没有字幕也没有漫画：8/9/10 必须如实报失败，不许放过。"""
        report = verify_run(self.work, self.out, "t", 4.0, ["page_0001"],
                            ffmpeg=self.ffmpeg, ffprobe=self.ffprobe)
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertFalse(by_id[9]["pass"])
        self.assertFalse(by_id[10]["pass"])
        self.assertFalse(report["ok"])
        self.assertTrue(report["warnings"])

    def test_chapter_label_check_reads_ass(self):
        report = verify_run(self.work, self.out, "t", 4.0, ["page_0001"],
                            ffmpeg=self.ffmpeg, ffprobe=self.ffprobe)
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertTrue(by_id[11]["pass"], by_id[11])

    def test_page_sequence_mismatch_is_caught(self):
        report = verify_run(self.work, self.out, "t", 4.0, ["page_0002"],
                            ffmpeg=self.ffmpeg, ffprobe=self.ffprobe)
        by_id = {c["id"]: c for c in report["checks"]}
        self.assertFalse(by_id[13]["pass"])

    def test_missing_video_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            verify_run(self.work, self.out, "nope", 4.0, ["page_0001"],
                       ffmpeg=self.ffmpeg, ffprobe=self.ffprobe)
        self.assertIn("video not found", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
