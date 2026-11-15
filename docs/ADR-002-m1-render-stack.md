# ADR-002: M1 渲染栈（分格 → TTS → 时间轴 → MP4）

- 状态：已采纳（Accepted）
- 日期：2026-11-15
- 背景：M0 已证明内容方向可行，M1 需要跑通第一条端到端闭环：
  8 页漫画 + 一份讲稿 → 带 AI 旁白的 1080p MP4，且"改一句稿只重算受影响的部分"。

## 决策

1. **ffmpeg 是唯一媒体依赖，不引入 Pillow / numpy**。沿用 ADR-001"仅标准库"的规矩：
   图像解码走 `ffmpeg -f rawvideo -pix_fmt gray`（字节即数据），分格、分析全部纯
   Python；缩放 / letterbox / 拼接 / 编码全部交给 ffmpeg 子进程。ffmpeg 按固定顺序
   解析：`PANELCAST_FFMPEG` → `shutil.which` → 已知安装路径（本机
   `D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin`），并与 ffprobe
   同目录绑定；实际路径写入 `capability_report.md` 与 `timeline.json`。缺 ffmpeg 或
   缺 libx264 → S0 直接停止，不装不下载。

2. **分格 = 灰度投影 + 过切合并（确定性，纯函数）**。Otsu 二值化后，行/列最长暗
   游程 > 页宽/高 30% 判为分格线带，线带间隙做初始框；分隔带在相邻框跨度上的暗
   覆盖率 < 60% 判为"过切"并合并（解决上栏全幅大格被下栏分栏线切碎的情形）；近全空
   的细条（<5% 页高/宽）按 gutter 丢弃；每框 confidence = 0.35 + 0.55 × 真边比例
   （四边齐全 ≈ 0.90，无边框 0.35）。候选 `*.candidates.json` **只写一次、永不覆盖**；
   输出逐字节确定（同一页连跑 3 次一致）。已知限制：斜线分栏、越框人物、贴边裁切
   的版式只能给近似框——这正是编辑器存在的原因，人工确认（source=manual）是渲染
   的硬门禁。

3. **TTS 优先级 edge-tts → SAPI5，失败即停**。edge-tts 仅当已装且网络通；否则
   Windows SAPI5 经 PowerShell System.Speech 调用（本机音色 Microsoft Huihui
   Desktop, zh-CN，22050 Hz）。两者都不可用 → 报错退出，**绝不生成静音冒充配音**。
   音频时长一律读 WAV 头（wave 模块），禁止按字数估算。缓存键
   sha256(text+voice+rate+backend)，索引 `cache/tts_index.json` 原子写；同段文本
   改动只重算该段（实测：改 1 段后其余 4 段 WAV 字节与 mtime 均不变）。

4. **时间轴只由真实音频时长累加派生**。start/end 为段的累计区间；段覆盖 1–3 页，
   段内各页均分时长（末页吃余数，保证视频轨总长与音频逐字节一致）；SRT 一段一条。
   `total_duration` 与音频总和误差 < 0.05 s（构建期断言）。

5. **渲染 = concat demuxer 硬切 + 白底 letterbox**。每页预缩放到 1920×1080 白底
   居中（不裁切），concat 清单按页时长硬切（末条文件按 ffmpeg 惯例重复一次），
   libx264 crf 20 / yuv420p / 30fps；音频 concat 后统一 44100 再混流。
   **用显式 `-t total_duration` 而非 `-shortest`**：实测 concat 静帧视频流会比音频长
   数秒且 `-shortest` 未能截断（首跑视频 139.1s vs 音频 134.6s），显式 -t 落实
   "时长以音频为准"，成片与 `total_duration` 误差实测 0.000s。渲染后用 ffprobe 复验
   分辨率 / 音轨 / 时长，不合格报错退出（一行 `error:`）。

6. **编辑器 = 标准库 http.server + 单文件前端**。不引 Flask / 构建工具 / CDN；
   框拖动、拖角缩放、空白拖拽新建、RTL 顺序提示、←/→/S/D 快捷键；只读写
   `m1/work/` 下文件（页名白名单 + resolve 校验，路径穿越 404）；保存 temp+replace
   原子写并置 `source: manual`。

7. **`m1 run` 是门禁式一键闭环**：任一页缺 `*.panels.json` 或 `source != manual`
   → 逐个列出并以退出码 3 退出，**不用候选凑数**；通过后依次 S3→S4→S5，任一步
   失败（TTS、ffmpeg、页面缺失）非零退出并给一行 `error:`。

## 后果

- 正面：零第三方 Python 依赖；全链路时长可复现（真实 WAV 头 + 显式 -t）；分段
  缓存使"改一句稿只重算受影响的部分"成立（实测 1/5 段重算）；摄取层零改动。
- 限制：SAPI5 为机械音（M2 可评估 edge-tts/云端 TTS）；分格对非规则版式只能给
  建议，人工修正确认是必要环节；`-t` 硬切使视频尾帧为静帧停留（对观感无影响）；
  M1 仅 8 页样片，扩章与词级对齐明确超范围。
