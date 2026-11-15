"""页面停留均衡（长段拆页）测试。"""

import unittest

from panelcast.timeline import (
    MAX_DWELL,
    MIN_DWELL,
    _cap_dwell,
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


class TestBalancedWindows(unittest.TestCase):
    def test_every_page_gets_a_window(self):
        tl = timeline_of([(20.0, ["p1", "p2"], None), (20.0, ["p3", "p4"], None)])
        entries = plan_page_windows(tl)
        self.assertEqual([p for p, _ in entries], ["p1", "p2", "p3", "p4"])

    def test_total_matches_timeline(self):
        tl = timeline_of([(12.0, ["p1", "p2"], None), (9.0, ["p3"], None)])
        self.assertAlmostEqual(sum(d for _, d in plan_page_windows(tl)), 21.0, 3)

    def test_single_page_gets_whole_duration(self):
        tl = timeline_of([(7.5, ["p1"], None)])
        self.assertEqual(plan_page_windows(tl), [("p1", 7.5)])

    def test_long_single_page_segment_is_shortened(self):
        """一段 1 页 30s 的老毛病：均衡后每页 10s，不再卡 30s。"""
        tl = timeline_of([(30.0, ["p1"], None), (10.0, ["p2"], None),
                          (10.0, ["p3"], None), (10.0, ["p4"], None)])
        old = page_entries(tl)
        new = plan_page_windows(tl)
        self.assertEqual(old[0], ("p1", 30.0))     # 旧行为：一页 30 秒
        self.assertLessEqual(max(d for _, d in new), MAX_DWELL)
        self.assertAlmostEqual(new[0][1], 15.0, 1)

    def test_uniform_when_no_snap_points(self):
        tl = timeline_of([(40.0, ["p1", "p2", "p3", "p4"], None)])
        dwells = [d for _, d in plan_page_windows(tl)]
        self.assertEqual(dwells, [10.0, 10.0, 10.0, 10.0])

    def test_snaps_to_sentence_boundary(self):
        # 4 页 / 40s → 理想切点 10s；句尾在 9.2s，应吸过去
        sents = [{"offset": 0.0, "duration": 9.2, "text": "一二三"}]
        tl = timeline_of([(40.0, ["p1", "p2", "p3", "p4"], sents)])
        dwells = [d for _, d in plan_page_windows(tl)]
        self.assertAlmostEqual(dwells[0], 9.2, 2)

    def test_snap_ignored_when_too_far(self):
        sents = [{"offset": 0.0, "duration": 4.0, "text": "一二三"}]
        tl = timeline_of([(40.0, ["p1", "p2", "p3", "p4"], sents)])
        dwells = [d for _, d in plan_page_windows(tl, snap=2.0)]
        self.assertAlmostEqual(dwells[0], 10.0, 2)

    def test_min_dwell_enforced(self):
        # 句尾紧贴理想切点但会挤压下一页 → 不能低于 MIN_DWELL
        sents = [{"offset": 0.0, "duration": 9.9, "text": "一二三"}]
        tl = timeline_of([(40.0, ["p1", "p2", "p3", "p4"], sents)])
        dwells = [d for _, d in plan_page_windows(tl)]
        self.assertGreaterEqual(min(dwells), MIN_DWELL - 1e-6)

    def test_too_few_pages_is_reported_not_fatal(self):
        """页数不够是内容问题：默认不抛错，交给 S9 第 12 条报出来。"""
        tl = timeline_of([(60.0, ["p1"], None)])
        self.assertEqual(plan_page_windows(tl), [("p1", 60.0)])

    def test_strict_mode_raises_on_too_few_pages(self):
        tl = timeline_of([(60.0, ["p1"], None)])
        with self.assertRaises(RuntimeError) as ctx:
            plan_page_windows(tl, strict=True)
        self.assertIn("ceiling", str(ctx.exception))

    def test_empty_timeline_raises(self):
        with self.assertRaises(RuntimeError):
            plan_page_windows({"total_duration": 0.0, "segments": []})

    def test_page_order_preserved(self):
        pages = [f"p{i}" for i in range(1, 9)]
        tl = timeline_of([(12.0, pages[:4], None), (12.0, pages[4:], None)])
        self.assertEqual([p for p, _ in plan_page_windows(tl)], pages)

    def test_balanced_beats_segment_split_on_dwell_spread(self):
        """均衡后的停留极差必须小于段内均分。"""
        tl = timeline_of([(18.0, ["p1"], None), (4.0, ["p2"], None),
                          (4.0, ["p3"], None), (18.0, ["p4"], None)])
        old = [d for _, d in page_entries(tl)]
        new = [d for _, d in plan_page_windows(tl)]
        self.assertGreater(max(old) - min(old), max(new) - min(new))


class TestDwellCeiling(unittest.TestCase):
    """上限是 S9 第 12 条的硬指标：末页吸收余量也不许顶破。"""

    def test_tail_page_does_not_exceed_ceiling(self):
        # 3 页 50 秒：均分 16.7，但末页会吸收吸附留下的余量
        tl = timeline_of([(50.0, ["p1", "p2", "p3"], None)])
        durs = [d for _, d in plan_page_windows(tl)]
        self.assertLessEqual(max(durs), MAX_DWELL)

    def test_total_length_is_preserved_after_capping(self):
        tl = timeline_of([(50.0, ["p1", "p2", "p3"], None)])
        entries = plan_page_windows(tl)
        self.assertAlmostEqual(sum(d for _, d in entries), 50.0, places=2)

    def test_every_page_stays_above_floor(self):
        tl = timeline_of([(9.0, ["p1", "p2"], None)])
        durs = [d for _, d in plan_page_windows(tl)]
        self.assertGreaterEqual(min(durs), MIN_DWELL - 1e-9)

    def test_cap_dwell_redistributes_without_changing_total(self):
        fixed = _cap_dwell([2.0, 30.0, 8.0], total=40.0,
                           min_dwell=3.5, max_dwell=18.0)
        self.assertAlmostEqual(sum(fixed), 40.0, places=3)
        self.assertLessEqual(max(fixed), 18.0 + 1e-6)
        self.assertGreaterEqual(min(fixed), 3.5 - 1e-6)

    def test_cap_dwell_is_identity_when_already_in_range(self):
        self.assertEqual(_cap_dwell([10.0, 12.0], 22.0, 3.5, 18.0),
                         [10.0, 12.0])

    def test_impossible_ceiling_is_left_visible(self):
        """3 页 90 秒均分 30 > 上限：代码不硬压，交给 S9 报出来。"""
        tl = timeline_of([(90.0, ["p1", "p2", "p3"], None)])
        durs = [d for _, d in plan_page_windows(tl)]
        self.assertGreater(max(durs), MAX_DWELL)
        self.assertAlmostEqual(sum(durs), 90.0, places=2)


if __name__ == "__main__":
    unittest.main()
