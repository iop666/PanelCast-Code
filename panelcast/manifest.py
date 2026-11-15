"""Source manifest for .local/source/source_manifest.json (schema_version 1).

Top-level fields:
- schema_version / extractor_version: manifest layout and writing code version
- created_at: first-generation time (UTC ISO-8601); preserved on re-runs
- language / reading_direction: EPUB dc:language; manga page flow (rtl)
- source_files: role/path/bytes/sha256 per ingested input
- chapter_count / page_count / unique_page_count: null when that input type
  is absent from the run

Everything except created_at is deterministic (sorted keys, stable ordering),
so repeated runs over the same inputs produce byte-identical output.
"""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from . import __version__

SCHEMA_VERSION = 1
READING_DIRECTION = "rtl"


def _file_info(role, path):
    """role/path/bytes/sha256 for one input file (streamed hash)."""
    p = Path(path)
    digest = hashlib.sha256()
    size = 0
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return {
        "role": role,
        "path": p.as_posix(),
        "bytes": size,
        "sha256": digest.hexdigest(),
    }


def _epub_section(epub_result):
    epub_path, chapters = epub_result
    return {
        "input": Path(epub_path).as_posix(),
        "chapters": [
            {
                "id": c["id"],
                "order": c["order"],
                "title": c["title"],
                "char_count": c["char_count"],
                "source_entry": c["source_entry"],
                "sha256": c["sha256"],
            }
            for c in chapters
        ],
    }


def _mobi_section(mobi_result):
    mobi_path, pages = mobi_result
    return {
        "input": Path(mobi_path).as_posix(),
        "pages": [
            {
                "page": p["page"],
                "file": p["file"],
                "pdb_record": p["pdb_record"],
                "width": p["width"],
                "height": p["height"],
                "sha256": p["sha256"],
                "duplicate_of": p["duplicate_of"],
            }
            for p in pages
        ],
        "unique_pages": sum(1 for p in pages if not p["duplicate_of"]),
    }


def build_manifest(epub_result, mobi_result, language=None):
    """Build the manifest dict (no created_at; write_manifest injects it).

    epub_result: (epub_path, chapters) or None; mobi_result: (mobi_path, pages)
    or None. A None side yields a null section and null counts (single-type run).
    """
    source_files = []
    if epub_result is not None:
        source_files.append(_file_info("epub", epub_result[0]))
    if mobi_result is not None:
        source_files.append(_file_info("mobi", mobi_result[0]))

    return {
        "schema_version": SCHEMA_VERSION,
        "extractor_version": __version__,
        "language": language,
        "reading_direction": READING_DIRECTION,
        "source_files": source_files,
        "chapter_count": len(epub_result[1]) if epub_result is not None else None,
        "page_count": len(mobi_result[1]) if mobi_result is not None else None,
        "unique_page_count": (
            sum(1 for p in mobi_result[1] if not p["duplicate_of"])
            if mobi_result is not None
            else None
        ),
        "epub": _epub_section(epub_result) if epub_result is not None else None,
        "mobi": _mobi_section(mobi_result) if mobi_result is not None else None,
    }


def write_manifest(source_dir, manifest):
    """Write manifest JSON, preserving created_at from an existing manifest.

    created_at is written on first generation only; subsequent runs (even with
    different inputs) keep the original value so re-runs stay diff-stable.
    Written via temp file + os.replace so a failed write cannot truncate the
    previous valid manifest.
    """
    path = source_dir / "source_manifest.json"
    created_at = None
    if path.exists():
        try:
            created_at = json.loads(path.read_text(encoding="utf-8")).get("created_at")
        except (OSError, ValueError):
            created_at = None
    if not created_at:
        created_at = datetime.now(UTC).isoformat(timespec="seconds")
    manifest = dict(manifest, created_at=created_at)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path
