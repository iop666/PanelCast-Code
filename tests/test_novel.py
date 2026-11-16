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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panelcast.novel import (  # noqa: E402
    ALTERATION_ORIGINS,
    AUDIT_STATUSES,
    DISPOSITIONS,
    FIDELITIES,
    REVIEW_STATUSES,
    SCOPES,
    SCRIPT_SCHEMAS,
    SEVERITIES,
    GateError,
    build_novel_ref,
    check,
    candidate_ranges,
    format_problems,
    lint_audit,
    load_novel,
    novel_chapter_range,
    render,
    script_segments,
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


_CN_DIGITS = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]


def authority_index(chapter):
    """给夹具造一份自洽的卷级索引。

    P0-REVIEW-07 之后身份校验是 fail-closed：没有权威表就拒绝。夹具如果
    不提供 `chapter_index.json`，所有门禁测试都会卡在第 1 步——这恰恰说明
    旧夹具一直在"没有权威表"的条件下跑，才没发现静默放行。
    """
    slug = chapter["series_slug"]
    vol = chapter["volume_number"]
    vcn = chapter["volume_chapter_number"]
    glob = chapter["global_chapter_number"]

    def ident(pos, g):
        return {
            "chapter_uid": f"{slug}-v{vol:02d}-ch{g:02d}",
            "series_slug": slug, "volume_number": vol,
            "global_chapter_number": g, "volume_chapter_number": pos,
            "id": f"ch{pos:02d}",
            "number": f"第{_CN_DIGITS[g]}章" if 0 <= g < len(_CN_DIGITS) else str(g),
        }

    chapters = [ident(i, glob - (vcn - i)) for i in range(1, vcn + 1)]
    return {"schema": "chapter-index/v1", "series": chapter.get("series"),
            "volume": chapter.get("volume"), "series_slug": slug,
            "volume_number": vol, "chapters": chapters}


