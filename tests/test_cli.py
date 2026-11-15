"""End-to-end CLI tests for `panelcast ingest` (synthetic inputs only)."""

import contextlib
import io
import json
import struct
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from panelcast.__main__ import main

CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF_TEMPLATE = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>TestBook</dc:title>
    <dc:language>ja</dc:language>
  </metadata>
  <manifest>{manifest}</manifest>
  <spine>{spine}</spine>
</package>"""

CHAPTERS = ("chapter00.xhtml", "chapter01.xhtml")


def _minimal_jpeg(width, height):
    sof = struct.pack(">BHHB", 0xC0, height, width, 3)
    body = b"\xff\xda" + struct.pack(">H", 4) + b"\x00"
    return (
        b"\xff\xd8\xff"
        + b"\xff" + bytes([0xC0]) + struct.pack(">H", len(sof) + 2) + sof
        + body + b"\xff\xd9"
    )


def _build_pdb(records):
    num = len(records)
    header_len = 78 + num * 8
    data = bytearray(b"\x00" * 32)  # name
    data += b"\x00" * 28  # attributes/version/dates/etc
    data += b"BOOK" + b"MOBI"
    data += b"\x00" * 8  # uniqueIDseed + nextRecordList
    data += struct.pack(">H", num)
    offset = header_len
    for rec in records:
        data += struct.pack(">I", offset) + b"\x00\x00" + struct.pack(">H", num - 1)
        offset += len(rec)
    for rec in records:
        data += rec
    return bytes(data)


def _build_epub(path):
    manifest_items = "".join(
        f'<item id="{c}" href="Text/{c}" media-type="application/xhtml+xml"/>'
        for c in CHAPTERS
    )
    spine_items = "".join(f'<itemref idref="{c}"/>' for c in CHAPTERS)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr(
            "OEBPS/content.opf",
            OPF_TEMPLATE.format(manifest=manifest_items, spine=spine_items),
        )
        for c in CHAPTERS:
            z.writestr(
                f"OEBPS/Text/{c}",
                f"<html><head><title>{c}</title></head><body><p>text {c}</p></body></html>",
            )


def _build_epub_with_spine(path, chapter_ids):
    """Valid EPUB with an arbitrary spine (empty-ingest guard fixtures)."""
    manifest_items = "".join(
        f'<item id="{c}" href="Text/{c}" media-type="application/xhtml+xml"/>'
        for c in chapter_ids
    )
    spine_items = "".join(f'<itemref idref="{c}"/>' for c in chapter_ids)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr(
            "OEBPS/content.opf",
            OPF_TEMPLATE.format(manifest=manifest_items, spine=spine_items),
        )
        for c in chapter_ids:
            z.writestr(
                f"OEBPS/Text/{c}",
                f"<html><head><title>{c}</title></head><body><p>text {c}</p></body></html>",
            )


class TestIngestCli(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        self.out = self.workspace / "out"
        self.epub = self.workspace / "book.epub"
        _build_epub(self.epub)
        img_a, img_b = _minimal_jpeg(100, 200), _minimal_jpeg(300, 400)
        self.mobi = self.workspace / "book.mobi"
        self.mobi.write_bytes(_build_pdb([img_a, img_a, img_b]))

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *argv):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                main(list(argv))
        return cm.exception.code, stderr.getvalue()

    def manifest(self):
        return json.loads(
            (self.out / "source_manifest.json").read_text(encoding="utf-8")
        )

    def test_both_types(self):
        code, _ = self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))
        self.assertEqual(code, 0)

        m = self.manifest()
        self.assertEqual(m["schema_version"], 1)
        self.assertIn("extractor_version", m)
        self.assertIn("created_at", m)
        self.assertEqual(m["reading_direction"], "rtl")
        self.assertEqual(m["language"], "ja")
        self.assertEqual(m["chapter_count"], 2)
        self.assertEqual(m["page_count"], 3)
        self.assertEqual(m["unique_page_count"], 2)

        self.assertEqual(sorted(f["role"] for f in m["source_files"]), ["epub", "mobi"])
        self.assertEqual(len(m["epub"]["chapters"]), 2)
        self.assertEqual(len(m["mobi"]["pages"]), 3)
        self.assertEqual(m["mobi"]["pages"][1]["duplicate_of"], "page_0001.jpg")

        self.assertTrue((self.out / "epub" / "chapters.json").exists())
        self.assertEqual(len(list((self.out / "mobi" / "pages").glob("*.jpg"))), 3)

    def test_epub_only_writes_valid_manifest(self):
        code, _ = self.run_cli("ingest", str(self.epub), "-o", str(self.out))
        self.assertEqual(code, 0)

        m = self.manifest()
        self.assertIsNone(m["mobi"])
        self.assertIsNone(m["page_count"])
        self.assertIsNone(m["unique_page_count"])
        self.assertEqual(m["chapter_count"], 2)
        self.assertEqual([f["role"] for f in m["source_files"]], ["epub"])
        self.assertFalse((self.out / "mobi").exists())

    def test_mobi_only_writes_valid_manifest(self):
        code, _ = self.run_cli("ingest", str(self.mobi), "-o", str(self.out))
        self.assertEqual(code, 0)

        m = self.manifest()
        self.assertIsNone(m["epub"])
        self.assertIsNone(m["chapter_count"])
        self.assertIsNone(m["language"])
        self.assertEqual(m["page_count"], 3)
        self.assertEqual(m["unique_page_count"], 2)
        self.assertEqual([f["role"] for f in m["source_files"]], ["mobi"])
        self.assertFalse((self.out / "epub").exists())

    def test_multiple_same_type_rejected_before_writing(self):
        other = self.workspace / "other.epub"
        _build_epub(other)

        # A previous good run must survive a rejected run untouched.
        self.run_cli("ingest", str(self.epub), "-o", str(self.out))
        manifest_before = (self.out / "source_manifest.json").read_text(encoding="utf-8")
        chapters_before = (self.out / "epub" / "chapters.json").read_text(encoding="utf-8")

        code, err = self.run_cli(
            "ingest", str(self.epub), str(other), "-o", str(self.out)
        )
        self.assertEqual(code, 2)
        self.assertIn("EPUB", err)
        self.assertIn(str(other), err)
        self.assertEqual(
            (self.out / "source_manifest.json").read_text(encoding="utf-8"),
            manifest_before,
        )
        self.assertEqual(
            (self.out / "epub" / "chapters.json").read_text(encoding="utf-8"),
            chapters_before,
        )

    def test_multiple_mobi_rejected(self):
        other = self.workspace / "other.mobi"
        other.write_bytes(self.mobi.read_bytes())
        code, err = self.run_cli("ingest", str(self.mobi), str(other), "-o", str(self.out))
        self.assertEqual(code, 2)
        self.assertIn("MOBI", err)
        self.assertFalse((self.out / "source_manifest.json").exists())

    def test_created_at_preserved_across_runs(self):
        self.run_cli("ingest", str(self.epub), "-o", str(self.out))
        first = self.manifest()["created_at"]

        # Second run ingests a different pair of inputs; created_at stays.
        self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))
        self.assertEqual(self.manifest()["created_at"], first)

    def test_pair_then_epub_only_removes_old_mobi(self):
        self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))
        self.assertTrue((self.out / "mobi" / "pages" / "page_0001.jpg").exists())

        code, _ = self.run_cli("ingest", str(self.epub), "-o", str(self.out))
        self.assertEqual(code, 0)
        self.assertFalse((self.out / "mobi").exists())
        m = self.manifest()
        self.assertIsNone(m["mobi"])
        self.assertIsNone(m["page_count"])
        self.assertEqual(m["chapter_count"], 2)
        self.assertTrue((self.out / "epub" / "chapters.json").exists())
        # no staging residue after a successful run
        self.assertEqual(list(self.out.glob(".panelcast-stage-*")), [])

    def test_pair_then_mobi_only_removes_old_epub(self):
        self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))

        code, _ = self.run_cli("ingest", str(self.mobi), "-o", str(self.out))
        self.assertEqual(code, 0)
        self.assertFalse((self.out / "epub").exists())
        m = self.manifest()
        self.assertIsNone(m["epub"])
        self.assertIsNone(m["chapter_count"])
        self.assertEqual(m["page_count"], 3)
        self.assertEqual(len(list((self.out / "mobi" / "pages").glob("*.jpg"))), 3)

    def test_fewer_pages_removes_stale_jpegs(self):
        small = self.workspace / "small.mobi"
        small.write_bytes(_build_pdb([_minimal_jpeg(50, 60)]))
        self.run_cli("ingest", str(self.mobi), "-o", str(self.out))  # 3 pages on disk

        code, _ = self.run_cli("ingest", str(small), "-o", str(self.out))
        self.assertEqual(code, 0)
        pages = sorted(p.name for p in (self.out / "mobi" / "pages").glob("*.jpg"))
        self.assertEqual(pages, ["page_0001.jpg"])
        m = self.manifest()
        self.assertEqual(m["page_count"], 1)
        self.assertEqual(m["unique_page_count"], 1)
        # the surviving page is the new one, not a stale leftover
        self.assertEqual(m["mobi"]["pages"][0]["width"], 50)
        self.assertEqual(m["mobi"]["pages"][0]["height"], 60)

    def test_failed_run_preserves_previous_output(self):
        self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))
        manifest_before = (self.out / "source_manifest.json").read_bytes()
        chapters_before = (self.out / "epub" / "chapters.json").read_bytes()
        pages_before = {
            p.name: p.read_bytes()
            for p in (self.out / "mobi" / "pages").glob("*.jpg")
        }

        bad = self.workspace / "bad.mobi"
        bad.write_bytes(b"\x00" * 8)  # fails the PDB header check
        code, _ = self.run_cli("ingest", str(self.epub), str(bad), "-o", str(self.out))
        self.assertEqual(code, 4)

        self.assertEqual(
            (self.out / "source_manifest.json").read_bytes(), manifest_before
        )
        self.assertEqual(
            (self.out / "epub" / "chapters.json").read_bytes(), chapters_before
        )
        pages_after = {
            p.name: p.read_bytes()
            for p in (self.out / "mobi" / "pages").glob("*.jpg")
        }
        self.assertEqual(pages_after, pages_before)
        self.assertEqual(list(self.out.glob(".panelcast-stage-*")), [])

    def test_failed_epub_only_run_keeps_everything(self):
        # No delete-before-fail: an EPUB-only run that fails must not remove
        # the old mobi/ subtree it would have dropped after committing.
        self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))
        bad = self.workspace / "bad.epub"
        bad.write_bytes(b"not a zip")
        code, _ = self.run_cli("ingest", str(bad), "-o", str(self.out))
        self.assertEqual(code, 4)

        self.assertTrue((self.out / "epub" / "chapters.json").exists())
        self.assertTrue((self.out / "mobi" / "pages" / "page_0001.jpg").exists())
        self.assertEqual(self.manifest()["page_count"], 3)

    def test_epub_without_known_chapters_exits_3(self):
        empty = self.workspace / "empty.epub"
        _build_epub_with_spine(empty, ("cover.xhtml",))

        code, err = self.run_cli("ingest", str(empty), "-o", str(self.out))
        self.assertEqual(code, 3)
        self.assertIn("error:", err)
        self.assertIn("empty.epub", err)
        self.assertFalse((self.out / "source_manifest.json").exists())

    def test_mobi_without_jpeg_pages_exits_3(self):
        empty = self.workspace / "empty.mobi"
        empty.write_bytes(_build_pdb([b"A" * 10]))  # valid PDB, no JPEG inside

        code, err = self.run_cli("ingest", str(empty), "-o", str(self.out))
        self.assertEqual(code, 3)
        self.assertIn("error:", err)
        self.assertFalse((self.out / "source_manifest.json").exists())
        # guard fired before any disk write: no mobi/ subtree was staged
        self.assertFalse((self.out / "mobi").exists())

    def test_empty_ingestion_keeps_previous_output(self):
        self.run_cli("ingest", str(self.epub), str(self.mobi), "-o", str(self.out))
        manifest_before = (self.out / "source_manifest.json").read_bytes()
        chapters_before = (self.out / "epub" / "chapters.json").read_bytes()
        pages_before = {
            p.name: p.read_bytes()
            for p in (self.out / "mobi" / "pages").glob("*.jpg")
        }

        empty = self.workspace / "empty.epub"
        _build_epub_with_spine(empty, ("cover.xhtml",))
        code, err = self.run_cli("ingest", str(empty), "-o", str(self.out))
        self.assertEqual(code, 3)
        self.assertIn("error:", err)

        self.assertEqual(
            (self.out / "source_manifest.json").read_bytes(), manifest_before
        )
        self.assertEqual(
            (self.out / "epub" / "chapters.json").read_bytes(), chapters_before
        )
        pages_after = {
            p.name: p.read_bytes()
            for p in (self.out / "mobi" / "pages").glob("*.jpg")
        }
        self.assertEqual(pages_after, pages_before)

    def test_corrupt_epub_reports_clean_error(self):
        bad = self.workspace / "bad.epub"
        bad.write_bytes(b"not a zip")

        code, err = self.run_cli("ingest", str(bad), "-o", str(self.out))
        self.assertEqual(code, 4)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_corrupt_mobi_reports_clean_error(self):
        bad = self.workspace / "bad.mobi"
        bad.write_bytes(b"\x00" * 8)

        code, err = self.run_cli("ingest", str(bad), "-o", str(self.out))
        self.assertEqual(code, 4)
        self.assertIn("error:", err)
        self.assertNotIn("Traceback", err)

    def test_failure_leaves_no_staging_residue(self):
        bad = self.workspace / "bad.mobi"
        bad.write_bytes(b"\x00" * 8)
        code, _ = self.run_cli("ingest", str(bad), "-o", str(self.out))  # exit 4 path
        self.assertEqual(code, 4)

        empty = self.workspace / "empty.epub"
        _build_epub_with_spine(empty, ("cover.xhtml",))
        code, _ = self.run_cli("ingest", str(empty), "-o", str(self.out))  # exit 3 path
        self.assertEqual(code, 3)

        self.assertEqual(list(self.out.glob(".panelcast-stage-*")), [])


if __name__ == "__main__":
    unittest.main()
