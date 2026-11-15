"""timeline.py 单元测试：真实时长累加、页均分、SRT 派生、结构校验。"""

import tempfile
import unittest
from pathlib import Path

from panelcast.timeline import (
    _anchors,
    _char_time,
    build_ass,
    build_cues,
    build_srt,
    build_timeline,
    format_ts,
    load_script,
    page_entries,
    split_cues,
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


class TestSubtitleCues(unittest.TestCase):
    """字幕分句：不出现 2 字闪屏、不切碎词、时长严格覆盖原段。"""

    def test_no_tiny_flash_chunks(self):
        text = "落地的地方，是一座被城墙环抱的城镇：红瓦屋顶连绵成片，街上走着尖耳朵的精灵、兽耳的亚人。"
        cues = split_cues(text)
        self.assertTrue(cues)
        self.assertGreaterEqual(min(len(c) for c in cues), 6)
        self.assertLessEqual(max(len(c) for c in cues), 16)
        self.assertEqual("".join(cues), text)      # 不丢字、不重复

    def test_long_token_split_balanced(self):
        # 19 字无标点词块 → 均衡切 10+9，而不是 16+3
        cues = split_cues("把家里蹲少年佐藤和真一起拽进了异世界")
        self.assertEqual(len(cues), 2)
        self.assertLessEqual(abs(len(cues[0]) - len(cues[1])), 2)

    def test_cues_cover_segment_duration_exactly(self):
        timeline = {"segments": [{
            "id": "seg_0001", "text": "第一句话。第二句话，第三句话。",
            "start": 1.5, "end": 7.5, "duration": 6.0,
        }]}
        cues = build_cues(timeline)
        self.assertAlmostEqual(cues[0]["start"], 1.5)
        self.assertAlmostEqual(cues[-1]["end"], 7.5)
        for a, b in zip(cues, cues[1:]):            # 无缝衔接
            self.assertAlmostEqual(a["end"], b["start"])

    def test_ass_has_outline_and_bottom_alignment(self):
        ass = build_ass([{"start": 0, "end": 1, "text": "测试"}], 1080, 1920)
        self.assertIn("PlayResY: 1920", ass)
        self.assertIn("&H00000000", ass)            # 黑色描边色
        self.assertIn("&H00FFFFFF", ass)            # 填充纯白（不能是灰）
        self.assertIn(",1,", ass)                   # BorderStyle=1 描边
        self.assertIn("Dialogue: 0,0:00:00.00,0:00:01.00,Default", ass)
        # 竖屏：MarginL=32, MarginR=32, MarginV=100（字幕整体下沉后）
        self.assertIn(",32,32,100,1", ass)


class TestSentenceAnchoredCues(unittest.TestCase):
    """字幕跟真实句边界走：句间长停顿不能被按字数比例平摊掉。"""

    def _seg(self, sentences=None):
        return {"segments": [{
            "id": "seg_0001", "text": "甲" * 10 + "乙" * 10,
            "start": 0.0, "end": 10.0, "duration": 10.0,
            "sentences": sentences or [],
        }]}

    def test_boundary_lands_on_real_sentence_end(self):
        sentences = [
            {"offset": 0.0, "duration": 8.0, "text": "甲" * 10},
            {"offset": 8.0, "duration": 2.0, "text": "乙" * 10},
        ]
        cues = build_cues(self._seg(sentences))
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        # 真实句尾在 8.0s；按字数比例会错算成 5.0s（差 3 秒）
        self.assertAlmostEqual(cues[0]["end"], 8.0, places=2)
        self.assertAlmostEqual(cues[-1]["end"], 10.0)

    def test_without_sentences_falls_back_to_proportional(self):
        cues = build_cues(self._seg())
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0]["end"], 5.0, places=2)

    def test_cues_still_cover_segment_exactly(self):
        sentences = [
            {"offset": 0.1, "duration": 3.0, "text": "甲" * 10},
            {"offset": 3.4, "duration": 5.0, "text": "乙" * 10},
        ]
        cues = build_cues(self._seg(sentences))
        self.assertAlmostEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[-1]["end"], 10.0)
        for a, b in zip(cues, cues[1:]):
            self.assertAlmostEqual(a["end"], b["start"])
        for cue in cues:                     # 不允许负长度
            self.assertGreaterEqual(cue["end"], cue["start"])

    def test_overlapping_sentence_times_are_clamped_not_dropped(self):
        # edge-tts 偶尔给出 2ms 量级的重叠，不能让整段退回比例分配
        sentences = [
            {"offset": 0.0, "duration": 5.0, "text": "甲" * 10},
            {"offset": 4.9, "duration": 5.0, "text": "乙" * 10},
        ]
        anchors = _anchors("甲" * 10 + "乙" * 10, 0.0, sentences)
        self.assertIsNotNone(anchors)
        times = [t for _, t in anchors]
        self.assertEqual(times, sorted(times))

    def test_anchors_reject_bad_data(self):
        self.assertIsNone(_anchors("甲乙", 0.0, []))
        self.assertIsNone(_anchors("", 0.0, [{"offset": 0, "duration": 1, "text": "甲"}]))
        self.assertIsNone(_anchors("甲乙", 0.0, [{"offset": "x", "duration": 1, "text": "甲"}]))

    def test_char_time_interpolates_between_anchors(self):
        anchors = [(0, 0.0), (10, 8.0)]
        self.assertAlmostEqual(_char_time(anchors, 0), 0.0)
        self.assertAlmostEqual(_char_time(anchors, 5), 4.0)
        self.assertAlmostEqual(_char_time(anchors, 10), 8.0)
        self.assertAlmostEqual(_char_time(anchors, 99), 8.0)   # 越界取末锚点


class TestChapterLabel(unittest.TestCase):
    """右上角章节标签：浅灰小字、右上对齐、常驻全片。"""

    def _ass(self, **kw):
        return build_ass([{"start": 0, "end": 1, "text": "测试"}], 1080, 1920, **kw)

    def test_label_style_is_top_right_and_light(self):
        ass = self._ass(chapter_label="第一章 与自称是女神的家伙一起转生到异世界！",
                        total_duration=416.6)
        self.assertIn("Style: Chapter,", ass)
        line = next(l for l in ass.splitlines() if l.startswith("Style: Chapter,"))
        fields = line.split(",")
        self.assertEqual(fields[3], "&H00999999")      # 浅灰填充
        self.assertEqual(fields[18], "9")              # Alignment=9 右上
        # 字号明显小于字幕字号
        self.assertLess(int(fields[2]), 77)

    def test_label_dialogue_covers_whole_video(self):
        ass = self._ass(chapter_label="第一章 测试", total_duration=100.0)
        line = next(l for l in ass.splitlines() if l.startswith("Dialogue: 1,"))
        self.assertIn("0:00:00.00,0:01:40.00", line)
        self.assertIn("第一章 测试", line)

    def test_no_label_no_chapter_style(self):
        ass = self._ass()
        self.assertNotIn("Chapter", ass)
        self.assertNotIn("Dialogue: 1,", ass)

    def test_label_braces_escaped(self):
        ass = self._ass(chapter_label="第一章 {测试}", total_duration=1.0)
        self.assertIn("第一章 (测试)", ass)
        self.assertNotIn("{测试}", ass)


if __name__ == "__main__":
    unittest.main()
