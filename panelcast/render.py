"""S5 渲染：ffmpeg 硬切合成 MP4——无转场、无运镜。

- 画布尺寸与填充方式可配：`letterbox`（等比缩放 + 留边，不裁切）或
  `cover`（等比放大到铺满 + 居中裁切，竖屏 9:16 用这个）；
- 帧率 30，yuv420p，libx264 crf 20；
- 音频：各段 WAV concat 后统一重采样 44100，aac 混流；时长以音频为准；
- 视频轨来自 concat demuxer（末条文件按 ffmpeg 惯例重复一次）；
- 产物 m1/out/sample.mp4、m1/out/sample.srt；成片时长与 total_duration
  误差 ≥ 0.2 秒则报错退出，绝不"能播就行"。

帧缓存按 (尺寸, 填充方式, 底色, 边距) 分目录，换画布或改布局不会复用旧帧。
"""

import subprocess
from pathlib import Path

from .timeline import (
    build_ass,
    build_cues,
    build_srt_from_cues,
    page_entries,
    write_text_atomic,
)

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1920, 1080
FIT_MODES = ("letterbox", "cover", "blurpad")
BG_MODES = ("blur", "white")
# blurpad：底部留给字幕的带状区域（占画布高度比例）与四周边距（像素）
SUBTITLE_BAND_RATIO = 0.14
BLURPAD_MARGIN = 10
# 顶部留白单独加大：漫画整体略下沉，不贴画面上边缘（纯平移，不缩尺寸）
# 72 = 给右上角章节标签留出位置，相比原来的 50 只下移 22px
BLURPAD_TOP_MARGIN = 72
# 右上角章节标签：字号（占画布高度）与距顶距离
CHAPTER_FONT_RATIO = 0.021
CHAPTER_TOP_RATIO = 0.006


def fit_filter(width, height, fit="letterbox", band=0, margin=0, bg="blur",
               top=None):
    """构造 ffmpeg 缩放滤镜。

    letterbox: 整页可见，四周补白（信息完整，但画面填不满）。
    cover:     铺满画布，超出部分居中裁掉（填满画面，边缘会被裁）。
    blurpad:   整页缩小放入画面（不裁切），底部预留字幕带；
               bg="blur" 用同页模糊放大版填底，bg="white" 用纯白底。
               top 是顶部留白（默认 = margin）；只改平移量、不改 fg_h，
               所以页面不会被缩小。
    """
    if fit not in FIT_MODES:
        raise RuntimeError(f"error: unknown fit mode {fit!r}, want {FIT_MODES}")
    if bg not in BG_MODES:
        raise RuntimeError(f"error: unknown bg mode {bg!r}, want {BG_MODES}")
    if fit == "cover":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    if fit == "blurpad":
        fg_h = height - band - margin * 2
        if fg_h <= 0:
            raise RuntimeError(f"error: subtitle band {band} too tall for {height}")
        top = margin if top is None else top
        if top + fg_h > height:
            raise RuntimeError(
                f"error: top margin {top} + page height {fg_h} exceeds {height}"
            )
        if bg == "white":
            return (
                f"scale={width}:{fg_h}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:{top}:color=white"
            )
        return (
            f"split=2[bg][fg];"
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma=36,eq=brightness=-0.10[bgb];"
            f"[fg]scale={width}:{fg_h}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:{top}"
        )
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=white"
    )


def _run(cmd, what, cwd=None):
    out = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                         timeout=600, cwd=cwd)
    if out.returncode != 0:
        raise RuntimeError(
            f"error: {what} failed: {(out.stderr or out.stdout).strip()[:400]}"
        )
    return out


