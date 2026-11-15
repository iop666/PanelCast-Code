"""S3 TTS：edge-tts（若已装且网络通）→ Windows SAPI5（PowerShell System.Speech）。

- 输出 WAV + 真实时长（wave 模块读头，不做任何估算）
- 缓存键 sha256(text + "\\0" + voice + "\\0" + rate + "\\0" + backend)；命中直接复用，
  同段文本改动只重算该段
- cache/tts_index.json 记录 键 → 文件名 + 时长 + 合成时间（原子写）
- 合成失败抛 RuntimeError（一行 error: ...），绝不写 0 字节文件充数
"""

import asyncio
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import wave
from datetime import UTC, datetime
from pathlib import Path

_SAPI_PS_TEMPLATE = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.SelectVoice('{voice}'); "
    "$s.Rate = {rate}; "
    "$s.SetOutputToWaveFile('{out}'); "
    "$t = [System.IO.File]::ReadAllText('{txt}', [System.Text.Encoding]::UTF8); "
    "$s.Speak($t); "
    "$s.Dispose()"
)
_PREFERRED_SAPI_VOICES = ("Microsoft Huihui Desktop",)


def _ps_quote(s):
    return str(s).replace("'", "''")


def list_sapi_voices():
    """已安装的 SAPI5 音色名（PowerShell 枚举）。"""
    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
        ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        return []
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]


