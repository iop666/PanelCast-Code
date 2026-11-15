"""S3 自动介绍页测试：只填几何字段，语义字段必须是占位且不许出片。"""

import json
import tempfile
import unittest
from pathlib import Path

from panelcast.profile import PLACEHOLDER_TAG, check_profile
from panelcast.profile_auto import (
    build_profile,
    composition_of,
    gray_palette,
    kind_of,
    source_of,
    text_density,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "docs" / "schemas" / "page-profile.schema.json").read_text("utf-8")
)


def measure(**kw):
    base = {"width": 668, "height": 1009, "ink": 0.20, "panel_count": 4,
            "max_confidence": 0.83, "borderless": False, "warnings": [],
            "is_color": False, "palette": ["#f9f9f9", "#a9a9a9", "#4a4a4a"]}
    base.update(kw)
    return base


def chapter(ch_id="ch01", label="第一章 转生"):
    return {"id": ch_id, "label_zh": label}


def profile(**kw):
    m = measure(**{k: v for k, v in kw.items() if k in measure()})
    m["is_chapter_start"] = kw.get("is_chapter_start", False)
    src = {"series": "s", "volume": "v", "file": "1卷.mobi", "page_index": 21,
           "printed_page": None, "sha256": "a" * 64, "width": m["width"],
           "height": m["height"]}
    return build_profile("page_0021", m, chapter(), src)


class TestGrayPalette(unittest.TestCase):
    def test_quantiles_returned_as_hex(self):
        gray = bytes([255] * 50 + [170] * 25 + [80] * 15 + [10] * 10)
        palette = gray_palette(gray, len(gray))
        # 累计从暗端往上数：p02/p10 落在 10，p25 落在 80，p50 落在 170
        self.assertEqual(palette, ["#0a0a0a", "#505050", "#aaaaaa"])

    def test_mostly_white_page_has_near_white_in_palette(self):
        gray = bytes([249] * 60 + [170] * 20 + [70] * 20)
        self.assertIn("#f9f9f9", gray_palette(gray, len(gray)))

    def test_all_gray_channels_equal(self):
        gray = bytes([200, 150, 100, 50] * 10)
        for color in gray_palette(gray, len(gray)):
            r, g, b = color[1:3], color[3:5], color[5:7]
            self.assertEqual(r, g)
            self.assertEqual(g, b)

    def test_single_tone_still_returns_something(self):
        self.assertTrue(gray_palette(bytes([255] * 100), 100))


class TestKindOf(unittest.TestCase):
    def test_blank(self):
        self.assertEqual(kind_of(measure(ink=0.001), False), "blank")

    def test_divider(self):
        self.assertEqual(kind_of(measure(ink=0.99), False), "divider")

    def test_story(self):
        self.assertEqual(kind_of(measure(ink=0.2), False), "story")

    def test_chapter_start_is_title_page(self):
        self.assertEqual(kind_of(measure(ink=0.2), True), "title_page")

    def test_blank_wins_over_chapter_start(self):
        self.assertEqual(kind_of(measure(ink=0.0), True), "blank")


class TestTextDensity(unittest.TestCase):
    def test_low(self):
        self.assertEqual(text_density(0.05), "low")

    def test_medium(self):
        self.assertEqual(text_density(0.20), "medium")

    def test_high(self):
        self.assertEqual(text_density(0.40), "high")


class TestComposition(unittest.TestCase):
    def test_reports_measurable_facts_only(self):
        text = composition_of(measure())
        self.assertIn("668×1009", text)
        self.assertIn("4 格", text)
        self.assertIn("墨量 20.0%", text)

    def test_borderless(self):
        self.assertIn("无框整幅", composition_of(measure(borderless=True)))


class TestBuildProfile(unittest.TestCase):
    def test_draft_validates_against_schema(self):
        self.assertEqual(check_profile(profile(), SCHEMA), [])

    def test_draft_is_not_reviewed(self):
        self.assertFalse(profile()["provenance"]["reviewed"])

    def test_draft_cannot_ship(self):
        errors = check_profile(profile(), SCHEMA, for_shipping=True)
        self.assertTrue(any(PLACEHOLDER_TAG in e for e in errors), errors)
        self.assertTrue(any("reviewed" in e for e in errors), errors)

    def test_semantic_fields_are_placeholders_not_inventions(self):
        p = profile()
        self.assertEqual(p["story"]["characters"], [])
        self.assertEqual(p["text"]["bubbles"], [])
        self.assertFalse(p["text"]["verbatim_complete"])
        self.assertIn("待视觉补全", p["story"]["summary"])

    def test_chapter_start_marks_title_page(self):
        self.assertEqual(profile(is_chapter_start=True)["layout"]["kind"],
                         "title_page")

    def test_color_page_keeps_color_palette(self):
        p = profile(is_color=True,
                    palette=["#e0c0a0", "#4a6b8a", "#ffffff"])
        self.assertEqual(check_profile(p, SCHEMA), [])
        self.assertEqual(len(p["visual"]["palette"]), 3)

    def test_bw_page_with_color_palette_would_be_rejected(self):
        p = profile(is_color=False, palette=["#e0c0a0", "#ffffff"])
        self.assertTrue(check_profile(p, SCHEMA))


class TestSourceOf(unittest.TestCase):
    def test_sha256_and_size_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            jpg = Path(tmp) / "page_0007.jpg"
            jpg.write_bytes(b"\xff\xd8\xff\xd9")
            src = source_of(7, jpg, measure(), "s", "v", "1卷.mobi")
        self.assertEqual(src["page_index"], 7)
        self.assertEqual(len(src["sha256"]), 64)
        self.assertEqual(src["file"], "1卷.mobi")
        self.assertIsNone(src["printed_page"])


if __name__ == "__main__":
    unittest.main()