def prepare_frames(ffmpeg, work, pages_seq, width=DEFAULT_WIDTH,
                   height=DEFAULT_HEIGHT, fit="letterbox", ffprobe=None,
                   trim=True, bg="blur"):
    """每个出场页生成目标画布的 PNG（重复页只做一次）。

    缓存按 <宽>x<高>-<fit>-<bg>-<布局参数> 分目录，切换画布/填充/底色/边距
    都不会误用旧帧（改了布局却不换目录，会静默复用旧位置的帧）。
    trim=True 时先自动裁掉页面四周的纯色扫描边（黑边/白边），再缩放。
    """
    band = round(height * SUBTITLE_BAND_RATIO) if fit == "blurpad" else 0
    margin = BLURPAD_MARGIN if fit == "blurpad" else 0
    top = BLURPAD_TOP_MARGIN if fit == "blurpad" else 0
    frames_dir = (Path(work) / "cache" / "frames"
                  / f"{width}x{height}-{fit}-{bg}-b{band}-m{margin}-t{top}")
    frames_dir.mkdir(parents=True, exist_ok=True)
    base_vf = fit_filter(width, height, fit, band=band, margin=margin, bg=bg,
                         top=top)
    for page in dict.fromkeys(pages_seq):  # 保序去重
        src = Path(work) / "pages" / f"{page}.jpg"
        dst = frames_dir / f"{page}.png"
        if dst.exists() and dst.stat().st_size > 0:
            continue
        vf = base_vf
        if trim and ffprobe is not None:
            from .panels import detect_content_box
            x, y, cw, ch = detect_content_box(ffmpeg, ffprobe, src)
            full = probe_size_cached(ffprobe, src)
            if (cw, ch) != full:
                vf = f"crop={cw}:{ch}:{x}:{y},{base_vf}"
        _run([ffmpeg, "-v", "error", "-y", "-i", src,
              "-vf", vf, "-frames:v", "1", dst],
             f"{fit} {page}")
    return frames_dir


def probe_size_cached(ffprobe, path):
    from .panels import probe_size
    return probe_size(ffprobe, path)


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


def _parse_fps(raw):
    raw = (raw or "").strip()
    if "/" in raw:
        num, den = raw.split("/", 1)
        try:
            return round(float(num) / float(den), 2) if float(den) else 0.0
        except ValueError:
            return 0.0
    try:
        return round(float(raw), 2)
    except ValueError:
        return 0.0


def video_filters(ass_name=None):
    """渲染用滤镜链（顺序是修复两个真 bug 的结果，不要调换）。

    1. `fps=30` 必须最前：concat demuxer 对每页只吐**一帧**（时长靠 PTS 撑），
       直接交给 ass 会让字幕只在换页时变一次，看起来"完全不跟配音"。
    2. `scale` 必须在 ass **之前**：漫画帧按 full range 写入，libass 输出按
       tv 压缩，不先归一色域，字幕白会落成 235 灰（背景仍是 255），
       肉眼看到的就是"字幕不是白色"。
    """
    chain = ["fps=30", "scale=in_range=full:out_range=tv"]
    if ass_name:
        chain.append(f"ass={ass_name}")
    return ",".join(chain)


def probe_video(ffprobe, path):
    """读成片 (width, height, fps, has_audio, duration, video_duration)。

    duration 是容器时长（≈音频），video_duration 是**视频轨**时长。两者必须
    一致：concat demuxer 每页只吐一帧，若末帧没有 duration，视频轨会提前结束
    而容器时长仍按音频算——成片表现为"最后几秒画面卡住、字幕不对"。
    """
    out = _run([ffprobe, "-v", "error", "-select_streams", "v:0",
                "-show_entries",
                "stream=width,height,avg_frame_rate,duration,nb_frames",
                "-of", "default=nw=1", path], "ffprobe video stream")
    meta = {}
    for line in out.stdout.strip().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            meta[key.strip()] = value.strip()
    try:
        width, height = int(meta["width"]), int(meta["height"])
    except (KeyError, ValueError):
        raise RuntimeError(f"error: cannot parse video params: {out.stdout!r}")
    fps = _parse_fps(meta.get("avg_frame_rate"))
    vdur = meta.get("duration", "")
    if vdur and vdur != "N/A":
        video_duration = float(vdur)
    elif fps and meta.get("nb_frames", "").isdigit():
        video_duration = int(meta["nb_frames"]) / fps
    else:
        video_duration = 0.0
    audio = _run([ffprobe, "-v", "error", "-select_streams", "a:0",
                  "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                 "ffprobe audio stream")
    dur = _run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "csv=p=0", path], "ffprobe duration")
    return {
        "width": width, "height": height, "fps": fps,
        "has_audio": audio.stdout.strip() == "audio",
        "duration": float(dur.stdout.strip()),
        "video_duration": round(video_duration, 3),
    }


