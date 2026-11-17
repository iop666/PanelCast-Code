# 竖版漫画解说 · 第一版工作流（V1）

- 状态：V1 已出片（十章技术验收通过，**内容审计未完成**）
- 适用形态：手机竖屏 1080×1920，漫画页 + 旁白解说 + 底部烧入字幕
- 落地代码：`panelcast`（Python 3.13，仅标准库；外部依赖只有 `ffmpeg` 与 `edge-tts`）
- 基线样本：漫画第 1 卷 第一章（38 页 / 6:56 / 25 段 / 2393 字）
- 本文所有数字均为实测值，来源见附录 C
- **优先级看 `docs/ROADMAP.md`**（P0–P5）；本文只讲"怎么做"

---

## 0. 这份文档怎么用

这份文档定义 **V1 的输入契约、输出契约、十阶段工作方式（含 S5a 底稿对齐）、每页"介绍页"规范、
两种视觉模式（竖版整页 / 横版切格）的边界**。它是给四类人看的：

| 读者 | 该看哪几节 |
| --- | --- |
| 派任务的人（选题/审片） | §1 产品定义、§5 阶段总览、§9 质检清单、`docs/ROADMAP.md` |
| 执行的人/模型（写代码、写讲稿、跑流程） | §3 输入（尤其 §3.4 小说底稿）、§4 输出、§5 每阶段细则、§6 介绍页 |
| 后续接"无漫画素材复用"的人 | §6 全文，尤其 §6.7 检索单、§6.8 决策矩阵、§14.2 |
| 后续接横版切格的人 | §1.4 模式边界、§15 横版规划、ROADMAP P1–P2 |

文中标 **【已实现】** 的是当前代码里已经能跑的能力，标 **【部分】** 的是"机器那一半能跑、
人的那一半还没做"，标 **【待建】** 的是本规范要求、但代码还没写的能力。
**不要把【待建】当成已完成去汇报，也不要把【部分】当成全自动。**

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
| 15 条**技术**验收一键化 | 【已实现】 | `m1 verify`（含切页同步、内容密度） |
| 小说正文抽取（epub → `novel.txt` + 索引） | 【已实现】 | `python tools/novel_extract.py` |
| 章节自动定界 | 【待建】 | §5.3 |
| 介绍页语义自动生成（读图填字段） | 【待建】 | §5.4 / §6.5 |
| 底稿对齐 `novel_ref.json` | 【部分】 | `m1 novel align` 产骨架（全部 `unconfirmed`），**逐 beat 判定必须人做** |
| `m1 novel check` 五步门禁 | 【已实现】 | `m1 novel check`（P0-05） |
| 审核报告 Schema 校验 | 【已实现】 | `m1 novel lint`（P0-REVIEW-04） |
| 逐段内容审计 | 【部分】 | 第一章样张 25 段已出结论，**未签核**；其余九章未做 |
| 真实帧视觉验收 | 【待建】 | §9.5 |
| 章节全书唯一 ID + 身份强校验 | 【已实现】 | §4.3.1、`m1 chapter --verify`、ROADMAP P0-08 |
| 无漫画素材复用（V2 page 模式） | 【待建】 | §14.2 |
| **横版切格模式（V2 panel 模式）** | 【待建】 | §15、ROADMAP P1–P2 |

> **两条状态必须分开记**：十章成片是"技术合格"，不是"内容合格"。
> 内容合格要求每段旁白可追溯到小说或画面证据，见 §9.1 S5a 与 §9.4。

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
| 底稿可追溯 | 每段讲稿能回指小说段或明确标 `original` | 画面没画、小说没有的内容一个字都不许写（§3.4 / §9.4） |

### 1.3 V1 明确不做

- 转场、运镜、Ken Burns、BGM、音效
- 词级字幕对齐（V1 是句级 + 句内线性插值）
- 多音色分角色配音
- 自动分格（只给候选，必须人工确认）
- 无漫画素材的自动替换（V1 只产出"检索单"，替换是 V2）
- 在线协作、云端渲染、批量队列
- **漫画格级视频**（横版模式，见 §15；V1 竖版不切格）

### 1.4 两种视觉模式：竖版整页 / 横版切格

PanelCast 不是"把竖版改造成切格视频"，而是**同一套内容底座 + 两套视觉生产层**。
两条路线互不侵入，任何一边的改动不得破坏另一边。

| | 竖版（V1，当前） | 横版（V2，规划见 §15） |
| --- | --- | --- |
| `visual_mode` | `page` | `panel` |
| 视觉单位 | 一张完整漫画页 | 一张或多张独立漫画切图 |
| 画布 | 1080×1920 | 1920×1080（待样片冻结） |
| 切格 | **不要求**，`panels.json` 是可选辅助 | **必须**人工确认，允许重叠 |
| 时间轴 | 页面窗口（`timeline.json`） | 格级视觉时间轴（`visual_timeline.json`） |
| 状态 | 【已实现】 | 【待建】，P1–P2 |

**共用**：素材摄取、章节索引、小说纯文本、剧情 Beat、来源对齐（S5a）、讲稿、配音、
句锚点、内容审计、缓存、交付管理。

**分开**：视觉资产（整页 vs 切图）、布局（竖屏 vs 横版多图）、时间轴、渲染器、视觉验收。

> 竖版出片时 `--skip-panel-gate` 是**合法默认路径**，不是偷懒：整页展示不需要分格。
> 横版则相反，没有人工确认的切图与阅读顺序就不能出片。

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
| **底稿 / novel_ref** | 一章一份的对齐表，把小说段落映射到漫画页，见 §4.3.9 |
| **拍点 / beat** | 小说里一件连续发生的事，3–20 段，映射到 0–3 个漫画页 |
| **fidelity** | 一个拍点和漫画的关系：`drawn` 画了 / `omitted` 没画 / `altered` 改了 / `original` 漫画原创 |
| **工作区 / work** | 一次出片的中间目录，含 `pages/ panels/ audio/ cache/` |

---

## 3. 输入

### 3.1 素材形态

| 类型 | 格式 | 规模实测 | 说明 |
| --- | --- | --- | --- |
| 漫画 | `.mobi`（PDB 容器，内嵌 JPEG） | 1 卷 = 169 页；**62 种尺寸**，宽 160–768、高 240–1024，主力 672×1009（41 页）/ 648×1009（32 页），119 页高 1009 | 主视觉来源 |
| 小说 | `.epub`（OPF spine + XHTML） | 1 卷 = 6 个正文文件（序章 + 4 章 + 终章），**2,627 段 / 83,599 字**；整个 epub 89,599 字符（多出的是人物介绍、后记、版权） | **剧情底稿**，见 §3.4 |

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

### 3.4 小说是剧情底稿，不是参考读物

**事实优先级（写稿时不可调换）**：

```
介绍页 OCR 到的画面事实   >   小说原文事实   >   不许推理
```

画面里有的，按画面写；画面里没有但小说写了的，按小说写；两边都没有的，**一个字都不许写**。

漫画和小说之间只有四种关系，每段讲稿必须能归到其中一种（`novel_ref.json` 的 `fidelity`，见 §4.3.9）：

| 值 | 含义 | 写稿规则 |
| --- | --- | --- |
| `drawn` | 漫画画了，小说也写了 | 两边都可用，画面优先 |
| `omitted` | 小说写了，漫画没画 | 可以写，但只能写在"这段画面对应的小说情节"里，不能张冠李戴 |
| `altered` | 漫画改了细节（换地点、换顺序、合并人物） | **按漫画写**，不按小说纠正；差异记进 `note` |
| `original` | 漫画原创，小说里没有 | 只写画面能看见的，不加动机、不加台词 |

**三条实测教训**（这是本节存在的理由）：

1. **章标题是两套命名，不能用来对齐。** 小说第三章叫「在这座湖中加入鲜榨自称女神汁！」，
   漫画同一段剧情叫「第六章 为这片湖献上自称女神的圣水！」。同一个故事，两个名字，
   一个都不包含对方的关键词。
2. **漫画会重排小说。** 「圣水」在小说里首次出现于第四章第 87 段（贝尔迪亚第 60 段登场之后），
   漫画却把阿克娅卖圣水这段日常放在第一卷第五章，即无头骑士退走**之后**当卷末。
   按"第 N 章对第 M 章"硬套，这一章必然错位。
3. **有的漫画章小说里根本没有。** 第七章「遭到梦幻竹笋偷袭！」共 8 页，
   在 18 卷小说正文里搜「竹笋」只命中 1 次（vol.13），第一卷 0 次。
   这类章属于 `original`，只能"只写画面"，长度天然短——**不许为了凑时长硬编**。

所以对齐是**逐章的人工/模型工作**，不是一条命令：先用人物事件锚点定位小说区间（§5.6.1），
再把区间内的段落逐条判成上面四种关系，最后才写讲稿。

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
             text/novel.txt            # 去标签纯文本，段号连续，§5.6.1 用
             text/novel_index.json     # 章 → 段区间 + 字数 + sha256
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
        novel_ref.json             # 本章的底稿对齐表，见 §4.3.9
        script.json
        timeline.json
      out/
        第一章.mp4 第一章.srt 第一章.ass run_report.json
