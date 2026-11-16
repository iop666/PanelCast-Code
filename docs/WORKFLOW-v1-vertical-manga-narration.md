# 竖版漫画解说 · 第一版工作流（V1）

- 状态：草案，待评审
- 适用形态：手机竖屏 1080×1920，漫画页 + 旁白解说 + 底部烧入字幕
- 落地代码：`panelcast`（Python 3.13，仅标准库；外部依赖只有 `ffmpeg` 与 `edge-tts`）
- 基线样本：漫画第 1 卷 第一章（38 页 / 6:56 / 25 段 / 2393 字）
- 本文所有数字均为实测值，来源见附录 C

---

## 0. 这份文档怎么用

这份文档定义 **V1 的输入契约、输出契约、十阶段工作方式、每页"介绍页"规范**。
它是给三类人看的：

| 读者 | 该看哪几节 |
| --- | --- |
| 派任务的人（选题/审片） | §1 产品定义、§5 十阶段总览、§9 质检清单 |
| 执行的人/模型（写代码、写讲稿、跑流程） | §3 输入、§4 输出、§5 每阶段细则、§6 介绍页 |
| 后续接"无漫画素材复用"的人 | §6 全文，尤其 §6.7 检索单、§6.8 决策矩阵 |

文中标 **【已实现】** 的是当前代码里已经能跑的能力，标 **【待建】** 的是本规范要求、
但代码还没写的能力。**不要把【待建】当成已完成去汇报。**

### 0.1 交付状态一览

评审时先看这张表，别逐节猜哪些是真能跑的。

| 能力 | 状态 | 对应命令/代码 |
| --- | --- | --- |
| 素材摄取（mobi / epub） | 【已实现】 | `python -m panelcast ingest` |
| 分格候选 + 人工确认（编辑器） | 【已实现】 | `m1 panels` / `m1 edit` |
| 讲稿 → 配音 → 时间轴 → 渲染 → 烧字幕 | 【已实现】 | `m1 run` |
| 章节标签（右上角） | 【已实现】 | `m1 run --chapter "第一章 …"` |
| 成片自检（容器/帧率/音轨/视频轨时长） | 【已实现】 | `m1 run` 内置断言 |
| 介绍页 schema + 八条质量门禁 | 【已实现】 | `python -m panelcast.profile … --ship` |
| 章节自动定界 | 【待建】 | §5.3 |
| 介绍页自动生成（读图填字段） | 【待建】 | §5.4 / §6.5 |
| 13 条验收一键化 `m1 verify` | 【待建】 | §9.2 |
| 无漫画素材复用（V2） | 【待建】 | §14.2 |

---

## 1. 产品定义

### 1.1 一句话

> 一本漫画（或轻小说）→ 逐页解读 → 逐段讲稿 → 神经配音 → 竖屏成片，且改一句稿只重算受影响的那一段。

### 1.2 一集成品必须满足的硬指标

| 项 | 值 | 说明 |
| --- | --- | --- |
| 画布 | 1080×1920 / 30fps / yuv420p | 手机竖屏，`libx264 crf 20` |
| 音轨 | AAC 160k，单声道 44100 | 必须有，无音轨即失败 |
| 视频轨时长 | 与音频误差 < 0.2s | **必须查流级时长，不能只查容器时长**（见 §13 坑 2） |
| 字幕 | 白字黑描边，烧入画面 + 独立 `.srt`/`.ass` | 字幕填充必须是 255 纯白（见 §13 坑 3） |
| 章节标签 | 右上角常驻，浅灰小字 | 字号约为字幕的 52%，颜色 `#999999` |
| 时长 | 按内容定，不设上限 | 第一章 38 页 = 6:56 |
| 单页停留 | 建议 8–14s，硬上限 26s | 一页挂多少字决定停多久；超上限说明这一段文字压在一页上（§9.2 第 12 条） |
| 切页同步 | 页窗口必须落在讲这一页的段内 | 越界 >0.5s 就是画面与配音脱钩（§9.2 第 14 条） |
| 内容密度 | 45–90 字/页 | 低于 45 页翻得太快、信息量不够（§9.2 第 15 条） |

### 1.3 V1 明确不做

- 转场、运镜、Ken Burns、BGM、音效
- 词级字幕对齐（V1 是句级 + 句内线性插值）
- 多音色分角色配音
- 自动分格（只给候选，必须人工确认）
- 无漫画素材的自动替换（V1 只产出"检索单"，替换是 V2）
- 在线协作、云端渲染、批量队列

---

## 2. 名词表

| 名词 | 含义 |
| --- | --- |
| **源文件** | 一个 `.mobi`（漫画）或 `.epub`（小说） |
| **页 / page** | 漫画里的一张图，命名 `page_0005`（4 位序号，从 1 起） |
| **章 / chapter** | 漫画的叙事单元，有标题页，如「第一章 …」 |
| **段 / segment** | 讲稿的最小单位，1–3 页配一段旁白，命名 `seg_0001` |
| **介绍页 / page profile** | 每一页的结构化描述（画面/人物/文字/复用建议），见 §6 |
| **句锚点 / sentence anchor** | edge-tts 返回的真实句边界时间，用来给字幕对时 |
| **素材检索单 / asset request** | 由介绍页派生、给"替代素材"用的检索规格，见 §6.7 |
| **工作区 / work** | 一次出片的中间目录，含 `pages/ panels/ audio/ cache/` |

---

## 3. 输入

### 3.1 素材形态

| 类型 | 格式 | 规模实测 | 说明 |
| --- | --- | --- | --- |
| 漫画 | `.mobi`（PDB 容器，内嵌 JPEG） | 1 卷 = 169 页；**62 种尺寸**，宽 160–768、高 240–1024，主力 672×1009（41 页）/ 648×1009（32 页），119 页高 1009 | 主视觉来源 |
| 小说 | `.epub`（OPF spine + XHTML） | 1 卷 = 6 章，约 8.6 万字 | 讲稿的事实来源 |

目录约定（素材不进 git，`.gitignore` 已排除）：

```
この素晴らしい世界に祝福を！/
  漫画/     1卷.mobi … 18卷.mobi, 話111-125.mobi
  正文/     1.epub … 17.epub
  外传及短篇/
```

### 3.2 三种输入模式

V1 只真正支持 **模式 A**，但介绍页规范必须让 B/C 在未来能直接接上：

| 模式 | 输入 | 视觉来源 | V1 支持度 |
| --- | --- | --- | --- |
| **A 有漫画** | 漫画 mobi + 小说 epub | 漫画页原图 | ✅ 完整支持 |
| **B 只有小说** | 仅 epub | 全部用替代素材（图库/AI 生成/文字卡） | ⬜ 仅规格预留（§6.7–6.8） |
| **C 混合** | 漫画 + 小说，但漫画覆盖不全 | 逐页决定：原页 / 复用其它页 / 替代素材 | ⬜ 仅规格预留 |

**这就是"每页都要有介绍页"的根本原因**：模式 B/C 下，你手上没有那一页的图，
只能靠介绍页里的结构化描述去找/生成一张能顶上的画面。

### 3.3 输入门禁（不合格立刻停，别硬跑）

