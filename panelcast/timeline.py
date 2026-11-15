"""S4 时间轴：由真实音频时长累加派生 start/end；SRT 一段一条；禁止按字数估算。

- 段 → 页面映射：一段覆盖 1–3 页，段内各页均分该段时长（末页吃余数，保证
  页时长之和与段时长逐字节一致），视频在该段起始时刻显示 pages[0]；
- total_duration = 最后一段的 end，与音频实际总长误差必须 < 0.05 秒；
- SRT：一段一条字幕，起止即段的起止（M1 不做词级对齐）。
"""

import json
import os
from pathlib import Path

_MAX_PAGES_PER_SEGMENT = 3


def load_script(work_dir, confirmed_pages):
    """读 work/script.json 并校验结构；不合格抛 RuntimeError（一行 error:）。"""
    path = Path(work_dir) / "script.json"
    if not path.exists():
        raise RuntimeError(f"error: script not found: {path}")
    try:
        script = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"error: bad script.json: {exc}")
    segs = script.get("segments")
    if not isinstance(segs, list) or not segs:
        raise RuntimeError("error: script.json has no segments")
    seen_ids = set()
    for i, seg in enumerate(segs):
        seg_id = seg.get("id") or f"seg_{i + 1:04d}"
        seg["id"] = seg_id
        if seg_id in seen_ids:
            raise RuntimeError(f"error: duplicate segment id {seg_id}")
        seen_ids.add(seg_id)
        text = seg.get("text", "")
        if not text.strip():
            raise RuntimeError(f"error: segment {seg_id} has empty text")
        pages = seg.get("pages") or []
        if not 1 <= len(pages) <= _MAX_PAGES_PER_SEGMENT:
            raise RuntimeError(
                f"error: segment {seg_id} covers {len(pages)} pages, want 1-3"
            )
        unknown = [p for p in pages if p not in confirmed_pages]
        if unknown:
            raise RuntimeError(
                f"error: segment {seg_id} references unconfirmed pages: "
                + ", ".join(unknown)
            )
    return script


def build_timeline(script, audio_results, backend_info, ffmpeg_path):
    """audio_results 与 script 顺序一致（见 tts.synth_segments）。

    timeline.json 结构见任务书 3.2，另附 voice / ffmpeg 字段（S0 要求记录）。
    """
    segments = []
    clock = 0.0
    for seg, audio in zip(script["segments"], audio_results):
        if audio["id"] != seg["id"]:
            raise RuntimeError(
                f"error: audio/script order mismatch at {seg['id']} vs {audio['id']}"
            )
        duration = round(audio["duration"], 3)
        start = round(clock, 3)
        end = round(clock + duration, 3)
        segments.append({
            "id": seg["id"],
            "text": seg["text"],
            "audio": Path(audio["file"]).name,
            "duration": duration,
            "start": start,
            "end": end,
            "pages": list(seg["pages"]),
            # 真实句边界（edge-tts 提供）；SAPI5 没有，为空时字幕按字数比例
            "sentences": list(audio.get("sentences") or []),
        })
        clock += duration
    total = round(clock, 3)
    declared = round(sum(s["duration"] for s in segments), 3)
    if abs(total - declared) >= 0.05:
        raise RuntimeError(
            f"error: timeline total {total} differs from audio sum {declared}"
        )
    return {
        "tts_backend": backend_info["backend"],
        "voice": backend_info["voice"],
        "ffmpeg": str(ffmpeg_path),
        "total_duration": total,
        "segments": segments,
    }


def page_entries(timeline):
    """视频轨页面序列：段内各页均分时长，末页吃余数。

    返回 [(page, duration)]，总长 == total_duration。
    """
    entries = []
    for seg in timeline["segments"]:
        pages = seg["pages"]
        per = seg["duration"] / len(pages)
        used = 0.0
        for i, page in enumerate(pages):
            if i < len(pages) - 1:
                d = round(per, 3)
                used += d
            else:
                d = round(seg["duration"] - used, 3)
            entries.append((page, d))
    total = round(sum(d for _, d in entries), 3)
    if abs(total - timeline["total_duration"]) >= 0.05:
        raise RuntimeError(
            f"error: page entries total {total} != total_duration "
            f"{timeline['total_duration']}"
        )
    return entries


