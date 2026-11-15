"""S2 章节定界测试。"""

import json
import unittest

from panelcast.chapters import (
    DIVIDER_BLANK_INK,
    DIVIDER_DARK_INK,
    build_index,
    detect_divider_starts,
    pages_of,
    require_confirmed,
)


def rows_of(inks, start=1):
    """把墨量列表变成 measure_pages 的输出形状。"""
    return [{"page": f"page_{start + i:04d}", "index": start + i,
             "ink": ink, "white": 0.0, "width": 672, "height": 1009}
            for i, ink in enumerate(inks)]


class TestDividerDetection(unittest.TestCase):
    def test_black_then_blank_marks_next_page(self):
        inks = [0.2, 0.2, DIVIDER_DARK_INK, DIVIDER_BLANK_INK, 0.2, 0.2]
        self.assertEqual(detect_divider_starts(rows_of(inks)), [5])

    def test_multiple_pairs(self):
        inks = [0.2, DIVIDER_DARK_INK, DIVIDER_BLANK_INK, 0.3,
                DIVIDER_DARK_INK, DIVIDER_BLANK_INK, 0.4]
        self.assertEqual(detect_divider_starts(rows_of(inks)), [4, 7])

    def test_black_without_blank_is_not_a_divider(self):
        inks = [0.2, DIVIDER_DARK_INK, 0.2, 0.2]
        self.assertEqual(detect_divider_starts(rows_of(inks)), [])

    def test_blank_without_black_is_not_a_divider(self):
        inks = [0.2, DIVIDER_BLANK_INK, 0.2, 0.2]
        self.assertEqual(detect_divider_starts(rows_of(inks)), [])

    def test_pair_at_very_end_has_no_next_page(self):
        inks = [0.2, DIVIDER_DARK_INK, DIVIDER_BLANK_INK]
        self.assertEqual(detect_divider_starts(rows_of(inks)), [])

    def test_grey_page_is_not_a_divider(self):
        inks = [0.2, 0.90, DIVIDER_BLANK_INK, 0.2]
        self.assertEqual(detect_divider_starts(rows_of(inks)), [])


class TestBuildIndexFromDetection(unittest.TestCase):
    def setUp(self):
        self.rows = rows_of([0.2, 0.2, DIVIDER_DARK_INK, DIVIDER_BLANK_INK, 0.3,
                             0.3, DIVIDER_DARK_INK, DIVIDER_BLANK_INK, 0.3, 0.3])

    def test_chapters_cover_the_volume(self):
        index = build_index(self.rows)
        self.assertEqual([c["start_page"] for c in index["chapters"]], [5, 9])
        # 第 1 章在分隔页（p7 黑 + p8 波点）之前收尾，不含这两页
        self.assertEqual([c["end_page"] for c in index["chapters"]], [6, 10])

    def test_trailing_divider_pages_excluded(self):
        """章末的黑页+波点页不属于任何一章，不能算进上一章。"""
        index = build_index(self.rows)
        self.assertEqual(index["chapters"][0]["page_count"], 2)

    def test_no_divider_means_no_trim(self):
        rows = rows_of([0.2] * 6)
        index = build_index(rows, labels={
            "chapters": [{"label_zh": "第一章", "start_page": 1},
                         {"label_zh": "第二章", "start_page": 4}]})
        self.assertEqual(index["chapters"][0]["end_page"], 3)

    def test_detected_chapters_are_unconfirmed(self):
        index = build_index(self.rows)
        self.assertTrue(all(not c["confirmed"] for c in index["chapters"]))

    def test_front_matter_recorded(self):
        index = build_index(self.rows)
        self.assertEqual(index["front_matter"], {"start_page": 1, "end_page": 4})

    def test_source_is_divider_pair(self):
        self.assertEqual(build_index(self.rows)["source"], "divider-pair")

    def test_no_divider_raises_instead_of_guessing(self):
        with self.assertRaises(RuntimeError) as ctx:
            build_index(rows_of([0.2, 0.2, 0.2]))
        self.assertIn("supply --labels", str(ctx.exception))


