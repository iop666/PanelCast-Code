# PanelCast 项目地图（审核用）

> 生成于 2026-11-16。本文件描述**磁盘上真实存在的东西**，不是理想结构。
> 主规范是 `docs/WORKFLOW-v1-vertical-manga-narration.md`（约 1,800 行），
> **优先级与排期看 `docs/ROADMAP.md`**。本文件是"目录 + 状态"摘要，
> 三者冲突时：优先级以 ROADMAP 为准，做法以主规范为准，事实以磁盘为准。

---

## 0. 审核怎么读

全项目的东西分四档，下文每个条目都标了档位：

| 标记 | 含义 | 能不能信 |
| --- | --- | --- |
| **【跑通】** | 代码在、测试过、实际出过产物 | 能信 |
| **【半自动】** | 代码只做一半，另一半靠人/模型，产物在 | 能用，要知道哪半是人的 |
| **【占位】** | 结构在、字段齐，内容是空壳 | **不能信内容** |
| **【待建】** | 规范写了，代码没有 | 只能当计划看 |

**最重要的一句**：`m1/` 下十章成片是**测试稿**。技术指标（15 条验收）全绿，
但讲稿的底稿对齐（`novel_ref.json`）是 2026-11-16 才写进规范的，
这十章全部产出于它之前，所以**没有任何一章的旁白可以追溯到小说段落**。

**两件事必须分开记，永远不要混**：

| | 含义 | 十章现状 |
| --- | --- | --- |
| **技术合格** | 视频生成成功、能播、音轨对、字幕参数对 | ✅ 15/15 |
| **内容合格** | 每段旁白可追溯到小说原文或画面证据 | ❌ 0/10（见 ROADMAP P0） |

技术合格不能推断内容合格。这是本轮审核最核心的结论。

---

## 1. 真实目录树

