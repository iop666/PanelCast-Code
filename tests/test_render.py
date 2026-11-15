"""render.py 单元测试：ffconcat 清单、命令构建 + 小样真渲染（需 ffmpeg）。"""

import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from panelcast.panels import _KNOWN_BIN, find_ffprobe
from panelcast.render import build_ffconcat, probe_video, render

FFMPEG = _KNOWN_BIN / "ffmpeg.exe"
_FFMPEG_OK = FFMPEG.exists()


def _timeline(pages_per_seg=((1.0, ("page_0001",)), (0.5, ("page_0001", "page_0002")))):
    """构造小 timeline：音频时长 = 页时长之和（真实 WAV 由测试生成）。"""
    segments = []
    clock = 0.0
    i = 0
    for dur, pages in pages_per_seg:
        i += 1
        segments.append({
            "id": f"seg_{i:04d}", "text": f"第{i}段",
            "audio": f"seg_{i:04d}.wav", "duration": dur,
            "start": round(clock, 3), "end": round(clock + dur, 3),
            "pages": list(pages),
        })
        clock += dur
    return {
        "tts_backend": "sapi5:test", "voice": "test", "ffmpeg": "unused",
        "total_duration": round(clock, 3), "segments": segments,
    }


def _write_wav(path, seconds, rate=8000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))


class TestFfconcat(unittest.TestCase):
    def test_manifest_and_last_repeat(self):
        text = build_ffconcat([("page_0001", 1.5), ("page_0002", 0.25)],
                              Path("frames"))
        self.assertIn("ffconcat version 1.0", text)
        self.assertIn("file 'page_0001.png'", text)
        self.assertIn("duration 1.500", text)
        self.assertIn("duration 0.250", text)
        # 末条文件重复一次（ffmpeg 惯例：最后一条 duration 才生效）
        self.assertEqual(text.count("file 'page_0002.png'"), 2)


@unittest.skipUnless(FFMPEG.exists(), "ffmpeg not available")
class TestRenderSmoke(unittest.TestCase):
    def test_two_frame_render_with_real_audio(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "work"
            out = Path(td) / "out"
            (work / "pages").mkdir(parents=True)
            (work / "audio").mkdir()
            # 两页 8×8 源图（用 ffmpeg 生成，内容各异：黑/白）
            for i, color in enumerate(("black", "white"), 1):
                src = work / "pages" / f"page_{i:04d}.jpg"
                subprocess.run(
                    [str(FFMPEG), "-v", "error", "-y", "-f", "lavfi",
                     "-i", f"color={color}:size=8x8", "-frames:v", "1",
                     str(src)],
                    capture_output=True, check=True)
            # 真实 WAV（0.3s + 0.2s）
            _write_wav(work / "audio" / "seg_0001.wav", 0.3)
            _write_wav(work / "audio" / "seg_0002.wav", 0.2)
            tl = _timeline(((0.3, ("page_0001",)), (0.2, ("page_0001", "page_0002"))))
            info = render(work, out, tl, ffmpeg=FFMPEG, ffprobe=find_ffprobe())
            self.assertEqual((info["width"], info["height"]), (1920, 1080))
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["duration"], 0.5, delta=0.2)
            self.assertTrue((out / "sample.mp4").exists())
            self.assertTrue((out / "sample.srt").exists())
            # ffprobe 独立复验
            params = probe_video(find_ffprobe(), out / "sample.mp4")
            self.assertEqual(params["width"], 1920)

    def test_render_fails_on_missing_audio(self):
        with tempfile.TemporaryDirectory() as td:
            work = Path(td) / "work"
            out = Path(td) / "out"
            (work / "pages").mkdir(parents=True)
            (work / "pages" / "page_0001.jpg").write_bytes(b"x")
            tl = _timeline(((1.0, ("page_0001",)),))
            with self.assertRaises(RuntimeError):
                render(work, out, tl, ffmpeg=FFMPEG, ffprobe=find_ffprobe())


if __name__ == "__main__":
    unittest.main()
