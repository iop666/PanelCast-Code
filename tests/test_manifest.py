import hashlib
import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from panelcast import __version__
from panelcast.manifest import SCHEMA_VERSION, build_manifest, write_manifest


def _chapter(i):
    return {
        "id": f"chapter{i:02d}.xhtml",
        "order": i,
        "title": f"ch{i}",
        "char_count": 10 + i,
        "source_entry": f"OEBPS/Text/chapter{i:02d}.xhtml",
        "sha256": f"hash{i}",
    }


def _page(i, duplicate_of=None):
    return {
        "page": i + 1,
        "file": f"page_{i + 1:04d}.jpg",
        "pdb_record": i,
        "width": 800,
        "height": 1200,
        "sha256": f"img{i}",
        "duplicate_of": duplicate_of,
    }


class TestBuildManifest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.epub_file = self.tmp / "book.epub"
        self.epub_file.write_bytes(b"epub-payload")
        self.mobi_file = self.tmp / "book.mobi"
        self.mobi_file.write_bytes(b"mobi-payload")

    def tearDown(self):
        self._tmp.cleanup()

    def test_both_inputs(self):
        epub_result = (self.epub_file, [_chapter(0), _chapter(1)])
        pages = [_page(0), _page(1, duplicate_of="page_0001.jpg"), _page(2)]
        mobi_result = (self.mobi_file, pages)

        m = build_manifest(epub_result, mobi_result, language="ja")

        self.assertEqual(m["schema_version"], SCHEMA_VERSION)
        self.assertEqual(m["extractor_version"], __version__)
        self.assertEqual(m["language"], "ja")
        self.assertEqual(m["reading_direction"], "rtl")
        self.assertEqual(m["chapter_count"], 2)
        self.assertEqual(m["page_count"], 3)
        self.assertEqual(m["unique_page_count"], 2)

        by_role = {f["role"]: f for f in m["source_files"]}
        self.assertEqual(set(by_role), {"epub", "mobi"})
        self.assertEqual(by_role["epub"]["path"], self.epub_file.as_posix())
        self.assertEqual(by_role["epub"]["bytes"], len(b"epub-payload"))
        self.assertEqual(
            by_role["epub"]["sha256"], hashlib.sha256(b"epub-payload").hexdigest()
        )
        self.assertEqual(by_role["mobi"]["bytes"], len(b"mobi-payload"))
        self.assertEqual(
            by_role["mobi"]["sha256"], hashlib.sha256(b"mobi-payload").hexdigest()
        )

        self.assertEqual(m["epub"]["input"], self.epub_file.as_posix())
        self.assertEqual(len(m["epub"]["chapters"]), 2)
        self.assertNotIn("text", m["epub"]["chapters"][0])  # 正文不进 manifest
        self.assertEqual(m["mobi"]["input"], self.mobi_file.as_posix())
        self.assertEqual(len(m["mobi"]["pages"]), 3)
        self.assertEqual(m["mobi"]["unique_pages"], 2)

    def test_epub_only(self):
        m = build_manifest((self.epub_file, [_chapter(0)]), None)
        self.assertIsNone(m["mobi"])
        self.assertIsNone(m["page_count"])
        self.assertIsNone(m["unique_page_count"])
        self.assertEqual(m["chapter_count"], 1)
        self.assertEqual([f["role"] for f in m["source_files"]], ["epub"])

    def test_mobi_only(self):
        m = build_manifest(None, (self.mobi_file, [_page(0)]), language=None)
        self.assertIsNone(m["epub"])
        self.assertIsNone(m["chapter_count"])
        self.assertIsNone(m["language"])
        self.assertEqual(m["page_count"], 1)
        self.assertEqual(m["unique_page_count"], 1)
        self.assertEqual([f["role"] for f in m["source_files"]], ["mobi"])


class TestWriteManifest(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.source_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _manifest(marker):
        return {"schema_version": SCHEMA_VERSION, "marker": marker}

    def test_created_at_written_once_and_preserved(self):
        first = write_manifest(self.source_dir, self._manifest("a"))
        m1 = json.loads(first.read_text(encoding="utf-8"))
        self.assertIn("created_at", m1)

        # Re-run with different content: created_at must survive unchanged.
        second = write_manifest(self.source_dir, self._manifest("b"))
        m2 = json.loads(second.read_text(encoding="utf-8"))
        self.assertEqual(m2["created_at"], m1["created_at"])
        self.assertEqual(m2["marker"], "b")

    def test_created_at_is_iso8601_utc(self):
        path = write_manifest(self.source_dir, self._manifest("a"))
        m = json.loads(path.read_text(encoding="utf-8"))
        dt = datetime.fromisoformat(m["created_at"])
        self.assertIsNotNone(dt.utcoffset())

    def test_corrupt_existing_manifest_gets_fresh_created_at(self):
        self.source_dir.mkdir(parents=True, exist_ok=True)
        (self.source_dir / "source_manifest.json").write_text("{not json", encoding="utf-8")
        path = write_manifest(self.source_dir, self._manifest("a"))
        m = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("created_at", m)
        self.assertEqual(m["marker"], "a")

    def test_output_is_valid_sorted_json(self):
        path = write_manifest(self.source_dir, self._manifest("a"))
        raw = path.read_text(encoding="utf-8")
        m = json.loads(raw)
        self.assertEqual(raw, json.dumps(m, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