```
PanelCast\
│
├── panelcast/                      【跑通】代码，5,649 行，仅标准库
│   ├── novel.py             674   S5a 底稿对齐 + script-audit 校验（m1 novel）
│   ├── __main__.py          657   CLI 入口（ingest / m1 slice|panels|edit|run|verify|novel|chapter）
│   ├── timeline.py          514   时间轴：段时长、页窗口、切页同步
│   ├── panels.py            435   分格检测（行/列投影 + Otsu）+ ffmpeg 定位
│   ├── chapters.py          386   章节定界 + 按章切 work（m1 slice）
│   ├── verify.py            385   成片 15 条验收，出 run_report.json
│   ├── render.py            321   逐页画布 → concat → 烧字幕
│   ├── identity.py          460   章节身份：uid 解析 + 跨文件强校验 + fail-closed（P0-08/07）
│   ├── profile.py           303   介绍页 schema 校验（§6.6 八条门禁）
│   ├── tts.py               295   edge-tts，stream() 收句锚点
│   ├── profile_auto.py      279   介绍页**骨架**生成（内容留空，见 §5）
│   ├── manifest.py          140   摄取清单
│   ├── epub_ingest.py       127   epub → chapters/*.xhtml
│   ├── mobi_ingest.py        78   mobi → pages/*.jpg（扫 PDB 里的 JPEG）
│   ├── jpeg.py               65   尺寸探测
│   ├── errors.py              2   退出码
│   └── editor/                    【跑通】本地校对工具
│       ├── server.py              HTTP + 分格/介绍页读写
│       └── static/index.html      浏览器界面（两个页签）
│
├── tests/                          【跑通】18 个文件 / 384 用例 / OK(skipped=2)
│
├── tools/                          三个不进 CLI 的辅助脚本
│   ├── novel_extract.py     114   【跑通】epub → novel.txt + novel_index.json
│   ├── contact_sheet.py      89   【跑通】N 页拼一张联系表
│   └── strip_sheet.py        88   【跑通】裁同一条横带竖拼（找章节横幅）
│
├── docs/
│   ├── WORKFLOW-v1-vertical-manga-narration.md   主规范（唯一权威"怎么做"）
│   ├── ROADMAP.md                                **优先级唯一依据**（P0–P5）
│   ├── PROJECT-MAP.md                            本文件（目录 + 状态）
│   ├── ADR-001-source-ingestion.md               摄取层决策记录
│   ├── ADR-002-m1-render-stack.md                渲染栈决策记录
│   ├── schemas/page-profile.schema.json          介绍页 schema
│   ├── schemas/script-audit.schema.json          逐段审计 schema（v2，含 11 条条件规则）
│   └── tasks/
│       ├── P0-execution-plan.md                  P0 九项任务书
│       ├── M0-content-validation.md
│       ├── M1-minimal-loop.md
│       └── TASK-002-ingest-hardening.md
│
├── m0/                             早期内容验证，已归档，不再动
│
├── m1/                            出片产物区，1.5G
│   ├── labels/v1.json  v2.json     【跑通】章节边界，人工读横幅确认
│   ├── delivery.md                 十章成片清单（时长/大小/验收）
│   ├── capability_report.md        S0 环境探测实测结果
│   ├── audit/                      【新增】内容审计区（P0-01/02/03 的产物）
│   │   ├── chapter-map.md          章节对应表（第一章已核，其余九章标「未核」）
│   │   ├── script-audit-ch01.md    第一章逐段审计（801 行，人读版）
│   │   └── P0-01-SAMPLE-CH01-report.md  第一章样张执行报告
│   ├── v1/work/                    整卷工作区（第 1 卷，169 页）
│   │   ├── pages/                  169 张页图（git 忽略）
│   │   ├── profiles/               145 份介绍页【占位】
│   │   └── chapter_index.json      【跑通】5 章，p5/45/75/105/137
│   ├── v1/ch01..ch05/              章级工作区 + 成片（ch01/work 是第一章样张，5 份产物未签核）
│   ├── v2/work/                    整卷工作区（第 2 卷，167 页）
│   │   ├── pages/ 167 张
│   │   ├── profiles/ 146 份【占位】
│   │   └── chapter_index.json      7 章，p3/31/39/67/83/107/138
│   ├── v2/ch06..ch10/              章级工作区 + 成片
│   ├── ch1/                        ⚠ 旧约定遗留，233M，可删
│   ├── work/                       ⚠ 最早单章实验，75M，可删
│   └── out/                        ⚠ 最早样片 sample.*，9.7M，可删
│
├── .local/                         源素材缓存，155M，git 忽略
│   ├── source/                     当前卷：epub/chapters.json + mobi/pages(26M)
│   ├── src_v1/  src_v2/            第 1、2 卷页图副本（各 26M）
│   └── review-*/                   ⚠ 测试遗留 4 个，共 78M，可删
│
├── この素晴らしい世界に祝福を！/    素材，git 忽略
│   ├── 漫画/    22 个 mobi（1–18 卷 + 話111-125）
│   ├── 正文/    18 个 epub（1–17 卷 + 台版）
│   └── 外传及短篇/  10 个
│
├── README.md                       仍停留在"只做 ingest"阶段，已过时
├── pyproject.toml
└── .gitignore                      素材 / 页图 / 音频 / 缓存 / 成片 全部排除
```

### 1.1 章级工作区里有什么（以 `m1/v1/ch02/` 为例）

```
ch02/
├── work/
│   ├── pages/          30 张页图（硬链接自整卷 work，不占额外空间）
│   ├── chapter.json    【跑通】schema chapter-work/v1，记 label / pages / page_count
│   ├── script.json     【半自动】讲稿，人工写的 29 段
│   ├── timeline.json   【跑通】机器生成：段起止、句锚点、总时长
│   ├── audio/          seg_0001.wav …（edge-tts 产物）
│   └── cache/          tts/<sha256>.wav 内容寻址 + frames/ 逐页画布 PNG
└── out/
    ├── 第二章.mp4      43M
    ├── 第二章.srt      独立字幕
    ├── 第二章.ass      烧入用的样式文件
    └── run_report.json 15 条验收明细
```

**入库的只有** `chapter.json` / `script.json` / `timeline.json` 三个文件。
页图、音频、帧缓存、成片全部 git 忽略（`.gitignore` 有对应规则）。

### 1.2 两个命名不一致，审核时注意

| 位置 | 第二卷的章节 id |
| --- | --- |
| 目录名 | `m1/v2/ch06` … `m1/v2/ch10`（按全书连续编号） |
| `chapter_index.json` | `ch01` … `ch07`（按卷内编号） |

