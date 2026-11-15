"""CLI entry point: python -m panelcast ingest [paths...]"""

import argparse
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .errors import IngestError
from .epub_ingest import ingest_epub
from .manifest import build_manifest, write_manifest
from .mobi_ingest import ingest_mobi

DEFAULT_OUTPUT = Path(".local/source")
DEFAULT_SCAN_ROOT = Path(".")
STAGE_PREFIX = ".panelcast-stage-"


def _iter_inputs(paths):
    """Expand CLI paths into concrete .epub / .mobi file paths.

    Directories are scanned for *.epub / *.mobi, skipping .local and any
    copyright-material files (covers/backcovers are never ingested as assets).
    """
    seen = set()
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and ".local" not in f.parts \
                        and f.suffix.lower() in (".epub", ".mobi"):
                    resolved = f.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        yield f
        elif p.is_file():
            resolved = p.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield p
        else:
            raise FileNotFoundError(f"input not found: {p}")


def _replace_subtree(stage_path, dst):
    """Swap one tool-managed output subtree (epub/ or mobi/) for the staged one.

    Commit-phase only: an absent staged subtree (input type not in this run)
    removes the old one, a present one replaces it wholesale (dropping stale
    pages/*.jpg beyond the new page count along the way). Same-volume
    os.replace keeps the swap atomic once the old tree is gone.
    """
    if dst.is_dir():
        shutil.rmtree(dst)
    elif dst.exists():
        dst.unlink()
    if stage_path.is_dir():
        os.replace(stage_path, dst)


def cmd_ingest(args):
    # Input expansion runs before any output dir / staging is created, so it
    # gets its own guard (exit 4) instead of joining the staging try/finally.
    try:
        inputs = list(_iter_inputs(args.inputs or [DEFAULT_SCAN_ROOT]))
    except OSError as exc:  # 输入路径不存在 / 无法访问 -> 4
        print(f"error: {exc}", file=sys.stderr)
        return 4
    epubs = [p for p in inputs if p.suffix.lower() == ".epub"]
    mobis = [p for p in inputs if p.suffix.lower() == ".mobi"]

    # One EPUB + one MOBI per run: same-type extras would silently overwrite
    # the shared outputs (chapters.json / pages.json), so reject before writing.
    rejected = False
    for kind, group in (("EPUB", epubs), ("MOBI", mobis)):
        if len(group) > 1:
            print(
                f"error: {len(group)} {kind} inputs given, at most one per run: "
                + ", ".join(str(p) for p in group),
                file=sys.stderr,
            )
            rejected = True
    if rejected:
        return 2

    source_dir = Path(args.output)
    source_dir.mkdir(parents=True, exist_ok=True)

    # Remove staging residue from any previously crashed run before staging afresh.
    for stale in source_dir.glob(f"{STAGE_PREFIX}*"):
        shutil.rmtree(stale, ignore_errors=True)

    # All new artifacts are written into a staging dir; the previous outputs are
    # only touched in the commit phase below, after every fallible step
    # (parsing, extraction, manifest build) has succeeded. A failed run keeps
    # the last valid outputs and manifest untouched.
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=source_dir))
    try:
        language = None
        epub_result = mobi_result = None
        if epubs:
            chapters, _, language = ingest_epub(epubs[0], stage / "epub")
            print(
                f"EPUB  {epubs[0].name}: {len(chapters)} chapters "
                f"-> {source_dir / 'epub' / 'chapters.json'}"
            )
            epub_result = (epubs[0], chapters)
        if mobis:
            pages, _ = ingest_mobi(mobis[0], stage / "mobi")
            dupes = sum(1 for p in pages if p["duplicate_of"])
            print(
                f"MOBI  {mobis[0].name}: {len(pages)} pages "
                f"({len(pages) - dupes} unique, {dupes} duplicates) "
                f"-> {source_dir / 'mobi' / 'pages.json'}"
            )
            mobi_result = (mobis[0], pages)

        if epub_result is None and mobi_result is None:
            print("no .epub or .mobi inputs found", file=sys.stderr)
            return 1

        manifest = build_manifest(epub_result, mobi_result, language=language)

        # Commit: the output dir must reflect exactly this manifest — drop the
        # subtree of any absent input type, swap in the staged one for present
        # types, then write the manifest last.
        for name in ("epub", "mobi"):
            _replace_subtree(stage / name, source_dir / name)
        manifest_path = write_manifest(source_dir, manifest)
        print(f"manifest -> {manifest_path}")
        return 0
    except IngestError as exc:        # 能打开但没内容 -> 3
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (zipfile.BadZipFile, ElementTree.ParseError, ValueError,
            KeyError, OSError) as exc:  # 根本读不了 -> 4
        print(f"error: {exc}", file=sys.stderr)
        return 4
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="panelcast", description="PanelCast source ingestion (stdlib only)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser(
        "ingest",
        help="Ingest one EPUB and/or one MOBI (one per type) into .local/source",
    )
    ingest.add_argument(
        "inputs", nargs="*", default=None,
        help="EPUB/MOBI files or directories to scan (default: current directory)",
    )
    ingest.add_argument(
        "-o", "--output", default=str(DEFAULT_OUTPUT),
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args(argv)
    if args.command == "ingest":
        sys.exit(cmd_ingest(args))


if __name__ == "__main__":
    main()
