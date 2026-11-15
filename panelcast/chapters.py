"""S2 章节定界：候选检测 + 强制人工确认。

**诚实的边界**：章节标题页只能靠**读横幅文字**确定，这是 OCR 问题，本模块
不做 OCR。它做两件事：

1. 把整卷缩到几个候选（有分隔页的卷命中率很高）；
2. 在没确认之前拒绝继续（`require_confirmed` 抛错，CLI 退出码 3）。

检测规则（v1 实测 3/3 命中）：
    近全黑页（墨量 ≥ 0.95）紧跟近空白页（墨量 ≤ 0.02）→ **再下一页**是标题页。

为什么只认这一条：我试过 6 种几何特征（无分格线、横幅白条、实心浅色矩形、
文字行方差、整幅出血、浅色小矩形+字块），没有一种能把标题页和普通页分开——
标题页的横幅本身就会产生分格线，而普通页的 gutter 也是纯白长条。
唯一稳的信号是黑页+波点页这对分隔页。没有分隔页的卷（如 2 卷全卷只有
1 个黑页）必须由 labels 文件直接给边界，不许猜。
"""

import json
import os
import shutil
from pathlib import Path

from .panels import decode_gray, find_ffmpeg, find_ffprobe, probe_size

#: 近全黑页阈值（墨量 = 灰度 ≤ 127 的像素占比）
DIVIDER_DARK_INK = 0.95
#: 近空白页阈值（波点分隔页实测 1.1%，纯空白 < 0.5%）
DIVIDER_BLANK_INK = 0.02
#: 判定墨像素的灰度上限
INK_LEVEL = 127

SCHEMA = "chapter-index/v1"


def measure_page(ffmpeg, ffprobe, jpg):
    """单页测量：墨量、纯白占比、尺寸。"""
    w, h = probe_size(ffprobe, jpg)
    gray = decode_gray(ffmpeg, jpg, w, h)
    total = len(gray)
    ink = sum(1 for b in gray if b <= INK_LEVEL) / total
    return {
        "page": Path(jpg).stem,
        "index": int(Path(jpg).stem.split("_")[-1]),
        "width": w,
        "height": h,
        "ink": round(ink, 4),
        "white": round(gray.count(255) / total, 4),
    }


def measure_pages(work_dir, ffmpeg=None, ffprobe=None):
    """work/pages 下每页测量，按页码升序。"""
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    pages_dir = Path(work_dir) / "pages"
    jpgs = sorted(pages_dir.glob("*.jpg"))
    if not jpgs:
        raise RuntimeError(f"error: no pages under {pages_dir}")
    return [measure_page(ffmpeg, ffprobe, p) for p in jpgs]


def detect_divider_starts(rows):
    """黑页 + 空白页 → 返回下一章起始页的 1 起页码列表。"""
    starts = []
    for i in range(len(rows) - 2):
        if (rows[i]["ink"] >= DIVIDER_DARK_INK
                and rows[i + 1]["ink"] <= DIVIDER_BLANK_INK):
            starts.append(rows[i + 2]["index"])
    return starts


def _normalize_labels(labels):
    """labels → [{number, title, start_page, label_zh}]，按 start_page 升序。"""
    out = []
    for item in (labels or {}).get("chapters") or []:
        try:
            start = int(item["start_page"])
        except (KeyError, TypeError, ValueError):
            raise RuntimeError(f"error: label missing start_page: {item!r}")
        number = (item.get("number") or "").strip()
        title = (item.get("title") or "").strip()
        label_zh = item.get("label_zh") or " ".join(x for x in (number, title) if x)
        if not label_zh:
            raise RuntimeError(
                f"error: label for page {start} has neither number/title nor label_zh"
            )
        out.append({"number": number, "title": title,
                    "start_page": start, "label_zh": label_zh})
    if not out:
        raise RuntimeError("error: labels file has no chapters")
    seen = set()
    for item in out:
        if item["start_page"] in seen:
            raise RuntimeError(f"error: duplicate chapter start {item['start_page']}")
        seen.add(item["start_page"])
    return sorted(out, key=lambda c: c["start_page"])


def _end_before_divider(rows, start_page, fallback):
    """章节收尾时把紧挨下一章的分隔页（黑页+波点页）排除掉。

    v1 实测：第二章起于 p45，它前面是 p43 全黑 + p44 波点——这两页是
    **章末分隔**，不属于第一章内容。不排掉的话第一章会多出两页空白，
    视频末尾凭空多停 8 秒。
    """
    dark_i = start_page - 3          # 1 起页码 → rows 下标
    blank_i = start_page - 2
    if dark_i < 0 or blank_i < 0 or blank_i >= len(rows):
        return fallback
    if (rows[dark_i]["ink"] >= DIVIDER_DARK_INK
            and rows[blank_i]["ink"] <= DIVIDER_BLANK_INK):
        return start_page - 3
    return fallback


