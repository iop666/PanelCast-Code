"""S5 渲染：ffmpeg 硬切合成 1080p MP4——白底 letterbox、无转场、无运镜。

- 画布 1920×1080，页面等比缩放居中（不裁切），帧率 30，yuv420p，libx264 crf 20；
- 音频：各段 WAV concat 后统一重采样 44100，aac 混流；时长以音频为准；
- 视频轨来自 concat demuxer（末条文件按 ffmpeg 惯例重复一次）；
- 产物 m1/out/sample.mp4、m1/out/sample.srt；成片时长与 total_duration
  误差 ≥ 0.2 秒则报错退出，绝不"能播就行"。
"""

import subprocess
from pathlib import Path

from .timeline import build_srt, page_entries, write_text_atomic

_WIDTH, _HEIGHT = 1920, 1080
_VF_LETTERBOX = (
    f"scale={_WIDTH}:{_HEIGHT}:force_original_aspect_ratio=decrease,"
    f"pad={_WIDTH}:{_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=white"
)


def _run(cmd, what):
    out = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                         timeout=600)
    if out.returncode != 0:
        raise RuntimeError(
            f"error: {what} failed: {(out.stderr or out.stdout).strip()[:400]}"
        )
    return out


def prepare_frames(ffmpeg, work, pages_seq):
    """每个出场页生成 1920×1080 白底 letterbox PNG（重复页只做一次）。"""
    frames_dir = Path(work) / "cache" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for page in dict.fromkeys(pages_seq):  # 保序去重
        src = Path(work) / "pages" / f"{page}.jpg"
        dst = frames_dir / f"{page}.png"
        if dst.exists() and dst.stat().st_size > 0:
            continue
        _run([ffmpeg, "-v", "error", "-y", "-i", src,
              "-vf", _VF_LETTERBOX, "-frames:v", "1", dst],
             f"letterbox {page}")
    return frames_dir


def build_ffconcat(entries, frames_dir):
    """concat demuxer 清单：逐页硬切；末条文件重复一次（ffmpeg 惯例）。"""
    lines = ["ffconcat version 1.0"]
    for page, dur in entries:
        lines.append(f"file '{page}.png'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{entries[-1][0]}.png'")
    return "\n".join(lines) + "\n"


def concat_audio(ffmpeg, wavs, dst):
    """各段 WAV 拼接 + 统一 44100（pcm_s16le）。"""
    inputs = []
    for w in wavs:
        inputs += ["-i", str(w)]
    n = len(wavs)
    if n == 1:
        cmd = [ffmpeg, "-v", "error", "-y", *inputs, "-ar", "44100",
               "-ac", "1", "-sample_fmt", "s16", str(dst)]
    else:
        cmd = [ffmpeg, "-v", "error", "-y", *inputs, "-filter_complex",
               f"concat=n={n}:v=0:a=1[cat];[cat]aresample=44100[aout]",
               "-map", "[aout]", "-ac", "1", "-sample_fmt", "s16", str(dst)]
    _run(cmd, "audio concat")


def probe_video(ffprobe, path):
    """读成片 (width, height, fps, has_audio, duration)。"""
    out = _run([ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,avg_frame_rate",
                "-of", "csv=p=0", path], "ffprobe video stream")
    try:
        w, h, fps = out.stdout.strip().splitlines()[0].split(",")
        if "/" in fps:
            num, den = fps.split("/")
            fps = float(num) / float(den) if float(den) else 0.0
        else:
            fps = float(fps)
        fps = round(fps, 2)
    except ValueError:
        raise RuntimeError(f"error: cannot parse video params: {out.stdout!r}")
    audio = _run([ffprobe, "-v", "error", "-select_streams", "a:0",
                  "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                 "ffprobe audio stream")
    dur = _run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path], "ffprobe duration")
    return {
        "width": int(w), "height": int(h), "fps": fps,
        "has_audio": audio.stdout.strip() == "audio",
        "duration": float(dur.stdout.strip()),
    }


def render(work_dir, out_dir, timeline, ffmpeg=None, ffprobe=None):
    """timeline → sample.mp4 + sample.srt。失败抛 RuntimeError（一行 error:）。"""
    from .panels import find_ffmpeg, find_ffprobe
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    work = Path(work_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not all((work / "pages" / f"{p}.jpg").exists()
               for p in {e[0] for e in page_entries(timeline)}):
        missing = [p for p in {e[0] for e in page_entries(timeline)}
                   if not (work / "pages" / f"{p}.jpg").exists()]
        raise RuntimeError(f"error: missing page images: {', '.join(missing)}")

    entries = page_entries(timeline)
    frames_dir = prepare_frames(ffmpeg, work, [p for p, _ in entries])
    ffconcat = build_ffconcat(entries, frames_dir)
    write_text_atomic(frames_dir / "video.ffconcat", ffconcat)

    seg_wavs = [work / "audio" / s["audio"] for s in timeline["segments"]]
    for w in seg_wavs:
        if not w.exists() or w.stat().st_size <= 44:
            raise RuntimeError(f"error: segment audio missing: {w.name}")
    audio_concat = work / "cache" / "audio_concat.wav"
    concat_audio(ffmpeg, seg_wavs, audio_concat)

    mp4 = out / "sample.mp4"
    # 时长以音频为准：显式 -t 硬切（任务书 S5 允许 -shortest 或显式 -t）
    _run([ffmpeg, "-v", "error", "-y",
          "-f", "concat", "-safe", "0", "-i", str(frames_dir / "video.ffconcat"),
          "-i", str(audio_concat),
          "-map", "0:v:0", "-map", "1:a:0",
          "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
          "-c:a", "aac", "-b:a", "160k",
          "-t", f"{timeline['total_duration']:.3f}",
          "-movflags", "+faststart", str(mp4)],
         "video render")

    info = probe_video(ffprobe, mp4)
    if (info["width"], info["height"]) != (_WIDTH, _HEIGHT):
        raise RuntimeError(
            f"error: rendered size {info['width']}x{info['height']}, "
            f"want {_WIDTH}x{_HEIGHT}"
        )
    if not info["has_audio"]:
        raise RuntimeError("error: rendered video has no audio track")
    drift = abs(info["duration"] - timeline["total_duration"])
    if drift >= 0.2:
        raise RuntimeError(
            f"error: rendered duration {info['duration']:.3f}s differs from "
            f"timeline {timeline['total_duration']:.3f}s by {drift:.3f}s"
        )

    write_text_atomic(out / "sample.srt", build_srt(timeline))
    return info