两套编号并存。`find_chapter` 支持 `chapter_uid` / `id` / `number`（「第六章」）三种键，
但**多命中直接报错**，不挑"最接近"的——`chapter_uid` 是唯一无歧义的身份。

**P0-08 已实现**：`chapter_uid`（全书唯一）、`global_chapter_number`（全书编号）、
`volume_chapter_number`（卷内编号）三者分开，`id` 只作兼容字段、不再承担第二种含义。
目录名 `ch06` 的含义固定为**全书号**，由 `m1 chapter --verify` 强制校验。

**校验边界（P0-REVIEW-07 起 fail-closed）**：权威表 `chapter_index.json`
缺失、损坏、为空，或索引自身不合格（uid / id / number 重复、卷内编号不连续）
一律拒绝；身份文件存在但 JSON 损坏也拒绝，不再当成"不存在"。
唯一跳过方式是代码里显式传 `authority=False`，只用于确实没有卷级索引的临时目录。

---

## 2. 工作流：十阶段 + 两个补丁阶段

### 2.1 全景

```
mobi ─S1─► pages/*.jpg ─S2─► chapter_index.json
                            │
                            ├─S3─► page_XXXX.profile.json ──► 素材检索单（V2）
                            │
                            └─S4─► *.candidates.json ──人工──► *.panels.json
                                                                    │
epub ─S1─► chapters/*.xhtml ─S1'─► novel.txt + novel_index.json     │
                                       │                            │
                            S5a 底稿对齐 ──► novel_ref.json         │
                                       │                            │
                                       └──► S5 讲稿 ──► script.json ◄┘
                                                          │
                                        ┌─────────────────┼─────────────────┐
                                        S6 配音        S7 时间轴        S8 渲染
                                        audio/*.wav    timeline.json    .mp4/.srt/.ass
                                                          │
                                                          └─S9─► run_report.json（15 条）
```

### 2.2 阶段表

| 阶段 | 做什么 | 执行者 | 产物 | 现状 |
| --- | --- | --- | --- | --- |
| S0 | 能力探测：ffmpeg/ffprobe/libx264/TTS/写权限 | 机器 | `capability_report.md` | 【跑通】 |
| S1 | 素材摄取：mobi 扫 JPEG、epub 取 XHTML | 机器 | `pages/*.jpg` + `pages.json` | 【跑通】 |
| **S1'** | 小说纯文本化 | 机器 | `novel.txt` + `novel_index.json` | 【跑通】`tools/novel_extract.py` |
| S2 | 章节定界：读横幅确认章首 | 机器 + 人 | `chapter_index.json` | 【半自动】边界靠人读横幅 |
| S3 | 页面解读：逐页读图填结构化介绍页 | 视觉模型 + 人 | `page_XXXX.profile.json` | 【占位】只有骨架 |
| S4 | 分格：投影给候选框，人在浏览器修 | 机器 + 人 | `*.panels.json` | 【跑通】 |
| **S5a** | 底稿对齐：小说段 ↔ 漫画页 | 人 + 模型 | `novel_ref.json` | 【部分】骨架已实现，逐 beat 判定靠人 |
| S5 | 讲稿：按拍点写 1–3 页一段旁白 | 人（模型辅助） | `script.json` | 【半自动】纯人工 |
| S6 | 配音：edge-tts，收句锚点 | 机器 | `audio/*.wav` + 索引 | 【跑通】 |
| S7 | 时间轴：累加真实时长，段内切页 | 机器 | `timeline.json` | 【跑通】 |
| S8 | 渲染：逐页画布 → concat → 烧字幕 | 机器 | `<章名>.mp4/.srt/.ass` | 【跑通】 |
| S9 | 验收：15 条独立复验 | 机器 + 人 | `run_report.json` | 【跑通】 |

### 2.3 每个阶段的输入 / 门禁 / 命令

