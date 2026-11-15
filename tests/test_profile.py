"""页面介绍页校验器测试。"""

import json
import unittest
from pathlib import Path

from panelcast.profile import (
    SUPPORTED_KEYWORDS,
    check_characters,
    check_palette,
    check_profile,
    check_shippable,
    check_transcript,
    validate,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "docs" / "schemas" / "page-profile.schema.json"
DOC_FILE = ROOT / "docs" / "WORKFLOW-v1-vertical-manga-narration.md"


def load_schema():
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def doc_example():
    """从规范文档附录 B 里抠出那个示例 JSON——文档与 schema 不许各说各话。"""
    text = DOC_FILE.read_text(encoding="utf-8")
    marker = "## 附录 B 介绍页完整示例"
    start = text.index(marker)
    fence = text.index("```json", start) + len("```json")
    end = text.index("```", fence)
    return json.loads(text[fence:end])


class TestSchemaSelfConsistency(unittest.TestCase):
    def test_schema_only_uses_supported_keywords(self):
        """schema 里出现校验器不认识的关键字 → 校验会静默放过，必须先失败。"""
        seen = set()

        def walk(node):
            if isinstance(node, dict):
                seen.update(node)
                for key, value in node.items():
                    if key == "properties":
                        # properties 的键是字段名，不是关键字，别混进来
                        for sub in value.values():
                            walk(sub)
                    elif key in ("items", "if", "then", "additionalProperties"):
                        walk(value)

        walk(load_schema())
        self.assertEqual(sorted(seen - SUPPORTED_KEYWORDS), [])


class TestAppendixExample(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
        self.profile = doc_example()

    def test_example_passes(self):
        self.assertEqual(validate(self.profile, self.schema), [])

    def test_example_passes_full_check(self):
        errors = check_profile(
            self.profile,
            self.schema,
            known_names=["佐藤和真", "阿克娅", "惠惠", "露娜"],
            for_shipping=True,
        )
        self.assertEqual(errors, [])

    def test_example_justifies_characters_from_the_page_itself(self):
        """不靠外部人物表也能过——登记的人物必须真在页上说话。"""
        self.assertEqual(check_characters(self.profile), [])

    def test_example_is_story_page(self):
        self.assertEqual(self.profile["layout"]["kind"], "story")
        self.assertTrue(self.profile["reuse"]["replaceable"])


class TestStructuralErrors(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
        self.profile = doc_example()

    def errors(self, mutate):
        profile = json.loads(json.dumps(self.profile))
        mutate(profile)
        return validate(profile, self.schema)

    def test_missing_required_section(self):
        errors = self.errors(lambda p: p.pop("reuse"))
        self.assertTrue(any("缺必填字段 'reuse'" in e for e in errors), errors)

    def test_extra_field_rejected(self):
        errors = self.errors(lambda p: p.__setitem__("mood", "happy"))
        self.assertTrue(any("不允许的字段 'mood'" in e for e in errors), errors)

    def test_bad_page_name(self):
        errors = self.errors(lambda p: p.__setitem__("page", "21"))
        self.assertTrue(any("不匹配" in e for e in errors), errors)

    def test_bad_enum(self):
        errors = self.errors(lambda p: p["story"].__setitem__("beat", "funny"))
        self.assertTrue(any("不在允许值" in e for e in errors), errors)

    def test_bad_sha256(self):
        errors = self.errors(lambda p: p["source"].__setitem__("sha256", "…"))
        self.assertTrue(any("不匹配" in e for e in errors), errors)

    def test_summary_too_long(self):
        errors = self.errors(lambda p: p["story"].__setitem__("summary", "字" * 41))
        self.assertTrue(any("41 > 40" in e for e in errors), errors)

    def test_too_many_scene_tags(self):
        errors = self.errors(
            lambda p: p["reuse"].__setitem__(
                "scene_tags", ["indoor.a", "indoor.b", "indoor.c", "indoor.d", "indoor.e", "indoor.f"]
            )
        )
        self.assertTrue(any("6 个 > 5" in e for e in errors), errors)

    def test_scene_tag_pattern(self):
        errors = self.errors(lambda p: p["reuse"].__setitem__("scene_tags", ["GuildHall"]))
        self.assertTrue(any("不匹配" in e for e in errors), errors)

    def test_wrong_type(self):
        errors = self.errors(lambda p: p["layout"].__setitem__("panel_count", "3"))
        self.assertTrue(any("期望 integer" in e for e in errors), errors)

    def test_bool_is_not_integer(self):
        errors = self.errors(lambda p: p["layout"].__setitem__("panel_count", True))
        self.assertTrue(any("期望 integer" in e for e in errors), errors)

    def test_nested_extra_field(self):
        errors = self.errors(lambda p: p["story"]["characters"][0].__setitem__("age", 17))
        self.assertTrue(any("characters[0]: 不允许的字段 'age'" in e for e in errors), errors)


class TestReplaceableConditional(unittest.TestCase):
    def setUp(self):
        self.schema = load_schema()
        self.profile = doc_example()

    def test_not_replaceable_needs_reason(self):
        profile = json.loads(json.dumps(self.profile))
        profile["reuse"]["replaceable"] = False
        profile["reuse"]["blocking_reason"] = None
        errors = validate(profile, self.schema)
        self.assertTrue(any("blocking_reason" in e for e in errors), errors)

    def test_not_replaceable_with_reason_ok(self):
        profile = json.loads(json.dumps(self.profile))
        profile["reuse"]["replaceable"] = False
        profile["reuse"]["blocking_reason"] = "页内有能力值卡片，换图会丢信息"
        self.assertEqual(validate(profile, self.schema), [])

    def test_replaceable_keeps_reason_null(self):
        self.assertIsNone(self.profile["reuse"]["blocking_reason"])
        self.assertEqual(validate(self.profile, self.schema), [])


class TestSemanticGates(unittest.TestCase):
    def setUp(self):
        self.profile = doc_example()

    def test_incomplete_transcript_needs_notes(self):
        self.profile["text"]["verbatim_complete"] = False
        self.profile["provenance"]["reviewer_notes"] = ""
        errors = check_transcript(self.profile)
        self.assertTrue(any("reviewer_notes" in e for e in errors), errors)

    def test_incomplete_transcript_with_notes_ok(self):
        self.profile["text"]["verbatim_complete"] = False
        self.profile["provenance"]["reviewer_notes"] = "第 2 格右下角气泡被裁切，无法读取"
        self.assertEqual(check_transcript(self.profile), [])

    def test_color_palette_on_bw_page_flagged(self):
        self.profile["visual"]["palette"] = ["#f9f9f9", "#8a6b4f", "#030303"]
        errors = check_palette(self.profile)
        self.assertTrue(any("是彩色" in e for e in errors), errors)

    def test_gray_palette_on_bw_page_ok(self):
        self.assertEqual(check_palette(self.profile), [])

    def test_color_page_allows_color_palette(self):
        self.profile["layout"]["is_color"] = True
        self.profile["visual"]["palette"] = ["#f9f9f9", "#8a6b4f", "#030303"]
        self.assertEqual(check_palette(self.profile), [])

    def test_unknown_character_flagged(self):
        self.profile["story"]["characters"].append(
            {"name": "达克妮斯", "role": "supporting", "region": "right", "expression": "微笑"}
        )
        errors = check_characters(self.profile, known_names=["佐藤和真", "阿克娅"])
        self.assertTrue(any("达克妮斯" in e for e in errors), errors)

    def test_character_known_via_bubble_speaker(self):
        self.profile["text"]["bubbles"] = [
            {"speaker": "露娜", "text": "欢迎光临", "region": "center", "is_shout": False}
        ]
        errors = check_characters(self.profile, known_names=["佐藤和真", "阿克娅"])
        self.assertEqual(errors, [])

    def test_no_known_names_skips_check(self):
        """没有人物表也没有台词时不该凭空报错（新手册/封面页就是这样）。"""
        self.assertEqual(check_characters(self.profile), [])

    def test_unreviewed_cannot_ship(self):
        self.profile["provenance"]["reviewed"] = False
        self.assertTrue(check_shippable(self.profile))

    def test_reviewed_can_ship(self):
        self.assertEqual(check_shippable(self.profile), [])

    def test_structural_error_short_circuits(self):
        self.profile.pop("visual")
        errors = check_profile(self.profile, load_schema(), for_shipping=True)
        self.assertTrue(any("缺必填字段 'visual'" in e for e in errors), errors)


class TestCli(unittest.TestCase):
    """命令行入口：退出码与一行 error 输出是给 CI 和下游脚本用的契约。"""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write(self, profile, name="p.json"):
        path = self.dir / name
        path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def run_cli(self, argv):
        import contextlib
        import io

        from panelcast.profile import _main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_ok(self):
        code, out, err = self.run_cli([self.write(doc_example())])
        self.assertEqual(code, 0)
        self.assertIn("ok page_0021", out)
        self.assertEqual(err, "")

    def test_unreviewed_blocks_shipping(self):
        profile = doc_example()
        profile["provenance"]["reviewed"] = False
        code, _, err = self.run_cli(["--ship", self.write(profile)])
        self.assertEqual(code, 3)
        self.assertIn("error:", err)
        self.assertIn("reviewed", err)
        self.assertNotIn("Traceback", err)

    def test_without_ship_flag_unreviewed_passes(self):
        profile = doc_example()
        profile["provenance"]["reviewed"] = False
        code, _, _ = self.run_cli([self.write(profile)])
        self.assertEqual(code, 0)

    def test_usage_error(self):
        code, _, err = self.run_cli([])
        self.assertEqual(code, 2)
        self.assertIn("用法", err)

    def test_unknown_flag(self):
        code, _, err = self.run_cli(["--nope", self.write(doc_example())])
        self.assertEqual(code, 2)
        self.assertIn("未知参数", err)

    def test_known_names_flag(self):
        profile = doc_example()
        profile["story"]["characters"].append(
            {"name": "达克妮斯", "role": "supporting", "region": "right", "expression": "微笑"}
        )
        path = self.write(profile)
        code, _, err = self.run_cli([path])
        self.assertEqual(code, 3)
        self.assertIn("达克妮斯", err)
        code, _, err = self.run_cli(["--known-names", "达克妮斯", path])
        self.assertEqual(code, 0, err)

    def test_missing_file(self):
        code, _, err = self.run_cli([str(self.dir / "nope.json")])
        self.assertEqual(code, 3)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
