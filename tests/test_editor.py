"""编辑器介绍页校对面板测试（S3 的人工半边）。"""

import json
import tempfile
import unittest
from pathlib import Path

from panelcast.editor.server import _Editor, _collect_enums, _profile_state

SHA = "cec1fce82d76156b4489d683db28aad80e9c36371d31539c3e559e7f1bd482ce"


def profile_doc(page="page_0007", **over):
    doc = {
        "schema": "page-profile/v1",
        "page": page,
        "source": {
            "series": "为美好的世界献上祝福！",
            "volume": "漫画 第1卷",
            "file": "1卷.mobi",
            "page_index": 7,
            "printed_page": None,
            "sha256": SHA,
            "width": 672,
            "height": 1009,
        },
        "chapter": {"id": "ch01", "label_zh": "第一章 转生"},
        "layout": {
            "kind": "story",
            "is_color": False,
            "panel_count": 4,
            "reading_direction": "rtl",
            "text_density": "medium",
            "has_splash": False,
            "borderless": False,
        },
        "story": {
            "beat": "dialogue",
            "summary": "和真在公会柜台前登记",
            "characters": [
                {"name": "和真", "role": "protagonist", "region": "center",
                 "expression": "无奈"},
            ],
            "location": "冒险者公会",
            "time_of_day": "day",
            "weather": "indoor",
            "emotion": "comedic",
            "continuity": "same_scene",
        },
        "text": {
            "bubbles": [
                {"speaker": "和真", "text": "请给我登记", "region": "center",
                 "is_shout": False},
            ],
            "narration_boxes": [],
            "sfx": [],
            "verbatim_complete": True,
            "ocr_confidence": 0.9,
        },
        "visual": {
            "shot": "medium",
            "composition": "柜台横贯画面中部",
            "key_props": ["冒险者卡片"],
            "palette": ["#f9f9f9", "#4a4a4a"],
            "motion_hint": "static",
        },
        "reuse": {
            "replaceable": True,
            "replace_strategy": "reuse_other_page",
            "scene_tags": ["indoor.guild"],
            "asset_brief": "公会柜台中景，木制台面",
            "blocking_reason": None,
        },
        "provenance": {
            "generated_by": "m1 profile",
            "generated_at": "2026-11-16T02:00:00+08:00",
            "confidence": 0.6,
            "reviewed": False,
        },
    }
    doc.update(over)
    return doc


class EditorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        (self.work / "pages").mkdir()
        (self.work / "panels").mkdir()
        (self.work / "profiles").mkdir()
        (self.work / "pages" / "page_0007.jpg").write_bytes(b"jpg")
        self.editor = _Editor(self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def write_profile(self, doc=None):
        doc = doc or profile_doc()
        (self.work / "profiles" / f"{doc['page']}.profile.json").write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        return doc


class TestCollectEnums(unittest.TestCase):
    def test_finds_layout_kind(self):
        from panelcast.profile import load_schema
        enums = _collect_enums(load_schema())
        self.assertIn("story", enums["$.layout.kind"])

    def test_finds_nested_array_item_enum(self):
        from panelcast.profile import load_schema
        enums = _collect_enums(load_schema())
        self.assertIn("left", enums["$.story.characters.items.region"])

    def test_paths_are_prefixed_with_dollar(self):
        from panelcast.profile import load_schema
        for path in _collect_enums(load_schema()):
            self.assertTrue(path.startswith("$."), path)


class TestGetProfile(EditorCase):
    def test_missing_profile_is_404(self):
        data, status = self.editor.get_profile("page_0007")
        self.assertEqual(status, 404)
        self.assertIn("no profile", data["error"])

    def test_returns_doc_enums_and_names(self):
        self.write_profile()
        data, status = self.editor.get_profile("page_0007")
        self.assertEqual(status, 200)
        self.assertEqual(data["data"]["page"], "page_0007")
        self.assertIn("$.story.beat", data["enums"])
        self.assertIn("和真", data["known_names"])

    def test_draft_is_reported_as_unshippable(self):
        self.write_profile()
        data, _ = self.editor.get_profile("page_0007")
        self.assertTrue(any("reviewed" in e for e in data["shippable_errors"]))

    def test_bad_page_name_is_404(self):
        data, status = self.editor.get_profile("../etc/passwd")
        self.assertEqual(status, 404)


class TestSaveProfile(EditorCase):
    def setUp(self):
        super().setUp()
        self.write_profile()

    def body(self, **over):
        doc = profile_doc()
        body = {k: doc[k] for k in ("story", "text", "visual", "reuse",
                                    "layout")}
        body["reviewer_notes"] = "已逐格核对"
        body.update(over)
        return body

    def test_save_marks_reviewed_and_persists(self):
        data, status = self.editor.save_profile("page_0007", self.body())
        self.assertEqual(status, 200, data)
        saved = json.loads(
            (self.work / "profiles" / "page_0007.profile.json")
            .read_text(encoding="utf-8"))
        self.assertTrue(saved["provenance"]["reviewed"])
        self.assertEqual(saved["provenance"]["generated_by"], "editor")
        self.assertEqual(saved["provenance"]["reviewer_notes"], "已逐格核对")

    def test_save_keeps_measured_source_fields(self):
        body = self.body()
        body["source"] = {"sha256": "0" * 64}
        self.editor.save_profile("page_0007", body)
        saved = json.loads(
            (self.work / "profiles" / "page_0007.profile.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(saved["source"]["sha256"], SHA)

    def test_rejects_too_long_summary(self):
        body = self.body()
        body["story"] = dict(body["story"], summary="长" * 41)
        data, status = self.editor.save_profile("page_0007", body)
        self.assertEqual(status, 400)
        self.assertTrue(any("summary" in e for e in data["errors"]))

    def test_rejects_color_palette_on_bw_page(self):
        body = self.body()
        body["visual"] = dict(body["visual"], palette=["#ff0000"])
        data, status = self.editor.save_profile("page_0007", body)
        self.assertEqual(status, 400)
        self.assertTrue(any("is_color" in e for e in data["errors"]))

    def test_rejects_incomplete_transcript_without_notes(self):
        body = self.body()
        body["text"] = dict(body["text"], verbatim_complete=False)
        body["reviewer_notes"] = "  "
        data, status = self.editor.save_profile("page_0007", body)
        self.assertEqual(status, 400)
        self.assertTrue(any("reviewer_notes" in e for e in data["errors"]))

    def test_rejects_unknown_character(self):
        body = self.body()
        body["story"] = dict(body["story"], characters=[
            {"name": "惠惠", "role": "supporting", "region": "left",
             "expression": "平静"}])
        data, status = self.editor.save_profile("page_0007", body)
        self.assertEqual(status, 400)
        self.assertTrue(any("惠惠" in e for e in data["errors"]))

    def test_placeholder_still_blocks_shipping_but_saves(self):
        body = self.body()
        body["reuse"] = dict(body["reuse"], scene_tags=["meta.unassigned"])
        data, status = self.editor.save_profile("page_0007", body)
        self.assertEqual(status, 200, data)
        self.assertTrue(data["shippable_errors"])

    def test_rejects_bad_layout_enum(self):
        body = self.body()
        body["layout"] = dict(body["layout"], kind="splash")
        data, status = self.editor.save_profile("page_0007", body)
        self.assertEqual(status, 400)

    def test_missing_profile_is_404(self):
        data, status = self.editor.save_profile("page_0001", self.body())
        self.assertEqual(status, 404)


class TestProfileState(EditorCase):
    def test_none_when_absent(self):
        self.assertEqual(_profile_state(self.editor, "page_0007"), "none")

    def test_draft_then_reviewed(self):
        self.write_profile()
        self.assertEqual(_profile_state(self.editor, "page_0007"), "draft")
        self.editor.save_profile("page_0007", {
            "story": profile_doc()["story"], "text": profile_doc()["text"],
            "visual": profile_doc()["visual"], "reuse": profile_doc()["reuse"],
            "reviewer_notes": "ok"})
        self.assertEqual(_profile_state(self.editor, "page_0007"), "reviewed")


if __name__ == "__main__":
    unittest.main()
