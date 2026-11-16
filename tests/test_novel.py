"""S5a 底稿对齐门禁测试（P0-05）。

覆盖规范 §9.1 的五步链，重点锁住三件容易做错的事：

1. `--align` 只产骨架，**不把候选标成已确认**（候选进了 `para_candidates`，
   `para` 必须是 `null`、`fidelity` 必须是 `unconfirmed`）。
2. `text_sha256` 比的是 `novel_index.json` 的 `file_sha256`，**不是** `sha256`。
3. 讲稿改一段之后，旧审核报告必须失效，并指出**是哪一段**。

用内存里现造的迷你素材测，不依赖仓库外的 epub / 漫画。
"""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panelcast.novel import (  # noqa: E402
    GateError,
    build_novel_ref,
    check,
    candidate_ranges,
    format_problems,
    load_novel,
    novel_chapter_range,
    render,
    write_novel_ref,
)


# ---------------------------------------------------------------- 素材构造

NOVEL_PARAS = [
    "第一章 和这个自称女神转生到异世界！",          # 0
    "和真在马路中间被拖拉机吓死，睁眼看到一个蓝衣女神。",  # 1
    "阿库娅自称引导死者的女神，要求他选一样东西带去异世界。",  # 2
    "和真选了女神本人，两人一起落到一个陌生的城镇。",    # 3
    "第二章 替华美的高阶职业带来愉悦！",            # 4
    "冒险者公会的后院有一口大浴池，热水是从地底引上来的。",  # 5
    "刚打完青蛙的两个人泡在里面，谁都没说话。",        # 6
    "惠惠在公会门口拦下和真，要求陪她练爆裂魔法。",      # 7
    "达克妮丝在公会上提出入队，被和真当成怪人。",       # 8
]