def render(work_dir, out_dir, timeline, ffmpeg=None, ffprobe=None,
           width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, fit="letterbox",
           burn_subs=True, bg="blur", chapter=None, name="sample"):
    """timeline → <name>.mp4 + <name>.srt + <name>.ass。失败抛 RuntimeError。

    chapter 非空时在右上角常驻一行章节标签（章节号 + 章节名）。
    """
    from .panels import find_ffmpeg, find_ffprobe
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    work = Path(work_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fit_filter(width, height, fit, bg=bg)  # 提前校验 fit/bg 取值

    if not all((work / "pages" / f"{p}.jpg").exists()
               for p in {e[0] for e in page_entries(timeline)}):
        missing = [p for p in {e[0] for e in page_entries(timeline)}
                   if not (work / "pages" / f"{p}.jpg").exists()]
        raise RuntimeError(f"error: missing page images: {', '.join(missing)}")

    entries = page_entries(timeline)
    frames_dir = prepare_frames(ffmpeg, work, [p for p, _ in entries],
                                width=width, height=height, fit=fit,
                                ffprobe=ffprobe, bg=bg)
    ffconcat = build_ffconcat(entries, frames_dir)
    write_text_atomic(frames_dir / "video.ffconcat", ffconcat)

    seg_wavs = [work / "audio" / s["audio"] for s in timeline["segments"]]
    for w in seg_wavs:
        if not w.exists() or w.stat().st_size <= 44:
            raise RuntimeError(f"error: segment audio missing: {w.name}")
    audio_concat = work / "cache" / "audio_concat.wav"
    concat_audio(ffmpeg, seg_wavs, audio_concat)

    mp4 = out / f"{name}.mp4"
    ass_name = None
    if burn_subs:
        ass_path = out / f"{name}.ass"
        write_text_atomic(ass_path, build_ass(
            build_cues(timeline), width, height,
            chapter_label=chapter,
            total_duration=timeline["total_duration"],
        ))
        # 用 cwd=out + 相对文件名，避免 Windows 盘符在滤镜参数里被当成分隔符
        ass_name = ass_path.name
    vf = ["-vf", video_filters(ass_name)]
    # cwd=out 时所有输入路径必须是绝对路径，否则会被解析到 out 目录下
    _run([ffmpeg, "-v", "error", "-y",
          "-f", "concat", "-safe", "0",
          "-i", str((frames_dir / "video.ffconcat").resolve()),
          "-i", str(audio_concat.resolve()),
          "-map", "0:v:0", "-map", "1:a:0",
          *vf,
          "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
          "-c:a", "aac", "-b:a", "160k",
          "-t", f"{timeline['total_duration']:.3f}",
          "-movflags", "+faststart", str(mp4.resolve())],
         "video render", cwd=out if burn_subs else None)

    info = probe_video(ffprobe, mp4)
    if (info["width"], info["height"]) != (width, height):
        raise RuntimeError(
            f"error: rendered size {info['width']}x{info['height']}, "
            f"want {width}x{height}"
        )
    if not info["has_audio"]:
        raise RuntimeError("error: rendered video has no audio track")
    drift = abs(info["duration"] - timeline["total_duration"])
    if drift >= 0.2:
        raise RuntimeError(
            f"error: rendered duration {info['duration']:.3f}s differs from "
            f"timeline {timeline['total_duration']:.3f}s by {drift:.3f}s"
        )
    # 容器时长够不代表视频轨够：视频轨短于音频时末段画面会卡住、字幕全错位
    vdrift = abs(info["video_duration"] - timeline["total_duration"])
    if vdrift >= 0.2:
        raise RuntimeError(
            f"error: video track {info['video_duration']:.3f}s differs from "
            f"timeline {timeline['total_duration']:.3f}s by {vdrift:.3f}s "
            f"(frames truncated)"
        )

    write_text_atomic(out / f"{name}.srt",
                      build_srt_from_cues(build_cues(timeline)))
    return info