#: 页面停留的硬边界：低于 MIN 会闪、高于 MAX 会闷（§1.2 与 §13 坑 12）
MIN_DWELL = 3.5
MAX_DWELL = 18.0
#: 切页点吸附到句子边界的最大位移（秒）
SNAP_WINDOW = 2.0


def _snap_points(timeline):
    """可吸附的时间点：段边界 + 每句的句首/句尾。"""
    pts = set()
    for seg in timeline["segments"]:
        pts.add(round(seg["start"], 3))
        pts.add(round(seg["end"], 3))
        for sent in seg.get("sentences") or []:
            try:
                off = float(sent["offset"])
                dur = float(sent["duration"])
            except (KeyError, TypeError, ValueError):
                continue
            pts.add(round(seg["start"] + off, 3))
            pts.add(round(seg["start"] + off + dur, 3))
    return sorted(pts)


def plan_page_windows(timeline, snap=SNAP_WINDOW, min_dwell=MIN_DWELL,
                      max_dwell=MAX_DWELL, strict=False):
    """整片页面停留均衡：每页 ≈ 总时长/页数，切页点吸附到句子边界。

    为什么要它：按段分配页时长时，一段只挂 1 页但字数多，那页就停留 15–18 秒
    （实测第一章有 4 页超过 17s），观感发闷；反过来短段只停 2 秒会闪。
    这里改成全局均衡——页序不变，但**切页时刻独立于段边界**，允许一页跨段、
    一段换多页。字幕仍按段走，两者互不干扰。

    页数太少（每页 > max_dwell）时不硬报错：这是内容问题不是代码问题，
    由 S9 第 12 条如实报出来。`strict=True` 才会抛错（给 CI 用）。

    返回 [(page, duration)]，总长严格等于 total_duration。
    """
    pages = [p for seg in timeline["segments"] for p in seg["pages"]]
    total = round(timeline["total_duration"], 3)
    n = len(pages)
    if n == 0:
        raise RuntimeError("error: timeline has no pages")

    nominal = total / n
    if nominal > max_dwell and strict:
        raise RuntimeError(
            f"error: {n} pages over {total:.1f}s = {nominal:.1f}s per page, "
            f"above the {max_dwell:.0f}s ceiling; add pages or cut text"
        )
    if n == 1:
        return [(pages[0], total)]

    pts = _snap_points(timeline)
    bounds = [0.0]
    for i in range(1, n):
        ideal = total * i / n
        if pts and snap > 0:
            near = min(pts, key=lambda c: abs(c - ideal))
            if abs(near - ideal) <= snap:
                ideal = near
        bounds.append(ideal)
    bounds.append(total)

    # 单调 + 最小停留：吸附可能把两个切点挤到一起，挤到就退回均分
    for i in range(1, len(bounds)):
        if bounds[i] - bounds[i - 1] < min_dwell:
            bounds[i] = bounds[i - 1] + nominal
    bounds[-1] = total
    if any(bounds[i] <= bounds[i - 1] for i in range(1, len(bounds))):
        bounds = [total * i / n for i in range(n)] + [total]

    entries = []
    for i, page in enumerate(pages):
        dur = round(bounds[i + 1] - bounds[i], 3)
        if i == n - 1:
            dur = round(total - sum(d for _, d in entries), 3)
        entries.append((page, dur))
    drift = abs(round(sum(d for _, d in entries), 3) - total)
    if drift >= 0.05:
        raise RuntimeError(
            f"error: balanced page windows drift {drift:.3f}s from timeline"
        )
    return entries


