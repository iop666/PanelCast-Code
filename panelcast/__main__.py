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


def cmd_m1(args):
    """M1 最小闭环：panels / edit / run，以及 S2 chapter、S3 profile、S9 verify。"""
    try:
        if args.m1_command == "panels":
            from .panels import generate_candidates
            results = generate_candidates(args.work)
            for page, status in results:
                print(f"{page}: {status}")
            return 0
        if args.m1_command == "edit":
            from .editor.server import serve
            serve(args.work, args.port)
            return 0
        if args.m1_command == "chapter":
            return _m1_chapter(args)
        if args.m1_command == "slice":
            return _m1_slice(args)
        if args.m1_command == "profile":
            return _m1_profile(args)
        if args.m1_command == "verify":
            return _m1_verify(args)
        if args.m1_command == "run":
            return _m1_run(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 4
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 4
    return 2


def _m1_chapter(args):
    """S2：测量每页 → 分隔页检测 + labels → chapter_index.json。"""
    from .chapters import (
        build_index,
        load_labels,
        measure_pages,
        require_confirmed,
        write_index,
    )

    work = Path(args.work)
    rows = measure_pages(work)
    labels = load_labels(args.labels) if args.labels else None
    index = build_index(rows, labels=labels,
                        series=getattr(args, "series", "") or "",
                        volume=getattr(args, "volume", "") or "")
    path = write_index(work, index)
    for ch in index["chapters"]:
        mark = "" if ch["confirmed"] else "  (未确认)"
        print(f"{ch['id']} {ch['label_zh'] or '?'} "
              f"p{ch['start_page']}-{ch['end_page']} "
              f"({ch['page_count']}p){mark}")
    print(f"detected divider starts: {index['detected_starts']}")
    print(f"chapter_index -> {path}")
    if getattr(args, "require_confirmed", False):
        try:
            require_confirmed(index)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 3
    return 0


def _m1_slice(args):
    """把一章的页面组装成章级 work 目录（pages/ + chapter.json）。"""
    from .chapters import build_chapter_work, load_index

    src = Path(args.work)
    out = Path(args.out)
    index = load_index(src)
    doc, stats, path = build_chapter_work(src, index, args.chapter, out)
    print(f"{doc['id']} {doc['label']} "
          f"p{doc['start_page']}-{doc['end_page']} ({doc['page_count']}p)")
    print(f"pages: {stats['total']} total, {stats['linked']} linked, "
          f"{stats['copied']} copied, {stats['reused']} reused -> {out / 'pages'}")
    print(f"chapter -> {path}")
    return 0


def _m1_profile(args):
    """S3：几何字段自动填，语义字段留占位（reviewed=false）。"""
    from .chapters import load_index, require_confirmed
    from .profile_auto import generate

    work = Path(args.work)
    index = load_index(work)
    if not getattr(args, "allow_unconfirmed", False):
        require_confirmed(index)
    written, failed, skipped = generate(
        work, index,
        series=getattr(args, "series", "") or "",
        volume=getattr(args, "volume", "") or "",
        mobi_name=getattr(args, "mobi", "") or "",
        chapter_id=getattr(args, "chapter", None),
        limit=getattr(args, "limit", None),
    )
    for page, err in failed:
        print(f"error: {page}: {err}", file=sys.stderr)
    print(f"profiles: {len(written)} written, {len(skipped)} skipped "
          f"(front/back matter), {len(failed)} failed -> {work / 'profiles'}")
    if failed:
        return 4
    return 0


def _m1_verify(args):
    """S9：15 条验收 → run_report.json；任一不过退出码 4。"""
    import json as _json

    from .verify import verify_run, write_report

    work = Path(args.work)
    out = Path(args.out)
    timeline_path = work / "timeline.json"
    script_path = work / "script.json"
    for p in (timeline_path, script_path):
        if not p.exists():
            print(f"error: {p} not found", file=sys.stderr)
            return 3
    timeline = _json.loads(timeline_path.read_text(encoding="utf-8"))
    script = _json.loads(script_path.read_text(encoding="utf-8"))
    pages = [p for seg in script["segments"] for p in seg.get("pages") or []]
    width, height = _parse_size(getattr(args, "size", None) or "1080x1920")
    report = verify_run(work, out, args.name, timeline["total_duration"], pages,
                        width=width, height=height)
    path = write_report(out, report)
    for c in report["checks"]:
        flag = "OK  " if c["pass"] else "FAIL"
        print(f"[{flag}] {c['id']:2d} {c['item']}: {c['actual']}")
    print(f"verify: {report['passed']}/{len(report['checks'])} passed "
          f"-> {path}")
    return 0 if report["ok"] else 4


def _m1_run(args):
    """S6：确认检查(缺 panels.json → 退出码 3) → TTS → timeline → render。"""
    import json as _json

    from .timeline import load_script

    work = Path(args.work)
    out = Path(args.out)
    pages_dir = work / "pages"
    panels_dir = work / "panels"
    pages = sorted(p.stem for p in pages_dir.glob("*.jpg"))
    if not pages:
        print(f"error: no pages in {pages_dir}", file=sys.stderr)
        return 3
    if getattr(args, "skip_panel_gate", False):
        # V1 是整页渲染，分格不参与出片；批量出片时不必逐页确认分格。
        # 一旦要做分镜级渲染，这个开关必须关掉。
        print("panels: gate skipped (whole-page render, panels unused)")
        confirmed = {p: None for p in pages}
        script = load_script(work, set(confirmed))
        return _m1_render_pipeline(args, work, out, script)

    missing = [p for p in pages
               if not (panels_dir / f"{p}.panels.json").exists()]
    if missing:
        print(
            "error: unconfirmed pages (no *.panels.json): "
            + ", ".join(missing),
            file=sys.stderr,
        )
        return 3
    confirmed = {}
    for p in pages:
        doc = _json.loads(
            (panels_dir / f"{p}.panels.json").read_text(encoding="utf-8")
        )
        if doc.get("source") != "manual":
            confirmed.setdefault("not_manual", []).append(p)
        else:
            confirmed[p] = doc
    if "not_manual" in confirmed:
        print(
            "error: pages not manually confirmed (source != manual): "
            + ", ".join(confirmed["not_manual"]),
            file=sys.stderr,
        )
        return 3

    script = load_script(work, set(confirmed))
    return _m1_render_pipeline(args, work, out, script)


def _m1_render_pipeline(args, work, out, script):
    """S6–S8：TTS → timeline → render。分格门禁已在上游处理。"""
    import json as _json

    from .panels import find_ffmpeg
    from .render import render
    from .timeline import build_timeline, write_text_atomic
    from .tts import probe_backend, synth_segments

    backend = probe_backend(voice=getattr(args, "voice", None),
                            rate=getattr(args, "rate", None))
    print(f"tts: {backend['backend']} (voice={backend['voice']}, "
          f"rate={backend['rate']})")
    audios = synth_segments(work, script, backend)
    ffmpeg = find_ffmpeg()
    timeline = build_timeline(script, audios, backend, ffmpeg)
    write_text_atomic(work / "timeline.json", _json.dumps(
        timeline, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        f"timeline: {len(timeline['segments'])} segments, "
        f"total {timeline['total_duration']:.1f}s -> {work / 'timeline.json'}"
    )
    width, height = _parse_size(getattr(args, "size", None))
    fit = getattr(args, "fit", "letterbox")
    bg = getattr(args, "bg", "blur")
    burn = getattr(args, "subs", "burn") == "burn"
    info = render(work, out, timeline, ffmpeg=ffmpeg,
                  width=width, height=height, fit=fit, burn_subs=burn, bg=bg,
                  chapter=getattr(args, "chapter", None),
                  name=getattr(args, "name", "sample"))
    print(
        f"render: {info['width']}x{info['height']} {info['fps']}fps "
        f"{info['duration']:.1f}s fit={fit} bg={bg} "
        f"subs={'burn' if burn else 'none'} "
        f"-> {out / (args.name + '.mp4')} (+ .srt/.ass)"
    )
    return 0


def _parse_size(size):
    """'1080x1920' → (1080, 1920)；None → 默认 1920x1080。"""
    from .render import DEFAULT_HEIGHT, DEFAULT_WIDTH
    if not size:
        return DEFAULT_WIDTH, DEFAULT_HEIGHT
    try:
        w, h = size.lower().split("x", 1)
        w, h = int(w), int(h)
    except (ValueError, AttributeError):
        raise SystemExit(f"error: bad --size {size!r}, want WIDTHxHEIGHT")
    if w <= 0 or h <= 0 or w % 2 or h % 2:
        raise SystemExit(f"error: bad --size {size!r}, need positive even numbers")
    return w, h


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
    m1 = sub.add_parser(
        "m1", help="M1 minimal loop: panel candidates / editor / render",
    )
    m1sub = m1.add_subparsers(dest="m1_command", required=True)
    m1panels = m1sub.add_parser(
        "panels", help="generate *.candidates.json for pages lacking one",
    )
    m1panels.add_argument("--work", default="m1/work")
    m1edit = m1sub.add_parser("edit", help="local panel-review editor")
    m1edit.add_argument("--work", default="m1/work")
    m1edit.add_argument("--port", type=int, default=8642)
    m1run = m1sub.add_parser(
        "run", help="confirmed pages -> TTS -> timeline -> MP4+SRT",
    )
    m1run.add_argument("--work", default="m1/work")
    m1run.add_argument("--out", default="m1/out")
    m1run.add_argument(
        "--voice", default=None,
        help="edge-tts 音色（如 zh-CN-YunxiNeural）；默认 zh-CN-XiaoxiaoNeural",
    )
    m1run.add_argument(
        "--rate", default=None,
        help='edge-tts 语速，如 "+20%%"（1.2 倍速）；默认 +0%%',
    )
    m1run.add_argument(
        "--size", default=None,
        help="画布尺寸 WIDTHxHEIGHT，如 1080x1920（竖屏）；默认 1920x1080",
    )
    m1run.add_argument(
        "--fit", default="letterbox", choices=["letterbox", "cover", "blurpad"],
        help="letterbox=整页可见留白；cover=铺满裁切；"
             "blurpad=缩小整页+模糊背景填充+底部字幕带（竖屏推荐）",
    )
    m1run.add_argument(
        "--bg", default="blur", choices=["blur", "white"],
        help="blurpad 底色：blur=同页模糊填充；white=纯白底",
    )
    m1run.add_argument(
        "--subs", default="burn", choices=["burn", "none"],
        help="burn=把字幕烧进画面（白字黑描边）；none=只出 srt/ass 文件",
    )
    m1run.add_argument(
        "--chapter", default=None,
        help='右上角常驻章节标签，如 "第一章 与自称是女神的家伙一起转生到异世界！"',
    )
    m1run.add_argument(
        "--skip-panel-gate", action="store_true",
        help="整页渲染不需要分格确认时跳过该门禁（批量出片用；"
             "改成分镜级渲染后必须关掉）",
    )
    m1run.add_argument(
        "--name", default="sample",
        help="产物文件名（不含扩展名），如 第一章 -> 第一章.mp4/.srt/.ass",
    )
    m1chapter = m1sub.add_parser(
        "chapter", help="S2: measure pages, detect chapter dividers, confirm labels",
    )
    m1chapter.add_argument("--work", default="m1/work")
    m1chapter.add_argument("--labels", default=None,
                           help="章节标签 JSON（人工确认过的边界与标题）")
    m1chapter.add_argument("--series", default="", help="系列名，写进 index")
    m1chapter.add_argument("--volume", default="", help="卷名，写进 index")
    m1chapter.add_argument("--require-confirmed", action="store_true",
                           help="有未确认章时退出码 3")

    m1slice = m1sub.add_parser(
        "slice", help="按章组装章级 work 目录（pages/ + chapter.json）",
    )
    m1slice.add_argument("--work", default="m1/work",
                         help="卷级 work（要有 chapter_index.json 和 pages/）")
    m1slice.add_argument("--chapter", required=True,
                         help="章 id 或章节号，如 ch02 / 第二章")
    m1slice.add_argument("--out", required=True,
                         help="章级 work 目录，如 m1/v1/ch02/work")

    m1profile = m1sub.add_parser(
        "profile", help="S3: geometry-only page profiles (semantic fields left blank)",
    )
    m1profile.add_argument("--work", default="m1/work")
    m1profile.add_argument("--series", default="")
    m1profile.add_argument("--volume", default="")
    m1profile.add_argument("--mobi", default="", help="源 mobi 文件名，写进 source.file")
    m1profile.add_argument("--chapter", default=None,
                           help="只做这一章（如 ch01）")
    m1profile.add_argument("--limit", type=int, default=None,
                           help="只做前 N 页（调试用）")
    m1profile.add_argument("--allow-unconfirmed", action="store_true",
                           help="章节未确认也继续（仅调试）")

    m1verify = m1sub.add_parser(
        "verify", help="S9: run the 15 acceptance checks -> run_report.json",
    )
    m1verify.add_argument("--work", default="m1/work")
    m1verify.add_argument("--out", default="m1/out")
    m1verify.add_argument("--name", default="sample")
    m1verify.add_argument("--size", default=None,
                          help="画布尺寸 WIDTHxHEIGHT，默认 1080x1920")
    args = parser.parse_args(argv)
    if args.command == "ingest":
        sys.exit(cmd_ingest(args))
    if args.command == "m1":
        sys.exit(cmd_m1(args))


if __name__ == "__main__":
    main()