def write_chapter_work(dirpath, pages=("page_0045", "page_0046", "page_0047"),
                       segments=None, schema=None):
    d = Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    chapter = {
        "schema": "chapter-work/v1", "series": "为美好的世界献上祝福！",
        "volume": "漫画 第1卷", "id": "ch02", "number": "第二章",
        "title": "替华美的高阶职业带来愉悦！",
        "label": "第二章 替华美的高阶职业带来愉悦！",
        # 身份字段（P0-08）：chapter_uid 是唯一权威身份，
        # id / number 只作兼容与展示，必须与它自洽。
        "chapter_uid": "konosuba-manga-v01-ch02",
        "series_slug": "konosuba-manga",
        "volume_number": 1,
        "global_chapter_number": 2,
        "volume_chapter_number": 2,
        "start_page": 45, "end_page": 47, "page_count": len(pages),
        "pages": list(pages), "source_work": "m1/v1/work",
    }
    (d / "chapter.json").write_text(json.dumps(chapter, ensure_ascii=False,
                                              indent=2) + "\n", encoding="utf-8")
    # 卷级权威索引放在 work 的上一层：真实布局 `m1/v1/ch01/work` 的索引在
    # `m1/v1/work/chapter_index.json`，这里用 `tmp/chapter_index.json` 等价模拟。
    (d.parent / "chapter_index.json").write_text(
        json.dumps(authority_index(chapter), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
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
                reviewed_by="human:reviewer", script_schema=None, seg_texts=None,
                seg_extra=None, drop=()):
    """落一份审核报告。默认是"全部通过"的基准，测试里再逐项破坏。

    `seg_extra` 按 `segment_id` 覆盖单段字段；`drop` 是要从报告里整体删掉的键。
    这两个参数让"只坏一处"的负例能写得很短。
    """
    work = Path(work)
    script_bytes = (work / "script.json").read_bytes()
    script = json.loads(script_bytes.decode("utf-8"))
    segs = script["segments"]
    audited = []
    for s in segs:
        text = s.get("text") or (s.get("narration") or {}).get("text") or ""
        if seg_texts and s["id"] in seg_texts:
            text = seg_texts[s["id"]]
        rec = {
            "segment_id": s["id"],
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "status": "approved",
            "fidelity": "drawn",
            "alteration_origin": None,
            "disposition": "keep",
            "pages_declared": list(s.get("pages") or []),
            "novel_para": [[0, 0]],
            "evidence": "夹具：基准证据",
        }
        rec.update((seg_extra or {}).get(s["id"], {}))
        audited.append(rec)
    audit = {
        "schema": "script-audit/v2",
        "audit_spec_version": "v1.1",
        "judgement_scope": "narration_vs_source",
        "chapter_uid": "konosuba-manga-v01-ch02",
        "script_schema": script_schema or schema,
        "script_sha256": hashlib.sha256(script_bytes).hexdigest(),
        "novel_ref_sha256": hashlib.sha256(Path(ref_path).read_bytes()).hexdigest(),
        "audited_segments": audited,
        "review_status": review_status,
        "reviewed_by": reviewed_by,
        "reviewed_at": "2026-11-16T00:00:00+08:00",
    }
    for k in drop:
        audit.pop(k, None)
    (work / "script-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return audit


def confirm_beats(work, fidelity="drawn", para=(0, 0)):
    """把骨架里的 beat 全部标成"人工已确认"，用于构造"结构完全合法"的基准。

    真实流程里这一步只能由人做；测试里必须显式调用它，
    否则任何用例都不该通过第 4 步——这正是 P0-05 验收第 5 条要锁住的行为。
    """
    work = Path(work)
    path = work / "novel_ref.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    for b in doc.get("beats") or []:
        b["fidelity"] = fidelity
        b["para"] = list(para)
        b["review_status"] = "confirmed"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return doc


def make_v2_script(work, beats_per_seg=1):
    """把 v1 讲稿改造成"结构合法"的 v2：每段挂一个存在的 beat。"""
    work = Path(work)
    doc = json.loads((work / "script.json").read_text(encoding="utf-8"))
    doc["schema"] = "script/v2"
    doc["chapter_uid"] = "konosuba-manga-v01-ch02"
    for i, seg in enumerate(doc["segments"], 1):
        seg["visual_refs"] = [{"type": "page", "id": p, "role": "depicts"}
                              for p in seg.get("pages") or []]
        # 幂等：已经迁过的段不再 pop，否则重复调用会 KeyError
        if "text" in seg:
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

    def _v2_ready(self):
        """造一份"结构上完全合法"的 v2 章：骨架 → 人工确认 → 讲稿迁移。"""
        self._align()
        confirm_beats(self.work)
        make_v2_script(self.work)
        return self.work / "novel_ref.json"


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

    def test_skeleton_beats_are_rejected_not_let_through(self):
        """--align 的骨架必须过不了门禁。这是 P0-05 验收第 5 条。"""
        self._align()
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        joined = " ".join(m for s, m in problems if s == 4)
        self.assertIn("needs_review", joined)

    def test_unconfirmed_fidelity_is_illegal(self):
        doc = self._align()
        for b in doc["beats"]:
            b["review_status"] = "confirmed"   # 只改状态，不改 fidelity
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        joined = " ".join(m for s, m in problems if s == 4)
        self.assertIn("unconfirmed", joined)

    def test_confirmed_beat_without_para_is_step_4(self):
        doc = self._align()
        for b in doc["beats"]:
            b["review_status"] = "confirmed"
            b["fidelity"] = "drawn"
            b["para"] = None
        write_novel_ref(self.work, doc)
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        joined = " ".join(m for s, m in problems if s == 4)
        self.assertIn("没有 para", joined)

    def test_original_beat_may_have_null_para(self):
        doc = self._align()
        for b in doc["beats"]:
            b["review_status"] = "confirmed"
            b["fidelity"] = "original"
            b["para"] = None
            b["pages"] = ["page_0005"]
        write_novel_ref(self.work, doc)
        _ok, problems = check(self.work, self.novel_dir)
        joined = " ".join(m for s, m in problems if s == 4)
        self.assertNotIn("没有 para", joined)


class TestCheckStep5(Base):
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


class TestAuditSchema(Base):
    """`script-audit.json` 的 Schema 校验（P0-REVIEW-04）。

    这一组用例针对的是"审核口径"本身，不是门禁哈希。它们存在的理由：
    上一版规范里 `status` 只有 approved/rewritten/removed，样张只好自己发明一个
    `pending` 并在文件里写声明；`alteration_origin` 又用 `"none"` 冒充枚举成员。
    自造的枚举没人校验，就等于没有枚举——所以这里逐条锁住。
    """

    PAGES = {"page_0045", "page_0046", "page_0047"}

    def _lint(self, **kw):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2", **kw)
        audit = json.loads((self.work / "script-audit.json").read_text(encoding="utf-8"))
        return lint_audit(audit, page_set=self.PAGES)

    def _text(self, problems):
        return " ".join(m for _sid, m in problems)

    def test_baseline_is_clean(self):
        self.assertEqual(self._lint(), [])

    def test_unsigned_report_passes_lint_but_not_the_gate(self):
        """样张必须能校验格式，同时必须过不了出片门禁——两件事不能混。"""
        problems = self._lint(review_status="pending_human", reviewed_by=None)
        self.assertEqual(problems, [])
        ok, gate = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertIn("只有 approved 允许出片", " ".join(m for s, m in gate if s == 5))

    def test_pending_is_not_a_status(self):
        problems = self._lint(seg_extra={"seg_0001": {"status": "pending"}})
        self.assertIn("pending_rewrite", self._text(problems))

    def test_none_is_not_an_origin(self):
        """`"none"` 是伪值：没有差异就该留空，不许造一个枚举成员冒充。"""
        problems = self._lint(seg_extra={"seg_0001": {"alteration_origin": "none"}})
        self.assertIn("alteration_origin", self._text(problems))

    def test_altered_without_origin_is_rejected(self):
        problems = self._lint(seg_extra={"seg_0001": {"fidelity": "altered"}})
        self.assertIn("必须说明差异责任方", self._text(problems))

    def test_manga_origin_without_pages_is_rejected(self):
        """`alteration_origin=manga` 本身是关于画面的断言，必须附页码。"""
        problems = self._lint(seg_extra={"seg_0001": {
            "fidelity": "altered", "alteration_origin": "manga",
            "pages_declared": []}})
        self.assertIn("pages_declared 为空", self._text(problems))

    def test_mixed_without_note_is_rejected(self):
        """`mixed` 最容易变成逃生门：一句"又像漫画又像原创"就绕过举证。"""
        problems = self._lint(seg_extra={"seg_0001": {
            "fidelity": "altered", "alteration_origin": "mixed"}})
        self.assertIn("mixed_note", self._text(problems))

    def test_mixed_with_note_is_accepted(self):
        problems = self._lint(seg_extra={"seg_0001": {
            "fidelity": "altered", "alteration_origin": "mixed",
            "mixed_note": "漫画 p45 给了摔进店里的动作，旁白自己加了「撞翻一排货架」"}})
        self.assertEqual(problems, [], self._text(problems))

    def test_unknown_cannot_be_approved(self):
        """`unknown` 是"还没查清"，不是结论——有它就整份不许签核。"""
        problems = self._lint(seg_extra={"seg_0001": {
            "fidelity": "altered", "alteration_origin": "unknown"}})
        self.assertIn("不许签核通过", self._text(problems))

    def test_unknown_is_allowed_as_an_open_question(self):
        """但允许先记下来等查：pending_rewrite + 未签核时它是合法的。"""
        problems = self._lint(
            review_status="pending_human", reviewed_by=None,
            seg_extra={"seg_0001": {
                "fidelity": "altered", "alteration_origin": "unknown",
                "status": "pending_rewrite", "disposition": "rewrite"}})
        self.assertEqual(problems, [], self._text(problems))

    def test_narration_origin_cannot_be_kept(self):
        """旁白自己编的却判保留，等于承认这段没有来源。"""
        problems = self._lint(seg_extra={"seg_0001": {
            "fidelity": "altered", "alteration_origin": "narration"}})
        self.assertIn("只能改写或删除", self._text(problems))

    def test_missing_judgement_scope_is_rejected(self):
        problems = self._lint(drop=("judgement_scope",))
        self.assertIn("judgement_scope", self._text(problems))

    def test_wrong_judgement_scope_is_rejected(self):
        """把审核报告标成 manga_vs_novel，就是把两层语义混用了。"""
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        path = self.work / "script-audit.json"
        audit = json.loads(path.read_text(encoding="utf-8"))
        audit["judgement_scope"] = "manga_vs_novel"
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        problems = lint_audit(audit, page_set=self.PAGES)
        self.assertIn("narration_vs_source", self._text(problems))

    def test_novel_ref_requires_its_own_scope(self):
        doc = self._align()
        doc.pop("judgement_scope")
        write_novel_ref(self.work, doc)
        _ok, problems = check(self.work, self.novel_dir)
        self.assertIn("manga_vs_novel", " ".join(m for s, m in problems if s == 4))

    def test_page_outside_chapter_is_rejected(self):
        problems = self._lint(seg_extra={"seg_0001": {
            "pages_declared": ["page_0099"]}})
        self.assertIn("page_0099", self._text(problems))

    def test_machine_cannot_sign_its_own_work(self):
        """机器出结论、机器签名 = 自己给自己发合格证。"""
        ref = self._v2_ready()
        audit = write_audit(self.work, ref, schema="script/v2",
                            reviewed_by="human:executor")
        audit["prepared_by"] = "human:executor"
        path = self.work / "script-audit.json"
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        problems = lint_audit(audit, page_set=self.PAGES)
        self.assertIn("另一只手", self._text(problems))

    def test_rewritten_does_not_imply_approved(self):
        """改完了仍可停在 pending_human——这是合法组合，不许被当成"未完成"报错。"""
        problems = self._lint(
            review_status="pending_human", reviewed_by=None,
            seg_extra={"seg_0001": {"status": "rewritten"}})
        self.assertEqual(problems, [], self._text(problems))

    def test_approved_with_rewrite_disposition_is_contradictory(self):
        problems = self._lint(seg_extra={"seg_0001": {"disposition": "rewrite"}})
        self.assertIn("通过了就不该还挂着要改", self._text(problems))


class TestAuditIntegrity(Base):
    """P0-REVIEW-07：审计记录完整性 + Schema/Linter 真正一致。

    这一组针对的不是"字段写错"，而是"错误能被藏起来"：
    重复 `segment_id` 让后一条覆盖前一条、`severity` 枚举写在 Schema 里却没人查、
    损坏的 JSON 被当成不存在。三者都会让校验器"看起来通过"。
    """

    PAGES = {"page_0045", "page_0046", "page_0047"}

    def _base_audit(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        return json.loads((self.work / "script-audit.json").read_text(encoding="utf-8"))

    def _text(self, problems):
        return " ".join(m for _sid, m in problems)

    def _lint(self, audit, **kw):
        kw.setdefault("page_set", self.PAGES)
        return lint_audit(audit, **kw)

    def test_duplicate_segment_id_is_rejected_in_either_order(self):
        """审核意见的原反例：无效记录在前、合法记录在后，不能靠覆盖洗白。"""
        audit = self._base_audit()
        valid = audit["audited_segments"][0]
        invalid = dict(valid, disposition="rewrite")   # 与 status=approved 矛盾
        for order, label in (([invalid, valid], "无效在前"),
                             ([valid, invalid], "无效在后")):
            with self.subTest(order=label):
                doc = json.loads(json.dumps(audit))
                doc["audited_segments"] = order
                problems = self._lint(doc)
                self.assertIn("segment_id 重复", self._text(problems))

    def test_extra_record_not_in_script_is_rejected(self):
        audit = self._base_audit()
        extra = dict(audit["audited_segments"][0], segment_id="seg_0099")
        audit["audited_segments"].append(extra)
        _doc, segs, _schema = script_segments(self.work)
        problems = self._lint(audit, segs=segs)
        self.assertIn("多余记录", self._text(problems))

    def test_missing_segment_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"] = audit["audited_segments"][:1]
        _doc, segs, _schema = script_segments(self.work)
        problems = self._lint(audit, segs=segs)
        self.assertIn("未覆盖该段", self._text(problems))

    def test_invalid_severity_is_rejected(self):
        """Schema 里有 severity enum，Linter 以前没查——这是漏检。"""
        audit = self._base_audit()
        audit["audited_segments"][0]["severity"] = "catastrophic"
        self.assertIn("severity 非法", self._text(self._lint(audit)))

    def test_bad_segment_id_format_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"][0]["segment_id"] = "seg_1"
        self.assertIn("segment_id 格式非法", self._text(self._lint(audit)))

    def test_bad_text_sha256_format_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"][0]["text_sha256"] = "abc"
        self.assertIn("text_sha256 必须是 64 位", self._text(self._lint(audit)))

    def test_bad_page_name_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"][0]["pages_declared"] = ["p45"]
        self.assertIn("page_XXXX", self._text(self._lint(audit)))

    def test_every_required_top_level_field_is_enforced(self):
        required = ["schema", "audit_spec_version", "judgement_scope", "chapter_uid",
                    "script_schema", "script_sha256", "novel_ref_sha256",
                    "audited_segments", "review_status"]
        for key in required:
            with self.subTest(field=key):
                audit = self._base_audit()
                audit.pop(key)
                problems = self._lint(audit)
                self.assertTrue(
                    any(key in m and "缺必填字段" in m for _s, m in problems),
                    f"{key}: {self._text(problems)}")

    def test_every_required_segment_field_is_enforced(self):
        for key in ("segment_id", "text_sha256", "status", "fidelity",
                    "disposition", "evidence"):
            with self.subTest(field=key):
                audit = self._base_audit()
                audit["audited_segments"][0].pop(key)
                problems = self._lint(audit)
                self.assertTrue(
                    any(key in m and "缺必填字段" in m for _s, m in problems),
                    f"{key}: {self._text(problems)}")

    # ---- 损坏的 JSON 不能当成不存在 ----
    def test_corrupt_audit_fails_the_gate_at_step_5(self):
        self._v2_ready()
        (self.work / "script-audit.json").write_text("{broken", encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertTrue(any(s == 5 and "无法解析" in m for s, m in problems), problems)

    def test_corrupt_novel_ref_fails_the_gate_at_step_1(self):
        self._v2_ready()
        (self.work / "novel_ref.json").write_text("{broken", encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertTrue(any(s == 1 and "novel_ref.json" in m and "无法解析" in m
                            for s, m in problems), problems)

    def test_corrupt_script_fails_the_gate(self):
        self._v2_ready()
        (self.work / "script.json").write_text("{broken", encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        self.assertTrue(any("script.json" in m and "无法解析" in m for _s, m in problems),
                        problems)


class TestStructuralFailClosed(Base):
    """P0-REVIEW-08：合法 JSON 但结构不对，必须返回校验错误而不是 traceback。

    覆盖审核意见列出的全部负例：报告顶层、`audited_segments`、逐段对象、
    `severity=null`、`pages_actual`、`narration + fix_pages`、`reviewed_by=[]`。
    """

    PAGES = {"page_0045", "page_0046", "page_0047"}

    def _base_audit(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        return json.loads((self.work / "script-audit.json").read_text(encoding="utf-8"))

    def _lint(self, audit):
        return lint_audit(audit, page_set=self.PAGES)

    def _text(self, problems):
        return " ".join(m for _sid, m in problems)

    def test_top_level_must_be_an_object(self):
        for bad in (None, [], "wrong type", 123):
            with self.subTest(value=bad):
                self.assertIn("顶层必须是对象", self._text(lint_audit(bad)))

    def test_audited_segments_must_be_an_array(self):
        audit = self._base_audit()
        audit["audited_segments"] = {}
        self.assertIn("audited_segments 必须是数组", self._text(self._lint(audit)))

    def test_audited_segments_entry_must_be_an_object(self):
        audit = self._base_audit()
        audit["audited_segments"] = [None]
        problems = self._lint(audit)
        self.assertIn("必须是对象", self._text(problems))
        self.assertIn("不能把它当成一条审核记录", self._text(problems))

    def test_severity_null_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"][0]["severity"] = None
        self.assertIn("severity 非法", self._text(self._lint(audit)))

    def test_pages_actual_null_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"][0]["pages_actual"] = None
        self.assertIn("pages_actual 必须是数组", self._text(self._lint(audit)))

    def test_pages_actual_bad_page_name_is_rejected(self):
        audit = self._base_audit()
        audit["audited_segments"][0]["pages_actual"] = ["p45"]
        self.assertIn("page_XXXX", self._text(self._lint(audit)))

    def test_narration_with_fix_pages_is_rejected(self):
        """Schema：旁白自己编的只能 rewrite/remove，fix_pages 也不行。"""
        audit = self._base_audit()
        audit["audited_segments"][0].update({
            "fidelity": "altered", "alteration_origin": "narration",
            "disposition": "fix_pages", "status": "pending_rewrite"})
        self.assertIn("只能改写或删除", self._text(self._lint(audit)))

    def test_reviewed_by_wrong_type_is_rejected(self):
        for bad in ([], 123, {}):
            with self.subTest(value=bad):
                audit = self._base_audit()
                audit["reviewed_by"] = bad
                self.assertIn("reviewed_by 必须是字符串或 null",
                              self._text(self._lint(audit)))

    def test_gate_returns_step5_for_structurally_invalid_audit(self):
        """`check()` 不能在 audited_segments=[null] 上抛 AttributeError。"""
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        path = self.work / "script-audit.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["audited_segments"] = [None]
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        step5 = " ".join(m for s, m in problems if s == 5)
        self.assertIn("必须是对象", step5)

    def test_gate_returns_step5_for_null_audit(self):
        ref = self._v2_ready()
        write_audit(self.work, ref, schema="script/v2")
        (self.work / "script-audit.json").write_text("null\n", encoding="utf-8")
        ok, problems = check(self.work, self.novel_dir)
        self.assertFalse(ok)
        step5 = " ".join(m for s, m in problems if s == 5)
        self.assertIn("顶层必须是 JSON 对象", step5)

    def test_cli_returns_errors_for_every_structural_negative(self):
        """审核意见要求的负例由真实 CLI 执行，且必须是非零退出码。"""
        base = self._base_audit()
        path = self.work / "script-audit.json"

        def mutate(doc):
            doc["audited_segments"][0]["severity"] = None

        def mutate_entry(doc):
            doc["audited_segments"] = [None]

        def mutate_pages_actual(doc):
            doc["audited_segments"][0]["pages_actual"] = None

        def mutate_bad_page(doc):
            doc["audited_segments"][0]["pages_actual"] = ["p45"]

        def mutate_narration(doc):
            doc["audited_segments"][0].update({
                "fidelity": "altered", "alteration_origin": "narration",
                "disposition": "fix_pages", "status": "pending_rewrite"})

        def mutate_reviewer(doc):
            doc["reviewed_by"] = []

        cases = [
            ("script-audit-null", None, "顶层必须是 JSON 对象"),
            ("audited-segment-null", mutate_entry, "必须是对象"),
            ("severity-null", mutate, "severity 非法"),
            ("pages-actual-null", mutate_pages_actual, "pages_actual 必须是数组"),
            ("pages-actual-bad-name", mutate_bad_page, "page_XXXX"),
            ("narration-fix-pages", mutate_narration, "只能改写或删除"),
            ("reviewed-by-array", mutate_reviewer, "reviewed_by 必须是字符串或 null"),
        ]
        for label, mutator, expected in cases:
            with self.subTest(case=label):
                if mutator is None:
                    path.write_text("null\n", encoding="utf-8")
                else:
                    doc = json.loads(json.dumps(base))
                    mutator(doc)
                    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
                r = subprocess.run(
                    [sys.executable, "-m", "panelcast", "m1", "novel", "lint",
                     "--work", str(self.work)],
                    cwd=str(ROOT), capture_output=True, text=True)
                self.assertEqual(r.returncode, 3,
                                 f"{label}: stderr={r.stderr}\nstdout={r.stdout}")
                self.assertIn(expected, r.stderr)


class TestSchemaFile(unittest.TestCase):
    """`docs/schemas/script-audit.schema.json` 与代码常量必须一致。

    两份枚举各写一遍是必要的（一份给人读、一份给机器跑），但**必须锁死不许分叉**：
    只改一边的后果是"文档说合法、校验器说非法"，比没有 Schema 更糟。
    """

    @classmethod
    def setUpClass(cls):
        path = ROOT / "docs" / "schemas" / "script-audit.schema.json"
        cls.schema = json.loads(path.read_text(encoding="utf-8"))
        cls.seg = cls.schema["properties"]["audited_segments"]["items"]

    def test_status_enum_matches(self):
        self.assertEqual(set(self.seg["properties"]["status"]["enum"]),
                         AUDIT_STATUSES)

    def test_fidelity_enum_matches(self):
        self.assertEqual(set(self.seg["properties"]["fidelity"]["enum"]),
                         FIDELITIES)

    def test_disposition_enum_matches(self):
        self.assertEqual(set(self.seg["properties"]["disposition"]["enum"]),
                         DISPOSITIONS)

    def test_alteration_origin_enum_matches(self):
        enum = set(self.seg["properties"]["alteration_origin"]["enum"])
        self.assertEqual(enum - {None}, ALTERATION_ORIGINS)
        self.assertIn(None, enum, "无差异必须允许留空")

    def test_review_status_enum_matches(self):
        self.assertEqual(set(self.schema["properties"]["review_status"]["enum"]),
                         REVIEW_STATUSES)

    def test_severity_enum_matches(self):
        """Schema 写了 severity enum，Linter 就必须执行——否则是纸面约束。"""
        self.assertEqual(set(self.seg["properties"]["severity"]["enum"]), SEVERITIES)

    def test_script_schema_enum_matches(self):
        self.assertEqual(set(self.schema["properties"]["script_schema"]["enum"]),
                         SCRIPT_SCHEMAS)

    def test_mixed_note_is_declared(self):
        """`mixed` 必须要求单独说明新增部分，否则它就是个逃生门。"""
        self.assertIn("mixed_note", self.seg["properties"])

    def test_conditional_rules_cover_the_three_risky_origins(self):
        """条件规则不能只是摆设：mixed / narration / unknown 各自都要有一条。"""
        text = json.dumps(self.seg["allOf"], ensure_ascii=False)
        for origin in ("mixed", "narration", "unknown"):
            self.assertIn(f'"{origin}"', text, f"缺 {origin} 的条件规则")
        self.assertIn("mixed_note", text)

    def test_judgement_scope_matches(self):
        self.assertEqual(self.schema["properties"]["judgement_scope"]["const"],
                         SCOPES["script_audit"])

    def test_shipped_sample_passes_lint(self):
        """第一章样张是正式示例，格式不许退化。"""
        work = ROOT / "m1" / "v1" / "ch01" / "work"
        if not (work / "script-audit.json").exists():
            self.skipTest("样张不在当前工作区")
        audit = json.loads((work / "script-audit.json").read_text(encoding="utf-8"))
        chapter = json.loads((work / "chapter.json").read_text(encoding="utf-8"))
        problems = lint_audit(audit, page_set=set(chapter["pages"]))
        self.assertEqual(problems, [], " ".join(m for _s, m in problems))

    def test_shipped_sample_is_still_unsigned(self):
        """样张必须保持未签核——签核是项目负责人的动作，不是 Agent 的。"""
        work = ROOT / "m1" / "v1" / "ch01" / "work"
        if not (work / "script-audit.json").exists():
            self.skipTest("样张不在当前工作区")
        audit = json.loads((work / "script-audit.json").read_text(encoding="utf-8"))
        self.assertEqual(audit["review_status"], "pending_human")
        self.assertIsNone(audit["reviewed_by"])


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
