import struct
import unittest
from pathlib import Path

from panelcast.jpeg import jpeg_dimensions
from panelcast.mobi_ingest import ingest_mobi, pdb_record_offsets, scan_jpeg_pages

WORKSPACE = Path(__file__).resolve().parent.parent
MOBI = WORKSPACE / "この素晴らしい世界に祝福を！" / "1卷.mobi"


def _minimal_jpeg(width, height, payload=b"\x00" * 8):
    """Smallest plausible JPEG: SOI, SOF0, arbitrary payload, EOI."""
    sof = struct.pack(">BHHB", 0xC0, height, width, 3)  # marker body
    body = b"\xff\xda" + struct.pack(">H", 4) + b"\x00"  # dummy SOS
    return b"\xff\xd8\xff" + b"\xff" + bytes([0xC0]) + struct.pack(">H", len(sof) + 2) + sof + body + b"\xff\xd9"


def _build_pdb(records):
    """Build a minimal PDB header + records (BOOK/MOBI)."""
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


class TestJpegDimensions(unittest.TestCase):
    def test_sof0(self):
        self.assertEqual(jpeg_dimensions(_minimal_jpeg(800, 1200)), (800, 1200))

    def test_sof2_progressive(self):
        img = _minimal_jpeg(640, 480)
        img = img[:4] + b"\xc2" + img[5:]  # swap SOF0 -> SOF2
        self.assertEqual(jpeg_dimensions(img), (640, 480))

    def test_bad_data_raises(self):
        with self.assertRaises(ValueError):
            jpeg_dimensions(b"\x00\x01\x02")


class TestPdbScanning(unittest.TestCase):
    def test_record_offsets(self):
        recs = [b"A" * 10, b"B" * 5, b"C"]
        data = _build_pdb(recs)
        offs = pdb_record_offsets(data)
        self.assertEqual([(i, e - s) for i, s, e in offs],
                         [(0, 10), (1, 5), (2, 1)])

    def test_bad_type_rejected(self):
        data = bytearray(_build_pdb([b"A" * 10]))
        data[60:64] = b"TEXt"
        with self.assertRaises(ValueError):
            pdb_record_offsets(bytes(data))

    def test_bad_creator_rejected(self):
        data = bytearray(_build_pdb([b"A" * 10]))
        data[64:68] = b"JAVA"
        with self.assertRaises(ValueError):
            pdb_record_offsets(bytes(data))

    def test_scan_jpeg_pages_with_duplicate(self):
        img_a = _minimal_jpeg(100, 200)
        img_b = _minimal_jpeg(300, 400)
        data = _build_pdb([img_a, img_a, img_b])  # record 1 duplicates record 0
        pages = scan_jpeg_pages(data)
        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[0]["file"], "page_0001.jpg")
        self.assertEqual(pages[2]["width"], 300)
        self.assertEqual(pages[1]["duplicate_of"], "page_0001.jpg")
        self.assertIsNone(pages[2]["duplicate_of"])
        self.assertEqual(pages[0]["sha256"], pages[1]["sha256"])
        # duplicates are kept, not dropped
        self.assertEqual([p["pdb_record"] for p in pages], [0, 1, 2])


class TestMobiIngest(unittest.TestCase):
    @unittest.skipUnless(MOBI.exists(), "real MOBI not present")
    def test_real_mobi_169_pages(self):
        import json
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            pages, json_path = ingest_mobi(MOBI, Path(tmp))
            self.assertEqual(len(pages), 169)
            self.assertEqual(pages[0]["file"], "page_0001.jpg")
            self.assertEqual(pages[-1]["file"], "page_0169.jpg")
            on_disk = sorted((Path(tmp) / "pages").glob("*.jpg"))
            self.assertEqual(len(on_disk), 169)
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 169)
            for p in saved:
                self.assertGreater(p["width"], 0)
                self.assertGreater(p["height"], 0)


if __name__ == "__main__":
    unittest.main()
