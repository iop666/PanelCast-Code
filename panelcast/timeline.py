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


def build_cues(timeline, max_chars=16):
    """段 → 字幕条：段内按字符占比切分该段真实时长（不改总时长）。"""
    cues = []
    for seg in timeline["segments"]:
        parts = split_cues(seg["text"], max_chars=max_chars)
        if not parts:
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


def build_srt_from_cues(cues):
    """字幕条 → SRT（与烧进画面的分行一致，供外部播放器用）。"""
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{format_ts(cue['start'])} --> {format_ts(cue['end'])}\n"
            f"{cue['text']}\n"
        )
    return "\n".join(blocks)


def format_ass_ts(sec):
    """ASS 时间戳 H:MM:SS.cc。"""
    cs = int(round(sec * 100))
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6_000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(cues, width, height, font="Microsoft YaHei", font_size=None,
              margin_v=None):
    """生成 ASS 字幕（白字黑描边，底部居中）。

    字号/边距按画布高度比例给默认值：竖屏 1920 高约 62px 字、MarginV 150；
    横屏 1080 高约 44px 字、MarginV 60。
    """
    font_size = font_size or max(28, round(height * 0.0325))
    margin_v = margin_v or round(height * 0.075)
    outline = max(2, round(font_size * 0.075))
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
        f"Style: Default,{font},{font_size},&H00FFFFFF,&H00FFFFFF,"
        f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,2,"
        f"60,60,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    lines = []
    for cue in cues:
        text = cue["text"].replace("\n", " ").replace("{", "(").replace("}", ")")
        lines.append(
            f"Dialogue: 0,{format_ass_ts(cue['start'])},"
            f"{format_ass_ts(cue['end'])},Default,,0,0,0,,{text}"
        )
    return header + "\n".join(lines) + "\n"


def write_text_atomic(path, text):
    """temp + replace 原子写文本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
