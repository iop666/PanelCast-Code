import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from panelcast.epub_ingest import _TextExtractor, extract_chapters, parse_opf

WORKSPACE = Path(__file__).resolve().parent.parent
EPUB = WORKSPACE / "この素晴らしい世界に祝福を！" / "1.epub"

SAMPLE_XHTML = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml">\n'
    "<head><title>\u5e8f\u7ae0</title></head>\n"
    "<body>\n"
    "<p>\u7b2c\u4e00\u6bb5\u6587\u5b57</p>\n"
    "<p><br /></p>\n"
    '<p>\u7b2c\u4e8c\u6bb5<img alt="x" src="../Images/pic012.jpg" />\u4e2d\u95f4\u6587\u5b57</p>\n'
    "</body>\n"
    "</html>"
).encode("utf-8")


def _build_epub(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        )
        z.writestr(
            "OEBPS/content.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>TestBook</dc:title><dc:language>ja</dc:language></metadata>
  <manifest>
    <item id="chapter00.xhtml" href="Text/chapter00.xhtml" media-type="application/xhtml+xml"/>
    <item id="chapter01.xhtml" href="Text/chapter01.xhtml" media-type="application/xhtml+xml"/>
    <item id="cover.xhtml" href="Text/cover.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="cover.xhtml"/>
    <itemref idref="chapter01.xhtml"/>
    <itemref idref="chapter00.xhtml"/>
  </spine>
</package>""",
        )
        z.writestr("OEBPS/Text/cover.xhtml", "<html><body><p>cover</p></body></html>")
        z.writestr("OEBPS/Text/chapter00.xhtml", SAMPLE_XHTML)
        z.writestr("OEBPS/Text/chapter01.xhtml", "<html><head><title>\u7b2c\u4e00\u7ae0</title></head><body><p>hello</p></body></html>")


class TestTextExtractor(unittest.TestCase):
    def test_paragraphs_joined_and_br_only_dropped(self):
        p = _TextExtractor()
        p.feed(SAMPLE_XHTML.decode("utf-8"))
        title, text = p.result()
        self.assertEqual(title, "\u5e8f\u7ae0")
        self.assertNotIn("\n\n", text)
        lines = text.split("\n")
        self.assertEqual(lines[0], "\u7b2c\u4e00\u6bb5\u6587\u5b57")
        # image tag contributes nothing; surrounding text kept
        self.assertEqual(lines[1], "\u7b2c\u4e8c\u6bb5\u4e2d\u95f4\u6587\u5b57")


class TestEpubParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = TemporaryDirectory()
        cls.epub_path = Path(cls._tmp.name) / "test.epub"
        _build_epub(cls.epub_path)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_spine_order_parsed(self):
        with zipfile.ZipFile(self.epub_path) as z:
            _, spine_ids, book_title, language, opf_path = parse_opf(z)
        self.assertEqual(spine_ids, ["cover.xhtml", "chapter01.xhtml", "chapter00.xhtml"])
        self.assertEqual(book_title, "TestBook")
        self.assertEqual(language, "ja")
        self.assertEqual(opf_path, "OEBPS/content.opf")

    def test_extract_chapters_order_and_fields(self):
        chapters, language = extract_chapters(self.epub_path)
        self.assertEqual([c["id"] for c in chapters],
                         ["chapter00.xhtml", "chapter01.xhtml"])
        first = chapters[0]
        for field in ("id", "order", "title", "text", "char_count",
                      "source_entry", "sha256"):
            self.assertIn(field, first)
        self.assertEqual(first["order"], 0)
        self.assertEqual(chapters[1]["order"], 1)
        self.assertEqual(first["char_count"], len(first["text"]))
        self.assertEqual(first["source_entry"], "OEBPS/Text/chapter00.xhtml")
        self.assertEqual(language, "ja")

    @unittest.skipUnless(EPUB.exists(), "real EPUB not present")
    def test_real_epub_six_chapters(self):
        chapters, _language = extract_chapters(EPUB)
        self.assertEqual([c["id"] for c in chapters],
                         [f"chapter{i:02d}.xhtml" for i in range(6)])
        self.assertTrue(all(c["char_count"] > 0 for c in chapters))
        self.assertTrue(all(c["sha256"] for c in chapters))


if __name__ == "__main__":
    unittest.main()