| 检查 | 不合格表现 | 处理 |
| --- | --- | --- |
| 文件存在 | 路径不存在 | 退出码 4，一行 `error:` |
| 能解出页/章 | 页数 0 或章数 0 | 退出码 3，**不允许写出 `chapter_count: 0`** |
| 同类输入唯一 | 一次传了 2 个 mobi | 退出码 2，且不写任何文件 |
| 页图可解码 | `ffmpeg` 灰度解码字节数 ≠ w×h | 退出码 4 |

---

## 4. 输出

### 4.1 交付物清单

一次出片必须产出下面全部内容，缺一项算失败：

| # | 产物 | 位置 | 给谁看 |
| --- | --- | --- | --- |
| 1 | 成片 | `out/<章节名>.mp4` | 观众 |
| 2 | 外挂字幕 | `out/<章节名>.srt` | 需要二次剪辑/上传平台 |
| 3 | 字幕工程 | `out/<章节名>.ass` | 复现烧入效果 |
| 4 | 时间轴 | `work/timeline.json` | 审查/复算 |
| 5 | 讲稿 | `work/script.json` | 编辑/改稿 |
| 6 | 每页介绍页 | `library/profiles/<系列>/<卷>/page_XXXX.profile.json` | 素材复用/检索 |
| 7 | 章节索引 | `work/chapter_index.json` | 定界/复用 |
| 8 | 运行报告 | `out/run_report.json` | 质检/追责 |

### 4.2 目录树（全量）

```
panelcast/
  .local/                          # 源素材缓存，git 忽略
    source/
      epub/  chapters/*.xhtml, chapters.json, source_manifest.json
      mobi/  pages/*.jpg, pages.json
  library/                         # 长期资产，进 git
    profiles/
      <系列slug>/<卷slug>/
        page_0005.profile.json
        …
    index/pages.jsonl              # 扁平索引，一行一页，供检索
  m1/
    ch1/                           # 一次出片的工作区（按章节一个）
      work/
        pages/                     # 从 .local 复制的页图，只读
        panels/
          page_0005.candidates.json
          page_0005.panels.json
        profiles -> ../../library/…  # 符号链接或复制，见 §6.2
        audio/seg_0001.wav
        cache/
          tts/<sha256>.wav
          tts_index_v3.json
          frames/1080x1920-blurpad-white-b269-m10-t72/page_0005.png
          audio_concat.wav
        chapter_index.json
        script.json
        timeline.json
      out/
        第一章.mp4 第一章.srt 第一章.ass run_report.json
```

### 4.3 各产物 schema

#### 4.3.1 `chapter_index.json`【待建】

```json
{
  "schema": "chapter-index/v1",
  "source_file": "1卷.mobi",
  "total_pages": 169,
  "chapters": [
    {
      "id": "ch01",
      "label_zh": "第一章 与自称是女神的家伙一起转生到异世界！",
      "label_orig": "第一章 與自稱是女神的傢伙一起轉生到異世界！",
      "title_page": 5,
      "start_page": 5,
      "end_page": 42,
      "page_count": 38
    }
  ],
  "page_kinds": {
    "1": "cover", "2": "colophon", "3": "frontispiece", "4": "frontispiece",
    "5": "title_page", "43": "blank", "44": "divider",
    "156": "watermark", "167": "colophon"
  }
}
```

`page_kinds` 取值：`cover | colophon | frontispiece | title_page | story | blank | divider | watermark | extra`。
**非 `story`/`title_page` 的页不进正文出片**，但介绍页照样要写（复用时会用到）。

#### 4.3.2 `page_XXXX.profile.json`【待建】— 见 §6

#### 4.3.3 `*.candidates.json` / `*.panels.json`【已实现】

```json
{
  "page": "page_0005", "width": 672, "height": 1009,
  "reading_direction": "rtl", "source": "manual",
  "panels": [{"id": "p1", "order": 1, "x": 0, "y": 0, "w": 672, "h": 1009,
              "confidence": 1.0, "locked": false}]
}
```

- `candidates` 只写一次，永不覆盖；`panels` 可反复编辑
- `source` 必须是 `manual` 才允许出片（退出码 3 卡住）
- 整页不分格时，就写一个满页框——**这不是偷懒，是明确的编辑决定**

#### 4.3.4 `script.json`【已实现】

```json
{
  "segments": [
    {"id": "seg_0001", "pages": ["page_0005", "page_0006"], "text": "…"}
  ]
}
```

约束：`pages` 1–3 页；`text` 非空；`id` 唯一；引用页必须已确认。

#### 4.3.5 `tts_index_v3.json`【已实现】

```json
{
  "<sha256>": {
    "file": "tts/<sha256>.wav",
    "duration": 17.64, "backend": "edge-tts:zh-CN-YunxiNeural",
    "voice": "zh-CN-YunxiNeural", "chars": 103,
    "sentences": [{"offset": 0.1, "duration": 4.262, "text": "…"}],
    "synthesized_at": "2026-11-16T…"
  }
}
```

`sentences` 是字幕对时的命根子，缺了就只能按字数猜（误差最大 805ms，见 §8.3）。

#### 4.3.6 `timeline.json`【已实现】

```json
{
  "tts_backend": "edge-tts:zh-CN-YunxiNeural",
  "voice": "zh-CN-YunxiNeural",
  "ffmpeg": "D:\\…\\ffmpeg.exe",
  "total_duration": 416.6,
  "segments": [
    {"id": "seg_0001", "text": "…", "audio": "seg_0001.wav",
     "duration": 17.64, "start": 0.0, "end": 17.64,
     "pages": ["page_0005", "page_0006"],
     "sentences": [{"offset": 0.1, "duration": 4.262, "text": "…"}]}
  ]
}
```

**时间轴一律由真实 WAV 时长累加派生，禁止按字数估算。**

#### 4.3.7 `<章节名>.ass` / `.srt`【已实现】

- ASS 两条样式：`Default`（底部字幕）、`Chapter`（右上标签）
- SRT 与 ASS 用**同一批 cue**，保证"烧进画面的"和"外挂的"逐条一致

#### 4.3.8 `run_report.json`【待建】

```json
{
  "schema": "run-report/v1",
  "built_at": "2026-11-16T01:48:00+08:00",
  "chapter": "第一章",
  "input": {"mobi": "1卷.mobi", "page_range": [5, 42]},
  "output": {"file": "第一章.mp4", "bytes": 44703616,
             "width": 1080, "height": 1920, "fps": 30.0,
             "video_duration": 416.6, "audio_duration": 416.616,
             "frames": 12498},
  "content": {"segments": 25, "chars": 2393, "cues": 209, "pages": 38},
  "layout": {"label": [18, 48], "comic": [72, 1703], "subtitle": [1747, 1821]},
  "checks": [{"name": "video_track_matches_audio", "ok": true}],
  "known_issues": ["page_0009 单页停留 17.7s"]
}
```

---

## 5. 工作方式：十阶段

### 5.0 总览