```

### 4.3 各产物 schema

#### 4.3.1 `chapter_index.json`【半自动：人工确认数据 + 程序辅助测量】

```json
{
  "schema": "chapter-index/v1",
  "series": "konosuba-manga",
  "volume_number": 1,
  "source_file": "1卷.mobi",
  "total_pages": 169,
  "chapters": [
    {
      "chapter_uid": "konosuba-manga-v01-ch01",
      "id": "ch01",
      "number": "第一章",
      "global_chapter_number": 1,
      "volume_chapter_number": 1,
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

**章节身份必须分开**（P0-08）：

| 字段 | 含义 | 现状 |
| --- | --- | --- |
| `chapter_uid` | 全书唯一，`<系列slug>-v<卷两位>-ch<全书两位>` | 【已实现】P0-08 |
| `global_chapter_number` | 全书连续编号（第六章 = 6） | 【已实现】P0-08 |
| `volume_chapter_number` | 卷内编号（第二卷第一话 = 1） | 【已实现】P0-08 |
| `id` | 卷内短 id，**仅供程序引用** | 现有，两卷都从 `ch01` 起 |
| `number` | 展示用章节号「第六章」 | 现有 |
| `label_zh` | 完整展示标签 | 现有 |

现状的坑：目录用 `ch06..ch10`（全书），`chapter_index.json` 用 `ch01..ch07`（卷内），
`find_chapter` 按 `id` 或 `number` 匹配才没炸。**人工对数必须看 `label_zh`，不要看 `id`。**
P0-08 会把三者分开，此后 `id` 不再承担两种含义。

##### P0-08 章节身份【已实现】

**问题**：三套编号在同一个目录里对不上。这不是"命名不统一"，
是**三个不同身份维度被混在一起**。实测证据（`m1/v2/ch06`）：

| 维度 | 迁移前的值 | 谁在用 |
| --- | --- | --- |
| 目录名 | `ch06` | 文件系统、脚本按路径找章 |
| `chapter.json` 的 `id` | `ch01` | 程序引用（`find_chapter`） |
| `chapter.json` 的 `number` | `第六章` | 展示、人工对数 |
| 实际身份 | 第二卷第一章（全书第六章） | 三者都没有正确表达 |

同一个"第六章"，`id` 说它是 `ch01`，目录说它是 `ch06`，`number` 说它是「第六章」。
**任一字段单独看都是对的，合起来就是错的。**

**危险在哪**：`P0-01` 的章节对应关系即使人工做对了，只要写进错误的工作区，
底稿、审计、讲稿会一起挂到另一章上，而且**门禁照样通过**——因为哈希绑的是文件内容，
不是章节身份。**哈希只能证明"没被改过"，证明不了"属于这一章"。**

**实现（`panelcast/identity.py`）**：

| 机制 | 行为 |
| --- | --- |
| `chapter_uid` | 唯一权威身份，`<系列slug>-v<卷两位>-ch<全书两位>`，如 `konosuba-manga-v02-ch06` |
| `make_uid` / `parse_uid` | 必须两位补零；`v2-ch6` 这类写法直接拒绝，避免"同一个身份两种字符串" |
| `chapter_problems` | 单章自洽：uid 解析出的卷号/全书号必须等于 `volume_number` / `global_chapter_number`；`number`（第六章）必须与全书号一致；`id` 必须等于 `ch{volume_chapter_number:02d}` |
| `index_problems` | 整卷自洽：`chapter_uid` / `id` / `number` 三者各自不许重复；`volume_chapter_number` 必须 1..N 连续 |
| `find_chapter` | 唯一命中才返回；**多命中报错并列出全部候选**，并提示改用 `chapter_uid` |
| `check_work_identity` | 交叉比对目录名、`chapter.json`、`novel_ref.json`、`script.json`、`script-audit.json`，**不一致就报错并列出全部值** |

**四条硬规则**：

1. `chapter_uid` 是机器内部**唯一**身份，跨文件引用只用它；
2. `id` / `number` 降级为展示或兼容字段，**不得**用于跨章定位；
3. 卷号、全书章节号、卷内章节号**分开存**，不许互相推导；
4. 四者不一致**明确报错**，报错信息同时列出全部值——**不许程序猜"最像的"**。

第 4 条是重点。迁移前 `find_chapter` 按 `id` 或 `number` 都能命中，
猜对是运气，猜错是静默错配。现在**多命中就是错误**。

**权威表与 fail-closed（P0-REVIEW-07）**：

五份文件自己一致，**证明不了它们没有一起抄错**一个不存在的章号。
能发现"集体一致地错"的只有卷级权威表 `chapter_index.json`，所以它不能"找不到就算了"：

| 情形 | 行为 |
| --- | --- |
| 找不到 `chapter_index.json` | **报错**（退出码 3）；只有代码里显式传 `authority=False` 才允许跳过 |
| 权威表存在但 JSON 损坏 | **报错**；损坏不等于没有 |
| 权威表 `chapters` 为空 | **报错** |
| 权威索引自身不合格（uid / id / number 重复、卷内编号不连续） | **报错**；章级与卷级都必须拒绝 |
| 身份文件（`chapter.json` / `novel_ref.json` / `script.json` / `script-audit.json`）存在但损坏 | **报错**；损坏不等于不存在 |

**权威表的搜索路径**：真实布局 `m1/v1/ch01/work` 的索引在
`m1/v1/work/chapter_index.json`。实现依次尝试
`<work>/…`、`<work>/work/…`、`<父>/…`、`<父>/work/…`、`<祖父>/…`、`<祖父>/work/…`。
早先只找 `work.parent` 与 `work.parent.parent`，两者都不指向 `work/` 子目录，
导致**章级校验从来没有真正加载过权威表**——"正常路径通过"其实是"根本没校验就通过"。

**目录名的含义固定为全书号**：`m1/v2/ch06` 的 `ch06` 指全书第 6 章，
不是卷内第 1 章。所以 `id=ch01` 与目录名 `ch06` 并存是**合法的**（前者卷内、后者全书），
但 `global_chapter_number` 必须等于 6，否则报错：

```
$ m1 chapter --work m1/v2/ch09/work --verify
error: 章节身份不一致（1 项）：
  - 目录名 'ch09' 表示全书第 9 章，但 chapter.json 的
    global_chapter_number=6（chapter_uid=konosuba-manga-v02-ch06）
```

**门禁接入**：`m1 novel check` 第 1 步先验身份，再验底稿存在。
身份不过时后面的内容校验没有意义——一份格式完全合法、哈希全部正确的审计，
也可能属于另一章。

**迁移结果**：两卷索引 + 十个章级 `chapter.json` 全部补齐身份字段；
`m1/v2/ch06–ch10` 的 `id` 仍是 `ch01–ch05`（卷内），但 `chapter_uid` 与
`global_chapter_number` 已是 6–10，`--verify` 十个目录全部通过。
**目录名没改**——改名会动十处路径，而身份统一不需要改目录。

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
- **门禁按 `visual_mode` 区分**（全文统一口径，别处不再重复）：
  - `visual_mode=page`（竖版）：**不要求分格**。`--skip-panel-gate` 是合法默认路径；
    页图存在、页序正确即可出片。`panels.json` 只是可选辅助。
  - `visual_mode=panel`（横版）：每页必须有**人工确认**的切图，且阅读顺序已确认
    （`confirmed_order` + `order_status=human_confirmed`，见 §15.3）。
    不满足 → 退出码 3。
- 整页不分格时，就写一个满页框——**这不是偷懒，是明确的编辑决定**

#### 4.3.4 `script.json`【v1 已实现 / v2 待建】

**两个版本并存，必须显式声明版本。**

##### v1（现状，十章成片用的就是这一版）

```json
{
  "segments": [
    {"id": "seg_0001", "pages": ["page_0005", "page_0006"], "text": "…"}
  ]
}
```

约束：`pages` 1–3 页；`text` 非空；`id` 唯一；引用页必须已确认。
**没有版本号字段时一律按 v1 处理。**

##### v2（目标结构，P0-05 迁移产出）

```json
{
  "schema": "script/v2",
  "chapter_uid": "konosuba-manga-v01-ch02",
  "segments": [
    {
      "id": "seg_0001",
      "narration": {
        "text": "讲解文字……",
        "source_refs": [
          {"type": "novel_beat", "id": "b03", "fidelity": "omitted", "note": ""},
          {"type": "page_visual", "id": "page_0045", "fidelity": "drawn", "note": "惠惠举杖的动作"}
        ]
      },
      "visual_refs": [
        {"type": "page", "id": "page_0045", "role": "context"}
      ]
    }
  ]
}
```

##### 完整字段路径（跨文件引用一律按这张表，不要写简写）

| 路径 | 类型 | 必填 | 取值 |
| --- | --- | --- | --- |
| `schema` | string | v2 必填 | `"script/v2"`；v1 无此字段 |
| `chapter_uid` | string | v2 必填 | 与 `chapter_index.json`、`novel_ref.json` 一致 |
| `segments[].id` | string | 是 | `seg_%04d`，全章唯一 |
| `segments[].narration.text` | string | 是 | 旁白原文 |
| `segments[].narration.source_refs[]` | array | 是 | **至少一条**，否则无法追溯 |
| `segments[].narration.source_refs[].type` | enum | 是 | `novel_beat` / `page_ocr` / `page_visual` / `setting` |
| `segments[].narration.source_refs[].id` | string | 是 | beat id / `page_XXXX` / 设定条目 id |
| `segments[].narration.source_refs[].fidelity` | enum | 是 | `drawn` / `omitted` / `altered` / `original`（§3.4） |
| `segments[].narration.source_refs[].note` | string | 否 | 为什么引用它 |
| `segments[].visual_refs[]` | array | 是 | 1–3 条；竖版 `type=page`，横版 `type=panel`（§15） |
| `segments[].visual_refs[].role` | enum | 是 | `depicts` / `context` / `aftermath` |

**四种来源类型的区别**（这是本轮补充的，之前只有前两种）：

| `type` | 证明什么 | 例 |
| --- | --- | --- |
| `novel_beat` | 小说原文里有这件事 | 达克妮丝在公会上提出入队 |
| `page_ocr` | 漫画**气泡文字**里写了 | 阿克娅喊「不要，太麻烦了」 |
| `page_visual` | 漫画**画面**里画了（动作/姿态/场景关系） | 惠惠举杖、笼子泡在水里、鳄鱼咬铁栏 |
| `setting` | 经审核的设定资料（P4 才有，V1 不用） | 角色年龄、地名 |

> **`page_ocr` 只覆盖文字，覆盖不了画面事实。** 漫画里大量信息是"画出来的"而不是"写出来的"，
> 如果只有 `page_ocr`，那"鳄鱼在啃笼子"这种没有台词的事实就无法标来源，
> 执行者只能含糊地标成 `novel_beat` 或干脆不标。所以必须有 `page_visual`。

##### 迁移规则（v1 → v2，任务号 P0-11）

> 本节规则是 P0-11 的施工依据。P0-11 依赖 P0-02（十章 `novel_ref.json` 齐备）——
> 没有 beat 就没有合法的 `source_refs` 来源，此时迁移只能靠猜，正是第 5 条禁止的。

| 步骤 | 规则 |
| --- | --- |
| 1 | `pages` → `visual_refs[{type:"page", id:<页>, role:"depicts"}]`，**机械转换，不推断语义** |
| 2 | `text` → `narration.text`，**一字不改** |
| 3 | `source_refs` **留空**，标 `[]`，由人/审计流程填 |
| 4 | 加 `schema: "script/v2"` 与 `chapter_uid` |
| 5 | **迁移不得自动推断剧情来源**。空 `source_refs` 就是空，不许猜一个 beat 填上 |

第 5 条是硬规则：自动填一个"看起来像"的 beat，比留空危害大得多——
它会让 `--check` 通过，而实际上没有人核过。

##### 迁移后的三态（P0-11 必须实现）

迁移成功**不等于**内容合格。每章脚本迁移后必须落在一个明确状态上，
三态存在 `work/migration-state.json`，**不允许含糊**：

| 状态 | 含义 | 允许做什么 | 谁可以置位 |
| --- | --- | --- | --- |
| `migrated_unreviewed` | 结构转换完成，内容**未**审核 | 可跑 `--check` 结构校验；**禁止正式出片** | 迁移脚本自动置位 |
| `content_reviewed` | 人工完成来源与剧情审核 | 可跑 `--draft` 预览 | **只能由审核流程置位**（需 `reviewed_by`） |
| `approved` | 满足正式出片全部条件 | 允许正式出片 | 审核流程 + 门禁全过 |

**关键约束**：迁移脚本跑完**只能**落到 `migrated_unreviewed`。
JSON 转换成功 ≠ 内容审过。**不许把"转换无报错"当成"可以出片"。**

`migrated_unreviewed` 的脚本 `source_refs` 全是 `[]`（按迁移第 3 步留空），
此时 `--check` 会在第 3 步报"来源为空"，这是**正确行为**，不是 bug。
要往 `content_reviewed` 走，只能靠人逐段填 `source_refs` 并签审核报告。

**兼容读取**：`m1 run` 必须同时读 v1 与 v2；`pages` 作为
`visual_refs[type=page]` 的简写继续支持。遇到 v1 文件按 v1 语义处理，
**不许把 v1 的 `pages` 当成"来源已确认"**。

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

#### 4.3.8 `run_report.json`【已实现】

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

#### 4.3.9 `novel_ref.json`【部分：骨架已实现，逐 beat 判定待人工】

一章一份，记录"这一章的画面，对应小说的哪几段，哪些照写、哪些没画、哪些改了"。
它是 §5.6.2 写稿的唯一依据，也是事后追责"这句旁白从哪来"的凭据。

`m1 novel align` 能自动产出的只有**骨架**：`para=null`、`fidelity="unconfirmed"`、
`review_status="needs_review"`、候选区间放 `para_candidates`。
**骨架不是结论**，`--check` 第 4 步会逐条拒绝未确认的 beat。

```json
{
  "schema": "novel-ref/v1",
  "chapter_uid": "konosuba-manga-v01-ch02",
  "judgement_scope": "manga_vs_novel",
  "chapter_id": "ch02",
  "label": "第二章 替华美的高阶职业带来愉悦！",
  "pages": [45, 74],
  "source": {
    "file": "この素晴らしい世界に祝福を！/正文/1.epub",
    "volume": 1,
    "sha256": "原始 EPUB 文件字节的 sha256",
    "text_sha256": "novel.txt 文件字节的 sha256（= novel_index.json 的 file_sha256）"
  },
  "novel_chapters": [
    {"index": "ch01", "title": "第一章 和这个自称女神转生到异世界！",
     "para_from": 338, "para_to": 563, "chars": 7900},
    {"index": "ch02", "title": "第二章 以这只右手偷取宝物（内裤）！",
     "para_from": 1, "para_to": 40, "chars": 1400}
  ],
  "order": "in_order",
  "beats": [
    {"id": "b01", "para": [338, 352], "gist": "惠惠在公会门口拦下和真，要求陪她练爆裂魔法",
     "pages": ["page_0045", "page_0046"], "fidelity": "drawn", "note": ""},
    {"id": "b02", "para": [353, 371], "gist": "两人去城外空地，惠惠每天只放一发",
     "pages": ["page_0047"], "fidelity": "drawn", "note": ""},
    {"id": "b03", "para": [372, 400], "gist": "达克妮丝在公会上提出入队",
     "pages": [], "fidelity": "omitted", "note": "漫画直接让达克妮丝在战斗中登场，省掉这段对话"},
    {"id": "b04", "para": null, "gist": "漫画原创：惠惠用爆裂魔法把练习场的树全烧了",
     "pages": ["page_0052"], "fidelity": "original", "note": "小说无对应段落"}
  ],
  "coverage": {
    "novel_chars": 9300,
    "script_chars": 1558,
    "beats_total": 24,
    "by_fidelity": {"drawn": 17, "omitted": 4, "altered": 2, "original": 1},
    "note": "omitted 的 4 段是本卷刻意压缩的日常，不影响主线"
  }
}
```

字段约束：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `chapter_uid` | 是 | **跨卷唯一身份**，`<系列>-v<卷两位>-ch<全书两位>`。跨文件引用一律用它 |
| `judgement_scope` | 是 | 固定 `"manga_vs_novel"`。**声明本文件里的 `fidelity` 判的是「漫画 vs 小说」**，见 §4.3.10 的两层语义 |
| `chapter_id` | 是 | 卷内短 id（`ch02`），**仅兼容用**，不得作为跨卷引用的唯一依据 |
| `source.sha256` | 是 | **原始 EPUB 文件**字节的 sha256。epub 换了 → 全部底稿失效 |
| `source.text_sha256` | 是 | **`novel.txt` 文件**字节的 sha256，等于 `novel_index.json` 的 `file_sha256` |
| `novel_chapters[].para_from/to` | 是 | **段号是 `novel.txt` 的全局段号**，不是章内序号，否则跨章区间没法表达 |
| `order` | 是 | `in_order` / `reordered` / `partial`。`reordered` 必须在 `note` 写明哪几段被挪动 |
| `beats[].para` | 是（`original` 可为 `null`） | 小说段区间；`null` 就是"小说里没有" |
| `beats[].pages` | 是 | 可空数组；空 = 这一段漫画没画 |
| `beats[].fidelity` | 是 | `drawn / omitted / altered / original`（§3.4） |
| `beats[].gist` | 是 | ≤ 40 字，一句话说清这一段发生了什么 |

**两个哈希不要混用**（这是容易实现错的地方）：

| 校验什么 | 用什么 | 对谁比 |
| --- | --- | --- |
| epub 有没有被换 | `source.sha256` | 当前 epub 文件字节 |
| 小说文本有没有被改 | `source.text_sha256` | `novel_index.json` 的 `file_sha256` |

> 注意 `novel_index.json` 里还有一个 `sha256`，那是**纯文本内容**哈希（段之间用 `\n` 连接），
> 不含文件尾部换行，所以它和 `file_sha256` **不相等**。`novel_ref` 用的是 `file_sha256`。
> `tools/novel_extract.py` 强制 LF 写盘，保证跨平台字节一致。

##### 哈希口径的实施复验（P0-A，四条必过）

字段设计正确不等于实现正确。实施时必须逐条验证这四种情况，
每条都要有对应测试，**不许只靠"看起来对"**：

| # | 场景 | 期望 | 为什么容易错 |
| --- | --- | --- | --- |
| 1 | Windows 与 Linux 生成相同的规范化文本 | 两次 `file_sha256` 完全相同 | 默认 `open()` 在 Windows 会做 `\n`→`\r\n` 转换 |
| 2 | 输入是 CRLF 的源文件 | 输出仍为 LF，哈希与 LF 源一致 | 读入侧若不做规范化，CRLF 会渗进输出 |
| 3 | 文件末尾有/无换行 | 口径固定为**带一个尾换行**，由 `render()` 决定 | 这是 `sha256` 与 `file_sha256` 差异的唯一来源 |
| 4 | 改动正文一个字节 | 门禁**必定失败**并指出是文本变了 | 若比的是内容哈希而改的是换行，会漏判 |

**旁路写入禁令**：`render()` 是所有 `novel.txt` 落盘的唯一出口。
任何新代码要写 `novel.txt`，必须调用它，**不得直接 `write_text` / `open(...,"w")`**。
一旦出现旁路，哈希与落盘字节就可能不一致，第 2 步门禁会变成随机通过/失败。
这条在 `tests/test_novel_extract.py` 里用「写盘字节 == `render()` 结果」的测试锁住。

**仓库侧 LF 的证据链（P0-REVIEW-06）**：上面四条讲的是**生成**文本；
`novel_ref.json` / `script-audit.json` 绑的字节还多经过一层 **git 检出**，
这层要单独证明。以下三条**必须合起来用**，单独任何一条都推不出结论：

| 证据 | 能证明 | 不能证明 |
| --- | --- | --- |
| `git ls-files --eol` 的 `i/lf` | blob 里存的是 LF | 证明不了检出到工作区后仍是 LF |
| `.gitattributes` 的 `* text=auto eol=lf` | 约束检出时的转换行为 | 纠正不了已经存进 blob 的 CRLF |
| 不同 `core.autocrlf` 下的新克隆 | 该配置下实际落盘字节 | 只覆盖被测过的配置 |

**不许单独拿 `i/lf` 推导"所有平台工作区都是 LF"**——这是审核明确要求保留的技术边界。
本仓实测 118 个文件 `i/lf`、`i/crlf` 计数为 0；`tests/test_lf.py` 6 例覆盖三种
`autocrlf` 的新克隆、索引侧零 CRLF、每个文件命中 `eol=lf`，并有
「删掉 `.gitattributes` 后 CRLF 确实泄漏」的反证防止主用例空跑。

**它不是必须 100% 覆盖的文档，而是必须 100% 诚实的文档**：宁可写 8 条 `omitted`，
也不许把没读过的段落标成 `drawn`。

#### 4.3.10 `script-audit.json`【已实现：Schema v2 + `m1 novel lint`】

**为什么需要它**：`novel_ref.json` 只证明"讲稿有来源"，**不证明"当前这份讲稿被审过"**。
没有它就会出现这个漏洞：

```
1. 某章完成 100% 人工审计
2. 之后有人改了一段旁白
3. 旧审计报告还在
4. 新讲稿照样通过结构检查 → 以"已审计"的名义出片
```

所以审核结果必须**绑定版本哈希**。讲稿或底稿一变，审计即失效。

一章一份，放 `work/script-audit.json`：

```json
{
  "schema": "script-audit/v2",
  "audit_spec_version": "v1.1",
  "judgement_scope": "narration_vs_source",
  "chapter_uid": "konosuba-manga-v01-ch02",
  "script_schema": "script/v2",
  "script_sha256": "当前 script.json 文件字节的 sha256",
  "novel_ref_sha256": "当前 novel_ref.json 文件字节的 sha256",
  "audited_segments": [
    {"segment_id": "seg_0001", "text_sha256": "该段 text 字段的 sha256",
     "status": "approved", "fidelity": "drawn", "alteration_origin": null,
     "disposition": "keep", "pages_declared": ["page_0045"],
     "novel_para": [[338, 352]], "evidence": "第一章 338–352；p45 分格 2"},
    {"segment_id": "seg_0002", "text_sha256": "…",
     "status": "pending_rewrite", "fidelity": "altered",
     "alteration_origin": "narration", "disposition": "rewrite",
     "pages_declared": ["page_0047"], "novel_para": [[353, 371]],
     "evidence": "小说 353–371 写的是……，旁白改成了……"},
    {"segment_id": "seg_0003", "text_sha256": "…",
     "status": "pending_rewrite", "fidelity": "altered",
     "alteration_origin": "manga", "disposition": "keep",
     "pages_declared": ["page_0052"], "novel_para": [[372, 400]],
     "evidence": "漫画把小说的 A 改成 B，旁白忠于 p52 的 B"}
  ],
  "review_status": "pending_human",
  "reviewed_by": null,
  "reviewed_at": null,
  "notes": "…"
}
```

##### 两层 `fidelity`：同名不同义，必须显式声明

这是本规范最容易混用的地方，也是 `judgement_scope` 存在的理由：

| 数据路径 | 判的是谁和谁 | `judgement_scope` |
| --- | --- | --- |
| `novel_ref.json` → `beats[].fidelity` | **漫画** vs **小说**：漫画有没有照画小说 | `manga_vs_novel` |
| `script-audit.json` → `audited_segments[].fidelity` | **旁白** vs **它的来源**：讲稿有没有讲对 | `narration_vs_source` |

两层都叫 `fidelity`，但判断主体不同。混用会犯两个方向相反的错：

- 把"旁白忠于漫画的改编"当成"漫画不忠于小说"→ 去改本来正确的旁白；
- 把"旁白自己编的"当成"漫画改的"→ 放过凭空捏造。

所以两个文件都必须写死自己的 `judgement_scope`，`m1 novel check` 第 4 步验前者、
第 5 步验后者，**值不匹配直接报错，不许猜**。

##### `alteration_origin`：只回答"差异是谁造成的"

| 值 | 含义 | 处理 |
| --- | --- | --- |
| `manga` | 漫画改的，旁白只是忠实复述漫画 | **保留旁白**，把差异与页码记进 `evidence` |
| `narration` | 旁白自己编的或改的 | **必须改写或删除** |
| `mixed` | 漫画改了一部分、旁白又追加编造了一部分 | 必须拆开说明各是哪一部分 |
| `unknown` | 查不清是谁改的 | 保留疑问，**不许硬塞进前两个** |
| `null` | 没有差异（`drawn` / `omitted`） | 留空 |

**六条硬规则**（全部由 `m1 novel lint` 机器校验，不是靠自觉）：

| # | 规则 | 拦什么 |
| --- | --- | --- |
| 1 | `manga` 必须给 `pages_declared` | "这是漫画改的"是关于画面的断言，指不出页码等于没证据 |
| 2 | 无差异必须留空，不许写 `"none"` | 伪值看着像枚举成员，实际无语义，会让枚举校验形同虚设 |
| 3 | `mixed` 必须填 `mixed_note` | 见下：`mixed` 是最容易被当成逃生门的分类 |
| 4 | `narration` 不许 `disposition=keep` | 旁白自己编的内容保留，等于承认这段没有来源 |
| 5 | `unknown` 不许 `status=approved` | 来源没查清不是一种结论，不能据它放行某一段 |
| 6 | 有 `unknown` 时整份不许 `review_status=approved` | 没查清就不许签核通过 |

##### 记录完整性与 Schema 对齐（P0-REVIEW-07）

六条规则之外，还有三类"错误能被藏起来"的情况，现在一并由 `lint` 拒绝：

| 情形 | 为什么危险 | 处理 |
| --- | --- | --- |
| `segment_id` 重复 | 转成 dict 时后一条覆盖前一条：一条自相矛盾的记录在前、一条合法记录在后，就"看起来全对" | **直接报错**，不做 first-wins / last-wins |
| 报告里有讲稿中不存在的段落 | 多余记录不会被任何一处校验看到 | **报错**（多余记录） |
| 讲稿某段没有审计记录 | 未覆盖的段落等于没审 | **报错**（未覆盖该段） |

**Schema 与 Linter 必须执行同一套约束**。`severity` 的 enum 一度只写在 Schema 里、
Linter 没查，`severity="catastrophic"` 能一路通过。现在：

- 顶层必填字段、逐段必填字段、`severity` 枚举、`script_schema` 枚举、
  `text_sha256` / `novel_ref_sha256` 的 64 位十六进制格式、
  `pages_declared` 的 `page_XXXX` 格式，全部由 `lint` 执行；
- `segment_id` 的唯一性与"逐段一一对应"无法用 JSON Schema 表达，
  由 `lint_audit()` 强制，Schema 里用 `$comment` 写明这一点；
- 每个枚举与必填项都有正反测试（`tests/test_novel.py::TestAuditIntegrity`）。

**损坏的 JSON 不等于不存在**：`script-audit.json` / `novel_ref.json` / `script.json`
存在但无法解析时，门禁报"存在但无法解析"，而不是当成缺失继续往下跑。

**第 3 条为什么单独设字段**：`mixed` 的诱惑太大——一句"又像漫画又像原创"就能绕开举证，
把真正无来源的部分藏在"混合"里。所以要求把两部分**分开写**：

```json
{"fidelity": "altered", "alteration_origin": "mixed",
 "pages_declared": ["page_0045"],
 "mixed_note": "漫画 p45 给了摔进店里的动作；旁白自己加了「撞翻一排货架」"}
```

`mixed_note` 里必须能看出**哪部分是漫画给的、哪部分是旁白新增的**。
混在一句话里含糊带过，`lint` 一样会拒——它只检查字段非空，判断"说清了没有"仍然是人的事。
**字段能拦住的是"根本没写"，拦不住"写了但含糊"。**

**第 5、6 条为什么把 `unknown` 单独拎出来**：`unknown` 的语义是"查不清是谁改的"，
它是**待办**，不是**结论**。允许它存在于报告里（总比硬塞进 `manga` 或 `narration` 诚实），
但不允许它跟着整份报告一起被签核通过。

##### `status` 与 `review_status`：处理状态 ≠ 签核状态

这两个字段必须分开，否则会出现"改完了 = 通过了"的错误理解：

| 字段 | 层级 | 合法值 | 回答什么问题 |
| --- | --- | --- | --- |
| `status` | 逐段 | `approved` / `pending_rewrite` / `rewritten` / `removed` | 这一段**处理到哪一步了** |
| `review_status` | 整份 | `pending_human` / `approved` / `rejected` | **有没有人签核** |

典型组合：

```json
{"status": "pending_rewrite", "review_status": "pending_human", "reviewed_by": null}
```

读法是：**已审出问题（并记录了证据）→ 改稿还没做 → 也没人签核**。
不许读成"机器还没生成任何结论"，也不许读成"已经通过"。

- `pending_rewrite` 是 P0-REVIEW-04 正式并入的枚举成员（原规范缺这一态，样张只好自己
  发明 `pending` 并在文件里写声明）。**`pending` 已废弃**，`lint` 会报错并提示改用
  `pending_rewrite`。
- `status=approved` 与 `disposition` 不许矛盾：通过了就不该还挂着 `rewrite`。
- **`rewritten` 绝不等于 `approved`。** 一段内容改写之后仍然可能有新的事实错误。
  合法组合是：

  ```json
  {"status": "rewritten", "review_status": "pending_human", "reviewed_by": null}
  ```

  读作"改完了，等重审"。**不许在改写完成时自动签核**——从 `rewritten` 到 `approved`
  只能由另一只手完成。
- 只有整份 `review_status=approved` 且 `reviewed_by=human:<name>` 才允许出片；
  `pending_human` 时 `reviewed_by` 必须为空——**没签核就不许留签名**。
- `reviewed_by` **不得等于** `prepared_by`。机器出结论、机器签名，
  等于自己给自己发合格证；`lint` 直接拒绝。

##### 逐段字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `segment_id` | 是 | 与 `script.json` 的段 id 一致 |
| `text_sha256` | 是 | 该段文字的哈希，用于定位"到底哪一段被改了" |
| `status` | 是 | 见上表，**不许用 `pending`** |
| `fidelity` | 是 | `drawn / omitted / altered / original`（判的是**旁白 vs 来源**） |
| `alteration_origin` | `altered` 必填，其余留空 | `manga / narration / mixed / unknown` |
| `disposition` | 是 | `keep` 原样保留 / `fix_pages` 只改页映射 / `rewrite` 改写文字 / `remove` 删除 |
| `pages_declared` | `drawn`/`altered` 必填 | 讲稿声称覆盖的页，必须在 `chapter.json` 的 `pages` 里 |
| `novel_para` | 非 `original` 必填 | 小说段区间；空数组等于"没有来源" |
| `evidence` | 是 | **人读证据**：页码 + 小说段号 + 一句可核对的话。不许只写"已核验" |

##### 整份字段

| 字段 | 说明 |
| --- | --- |
| `audit_spec_version` | **审核标准版本**。审核规范升级后，凭它能看出旧报告依据的是哪一版 |
| `judgement_scope` | 固定 `narration_vs_source`，见上 |
| `script_schema` | 被审讲稿用的 schema（`script/v1` 或 `script/v2`）。v1 与 v2 的字段不同，不能混判 |
| `script_sha256` | **整份** `script.json` 的字节哈希。改一个字就失效 |
| `novel_ref_sha256` | 底稿的字节哈希。底稿一变，之前的审计结论也不再可信 |
| `review_status` | 只有 `approved` 才允许正式出片；`pending_human` / `rejected` 都不行 |
| `reviewed_by` | 必须是人（`human:<name>`）。**模型自审不能填这里** |

**审核报告只由审核流程生成**（P0-C 第二条约束）：

- `script-audit.json` 的**唯一写入者是审核流程**（`m1 novel --audit` 之类的专用入口）。
- 普通讲稿编辑、迁移脚本、`m1 run` 一律**不得写**这个文件；
  要改审核状态，只能重跑审核流程并重新签 `reviewed_by`。
- 讲稿被改动后，审核流程**不能"继承"旧结论**——必须重新逐段判。
  否则"改了台词再点一下审核"就等于伪造审计。

##### 校验分两层：`lint` 管格式，`check` 管放行

```
m1 novel lint --work <work>     只校验 Schema：枚举 / 证据 / 两层语义 / 覆盖
                                不要求签核 → 未签核的样张也能被机器校验
m1 novel check --work <work> --novel-dir <dir>
                                五步门禁：先 lint，再验三层哈希与人签
                                任一不过 → 退出码 3
```

分成两层的原因很实际：把"格式合法"和"人已签核"混在一个判定里，
一份**尚未签核**的报告就根本没法被机器校验——它连"我这份格式对不对"都问不出来。
而样张恰恰必须保持未签核状态。所以 `lint` 在前、签名在后，报错顺序也是先格式后哈希
（否则人会以为是讲稿改了）。

**失效规则（P0-06 门禁）**：

```
m1 novel lint 全过？（schema / judgement_scope / 枚举 / 证据 / 覆盖）
当前 script.json 字节哈希  == script_audit.script_sha256 ？
当前 novel_ref.json 字节哈希 == script_audit.novel_ref_sha256 ？
script_schema 与当前讲稿实际 schema 一致？
audited_segments 覆盖全部当前段，且每段 text_sha256 对得上？
review_status == "approved" 且 reviewed_by 以 human: 开头？
        ↓ 全过才允许正式出片
```

任一不等 → 审计过期，必须重新审。**不许"只补一条审计记录"绕过。**

---

## 5. 工作方式：十阶段 + 底稿对齐

### 5.0 总览

```
mobi ─S1─► pages/*.jpg ─S2─► chapter_index.json
                            │
                            ├─S3─► page_XXXX.profile.json（按需，不阻塞竖版）
                            │
                            └─S4─► 分格：按 visual_mode 分岔
                                     ├─ page  模式 ──► 整页引用，跳过分格，无 *.panels.json
                                     └─ panel 模式 ──► *.candidates.json ─人工─► *.panels.json
                                                                                     │
epub ─S1─► chapters/*.xhtml ─S1'─► novel.txt + novel_index.json                       │
                                       │                                             │
                            S5a 底稿对齐 ──► novel_ref.json                          │
                                       │                                             │
                                       └──► S5 讲稿 ──► script.json ◄────────────────┘
                                                          │
                                                          ├─S6─► audio/*.wav + tts_index_v3.json
                                                          ├─S7─► timeline.json
                                                          └─S8─► <章节名>.mp4 / .srt / .ass
                                                                    │
                                                                    └─S9─► run_report.json
```

**读图要点**：S3 和 S4 都不是竖版主链路上的必经环节。

- S3（页面解读）产出的是素材检索单，服务 V2 的配图检索，竖版 `visual_mode=page` 用不到。
- S4（分格）只有 `visual_mode=panel`（横版）才需要。竖版走 `page` 模式，**整页引用、跳过分格**，
  `--skip-panel-gate` 在 `visual_mode=page` 下是合法调用（见 §4.3.3）。
  换句话说：竖版今天能出片，不依赖 S3/S4 任何产物。

| 阶段 | 名称 | 执行者 | 产物 | 现状 |
| --- | --- | --- | --- | --- |
| S0 | 能力探测 | 机器 | `capability_report.md` | 【已实现】 |
| S1 | 素材摄取 | 机器 | `pages/*.jpg` + `pages.json` | 【已实现】 |
| S1' | 小说纯文本化 | 机器 | `text/novel.txt` + `novel_index.json` | 【已实现】`tools/novel_extract.py` |
| S2 | 章节定界 | 机器 + 人 | `chapter_index.json` | **半自动**（程序测墨量 + 人读横幅） |
| S3 | 页面解读 | 视觉模型 + 人 | `page_XXXX.profile.json` | 【待建】（仅 V2 素材检索需要） |
| S4 | 分格与确认 | 机器 + 人 | `*.panels.json` | 【已实现】（仅 `visual_mode=panel` 需要） |
| **S5a** | **底稿对齐** | **人 + 模型** | **`novel_ref.json`** | **半自动**：`m1 novel align` 产骨架，`check` 五步门禁；逐 beat 判定必须人做（§5.6.1） |
| S5 | 讲稿 | 模型 + 人 | `script.json` | 半自动（当前人工） |
| S6 | 配音 | 机器 | `audio/*.wav` + 索引 | 【已实现】 |
| S7 | 时间轴 | 机器 | `timeline.json` | 【已实现】 |
| S8 | 渲染 | 机器 | `<章节名>.mp4` | 【已实现】 |
| S9 | 质检交付 | 机器 + 人 | `run_report.json` | 【已实现】 |

**S2 为什么是半自动而不是【待建】**：程序侧已经跑通——全页灰度导出、墨量计算、
「黑页 + 波点页」配对反推标题页，都在 `m1 chapter` 里实现并有测试覆盖；
缺的是「横幅文字要人读一眼」这一步，而这一步本质上无法自动化（横幅位置跨卷不固定，
见 §5.3）。能力有一半、且缺口是人工环节而非代码，状态就写半自动，
不写【待建】——否则会让人误以为整段没动手。

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

### 5.3 S2 章节定界【半自动：人工确认 + 程序辅助】

漫画 mobi **没有目录页**，章节要靠图像特征找。`m1 chapter` 能做的部分：

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

**几何检测在两卷上都失效了，这是实测结论，不是没调好**：

- 第一卷只有 p43/p44 一对分隔页，能反推出第二章；**第三章（p75）没有分隔页**，
  第一版按"横幅只在页首"扫，整章漏掉。
- 第二卷只有一个全黑页（p162），**没有任何分隔页对**，几何法完全失效。
- 横幅位置毫无规律：第一卷 p45 页首、p75/p105/p137 页脚；第二卷 p3 页首、
  p31 页面中部、p39 页脚、p67 页首、p83 页面中部（p84 又印一次带标题的）、p107 页首、p138 页面中部。

**所以 S2 的正确做法是"程序辅助 + 人读横幅"**：

```bash
# 裁连续若干页的同一条横带，竖着拼成一张图，十页一张
python tools/strip_sheet.py --pages m1/v2/work/pages \
  --from 31 --to 40 --band bottom --ratio 0.15 --count 10 --out strip.jpg
```

页首和页脚各扫一遍，横幅一定落在那条带子里。这是目前唯一经济的解法。
结论记进 `m1/labels/v{n}.json`，`note` 里写清每次修正的原因。

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

### 5.6 S5a 底稿对齐 → S5 讲稿

写稿前必须先有底稿。跳过这一步直接看漫画写，就会写出"哥布林绑票、竹筏漂向湖心、
大青蛙吞掉铁笼"这种画面里根本没有、小说里也根本没有的段落（实测事故，见 §13 第 15 条）。

#### 5.6.1 S5a 底稿对齐【半自动：`--align` 产骨架，`--check` 五步门禁】

**第一步：小说纯文本化**（`tools/novel_extract.py`，已实现）

```bash
python tools/novel_extract.py \
  --epub "この素晴らしい世界に祝福を！/正文/1.epub" \
  --out  .local/source/epub/text
# 1.epub: 2627 段 83599 字 sha256 6eb5912fa36f…
#   chapter00.xhtml      0-148     4536 字  序章
#   chapter01.xhtml    149-711    19142 字  第一章 和这个自称女神转生到异世界！
#   …
```

epub 就是 zip，取出 XHTML 去标签后逐段落行。**不要用第三方库**，
`zipfile` + `re` + `html.unescape` 足够。核心逻辑：

```python
import zipfile, re, html, hashlib

def extract(epub_path):
    z = zipfile.ZipFile(epub_path)
    # 只取正文：chapter00..chapter05。colorpages/Houji/Message/Writer 等一律排除，
    # 否则字数会多出约 3,400（人物介绍、后记、版权、转载信息）。
    # 本卷的文件名排序恰好等于 spine 顺序；换出版社的 epub 要读 OPF 的 <spine><itemref>。
    names = sorted(n for n in z.namelist()
                   if re.fullmatch(r".*/chapter\d+\.xhtml", n))
    chapters, lines = [], []
    for n in names:
        raw = z.read(n).decode("utf-8", "replace")
        b = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        b = re.sub(r"(?i)<br\s*/?>", "\n", b)
        b = re.sub(r"(?i)</p>", "\n", b)
        b = re.sub(r"<[^>]+>", "", b)
        ps = [l.strip() for l in html.unescape(b).splitlines() if l.strip()]
        if not ps:
            continue
        start = len(lines)
        lines.extend(ps)
        chapters.append({"file": n.split("/")[-1], "title": ps[0][:40],
                         "para_from": start, "para_to": len(lines) - 1,
                         "chars": sum(len(p) for p in ps)})
    text = "\n".join(lines)
    return text, {"schema": "novel-index/v1",
                  "chapters": chapters,
                  "total_paras": len(lines),
                  "total_chars": sum(c["chars"] for c in chapters),
                  # 内容哈希：不含文件尾部换行
                  "sha256": hashlib.sha256(text.encode()).hexdigest(),
                  # 落盘字节哈希：含一个尾部换行，novel_ref 的 text_sha256 用它
                  "file_sha256": hashlib.sha256(render(text).encode()).hexdigest()}
```

`render(text)` 定义在 `panelcast/novel.py`（`return text + "\n"`），
**它是 `novel.txt` 的唯一写入口**，`tools/novel_extract.py` 直接 import 它。
写盘时必须 `newline="\n"`，否则 Windows 会把 `\n` 翻成 `\r\n`，
同一份 epub 在不同平台算出不同的 `file_sha256`。详见 §4.3.9 的四条复验。

落盘 `.local/source/epub/text/novel.txt` + `novel_index.json`。
**段号是全局连续的**，跨章引用才不会歧义。

第一卷实测分章（`1.epub`，字数不含换行）：

| 文件 | 标题 | 段区间 | 段数 | 字数 |
| --- | --- | --- | ---: | ---: |
| chapter00 | 序章 | 0–148 | 149 | 4,536 |
| chapter01 | 第一章 和这个自称女神转生到异世界！ | 149–711 | 563 | 19,142 |
| chapter02 | 第二章 以这只右手偷取宝物（内裤）！ | 712–1280 | 569 | 19,403 |
| chapter03 | 第三章 在这座湖中加入鲜榨自称女神汁！ | 1281–2013 | 733 | 22,906 |
| chapter04 | 第四章 解决这场不像话的战斗！ | 2014–2550 | 537 | 15,758 |
| chapter05 | 终章 | 2551–2626 | 76 | 1,854 |
| — | **正文合计** | 0–2626 | **2,627** | **83,599** |

> 89,599 是整个 epub 的字符数（含人物介绍、后记、版权、转载信息，约多 6,000 字）。
> **别拿它当正文规模**，也别用它估"这章该写多长"。

**第二步：用人物事件锚点定位区间**

按关键词统计 + 首次出现段号，先粗定"这个漫画章大概在小说哪一段"。
第一卷实测（`首次出现：章 段`）：

| 锚点 | 序章 | 一章 | 二章 | 三章 | 四章 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 惠惠 | – | **338** | 6 | 29 | 4 |
| 达克妮丝 | – | – | **40** | 29 | 4 |
| 墓地 | – | – | **415** | – | – |
| 净化 | – | – | 493 | 286 | 502 |
| 维兹 | – | – | **511** | – | – |
| 御剑 | – | – | – | **534** | 206 |
| 无头骑士 | – | – | – | **33** | 33 |
| 贝尔迪亚 | – | – | – | – | **60** |
| 圣水 | – | – | – | – | **87** |

**第三步：逐段判 fidelity，写 `novel_ref.json`**（schema 见 §4.3.9）

- 一个 beat = 小说里一件连续发生的事（通常 3–20 段），映射到 0–3 个漫画页
- 顺序对不上就写 `order: "reordered"` 并在 `note` 里写明挪动方向
- 漫画页上没有的 beat，`pages` 留空数组、`fidelity: omitted`——**这不丢人，是信息**
- 反过来，漫画页上有但小说没有的，`para: null`、`fidelity: original`

- **门禁**：每章 `beats` 覆盖全部漫画页；`by_fidelity` 四类计数之和 = `beats_total`；
  `original` 的 beat 必须有 `pages`（否则就是凭空写的）
- **耗时**：一章 8–30 页，约 20–40 分钟（读小说 + 对页）

##### 工具：`m1 novel --align` / `--check`（P0-05，已实现）

```bash
# 生成骨架：所有 beat 一律 unconfirmed + needs_review，para 留空
python -m panelcast m1 novel align \
  --work m1/v1/ch02/work \
  --novel-dir .local/source/epub/text \
  --chapter-uid konosuba-manga-v01-ch02 \
  --epub "この素晴らしい世界に祝福を！/正文/1.epub" \
  --novel-chapter ch01

# 五步门禁
python -m panelcast m1 novel check \
  --work m1/v1/ch02/work --novel-dir .local/source/epub/text
```

**`--align` 的候选为什么只是"弱提示"（实测结论）**

第一版实现用二元组 Jaccard 相似度打分，实测**不可靠**。原因很具体：
旁白是**改写**的，不是原文摘抄。

| | 文本 |
| --- | --- |
| 旁白 | 冒险者公会的**后院**有一口大**浴池**，**热水**是从**地底**引上来的 |
| 小说原文 | 这里的入浴费比日本还贵……我将肩膀以下都浸泡在**热水浴池**里 |

只有「浴池」「热水」两个词真正重合。任何相似度都会把它排到很后面，
而排到前面的往往是「从地底」「高阶」这类**巧合命中的无关段落**——
实测 ch01 范围内，Jaccard 版本的第 1 名是第 446 段（讲蟾蜍的），正确答案在第 324 段。

所以现在退一步，只回答一个站得住的问题：
**"这段旁白里有哪些全书中很罕见的词（df ≤ 3）？它们在候选范围内出现在哪几段？"**
命中词写在候选的 `anchors` 里，人一眼能判断这个候选靠什么猜的、值不值得看。

实测 ch02 第 1 段：`para 324, anchors=[热水, 浴池]` —— 正确，且可解释。
同章第 2、3 段则给出 `anchors=[费也]`、`[的简]` 这类无意义命中，
**这正是它该有的样子**：候选不可靠的时候要看得出来，而不是伪装成结论。

> **纪律**：候选一律进 `para_candidates`，`para` 永远是 `null` 直到人填。
> 把候选写进 `para` 等于伪造"已确认"。

**`--check` 对 v1 讲稿会直接失败**，这是正确的：v1 结构里没有 `source_refs` 字段，
无从判断来源。要过第 3 步必须先迁到 v2（P0-11）。

##### 工具：`m1 novel lint`（P0-REVIEW-04，已实现）

底稿对齐做完、内容审完之后，还有一层**只校验格式**的入口：

```bash
python -m panelcast m1 novel lint --work m1/v1/ch01/work
# novel lint: Schema 合法 -> m1/v1/ch01/work/script-audit.json
#   注意：这只证明格式对，不证明已签核；出片仍需 review_status=approved
```

它校验的是审核口径本身，而不是哈希：`schema` / `judgement_scope` / `status` 枚举 /
`alteration_origin` 枚举 / `disposition` / 证据是否可定位 / 段落覆盖。
**不要求签核**——所以未签核的样张也能被机器校验。字段定义见 §4.3.10。

`lint` 与 `check` 的分工是刻意的：

| 命令 | 管什么 | 未签核的样张 |
| --- | --- | --- |
| `lint` | 格式合法吗 | **能过**（这正是它的用途） |
| `check` | 能不能出片 | **必须不过**（`review_status` 与 `reviewed_by` 两处拦） |

第一章样张就是这个状态的实例：`lint` 全过、`check` 卡在第 5 步，
同时因为讲稿还是 v1 卡在第 3 步、因为 37 个 beat 未人工确认卡在第 4 步。

##### 第一章样张（`P0-01-SAMPLE-CH01`）

已产出并作为**正式示例**保留，**未签核**：

| 产物 | 位置 | 说明 |
| --- | --- | --- |
| 章节对应表 | `m1/audit/chapter-map.md` | 为什么不能靠编号 + 判定四步法 + 30 行页段对照 |
| 底稿 | `m1/v1/ch01/work/novel_ref.json` | 37 beats，页覆盖 38/38，`order: reordered` |
| 审核报告 | `m1/v1/ch01/work/script-audit.json` | 25 段全审，`review_status: pending_human` |
| 审计明细 | `m1/audit/script-audit-ch01.md` | 逐段判据、反例回归、高危案例 |

结论摘要：25 段中 `drawn` 11 / `altered` 14，`disposition` 为
`keep` 12 / `fix_pages` 1 / `rewrite` 12；高危 6 段，其中三处属**改变了事实**——
虚构柜台小姐姓名「露娜」（全书 `grep` 命中 0 次）、把「我还是当冒险者好了」
改成「我要当大贤者」、把被推开的女生说的「好痛」归到和真身上。
2026-11-17 项目负责人复核裁定 `REVIEW_RETURNED`，已按裁定修订
（b18/b19、b25/b26 段号边界、b01 扉页描述、`seg_0005/0016/0018/0023` 判定）；
映射与 seg_0014 来源同步均已复核通过（`MAPPING_REVIEW_PASS / SEGMENT_SOURCE_SYNC_PASS`），
仍未签核。

**其余九章未核**，不得据第一章的结果推断它们的状态。

#### 5.6.2 S5 讲稿

- **输入**：`novel_ref.json`（**主依据**）+ `page_XXXX.profile.json`（画面细节）+ `panels.json`
- **动作**：按 1–3 页一段写旁白，**每段必须回指至少一个来源**（`narration.source_refs`，
  见 §4.3.4）。`fidelity: original` 的 beat 只能写画面能看见的东西
- **产物**：`script.json`
- **门禁**（写稿自检）：

  **① 段字数按页数定，不是一个固定值。** 旧规则"每段 ≤ 130 字"与"45–90 字/页"
  在 3 页段上互相矛盾（130 ÷ 3 = 43.3 < 45），已修正：

  | 段页数 | 段字数下限 | 段字数上限 | 折算 字/页 |
  | ---: | ---: | ---: | --- |
  | 1 页 | 45 | 90 | 45–90 |
  | 2 页 | 90 | 180 | 45–90 |
  | 3 页 | 135 | 180 | 45–60 |

  上限 180 是**字幕碎化**的硬顶（约 12 条字幕），不是内容限制；
  想写更多就拆段，别把 3 页塞成一段。

  **② 密度是章级指标**（§9.2 第 15 条按 `总字数 ÷ 总页数` 算），段级只是推导。
  章级低于 45 字/页就是"内容不充实"，靠补小说细节而不是拖长句子；
  但本章 `by_fidelity.original` 占比高（小说无底稿）时密度天然偏低，**不许硬灌**。

  **③ 其他**
  - 引用页必须在 `chapter_index` 的本章范围内
  - 人名只用介绍页或小说原文里出现过的写法
  - 每段 `source_refs` 非空，且指向的 beat/页里确实有这个段提到的动作/人物
  - 写完必须回看对应页：翻三页抽查一次（§9.4）

- **耗时**：38 页 / 25 段约 1.5 小时（人工，含回看）

> 注：`≤130 字` 从未写进代码，它只是文档里的写稿建议；`m1 run` 不校验段字数。
> 真正会拦人的只有 §9.2 第 15 条的章级密度。

### 5.7 S6 配音

- **输入**：`script.json` + 后端信息
- **动作**：edge-tts 合成，**用 `stream()` 而不是 `save()`**，同时收集 `SentenceBoundary`
- **产物**：`cache/tts/<sha256>.wav`（内容寻址）+ `audio/seg_XXXX.wav`（工作名）+ 索引
- **门禁**：合成失败/0 字节 → 退出码 4；时长 ≤ 0 → 退出码 4
- **耗时**：25 段约 2.5 分钟（网络）

### 5.8 S7 时间轴

- **输入**：`script.json` + 音频真实时长 + 句锚点
- **动作**：累加真实时长得 `start/end`；**段内切页**（`_segment_cuts`）；生成 cue
- **产物**：`timeline.json`
- **门禁**：总时长与音频累加误差 ≥ 0.05s → 退出码 4
- **耗时**：<1s

**页窗口算法（以代码为准，`panelcast/timeline.py`）**：

1. 段起止由真实 WAV 时长累加，不做估算；
2. 一段覆盖 k 页 → 在这一段**内部**求 k−1 个切点，理想位置为段内均分；
3. 每个理想切点吸附到最近的**真实句边界**（配音真的说到下一页了），吸附半径 `SNAP_WINDOW=2.0s`；
4. 切点硬约束是**绝不越出本段**，且相邻切点间隔 ≥ `MIN_DWELL`；
5. 切完后体检每页停留是否落在 `[MIN_DWELL, MAX_DWELL] = [3.5, 26.0]`。
   超限只报告（§9.2 第 12 条），**不靠夹逼掩盖**；但若因末页吸收余量导致单页超上限，
   `_cap_dwell` 会按容量摊回其他页。

> 旧版本文写的是"段内页时长均分"，那是全局均衡时代的做法（会让画面比配音慢 30 秒），
> 已被 `_segment_cuts` 取代。这句话于 2026-11-16 修正（P0-09）。
>
> 也就是说：**一页停多久 = 讲这一页的文字有多长**，不是"总时长 ÷ 总页数"。

### 5.9 S8 渲染

- **输入**：`timeline.json` + 页图 + 音频
- **动作**：逐页出目标画布 PNG（带缓存）→ concat → 一条 ffmpeg 烧字幕出片
- **产物**：`<章节名>.mp4/.srt/.ass`
- **门禁**：见 §9.2，任一不过 → 退出码 4
- **耗时**：38 页约 2 分钟

### 5.10 S9 质检交付

- **输入**：成片 + 全部中间产物
- **动作**：跑 §9.2 的 15 条验收，写 `run_report.json`；抽 6 帧人工看（§9.3）；
  抽 3 段对底稿（§9.4）
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
| `confidence` | number | ✅ | 0–1，**模型的自信程度，不是事实正确性** |
| `reviewed` | bool | ✅ | 兼容旧字段；等价于 `review_status == "human_verified"` |
| `review_status` | enum | ✅ | `unreviewed` / `machine_checked` / `human_verified` / `needs_review`（P0 新增） |
| `reviewed_by` | string | ⬜ | `human:<name>` / `vision:<model>`，**谁审的必须能区分** |
| `review_method` | enum | ⬜ | `visual_comparison`（对着原图逐格核）/ `text_only` / `sampling` |
| `evidence` | object | ⬜ | `{"page": "page_0021", "panels": ["p2","p3"], "bbox_px": [...]}` 回指原始证据 |

**为什么要把 `reviewed` 拆开**（审核意见 §6）：原来的 `reviewed: true` 把"人工审核过"
和"另一个模型复核过"混成一个布尔值。模型自评高置信度**不等于事实正确**。
新字段要求 `reviewed_by` 明确写是谁，`review_method` 明确写怎么核的。

`evidence` 是为了让检索结果能回到原始证据：以后检索到"某页有个人物在做某动作"，
必须能定位到具体页和具体格，而不是只有一句模型总结。

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

#### 6.5.1 按需生成，不要一次性填满全库

现状是 291 份**空壳**（v1 145 + v2 146）：`story.summary` 全是「（待视觉补全）」、
`characters` 空、`reviewed` 全 `null`。这批文件**不是资料库**，只是 schema 骨架。

明确规则：

- **竖版整页出片不依赖全库 profile**。现在十章就是这么出的（§1.4）。
- **横版切格工具第一阶段也不需要全库语义分析**（P1-02）。先保证切图边界、
  切图身份、阅读顺序可靠，语义按需补。
- 生成顺序：**当前要做的章节 → 当前检索需求**，不做"为凑目录完整"的批量生成。
- 每页四类字段要分清，**不得因 schema 字段齐全就认定语义真实**：

  | 类别 | 字段 | 谁产生 |
  | --- | --- | --- |
  | 几何 | `layout.panel_count` / `reading_direction` / `width` / `height` | 机器测量，可信 |
  | OCR | `text.bubbles[].text` | 视觉模型，需 `verbatim_complete` 自评 |
  | 叙事 | `story.*` / `visual.*` | 视觉模型，**必须人工核** |
  | 审阅 | `provenance.review_status` / `reviewed_by` | 人 |

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
| S1' | `novel.txt` 非空、`novel_index.json` 段号连续、`file_sha256` 与**磁盘字节**一致 | 3 |
| S2 | 章节标题页人工确认（`verified_by` 非空） | 3 |
| S3 | **仅当本章需要素材检索单时校验**：`§6.6` 全过 + `reviewed=true`。竖版 `visual_mode=page` 不读 profile，**S3 缺失不阻塞竖版出片** | 3 |
| S4 | **按模式区分**：竖版 `page` 可跳过（`--skip-panel-gate` 合法）；横版 `panel` 每页必须有 `panels.json` 且 `source=manual` | 3 |
| **S5a** | 五步链全过（见下） | 3 |
| S6 | 音频存在且 > 44 字节、时长 > 0 | 4 |
| S7 | 总时长与音频累加差 < 0.05s | 4 |
| S8 | §9.2 全部硬指标 | 4 |

**S3 的适用范围（重要）**：S3 产出 `page_XXXX.profile.json`，是给 V2「按文字找画面」的素材检索单用的。
竖版 `visual_mode=page` 整页引用、不做画面检索，因此 **S3 与竖版出片无依赖关系**。
现存 291 个 profile 占位文件**不构成竖版的阻塞项**——不要因为「S3 还没审完」就停掉竖版交付。
只有当某章确实要用 profile 做检索时，才对该章启用 S3 门禁。

**S5a 的五步门禁链**（P0-05/P0-06，任一不过就 `BLOCKED`，禁止进入 S6）：

```
script.json
   │
   ├─1. 章节身份一致 + 权威表 + novel_ref.json 存在？
   │     · chapter_uid 在 chapter.json / novel_ref / script / script-audit 中一致
   │     · 目录名的全书号 == global_chapter_number
   │     · id / number 与 chapter_uid 自洽
   │     · 权威表 chapter_index.json 存在、可解析、非空、自身合格，
   │       且 chapter_uid 在表中唯一命中     否 → 禁止出片（身份错了，后面全无意义）
   ├─2. novel_ref.source.text_sha256
   │     == novel_index.json 的 file_sha256？   否 → 底稿失效，回 S5a 重对齐
   ├─3. 每段 source_refs 非空且 beat 存在？      否 → 禁止出片
   ├─4. beat 的页映射合法
   │     （judgement_scope=manga_vs_novel、页在本章、original 必带 pages、
   │       非 original 必带 para、beat 已人工 confirmed）？
   │                                            否 → 禁止出片
   └─5. script-audit.json 有效？
          · 先跑 Schema 校验（= `m1 novel lint`）
            schema / judgement_scope=narration_vs_source / 枚举 / 证据 / 覆盖
          · script_sha256 == 当前 script.json 的哈希
          · novel_ref_sha256 == 当前 novel_ref.json 的哈希
          · 每段 text_sha256 对得上
          · review_status == approved 且 reviewed_by = human:<name>
                                            否 → 禁止正式出片（只允许 --draft 预览）
                                    ↓ 全过
                                 允许 TTS
```

第 2 步用的哈希是 `text_sha256`，**不是** `novel_ref.source.sha256`。
前者是 `novel.txt` 落盘字节的哈希（= `novel_index.json` 的 `file_sha256`，含尾部换行）；
后者是 EPUB 原文件哈希，两者永远不相等。混用会导致「底稿永远判定为失效」。详见 §4.3.9。

第 5 步是 P0-C 加的。前四步能证明「来源可追」，但**证明不了「有人看过这段文字」**——
脚本可以完全合规地引用正确的 beat，同时把剧情讲错。`script-audit.json` 就是那把
「人确实读过」的锁，它的失效规则见 §4.3.10：脚本、底稿、任一段文字任一变化，审计即过期。

第 5 步内部**先格式后哈希**：`lint` 不过就只报格式错，不再往下比哈希。
顺序反了会误导——人会以为"哈希不符"是讲稿被改了，其实只是枚举写错了。

**第 1 步是 fail-closed 的**（P0-REVIEW-07）：找不到权威表、权威表损坏或为空、
索引自身不合格（uid / id / number 重复、卷内编号不连续）、身份文件存在但 JSON 损坏，
**全部报错并退出码 3**。五份文件自己一致不作数——它们可能一起抄错了一个不存在的章号。
唯一跳过权威表的方式是在代码里显式传 `authority=False`，CLI 不提供这个开关。

单独跑格式校验用 `m1 novel lint --work <work>`（不要求签核），
它和 `check` 的分工见 §5.6.1。

这五步只能证明**结构完整、来源可追、有人审过**，**不能证明剧情理解正确** —— 后者仍然只能靠
§9.4 的人工抽检。不要因为 `--check` 通过就宣布内容合格。

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

> **这 15 条的名字是"技术交付验收"**：证明视频生成成功、能播、音轨对、参数对。
> 它**不证明**画面内容正确 —— 章节标签是读 `.ass` 而不是看渲染结果，
> 停留时长是算计划值而不是测实际帧。真实帧的视觉验收见 §9.5（待建）。
> 内容是否讲对，见 §9.4（人工）。

### 9.3 抽帧复验（人工 6 帧）

取 `t = 0.5s`、`1/6`、`2/6`、`3/6`、`4/6`、`5/6` 六个时刻，逐帧确认：
画面内容与字幕语义一致、标签在、字幕不裁切。**这一条不能自动化，必须人看。**

### 9.4 底稿抽检（人工，每章 3 段）

§9.2 的 15 条全是"技术指标合格"，一条都不能证明**旁白说的是不是这页的事**。
这一条专门抓这个，只抽查、不自动化：

1. 从本章随机取 3 段（首、中、末各一），把该段覆盖的页图打开
2. 逐句问：**这句话描述的动作/人物，在这一页上能看见吗？**
3. 三种回答都要记：
   - 看得见 → 过
   - 看不见但小说写了（`fidelity: omitted`）→ 过，但确认它没写在错的页上
   - 看不见、小说也没有 → **不过**，回 S5 重写

> 自动化的那半边留给 `m1 novel --check`（§14.1）：只能校验"每段有 beat 且 beat 存在"，
> 校验不了"beat 和这一页对不对得上"。那一半永远是人眼。

### 9.5 视觉验收（真实帧，【待建】）

**先把话说清楚**：§9.2 那 15 条更准确的名字是**技术交付验收** —— 它证明"视频生成成功、
能播、有音轨、时长对、字幕参数符合预设"。它**不证明最终画面是对的**。

| 项 | 现有方法 | 为什么不够 |
| --- | --- | --- |
| 章节标签 | 读 `.ass` 文件 | 文件里有 ≠ 渲染后看得见（可能被裁、被盖、字号过小） |
| 单页停留 | 算计划时长 | 计划 ≠ 实际帧时间（帧缓存复用、编码丢帧都会偏） |
| 字幕纯白 | 字幕带灰度最高频 | 画面本身有白色时会被误判 |
| 描边存在 | 数暗像素 | 画面里的黑线也算暗像素，不能证明描边对 |
| 画面内容对应 | 抽 6 帧人工看 | 249 次切页抽 6 帧，漏检率极高 |

**待建的视觉验收（`m1 verify --visual`）**：

1. **每个切页点前后各抽一帧**（`cut-0.1s` 与 `cut+0.1s`），确认画面确实换了、没闪黑；
2. **每个字幕段抽一个随机显示时刻**，OCR 或模板比对，确认字幕文本与 `.ass` 一致；
3. **最长停留页强制抽 2 帧**（首尾），确认没冻结在同一画面却是别的页；
4. **首尾帧检查**：非黑屏、非纯色、有内容；
5. **冻结帧检测**：相邻帧直方图差为 0 且跨越切页点 → 报警（说明切页没生效）；
6. **画面越界检测**：白边宽度 > 阈值 → 说明页图被裁掉了内容。

**待建的视觉验收（`m1 verify --visual`）分三层**，不要做成"抽六帧看看"：

| 层次 | 查什么 | 对应具体检查 | 判据性质 |
| --- | --- | --- | --- |
| **L1 渲染完整性** | 画面到底有没有东西 | ① 首尾帧非黑屏/非纯色 ② 空白页检测（灰度均值 > 250）③ 黑屏检测（< 5）④ 冻结帧（相邻帧直方图差为 0 且跨切页点）⑤ 缺失图片（漫画区边缘密度为 0） | 硬失败，直接 FAIL |
| **L2 视觉布局** | 画面摆得对不对 | ⑥ 字幕带遮挡（字幕带以上区域被图片侵入）⑦ 画面越界（白边宽度 > 阈值 = 页图被裁）⑧ 比例异常（漫画区宽高比与源页不符）⑨ 章节标签可见（右上角区域有文字像素） | 硬失败，直接 FAIL |
| **L3 时间同步** | 画面换得对不对 | ⑩ **每个切页点前后各抽一帧**（`cut-0.1s` / `cut+0.1s`）确认真的换了且没闪黑 ⑪ 最长停留页首尾各抽一帧 ⑫ 每个字幕段抽一个显示时刻，OCR/模板比对与 `.ass` 一致 | 硬失败 + 疑似清单 |

**L3 的第 ⑩ 条是这轮新增的重点**：只随机抽帧是不够的——切换瞬间的错误
（闪黑一帧、切换滞后、两页叠在一起）恰好落在随机抽帧的空隙里。
249 次切页就是 249 个必查点，**不能抽样**。

**机器只能标记疑似，不能判内容正确**（硬边界）：

- `--visual` 的 PASS 只表示"这帧渲染正常"，**不表示"这页讲对了"**。
- 剧情正确性永远归 §9.4 人工抽检 + `script-audit.json` 审核报告。
- 所以 `--visual` 通过**不得**作为 `content_reviewed` 或 `approved` 的置位依据。
- 反过来，`--visual` FAIL 可以直接阻断出片——画面坏了没有争议。

这一套是**机器可做的**；"旁白说的是不是这页的事"仍然只能人看（§9.4）。
两者不能互相替代。

### 9.6 P0-RELEASE-GATE 正式内容生产资格

> **这不是第十二个开发任务**，是 P0 全部做完时的**总验收条件**。
> 只有全过，才允许进入正常批量制作（第十一章之后的量产）。

九条必须**同时**满足，缺一条就是"不具备量产资格"：

| # | 条件 | 怎么验 |
| --- | --- | --- |
| 1 | 原有十章完成 **100%** 内容审计 | 十章各有 `script-audit.json` 且 `review_status=approved`，逐段覆盖 |
| 2 | 新版 Schema 与旧版迁移通过 | 十章 `script.json` 为 v2 且过 schema 校验；`script.v1.json.bak` 可回滚 |
| 3 | 小说来源哈希门禁通过 | 十章 `m1 novel --check` 全过，含第 2 步 `text_sha256` |
| 4 | 审核报告与当前讲稿版本一致 | 三层哈希（`script_sha256` / `novel_ref_sha256` / 逐段）全对得上 |
| 5 | 正式出片门禁**无法绕过**审核 | 有测试证明：缺报告 / 改台词不重审 → 退出码 3 |
| 6 | 竖版完整页面路径正常 | 十章 `visual_mode=page` 全链路能出片，无隐性硬门禁 |
| 7 | 横版功能**尚未被错误地设为竖版依赖** | 竖版出片不读 `*.panels.json`、不读 `page_*.profile.json` |
| 8 | 视觉验收能发现预设故障样例 | 人为注入 5 类故障（空白页/黑屏/字幕遮挡/越界/切页未生效），`--visual` 全部报出 |
| 9 | 全部测试通过，失败与跳过项**如实记录** | 报告里写 `Ran N tests / OK (skipped=M)`，跳过原因逐条列出 |

**第 8 条是最容易被做成"走过场"的一条**：不能只跑一遍真片说"没报错"，
必须**先注入已知故障、确认能抓到**，否则无法证明这个验收有效。

第 7 条防的是一种慢性病：横版功能做完后，有人为了"复用"把
`panels.json` 设成竖版的前置依赖，竖版就悄悄被绑架了。



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

**现状**（代码里的实现）：

| 缓存 | 键 | 位置 |
| --- | --- | --- |
| TTS 音频 | `sha256(text + voice + rate + backend)` | `cache/tts/<key>.wav` |
| TTS 索引 | 同上 | `cache/tts_index_v3.json` |
| 目标画布帧 | `WxH-fit-bg-b<band>-m<margin>-t<top>` | `cache/frames/<key>/` |
| 音频拼接 | 段音频集合 | `cache/audio_concat.wav` |

**问题**：画布帧键里**没有源图 hash**。上游素材"文件名没变、内容变了"（重新解压、
换了压缩质量、修了一页）时，缓存会命中旧帧，静默出错片。

**目标键（P1 增强，【待建】）**：

| 缓存 | 目标键应包含 |
| --- | --- |
| 画布帧 | 源图 `sha256` + 分格裁切坐标（竖版为满页）+ `WxH` + `fit` + `bg` + 边距参数 + **裁边算法版本** + **渲染程序版本** |
| TTS | `sha256(text)` + voice + rate + volume + pitch + **edge-tts 版本** + **句边界解析版本** + backend |
| 音频拼接 | 段音频的 `sha256` 有序集合（不是段 id 集合） |

### 11.1.1 "可复现"的定义

旧文档说"同一输入重复跑逐帧一致"，这句话不严谨，因为在线 TTS 是**不可控变量**。

明确定义：

> 在**相同的不可变输入素材 + 相同的音频文件 + 相同的工具链版本 + 相同的渲染参数**下，
> 必须产生**相同的解码帧**。

也就是说：TTS 的实时返回不进这条保证（所以 TTS 产物要落盘并计入 hash）；
一旦 `audio/*.wav` 定稿，从 S7 到 S8 的重跑必须逐帧一致。这靠 `ffmpeg` 的确定性参数
（固定 `crf`、固定 `fps`、不用 `-tune zerolatency` 之类带时间戳的选项）保证。

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
13. **章标题是两套命名，不能用标题对齐**。小说第三章「在这座湖中加入鲜榨自称女神汁！」
    和漫画第六章「为这片湖献上自称女神的圣水！」是同一段剧情，两个标题没有一个共同关键词。
    对齐只能靠人物/事件锚点（§5.6.1 第二步）。
14. **漫画会重排小说**。阿克娅卖圣水在小说第四章第 87 段（贝尔迪亚登场之后、决战之前），
    漫画挪到第一卷第五章（无头骑士退走之后）当卷末日常。按"第 N 章 ↔ 第 M 章"硬套必错，
    必须写 `order: "reordered"`。
15. **只看画面写稿会编出不存在的情节**。实测事故：漫画是"和真把阿克娅装进公会借的铁笼，
    泡在湖边净化，鳄鱼啃了七小时笼子"，被写成"哥布林从芦苇里窜出来绑票、竹筏漂向湖心、
    大青蛙把笼子吞了"——三个事件画面里没有、小说里也没有。**旁白只能来自画面 OCR 或小说原文**。
16. **有的漫画章小说里根本没有**。第七章「梦幻竹笋」8 页，18 卷小说正文里搜「竹笋」
    只命中 1 次（vol.13），第一卷 0 次。这类章只能"只写画面"，密度天然低，
    **不许为了凑 45 字/页硬编**——第 15 条验收在 `original` 占比高的章要放宽解释。
17. **搜关键词前先试两三种写法**。中文版是简体，搜「神聖解咒」0 命中、搜「神圣」才有；
    角色名也有「贝尔迪亚 / 貝爾迪亞」两种。一次搜不到不等于小说里没有。
18. **小说字数别拿全 epub 算**。`1.epub` 整个 89,599 字符，正文只有 **83,599 字**
    （6 个 `chapter*.xhtml`，2,627 段；多出的约 6,000 字是人物介绍、后记、版权、转载信息）。
    抽取时必须按文件名白名单过滤，否则字数虚高、`sha256` 也会跟着变。

---

## 14. 后续版本

> **优先级以 `docs/ROADMAP.md` 为准**，本节只描述"技术上要做什么"，
> 不再承担"先做什么"的职责。ROADMAP 的 P0–P5 与本文的 §14.1/§15 是同一套东西的两种视图。

### 14.1 V1.1 待补（按优先级）

1. **`m1 novel`：S5a 一条命令**。抽取半边已经有了（`tools/novel_extract.py`）；
   缺的是 `novel --align --work …`（按锚点给候选段区间、生成 `novel_ref.json` 骨架）
   与 `novel --check`（跑 §9.1 的**五步**门禁链，含 `script-audit.json` 审核报告校验）。
   **这是"内容不充实/编错"的根因，优先级最高**
2. **十章底稿回填 + 100% 内容审计**（ROADMAP P0-01…P0-04）：
   现有十章全部产出于 S5a 之前，技术上合格但**底稿不可追溯**。
   这不是"补十份 JSON"，要逐段核来源、改错稿、重出片。**抽查不够，必须全量。**
3. `m1 chapter`：S2 章节定界**收敛人工工作量**（程序侧墨量测量 + 黑页/波点页配对已实现，
   缺的是把"人读横幅"这一步做得更省力，`tools/strip_sheet.py` 是经济解法）。
   状态是**半自动**，不要写成【待建】。
4. **章节身份统一**（P0-08）：`chapter_uid` + 三种编号分开，见 §4.3.1。
   已落地 `novel_ref` / `script`，**还缺交付清单**。
5. `m1 profile`：S3 页面解读**自动生成**（字段规范与自检已就绪；缺的是"读图填字段"这一步）。
   **注意 S3 不阻塞竖版**：竖版整页引用不读 profile，见 §9.1。
   **按需生成**，不批量填满 291 份（§6.5.1）
6. **`m1 verify --visual`**：真实帧视觉验收（§9.5）
7. **缓存键补源图 hash 与工具链版本**（§11.1）
8. 长段拆页：让单页停留稳定落在 8–14 秒（现在一页停多久 = 这段文字多长，上限 26s 只抓病态）

其中第 5 条的**校验半边已经落地**：`panelcast/profile.py` + `docs/schemas/page-profile.schema.json`
能对一份介绍页跑完 §6.6 八条门禁（`python -m panelcast.profile … --ship`，37 个测试覆盖）。
剩下的是生成半边——按 §6.5 的规则逐页读图填字段，这一步要接视觉模型。

**本节条目与 ROADMAP 任务号的对应**（两边是同一件事的两种视图）：

| 本文条目 | ROADMAP | 状态 |
| --- | --- | --- |
| 1 `m1 novel --align/--check` | P0-05 | 未开工 |
| 2 十章底稿回填 + 内容审计 | P0-01…P0-04 | 未开工 |
| 3 S2 收敛人工工作量 | P0-07 | 半自动，文档已统一 |
| 4 章节身份统一 | P0-08 | `novel_ref`/`script` 已落地，交付清单待补 |
| 5 S3 生成半边 | 未排期（不阻塞竖版） | 校验已落地，生成待接视觉模型 |
| 6 `m1 verify --visual` | **P0-10** | CLI 有开关，判据未实现 |
| 7 缓存键补 hash | P2 之后 | 未开工 |
| 8 长段拆页 | 未排期 | 未开工 |
| — | **P0-11** script v1→v2 迁移 | 规范已定，代码未写 |

已完成、不必再列：`m1 verify`（15 条）、编辑器"介绍页校对"面板、切页同步（§9.2 第 14 条）、
`tools/contact_sheet.py` / `tools/strip_sheet.py` / `tools/novel_extract.py`。

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

> 注意：替代素材复用属于**竖版 page 模式**的扩展，与 §15 的横版 panel 模式是两条线。

---

## 15. 横版模式（V2）规划【待建】

> 本章是**规划**，不是实现。按 `docs/ROADMAP.md`，横版在 P1–P2，
> **必须在 P0 内容闭环完成之后**才开始。此处只冻结边界与数据契约，不写代码。

### 15.1 与竖版的边界

| | 竖版 page | 横版 panel |
| --- | --- | --- |
| 视觉单位 | 完整漫画页 | 独立漫画切图（可重叠） |
| 画布 | 1080×1920 | 1920×1080（候选，待样片冻结） |
| 切格 | 不要求 | 必须人工确认 |
| 时间轴 | `timeline.json`（页窗口） | `visual_timeline.json`（格级事件） |
| 验收 | §9.2 15 条 + §9.5 | H9 独立清单，**不得用竖版通过推断横版通过** |

**两条禁止**：不得为横版强迫竖版改格级数据；不得把竖版页面时间轴逻辑直接套到横版。

### 15.2 横版阶段（H1–H9）

| 阶段 | 名称 | 产物 | 门禁 |
| --- | --- | --- | --- |
| H1 | 页面准备 | 页面清单 + 原图 hash | 原图完整、页序确认 |
| H2 | 人工切格 | `panel-cuts.json` + 独立切图 | 坐标合法、可重建、**重叠保留** |
| H3 | 阅读顺序推断 | `auto_order` + 置信度 | 低置信度标 `needs_review` |
| H4 | 切图审核 | `confirmed_order` | 本章所有出片切图顺序已确认 |
| H5 | 内容与切图映射 | 段落 → panel ids | `source_refs` 与 `visual_refs` 分离 |
| H6 | 格级视觉时间轴 | `visual_timeline.json` | 画面时间不越出对应讲解段 |
| H7 | 横版预览 | 可交互预览 | 无裁切、无字幕遮挡、无切换异常 |
| H8 | 横版渲染 | MP4 / SRT / ASS / 报告 | 视频流与音频流时长一致 |
| H9 | 横版验收 | `horizontal_run_report.json` | 技术检查 + 视觉抽检均通过 |

### 15.3 切格数据契约 `panel-cuts/v1`

**核心规则：每次切图都从原始页面独立裁切，允许重叠。**
`panel_002` 的框可以覆盖 `panel_001` 的一部分，重叠像素在两张切图里**都保留**，
不得因为 `panel_001` 已裁过就自动扣除。空白区域可以不属于任何切图。

```json
{
  "schema": "panel-cuts/v1",
  "source_page": "page_0005",
  "source_sha256": "…",
  "image_width": 672,
  "image_height": 1009,
  "reading_direction": "rtl",
  "cuts": [
    {
      "panel_id": "page_0005_panel_001",
      "bbox_px": [320, 120, 650, 430],
      "bbox_norm": [0.476, 0.119, 0.967, 0.426],
      "output": "panels/page_0005_panel_001.png",
      "auto_order": 2,
      "confirmed_order": 1,
      "order_confidence": 0.91,
      "order_status": "human_confirmed",
      "locked": true,
      "overlaps": ["page_0005_panel_002"]
    }
  ]
}
```

| 字段 | 说明 |
| --- | --- |
| `bbox_px` | 原始图像素坐标 `[x1,y1,x2,y2]` |
| `bbox_norm` | 归一化坐标，便于跨分辨率迁移 |
| `auto_order` / `confirmed_order` | **机器建议与人工决定必须分开存** |
| `order_status` | `auto` / `needs_review` / `human_confirmed` |
| `locked` | 人工锁定后机器不得重排 |
| `overlaps` | 几何计算的冗余字段，**不是唯一事实来源** |
| `source_sha256` | 与原图不符 → 旧裁切全部失效 |

`panel_id` 必须稳定，不因单纯调整顺序而全部重建。

### 15.4 切格工具要求（P1）

本地网页工具，不是"把整页切成互不重叠网格"的切片器：

- 逐页打开，缩放 / 平移 / 适应窗口 / 100% 像素
- 画框、拖四边四角、从原图任意位置再加框
- 删除、复制、撤销、重做、微调坐标、重新裁切、预览实际输出
- 侧栏显示本页所有切图缩略图 + ID + 建议顺序 + 确认状态
- 一键自动排序，给置信度与理由；人工可拖动、锁定、局部重排、恢复机器建议
- RTL / LTR / 人工自定义顺序
- 自动保存，刷新或重启服务后可恢复
- 生成联系表供人工确认有没有漏切/重切

**自动排序不能只按 `y` 再按 `x`**。日式漫画默认 RTL，但必须允许项目级/页面级覆盖；
跨行、斜向、重叠、无边框布局要交给视觉模型辅助判断，结果低置信度就标 `needs_review`。

### 15.5 横版视觉时间轴

一段旁白可以：对应一个切图 / 依次对应多个切图 / 同一图跨段重复 / 同时展示多图 /
对同一切图局部放大（**不得破坏原图比例与证据**）。

音频时间轴与视觉事件轴**分开存**：

```json
{
  "schema": "visual-timeline/v1",
  "mode": "panel",
  "segments": [
    {"segment_id": "seg_0001", "start": 0.0, "end": 12.4,
     "events": [
       {"asset_ref": "page_0005_panel_001", "start": 0.0, "end": 5.1,
        "layout": "center", "transition": "cut", "scale": 1.0},
       {"asset_ref": "page_0005_panel_002", "start": 5.1, "end": 12.4,
        "layout": "center", "transition": "fade", "scale": 1.0}
     ]}
  ]
}
```

- 音频时间由真实 WAV 派生，视觉切换点可参考句锚点自动建议、人工微调
- 改画面排布**不应**重新生成音频；改讲稿导致时长变化**必须**重算受影响的视觉时间轴
- 布局要允许单格居中、多格组合、留白、字幕安全区，**不把切图拉伸填满画布**

### 15.6 横版验收（H9）

技术项：分辨率、帧率、音轨、时长、字幕、黑帧、冻结帧、切换点、画面越界。

视觉抽检（人工）：
- 重叠区域内容在每张切图里是否完整
- 阅读顺序是否符合原作
- 切图与讲解是否对应（`visual_refs.role` 是否诚实）
- 字幕是否遮挡关键内容

**建立人工标注测试集**：常规 / 无边框 / 跨格 / 重叠 / 非规则布局。
先测真实表现，再根据基线定准确率目标 —— **不得预先虚构自动识别准确率**。

---

## 附录 A 命令速查

```bash
# S0/S1 摄取（一次一对输入）
python -m panelcast ingest "この素晴らしい世界に祝福を！/漫画/1卷.mobi" -o .local/src_v1

# S1' 小说纯文本化（§5.6.1 第一步）
python tools/novel_extract.py \
  --epub "この素晴らしい世界に祝福を！/正文/1.epub" \
  --out  .local/source/epub/text

# S5a 底稿对齐（待建）
# python -m panelcast m1 novel --align --work m1/v1/ch02/work
# python -m panelcast m1 novel --check --work m1/v1/ch02/work

# S2 切章：把整卷 work 按章节切出一个章级 work
python -m panelcast m1 slice --work m1/v1/work --chapter 第二章 --out m1/v1/ch02/work

# S4 分格候选 + 人工确认
python -m panelcast m1 panels --work m1/v1/ch02/work
python -m panelcast m1 edit   --work m1/v1/ch02/work --port 8642

# S6–S8 一键出片（竖版 page 模式：整页展示，跳过分格门禁是合法默认）
python -m panelcast m1 run \
  --work m1/v1/ch02/work --out m1/v1/ch02/out \
  --voice zh-CN-YunxiNeural --rate "+20%" \
  --size 1080x1920 --fit blurpad --bg white --subs burn \
  --skip-panel-gate \
  --chapter "第二章 替华美的高阶职业带来愉悦！" \
  --name 第二章

# S9 验收（15 条，出 run_report.json）
python -m panelcast m1 verify --work m1/v1/ch02/work --out m1/v1/ch02/out --name 第二章

# 辅助：拼联系表 / 裁横带找章节横幅（--out 是前缀，strip 会按批加页码后缀）
python tools/contact_sheet.py --pages m1/v1/work/pages --from 5 --to 13 --out contact.jpg --cols 3
python tools/strip_sheet.py  --pages m1/v2/work/pages --from 31 --to 40 \
  --band bottom --ratio 0.15 --count 10 --out strip.jpg

# 测试
python -m unittest discover -s tests -q

# 介绍页校验（§6.6 八条门禁）
python -m panelcast.profile m1/v1/ch02/work/profiles/*.json --ship

# 质检：视频轨 vs 音频
ffprobe -v error -show_entries stream=codec_type,duration,nb_frames \
  -of default=nw=1 "m1/v1/ch02/out/第二章.mp4"
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
| 小说正文 83,599 字 / 2,627 段 | `1.epub` 只取 `chapter*.xhtml`，去标签后逐段统计（§5.6.1） |
| 序章 149 段 / 一章 563 / 二章 569 / 三章 733 / 四章 537 / 终章 76 | 同上，段号 0–2626 全局连续 |
| 人物锚点首次出现段号（惠惠 1-338、达克妮丝 2-40、维兹 2-511…） | 同上，逐段 `in` 判断 |
| 「竹笋」在 18 卷正文仅 vol.13 命中 1 次 | 全部 epub 去标签后 `count()` |
| 测试 250 个 | `python -m unittest discover -s tests` |
