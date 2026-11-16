"""P0-08 章节身份测试。

锁住三件事：

1. `chapter_uid` 是唯一权威身份，格式与三套编号必须自洽；
2. `find_chapter` **有歧义就报错**，绝不挑一个"最像的"；
3. 章级 work 里五份文件声明不同章节时，`check_work_identity` 必须报错并列出全部值。
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from panelcast.chapters import build_chapter_work, build_index, find_chapter, pages_of  # noqa: E402
from panelcast.identity import (  # noqa: E402
    IdentityError,
    chapter_problems,
    check_work_identity,
    cn_to_int,
    index_problems,
    make_uid,
    parse_uid,
    require_index_identity,
)


def chapter(uid="konosuba-manga-v02-ch06", **over):
    """一份自洽的第六章身份块，测试里逐项破坏。"""
    base = {
        "chapter_uid": uid,
        "series_slug": "konosuba-manga",
        "volume_number": 2,
        "global_chapter_number": 6,
        "volume_chapter_number": 1,
        "id": "ch01",
        "number": "第六章",
        "label_zh": "第六章 为这片湖献上自称女神的圣水！",
        "start_page": 3, "end_page": 30, "page_count": 28,
        "confirmed": True,
    }
    base.update(over)
    return base


def index_of(*chapters, slug="konosuba-manga", volume=2):
    return {"schema": "chapter-index/v1", "series": "为美好的世界献上祝福！",
            "volume": f"漫画 第{volume}卷", "series_slug": slug,
            "volume_number": volume, "chapters": list(chapters)}


class TestCnNum(unittest.TestCase):
    def test_parses_chapter_numbers(self):
        cases = {"第一章": 1, "第六章": 6, "第十章": 10, "第十一章": 11,
                 "第十二章": 12, "第二章 替华美的高阶职业带来愉悦！": 2}
        for text, want in cases.items():
            self.assertEqual(cn_to_int(text), want, text)

    def test_returns_none_instead_of_guessing(self):
        for text in ("", None, "Chapter 6", "第？章", "序章"):
            self.assertIsNone(cn_to_int(text), repr(text))


class TestUid(unittest.TestCase):
    def test_make_uid_pads_to_two_digits(self):
        self.assertEqual(make_uid("konosuba-manga", 2, 6), "konosuba-manga-v02-ch06")
        self.assertEqual(make_uid("konosuba-manga", 1, 1), "konosuba-manga-v01-ch01")

    def test_non_ascii_slug_is_rejected(self):
        with self.assertRaises(IdentityError):
            make_uid("为美好的世界献上祝福", 1, 1)

    def test_parse_roundtrip(self):
        self.assertEqual(parse_uid("konosuba-manga-v02-ch06"),
                         ("konosuba-manga", 2, 6))

    def test_unpadded_uid_is_rejected(self):
        """`v1` 与 `v01` 并存会让"唯一身份"变成两套字符串。"""
        for bad in ("konosuba-manga-v2-ch6", "konosuba-manga-v02-ch6", "x"):
            with self.assertRaises(IdentityError):
                parse_uid(bad)


class TestChapterProblems(unittest.TestCase):
    def test_consistent_chapter_is_clean(self):
        self.assertEqual(chapter_problems(chapter(), "konosuba-manga", 2), [])

    def test_missing_fields_are_reported_as_a_block(self):
        problems = chapter_problems({"id": "ch01", "number": "第六章"})
        self.assertTrue(any("缺身份字段" in p for p in problems), problems)

    def test_uid_volume_disagrees_with_field(self):
        problems = chapter_problems(chapter(volume_number=3), "konosuba-manga", 2)
        self.assertTrue(any("两个字段各说一套" in p or "卷号" in p for p in problems),
                        problems)

    def test_number_disagrees_with_global_number(self):
        """`number` 写「第七章」但全书号是 6 —— 人工对数会数错章。"""
        problems = chapter_problems(chapter(number="第七章"), "konosuba-manga", 2)
        self.assertTrue(any("第七章" in p for p in problems), problems)

    def test_id_must_derive_from_volume_chapter_number(self):
        """`id` 只作兼容字段，不许承载第二种含义。"""
        problems = chapter_problems(chapter(volume_chapter_number=2), "konosuba-manga", 2)
        self.assertTrue(any("id=" in p and "volume_chapter_number" in p
                            for p in problems), problems)

    def test_series_slug_mismatch(self):
        problems = chapter_problems(chapter(), "other-series", 2)
        self.assertTrue(any("系列" in p for p in problems), problems)


class TestIndexProblems(unittest.TestCase):
    def test_two_volumes_numbered_independently_are_each_valid(self):
        v1 = index_of(chapter("konosuba-manga-v01-ch01", volume_number=1,
                              global_chapter_number=1, volume_chapter_number=1,
                              id="ch01", number="第一章"),
                      slug="konosuba-manga", volume=1)
        self.assertEqual(index_problems(v1), [])

    def test_duplicate_id_is_reported(self):
        a = chapter()
        b = chapter("konosuba-manga-v02-ch07", global_chapter_number=7,
                    volume_chapter_number=2, id="ch02", number="第七章")
        self.assertEqual(index_problems(index_of(a, b)), [])

        dup = chapter("konosuba-manga-v02-ch07", global_chapter_number=7,
                      volume_chapter_number=1, number="第七章")  # id 撞了
        problems = index_problems(index_of(a, dup))
        self.assertTrue(any("重复" in p for p in problems), problems)

    def test_volume_chapter_numbers_must_be_contiguous(self):
        a = chapter()
        b = chapter("konosuba-manga-v02-ch07", global_chapter_number=7,
                    volume_chapter_number=3, id="ch03", number="第七章")
        problems = index_problems(index_of(a, b))
        self.assertTrue(any("1..2" in p for p in problems), problems)

    def test_require_index_identity_raises(self):
        with self.assertRaises(IdentityError):
            require_index_identity({"chapters": []})


class TestFindChapter(unittest.TestCase):
    def setUp(self):
        self.index = index_of(
            chapter(),
            chapter("konosuba-manga-v02-ch07", global_chapter_number=7,
                    volume_chapter_number=2, id="ch02", number="第七章"),
        )

    def test_find_by_uid(self):
        ch = find_chapter(self.index, "konosuba-manga-v02-ch06")
        self.assertEqual(ch["global_chapter_number"], 6)

    def test_find_by_id_and_number(self):
        self.assertEqual(find_chapter(self.index, "ch02")["number"], "第七章")
        self.assertEqual(find_chapter(self.index, "第六章")["global_chapter_number"], 6)

    def test_unknown_key_lists_known_chapters(self):
        with self.assertRaises(IdentityError) as ctx:
            find_chapter(self.index, "ch09")
        self.assertIn("找不到", str(ctx.exception))
        self.assertIn("konosuba-manga-v02-ch06", str(ctx.exception))

    def test_ambiguous_key_raises_instead_of_picking_one(self):
        """同一个 key 命中两章时必须报错——这是 P0-08 的核心纪律。"""
        idx = index_of(
            chapter(),
            chapter("konosuba-manga-v02-ch07", global_chapter_number=7,
                    volume_chapter_number=2, id="ch02", number="第六章"),  # number 撞了
        )
        with self.assertRaises(IdentityError) as ctx:
            find_chapter(idx, "第六章")
        msg = str(ctx.exception)
        self.assertIn("有歧义", msg)
        self.assertIn("konosuba-manga-v02-ch06", msg)
        self.assertIn("konosuba-manga-v02-ch07", msg)
        self.assertIn("chapter_uid", msg)

    def test_pages_of_accepts_uid(self):
        pages = pages_of(self.index, "konosuba-manga-v02-ch06")
        self.assertEqual(len(pages), 28)
        self.assertEqual(pages[0], "page_0003")


class TestWorkIdentity(unittest.TestCase):
    """章级 work 的跨文件核对。这里复现审核意见里的反例。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _work(self, name="ch06"):
        work = self.root / name
        work.mkdir(parents=True)
        return work

    def _write(self, work, name, doc):
        (work / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")

    def test_consistent_work_is_clean(self):
        work = self._work()
        self._write(work, "chapter.json", chapter())
        self._write(work, "novel_ref.json", {
            "schema": "novel-ref/v1",
            "chapter_uid": "konosuba-manga-v02-ch06", "chapter_id": "ch01"})
        self._write(work, "script-audit.json", {
            "schema": "script-audit/v2",
            "chapter_uid": "konosuba-manga-v02-ch06"})
        errors, warnings = check_work_identity(work, authority=False)
        self.assertEqual(errors, [])
        self.assertTrue(any("script.json" in w for w in warnings) or not warnings)

    def test_counter_example_from_review(self):
        """目录 ch06 / chapter.json ch01 / novel_ref 说 A / script-audit 说 B → 必须报错。"""
        work = self._work("ch06")
        self._write(work, "chapter.json", chapter())          # uid A: ...-v02-ch06
        self._write(work, "novel_ref.json", {
            "schema": "novel-ref/v1",
            "chapter_uid": "konosuba-manga-v02-ch07",          # uid B
            "chapter_id": "ch02"})
        self._write(work, "script-audit.json", {
            "schema": "script-audit/v2",
            "chapter_uid": "konosuba-manga-v02-ch08"})         # uid C
        errors, _ = check_work_identity(work, authority=False)
        joined = " | ".join(errors)
        self.assertIn("novel_ref.json", joined)
        self.assertIn("script-audit.json", joined)
        self.assertIn("konosuba-manga-v02-ch07", joined)
        self.assertIn("konosuba-manga-v02-ch08", joined)
        self.assertIn("konosuba-manga-v02-ch06", joined)       # 基准值也要列出来

    def test_directory_name_means_global_number(self):
        """目录 `ch06` 指全书第 6 章，不是卷内第 1 章。"""
        work = self._work("ch06")
        self._write(work, "chapter.json", chapter(global_chapter_number=7,
                                                  chapter_uid="konosuba-manga-v02-ch07"))
        errors, _ = check_work_identity(work, authority=False)
        self.assertTrue(any("目录名" in e for e in errors), errors)

    def test_parent_directory_is_checked_for_work_layout(self):
        """真实布局是 `m1/v2/ch06/work`——章号在上一层，`work` 自己不算。"""
        work = self._work("ch09") / "work"
        work.mkdir()
        self._write(work, "chapter.json", chapter())   # 全书第 6 章
        errors, _ = check_work_identity(work, authority=False)
        self.assertTrue(any("ch09" in e and "global_chapter_number=6" in e
                            for e in errors), errors)

    def test_missing_uid_is_an_error_not_a_warning(self):
        work = self._work()
        doc = chapter()
        doc.pop("chapter_uid")
        self._write(work, "chapter.json", doc)
        errors, _ = check_work_identity(work, authority=False)
        self.assertTrue(any("chapter_uid" in e for e in errors), errors)

    def test_v1_script_without_chapter_is_only_a_warning(self):
        """v1 讲稿没有章节声明——记下来，但不该因此判整章不可用。"""
        work = self._work()
        self._write(work, "chapter.json", chapter())
        self._write(work, "script.json", {"segments": []})
        errors, warnings = check_work_identity(work, authority=False)
        self.assertEqual(errors, [])
        self.assertTrue(any("script.json" in w for w in warnings), warnings)

    def test_missing_chapter_json_is_an_error(self):
        work = self._work()
        errors, _ = check_work_identity(work, authority=False)
        self.assertTrue(any("chapter.json" in e for e in errors), errors)


class TestBuildIndex(unittest.TestCase):
    ROWS = [{"page": i, "ink": 0.5, "ink_dark": 0.1} for i in range(1, 21)]

    def test_uid_is_emitted_when_slug_and_volume_given(self):
        labels = {"series": "为美好的世界献上祝福！", "volume": "漫画 第2卷",
                  "series_slug": "konosuba-manga", "volume_number": 2,
                  "chapters": [{"number": "第六章", "title": "湖", "start_page": 3},
                               {"number": "第七章", "title": "竹笋", "start_page": 10}]}
        idx = build_index(self.ROWS, labels=labels)
        self.assertEqual(idx["series_slug"], "konosuba-manga")
        self.assertEqual(idx["volume_number"], 2)
        self.assertEqual([c["chapter_uid"] for c in idx["chapters"]],
                         ["konosuba-manga-v02-ch06", "konosuba-manga-v02-ch07"])
        self.assertEqual([c["global_chapter_number"] for c in idx["chapters"]], [6, 7])
        self.assertEqual([c["volume_chapter_number"] for c in idx["chapters"]], [1, 2])
        self.assertEqual(index_problems(idx), [])

    def test_without_slug_no_uid_is_invented(self):
        """没有 slug 就不写 uid——编一个出来会让人误以为身份已统一。"""
        labels = {"chapters": [{"number": "第一章", "start_page": 3}]}
        idx = build_index(self.ROWS, labels=labels)
        self.assertNotIn("chapter_uid", idx["chapters"][0])

    def test_build_chapter_work_carries_identity(self):
        labels = {"series": "为美好的世界献上祝福！", "volume": "漫画 第2卷",
                  "series_slug": "konosuba-manga", "volume_number": 2,
                  "chapters": [{"number": "第六章", "title": "湖", "start_page": 3}]}
        idx = build_index(self.ROWS, labels=labels)
        src = self._src_work()
        out = Path(tempfile.mkdtemp()) / "ch06"
        doc, _stats, _path = build_chapter_work(src, idx, "konosuba-manga-v02-ch06", out)
        self.assertEqual(doc["chapter_uid"], "konosuba-manga-v02-ch06")
        self.assertEqual(doc["global_chapter_number"], 6)
        self.assertEqual(doc["series_slug"], "konosuba-manga")

    def _src_work(self):
        src = Path(tempfile.mkdtemp()) / "src"
        (src / "pages").mkdir(parents=True)
        for i in range(1, 21):
            (src / "pages" / f"page_{i:04d}.jpg").write_bytes(b"x")
        return src


class TestIdentityMatrix(unittest.TestCase):
    """七类局部错配，逐类拒绝。

    只有 `test_counter_example_from_review` 那一个"五处全冲突"的反例不够：
    真实迁移里更常见的是**只错一处**，而其余四处看起来完全合理。
    这里每一类都只破坏一对关系，验证校验器不会因为"其他地方都对"就放过。

    基线布局：`tmp/ch06/work/`，权威表 `tmp/chapter_index.json`，
    五份文件全部自称 `konosuba-manga-v02-ch06`。
    """

    UID = "konosuba-manga-v02-ch06"
    OTHER = "konosuba-manga-v02-ch07"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root / "ch06" / "work"
        self.work.mkdir(parents=True)
        self._write(self.work, "chapter.json", chapter())
        self._write(self.work, "novel_ref.json", {
            "schema": "novel-ref/v1",
            "chapter_uid": self.UID, "chapter_id": "ch01"})
        self._write(self.work, "script.json", {
            "schema": "script/v2", "chapter_uid": self.UID, "segments": []})
        self._write(self.work, "script-audit.json", {
            "schema": "script-audit/v2", "chapter_uid": self.UID})
        self._write(self.root, "chapter_index.json", index_of(chapter()))

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, folder, name, doc):
        (folder / name).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _set_uid(self, name, uid):
        path = self.work / name
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["chapter_uid"] = uid
        self._write(self.work, name, doc)

    def _errors(self, work=None):
        errors, warnings = check_work_identity(work or self.work)
        return errors, warnings, " | ".join(errors)

    def test_00_baseline_is_clean(self):
        """先证明基线本身干净，否则后面每一条都可能是假阳性。"""
        errors, warnings, joined = self._errors()
        self.assertEqual(errors, [], joined)
        self.assertEqual(warnings, [], warnings)

    def test_01_workspace_disagrees_with_chapter_json(self):
        """工作区目录名 ch07，chapter.json 说全书第 6 章。"""
        (self.root / "ch06").rename(self.root / "ch07")
        errors, _warnings, joined = self._errors(self.root / "ch07" / "work")
        self.assertTrue(errors, "目录名错配必须拒绝")
        self.assertIn("目录名", joined)
        self.assertIn("ch07", joined)

    def test_02_chapter_json_disagrees_with_novel_ref(self):
        self._set_uid("novel_ref.json", self.OTHER)
        errors, _warnings, joined = self._errors()
        self.assertTrue(errors)
        self.assertIn("novel_ref.json", joined)
        self.assertIn(self.OTHER, joined)

    def test_03_novel_ref_disagrees_with_script(self):
        """novel_ref 说 ch06、script 说 ch07，其余三处都对。"""
        self._set_uid("script.json", self.OTHER)
        errors, _warnings, joined = self._errors()
        self.assertTrue(errors)
        self.assertIn("script.json", joined)
        self.assertIn("身份来源互相矛盾", joined)

    def test_03b_pairwise_conflict_caught_even_without_baseline_uid(self):
        """关键变体：chapter.json 缺 uid 时逐项比对整轮空转，两两比对仍须抓到。

        这正是"只测一个完整反例"会漏掉的场景。
        """
        path = self.work / "chapter.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.pop("chapter_uid")
        self._write(self.work, "chapter.json", doc)
        self._set_uid("script.json", self.OTHER)
        _errors, _warnings, joined = self._errors()
        self.assertIn("身份来源互相矛盾", joined,
                      "基准 uid 缺失时，novel_ref 与 script 的冲突不能被忽略")
        self.assertIn(self.UID, joined)
        self.assertIn(self.OTHER, joined)

    def test_04_script_disagrees_with_script_audit(self):
        self._set_uid("script-audit.json", self.OTHER)
        errors, _warnings, joined = self._errors()
        self.assertTrue(errors)
        self.assertIn("script-audit.json", joined)
        self.assertIn("身份来源互相矛盾", joined)

    def test_05_all_five_agree_but_uid_not_in_authority(self):
        """五处一致地抄了同一个不存在的章号——自洽但不在权威表。"""
        orphan_uid = "konosuba-manga-v02-ch08"
        self._write(self.work, "chapter.json",
                    chapter(orphan_uid, global_chapter_number=8, number="第八章"))
        for name in ("novel_ref.json", "script.json", "script-audit.json"):
            self._set_uid(name, orphan_uid)
        (self.root / "ch06").rename(self.root / "ch08")
        errors, _warnings, joined = self._errors(self.root / "ch08" / "work")
        self.assertTrue(errors, "权威表里没有的 uid 必须拒绝")
        self.assertIn("不在权威章节映射表", joined)
        self.assertIn(orphan_uid, joined)

    def test_06_missing_uid_is_rejected(self):
        """身份绑定文件缺 uid 一律拒绝；v1 script.json 是唯一已知例外。"""
        for name in ("chapter.json", "novel_ref.json", "script-audit.json"):
            with self.subTest(file=name):
                path = self.work / name
                raw = path.read_text(encoding="utf-8")
                doc = json.loads(raw)
                doc.pop("chapter_uid", None)
                self._write(self.work, name, doc)
                errors, _warnings, joined = self._errors()
                self.assertTrue(any(name in e and "chapter_uid" in e for e in errors),
                                joined)
                path.write_text(raw, encoding="utf-8")  # 还原，避免污染下一个子用例

        path = self.work / "script.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc.pop("chapter_uid")
        self._write(self.work, "script.json", doc)
        errors, warnings, joined = self._errors()
        self.assertEqual(errors, [], joined)
        self.assertTrue(any("script.json" in w for w in warnings), warnings)

    def test_07_duplicate_uid_in_authority_is_rejected(self):
        """权威表里同一个 uid 出现两次：身份不唯一，查找必然歧义。"""
        self._write(self.root, "chapter_index.json",
                    index_of(chapter(), chapter(self.UID)))
        errors, _warnings, joined = self._errors()
        self.assertTrue(errors)
        self.assertIn("重复", joined)
        self.assertIn(self.UID, joined)

    def test_08_cli_verify_rejects_orphan_uid(self):
        """拒绝路径真的接入 CLI——不只是函数级测试。"""
        orphan_uid = "konosuba-manga-v02-ch08"
        self._write(self.work, "chapter.json",
                    chapter(orphan_uid, global_chapter_number=8, number="第八章"))
        for name in ("novel_ref.json", "script.json", "script-audit.json"):
            self._set_uid(name, orphan_uid)
        (self.root / "ch06").rename(self.root / "ch08")
        work = self.root / "ch08" / "work"

        r = subprocess.run(
            [sys.executable, "-m", "panelcast", "m1", "chapter",
             "--verify", "--work", str(work)],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, f"stderr={r.stderr}\nstdout={r.stdout}")
        self.assertIn("权威章节映射表", r.stderr)
        self.assertIn(orphan_uid, r.stderr)