```
mobi ─S1─► pages/*.jpg ─S2─► chapter_index.json
                            │
                            ├─S3─► page_XXXX.profile.json ──► 素材检索单（V2）
                            │
                            └─S4─► *.candidates.json ──人工──► *.panels.json
                                                                    │
epub ─S1─► chapters/*.xhtml ─S5─► script.json ◄──────────────────────┘
                                    │
                                    ├─S6─► audio/*.wav + tts_index_v3.json
                                    ├─S7─► timeline.json
                                    └─S8─► <章节名>.mp4 / .srt / .ass
                                              │
                                              └─S9─► run_report.json
```

| 阶段 | 名称 | 执行者 | 产物 | 现状 |
| --- | --- | --- | --- | --- |
| S0 | 能力探测 | 机器 | `capability_report.md` | 【已实现】 |
| S1 | 素材摄取 | 机器 | `pages/*.jpg` + `pages.json` | 【已实现】 |
| S2 | 章节定界 | 机器 + 人 | `chapter_index.json` | 【待建】（方法已定，见下） |
| S3 | 页面解读 | 视觉模型 + 人 | `page_XXXX.profile.json` | 【待建】 |
| S4 | 分格与确认 | 机器 + 人 | `*.panels.json` | 【已实现】 |
| S5 | 讲稿 | 模型 + 人 | `script.json` | 半自动（当前人工） |
| S6 | 配音 | 机器 | `audio/*.wav` + 索引 | 【已实现】 |
| S7 | 时间轴 | 机器 | `timeline.json` | 【已实现】 |
| S8 | 渲染 | 机器 | `<章节名>.mp4` | 【已实现】 |
| S9 | 质检交付 | 机器 + 人 | `run_report.json` | 部分（校验内建于 S8） |

### 5.1 S0 能力探测

- **输入**：本机环境
- **动作**：按 `PANELCAST_FFMPEG` → `shutil.which` → 已知路径 解析 ffmpeg/ffprobe；
  验证 `libx264` 存在；验证灰度解码字节数 = w×h；探测 TTS 后端；验证目录可写
- **产物**：`capability_report.md`（逐项写实测值，不写"应该可以"）
- **门禁**：任一不过 → 停，报告实际试过的路径。**不许装软件凑通**
- **耗时**：约 5s（TTS 探测含一次合成）

### 5.2 S1 素材摄取

- **输入**：`.mobi` / `.epub` 路径或目录
- **动作**：mobi 扫 PDB record 里的 JPEG（SOI/EOI）；epub 按 OPF spine 取章节 XHTML
- **产物**：`.local/source/mobi/{pages/*.jpg, pages.json}`、`.local/source/epub/{chapters/*.xhtml, chapters.json}`、`source_manifest.json`
- **门禁**：页数/章数为 0 → 退出码 3；同类输入 >1 → 退出码 2
- **耗时**：169 页约 3s

### 5.3 S2 章节定界【待建】

漫画 mobi **没有目录页**，章节要靠图像特征找。已跑通的方法：

1. 全页灰度一次导出：`ffmpeg -start_number 1 -i page_%04d.jpg -vf "scale=54:81,format=gray" -f rawvideo`
2. 算每页墨量（灰度 <160 的像素占比）
   - **波点分隔页墨量 ≈ 1.6%** → 一抓一个准
   - **全黑页墨量 = 100%** → 与波点页成对出现
3. 章节标题页是**全幅插画 + 小横幅**，墨量正常，靠墨量找不到；靠"黑页 + 波点页"配对反推：
   `p43 黑 → p44 波点 → p45 = 第二章标题页`
4. 第一章没有前置分隔页，直接从卷首彩页后的第一个标题页起算

- **产物**：`chapter_index.json`
- **门禁**：章节标题页必须人工确认一次（横幅文字要人读），确认后写入 `verified_by`
- **耗时**：169 页约 10s（统计）+ 人工 2 分钟

> **别用 `-vf tile=` 拼联系表**：实测只输出 1 帧，白费时间。逐页灰度统计更可靠。

### 5.4 S3 页面解读【待建】— 本版新增的核心

- **输入**：`pages/*.jpg` + `chapter_index.json`
- **动作**：视觉模型逐页读图，产出结构化介绍页（§6）。**必须逐字转录页内文字**，
  不许"大概意思"；看不清就标 `ocr_confidence` 低并留空，**不许编**
- **产物**：`library/profiles/<系列>/<卷>/page_XXXX.profile.json` + `library/index/pages.jsonl`
- **门禁**：
  - 必需字段齐全（§6.6）
  - `reviewed: true`（人或二次模型校对过）
  - `story.summary` ≤ 40 字且不含未出现的人名
- **耗时**：约 8–12s/页（含模型往返）；169 页约 30 分钟

### 5.5 S4 分格与确认

- **输入**：`pages/*.jpg`
- **动作**：纯 Python 行/列投影 + Otsu 给候选框；人在浏览器里拖拽修正
- **命令**：
  ```bash
  python -m panelcast m1 panels --work m1/ch1/work
  python -m panelcast m1 edit  --work m1/ch1/work --port 8642
  ```
- **产物**：`*.candidates.json`（只写一次）+ `*.panels.json`（`source: manual`）
- **门禁**：任一页缺 `panels.json` 或 `source != manual` → 退出码 3，列出页名
- **耗时**：自动 0.3s/页；人工修正 10–30s/页（V1 整页出片时可直接满页框）

### 5.6 S5 讲稿

- **输入**：`page_XXXX.profile.json`（画面事实）+ epub 章节文本（剧情事实）+ `panels.json`
- **动作**：按 1–3 页一段写旁白。**画面里有的才写画面，剧情靠小说补，不许编**
- **产物**：`script.json`
- **门禁**（写稿自检）：
  - 每段 ≤ 130 字（超过会被切成 9 条以上字幕，观感碎）
  - 引用页必须在 `chapter_index` 的本章范围内
  - 人名只用介绍页里出现过的写法
  - **45–90 字/页**（§9.2 第 15 条）。低于 45 就是"内容不充实"，靠补小说细节而不是拖长句子
  - **画面里没有的东西不许写**。漫画省略的情节不能凭空补；漫画没画但小说有的事件，
    要么不写，要么写在"这段画面对应的小说情节"里，不能张冠李戴
  - 写完必须回看对应页：翻三页抽查一次，确认旁白里的动作/人物真的在那页上
- **耗时**：38 页 / 25 段约 1.5 小时（人工）

### 5.7 S6 配音

- **输入**：`script.json` + 后端信息
- **动作**：edge-tts 合成，**用 `stream()` 而不是 `save()`**，同时收集 `SentenceBoundary`
- **产物**：`cache/tts/<sha256>.wav`（内容寻址）+ `audio/seg_XXXX.wav`（工作名）+ 索引
- **门禁**：合成失败/0 字节 → 退出码 4；时长 ≤ 0 → 退出码 4
- **耗时**：25 段约 2.5 分钟（网络）

### 5.8 S7 时间轴

- **输入**：`script.json` + 音频真实时长 + 句锚点
- **动作**：累加真实时长得 `start/end`；段内页时长均分；生成 cue
- **产物**：`timeline.json`
- **门禁**：总时长与音频累加误差 ≥ 0.05s → 退出码 4
- **耗时**：<1s

### 5.9 S8 渲染

