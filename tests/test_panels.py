"""panels.py 单元测试：合成灰度字节，不依赖 ffmpeg。"""

import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from panelcast.panels import analyze_gray, candidates_dict, generate_candidates

W, H = 200, 100


def _white():
    return bytes([255] * (W * H))


def _black():
    return bytes([0] * (W * H))


def _bordered(bw=3):
    """整页单格：3px 黑边框 + 白底。"""
    buf = bytearray([255] * (W * H))
    for y in range(H):
        for x in range(W):
            if x < bw or x >= W - bw or y < bw or y >= H - bw:
                buf[y * W + x] = 0
    return bytes(buf)


def _two_panels(bw=3):
    """左右两格：外框 + 全高中缝竖线。"""
    buf = bytearray(_bordered(bw))
    for y in range(H):
        buf[y * W + W // 2] = 0
        buf[y * W + W // 2 + 1] = 0
    return bytes(buf)


def _fullbleed():
    """无长直线的确定性伪随机噪声（无框全幅）。"""
    buf = bytearray()
    seed = 12345
    for _ in range(W * H):
        seed = (seed * 1103515245 + 12345) % (2 ** 31)
        buf.append(0 if (seed >> 16) % 2 else 255)
    return bytes(buf)


class TestAnalyzeGray(unittest.TestCase):
    def test_deterministic_three_runs(self):
        gray = _two_panels()
        outs = []
        for _ in range(3):
            panels, _warnings = analyze_gray(gray, W, H)
            outs.append(json.dumps(candidates_dict("page_0001", W, H, panels, []),
                                   sort_keys=True))
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[1], outs[2])

    def test_blank_and_black_pages_return_empty(self):
        for gray in (_white(), _black()):
            panels, warnings = analyze_gray(gray, W, H)
            self.assertEqual(panels, [])
            self.assertTrue(warnings)

    def test_single_full_page_panel(self):
        panels, _warnings = analyze_gray(_bordered(), W, H)
        self.assertEqual(len(panels), 1)
        p = panels[0]
        self.assertEqual((p["x"], p["y"]), (3, 3))
        self.assertGreaterEqual(p["confidence"], 0.85)  # 四边齐全 → 高置信度

    def test_two_panels_rtl_order(self):
        panels, _warnings = analyze_gray(_two_panels(), W, H)
        self.assertEqual(len(panels), 2)
        # RTL：右边的框排第 1
        self.assertGreater(panels[0]["x"], panels[1]["x"])
        doc = candidates_dict("page_0001", W, H, panels, [])
        self.assertEqual(doc["panels"][0]["order"], 1)
        self.assertGreater(doc["panels"][0]["x"], doc["panels"][1]["x"])

    def test_fullbleed_single_low_confidence(self):
        panels, warnings = analyze_gray(_fullbleed(), W, H)
        self.assertEqual(len(panels), 1)
        self.assertEqual((panels[0]["x"], panels[0]["w"]), (0, W))
        self.assertLessEqual(panels[0]["confidence"], 0.4)  # 无边框 → 低置信度
        self.assertTrue(warnings)

    def test_performance_under_2s(self):
        bw, bh = 656, 1009
        buf = bytearray([255] * (bw * bh))
        for x in range(bw):
            for y in (0, 1, 2, bh - 3, bh - 2, bh - 1):
                buf[y * bw + x] = 0
        for y in range(bh):
            for x in (0, 1, 2, bw - 3, bw - 2, bw - 1):
                buf[y * bw + x] = 0
        big = bytes(buf)
        t0 = time.perf_counter()
        analyze_gray(big, bw, bh)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 2.0)


class TestGenerateCandidates(unittest.TestCase):
    def test_candidates_never_overwritten(self):
        with TemporaryDirectory() as td:
            work = Path(td)
            (work / "pages").mkdir()
            (work / "pages" / "page_0001.jpg").write_bytes(b"jpg-bytes")
            panels_dir = work / "panels"
            panels_dir.mkdir()
            sentinel = '{"sentinel": true}'
            target = panels_dir / "page_0001.candidates.json"
            target.write_text(sentinel, encoding="utf-8")
            results = generate_candidates(
                work, ffmpeg=Path("unused"), ffprobe=Path("unused")
            )
            self.assertEqual(results, [("page_0001", "kept (exists)")])
            self.assertEqual(target.read_text(encoding="utf-8"), sentinel)


if __name__ == "__main__":
    unittest.main()
