"""tts.py 单元测试：WAV 头真实时长、缓存键稳定性、缓存命中与局部重算。"""

import json
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
            # 时长随 rate 变化，以便断言"换语速 → 音频不同"
            try:
                pct = int(str(rate).strip("%+"))
            except ValueError:
                pct = 0
            _write_wav(out_path, seconds=round(0.5 * 100 / (100 + pct), 3),
                       rate=8000, fill=text)

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
        # 索引已落盘，且音频按内容哈希存放（换语速不会互相覆盖）
        index = (self.work / "cache" / "tts_index_v2.json").read_text(
            encoding="utf-8")
        self.assertIn("tts/", index)
        self.assertEqual(len(json.loads(index)), 3)   # 第一段 / 第二段 / 第二段改
        self.assertEqual(len(list((self.work / "cache" / "tts").glob("*.wav"))), 3)

    def test_switching_rate_does_not_reuse_other_rates_audio(self):
        """回归：换 rate 再换回来，必须拿到该 rate 自己的音频，不能串味。"""
        script = self._script(["第一段"])
        slow = dict(BACKEND, rate="+0%")
        fast = dict(BACKEND, rate="+30%")

        a = tts.synth_segments(self.work, script, slow)[0]
        b = tts.synth_segments(self.work, script, fast)[0]
        self.assertNotEqual(a["duration"], b["duration"])  # 假实现按 rate 区分

        # 再切回 +0%：必须命中 +0% 的内容，而不是刚写的 +30%
        c = tts.synth_segments(self.work, script, slow)[0]
        self.assertTrue(c["cached"])
        self.assertEqual(c["duration"], a["duration"])
        self.assertNotEqual(c["duration"], b["duration"])

    def test_empty_text_rejected(self):
        with self.assertRaises(RuntimeError):
            tts.synth_segments(self.work, self._script(["  "]), BACKEND)


class TestEdgeSynthesize(unittest.TestCase):
    """回归：edge-tts 必须写 .tmp.mp3，否则 ffmpeg 找不到输入、静默回退 SAPI5。"""

    def test_edge_writes_temp_mp3_not_wav_path(self):
        import sys
        import types
        from unittest import mock

        saved = {}

        class FakeCommunicate:
            def __init__(self, text, voice, rate="+0%"):
                self.text, self.voice, self.rate = text, voice, rate
                saved["rate"] = rate

            async def save(self, path):
                saved["path"] = path
                Path(path).write_bytes(b"fake-mp3")

        fake = types.ModuleType("edge_tts")
        fake.Communicate = FakeCommunicate

        def fake_run(cmd, **kwargs):
            # 输入必须是 .tmp.mp3，且文件真实存在（这正是原 bug 的失败点）
            src = Path(cmd[cmd.index("-i") + 1])
            self.assertTrue(src.name.endswith(".tmp.mp3"), f"unexpected input {src}")
            self.assertTrue(src.exists(), "ffmpeg input missing: save() went elsewhere")
            Path(cmd[-1]).write_bytes(b"\x00" * 100)
            return mock.Mock(returncode=0, stderr="")

        with mock.patch.dict(sys.modules, {"edge_tts": fake}), \
                mock.patch.object(tts.subprocess, "run", side_effect=fake_run):
            out = Path(tempfile.mkdtemp()) / "seg.wav"
            tts._edge_synthesize("测试", "zh-CN-XiaoxiaoNeural", out, Path("ffmpeg"))

        self.assertTrue(saved["path"].endswith(".tmp.mp3"))
        self.assertFalse(out.with_suffix(".tmp.mp3").exists(), "temp mp3 not cleaned up")


if __name__ == "__main__":
    unittest.main()