- **输入**：`timeline.json` + 页图 + 音频
- **动作**：逐页出目标画布 PNG（带缓存）→ concat → 一条 ffmpeg 烧字幕出片
- **产物**：`<章节名>.mp4/.srt/.ass`
- **门禁**：见 §9.2，任一不过 → 退出码 4
- **耗时**：38 页约 2 分钟

### 5.10 S9 质检交付

- **输入**：成片 + 全部中间产物
- **动作**：跑 §9.2 的 13 条验收，写 `run_report.json`；抽 6 帧人工看
- **产物**：`run_report.json` + 验收单
- **门禁**：任一硬指标不过 → 不出片，回退到对应阶段

### 5.11 派任务用的任务书模板

本项目实际工作方式是"人审 + 模型执行"，所以每个阶段的任务书要包含：

```markdown
# TASK-<编号> <一句话标题>

## 背景
（为什么做，前置是什么，验收过没有）

## 范围
（只做 X，不做 Y；列出允许改的文件白名单）

## 输入事实（别再探测）
（路径、版本、实测数字）

## 硬要求
（可测的条目，每条都能用命令复验）

## 验收（审查方逐条独立复验）
1. …
2. …

## 交付格式
capability: …
files: …
tests: <总数> 通过
blocked: <无 / 具体卡点>
```

**任务书必须写"不允许改的文件"**，否则执行方会顺手重构摄取层。

---

## 6. 页面介绍页（page profile）规范

### 6.1 为什么要它

三个用途，按重要性排：

1. **无漫画时的素材复用（V2 的主路径）**：模式 B/C 下没有原页，只能靠结构化描述
   去找图库、生成图、或复用同章节其它页。
2. **讲稿的事实底稿**：写稿时先看介绍页，避免"看图说话"时漏掉关键信息或编造。
3. **检索与统计**：全库按人物/场景/景别检索，做合辑、做预告、做封面。

**一句话：介绍页是"这一页可以被机器理解"的唯一形式。**

### 6.2 文件位置与命名

```
library/profiles/<系列slug>/<卷slug>/page_0005.profile.json
library/index/pages.jsonl          # 一行一页的扁平索引
```

- `系列slug`：`konosuba`
- `卷slug`：`manga-v01`
- 页面序号与 `.local/source/mobi/pages/page_0005.jpg` 一一对应
- 工作区通过 `work/profiles/` 指向 library（符号链接优先，Windows 不行就复制），
  这样出片时按工作区路径找得到

**为什么放 `library/` 而不是工作区**：介绍页描述的是**源素材**，跨章节、跨次出片都要复用。
放进工作区会导致每做一章重写一遍，白烧模型调用。

### 6.3 字段定义

顶层：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `schema` | string | ✅ | 固定 `page-profile/v1` |
| `page` | string | ✅ | `page_0005` |
| `source` | object | ✅ | 溯源信息 |
| `chapter` | object | ✅ | 所属章节 |
| `layout` | object | ✅ | 版式特征 |
| `story` | object | ✅ | 叙事内容 |
| `text` | object | ✅ | 页内文字 |
| `visual` | object | ✅ | 视觉特征 |
| `reuse` | object | ✅ | 复用建议 |
| `provenance` | object | ✅ | 谁生成的、可信度、审过没有 |

`source`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `series` | string | ✅ | `为美好的世界献上祝福！` |
| `volume` | string | ✅ | `漫画 第1卷` |
| `file` | string | ✅ | `1卷.mobi` |
| `page_index` | int | ✅ | mobi 内序号（1 起） |
| `printed_page` | int\|null | ✅ | 页脚印刷页码，无则 null |
| `sha256` | string | ✅ | 页图内容哈希，用于去重 |
| `width` / `height` | int | ✅ | 原始像素 |

`layout`：

| 字段 | 类型 | 必填 | 取值 |
| --- | --- | --- | --- |
| `kind` | string | ✅ | `story / title_page / frontispiece / divider / cover / blank / colophon / watermark` |
| `is_color` | bool | ✅ | 是否彩页 |
| `panel_count` | int | ✅ | 分格数（整页=1） |
| `reading_direction` | string | ✅ | `rtl / ltr` |
| `text_density` | string | ✅ | `low / medium / high` |
| `has_splash` | bool | ✅ | 是否有整页大图 |
| `borderless` | bool | ✅ | 是否无边框（影响分格可信度） |

`story`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `beat` | string | ✅ | 叙事功能，受控词表见 §6.4 |
| `summary` | string | ✅ | ≤40 字，这页发生了什么 |
| `characters` | array | ✅ | `[{name, role, region, expression}]`，可为空数组 |
| `location` | string | ✅ | `阿克塞尔·冒险者公会大厅` |
| `time_of_day` | string | ✅ | `day / night / dusk / dawn / unknown` |
| `weather` | string | ✅ | `indoor / clear / rain / snow / unknown` |
| `emotion` | string | ✅ | 受控词表见 §6.4 |
| `continuity` | string | ✅ | 与上一页的关系：`same_scene / cut / flashback / time_skip` |

`text`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `bubbles` | array | ✅ | `[{speaker, text, region, is_shout}]`，逐字转录 |
| `narration_boxes` | array | ✅ | 旁白框文字 |
| `sfx` | array | ✅ | 拟声词（`噗`、`呱`） |
| `verbatim_complete` | bool | ✅ | 是否完整转录（看不清就 false） |
| `ocr_confidence` | number | ✅ | 0–1，模型自评 |

`visual`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `shot` | string | ✅ | 景别，受控词表 §6.4 |
| `composition` | string | ✅ | 构图一句话（`对角构图，人物占右下三分之二`） |
| `key_props` | array | ✅ | 关键道具（`冒险者卡片`、`法杖`） |
| `palette` | array | ✅ | 3–5 个主色，`#RRGGBB`。**黑白页取灰度分位**（p50 纸白 / p25 网点 / p10 深墨 / p02 实黑），不许编彩色 |
| `motion_hint` | string | ✅ | 静态页建议运镜，受控词表 §6.4 |

`reuse`（**素材复用的核心**）：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `replaceable` | bool | ✅ | 这页能不能被替代素材顶掉 |
| `replace_strategy` | string | ✅ | `keep_original / reuse_other_page / stock / generated / text_card` |
| `scene_tags` | array | ✅ | 受控词表 §6.4，1–5 个（一般 2–3；`blank` 页 1 个 `meta.blank` 即可） |
| `asset_brief` | string | ✅ | 给找图/生图用的一句话描述（**不带原作人名**，避免检索不到） |
| `blocking_reason` | string\|null | ✅ | `replaceable=false` 时必填原因 |

`provenance`：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `generated_by` | string | ✅ | `vision:<model>` 或 `human` |
| `generated_at` | string | ✅ | ISO8601 |
| `confidence` | number | ✅ | 0–1 |
| `reviewed` | bool | ✅ | **出片门禁看这个** |
| `reviewer_notes` | string | ⬜ | 人工修正说明 |

### 6.4 受控词表

自由文本没法检索，所以这些字段必须是枚举：

**`beat`（叙事功能）**

