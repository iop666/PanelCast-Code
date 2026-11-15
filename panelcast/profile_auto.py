"""S3 页面解读（自动半边）：只填**几何上能算出来**的字段。

边界必须说清楚：`summary / beat / characters / location / scene_tags /
asset_brief` 这些要**读图**才有，本模块一律不猜，填占位符并标
`reviewed: false`。占位符 `meta.unassigned` 会被 `--ship` 门禁拦下，
所以草稿永远进不了出片流程。

能算的：尺寸、sha256、章归属、kind、is_color、panel_count、text_density、
has_splash、borderless、palette（黑白页取灰度分位，彩页取主色）、
composition 的机械描述。
"""

import hashlib
import json
from pathlib import Path

from .panels import analyze_gray, decode_gray, find_ffmpeg, find_ffprobe, probe_size
from .profile import PLACEHOLDER_TAG

SCHEMA = "page-profile/v1"
#: 墨量分档（实测：story 页 12–40%，稀疏页 < 5%）
DENSITY_LOW = 0.12
DENSITY_HIGH = 0.26
BLANK_INK = 0.02
DARK_INK = 0.95
#: 彩页判定：RGB 通道极差的平均值超过这个值就算彩色。
#: 实测标定（1卷/2卷各 5 页）：黑白页极差**精确为 0.00**，彩页 22–50，
#: 所以阈值取 5 足够宽松又不会把扫描色偏当成彩页。
COLOR_SPREAD = 5


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def color_stats(ffmpeg, jpg):
    """低分辨率 RGB 采样：平均通道极差 + 主色（用于 palette）。"""
    import subprocess
    out = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(jpg),
         "-vf", "scale=64:96", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"error: rgb decode failed for {jpg}: "
            f"{out.stderr.decode(errors='replace').strip()[:200]}"
        )
    data = out.stdout
    spread = 0
    buckets = {}
    for i in range(0, len(data) - 2, 3):
        r, g, b = data[i], data[i + 1], data[i + 2]
        spread += max(r, g, b) - min(r, g, b)
        key = (r // 32, g // 32, b // 32)
        buckets[key] = buckets.get(key, 0) + 1
    n = max(1, len(data) // 3)
    top = sorted(buckets.items(), key=lambda kv: -kv[1])[:4]
    palette = []
    for (qr, qg, qb), _ in top:
        rgb = (qr * 32 + 16, qg * 32 + 16, qb * 32 + 16)
        hexv = "#%02x%02x%02x" % rgb
        if hexv not in palette:
            palette.append(hexv)
    return {"mean_spread": spread / n, "palette": palette}


def gray_palette(gray, total):
    """黑白页调色板：灰度分位（p02 实黑 / p10 深墨 / p25 网点 / p50 纸白）。

    累计分布是从**暗端**往上数的，所以分位阈值必须升序；写成降序会让
    四个分位落在同一个灰度上（这个 bug 被测试抓过）。
    """
    counts = [0] * 256
    for b in gray:
        counts[b] += 1
    targets = [0.02, 0.10, 0.25, 0.50]
    out, cum, ti = [], 0, 0
    for v in range(256):
        cum += counts[v]
        while ti < len(targets) and cum / total >= targets[ti]:
            out.append(v)
            ti += 1
    seen, palette = set(), []
    for v in out:
        if v in seen:
            continue
        seen.add(v)
        palette.append("#%02x%02x%02x" % (v, v, v))
    return palette or ["#ffffff"]


def measure(ffmpeg, ffprobe, jpg):
    """单页几何测量。"""
    w, h = probe_size(ffprobe, jpg)
    gray = decode_gray(ffmpeg, jpg, w, h)
    total = len(gray)
    ink = sum(1 for b in gray if b <= 127) / total
    panels, warnings = analyze_gray(gray, w, h)
    colors = color_stats(ffmpeg, jpg)
    is_color = colors["mean_spread"] > COLOR_SPREAD
    max_conf = max((p["confidence"] for p in panels), default=0.0)
    return {
        "width": w, "height": h, "ink": round(ink, 4),
        "panel_count": len(panels),
        "max_confidence": max_conf,
        "borderless": max_conf <= 0.40 or any(
            "no separator lines" in w_ for w_ in warnings),
        "warnings": warnings,
        "is_color": is_color,
        "palette": colors["palette"] if is_color else gray_palette(gray, total),
    }


def kind_of(measure_result, is_chapter_start):
    """版式分类。标题页按"章起始页"判，不靠几何（几何分不出来，见 chapters.py）。"""
    ink = measure_result["ink"]
    if ink <= BLANK_INK:
        return "blank"
    if ink >= DARK_INK:
        return "divider"
    if is_chapter_start:
        return "title_page"
    return "story"


def text_density(ink):
    if ink < DENSITY_LOW:
        return "low"
    if ink < DENSITY_HIGH:
        return "medium"
    return "high"


def composition_of(m):
    """机械描述：只写能测的，不写"人物在哭"这种要读图的。"""
    parts = [f"{m['width']}×{m['height']}"]
    if m["borderless"]:
        parts.append("无框整幅")
    else:
        parts.append(f"{m['panel_count']} 格")
    parts.append(f"墨量 {m['ink'] * 100:.1f}%")
    return "，".join(parts)


def _now():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def build_profile(page, m, chapter, source, generated_at=None):
    """几何测量 → 符合 schema 的草稿介绍页（reviewed=false）。"""
    return {
        "schema": SCHEMA,
        "page": page,
        "source": source,
        "chapter": chapter,
        "layout": {
            "kind": kind_of(m, is_chapter_start=m.get("is_chapter_start", False)),
            "is_color": m["is_color"],
            "panel_count": m["panel_count"],
            "reading_direction": "rtl",
            "text_density": text_density(m["ink"]),
            "has_splash": m["panel_count"] <= 1 and m["ink"] > DENSITY_LOW,
            "borderless": m["borderless"],
        },
        "story": {
            "beat": "transition",
            "summary": "（待视觉补全）",
            "characters": [],
            "location": "（待视觉补全）",
            "time_of_day": "unknown",
            "weather": "unknown",
            "emotion": "neutral",
            "continuity": "cut",
        },
        "text": {
            "bubbles": [],
            "narration_boxes": [],
            "sfx": [],
            "verbatim_complete": False,
            "ocr_confidence": 0.0,
        },
        "visual": {
            "shot": "medium",
            "composition": composition_of(m),
            "key_props": [],
            "palette": m["palette"],
            "motion_hint": "static",
        },
        "reuse": {
            "replaceable": True,
            "replace_strategy": "keep_original",
            "scene_tags": [PLACEHOLDER_TAG],
            "asset_brief": "（待视觉补全）",
            "blocking_reason": None,
        },
        "provenance": {
            "generated_by": "geometry-only",
            "generated_at": generated_at or _now(),
            "confidence": 0.0,
            "reviewed": False,
            "reviewer_notes": "自动草稿：只含几何字段，语义字段待视觉模型或人工补全",
        },
    }


def source_of(page_index, jpg, m, series, volume, mobi_name):
    return {
        "series": series,
        "volume": volume,
        "file": mobi_name,
        "page_index": page_index,
        "printed_page": None,
        "sha256": sha256_file(jpg),
        "width": m["width"],
        "height": m["height"],
    }


def generate(work_dir, index, series, volume, mobi_name, out_dir=None,
             ffmpeg=None, ffprobe=None, chapter_id=None, limit=None):
    """为 work/pages 下每页生成草稿介绍页；返回 (写出路径列表, 失败列表)。"""
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    work = Path(work_dir)
    target = Path(out_dir) if out_dir else work / "profiles"
    target.mkdir(parents=True, exist_ok=True)
    now = _now()

    starts = {c["start_page"]: c for c in index["chapters"]}
    written, failed, skipped = [], [], []
    jpgs = sorted((work / "pages").glob("*.jpg"))
    if limit:
        jpgs = jpgs[:limit]
    for jpg in jpgs:
        page = jpg.stem
        idx = int(page.split("_")[-1])
        if chapter_id:
            ch = next((c for c in index["chapters"]
                       if c["id"] == chapter_id), None)
            if ch is None:
                raise RuntimeError(f"error: unknown chapter {chapter_id!r}")
            if not ch["start_page"] <= idx <= ch["end_page"]:
                continue
        ch = _chapter_of(index, idx)
        if ch is None:
            # 封面/卷头/版权/预告：不属于任何章，不出介绍页
            skipped.append(page)
            continue
        try:
            m = measure(ffmpeg, ffprobe, jpg)
            m["is_chapter_start"] = idx in starts
            profile = build_profile(
                page, m,
                {"id": ch["id"], "label_zh": ch["label_zh"] or ch["number"] or "未确认"},
                source_of(idx, jpg, m, series, volume, mobi_name),
                generated_at=now,
            )
            path = target / f"{page}.profile.json"
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
            written.append(path)
        except RuntimeError as exc:
            failed.append((page, str(exc)))
    return written, failed, skipped


def _chapter_of(index, page_index):
    """页所属章；前后附页返回 None（不是错误）。"""
    for ch in index["chapters"]:
        if ch["start_page"] <= page_index <= ch["end_page"]:
            return ch
    return None