def format_ts(sec):
    """SRT 时间戳 HH:MM:SS,mmm。"""
    ms = int(round(sec * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(timeline):
    """一段一条字幕（供外部播放器用，不烧进画面）。"""
    blocks = []
    for i, seg in enumerate(timeline["segments"], 1):
        blocks.append(
            f"{i}\n{format_ts(seg['start'])} --> {format_ts(seg['end'])}\n"
            f"{seg['text']}\n"
        )
    return "\n".join(blocks)


_SENT_END = "。！？…；"
_SOFT_BREAK = "，、：—"


def _tokens(text):
    """按标点切成词块（标点跟随前块）。"""
    toks, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _SENT_END or ch in _SOFT_BREAK:
            toks.append(buf)
            buf = ""
    if buf:
        toks.append(buf)
    return toks


def split_cues(text, max_chars=16, min_chars=6):
    """把一段长文本切成适合单行显示的短句。

    先按标点切词块，再贪心打包到 <= max_chars；过长的词块硬切；过短的尾块
    并入前一块。目标是让每条字幕长度接近，避免 2 个字闪 0.3 秒那种跳字。
    仅用于**字幕分行**，不改变任何时长计算。
    """
    text = (text or "").strip()
    if not text:
        return []

    pieces = []
    for tok in _tokens(text):
        if len(tok) <= max_chars:
            pieces.append(tok)
            continue
        # 超长词块均衡切分（而非切满 max_chars 留个 3 字尾巴）
        n = -(-len(tok) // max_chars)
        size = -(-len(tok) // n)
        pieces.extend(tok[i:i + size] for i in range(0, len(tok), size))

    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + len(p) > max_chars:
            chunks.append(cur)
            cur = p
        else:
            cur += p
    if cur:
        chunks.append(cur)

    merged = []
    for c in chunks:                          # 短块并入前块，减少闪烁
        if merged and len(c) < min_chars and len(merged[-1]) + len(c) <= max_chars + 4:
            merged[-1] += c
        else:
            merged.append(c)
    return merged


def _anchors(text, seg_start, sentences):
    """用真实句边界建 (字符位置, 时间) 锚点表；数据不可用时返回 None。

    每句给出两个锚点：句首（前一句之后的停顿结束）与句尾。锚点之间线性插值，
    等于把"句内按字数"和"句间按真实停顿"两件事分开处理——这正是按字数比例
    分配会跑偏的地方（长停顿被平摊掉了）。
    """
    if not text or not sentences:
        return None
    anchors, cum = [], 0
    for sent in sentences:
        stext = sent.get("text") or ""
        if not stext:
            continue
        try:
            off = float(sent["offset"])
            dur = float(sent["duration"])
        except (KeyError, TypeError, ValueError):
            return None
        anchors.append((cum, seg_start + off))
        cum += len(stext)
        anchors.append((cum, seg_start + off + dur))
    if not anchors or cum <= 0:
        return None
    if cum != len(text):
        # 句文本长度之和与整段不一致（数字/标点被 TTS 归一化过）→ 拉伸字符轴
        scale = len(text) / cum
        anchors = [(round(c * scale), t) for c, t in anchors]
    # 同一字符位置可能出两个锚点（句尾与下句句首），保留较晚的时间
    merged = []
    for c, t in anchors:
        if merged and c <= merged[-1][0]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], t))
        else:
            merged.append((c, t))
    # 时间必须单调（句间偶尔有 1~2 帧重叠，夹紧即可，不要整段放弃）
    for i in range(1, len(merged)):
        if merged[i][1] < merged[i - 1][1]:
            merged[i] = (merged[i][0], merged[i - 1][1])
    return merged


def _char_time(anchors, x):
    """锚点表插值：字符位置 → 时间。"""
    if x <= anchors[0][0]:
        return anchors[0][1]
    for (c0, t0), (c1, t1) in zip(anchors, anchors[1:]):
        if c0 <= x <= c1:
            return t1 if c1 == c0 else t0 + (t1 - t0) * (x - c0) / (c1 - c0)
    return anchors[-1][1]


def build_cues(timeline, max_chars=16):
    """段 → 字幕条：优先按真实句边界对时，缺失时退回按字数占比。

    两种方式都不改总时长：首条起于段首、末条止于段尾，条与条首尾相接。
    """
    cues = []
    for seg in timeline["segments"]:
        parts = split_cues(seg["text"], max_chars=max_chars)
        if not parts:
            continue
        anchors = _anchors(seg["text"], seg["start"], seg.get("sentences"))
        if anchors:
            bounds = [seg["start"]]
            pos = 0
            for part in parts[:-1]:
                pos += len(part)
                bounds.append(_char_time(anchors, pos))
            bounds.append(seg["end"])
            for i in range(1, len(bounds)):      # 夹紧，防零/负长度
                bounds[i] = max(bounds[i], bounds[i - 1])
            for i, part in enumerate(parts):
                cues.append({"start": bounds[i], "end": bounds[i + 1],
                             "text": part})
            continue
        total = sum(len(p) for p in parts)
        start = seg["start"]
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                end = seg["end"]          # 末条吃余数，保证无缝衔接
            else:
                end = start + seg["duration"] * len(part) / total
            cues.append({"start": start, "end": end, "text": part})
            start = end
    return cues


STRIP_CHARS = "，。"


def clean_display(text, strip=STRIP_CHARS):
    """字幕显示用：去掉逗号/句号这类纯停顿标点（句读靠换条表达）。

    只影响**显示文本**，不影响分句与时长计算。
    """
    return "".join(ch for ch in text if ch not in strip)


def build_srt_from_cues(cues, strip=STRIP_CHARS):
    """字幕条 → SRT（与烧进画面的分行一致，供外部播放器用）。"""
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{format_ts(cue['start'])} --> {format_ts(cue['end'])}\n"
            f"{clean_display(cue['text'], strip)}\n"
        )
    return "\n".join(blocks)


