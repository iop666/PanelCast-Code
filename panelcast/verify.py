"""S9 质检：把规范 §9.2 的 15 条做成一条命令，产出 run_report.json。

设计原则：**每条都独立复验，不许互相引用**。比如"视频轨时长"必须走
`stream=duration`，不能拿容器时长代替——容器时长够而视频轨短，正是第一章
那个"最后几秒画面卡住"的 bug 能溜过去的原因。

画面类三条（8/9/10）靠抽一帧做灰度统计，因此它们是**抽样**而非全片：
抽的是字幕最可能出现的时刻（成片 30% 处）。抽帧时间可调，报告里会写明。
"""

import json
import subprocess
from pathlib import Path

from .timeline import (
    MAX_CHARS_PER_PAGE,
    MAX_DWELL,
    MIN_CHARS_PER_PAGE,
    MIN_DWELL,
    plan_page_windows,
)

SCHEMA = "run-report/v1"

#: 版面三段（1080×1920 实测值，见 §7.2）
LABEL_BAND = (18, 48)
COMIC_TOP = 72
COMIC_BOTTOM_RANGE = (1693, 1703)
SUBTITLE_BAND = (1747, 1821)
BAND_TOL = 6

#: 字幕带：白字 255、黑描边 < 60
WHITE_LEVEL = 250
OUTLINE_LEVEL = 60
MIN_OUTLINE_PIXELS = 5000

#: 章节标签的浅灰 #999999
LABEL_GREY = (140, 175)

DEFAULT_SAMPLE_RATIO = 0.3

#: 页窗口越出"讲这一页的段"的容忍量（秒）。0.5 秒是观感上的临界值：
#: 超过半秒，观众就能察觉画面在等文本，或者文本已经走远了画面还没翻。
PAGE_SYNC_TOL = 0.5


def _run(cmd, what, timeout=120):
    out = subprocess.run([str(c) for c in cmd], capture_output=True,
                         timeout=timeout)
    if out.returncode != 0:
        raise RuntimeError(
            f"error: {what} failed: "
            f"{(out.stderr or out.stdout).decode(errors='replace').strip()[:300]}"
        )
    return out


def probe_streams(ffprobe, video):
    """视频流 + 音频流 + 容器时长，一次拿全。"""
    out = _run([ffprobe, "-v", "error", "-show_entries",
                "stream=index,codec_type,width,height,avg_frame_rate,pix_fmt,"
                "duration,nb_frames:format=duration",
                "-of", "json", video], "ffprobe streams")
    data = json.loads(out.stdout.decode("utf-8", "replace") or "{}")
    streams = data.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format") or {}
    return v, a, fmt


def _parse_fps(raw):
    raw = (raw or "").strip()
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            return round(float(num) / float(den), 3) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return round(float(raw), 3)
    except ValueError:
        return 0.0


