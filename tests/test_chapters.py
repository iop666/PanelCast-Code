"""S2 章节定界测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from panelcast.chapters import (
    DIVIDER_BLANK_INK,
    DIVIDER_DARK_INK,
    build_chapter_work,
    build_index,
    chapter_label,
    detect_divider_starts,
    find_chapter,
    pages_of,
    require_confirmed,
    slice_pages,
    write_index,
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
            # P0-08：有 slug + 卷号才会生成 chapter_uid
            "series_slug": "konosuba-manga",
            "volume_number": 1,
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


class TestFindChapter(unittest.TestCase):
    def setUp(self):
        self.index = build_index(rows_of([0.2] * 6), labels={
            "chapters": [{"number": "第一章", "title": "转生", "start_page": 2},
                         {"number": "第十章", "start_page": 5}]})

    def test_lookup_by_id(self):
        self.assertEqual(find_chapter(self.index, "ch02")["number"], "第十章")

    def test_lookup_by_number(self):
        self.assertEqual(find_chapter(self.index, "第一章")["id"], "ch01")

    def test_unknown_lists_known(self):
        with self.assertRaises(RuntimeError) as ctx:
            find_chapter(self.index, "第三章")
        self.assertIn("ch01", str(ctx.exception))
        self.assertIn("第一章", str(ctx.exception))

    def test_label_without_title_is_number_only(self):
        self.assertEqual(chapter_label(find_chapter(self.index, "ch02")), "第十章")

    def test_label_with_title_joins_both(self):
        self.assertEqual(chapter_label(find_chapter(self.index, "ch01")),
                         "第一章 转生")


class TestSlicePages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.src = root / "vol" / "pages"
        self.dst = root / "ch" / "pages"
        self.src.mkdir(parents=True)
        for i in (3, 4, 5):
            (self.src / f"page_{i:04d}.jpg").write_bytes(b"x" * 10)

    def tearDown(self):
        self.tmp.cleanup()

    def test_links_every_requested_page(self):
        stats = slice_pages(self.src, self.dst,
                            ["page_0003", "page_0004", "page_0005"])
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["linked"] + stats["copied"], 3)
        self.assertEqual(sorted(p.name for p in self.dst.glob("*.jpg")),
                         ["page_0003.jpg", "page_0004.jpg", "page_0005.jpg"])

    def test_only_requested_pages_are_sliced(self):
        slice_pages(self.src, self.dst, ["page_0004"])
        self.assertEqual([p.name for p in self.dst.glob("*.jpg")],
                         ["page_0004.jpg"])

    def test_rerun_reuses_existing_files(self):
        slice_pages(self.src, self.dst, ["page_0003"])
        stats = slice_pages(self.src, self.dst, ["page_0003"])
        self.assertEqual(stats["reused"], 1)
        self.assertEqual(stats["linked"] + stats["copied"], 0)

    def test_missing_source_page_raises(self):
        with self.assertRaises(RuntimeError) as ctx:
            slice_pages(self.src, self.dst, ["page_0009"])
        self.assertIn("page_0009", str(ctx.exception))


class TestBuildChapterWork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.work = root / "vol"
        (self.work / "pages").mkdir(parents=True)
        for i in range(1, 8):
            (self.work / "pages" / f"page_{i:04d}.jpg").write_bytes(b"x")
        self.index = build_index(rows_of([0.2] * 7), labels={
            "series": "为美好的世界献上祝福！",
            "volume": "漫画 第1卷",
            "series_slug": "konosuba-manga",
            "volume_number": 1,
            "chapters": [{"number": "第二章", "title": "公会", "start_page": 2},
                         {"number": "第三章", "start_page": 5}]})
        write_index(self.work, self.index)
        self.out = root / "ch02"

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_pages_and_chapter_json(self):
        doc, stats, path = build_chapter_work(self.work, self.index, "ch01",
                                              self.out)
        self.assertEqual(doc["label"], "第二章 公会")
        self.assertEqual(stats["total"], 3)
        self.assertTrue(path.exists())
        self.assertEqual(len(list((self.out / "pages").glob("*.jpg"))), 3)

    def test_chapter_json_roundtrips(self):
        build_chapter_work(self.work, self.index, "ch01", self.out)
        doc = json.loads((self.out / "chapter.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["pages"],
                         ["page_0002", "page_0003", "page_0004"])
        self.assertEqual(doc["start_page"], 2)

    def test_does_not_copy_the_volume_script(self):
        build_chapter_work(self.work, self.index, "ch01", self.out)
        self.assertFalse((self.out / "script.json").exists())


if __name__ == "__main__":
    unittest.main()