class TestFailClosed(unittest.TestCase):
    """P0-REVIEW-07：身份校验必须 fail-closed。

    这几条针对的都是"静默放行"：权威表缺失、文件损坏、索引自身不合格，
    以前都可能被当成"没问题"。审核意见要求全部拒绝，且只留一个显式逃生口。
    """

    UID = "konosuba-manga-v02-ch06"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, folder, name, doc):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _work(self, name="ch06"):
        work = self.root / name / "work"
        work.mkdir(parents=True)
        self._write(work, "chapter.json", chapter())
        return work

    def _joined(self, work, **kw):
        errors, _warnings = check_work_identity(work, **kw)
        return " | ".join(errors)

    def test_missing_authority_table_is_rejected(self):
        """authority=None 且根本找不到索引 —— 必须报错，不能静默放行。"""
        joined = self._joined(self._work())
        self.assertIn("找不到权威章节映射表", joined)

    def test_corrupt_authority_table_is_rejected(self):
        work = self._work()
        (self.root / "chapter_index.json").write_text("{broken", encoding="utf-8")
        self.assertIn("无法解析", self._joined(work))

    def test_empty_authority_table_is_rejected(self):
        work = self._work()
        self._write(self.root, "chapter_index.json",
                    {"series_slug": "konosuba-manga", "volume_number": 2,
                     "chapters": []})
        joined = self._joined(work)
        self.assertIn("权威索引自身不合格", joined)
        self.assertIn("为空", joined)

    def test_corrupt_chapter_json_is_not_treated_as_missing(self):
        work = self._work()
        (work / "chapter.json").write_text("{broken", encoding="utf-8")
        joined = self._joined(work, authority=False)
        self.assertIn("chapter.json 存在但不是合法 JSON", joined)

    def test_corrupt_novel_ref_is_rejected(self):
        """损坏的 novel_ref 以前被当成不存在而跳过——现在必须报错。"""
        work = self._work()
        self._write(self.root, "chapter_index.json", index_of(chapter()))
        self._write(work, "novel_ref.json", {"chapter_uid": self.UID})
        (work / "novel_ref.json").write_text("{broken", encoding="utf-8")
        self.assertIn("novel_ref.json 存在但不是合法 JSON", self._joined(work))

    def test_chapter_level_validates_the_whole_authority_index(self):
        """当前章完全正确，但索引里另一章重复 id —— 章级也必须拒绝。"""
        work = self._work()
        self._write(self.root, "chapter_index.json",
                    index_of(chapter(), chapter(self.UID)))
        self.assertIn("权威索引自身不合格", self._joined(work))

    def test_real_layout_finds_volume_index(self):
        """真实布局 `v2/ch06/work` 的索引在 `v2/work/chapter_index.json`。

        旧实现只找 `work.parent` / `work.parent.parent`（= `v2/ch06` / `v2`），
        两个都不对——所以真实仓库的章级校验从来没加载过权威表，
        "正常路径通过"其实是"根本没校验就通过"。
        """
        work = self.root / "v2" / "ch06" / "work"
        work.mkdir(parents=True)
        self._write(work, "chapter.json", chapter())
        self._write(self.root / "v2" / "work", "chapter_index.json",
                    index_of(chapter()))
        errors, _warnings = check_work_identity(work)
        self.assertEqual(errors, [], " | ".join(errors))

    def test_explicit_false_is_the_only_escape(self):
        """显式 authority=False 是唯一允许跳过权威表的入口。"""
        errors, _warnings = check_work_identity(self._work(), authority=False)
        self.assertEqual(errors, [])

    def test_cli_rejects_missing_authority_table(self):
        work = self._work()
        r = subprocess.run(
            [sys.executable, "-m", "panelcast", "m1", "chapter",
             "--verify", "--work", str(work)],
            cwd=str(ROOT), capture_output=True, text=True)
        self.assertEqual(r.returncode, 3, f"stderr={r.stderr}")
        self.assertIn("找不到权威章节映射表", r.stderr)


if __name__ == "__main__":
    unittest.main()