def build_index(rows, labels=None, series="", volume="",
                front_matter_end=None, back_matter_start=None):
    """测量结果 (+ labels) → chapter_index 字典。

    有 labels 时以 labels 为准（labels 的 start_page 覆盖检测结果）；
    无 labels 时用分隔页检测，且全部标 `confirmed: false`。
    """
    page_count = len(rows)
    if labels:
        chapters = _normalize_labels(labels)
        series = labels.get("series") or series
        volume = labels.get("volume") or volume
        front_matter_end = labels.get("front_matter_end", front_matter_end)
        back_matter_start = labels.get("back_matter_start", back_matter_start)
        detected = detect_divider_starts(rows)
        source = "labels"
    else:
        starts = detect_divider_starts(rows)
        if not starts:
            raise RuntimeError(
                "error: no chapter divider pairs found; supply --labels "
                "(this volume needs human confirmation)"
            )
        chapters = [{"number": "", "title": "", "start_page": s, "label_zh": ""}
                    for s in starts]
        detected = starts
        source = "divider-pair"

    starts = [c["start_page"] for c in chapters]
    if starts[0] <= 1:
        front_matter_end = 0
    elif front_matter_end is None:
        front_matter_end = starts[0] - 1

    out = []
    for i, ch in enumerate(chapters):
        start = ch["start_page"]
        if i + 1 < len(chapters):
            end = _end_before_divider(rows, chapters[i + 1]["start_page"],
                                      chapters[i + 1]["start_page"] - 1)
        elif back_matter_start:
            end = back_matter_start - 1
        else:
            end = page_count
        if end < start:
            raise RuntimeError(
                f"error: chapter at page {start} ends before it starts ({end})"
            )
        out.append({
            "id": f"ch{i + 1:02d}",
            "number": ch["number"],
            "title": ch["title"],
            "label_zh": ch["label_zh"],
            "start_page": start,
            "end_page": end,
            "page_count": end - start + 1,
            "confirmed": bool(ch["label_zh"]),
        })

    return {
        "schema": SCHEMA,
        "series": series,
        "volume": volume,
        "page_count": page_count,
        "source": source,
        "detected_starts": detected,
        "warnings": _warnings(starts, detected),
        "front_matter": {"start_page": 1, "end_page": front_matter_end}
                        if front_matter_end and front_matter_end >= 1 else None,
        "back_matter": {"start_page": back_matter_start, "end_page": page_count}
                       if back_matter_start else None,
        "chapters": out,
    }


def _warnings(starts, detected):
    """把"检测不到"的事实说出来，别让人以为整卷只有这么多章。"""
    out = []
    if detected and starts and min(starts) < min(detected):
        out.append(
            f"first chapter starts at page {min(starts)}, before the first "
            f"divider pair (page {min(detected)}); it cannot be auto-detected"
        )
    if not detected:
        out.append(
            "no divider pairs found in this volume; every boundary comes from "
            "the labels file, nothing was verified by geometry"
        )
    return out


def require_confirmed(index):
    """没确认就不许进 S3/S4。抛 RuntimeError（CLI 退出码 3）。"""
    pending = [c for c in index["chapters"] if not c["confirmed"]]
    if pending:
        pages = ", ".join(str(c["start_page"]) for c in pending)
        raise RuntimeError(
            f"error: {len(pending)} chapter(s) unconfirmed at page {pages}; "
            f"fill label_zh in the labels file first"
        )
    return index


def pages_of(index, chapter_id):
    """某章的页码字符串列表（page_0005 形式）。"""
    for ch in index["chapters"]:
        if ch["id"] == chapter_id:
            return [f"page_{i:04d}"
                    for i in range(ch["start_page"], ch["end_page"] + 1)]
    raise RuntimeError(f"error: unknown chapter {chapter_id!r}")


def write_index(work_dir, index):
    path = Path(work_dir) / "chapter_index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


def load_index(work_dir):
    path = Path(work_dir) / "chapter_index.json"
    if not path.exists():
        raise RuntimeError(f"error: chapter index not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_labels(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_chapter(index, key):
    """按 id（ch02）或章节号（第二章）找一章，找不到抛错。"""
    for ch in index["chapters"]:
        if key in (ch["id"], ch["number"]):
            return ch
    known = ", ".join(f"{c['id']}={c['number']}" for c in index["chapters"])
    raise RuntimeError(f"error: unknown chapter {key!r}; known: {known}")


def chapter_label(ch):
    """右上角标签文案：有标题就「第二章 标题」，没标题就只写「第十章」。"""
    title = (ch.get("title") or "").strip()
    return f"{ch['number']} {title}".strip()


def slice_pages(src_pages, dst_pages, names):
    """把一章的页面放进章级 work/pages/。

    优先硬链接（同卷、零拷贝、几百 MB 不重复占盘），跨卷或文件系统不支持时
    退回复制。已存在的同名文件直接复用——重跑不会重复搬运。
    """
    src_pages = Path(src_pages)
    dst_pages = Path(dst_pages)
    dst_pages.mkdir(parents=True, exist_ok=True)
    linked = copied = reused = 0
    missing = []
    for name in names:
        src = src_pages / f"{name}.jpg"
        dst = dst_pages / f"{name}.jpg"
        if not src.exists():
            missing.append(name)
            continue
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            reused += 1
            continue
        if dst.exists():
            dst.unlink()
        try:
            os.link(src, dst)
            linked += 1
        except OSError:
            shutil.copyfile(src, dst)
            copied += 1
    if missing:
        raise RuntimeError(
            f"error: {len(missing)} page(s) missing in {src_pages}: "
            + ", ".join(missing[:5]) + ("..." if len(missing) > 5 else "")
        )
    return {"linked": linked, "copied": copied, "reused": reused,
            "total": len(names)}


def build_chapter_work(src_work, index, key, out_work):
    """组装章级 work 目录：pages/ + chapter.json。

    只搬页面，不搬 script.json——旁白要按章重写，不能从整卷脚本里切。
    """
    ch = find_chapter(index, key)
    names = pages_of(index, ch["id"])
    stats = slice_pages(Path(src_work) / "pages", Path(out_work) / "pages",
                        names)
    doc = {
        "schema": "chapter-work/v1",
        "series": index.get("series", ""),
        "volume": index.get("volume", ""),
        "id": ch["id"],
        "number": ch["number"],
        "title": ch.get("title") or "",
        "label": chapter_label(ch),
        "start_page": ch["start_page"],
        "end_page": ch["end_page"],
        "page_count": ch["page_count"],
        "pages": names,
        "source_work": str(src_work),
    }
    path = Path(out_work) / "chapter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return doc, stats, path
