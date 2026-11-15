"""EPUB ingestion: parse OPF spine, extract chapter text as JSON records."""

import hashlib
import json
import posixpath
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

from .errors import IngestError

CHAPTER_IDS = [f"chapter{i:02d}.xhtml" for i in range(6)]  # chapter00..chapter05

_OPF_NS = "{http://www.idpf.org/2007/opf}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"


class _TextExtractor(HTMLParser):
    """Collect visible text from <p> blocks (plus bare <br/>-separated runs)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs = []
        self._buf = []
        self._title = None
        self._in_title = False
        self._in_p = False

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._in_p = True
            self._buf = []
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "p":
            self._in_p = False
            text = "".join(self._buf).strip()
            if text:
                self.paragraphs.append(text)
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self._title = (self._title or "") + data
        elif self._in_p:
            self._buf.append(data)

    def result(self):
        title = (self._title or "").strip()
        return title, "\n".join(self.paragraphs)


def parse_opf(epub: zipfile.ZipFile):
    """Parse container.xml -> OPF.

    Return (manifest_map, spine_id_list, book_title, language, opf_path).
    """
    container = ElementTree.fromstring(epub.read("META-INF/container.xml"))
    rootfile = container.find(".//{*}rootfile")
    opf_path = rootfile.get("full-path")
    opf_dir = posixpath.dirname(opf_path)
    opf = ElementTree.fromstring(epub.read(opf_path))

    manifest = {}
    for item in opf.find(f"{_OPF_NS}manifest"):
        href = item.get("href")
        manifest[item.get("id")] = posixpath.normpath(
            posixpath.join(opf_dir, href) if opf_dir else href
        )

    spine_ids = [itemref.get("idref") for itemref in opf.find(f"{_OPF_NS}spine")]

    title_el = opf.find(f".//{_DC_NS}title")
    book_title = title_el.text if title_el is not None else None
    lang_el = opf.find(f".//{_DC_NS}language")
    language = lang_el.text.strip() if lang_el is not None and lang_el.text else None
    return manifest, spine_ids, book_title, language, opf_path


def extract_chapters(epub_path):
    """Extract chapter00..chapter05 (in OPF spine order) as (chapters, language)."""
    chapters = []
    with zipfile.ZipFile(epub_path) as z:
        manifest, spine_ids, _book_title, language, opf_path = parse_opf(z)
        id_to_href = manifest
        wanted = [sid for sid in spine_ids if sid in CHAPTER_IDS]
        # Sort by requested chapter order (chapter00..05), not spine position,
        # so output order is deterministic even if spine reorders them.
        wanted.sort(key=lambda sid: CHAPTER_IDS.index(sid))
        for order, sid in enumerate(wanted):
            entry = id_to_href[sid]
            raw = z.read(entry)
            parser = _TextExtractor()
            parser.feed(raw.decode("utf-8"))
            title, text = parser.result()
            if not title:
                title = sid
            chapters.append({
                "id": sid,
                "order": order,
                "title": title,
                "text": text,
                "char_count": len(text),
                "source_entry": entry,
                "sha256": hashlib.sha256(raw).hexdigest(),
            })
        if not chapters:
            raise IngestError(
                f"no usable chapters in {Path(epub_path).name}: expected spine "
                f"chapter ids {CHAPTER_IDS[0]}~{CHAPTER_IDS[-1]}"
            )
    return chapters, language


def ingest_epub(epub_path, out_dir):
    """Write chapters JSON for one EPUB; returns (records, json_path, language)."""
    chapters, language = extract_chapters(epub_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "chapters.json"
    json_path.write_text(
        json.dumps(chapters, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chapters, json_path, language
