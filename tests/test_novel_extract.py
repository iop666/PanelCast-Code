"""S1' 小说纯文本化测试（tools/novel_extract.py）。

用内存里现造的迷你 epub 测，不依赖仓库外的素材。
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from novel_extract import extract, main  # noqa: E402


def make_epub(path, files):
    """files: {arcname: xhtml 文本}"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        for name, body in files.items():
            z.writestr(name, body)


def xhtml(*paras):
    inner = "".join(f"<p>{p}</p>" for p in paras)
    return f'<?xml version="1.0"?><html><body>{inner}</body></html>'


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _epub(self, files):
        p = self.dir / "t.epub"
        make_epub(p, files)
        return p

    def test_paragraph_numbers_are_global(self):
        p = self._epub({
            "OEBPS/Text/chapter00.xhtml": xhtml("序章", "一", "二"),
            "OEBPS/Text/chapter01.xhtml": xhtml("第一章", "三", "四"),
        })
        text, idx = extract(p)
        self.assertEqual(text.splitlines(), ["序章", "一", "二", "第一章", "三", "四"])
        self.assertEqual(idx["total_paras"], 6)
        self.assertEqual([c["para_from"] for c in idx["chapters"]], [0, 3])
        self.assertEqual([c["para_to"] for c in idx["chapters"]], [2, 5])

    def test_non_body_files_are_excluded(self):
        p = self._epub({
            "OEBPS/Text/chapter01.xhtml": xhtml("第一章", "正文"),
            "OEBPS/Text/Houji.xhtml": xhtml("后记", "不该进来"),
            "OEBPS/Text/Message.xhtml": xhtml("转载信息"),
            "OEBPS/Text/colorpages01.xhtml": xhtml("彩页"),
        })
        text, idx = extract(p)
        self.assertEqual(text.splitlines(), ["第一章", "正文"])
        self.assertEqual([c["file"] for c in idx["chapters"]], ["chapter01.xhtml"])

    def test_chars_exclude_newlines(self):
        p = self._epub({"OEBPS/Text/chapter01.xhtml": xhtml("abc", "de")})
        _, idx = extract(p)
        self.assertEqual(idx["total_chars"], 5)          # 3 + 2，不含换行
        self.assertEqual(idx["chapters"][0]["chars"], 5)

    def test_html_entities_and_br(self):
        p = self._epub({
            "OEBPS/Text/chapter01.xhtml":
                "<html><body><p>a&amp;b</p><p>x<br/>y</p></body></html>"
        })
        text, _ = extract(p)
        self.assertEqual(text.splitlines(), ["a&b", "x", "y"])

    def test_script_and_style_are_stripped(self):
        p = self._epub({
            "OEBPS/Text/chapter01.xhtml":
                "<html><head><style>p{color:red}</style></head>"
                "<body><script>var a=1;</script><p>只有这句</p></body></html>"
        })
        text, _ = extract(p)
        self.assertEqual(text.splitlines(), ["只有这句"])

    def test_empty_paragraphs_dropped(self):
        p = self._epub({
            "OEBPS/Text/chapter01.xhtml": "<html><body><p>a</p><p>  </p><p></p><p>b</p></body></html>"
        })
        text, _ = extract(p)
        self.assertEqual(text.splitlines(), ["a", "b"])

    def test_no_chapter_file_raises(self):
        p = self._epub({"OEBPS/Text/Houji.xhtml": xhtml("后记")})
        with self.assertRaises(RuntimeError) as ctx:
            extract(p)
        self.assertIn("no chapter", str(ctx.exception))

    def test_sha256_is_stable_and_content_sensitive(self):
        a = self._epub({"OEBPS/Text/chapter01.xhtml": xhtml("甲", "乙")})
        _, i1 = extract(a)
        _, i2 = extract(a)
        self.assertEqual(i1["sha256"], i2["sha256"])

        b = self.dir / "b.epub"
        make_epub(b, {"OEBPS/Text/chapter01.xhtml": xhtml("甲", "丙")})
        _, i3 = extract(b)
        self.assertNotEqual(i1["sha256"], i3["sha256"])

    def test_file_sha256_matches_written_bytes(self):
        """file_sha256 必须等于落盘文件的字节哈希 —— 这是 novel_ref 校验的依据。"""
        import hashlib
        epub = self.dir / "1.epub"
        make_epub(epub, {"OEBPS/Text/chapter01.xhtml": xhtml("第一章", "正文")})
        out = self.dir / "text"
        self.assertEqual(main(["--epub", str(epub), "--out", str(out)]), 0)
        idx = json.loads((out / "novel_index.json").read_text(encoding="utf-8"))
        actual = hashlib.sha256((out / "novel.txt").read_bytes()).hexdigest()
        self.assertEqual(idx["file_sha256"], actual)

    def test_file_sha256_differs_from_content_sha256(self):
        """两个哈希含义不同：内容哈希不含尾部换行，文件哈希含。不能混用。"""
        epub = self.dir / "1.epub"
        make_epub(epub, {"OEBPS/Text/chapter01.xhtml": xhtml("甲")})
        _, idx = extract(epub)
        self.assertNotEqual(idx["sha256"], idx["file_sha256"])

    def test_novel_txt_is_lf_only(self):
        """强制 LF，否则 Windows 上 \n 会被翻成 \r\n，哈希跨平台不一致。"""
        epub = self.dir / "1.epub"
        make_epub(epub, {"OEBPS/Text/chapter01.xhtml": xhtml("甲", "乙")})
        out = self.dir / "text"
        main(["--epub", str(epub), "--out", str(out)])
        raw = (out / "novel.txt").read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertTrue(raw.endswith(b"\n"))


class TestMain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_writes_both_files(self):
        epub = self.dir / "1.epub"
        make_epub(epub, {"OEBPS/Text/chapter01.xhtml": xhtml("第一章", "正文")})
        out = self.dir / "text"
        code = main(["--epub", str(epub), "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertTrue((out / "novel.txt").exists())
        idx = json.loads((out / "novel_index.json").read_text(encoding="utf-8"))
        self.assertEqual(idx["schema"], "novel-index/v1")
        self.assertEqual(idx["source_file"], "1.epub")
        self.assertEqual((out / "novel.txt").read_text(encoding="utf-8"),
                         "第一章\n正文\n")

    def test_missing_epub_exits_4(self):
        code = main(["--epub", str(self.dir / "nope.epub"), "--out", str(self.dir / "o")])
        self.assertEqual(code, 4)

    def test_no_body_exits_3(self):
        epub = self.dir / "x.epub"
        make_epub(epub, {"OEBPS/Text/Houji.xhtml": xhtml("后记")})
        code = main(["--epub", str(epub), "--out", str(self.dir / "o")])
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