| 值 | 含义 | 典型用法 |
| --- | --- | --- |
| `establishing` | 建立镜头 | 交代地点、氛围，配开场白 |
| `dialogue` | 对话推进 | 主体叙事 |
| `reaction` | 反应/表情 | 吐槽、惊讶，短停留 |
| `action` | 动作/战斗 | 配短句、快节奏 |
| `exposition` | 说明/设定 | 讲世界观，可长停留 |
| `transition` | 过渡 | 换场，配一句衔接 |
| `gag` | 搞笑/吐槽 | 节奏放缓，给笑点留白 |
| `cliffhanger` | 悬念收尾 | 章末 |

**`shot`（景别）**：`wide / full / medium / closeup / extreme_closeup / insert / over_shoulder`

**`motion_hint`（运镜建议）**：`static / push_in / pull_out / pan_left / pan_right / tilt_up / tilt_down / shake`

**`emotion`**：`comedic / tense / sad / exciting / warm / eerie / neutral`

**`scene_tags`（两级，`域.对象`）**

| 域 | 允许值（V1 起步集） |
| --- | --- |
| `indoor.` | `guild_hall, tavern, room, shop, corridor, throne_room, church, dungeon, carriage` |
| `outdoor.` | `street, town_overview, field, forest, road, lake, mountain, sky, ruins` |
| `fantasy.` | `magic_circle, explosion, monster, guild_board, weapon, armor` |
| `character.` | `group, solo, back_view, silhouette` |
| `meta.` | `title_card, divider, credit, blank` |

**新增词条要走评审**，不许就地发明——否则检索会碎成一堆同义词。

### 6.5 生成规则

1. **逐页读图，逐字转录**页内文字。看不清就 `verbatim_complete: false`，
   **绝不猜**。M0 已验证：竖排繁体逐字读是可靠的，但"读不出"必须承认。
2. `summary` 只写**画面能证明的事**。剧情因果靠小说，标 `source: novel` 时另行记录。
3. 人名用**中文常用译名**（佐藤和真 / 阿克娅 / 惠惠 / 露娜），与讲稿保持一致。
4. `asset_brief` 里**不要写原作人名**：`一位蓝发少女在公会柜台前大哭` 比
   `阿克娅在哭` 更容易在图库/生成器里命中。
5. 非 `story` 页（封面、分隔、版权）照样要写，`reuse.replaceable` 一般 `false`。
6. 生成后跑一次**自检**（§6.6），不过就重生成，不要人工硬改字段凑过。

### 6.6 质量门禁

| 检查 | 判据 |
| --- | --- |
| 必需字段齐全 | §6.3 标 ✅ 的全部非空（数组可为空但必须存在） |
| 枚举合法 | `beat/shot/emotion/motion_hint/replace_strategy/scene_tags` 全在词表内 |
| 摘要长度 | `len(summary) <= 40` |
| 不编人名 | `characters[].name` 必须出现在 `text.bubbles[].speaker` 或该系列已知人物表里 |
| 转录自洽 | `verbatim_complete=false` 时 `reviewer_notes` 必须写明缺了哪一块；不许只把置信度压低就算交差 |
| 调色板可信 | `is_color=false` 时 `palette` 每个色都必须近灰（R/G/B 极差 ≤ 8），黑白页不许出现暖色 |
| 复用自洽 | `replaceable=false` 必须有 `blocking_reason` |
| 已审 | `reviewed=true` 才允许出片 |

**这八条已经能跑**，不是纸面清单：

```bash
# 结构 + 语义全检；--ship 额外要求 reviewed=true
python -m panelcast.profile work/profiles/page_0021.json --ship
# ok page_0021                → 退出码 0
# error: …: $.visual.palette[1]: #8a6b4f 是彩色，但 layout.is_color=false  → 退出码 3
```

`panelcast/profile.py` 自带一个 draft-07 子集校验器（只用标准库），
不认识的关键字会**报错而不是放过**——`tests/test_profile.py` 里有一条用例
专门盯"schema 用了未支持的关键字"。附录 B 那个示例就是被这条链路
逐条校验过的，改文档里的示例而忘了改 schema，测试会红。

### 6.7 从介绍页到素材检索单

V2 的输入就是这个 JSON，V1 只负责把它生成对：

```json
{
  "schema": "asset-request/v1",
  "request_id": "konosuba-ch01-page0021",
  "duration": 9.3,
  "aspect": "9:16",
  "shot": "medium",
  "scene_tags": ["indoor.guild_hall", "fantasy.guild_board"],
  "characters": ["蓝发少女", "黑发少年"],
  "action": "两人在木制柜台前登记，少女在哭",
  "mood": "comedic",
  "palette": ["#f2efe6", "#8a6b4f", "#3b4a6b"],
  "safe_area": {"top": 72, "bottom": 1747},
  "constraints": ["不要文字水印", "主体不要压到顶部 72px 与底部 173px"],
  "fallback": ["reuse_other_page", "text_card"]
}
```

`safe_area` 直接来自版面规范（§7）：**任何替代素材都必须把主体放在
`y=72..1747` 之间**，否则会被章节标签或字幕压住。

### 6.8 复用决策矩阵

| 情况 | `replaceable` | `replace_strategy` | 说明 |
| --- | --- | --- | --- |
| 标题页、分隔页、封面 | false | keep_original | 版式本身是信息 |
| 页内有不可替代的文字信息（如能力值卡片） | false | keep_original | 换成别的图会丢信息 |
| 同场景的过渡页 | true | reuse_other_page | 复用本章同景别的页，最省 |
| 通用场景（街景、公会大厅、森林） | true | stock | 图库命中率高 |
| 特定人物特写 | true | generated | 图库没有，只能生成 |
| 纯旁白/设定说明页 | true | text_card | 直接做文字卡，最稳 |

**优先级：keep_original > reuse_other_page > stock > generated > text_card**
（越靠前越保真、越便宜）。

### 6.9 索引与检索

`library/index/pages.jsonl` 一行一页，只放检索用字段：

```json
{"page":"page_0021","series":"konosuba","volume":"manga-v01","chapter":"ch01",
 "kind":"story","beat":"dialogue","shot":"medium","emotion":"comedic",
 "scene_tags":["indoor.guild_hall"],"characters":["佐藤和真","阿克娅","露娜"],
 "replaceable":true,"reviewed":true,"sha256":"…"}
```

常用查询（V1 用 `grep`/`jq` 就够，不需要数据库）：

```bash
# 本章所有"可替换的室内公会场景"
grep '"chapter":"ch01"' library/index/pages.jsonl | grep 'indoor.guild_hall'
# 全书所有"爆炸"镜头，做合辑
grep 'fantasy.explosion' library/index/pages.jsonl
```

---

## 7. 版面规范（竖屏几何）

### 7.1 三段分区

1080×1920 自上而下切成三段，**互不重叠**：

```
y=0      ┌──────────────────────────┐
         │            第一章 与自称… │ ← 章节标签（浅灰，右上）
y=72     ├──────────────────────────┤
         │                          │
         │        漫画页（不裁切）    │ ← 等比缩放，宽度优先
         │                          │
y=1703   ├──────────────────────────┤
         │                          │ ← 留白
y=1747   ├──────────────────────────┤
         │      字幕（白字黑描边）    │
y=1821   └──────────────────────────┘
```