| 阶段 | 输入 | 门禁（不过就停） | 命令 |
| --- | --- | --- | --- |
| S0 | 本机环境 | 任一探测不过 → 停，**不许装软件凑通** | 人工跑探测，结论写 `m1/capability_report.md`（无 CLI 子命令） |
| S1 | 一对 `.mobi` / `.epub` | 页数/章数为 0 → 退出码 3；同类 >1 → 退出码 2 | `python -m panelcast ingest <mobi> <epub> -o .local/src_v1` |
| S1' | `.epub` | 无 `chapter*.xhtml` → 退出码 3 | `python tools/novel_extract.py --epub … --out .local/source/epub/text` |
| S2 | 整卷 pages | 章首必须人工确认横幅文字 | `m1 chapter --work …`（量墨量、找分隔页、确认标签） |
| S3 | pages + chapter_index | §6.6 八条 + `reviewed=true` | `m1 profile --work …`（**只填几何，语义留空**） |
| S4 | pages | 每页 `panels.json` 且 `source=manual` | `m1 panels` → `m1 edit --port 8642` |
| S5a | novel.txt + pages | 覆盖全部页；四类 `fidelity` 计数自洽 | （待建） |
| S5 | novel_ref + profiles | 45–90 字/页；每段回指 beat；回看抽查 | 人工写 `script.json` |
| S6 | script.json | 音频 > 44 字节、时长 > 0 | `m1 run` 内部 |
| S7 | 真实音频时长 | 总时长误差 < 0.05s | `m1 run` 内部 |
| S8 | timeline + 页图 | §9.2 全部硬指标 | `m1 run` |
| S9 | 成片 + 中间产物 | 15 条全过 | `m1 verify` |

> S2 与切章是两件事：`m1 chapter` 负责**定界**（量墨量、找分隔页、写 `chapter_index.json`），
> `m1 slice` 负责按已确认的边界**切出章级 work**。本作两卷的几何检测都失效，
> 边界是人读横幅定的，`m1 chapter` 只用来量数据。

### 2.4 一集的完整命令序列（可复制执行）

```bash
# 1) 摄取（每卷一次）
python -m panelcast ingest \
  "この素晴らしい世界に祝福を！/漫画/1卷.mobi" \
  "この素晴らしい世界に祝福を！/正文/1.epub" -o .local/src_v1

# 2) 小说纯文本（每卷一次）
python tools/novel_extract.py \
  --epub "この素晴らしい世界に祝福を！/正文/1.epub" \
  --out  .local/source/epub/text

# 3) 切章（每章一次，产出章级 work）
python -m panelcast m1 slice --work m1/v1/work --chapter 第二章 --out m1/v1/ch02/work

# 4) 分格（整页出片时可直接跳过，用满页框）
python -m panelcast m1 panels --work m1/v1/ch02/work
python -m panelcast m1 edit   --work m1/v1/ch02/work --port 8642

# 5) 写讲稿（人工）→ m1/v1/ch02/work/script.json

# 6) 出片
python -m panelcast m1 run \
  --work m1/v1/ch02/work --out m1/v1/ch02/out \
  --voice zh-CN-YunxiNeural --rate "+20%" \
  --size 1080x1920 --fit blurpad --bg white --subs burn \
  --chapter "第二章 替华美的高阶职业带来愉悦！" --name 第二章

# 7) 验收
python -m panelcast m1 verify --work m1/v1/ch02/work --out m1/v1/ch02/out --name 第二章
```

出片耗时实测：38 页约 5 分钟（首次），改稿重跑约 2 分钟。

### 2.5 横版模式（不在当前阶段）

横版不是"把 1080×1920 改成 1920×1080"，而是另一套视觉生产层：人工切格（允许重叠）→
阅读顺序确认 → 格级视觉时间轴 → 独立渲染器 → 独立验收（H1–H9）。

边界、数据契约 `panel-cuts/v1`、切格工具要求见主规范 §15；排期见 ROADMAP P1–P2。
**竖版现有整页流程不因横版改动**，横版也不得套用竖版页面时间轴。

---

## 3. 产物契约（五个 JSON）