def frame_gray(ffmpeg, video, t, width, height):
    """抽 t 秒处一帧，返回 width*height 灰度字节。"""
    out = _run([ffmpeg, "-v", "error", "-ss", f"{max(t, 0):.3f}", "-i", video,
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
               "frame extract", timeout=180)
    data = out.stdout
    if len(data) < width * height:
        raise RuntimeError(
            f"error: frame at {t:.2f}s has {len(data)} bytes, "
            f"want {width * height}"
        )
    return data[:width * height]


def band_rows(gray, width, y0, y1, predicate, min_hits):
    """[y0, y1) 内满足 predicate 的像素数 >= min_hits 的行，返回 (first, last)。"""
    rows = []
    for y in range(max(0, y0), min(y1, len(gray) // width)):
        row = gray[y * width:(y + 1) * width]
        if sum(1 for b in row if predicate(b)) >= min_hits:
            rows.append(y)
    return (rows[0], rows[-1]) if rows else None


def row_content_frac(gray, width, y):
    """某行非白像素占比（>=240 算白）。"""
    row = gray[y * width:(y + 1) * width]
    return sum(1 for b in row if b < 240) / width


def check_layout(gray, width, height):
    """版面三段：**该有的地方有、gutter 必须是纯白**。

    早期版本用"扫出连续行范围"再比对，结果漫画末几行的暗像素被算进字幕带、
    标签带的浅灰判定又吃进了漫画像素——两个都误报。现在改成断言式：
    标签在 18–48 有浅灰字、50–70 必须干净；漫画从 72 起；1706–1744 必须干净；
    字幕 1747–1821 有黑描边；1824 以下必须干净。
    """
    def grey_hits(y):
        row = gray[y * width:(y + 1) * width]
        return sum(1 for b in row if LABEL_GREY[0] <= b <= LABEL_GREY[1])

    def dark_hits(y):
        row = gray[y * width:(y + 1) * width]
        return sum(1 for b in row if b < OUTLINE_LEVEL)

    label_rows = [y for y in range(0, 60) if grey_hits(y) >= 4]
    label = (label_rows[0], label_rows[-1]) if label_rows else None

    # 只在漫画带**之后**找字幕，否则漫画末几行的暗像素会被当成描边
    sub_scan_from = COMIC_BOTTOM_RANGE[1] + 4
    sub_rows = [y for y in range(sub_scan_from,
                                 min(SUBTITLE_BAND[1] + 30, height))
                if dark_hits(y) >= 3]
    subtitle = (sub_rows[0], sub_rows[-1]) if sub_rows else None

    def clean(y0, y1):
        return all(row_content_frac(gray, width, y) <= 0.002
                   for y in range(max(0, y0), min(y1, height)))

    checks = {
        "label_in_band": (label is not None
                          and LABEL_BAND[0] - BAND_TOL <= label[0]
                          and label[1] <= LABEL_BAND[1] + BAND_TOL),
        "gutter_above_label": clean(0, 14),
        "gutter_label_comic": clean(52, COMIC_TOP - 2),
        "comic_starts_at_top": any(row_content_frac(gray, width, y) >= 0.02
                                   for y in range(COMIC_TOP - 2, COMIC_TOP + 4)),
        "gutter_comic_subtitle": clean(COMIC_BOTTOM_RANGE[1] + 3,
                                       SUBTITLE_BAND[0] - 3),
        "subtitle_in_band": (subtitle is not None
                             and abs(subtitle[0] - SUBTITLE_BAND[0]) <= BAND_TOL
                             and abs(subtitle[1] - SUBTITLE_BAND[1]) <= BAND_TOL),
        "gutter_below_subtitle": clean(SUBTITLE_BAND[1] + 4, height),
    }
    return {"label": label, "subtitle": subtitle, "checks": checks,
            "ok": all(checks.values())}


def _band_stats(gray, width, band):
    """字幕带里的白字峰值与黑描边像素数。"""
    y0, y1 = band
    counts = [0] * 256
    total_rows = 0
    for y in range(max(0, y0), min(y1, len(gray) // width)):
        row = gray[y * width:(y + 1) * width]
        for b in row:
            counts[b] += 1
        total_rows += 1
    if not total_rows:
        return {"peak_white": 0, "outline_pixels": 0}
    peak = max(range(WHITE_LEVEL, 256), key=lambda v: counts[v])
    outline = sum(counts[:OUTLINE_LEVEL])
    return {"peak_white": peak, "outline_pixels": outline}


def parse_ass(path):
    """读 .ass：章节样式是否浅灰/右上、章节对话是否覆盖全片。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    chapter_style = None
    chapter_line = None
    for line in text.splitlines():
        if line.startswith("Style: Chapter,"):
            chapter_style = line
        elif line.startswith("Dialogue: 1,") and ",Chapter," in line:
            chapter_line = line
    info = {"has_style": chapter_style is not None,
            "has_line": chapter_line is not None,
            "grey": bool(chapter_style and "&H00999999" in chapter_style),
            "top_right": False, "end": None}
    if chapter_style:
        parts = chapter_style.split(",")
        # Format: Name, Fontname, Fontsize, ..., Alignment(第 19 项, 0 起 18)
        info["top_right"] = len(parts) > 18 and parts[18].strip() == "9"
    if chapter_line:
        parts = chapter_line.split(",", 9)
        try:
            info["end"] = _ass_ts(parts[2])
        except (IndexError, ValueError):
            pass
    return info


def _ass_ts(raw):
    hms, cs = raw.strip().split(".")
    h, m, s = (int(x) for x in hms.split(":"))
    return h * 3600 + m * 60 + s + int(cs) / 100.0


def verify_run(work_dir, out_dir, name, total_duration, script_pages,
               ffmpeg=None, ffprobe=None, width=1080, height=1920,
               sample_ratio=DEFAULT_SAMPLE_RATIO):
    """跑 15 条，返回 run_report 字典。"""
    from .panels import find_ffmpeg, find_ffprobe
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    out = Path(out_dir)
    mp4 = out / f"{name}.mp4"
    if not mp4.exists():
        raise RuntimeError(f"error: video not found: {mp4}")

    v, a, fmt = probe_streams(ffprobe, mp4)
    checks = []

    def add(idx, item, expected, actual, ok, note=""):
        checks.append({"id": idx, "item": item, "expected": expected,
                       "actual": actual, "pass": bool(ok), "note": note})

    got_w = v.get("width")
    got_h = v.get("height")
    add(1, "画布", f"{width}x{height}", f"{got_w}x{got_h}",
        (got_w, got_h) == (width, height))

    fps = _parse_fps(v.get("avg_frame_rate"))
    add(2, "帧率", "30", f"{fps}", abs(fps - 30) < 0.01)

    pix = v.get("pix_fmt")
    add(3, "像素格式", "yuv420p", f"{pix}", pix == "yuv420p")

    add(4, "有音轨", "有", "有" if a else "无", a is not None)

    vdur = v.get("duration")
    vdur = float(vdur) if vdur not in (None, "N/A") else None
    vdrift = abs(vdur - total_duration) if vdur is not None else 999
    add(5, "视频轨时长", f"{total_duration:.3f}±0.2", 
        f"{vdur:.3f}" if vdur is not None else "N/A",
        vdrift < 0.2, "走 stream=duration，不是 format=duration")

    cdur = float(fmt.get("duration", 0) or 0)
    add(6, "容器时长", f"{total_duration:.3f}±0.2", f"{cdur:.3f}",
        abs(cdur - total_duration) < 0.2)

    frames = v.get("nb_frames")
    frames = int(frames) if str(frames).isdigit() else None
    expect_frames = round((vdur or 0) * 30)
    add(7, "帧数自洽", f"≈{expect_frames}",
        f"{frames}" if frames is not None else "N/A",
        frames is not None and abs(frames - expect_frames) <= 2)

    # ---- 画面抽样三条 ----
    t = max(0.5, total_duration * sample_ratio)
    gray = frame_gray(ffmpeg, mp4, t, width, height)
    stats = _band_stats(gray, width, SUBTITLE_BAND)
    add(8, "字幕纯白", "255", f"{stats['peak_white']}",
        stats["peak_white"] >= 255, f"抽帧 t={t:.1f}s")
    add(9, "描边存在", f">{MIN_OUTLINE_PIXELS}", f"{stats['outline_pixels']}",
        stats["outline_pixels"] > MIN_OUTLINE_PIXELS, f"抽帧 t={t:.1f}s")

    layout = check_layout(gray, width, height)
    failed_layout = [k for k, v in layout["checks"].items() if not v]
    add(10, "版面三段",
        f"标签{LABEL_BAND} 漫画{COMIC_TOP}..{COMIC_BOTTOM_RANGE[1]} 字幕{SUBTITLE_BAND}",
        f"标签{layout['label']} 字幕{layout['subtitle']}"
        + (f" 不过: {','.join(failed_layout)}" if failed_layout else ""),
        layout["ok"], f"抽帧 t={t:.1f}s，±{BAND_TOL}px")

    ass = parse_ass(out / f"{name}.ass")
    ass_ok = (ass["has_style"] and ass["has_line"] and ass["grey"]
              and ass["top_right"]
              and ass["end"] is not None
              and abs(ass["end"] - total_duration) < 1.0)
    add(11, "章节标签", "右上/浅灰/覆盖全片",
        f"样式={ass['has_style']} 灰={ass['grey']} 右上={ass['top_right']} "
        f"end={ass['end']}", ass_ok)

    # ---- 时长与页序 ----
    segments = _segments_for(work_dir)
    entries = plan_page_windows({"total_duration": total_duration,
                                 "segments": segments})
    dwells = [d for _, d in entries]
    over = [round(d, 1) for d in dwells if d > MAX_DWELL]
    under = [round(d, 1) for d in dwells if d < MIN_DWELL]
    add(12, "单页停留", f"{MIN_DWELL}–{MAX_DWELL:.0f}s",
        f"min={min(dwells):.1f} max={max(dwells):.1f}",
        not over and not under,
        f"超上限 {len(over)} 页，低于下限 {len(under)} 页")

    got_pages = [p for p, _ in entries]
    seq_ok = got_pages == list(script_pages)
    add(13, "页序列", f"{len(script_pages)} 页与脚本一致",
        f"{len(got_pages)} 页" + ("（一致）" if seq_ok else "（不一致）"),
        seq_ok,
        "" if seq_ok else _first_mismatch(script_pages, got_pages))

    sync_ok, worst_page, worst_out, total_out = page_sync(
        entries, _segments_for(work_dir))
    add(14, "切页同步", f"越界 ≤{PAGE_SYNC_TOL}s",
        f"最大越界 {worst_out:.2f}s" + (f"（{worst_page}）" if worst_page else "")
        + f"，累计 {total_out:.1f}s",
        sync_ok,
        "页窗口必须落在讲这一页的段区间内，否则画面与配音脱钩")

    chars = sum(len(s.get("text") or "") for s in segments)
    per_page = chars / len(got_pages) if got_pages else 0.0
    add(15, "内容密度", f"{MIN_CHARS_PER_PAGE}–{MAX_CHARS_PER_PAGE} 字/页",
        f"{per_page:.1f} 字/页（{chars} 字 / {len(got_pages)} 页）",
        MIN_CHARS_PER_PAGE <= per_page <= MAX_CHARS_PER_PAGE,
        "按 5.7 字/秒折算约 8–16 秒/页；偏低就是内容不充实")

    failed = [c for c in checks if not c["pass"]]
    return {
        "schema": SCHEMA,
        "name": name,
        "video": str(mp4),
        "total_duration": total_duration,
        "checks": checks,
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "ok": not failed,
        "warnings": [f"#{c['id']} {c['item']}: {c['actual']}" for c in failed],
    }


def _segments_for(work_dir):
    """从 timeline.json 取段（页序列与时长）。"""
    path = Path(work_dir) / "timeline.json"
    if not path.exists():
        raise RuntimeError(f"error: timeline not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))["segments"]


def page_sync(entries, segments):
    """每个页窗口必须落在"讲这一页"的段区间内。

    返回 (ok, worst_page, worst_outside, total_outside)。越界时长 = 页窗口
    落在该页所有所属段之外的部分；一页被多段提及时按并集算，不误判。
    """
    spans = {}
    for seg in segments:
        for page in seg["pages"]:
            spans.setdefault(page, []).append((float(seg["start"]),
                                               float(seg["end"])))
    clock = 0.0
    worst_page, worst_outside, total_outside = None, 0.0, 0.0
    for page, dur in entries:
        t0, t1 = clock, clock + dur
        clock = t1
        inside = sum(max(0.0, min(t1, e) - max(t0, s))
                     for s, e in spans.get(page, []))
        outside = max(0.0, dur - inside)
        total_outside += outside
        if outside > worst_outside:
            worst_page, worst_outside = page, outside
    return (worst_outside <= PAGE_SYNC_TOL, worst_page,
            worst_outside, total_outside)


def _first_mismatch(want, got):
    for i, (a, b) in enumerate(zip(want, got)):
        if a != b:
            return f"第 {i + 1} 页：脚本 {a}，成片 {b}"
    return f"长度不同：脚本 {len(want)}，成片 {len(got)}"


def write_report(out_dir, report):
    path = Path(out_dir) / "run_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path
