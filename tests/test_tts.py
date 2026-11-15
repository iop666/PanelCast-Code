"""tts.py 单元测试：WAV 头真实时长、缓存键稳定性、缓存命中与局部重算。"""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

from panelcast import tts

BACKEND = {
    "backend": "sapi5:Microsoft Huihui Desktop",
    "voice": "Microsoft Huihui Desktop",
    "rate": 0,
}


def _write_wav(path, seconds=0.5, rate=8000, fill=""):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        if fill:
            frame = ((hash(fill) % 65535) + 1).to_bytes(2, "little")
            frames = frame * int(rate * seconds)
        else:
            frames = b"\x00\x00" * int(rate * seconds)
        w.writeframes(frames)


class TestWavDuration(unittest.TestCase):
    def test_wav_duration_real_header(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.wav"
            _write_wav(p, seconds=0.75, rate=8000)
            self.assertAlmostEqual(tts.wav_duration(p), 0.75, places=3)

    def test_wav_duration_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.wav"
            p.write_bytes(struct.pack(">4sI", b"RIFX", 0))
            with self.assertRaises(RuntimeError):
                tts.wav_duration(p)


class TestCacheKey(unittest.TestCase):
    def test_key_stable_and_text_sensitive(self):
        k1 = tts.cache_key("同一段文本", "sapi5:v", 0, "sapi5:Microsoft Huihui Desktop")
        k2 = tts.cache_key("同一段文本", "sapi5:v", 0, "sapi5:Microsoft Huihui Desktop")
        k3 = tts.cache_key("改动后的文本", "sapi5:v", 0, "sapi5:Microsoft Huihui Desktop")
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)


class TestSynthSegments(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.work = Path(self._tmp.name)
        self.calls = []
        self._orig = tts._sapi_synthesize

        def fake_synth(text, voice, rate, out_path):
            self.calls.append(text)
            # 内容随文本变化，以便断言"改文本 → 音频字节变化"
            _write_wav(out_path, seconds=0.5, rate=8000, fill=text)

        tts._sapi_synthesize = fake_synth
        self.addCleanup(setattr, tts, "_sapi_synthesize", self._orig)

    def _script(self, texts):
        return {"segments": [
            {"id": f"seg_{i + 1:04d}", "text": t, "pages": ["page_0005"]}
            for i, t in enumerate(texts)
        ]}

    def test_cache_reuse_then_partial_recompute(self):
        script = self._script(["第一段", "第二段"])
        r1 = tts.synth_segments(self.work, script, BACKEND)
        self.assertEqual([a["cached"] for a in r1], [False, False])
        self.assertEqual(len(self.calls), 2)
        mtime_1 = (self.work / "audio" / "seg_0001.wav").stat().st_mtime
        bytes_1 = (self.work / "audio" / "seg_0002.wav").read_bytes()

        # 原样重跑：两段全部命中缓存，不触发合成、不动文件
        r2 = tts.synth_segments(self.work, script, BACKEND)
        self.assertEqual([a["cached"] for a in r2], [True, True])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(
            (self.work / "audio" / "seg_0001.wav").stat().st_mtime, mtime_1
        )

        # 只改第二段：仅该段重新合成
        script2 = self._script(["第一段", "第二段改"])
        r3 = tts.synth_segments(self.work, script2, BACKEND)
        self.assertEqual([a["cached"] for a in r3], [True, False])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[-1], "第二段改")
        self.assertEqual(
            (self.work / "audio" / "seg_0001.wav").stat().st_mtime, mtime_1
        )
        self.assertNotEqual(
            (self.work / "audio" / "seg_0002.wav").read_bytes(), bytes_1
        )
        # 索引已落盘
        index = (self.work / "cache" / "tts_index.json").read_text(encoding="utf-8")
        self.assertIn("seg_0001.wav", index)
        self.assertIn("seg_0002.wav", index)

    def test_empty_text_rejected(self):
        with self.assertRaises(RuntimeError):
            tts.synth_segments(self.work, self._script(["  "]), BACKEND)


if __name__ == "__main__":
    unittest.main()