实测三段的墨迹范围：**标签 18–48 / 漫画 72–1703 / 字幕 1747–1821**。

### 7.2 参数表

| 参数 | 值 | 计算方式 | 作用 |
| --- | --- | --- | --- |
| 画布 | 1080×1920 | 固定 | 竖屏 |
| `band`（字幕带） | 269 | `round(H×0.14)` | 底部预留 |
| `margin` | 10 | 固定 | 左右/底部边距 |
| `top`（顶部留白） | 72 | 固定 | 给章节标签让位 |
| `fg_h`（漫画最大高） | 1631 | `H - band - margin×2` | **不因 top 变化而缩小** |
| 字幕字号 | 77 | `round(H×0.040)` | — |
| 字幕描边 | 6 | `round(font×0.075)` | 白字黑边 |
| 字幕 `MarginV` | 100 | `round(H×0.052)` | 距底 |
| 字幕左右边距 | 32 | `round(W×0.03)` | — |
| 章节字号 | 40 | `round(H×0.021)` | 约为字幕的 52% |
| 章节距顶 | 12 | `round(H×0.006)` | — |
| 章节颜色 | `#999999` | 固定 | 浅灰、无描边 |

**关键设计**：`top` 只改平移量，不改 `fg_h`，所以漫画**不会因为加标签而缩小**。
实测漫画从 `y50` 移到 `y72`，只下移 22px（1.1% 画面高度）。

### 7.3 页面适配

| 模式 | 行为 | 何时用 |
| --- | --- | --- |
| `letterbox` | 等比缩放 + 居中留白 | 横屏、信息完整优先 |
| `cover` | 铺满 + 裁切 | 不用（会切掉文字） |
| `blurpad` | 等比缩小整页 + 底色填充 | **竖屏默认** |
| `blurpad + white` | 同上，底色纯白 | 本系列在用 |

页面宽高比与落位：

- 宽优先（如 672×1009，比例 0.666）：缩放后 1080×1621，占 `y72..1693`
- 高优先（比例 < 0.662）：占满 `y72..1703`

一卷里 62 种尺寸混着来，**落位是逐页算的**，不存在"全片一个固定缩放"。
上表是 672×1009 这类的算例，别当成常数往别处抄。

**出片前会先自动裁掉扫描黑边**（`detect_content_box`，带 60% 面积保护，防过度裁切）。

### 7.4 渲染滤镜链（顺序不可改）

```
fps=30 , scale=in_range=full:out_range=tv , ass=<章节名>.ass
```

| 顺序 | 原因 | 违反的后果 |
| --- | --- | --- |
| `fps=30` 必须最前 | concat demuxer 每页只吐**一帧**（时长靠 PTS 撑），不先转真 30fps，`ass` 只会烧进"每页起始时刻"那一条字幕 | 字幕只在换页时变，看起来完全不跟配音 |
| `scale` 必须在 `ass` 之前 | 漫画帧按 full range 写入，libass 输出按 tv 压缩；不先归一色域，字幕白落成 **235 灰**而背景是 255 | 字幕看起来"不是白色" |
| `ass` 最后 | 字幕必须烧在归一后的画面上 | — |

---

## 8. 音频与字幕规范

### 8.1 语速与时长估算

- 默认音色 `zh-CN-YunxiNeural`，`rate=+20%`
- **实测语速 5.74 字/秒**（2393 字 → 416.6s；另两次 5.84 / 5.70）
- 估算公式：`时长(s) ≈ 字数 / 5.75`，误差 ±3%
- `--rate` 的百分比不是线性的：`+20% → 1.24×`、`+30% → 1.35×`、`+40% → 1.45×`

| 目标时长 | 参考字数 |
| --- | --- |
| 1 分钟 | 345 |
| 3 分钟 | 1035 |
| 5 分钟 | 1725 |
| 7 分钟 | 2415 |

### 8.2 断句规则

- 按标点切词块，贪心打包到 **≤16 字**，`min_chars=6`
- 超长词块**均衡切分**（19 字切 10+9，而不是 16+3）
- 短块并入前块，避免 2 字闪 0.34s
- 显示时去掉 `，。` 这两个纯停顿标点（句读靠换条表达）
- 段内 cue 首尾相接，**总长严格等于段时长**

### 8.3 句锚点（字幕跟配音走的关键）

- edge-tts 对中文 **不吐 `WordBoundary`**（全 0），但 `SentenceBoundary` 是真实偏移（单位 100ns）
- 必须用 `stream()` 收集，`save()` 拿不到标记
- 每句给两个锚点（句首、句尾），锚点间线性插值 → 等于"句内按字数、句间按真实停顿"
- **实测误差对比**：

| 方法 | 平均 | p90 | 最大 |
| --- | --- | --- | --- |
| 按字数比例（旧） | 205ms | 463ms | 805ms |
| 句锚点插值（现） | 3ms | 5ms | 5ms |

- 句锚点缺失时（如 SAPI5 后端）自动退回按字数比例，**不报错但要记进 `run_report`**

### 8.4 字幕显示

- 白字 `&H00FFFFFF` + 黑描边 `&H00000000`，`BorderStyle=1`
- `WrapStyle: 2`（不自动换行，已按字数切好）
- 单行最长实测 16 字 ≈ 883px，左右各留 ~100px，**不裁切**
- 平均 2.0 秒一条（209 条 / 416.6s）

---

## 9. 质检清单

### 9.1 每阶段门禁

| 阶段 | 门禁 | 不过的退出码 |
| --- | --- | --- |
| S1 | 页数/章数 > 0 | 3 |
| S2 | 章节标题页人工确认 | 3 |
| S3 | 介绍页 §6.6 全过 + `reviewed=true` | 3 |
| S4 | 每页有 `panels.json` 且 `source=manual` | 3 |
| S6 | 音频存在且 > 44 字节、时长 > 0 | 4 |
| S7 | 总时长与音频累加差 < 0.05s | 4 |
| S8 | §9.2 全部硬指标 | 4 |

### 9.2 成片验收（15 条，逐条独立复验）

| # | 项 | 判据 | 复验方法 |
| --- | --- | --- | --- |
| 1 | 画布 | 1080×1920 | `ffprobe -show_entries stream=width,height` |
| 2 | 帧率 | 30fps | 同上 `avg_frame_rate` |
| 3 | 像素格式 | `yuv420p` | 同上 `pix_fmt` |
| 4 | 有音轨 | 是 | `-select_streams a:0` |
| 5 | **视频轨时长** | 与 `total_duration` 差 < 0.2s | `stream=duration`（**不是 `format=duration`**） |
| 6 | 容器时长 | 与 `total_duration` 差 < 0.2s | `format=duration` |
| 7 | 帧数自洽 | `frames ≈ duration × 30`（±2 帧） | `stream=nb_frames` |
| 8 | 字幕纯白 | 字幕带亮部最高频 = 255 | 抽帧取灰度直方图 |
| 9 | 描边存在 | 字幕带暗像素（<60）> 5000 | 同上 |
| 10 | 版面三段 | 标签 18–48 / 漫画 72–1703 / 字幕 1747–1821（±6px） | 抽帧测行范围 |
| 11 | 章节标签 | 右上、浅灰、覆盖全片 | 读 `.ass` 的 `Style: Chapter` + `Dialogue: 1` |
| 12 | 单页停留 | 3.5–26s | `plan_page_windows` 计算 |
| 13 | 页序列 | 与 `script.json` 完全一致 | 比对列表 |
| 14 | **切页同步** | 每页窗口越出"讲这一页的段"累计 ≤ 0.5s | `page_sync()` 逐页算越界时长 |
| 15 | **内容密度** | 45–90 字/页 | 总字数 ÷ 总页数 |

