"""timeline.py 单元测试：真实时长累加、页均分、SRT 派生、结构校验。"""

import tempfile
import unittest
from pathlib import Path

from panelcast.timeline import (
    build_srt,
    build_timeline,
    format_ts,
    load_script,
    page_entries,
)

BACKEND = {
    "backend": "sapi5:Microsoft Huihui Desktop",
    "voice": "Microsoft Huihui Desktop",
    "rate": 0,
}
_DURATIONS = [1.0, 2.5, 0.75, 3.0, 1.04]


def _script(pages_spec):
    return {"segments": [
        {"id": f"seg_{i + 1:04d}", "text": f"第{i + 1}段", "pages": pages}
        for i, pages in enumerate(pages_spec)
    ]}


def _audio(script):
    return [
        {"id": s["id"], "text": s["text"], "file": f"audio/{s['id']}.wav",
         "duration": _DURATIONS[i % len(_DURATIONS)], "cached": False}
        for i, s in enumerate(script["segments"])
    ]


class TestBuildTimeline(unittest.TestCase):
    def test_accumulate_start_end_and_total(self):
        script = _script([["page_0005", "page_0006"],
                          ["page_0007"],
                          ["page_0008"]])
        tl = build_timeline(script, _audio(script), BACKEND, Path("ffmpeg.exe"))
        self.assertEqual(len(tl["segments"]), 3)
        self.assertEqual(tl["segments"][0]["start"], 0.0)
        self.assertEqual(tl["segments"][0]["end"], 1.0)
        self.assertEqual(tl["segments"][1]["start"], 1.0)
        self.assertEqual(tl["segments"][1]["end"], 3.5)
        self.assertEqual(tl["total_duration"], 4.25)
        self.assertEqual(tl["segments"][2]["audio"], "seg_0003.wav")
        self.assertEqual(tl["tts_backend"], BACKEND["backend"])

    def test_page_even_split_last_takes_remainder(self):
        script = _script([["page_0005", "page_0006", "page_0007"],
                          ["page_0008", "page_0009"]])
        tl = build_timeline(script, _audio(script), BACKEND, Path("f"))
        entries = page_entries(tl)
        self.assertEqual([p for p, _ in entries],
                         ["page_0005", "page_0006", "page_0007",
                          "page_0008", "page_0009"])
        # 1.0 秒三页均分（0.333/0.333/余数 0.334）；2.5 秒两页均分（1.25/1.25）
        self.assertAlmostEqual(entries[0][1], 0.333, places=3)
        self.assertAlmostEqual(entries[1][1], 0.333, places=3)
        self.assertAlmostEqual(entries[2][1], 0.334, places=3)
        self.assertAlmostEqual(entries[3][1], 1.25, places=3)
        self.assertAlmostEqual(entries[4][1], 1.25, places=3)
        total = round(sum(d for _, d in entries), 3)
        self.assertAlmostEqual(total, tl["total_duration"], places=3)

    def test_srt_one_block_per_segment(self):
        script = _script([["page_0005"], ["page_0006"]])
        tl = build_timeline(script, _audio(script), BACKEND, Path("f"))
        srt = build_srt(tl)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,000\n第1段", srt)
        self.assertIn("2\n00:00:01,000 --> 00:00:03,500\n第2段", srt)
        self.assertEqual(format_ts(3661.5), "01:01:01,500")

    def test_load_script_rejects_bad_pages(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td)
            (work / "script.json").write_text(
                '{"segments": [{"id": "s1", "text": "x", '
                '"pages": ["p1", "p2", "p3", "p4"]}]}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script(work, {"p1", "p2", "p3", "p4"})
            (work / "script.json").write_text(
                '{"segments": [{"id": "s1", "text": "x", '
                '"pages": ["page_0099"]}]}', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script(work, {"page_0005"})


if __name__ == "__main__":
    unittest.main()