def write_novel(dirpath, paras=None):
    """落一份 novel.txt + novel_index.json，哈希口径与 tools/novel_extract.py 一致。"""
    paras = NOVEL_PARAS if paras is None else paras
    d = Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    text = "\n".join(paras)
    body = render(text)
    (d / "novel.txt").write_text(body, encoding="utf-8", newline="\n")
    index = {
        "schema": "novel-index/v1",
        "source_file": "1.epub",
        "chapters": [
            {"file": "chapter01.xhtml", "title": paras[0],
             "para_from": 0, "para_to": 3, "paras": 4,
             "chars": sum(len(p) for p in paras[0:4])},
            {"file": "chapter02.xhtml", "title": paras[4],
             "para_from": 4, "para_to": 8, "paras": 5,
             "chars": sum(len(p) for p in paras[4:9])},
        ],
        "total_paras": len(paras),
        "total_chars": sum(len(p) for p in paras),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "file_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    (d / "novel_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return index


def write_chapter_work(dirpath, pages=("page_0045", "page_0046", "page_0047"),
                       segments=None, schema=None):
    d = Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    chapter = {
        "schema": "chapter-work/v1", "series": "为美好的世界献上祝福！",
        "volume": "漫画 第1卷", "id": "ch02", "number": "第二章",
        "title": "替华美的高阶职业带来愉悦！",
        "label": "第二章 替华美的高阶职业带来愉悦！",
        "start_page": 45, "end_page": 47, "page_count": len(pages),
        "pages": list(pages), "source_work": "m1/v1/work",
    }
    (d / "chapter.json").write_text(json.dumps(chapter, ensure_ascii=False,
                                              indent=2) + "\n", encoding="utf-8")
    segs = segments if segments is not None else [
        {"id": "seg_0001", "pages": ["page_0045", "page_0046"],
         "text": "冒险者公会的后院有一口大浴池，热水是从地底引上来的。"},
        {"id": "seg_0002", "pages": ["page_0047"],
         "text": "惠惠在公会门口拦下和真，要求陪她练爆裂魔法。"},
    ]
    script = {"segments": segs}
    if schema:
        script["schema"] = schema
    (d / "script.json").write_text(json.dumps(script, ensure_ascii=False,
                                              indent=2) + "\n", encoding="utf-8")
    return d


def write_audit(work, ref_path, schema="script/v1", review_status="approved",
                reviewed_by="human:reviewer", script_schema=None, seg_texts=None):
    """落一份审核报告。默认是"全部通过"的基准，测试里再逐项破坏。"""
    work = Path(work)
    script_bytes = (work / "script.json").read_bytes()
    script = json.loads(script_bytes.decode("utf-8"))
    segs = script["segments"]
    audited = []
    for s in segs:
        text = s.get("text") or (s.get("narration") or {}).get("text") or ""
        if seg_texts and s["id"] in seg_texts:
            text = seg_texts[s["id"]]
        audited.append({
            "segment_id": s["id"],
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "status": "approved",
        })
    audit = {
        "schema": "script-audit/v1",
        "audit_spec_version": "v1.0",
        "chapter_uid": "konosuba-manga-v01-ch02",
        "script_schema": script_schema or schema,
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "novel_ref_sha256": hashlib.sha256(Path(ref_path).read_bytes()).hexdigest(),
        "audited_segments": audited,
        "review_status": review_status,
        "reviewed_by": reviewed_by,
        "reviewed_at": "2026-11-16T00:00:00+08:00",
    }
    (work / "script-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return audit


def make_v2_script(work, beats_per_seg=1):
    """把 v1 讲稿改造成"结构合法"的 v2：每段挂一个存在的 beat。"""
    work = Path(work)
    doc = json.loads((work / "script.json").read_text(encoding="utf-8"))
    doc["schema"] = "script/v2"
    doc["chapter_uid"] = "konosuba-manga-v01-ch02"
    for i, seg in enumerate(doc["segments"], 1):
        seg["visual_refs"] = [{"type": "page", "id": p, "role": "depicts"}
                              for p in seg.get("pages") or []]
        seg["narration"] = {
            "text": seg.pop("text"),
            "source_refs": [{"type": "novel_beat", "beat": f"b{i:02d}"}],
        }
    (work / "script.json").write_text(json.dumps(doc, ensure_ascii=False,
                                                 indent=2) + "\n", encoding="utf-8")
    return doc


# ---------------------------------------------------------------- 用例

class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.novel_dir = self.root / "novel"
        self.index = write_novel(self.novel_dir)
        self.work = write_chapter_work(self.root / "work")

    def tearDown(self):
        self.tmp.cleanup()

    def _align(self, **kw):
        kw.setdefault("chapter_uid", "konosuba-manga-v01-ch02")
        kw.setdefault("novel_chapter", "ch02")
        doc = build_novel_ref(self.work, self.novel_dir, **kw)
        write_novel_ref(self.work, doc)
        return doc

    def _steps(self, problems):
        return sorted({s for s, _ in problems})


class TestHashing(Base):
    def test_render_adds_exactly_one_trailing_newline(self):
        self.assertEqual(render("a\nb"), "a\nb\n")

    def test_file_sha256_differs_from_content_sha256(self):
        """索引里两个哈希不相等——这是 novel_ref 只用 file_sha256 的原因。"""
        self.assertNotEqual(self.index["sha256"], self.index["file_sha256"])

    def test_align_records_file_sha256_not_content_sha256(self):
        doc = self._align()
        self.assertEqual(doc["source"]["text_sha256"], self.index["file_sha256"])
        self.assertNotEqual(doc["source"]["text_sha256"], self.index["sha256"])

    def test_load_novel_drops_the_render_newline(self):
        lines, index = load_novel(self.novel_dir)
        self.assertEqual(len(lines), len(NOVEL_PARAS))
        self.assertEqual(lines[-1], NOVEL_PARAS[-1])
        self.assertEqual(index["file_sha256"], self.index["file_sha256"])

    def test_crlf_input_does_not_change_hash(self):
        """源文件是 CRLF，落盘仍是 LF，哈希与 LF 版一致。"""
        text = "\n".join(NOVEL_PARAS)
        lf = hashlib.sha256(render(text).encode("utf-8")).hexdigest()
        crlf_bytes = render(text).replace("\n", "\r\n").encode("utf-8")
        normalized = crlf_bytes.decode("utf-8").replace("\r\n", "\n")
        self.assertEqual(
            hashlib.sha256(normalized.encode("utf-8")).hexdigest(), lf)

    def test_one_byte_change_breaks_the_gate(self):
        self._align()
        # 改正文一个字（不改长度），模拟"有人手改了 novel.txt"
        txt = self.novel_dir / "novel.txt"
        body = txt.read_text(encoding="utf-8")
        txt.write_text(body.replace("拖拉机", "推土机"), encoding="utf-8",
                       newline="\n")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn(2, self._steps(problems))
        joined = " ".join(m for _, m in problems)
        self.assertIn("磁盘字节", joined)


class TestAlignSkeleton(Base):
    def test_beats_are_never_auto_confirmed(self):
        doc = self._align()
        for b in doc["beats"]:
            self.assertEqual(b["fidelity"], "unconfirmed")
            self.assertEqual(b["review_status"], "needs_review")
            self.assertIsNone(b["para"], "候选不得写进 para")

    def test_candidates_land_in_para_candidates(self):
        doc = self._align()
        self.assertTrue(any(b["para_candidates"] for b in doc["beats"]),
                        "至少应给出一段候选，否则 align 没有价值")
        for b in doc["beats"]:
            for c in b["para_candidates"]:
                self.assertLessEqual(c["para_from"], c["para_to"])

    def test_align_meta_declares_not_auto_confirmed(self):
        doc = self._align()
        self.assertFalse(doc["align_meta"]["auto_confirmed"])

    def test_coverage_counts_sum_to_beats_total(self):
        doc = self._align()
        by = doc["coverage"]["by_fidelity"]
        self.assertEqual(sum(by.values()), doc["coverage"]["beats_total"])

    def test_pages_come_from_chapter_json_as_ints(self):
        doc = self._align()
        self.assertEqual(doc["pages"], [45, 46, 47])

    def test_unknown_novel_chapter_raises(self):
        with self.assertRaises(GateError):
            novel_chapter_range(self.index, "ch99")

    def test_candidate_ranges_respects_chapter_bounds(self):
        lines, _ = load_novel(self.novel_dir)
        got = candidate_ranges("惠惠在公会门口拦下和真", lines, 4, 8)
        self.assertTrue(got)
        for c in got:
            self.assertGreaterEqual(c["para_from"], 4)
            self.assertLessEqual(c["para_to"], 8)


class TestCheckStep1(Base):
    def test_missing_novel_ref_is_step_1(self):
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertEqual(self._steps(problems), [1])


class TestCheckStep2(Base):
    def test_tampered_text_sha256_is_step_2(self):
        doc = self._align()
        doc["source"]["text_sha256"] = "0" * 64
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn(2, self._steps(problems))

    def test_missing_text_sha256_is_step_2(self):
        doc = self._align()
        doc["source"].pop("text_sha256")
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn(2, self._steps(problems))


class TestCheckStep3(Base):
    def test_v1_script_cannot_pass_step_3(self):
        """v1 结构里没有 source_refs，无从判断来源——必须报"先迁移"。"""
        self._align()
        write_audit(self.work, self.work / "novel_ref.json", schema="script/v1")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        step3 = [m for s, m in problems if s == 3]
        self.assertTrue(any("P0-11" in m or "source_refs" in m for m in step3), step3)

    def test_empty_source_refs_is_reported_with_segment_id(self):
        self._align()
        make_v2_script(self.work)
        doc = json.loads((self.work / "script.json").read_text(encoding="utf-8"))
        doc["segments"][0]["narration"]["source_refs"] = []
        (self.work / "script.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        joined = " ".join(m for s, m in problems if s == 3)
        self.assertIn("seg_0001", joined)

    def test_unknown_beat_reference_is_step_3(self):
        self._align()
        make_v2_script(self.work)
        doc = json.loads((self.work / "script.json").read_text(encoding="utf-8"))
        doc["segments"][0]["narration"]["source_refs"] = [
            {"type": "novel_beat", "beat": "b99"}]
        (self.work / "script.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("b99", " ".join(m for s, m in problems if s == 3))


class TestCheckStep4(Base):
    def test_original_beat_without_pages_is_step_4(self):
        doc = self._align()
        doc["beats"][0]["fidelity"] = "original"
        doc["beats"][0]["pages"] = []
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn(4, self._steps(problems))

    def test_page_outside_chapter_is_step_4(self):
        doc = self._align()
        doc["beats"][0]["pages"] = ["page_9999"]
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        joined = " ".join(m for s, m in problems if s == 4)
        self.assertIn("page_9999", joined)


class TestCheckStep5(Base):
    def _v2_ready(self):
        self._align()
        make_v2_script(self.work)
        return self.work / "novel_ref.json"

    def test_missing_audit_is_step_5(self):
        self._v2_ready()
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        joined = " ".join(m for s, m in problems if s == 5)
        self.assertIn("script-audit.json", joined)

    def test_complete_audit_passes_all_five_steps(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        ok, problems = check(self.work, self.novel_dir)
        self.assertTrue(ok, format_problems(problems))

    def test_editing_one_segment_invalidates_audit_and_names_the_segment(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        doc = json.loads((self.work / "script.json").read_text(encoding="utf-8"))
        doc["segments"][1]["narration"]["text"] += "（改了一句）"
        (self.work / "script.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        step5 = " ".join(m for s, m in problems if s == 5)
        self.assertIn("script_sha256", step5)
        self.assertIn("seg_0002", step5)

    def test_model_cannot_sign_the_audit(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2", reviewed_by="model:gpt")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("human:", " ".join(m for s, m in problems if s == 5))

    def test_partial_review_status_blocks_release(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2", review_status="partial")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("partial", " ".join(m for s, m in problems if s == 5))

    def test_changing_novel_ref_invalidates_audit(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        doc = json.loads(ref.read_text(encoding="utf-8"))
        doc["beats"][0]["note"] = "事后又改了一笔"
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("novel_ref_sha256", " ".join(m for s, m in problems if s == 5))

    def test_schema_mismatch_is_step_5(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2", script_schema="script/v1")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("script_schema", " ".join(m for s, m in problems if s == 5))

    def test_audit_missing_spec_version_is_step_5(self):
        ref = self._v2_ready()
        audit = write_audit(self.work, ref, schema="script/v2")
        audit.pop("audit_spec_version")
        (self.work / "script-audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("audit_spec_version", " ".join(m for s, m in problems if s == 5))

    def test_audit_not_covering_a_segment_is_step_5(self):
        ref = self._v2_ready()
        audit = write_audit(self.work, ref, schema="script/v2")
        audit["audited_segments"] = audit["audited_segments"][:1]
        (self.work / "script-audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("seg_0002", " ".join(m for s, m in problems if s == 5))


class TestFormatting(Base):
    def test_problems_are_grouped_by_step(self):
        self._align()
        ok, problems = check(self.work, self.novel_dir)
        text = format_problems(problems)
        self.assertIn("step 3", text)
        self.assertTrue(text.startswith("error:"))

    def test_all_problems_reported_at_once(self):
        """不要修一个跑一次：一次要把全部问题列出来。"""
        doc = self._align()
        doc["source"]["text_sha256"] = "0" * 64
        doc["beats"][0]["fidelity"] = "original"
        doc["beats"][0]["pages"] = []
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertTrue({2, 3, 4, 5}.issubset(set(self._steps(problems))),
                        self._steps(problems))


if __name__ == "__main__":
    unittest.main()