### 9.3 抽帧复验（人工 6 帧）

取 `t = 0.5s`、`1/6`、`2/6`、`3/6`、`4/6`、`5/6` 六个时刻，逐帧确认：
画面内容与字幕语义一致、标签在、字幕不裁切。**这一条不能自动化，必须人看。**

---

## 10. 失败模式与退出码

| 退出码 | 含义 | 典型触发 |
| --- | --- | --- |
| 0 | 成功 | — |
| 2 | 用法/输入冲突 | 一次传 2 个 mobi；argparse 用法错 |
| 3 | 前置条件未满足 | 空摄取、有未确认页、无页面、介绍页未审 |
| 4 | 运行期失败 | 文件缺失/损坏、TTS 失败、ffmpeg 失败、渲染校验不过 |

**硬规矩：失败必须非零退出 + stderr 一行 `error: …`，不许 traceback，不许出半成品。**

常见失败对照：

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| 成片最后几秒画面卡住 | 视频轨比音频短（末帧无 duration） | 查流级时长，见 §13 坑 2 |
| 字幕只在换页时变 | `ass` 作用在"每页一帧"上 | 滤镜链加 `fps=30` 在最前 |
| 字幕发灰 | 色域没归一 | `scale=in_range=full:out_range=tv` 放 `ass` 前 |
| 换了语速，音频却是旧速度 | 缓存键没含 rate | 内容寻址缓存 + 索引含 rate |
| 改了布局但画面没变 | 帧缓存目录没含布局参数 | 目录名带 `b/m/t` 参数 |
| `NoAudioReceived` 但退出 0 | 异常被吞 | 重跑并核对退出码与产物 |

---

## 11. 幂等、缓存与重跑

### 11.1 缓存键

| 缓存 | 键 | 位置 |
| --- | --- | --- |
| TTS 音频 | `sha256(text + voice + rate + backend)` | `cache/tts/<key>.wav` |
| TTS 索引 | 同上 | `cache/tts_index_v3.json` |
| 目标画布帧 | `WxH-fit-bg-b<band>-m<margin>-t<top>` | `cache/frames/<key>/` |
| 音频拼接 | 段音频集合 | `cache/audio_concat.wav` |

### 11.2 变更影响面

| 改了什么 | 要重算什么 |
| --- | --- |
| 某段文本 | 该段 TTS + 该段之后的时间轴 + 全片渲染 |
| 某段页映射 | 时间轴 + 全片渲染（音频不重算） |
| 音色/语速 | 全部 TTS + 时间轴 + 渲染 |
| 画布/填充/底色/边距 | 全部帧 + 渲染（音频不重算） |
| 字幕字号/位置 | 只重生成 ASS + 渲染 |
| 章节标签 | 只重生成 ASS + 渲染 |

### 11.3 重跑语义

- 所有中间产物**可安全删除重跑**，不产生副作用
- 帧缓存与 TTS 缓存**只增不减**，磁盘紧张时手动清理 `cache/`
- 同一输入重复跑，成片**逐帧一致**（ffmpeg 参数固定、无随机性）

---

## 12. 性能基线（实测）

| 环节 | 规模 | 耗时 |
| --- | --- | --- |
| S1 摄取 | 169 页 mobi | ~3s |
| S2 墨量统计 | 169 页 | ~10s |
| S3 页面解读 | 1 页 | 8–12s（模型） |
| S4 自动分格 | 1 页 | ~0.3s |
| S6 TTS | 25 段 / 2393 字 | ~2.5 min（网络） |
| S7 时间轴 | 25 段 | <1s |
| S8 帧生成 | 38 页 | ~40s |
| S8 编码 | 416.6s / 12498 帧 | ~70s |
| **合计（38 页 6:56）** | — | **首次 ~5 分钟，改稿重跑 ~2 分钟** |

---

## 13. 已知坑（血泪清单）

1. **`concat` demuxer 每页只吐一帧**。`-vf ass=` 直接接上去，字幕只在换页时变。
   → 滤镜链最前面 `fps=30`。
2. **视频轨会比音频短**。末帧（repeat 的那条）没有 duration，视频轨提前收尾：
   90.19s 的片子只出 83.27s / 2498 帧，而容器时长仍按音频算，**看不出来**。
   → `probe_video` 必须读 `stream=duration` 并断言。
3. **字幕 235 灰**。漫画帧按 full range 写、libass 按 tv 压缩。
   → `scale=in_range=full:out_range=tv` 必须在 `ass` 之前。
4. **`edge-tts` 的 `save()` 拿不到句边界**，必须 `stream()`。
5. **`WordBoundary` 对中文全 0**，别指望词级对齐。
6. **`-vf tile=` 拼缩略图只出 1 帧**，别用它做联系表。
7. **`$?` 会被管道吞掉**。`cmd | tail` 之后的 `$?` 是 `tail` 的，要用 `${PIPESTATUS[0]}`。
8. **Git-Bash 的 `/d/...` 路径 Python 认不了**，脚本里用 `D:/...`。
9. **Windows 盘符在 ffmpeg 滤镜参数里会被当分隔符**，`ass=` 用相对名 + `cwd`。
10. **改了布局却不换缓存目录**，会静默复用旧位置的帧。
11. **`PANELCAST_FFMPEG` 指到不存在的路径会静默回退**，不报错。
12. **切页不能全局均分**。按"总时长÷总页数"均分，某页的切页时刻会跑到别的段的区间里——
    实测第三章最大偏移 32 秒，全片 249 次切页有 209 次偏移 >0.5 秒，画面和配音彻底脱钩。
    切页点必须由**本段的句边界**决定（`_segment_cuts`），停留上限只做体检、不做掩盖。

---

## 14. 后续版本

### 14.1 V1.1 待补（按优先级）

1. `m1 chapter`：S2 章节定界自动化 + 人工确认（现在靠人肉看横幅）
2. `m1 profile`：S3 页面解读**自动生成**（字段规范与自检已就绪，见下条；缺的是"读图填字段"这一步）
3. `m1 verify`：把 §9.2 的 13 条做成一条命令，出 `run_report.json`
4. 编辑器加"介绍页校对"面板（现在只改分格）
5. 长段拆页：让单页停留稳定落在 8–12 秒

其中第 2 条的**校验半边已经落地**：`panelcast/profile.py` + `docs/schemas/page-profile.schema.json`
能对一份介绍页跑完 §6.6 八条门禁（`python -m panelcast.profile … --ship`，37 个测试覆盖）。
剩下的是生成半边——按 §6.5 的规则逐页读图填字段，这一步要接视觉模型。

