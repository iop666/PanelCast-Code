"""MOBI ingestion: scan PDB records in order, extract JPEG pages."""

import json
import struct
from pathlib import Path

from .errors import IngestError
from .jpeg import EOI, SOI, iter_jpegs, jpeg_dimensions, sha256


def pdb_record_offsets(data: bytes):
    """Return list of (index, start, end) for each PDB record."""
    if data[60:64] != b"BOOK":
        raise ValueError("not a PDB file (bad type)")
    if data[64:68] != b"MOBI":
        raise ValueError("not a MOBI file (bad creator)")
    num_records = struct.unpack(">H", data[76:78])[0]
    offsets = []
    for i in range(num_records):
        off = struct.unpack(">I", data[78 + i * 8:78 + i * 8 + 4])[0]
        offsets.append(off)
    offsets.append(len(data))
    return [(i, offsets[i], offsets[i + 1]) for i in range(num_records)]


def scan_jpeg_pages(data: bytes):
    """Walk PDB records in order; yield one entry per JPEG found.

    A record may start with a JPEG (the common case for image-only MOBIs);
    any SOI..EOI stream found inside the record payload is also extracted.
    """
    entries = []
    for rec_idx, start, end in pdb_record_offsets(data):
        payload = data[start:end]
        for img_start, img_end in iter_jpegs(payload):
            img = payload[img_start:img_end]
            width, height = jpeg_dimensions(img)
            entries.append({
                "pdb_record": rec_idx,
                "bytes": len(img),
                "width": width,
                "height": height,
                "sha256": sha256(img),
                "duplicate_of": None,
                "_image": img,
            })
    # Assign page names in scan order, then flag duplicate_of as the first
    # page carrying the same hash. Duplicates are kept on disk, not deleted.
    first_by_hash = {}
    for i, e in enumerate(entries):
        e["page"] = i + 1
        e["file"] = f"page_{i + 1:04d}.jpg"
        e["duplicate_of"] = first_by_hash.get(e["sha256"])
        first_by_hash.setdefault(e["sha256"], e["file"])
    return entries


def ingest_mobi(mobi_path, out_dir):
    """Extract JPEG pages from a MOBI; write page files + pages.json.

    Duplicate pages are kept on disk and flagged via duplicate_of.
    Returns (records, json_path).
    """
    data = Path(mobi_path).read_bytes()
    entries = scan_jpeg_pages(data)
    if not entries:
        raise IngestError(f"no JPEG pages found in {Path(mobi_path).name}")

    pages_dir = out_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for e in entries:
        (pages_dir / e["file"]).write_bytes(e.pop("_image"))

    json_path = out_dir / "pages.json"
    json_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return entries, json_path
