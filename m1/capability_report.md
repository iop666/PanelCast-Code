# M1 S0 能力探测报告

探测时间：2026-11-15（S0 硬门禁，全部通过）

| 项 | 实测值 | 结果 |
| --- | --- | --- |
| ffmpeg 解析 | `PANELCAST_FFMPEG` 未设置 → `shutil.which("ffmpeg")` 未命中 → 命中已知路径 `D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe` | ✓ |
| ffmpeg 版本 | N-125773-g7002e01c19-20260726（gcc 15.2.0），`-encoders` 含 `libx264`（2 处） | ✓ |
| ffprobe | 同目录 `ffprobe.exe`，N-125773，`-version` 正常 | ✓ |
| 灰度解码 | `page_0005.jpg`（656×1009）经 `-f rawvideo -pix_fmt gray` 输出 661904 字节 = 656×1009，精确一致 | ✓ |
| edge-tts | `importlib.util.find_spec("edge_tts")` → None（未安装，不装） | 跳过 |
| TTS 后端 | SAPI5（PowerShell System.Speech）；已装音色：`Microsoft Huihui Desktop`（zh-CN）、`Microsoft Zira Desktop`（en-US）；选定 **Huihui**，合成「测试」→ WAV 22050 Hz / 16bit / mono，实测 1.379 s > 0 | ✓ |
| 写权限 | `m1/work`、`m1/out` 创建/写入成功 | ✓ |
| Python | 3.14.6（仅标准库） | ✓ |

实际使用的路径（将同步写入 `timeline.json`）：
- ffmpeg：`D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe`
- ffprobe：`D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffprobe.exe`
- TTS：`sapi5:Microsoft Huihui Desktop`（rate=0，22050 Hz → 渲染期统一重采样 44100）

**结论：S0 通过，进入 S1。**