class TestBuildIndexFromLabels(unittest.TestCase):
    def setUp(self):
        self.rows = rows_of([0.2] * 20)
        self.labels = {
            "series": "为美好的世界献上祝福！",
            "volume": "漫画 第1卷",
            "chapters": [
                {"number": "第一章", "title": "转生", "start_page": 3},
                {"number": "第二章", "title": "公会", "start_page": 11},
            ],
            "back_matter_start": 18,
        }

    def test_labels_define_boundaries(self):
        index = build_index(self.rows, labels=self.labels)
        self.assertEqual([(c["start_page"], c["end_page"])
                          for c in index["chapters"]], [(3, 10), (11, 17)])

    def test_label_zh_joined_from_number_and_title(self):
        index = build_index(self.rows, labels=self.labels)
        self.assertEqual(index["chapters"][0]["label_zh"], "第一章 转生")

    def test_labels_are_confirmed(self):
        index = build_index(self.rows, labels=self.labels)
        self.assertTrue(all(c["confirmed"] for c in index["chapters"]))

    def test_explicit_label_zh_wins(self):
        labels = json.loads(json.dumps(self.labels))
        labels["chapters"][0]["label_zh"] = "自定义标题"
        index = build_index(self.rows, labels=labels)
        self.assertEqual(index["chapters"][0]["label_zh"], "自定义标题")

    def test_back_matter_excluded(self):
        index = build_index(self.rows, labels=self.labels)
        self.assertEqual(index["back_matter"]["start_page"], 18)
        self.assertEqual(index["chapters"][-1]["end_page"], 17)

    def test_duplicate_start_rejected(self):
        labels = json.loads(json.dumps(self.labels))
        labels["chapters"][1]["start_page"] = 3
        with self.assertRaises(RuntimeError) as ctx:
            build_index(self.rows, labels=labels)
        self.assertIn("duplicate chapter start", str(ctx.exception))

    def test_missing_start_rejected(self):
        labels = {"chapters": [{"number": "第一章"}]}
        with self.assertRaises(RuntimeError) as ctx:
            build_index(self.rows, labels=labels)
        self.assertIn("start_page", str(ctx.exception))

    def test_empty_chapters_rejected(self):
        with self.assertRaises(RuntimeError):
            build_index(self.rows, labels={"chapters": []})

    def test_labels_override_detection_but_detection_still_reported(self):
        rows = rows_of([0.2, DIVIDER_DARK_INK, DIVIDER_BLANK_INK, 0.2] * 5)
        index = build_index(rows, labels=self.labels)
        self.assertEqual(index["source"], "labels")
        self.assertTrue(index["detected_starts"])


class TestRequireConfirmed(unittest.TestCase):
    def test_unconfirmed_raises(self):
        index = build_index(rows_of([0.2, DIVIDER_DARK_INK, DIVIDER_BLANK_INK,
                                     0.2, 0.2]))
        with self.assertRaises(RuntimeError) as ctx:
            require_confirmed(index)
        self.assertIn("unconfirmed", str(ctx.exception))

    def test_confirmed_passes(self):
        labels = {"chapters": [{"label_zh": "第一章", "start_page": 1}]}
        index = build_index(rows_of([0.2] * 5), labels=labels)
        self.assertIs(require_confirmed(index), index)


class TestPagesOf(unittest.TestCase):
    def setUp(self):
        self.index = build_index(rows_of([0.2] * 6), labels={
            "chapters": [{"label_zh": "第一章", "start_page": 2},
                         {"label_zh": "第二章", "start_page": 5}]})

    def test_pages_are_zero_padded(self):
        self.assertEqual(pages_of(self.index, "ch01"),
                         ["page_0002", "page_0003", "page_0004"])

    def test_last_chapter_runs_to_the_end(self):
        self.assertEqual(pages_of(self.index, "ch02"),
                         ["page_0005", "page_0006"])

    def test_unknown_chapter(self):
        with self.assertRaises(RuntimeError):
            pages_of(self.index, "ch99")


if __name__ == "__main__":
    unittest.main()
