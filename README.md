# PanelCast

把轻小说 / 漫画电子书源文件做成**竖版漫画解说视频**（1080×1920，漫画页 + 旁白 + 烧入字幕），
并保留一套可扩展的内容底座（小说底稿、剧情拍点、来源对齐），供后续横版切图模式复用。

Python 3.13，**仅标准库**；外部依赖只有 `ffmpeg` 与 `edge-tts`。

## 现在能做什么

| 能力 | 状态 | 命令 |
| --- | --- | --- |
| 素材摄取（mobi / epub） | ✅ | `python -m panelcast ingest` |
| 小说正文抽取（epub → 纯文本 + 段索引） | ✅ | `python tools/novel_extract.py` |
| 章节定界 | 半自动（程序测量 + 人读横幅） | `python -m panelcast m1 chapter` |
| 按章切工作区 | ✅ | `python -m panelcast m1 slice` |
| 分格候选 + 浏览器校对 | ✅ | `m1 panels` / `m1 edit` |
| 配音 → 时间轴 → 渲染 → 烧字幕 | ✅ | `m1 run` |
| 15 条技术验收 | ✅ | `m1 verify` |
| **底稿对齐（S5a）** | ⬜ 待建 | 见 ROADMAP P0-05 |
| **真实帧视觉验收** | ⬜ 待建 | 见 ROADMAP P0-06 |
| **横版切图模式** | ⬜ 待建 | 见 ROADMAP P1–P2 |

**状态口径**：✅ = 代码在、测试过、出过产物；半自动 = 有一半靠人；⬜ = 规范写了、代码没有。

## 快速开始

```bash
# 1) 摄取一对输入（至多一个 EPUB + 一个 MOBI）
python -m panelcast ingest \
  "この素晴らしい世界に祝福を！/漫画/1卷.mobi" \
  "この素晴らしい世界に祝福を！/正文/1.epub" -o .local/src_v1

# 2) 小说正文抽取（讲稿的底稿来源）
python tools/novel_extract.py \
  --epub "この素晴らしい世界に祝福を！/正文/1.epub" \
  --out  .local/source/epub/text

# 3) 切出一章的工作区
python -m panelcast m1 slice --work m1/v1/work --chapter 第二章 --out m1/v1/ch02/work

# 4) 出片（竖版整页模式，跳过分格门禁是合法默认）
python -m panelcast m1 run \
  --work m1/v1/ch02/work --out m1/v1/ch02/out \
  --voice zh-CN-YunxiNeural --rate "+20%" \
  --size 1080x1920 --fit blurpad --bg white --subs burn \
  --skip-panel-gate \
  --chapter "第二章 替华美的高阶职业带来愉悦！" --name 第二章

# 5) 验收
python -m panelcast m1 verify --work m1/v1/ch02/work --out m1/v1/ch02/out --name 第二章
```

## 出片参数

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `--size` | `WIDTHxHEIGHT` | 竖版用 `1080x1920`（默认 `1920x1080`） |
| `--fit` | `letterbox` / `cover` / `blurpad` | `blurpad` = 整页放大 + 底部字幕带（竖版推荐） |
| `--bg` | `blur` / `white` | `blurpad` 的底色，竖版用 `white` |
| `--subs` | `burn` / `none` | `burn` = 白字黑描边烧进画面，同时出 `.srt` / `.ass` |
| `--voice` | edge-tts 音色名 | 本作固定 `zh-CN-YunxiNeural`（云希） |
| `--rate` | 如 `+20%` | SSML 语速，实测时长变化约 1.24 倍（非线性） |
| `--skip-panel-gate` | 开关 | 竖版整页展示不需要分格，这是**合法默认路径**，不是偷懒 |

字幕按标点切成 ≤16 字单行，段内按字数占比切分该段**真实时长**；
画面字幕去掉 `，``。` 这类纯停顿标点。音频时长一律读 WAV 头，**禁止估算**。

## 版面

```
y=0     ┌──────────────────────┐
        │              第一章 … │  章节标签：右上，浅灰 #999999
y=72    ├──────────────────────┤
        │      漫画页（放大）    │  白底，等比缩放，裁掉黑边
y=1703  ├──────────────────────┤
        │   字幕：白字黑描边     │  字幕带 1747–1821
y=1821  └──────────────────────┘
```

## 目录

```
panelcast/   代码（15 模块 + editor/ 浏览器校对）
tests/       250 用例
tools/       novel_extract / contact_sheet / strip_sheet
docs/        WORKFLOW（怎么做）/ ROADMAP（先做什么）/ PROJECT-MAP（目录与状态）
m1/          出片产物区
```

## 文档

| 文件 | 作用 |
| --- | --- |
| [docs/WORKFLOW-v1-vertical-manga-narration.md](docs/WORKFLOW-v1-vertical-manga-narration.md) | 主规范：输入输出契约、阶段细则、介绍页规范、横版规划 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | **优先级唯一依据**（P0–P5） |
| [docs/PROJECT-MAP.md](docs/PROJECT-MAP.md) | 真实目录树 + 诚实状态 |
| [docs/tasks/P0-execution-plan.md](docs/tasks/P0-execution-plan.md) | P0 九项任务书 |
| [docs/ADR-001-source-ingestion.md](docs/ADR-001-source-ingestion.md) | 摄取方案决策 |
| [docs/ADR-002-m1-render-stack.md](docs/ADR-002-m1-render-stack.md) | 渲染栈决策 |

## 测试

```bash
python -m unittest discover -s tests -q     # 250 tests, OK (skipped=2)
```

## 边界（当前）

- **竖版只做整页展示**，不切格；分格是可选辅助能力。
- 横版切图模式是**独立扩展方向**，尚未实现，见 ROADMAP P1–P2。
- 十章成片是**技术合格**，不是**内容合格** —— 讲稿底稿尚未对齐，见 ROADMAP P0。
- 291 份介绍页是**空壳骨架**，不是语义资料库。