### 14.2 V2 展望（无漫画素材复用）

V2 的输入是 §6.7 的检索单，输出是能直接落进 `pages/` 的替代图：

```
page_XXXX.profile.json
   → asset-request.json
   → 检索/生成（图库 / AI 生图 / 同章复用 / 文字卡）
   → pages/page_XXXX.jpg（同尺寸、同安全区）
   → 走同一条 S4..S8 管线
```

**关键约束**：替代图必须遵守 §7 的安全区（`y=72..1747`），
且分辨率不低于 1080×1620，否则会在缩放后糊掉。

---

## 附录 A 命令速查

```bash
# S0/S1 摄取（一次一对输入）
python -m panelcast ingest "この素晴らしい世界に祝福を！/漫画/1卷.mobi" -o .local/src_v1

# S4 分格候选 + 人工确认
python -m panelcast m1 panels --work m1/ch1/work
python -m panelcast m1 edit   --work m1/ch1/work --port 8642

# S6–S8 一键出片
python -m panelcast m1 run \
  --work m1/ch1/work --out m1/ch1/out \
  --voice zh-CN-YunxiNeural --rate "+20%" \
  --size 1080x1920 --fit blurpad --bg white --subs burn \
  --chapter "第一章 与自称是女神的家伙一起转生到异世界！" \
  --name 第一章

# 测试
python -m unittest discover -s tests -q

# 介绍页校验（§6.6 八条门禁）
python -m panelcast.profile m1/ch1/work/profiles/*.json --ship

# 质检：视频轨 vs 音频
ffprobe -v error -show_entries stream=codec_type,duration,nb_frames \
  -of default=nw=1 "m1/ch1/out/第一章.mp4"
```

## 附录 B 介绍页完整示例（page_0021，已逐格核对原图）

这一页值得当范例，因为它同时踩到三个坑：**无页码**、**黑白页**、**说话人不在画面上**。
原图 668×1009，4 格，繁体竖排，页脚无印刷页码。

```json
{
  "schema": "page-profile/v1",
  "page": "page_0021",
  "source": {
    "series": "为美好的世界献上祝福！",
    "volume": "漫画 第1卷",
    "file": "1卷.mobi",
    "page_index": 21,
    "printed_page": null,
    "sha256": "cec1fce82d76156b4489d683db28aad80e9c36371d31539c3e559e7f1bd482ce",
    "width": 668,
    "height": 1009
  },
  "chapter": {
    "id": "ch01",
    "label_zh": "第一章 与自称是女神的家伙一起转生到异世界！"
  },
  "layout": {
    "kind": "story",
    "is_color": false,
    "panel_count": 4,
    "reading_direction": "rtl",
    "text_density": "medium",
    "has_splash": false,
    "borderless": false
  },
  "story": {
    "beat": "establishing",
    "summary": "公会建筑外观、酒馆喧闹，最后一格柜台小姐出声招呼",
    "characters": [
      {"name": "露娜", "role": "supporting", "region": "bottom", "expression": "闭眼微笑"}
    ],
    "location": "阿克塞尔·冒险者公会（外观 + 一楼酒馆）",
    "time_of_day": "day",
    "weather": "indoor",
    "emotion": "warm",
    "continuity": "cut"
  },
  "text": {
    "bubbles": [
      {"speaker": "和真（画外·心声）", "text": "現在只能找人問路了…（旁注：向矮人之類的問路，不知道會不會有問題…）", "region": "top-right", "is_shout": false},
      {"speaker": "露娜", "text": "歡迎來到新手冒險者的城鎮·阿克賽爾…", "region": "bottom-right", "is_shout": false},
      {"speaker": "露娜", "text": "請問今天有什麼事要辦理的嗎？", "region": "bottom-right", "is_shout": false}
    ],
    "narration_boxes": [],
    "sfx": ["ヤァ"],
    "verbatim_complete": true,
    "ocr_confidence": 0.92
  },
  "visual": {
    "shot": "wide",
    "composition": "上格横幅建筑外观，中格左右双分（人群中景 / 酒馆全景），下格人物特写",
    "key_props": ["公会建筑", "木桶", "酒杯", "圆桌", "荷叶边头巾"],
    "palette": ["#f9f9f9", "#a9a9a9", "#4a4a4a", "#030303"],
    "motion_hint": "static"
  },
  "reuse": {
    "replaceable": true,
    "replace_strategy": "stock",
    "scene_tags": ["indoor.guild_hall", "outdoor.street", "character.group"],
    "asset_brief": "欧洲中世纪木结构公会建筑外观与石铺街道，白天；室内是挤满冒险者的酒馆，圆桌木桶，人群中一位戴荷叶边头巾的柜台少女微笑招呼",
    "blocking_reason": null
  },
  "provenance": {
    "generated_by": "vision:glm-4.6v+human",
    "generated_at": "2026-11-16T02:05:00+08:00",
    "confidence": 0.9,
    "reviewed": true,
    "reviewer_notes": "页脚无印刷页码故 printed_page=null；顶格椭圆泡无尖角、画面内无说话人，判为和真画外心声；人物区只登记露娜，前两格的剪影无法辨认故不登记；ヤァ 出现三次，取一次入 sfx"
  }
}
```

几个刻意的选择，抄的时候照做：

- **`printed_page: null`**——这卷 mobi 是扫描件，页脚没有印刷页码。填 `page_index` 冒充页码会让后续引用错位。
- **`palette` 是四个灰度**——黑白页编出暖色是典型的模型幻觉，素材检索会因此命中彩色图库。
- **`motion_hint: static`**——4 格密集页，任何推拉都会让观众看不清格内信息。V1 本来也不做运镜。
- **`characters` 只登记露娜**——前两格那两个人影无法确认身份，宁可少登记也不许猜。
- **`asset_brief` 不带"阿克娅/和真"**——换成"戴荷叶边头巾的柜台少女"才搜得到通用素材（§6.5 第 4 条）。

## 附录 C 实测数据来源

| 数据 | 来源 |
| --- | --- |
| 169 页 / 62 种尺寸 / 宽 160–768 | `.local/src_v1/mobi/pages.json`（逐条统计） |
| page_0021 = 668×1009, sha256 `cec1fce8…82ce` | 同上 |
| 该页 4 格 / 3 气泡 / 无页码 / 灰度 p50=249 p25=169 p10=74 p02=3 | 原图逐格放大读取 + `ffmpeg -pix_fmt gray` 直方图 |
| 章节结构 p5–p42 | 墨量统计 + 横幅页人工确认（见 §5.3） |
| 5.74 字/秒 | 2393 字 / 416.6s |
| 版面 18–48 / 72–1703 / 1747–1821 | 成片抽帧灰度行范围 |
| 字幕填充 255 | 抽帧字幕带灰度直方图最高频 |
| 12498 帧 | `ffprobe stream=nb_frames` |
| 句锚点误差 3ms/5ms | 锚点插值 vs 实际切点对比 |
| 旧方法误差 205/463/805ms | 按字数比例 vs 锚点基准对比 |
| 测试 80 个 | `python -m unittest discover -s tests` |
