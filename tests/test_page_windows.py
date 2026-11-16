"""页面窗口：切页点必须落在"正在讲这一页的那一段"内部。"""

import unittest

from panelcast.timeline import (
    MAX_DWELL,
    MIN_DWELL,
    page_entries,
    plan_page_windows,
)


def timeline_of(segments):
    """segments: [(duration, [pages], sentences|None)] → timeline dict"""
    out, clock = [], 0.0
    for i, (dur, pages, sentences) in enumerate(segments, 1):
        out.append({
            "id": f"seg_{i:04d}", "text": "字" * 10, "audio": f"seg_{i:04d}.wav",
            "duration": dur, "start": round(clock, 3),
            "end": round(clock + dur, 3), "pages": pages,
            "sentences": sentences or [],
        })
        clock += dur
    return {"total_duration": round(clock, 3), "segments": out}


def windows_with_times(entries):
    """[(page, start, end)]，便于断言切页时刻。"""
    out, clock = [], 0.0
    for page, dur in entries:
        out.append((page, round(clock, 3), round(clock + dur, 3)))
        clock += dur
    return out


class TestPageSync(unittest.TestCase):
    """同步是硬约束：切页时刻不得跑出本段的 [start, end]。"""

    def test_every_page_gets_a_window(self):
        tl = timeline_of([(20.0, ["p1", "p2"], None), (20.0, ["p3", "p4"], None)])
        entries = plan_page_windows(tl)
        self.assertEqual([p for p, _ in entries], ["p1", "p2", "p3", "p4"])

    def test_total_matches_timeline(self):
        tl = timeline_of([(12.0, ["p1", "p2"], None), (9.0, ["p3"], None)])
        self.assertAlmostEqual(sum(d for _, d in plan_page_windows(tl)), 21.0, 3)

    def test_single_page_gets_whole_segment(self):
        tl = timeline_of([(7.5, ["p1"], None)])
        self.assertEqual(plan_page_windows(tl), [("p1", 7.5)])

    def test_page_order_preserved(self):
        pages = [f"p{i}" for i in range(1, 9)]
        tl = timeline_of([(12.0, pages[:4], None), (12.0, pages[4:], None)])
        self.assertEqual([p for p, _ in plan_page_windows(tl)], pages)

    def test_window_never_leaves_its_segment(self):
        """核心回归：旧实现全局均分，p1 的窗口能跑到第 3 段里去。"""
        tl = timeline_of([(30.0, ["p1"], None), (10.0, ["p2"], None),
                          (10.0, ["p3"], None), (10.0, ["p4"], None)])
        got = windows_with_times(plan_page_windows(tl))
        self.assertEqual(got[0], ("p1", 0.0, 30.0))   # 一页独占自己那段
        self.assertEqual(got[1], ("p2", 30.0, 40.0))  # 不会被拉到 15s 处

    def test_uneven_segments_do_not_drift(self):
        """段字数不均时，末页也不能提前/推后到别的段区间。"""
        tl = timeline_of([(4.0, ["p1"], None), (40.0, ["p2", "p3"], None),
                          (4.0, ["p4"], None)])
        got = windows_with_times(plan_page_windows(tl))
        self.assertEqual(got[0][1:], (0.0, 4.0))
        self.assertEqual(got[1][1:], (4.0, 24.0))
        self.assertEqual(got[2][1:], (24.0, 44.0))
        self.assertEqual(got[3][1:], (44.0, 48.0))

    def test_cuts_stay_inside_segment_with_snap(self):
        # 段 10–50s、2 页：理想切点 30s；句尾 10+19.2=29.2s，吸过去
        sents = [{"offset": 0.0, "duration": 19.2, "text": "一二三"}]
        tl = timeline_of([(10.0, ["p0"], None),
                          (40.0, ["p1", "p2"], sents)])
        got = windows_with_times(plan_page_windows(tl))
        self.assertAlmostEqual(got[1][2], 29.2, 2)   # 切点 = 10 + 19.2
        self.assertAlmostEqual(got[2][2], 50.0, 2)

    def test_snap_ignored_when_too_far(self):
        sents = [{"offset": 0.0, "duration": 4.0, "text": "一二三"}]
        tl = timeline_of([(40.0, ["p1", "p2", "p3", "p4"], sents)])
        dwells = [d for _, d in plan_page_windows(tl, snap=2.0)]
        self.assertAlmostEqual(dwells[0], 10.0, 2)

    def test_sentence_offsets_outside_segment_are_ignored(self):
        """句子锚点来自别的段时不能被采用（越段就是不同步）。"""
        sents = [{"offset": -20.0, "duration": 1.0, "text": "外"}]
        tl = timeline_of([(10.0, ["p0"], None),
                          (20.0, ["p1", "p2"], sents)])
        got = windows_with_times(plan_page_windows(tl))
        self.assertEqual(got[1][1:], (10.0, 20.0))

    def test_min_dwell_enforced_inside_segment(self):
        sents = [{"offset": 0.0, "duration": 9.9, "text": "一二三"}]
        tl = timeline_of([(40.0, ["p1", "p2", "p3", "p4"], sents)])
        dwells = [d for _, d in plan_page_windows(tl)]
        self.assertGreaterEqual(min(dwells), MIN_DWELL - 1e-6)

    def test_short_segment_with_three_pages_degrades_gracefully(self):
        """段太短塞不下 3 页：放宽最小停留，但切点仍留在段内。"""
        tl = timeline_of([(6.0, ["p1", "p2", "p3"], None)])
        got = windows_with_times(plan_page_windows(tl))
        self.assertEqual(got[0][1], 0.0)
        self.assertEqual(got[-1][2], 6.0)
        for page, start, end in got:
            self.assertGreaterEqual(start, -1e-9)
            self.assertLessEqual(end, 6.0 + 1e-9)

    def test_long_single_page_is_left_visible(self):
        """一页 30 秒是内容问题：不靠挪切页点掩盖，交给 S9 第 12 条。"""
        tl = timeline_of([(30.0, ["p1"], None), (10.0, ["p2"], None)])
        old = page_entries(tl)
        new = plan_page_windows(tl)
        self.assertEqual(old, new)          # 两者都必须老实承认 30 秒
        self.assertGreater(max(d for _, d in new), MAX_DWELL)

    def test_strict_mode_raises_on_too_long_page(self):
        tl = timeline_of([(30.0, ["p1"], None)])
        with self.assertRaises(RuntimeError) as ctx:
            plan_page_windows(tl, strict=True)
        self.assertIn("ceiling", str(ctx.exception))

    def test_strict_mode_raises_on_too_short_page(self):
        tl = timeline_of([(5.0, ["p1", "p2", "p3"], None)])
        with self.assertRaises(RuntimeError) as ctx:
            plan_page_windows(tl, strict=True)
        self.assertIn("floor", str(ctx.exception))

    def test_empty_timeline_raises(self):
        with self.assertRaises(RuntimeError):
            plan_page_windows({"total_duration": 0.0, "segments": []})