| 文件 | 谁写 | 关键字段 | 现状 |
| --- | --- | --- | --- |
| `chapter.json` | `m1 slice` | `schema` / `label` / `pages` / `page_count` | 【跑通】 |
| `chapter_index.json` | 人工 | `chapters[].start_page/end_page/label_zh` | 【跑通】5 + 7 章 |
| `script.json` | 人工 | `segments[].{id,pages,text}`（`beats` 待补） | 【半自动】 |
| `timeline.json` | S7 | `segments[].{start,end,duration,sentences}` / `total_duration` | 【跑通】 |
| `run_report.json` | `m1 verify` | `checks[15]` / `passed` / `total_duration` | 【跑通】 |
| `page_XXXX.profile.json` | S3 | 十组字段，见 schema | 【占位】 |
| `novel_ref.json` | S5a | `beats[].{para,pages,fidelity}` / `coverage` / `judgement_scope` | 【已实现】P0-08 |
| `script-audit.json` | S5a 后置 | `segments[].{fidelity,alteration_origin,disposition,status}` / `review_status` | 【已实现】Schema v2 + `m1 novel lint` |

**页窗口的规则**（S7 最容易出错的地方）：一段覆盖 k 页，就在**这一段内部**找 k−1 个切点，
优先吸附真实句边界，硬约束是切点绝不越出本段。所以"一页停多久"等于"这段文字多长"，
不是"总时长 ÷ 总页数"。后者是早期 bug，会让画面比配音慢 30 秒。

---

## 4. 版面（竖屏 1080×1920）三段分区

```
y=0     ┌──────────────────────┐
        │              第一章 … │  ← 章节标签：右上，浅灰 #999999，字号 0.021H
y=72    ├──────────────────────┤
        │                      │
        │      漫画页（放大     │  ← 白底，页图等比缩放，黑边裁掉
        │      填满宽度）       │
        │                      │
y=1703  ├──────────────────────┤
        │   字幕：白字黑描边     │  ← 字幕带 1747–1821，字号约 0.052H
y=1821  └──────────────────────┘
```

参数：`BLURPAD_TOP_MARGIN=72`、`SUBTITLE_BAND_RATIO=0.14`、Alignment 9。
字幕去掉「，」「。」等标点。渲染滤镜链顺序不可改：
`fps=30` → `scale=in_range=full:out_range=tv` → `ass=`。

---

## 5. 当前真实状态（审核重点）

### 5.1 已经真跑通的

| 能力 | 证据 |
| --- | --- |
| 摄取 mobi / epub | 169 页 / 167 页，62 种页尺寸都能解 |
| 切章 | 12 个章级 work，页序正确 |
| 配音 + 时间轴 + 渲染 + 烧字幕 | 十章 mp4，每章 15/15 |
| 验收 | 15 条，`run_report.json` 逐条留痕 |
| 分格编辑器 | 分格页签 + 介绍页页签（schema 驱动表单） |
| 小说抽取 | 2,627 段 / 83,599 字；`sha256`（内容）与 `file_sha256`（落盘字节）双哈希稳定 |
| 测试 | 384 用例通过 |

### 5.2 半自动的

- **S2 章节定界**：程序侧能做的是「墨量测量 + 黑页/波点页配对反推」，
  这部分已实现且有测试。**做不了的是"横幅文字要人读一眼"**——横幅位置跨卷不固定
  （页首/中部/页脚都出现过），几何检测必然失效。所以边界是人一页页读横幅定的，
  结论记在 `m1/labels/v*.json`。能力一半在程序、一半在人，状态记**半自动**，不是【待建】。
- **S5 讲稿**：纯人工写，模型只做辅助。门禁是事后自查，不是写时拦截。

### 5.3 占位的（不能信内容）

- **291 份介绍页**（v1 145 + v2 146）：`story.summary` = `（待视觉补全）`、
  `characters` 空、`reviewed` 全为 `null`。只有 `layout` 和 `source` 是真测出来的。
  这是 `profile_auto.py` 生成的骨架，等 S3 接视觉模型填肉。
  **注意：这 291 份占位不阻塞竖版出片**——竖版 `visual_mode=page` 整页引用，
  不读 profile，不做画面检索。不要拿"S3 没审完"当停掉竖版的理由。

### 5.4 测试稿

- **十章成片**：技术合格，底稿不可追溯（无 `novel_ref.json`）。
  已知至少一处内容错误已修（第六章把"铁笼泡湖"写成"哥布林绑票"），
  但第一～五章是在同一套"只看画面"方法下写的，**风险同级，尚未逐章复核**。