def format_ass_ts(sec):
    """ASS 时间戳 H:MM:SS.cc。"""
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6_000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape_ass(text):
    """ASS 文本转义：换行压成空格，大括号会被当成覆盖标签。"""
    return str(text).replace("\n", " ").replace("{", "(").replace("}", ")")


def build_ass(cues, width, height, font="Microsoft YaHei", font_size=None,
              margin_v=None, strip=STRIP_CHARS, chapter_label=None,
              chapter_size=None, chapter_top=None, total_duration=None):
    """生成 ASS 字幕（白字黑描边，底部居中）+ 右上角章节标签。

    字号/边距按画布高度比例给默认值：竖屏 1920 高约 77px 字、MarginV 100；
    横屏 1080 高约 43px 字、MarginV 56。strip 里的标点不进画面。
    chapter_label 非空时在右上角（Alignment=9）加一行浅灰小字，常驻全片。
    """
    font_size = font_size or max(28, round(height * 0.040))
    margin_v = margin_v if margin_v is not None else round(height * 0.052)
    outline = max(2, round(font_size * 0.075))
    margin_h = round(width * 0.03)
    chapter_size = chapter_size or max(18, round(height * 0.021))
    chapter_top = chapter_top if chapter_top is not None else round(height * 0.006)
    styles = (
        f"Style: Default,{font},{font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"{margin_h},{margin_h},{margin_v},1\n"
    )
    if chapter_label:
        # 浅灰（&H00999999）、不加粗、无描边，压在顶部留白里不抢画面
        styles += (
            f"Style: Chapter,{font},{chapter_size},&H00999999,&H00999999,"
            f"&H00FFFFFF,&H00000000,0,0,0,0,100,100,0,0,1,0,0,9,"
            f"{margin_h},{margin_h},{chapter_top},1\n"
        )
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"          # 不自动换行（已按字数切好）
        "ScaledBorderAndShadow: yes\n"
        "YCbCr Matrix: TV.709\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + styles +
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = []
    if chapter_label:
        end = total_duration if total_duration else (cues[-1]["end"] if cues else 0)
        lines.append(
            f"Dialogue: 1,{format_ass_ts(0)},{format_ass_ts(end)},Chapter,,"
            f"0,0,0,,{_escape_ass(chapter_label)}"
        )
    for cue in cues:
        text = clean_display(cue["text"], strip)
        lines.append(
            f"Dialogue: 0,{format_ass_ts(cue['start'])},"
            f"{format_ass_ts(cue['end'])},Default,,0,0,0,,{_escape_ass(text)}"
        )
    return header + "\n".join(lines) + "\n"


def write_text_atomic(path, text):
    """temp + replace 原子写文本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
