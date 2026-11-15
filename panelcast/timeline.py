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
    """一段一条字幕。"""
    blocks = []
    for i, seg in enumerate(timeline["segments"], 1):
        blocks.append(
            f"{i}\n{format_ts(seg['start'])} --> {format_ts(seg['end'])}\n"
            f"{seg['text']}\n"
        )
    return "\n".join(blocks)


def write_text_atomic(path, text):
    """temp + replace 原子写文本。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