class TestPageSyncCheck(unittest.TestCase):
    """S9 第 14 条：页窗口越出所属段就是不同步。"""

    def test_contained_windows_pass(self):
        from panelcast.verify import page_sync
        segs = [{"start": 0.0, "end": 10.0, "pages": ["p1"]},
                {"start": 10.0, "end": 20.0, "pages": ["p2"]}]
        ok, page, worst, total = page_sync([("p1", 10.0), ("p2", 10.0)], segs)
        self.assertTrue(ok)
        self.assertEqual((page, worst, total), (None, 0.0, 0.0))

    def test_crossing_window_is_caught(self):
        from panelcast.verify import page_sync
        segs = [{"start": 0.0, "end": 10.0, "pages": ["p1"]},
                {"start": 10.0, "end": 20.0, "pages": ["p2"]}]
        ok, page, worst, total = page_sync([("p1", 15.0), ("p2", 5.0)], segs)
        self.assertFalse(ok)
        self.assertEqual(page, "p1")
        self.assertAlmostEqual(worst, 5.0, 3)

    def test_page_shared_by_two_segments_uses_union(self):
        from panelcast.verify import page_sync
        segs = [{"start": 0.0, "end": 10.0, "pages": ["p1", "p2"]},
                {"start": 10.0, "end": 20.0, "pages": ["p2"]}]
        ok, _, _, _ = page_sync([("p1", 10.0), ("p2", 10.0)], segs)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