def _sapi_synthesize(text, voice, rate, out_path):
    """SAPI5 → WAV（22050 Hz 16bit mono，由 System.Speech 决定）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        txt = Path(td) / "text.txt"
        txt.write_text(text, encoding="utf-8")
        ps = _SAPI_PS_TEMPLATE.format(
            voice=_ps_quote(voice), rate=int(rate),
            out=_ps_quote(out_path), txt=_ps_quote(txt),
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=300,
        )
    if out.returncode != 0 or not out_path.exists() or out_path.stat().st_size <= 44:
        raise RuntimeError(
            f"error: SAPI5 synthesis failed (voice={voice}): "
            f"{out.stderr.strip() or 'empty output'}"
        )


def _edge_synthesize(text, voice, out_path, ffmpeg, rate="+0%"):
    """edge-tts → mp3 → ffmpeg 转 WAV（仅当 edge-tts 已安装且网络通时可达）。"""
    import edge_tts  # noqa: 仅探测成功后才 import

    tmp_mp3 = out_path.with_suffix(".tmp.mp3")

    async def _save():
        # 必须写到 tmp_mp3：edge-tts 产出的是 mp3，直接写 out_path 会让下面的
        # ffmpeg 找不到输入（曾因此静默回退到 SAPI5）。
        await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp_mp3))

    try:
        asyncio.run(asyncio.wait_for(_save(), timeout=60))
        conv = subprocess.run(
            [str(ffmpeg), "-v", "error", "-y", "-i", str(tmp_mp3),
             "-ar", "22050", "-ac", "1", "-sample_fmt", "s16", str(out_path)],
            capture_output=True, text=True, timeout=120,
        )
        if conv.returncode != 0 or not out_path.exists() or out_path.stat().st_size <= 44:
            raise RuntimeError(f"error: edge-tts conversion failed: {conv.stderr.strip()}")
    finally:
        with contextlib.suppress(OSError):
            tmp_mp3.unlink()


def wav_duration(path):
    """从 WAV 头读真实时长（秒）；失败抛 RuntimeError。"""
    try:
        with wave.open(str(path)) as w:
            rate = w.getframerate()
            frames = w.getnframes()
    except Exception as exc:
        raise RuntimeError(f"error: cannot read WAV header {path}: {exc}")
    if rate <= 0:
        raise RuntimeError(f"error: bad WAV sample rate in {path}")
    return frames / rate


def probe_backend(ffmpeg=None, voice=None, rate=None):
    """按 2.2 顺序探测：edge-tts → SAPI5。返回 {backend, voice, rate}。

    voice/rate 可显式指定（edge-tts 音色如 zh-CN-YunxiNeural，rate 如 "+20%"）；
    未指定时用默认晓晓 + 原速。SAPI5 无多音色可选，voice 仅作参考。
    """
    ffmpeg = ffmpeg or None
    # 1) edge-tts：已装且网络通
    try:
        import importlib.util
        if importlib.util.find_spec("edge_tts") is not None:
            voice = voice or "zh-CN-XiaoxiaoNeural"
            rate = rate or "+0%"
            probe_path = Path(tempfile.gettempdir()) / "panelcast-tts-edge-probe.wav"
            _edge_synthesize("测试", voice, probe_path,
                             ffmpeg or _lazy_ffmpeg(), rate=rate)
            if wav_duration(probe_path) > 0:
                with contextlib.suppress(OSError):
                    probe_path.unlink()
                return {"backend": f"edge-tts:{voice}", "voice": voice, "rate": rate}
    except Exception:
        pass  # 网络/包不可用 → 回退 SAPI5
    # 2) SAPI5
    voices = list_sapi_voices()
    if voices:
        chosen = next((v for v in _PREFERRED_SAPI_VOICES if v in voices), None)
        if chosen is None:
            chosen = next((v for v in voices if v.startswith("Microsoft")), voices[0])
        probe_path = Path(tempfile.gettempdir()) / "panelcast-tts-sapi-probe.wav"
        with contextlib.suppress(OSError):
            probe_path.unlink()
        _sapi_synthesize("测试", chosen, 0, probe_path)
        if wav_duration(probe_path) <= 0:
            raise RuntimeError("error: SAPI5 probe produced empty audio")
        with contextlib.suppress(OSError):
            probe_path.unlink()
        return {"backend": f"sapi5:{chosen}", "voice": chosen, "rate": 0}
    raise RuntimeError("error: no TTS backend available (edge-tts offline, no SAPI5 voice)")


def _lazy_ffmpeg():
    from .panels import find_ffmpeg
    return find_ffmpeg()


def cache_key(text, backend, voice, rate):
    """缓存键：sha256(text + voice + rate + backend)，分隔符防拼接歧义。"""
    material = "\x00".join((text, str(voice), str(rate), backend))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _load_index(cache_dir):
    path = cache_dir / "tts_index.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")), path
        except (OSError, ValueError):
            pass  # 坏索引当空处理，重新积累
    return {}, path


def _save_index(path, index):
    """原子写索引（temp + replace）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def synth_segments(work_dir, script, backend_info, ffmpeg=None):
    """按讲稿逐段合成/取缓存。

    script: {"segments": [{"id": "seg_0001", "text": ..., "pages": [...]}, ...]}
    返回 [{id, text, file(Path), duration(float), cached(bool)}]，顺序与讲稿一致。
    任一段合成失败即抛 RuntimeError，不写空文件。
    """
    work = Path(work_dir)
    audio_dir = work / "audio"
    cache_dir = work / "cache"
    audio_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    index, index_path = _load_index(cache_dir)
    backend, voice, rate = (
        backend_info["backend"], backend_info["voice"], backend_info["rate"]
    )
    results = []
    dirty = False
    for seg in script["segments"]:
        seg_id = seg["id"]
        text = seg["text"]
        if not text.strip():
            raise RuntimeError(f"error: segment {seg_id} has empty text")
        key = cache_key(text, backend, voice, rate)
        entry = index.get(key)
        target = audio_dir / f"{seg_id}.wav"
        if entry and entry.get("file"):
            cached = audio_dir / entry["file"]
            if cached.exists() and cached.stat().st_size > 44:
                duration = wav_duration(cached)
                if not target.exists() or target.resolve() != cached.resolve():
                    _copy_atomic(cached, target)
                results.append({
                    "id": seg_id, "text": text, "file": target,
                    "duration": duration, "cached": True,
                })
                continue
        # 未命中 → 真实合成
        if backend.startswith("edge-tts:"):
            _edge_synthesize(text, voice, target, ffmpeg or _lazy_ffmpeg(),
                             rate=str(rate))
        else:
            _sapi_synthesize(text, voice, rate, target)
        if not target.exists() or target.stat().st_size <= 44:
            raise RuntimeError(f"error: synthesis produced no audio for {seg_id}")
        duration = wav_duration(target)
        if duration <= 0:
            raise RuntimeError(f"error: zero-length audio for {seg_id}")
        index[key] = {
            "file": target.name,
            "duration": round(duration, 3),
            "backend": backend,
            "voice": voice,
            "chars": len(text),
            "synthesized_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        dirty = True
        results.append({
            "id": seg_id, "text": text, "file": target,
            "duration": duration, "cached": False,
        })
    if dirty:
        _save_index(index_path, index)
    return results


def _copy_atomic(src, dst):
    """把缓存文件复制到位（temp + replace，避免半文件）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_bytes(src.read_bytes())
    os.replace(tmp, dst)


if __name__ == "__main__":  # 手工自检入口：python -m panelcast.tts
    info = probe_backend()
    print(json.dumps(info, ensure_ascii=False))
    sys.exit(0)