- **第十一、十二章**：边界已确认（p107–137 / p138–148），无脚本无成片。

---

## 6. 可清理项（约 400M）

| 路径 | 大小 | 为什么能删 |
| --- | --- | --- |
| `m1/ch1/` | 233M | 第一章旧的目录约定，已重切到 `m1/v1/ch01/` |
| `m1/work/` | 75M | 最早的单章实验，被 `m1/v1/work/` 取代 |
| `.local/review-*`（4 个） | 78M | 摄取层测试遗留的页图副本 |
| `m1/out/sample.*` | 9.7M | 最早的分辨率/语速试验片 |

删之前确认两件事：`m1/ch1/work/script.json` 与 `m1/v1/ch01/work/script.json` 内容一致
（已核，25 段）；`m1/work/panels/` 有 16 个文件入库，删目录前先 `git rm --cached`。

---

## 7. 下一步

**排期以 `docs/ROADMAP.md` 为准。** 当前处于 **P0：内容可信度与规范闭环**，
具体任务书见 `docs/tasks/P0-execution-plan.md`。

P0 十一项，按依赖顺序：

| ID | 任务 | 产出 |
| --- | --- | --- |
| P0-01 | 核实十章 ↔ 小说 ↔ 讲稿的真实对应 | `m1/audit/chapter-map.md`（**第一章已核，九章未核**） |
| P0-02 | 十章各建 `novel_ref.json` | `m1/v{n}/chNN/work/novel_ref.json` × 10（**ch01 已建，34 beats 全 needs_review**） |
| P0-03 | 讲稿来源 **100%** 复核（不是抽查） | `m1/audit/script-audit-ch01.md`（**ch01 已审，13 段待改写 / 1 段待修页映射**） |
| P0-04 | 改稿后重出受影响成片 | 十章 mp4 + 更新的 `delivery.md` |
| P0-05 | `m1 novel --align/--check`（五步链）+ `lint`（Schema 校验） | CLI + 测试（`test_novel.py` 78 例） |
| P0-06 | 正式出片门禁（`--draft` 分离 + 审核报告校验） | `m1 run` 改动 + 测试 |
| P0-07 | 文档与实现统一 | 主规范 / 本文件 / README / CLI 帮助 |
| P0-08 | 章节身份统一 | ✅ `panelcast/identity.py` + `m1 chapter --verify`（`test_identity.py` 50 例） |
| P0-09 | 规则冲突核查 | 已核三处（时间轴、字数、哈希口径），结论已写进主规范 |
| P0-10 | `m1 verify --visual` 视觉验收 | 抽帧判据 + 测试 |
| P0-11 | `script.json` v1→v2 迁移 | 十章 v2 脚本 + 迁移脚本 |

P0 之后的 P1（横版切格工具）**不得提前开始**。

第十一、十二章出片（v2 p107–137 / p138–148）暂排在 P0-04 之后，
因为它们的讲稿也应当走 S5a 流程，而不是重犯"只看画面写稿"的老路。

---

## 8. 关于根目录 `README.md`

**当前状态**：根目录 `README.md` 已重写为「当前能力表 + 命令 + 文档索引 + 边界」，
共 112 行，不再是"只做 ingest"的旧文本。

**替换规则**（以后改 README 照这个来）：

1. **根目录 `README.md` 是唯一对外的项目说明**，不另设 `PROJECT-README.md`。
   审核文档里出现的「PROJECT-README」指的就是这个文件，不是新文件。
2. README 只写三件事：**现在能做什么、怎么跑、看哪份文档**。
   不做路线图（那是 `docs/ROADMAP.md`）、不做目录树（那是本文件）。
3. README 里的能力状态必须与本文件 §5「当前真实状态」一致：
   §5 写【占位】的，README 不得写成"支持"。
4. 改 README 时同步检查三处：CLI 帮助文本（`python -m panelcast --help`）、
   `m1 verify --help` 的验收条数、本文件 §5。
   **这四处曾经对不上过一次（帮助文本写 13 条，实际 15 条）。**
5. 交付物、临时文件、`.local/` 下的内容一律不进 README。
