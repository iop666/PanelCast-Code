# PanelCast 复核索引

> 本仓库是 PanelCast 的唯一公开仓库：**代码、文档、测试与审计证据都在这里**。
> 原文档镜像 `ChatGPT-Read` 与代码审查镜像 `PanelCast-Code-Review` 已合并到本仓库。
> 逐文件 SHA-256、测试输出与未纳入文件说明见 [`REVIEW-MANIFEST.md`](../REVIEW-MANIFEST.md)。

竖版漫画解说视频流水线。当前阶段：**P0 内容可信度与规范闭环**。

## 找不到第一章样张？看这里

样张**不在任何按日期命名的目录里**（那些快照已删除，历史由 git 记录）。
它在以下五个位置：

| 想复核什么 | 直链 |
| --- | --- |
| 执行报告（A–L 十二节，先看这个） | [`m1/audit/P0-01-SAMPLE-CH01-report.md`](../m1/audit/P0-01-SAMPLE-CH01-report.md) |
| 25 段逐段审计（人读版，801 行） | [`m1/audit/script-audit-ch01.md`](../m1/audit/script-audit-ch01.md) |
| 章节对应表（30 条页段锚点） | [`m1/audit/chapter-map.md`](../m1/audit/chapter-map.md) |
| 底稿（34 beats，机器可读） | [`m1/v1/ch01/novel_ref.json`](../m1/v1/ch01/work/novel_ref.json) |
| 审核报告（25 段，三层哈希绑定） | [`m1/v1/ch01/script-audit.json`](../m1/v1/ch01/work/script-audit.json) |

**如果看到的是"novel_ref 待建 / 四步门禁 / 没有 script-audit"，那是旧版本文档。**
当前主规范是 2,390 行、五步门禁、`script-audit/v2`，且 §4.3.10 已不再是【待建】。

## 文档分工

| 文件 | 是什么 | 什么时候看 |
| --- | --- | --- |
| [`WORKFLOW-v1-vertical-manga-narration.md`](WORKFLOW-v1-vertical-manga-narration.md) | **主规范**，约 2,390 行。阶段定义、JSON schema、门禁、坑 | 改任何东西之前 |
| [`ROADMAP.md`](ROADMAP.md) | **路线图**，P0–P5。优先级唯一依据 | 决定先做什么 |
| [`P0-execution-plan.md`](tasks/P0-execution-plan.md) | **P0 任务书**，11 项 + P0-REVIEW-04…08 + 依赖图 + 验收命令 | 执行 P0 |
| [`PROJECT-MAP.md`](PROJECT-MAP.md) | **项目地图**，真实目录树 + 工作流全景 + 诚实状态 | 想知道"东西在哪" |
| [`PROJECT-README.md`](../README.md) | 项目根目录 README 的副本 | — |
| [`schemas/script-audit.schema.json`](schemas/script-audit.schema.json) | **审核报告 Schema**（draft-07），§4.3.10 的机器可读形式 | 校验/写审核报告时 |

## 审核口径（P0-REVIEW-04 / 05 定稿）

规范 §4.3.10。三个容易混的点：

| 点 | 结论 |
| --- | --- |
| `alteration_origin` | `manga / narration / mixed / unknown`；无差异**留空**，不许写 `"none"` |
| `status` vs `review_status` | 逐段处理状态（含 `pending_rewrite`）≠ 人工签核状态 |
| 两层 `fidelity` | `novel_ref` 判「漫画 vs 小说」，`script-audit` 判「旁白 vs 来源」，靠 `judgement_scope` 区分 |

**`alteration_origin` 不能代替来源引用**：标了 `manga` 仍必须给 `pages_declared`。

### 四条不许被绕过的规则（P0-REVIEW-05）

| 风险 | 怎么锁住 |
| --- | --- |
| `mixed` 变成逃避举证的分类 | `manga` / `mixed` 都必须给 `pages_declared`；`mixed` 另需必填 `mixed_note`，写明哪部分是漫画给的、哪部分是旁白新增的 |
| `rewritten` 被当成 `approved` | `rewritten` + `pending_human` 是**合法组合**；`reviewed_by` 不得等于 `prepared_by`（机器不能自己签自己） |
| `judgement_scope` 只是个字符串 | Schema 里是 `const`；`lint` 拒错值；`check` 第 4 步验另一个值；审核报告里出现 `beats` / `novel_chapters` 直接报错 |
| 换行规则没跨平台复验 | `tests/test_lf.py` 6 例：三种 `autocrlf` 新克隆、索引侧零 CRLF blob、以及"删掉 `.gitattributes` 后确实泄漏"的反证 |

另加两条收紧：`narration` + `keep` 报错（旁白自己编的不能留）；
`unknown` + `approved` 报错，且整份有 `unknown` 时不许 `approved`——`unknown` 是待办，不是结论。

## 章节身份：三套编号必须分开（P0-08）

`m1/v2/ch06` 里三个值单看都对，合起来就是错的：

| 身份来源 | 值 | 含义 |
| --- | --- | --- |
| 目录名 | `ch06` | **全书**第 6 章 |
| `chapter.json` 的 `id` | `ch01` | **本卷**第 1 章 |
| `chapter.json` 的 `number` | 第六章 | 全书第 6 章（中文） |
| `chapter_uid` | `konosuba-manga-v02-ch06` | **唯一权威身份** |

所以 `chapter_uid` 是唯一权威身份，被「章节工作区 / `chapter.json` /
`novel_ref.json` / `script.json` / `script-audit.json`」全部引用。

**不一致就报错，不猜。** 反例已写成测试：目录 `ch06` + `chapter.json` 说 `ch01`
+ `novel_ref` 说 A + `script-audit` 说 B → 退出码 3，且报错里把 A/B/C 与基准值
全部列出来，**不允许自动选"最接近的那一章"**。

**哈希只能证明"没被改过"，证明不了"属于这一章"**——所以身份校验放在门禁
**第 1 步**，先于任何内容校验。

### 七类局部错配必须逐类拒绝（P0-REVIEW-06）

只测"五处全冲突"不够，真实迁移里更常见的是只错一处。矩阵每一类只破坏一对关系：

| # | 场景 | 拒绝依据 |
| --- | --- | --- |
| 1 | 工作区目录名 vs `chapter.json` | 目录名报全书号不符 |
| 2 | `chapter.json` vs `novel_ref.json` | 列出两个 uid |
| 3 | `novel_ref.json` vs `script.json` | 两两冲突汇总 |
| 3b | 上述冲突 + `chapter.json` 缺 uid | **逐项比对整轮空转时仍须拒绝** |
| 4 | `script.json` vs `script-audit.json` | 两两冲突汇总 |
| 5 | 五处一致但 uid 不在权威表 | 报"不在权威章节映射表" |
| 6 | 缺 `chapter_uid` / 权威表 uid 重复 | 一律 error |
| 7 | CLI `--verify` 命中场景 5 | **退出码 3**，拒绝路径接入 CLI |

权威表由 CLI 从卷级 `chapter_index.json` **自动加载**——五份文件一起抄错一个
不存在的章号，自洽也照样拒绝。唯一 warning 例外是 v1 `script.json` 没有
章节声明（P0-11 迁移后消失）。

### 校验必须 fail-closed（P0-REVIEW-07）

「找不到权威表就跳过」等于把 P0-08 的立论作废。现在：

| 情形 | 结果 |
| --- | --- |
| 找不到 `chapter_index.json` | 退出码 3；只有代码里显式传 `authority=False` 才可跳过 |
| 权威表损坏 / 为空 | 退出码 3 |
| 权威索引自身不合格（uid/id/number 重复、编号跳号） | 退出码 3，**章级也拒绝** |
| 身份文件存在但 JSON 损坏 | 退出码 3（损坏 ≠ 不存在） |
| 审计段落 `segment_id` 重复 | 退出码 3，不做 first-wins / last-wins |
| `severity` 越界（如 `catastrophic`） | 退出码 3（Schema 与 Linter 同步） |

顺带查出一个比"临时目录缺表"更严重的问题：真实布局的索引在
`m1/v1/work/chapter_index.json`，旧搜索路径只找 `work.parent` 与
`work.parent.parent`，**从未加载过权威表**——此前十次"正常路径通过"实际是
"根本没校验就通过"。已修正搜索路径并补测试。

### 合法 JSON ≠ 结构合法（P0-REVIEW-08）

`json.loads("null")` 会成功返回 `None`。如果只区分"文件在不在"和"JSON 坏没坏"，
那么 `chapter.json` 写成 `null` 就会被当成"还没读到章节"，身份校验静默放行。
现在身份文件与审计报告都要先验顶层结构：

| 输入 | 结果 |
| --- | --- |
| `chapter.json = null` / `[]` / `"wrong type"` / `123` | 章级 `--verify` 退出码 3 |
| `novel_ref.json = null` / `script.json = []` / `script-audit.json = null` | 章级 `--verify` 退出码 3 |
| 权威表顶层不是对象，或 `chapters` 不是章节对象数组 | 退出码 3 |
| 同时存在多份 `chapter_index.json` | 退出码 3（不替你挑哪份是当前卷） |
| `audited_segments = [null]` | `m1 novel lint` 退出码 3，不抛 traceback |
| `severity = null` / `pages_actual = null` / `pages_actual = ["p45"]` | `m1 novel lint` 退出码 3 |
| `alteration_origin=narration` + `disposition=fix_pages` | `m1 novel lint` 退出码 3 |
| `reviewed_by = []` | `m1 novel lint` 退出码 3 |

注意：`severity` 是可选字段，但"没写"合法、"写了 `null`"非法；
Schema 里 `severity` 只有四个字符串枚举，没有 `null`。

### 类型错误不是身份（P0-REVIEW-09）

Python 里 `True == 1 == 1.0`，所以"数值相等"不能证明"类型正确"。
现在身份整数一律用 `type(v) is int`，字符串字段必须真是字符串；
唯一性检查只把字符串放进字典键，格式化 `ch{vcn:02d}` 前先验类型。

| 输入 | 结果 |
| --- | --- |
| 身份整数 = `true` / `false` / `1.0` / `"1"` / `[]` / `{}` | 章级/卷级 `--verify` 退出码 3 |
| `chapter_uid` / `series_slug` / `id` / `number` = `123` / `true` / `[]` / `{}` | 退出码 3 |
| 索引章节的 `id` / `chapter_uid` / `number` = `[]` / `{}` | 卷级 `--verify` 退出码 3，不抛 `TypeError` |
| 审计枚举 = `[]` / `{}` / 数字 / 布尔 / 错误字符串 / `null` | `m1 novel lint` 退出码 3，不抛 `TypeError` |
| `alteration_origin = []` 且 `fidelity=altered` | `m1 novel lint` 退出码 3 |
| 非 `original` 删除 `novel_para`，或 `drawn/altered` 删除 `pages_declared` | Schema 与 Linter 都拒绝 |
| 非 mixed 记录写 `mixed_note=""` | Schema 与 Linter 都拒绝 |
| `approved` 且 `reviewed_by == prepared_by` | Schema 通过，Linter 拒绝：这是业务纪律 |

Schema 层负责结构、类型、枚举、格式和可表达的条件规则；`lint_audit()` 额外执行
Schema 无法表达的业务纪律。两边不能对同一基础规则给出相反结果。
`TestSchemaLinterParity` 用 `jsonschema` 做正反例对照（仅测试可选依赖；
环境没有该库时这 3 条会跳过并给出原因）。

### LF 证据链的三条边界

**不许单独拿 `i/lf` 推导"所有平台工作区都是 LF"**：

| 证据 | 能证明 | 不能证明 |
| --- | --- | --- |
| `git ls-files --eol` 的 `i/lf` | blob 里存的是 LF | 检出到工作区后是否仍是 LF |
| `.gitattributes` 的 `eol=lf` | 约束检出时的转换 | 纠正不了已存进 blob 的 CRLF |
| 不同 `core.autocrlf` 新克隆 | 该配置下实际落盘字节 | 只覆盖被测过的配置 |

三者合起来才是完整证据。规范 §4.3.9 已按此边界改写。

## 当前进度（2026-11-16）

### 已实现

| 能力 | 证据 |
| --- | --- |
| 素材摄取（mobi / epub） | 169 页 / 167 页 |
| 小说正文抽取 | 2,627 段 / 83,599 字，双哈希稳定 |
| 章节定界 | 半自动（程序测墨量 + 人读横幅） |
| 按章切工作区 | 12 个章级 work |
| 配音 → 时间轴 → 渲染 → 烧字幕 | 十章 mp4，每章 15/15 |
| 15 条技术验收 | `run_report.json` 逐条留痕 |
| **底稿对齐骨架 + 五步门禁** | `m1 novel align/check` |
| **审核报告 Schema 校验** | `m1 novel lint`（只校格式、不要求签核） |
| **章节身份强校验** | `m1 chapter --verify`（不一致就报错，不猜"最接近"） |
| **第一章逐段来源审计** | 25 段 100% 审完，**未签核** |
| 测试 | **422 tests OK (skipped=2)**（`test_novel.py` 102 例 / `test_identity.py` 64 例 / `test_lf.py` 6 例） |

### P0 任务状态

| ID | 任务 | 状态 |
| --- | --- | --- |
| P0-01 | 核实十章 ↔ 小说 ↔ 讲稿对应 | 🔄 **第一章样张完成**，其余九章未核 |
| P0-02 | 十章各建 `novel_ref.json` | 🔄 **ch01 完成**（34 beats），其余九章未建 |
| P0-03 | 讲稿来源 **100%** 复核 | 🔄 **ch01 完成**（13 段待改写 + 1 段改页映射），其余九章未审 |
| P0-04 | 改稿后重出受影响成片 | ⬜ 未开始（等 P0-03） |
| P0-05 | `m1 novel --align/--check` | ✅ **已完成**（含验收第 5 条补修 + lint 拆分） |
| P0-06 | 正式出片门禁（`--draft` + 审核报告） | ⬜ 未开始 |
| P0-07 | 文档与实现统一 | 🔄 进行中 |
| P0-08 | 章节身份统一 | 🔄 **主体完成，待最终签核**（P0-REVIEW-09 已关闭严格类型绕过，仍待独立复审） |
| P0-09 | 规则冲突核查 | 🔄 部分完成（1/2/3 页映射密度未验） |
| P0-10 | `m1 verify --visual` 三层视觉验收 | ⬜ 未开始 |
| P0-11 | `script.json` v1→v2 迁移（含三态） | ⬜ 未开始 |
| P0-REVIEW-04 | 审核口径进规范 + Schema + lint | ✅ **已完成**（样张升 v2，仍未签核） |
| P0-REVIEW-05 | 四条风险落地（mixed / rewritten / scope / LF） | ✅ **已完成**（Schema 11 条条件规则 + 6 例换行复验） |
| P0-REVIEW-06 | 身份测试矩阵 + 权威表校验 | ✅ **已完成**（七类局部错配 + CLI 端到端拒绝） |
| P0-REVIEW-07 | fail-closed 身份 + 审计完整性 | ✅ **已完成**（权威表缺失/损坏/不合格一律拒绝；重复段落拒绝；`severity` 补齐） |
| P0-REVIEW-08 | JSON 结构 fail-closed + Schema/Linter 对齐 | 🔄 **部分通过**（顶层结构/权威表修复成立；严格字段类型与枚举安全由 P0-REVIEW-09 补齐） |
| P0-REVIEW-09 | 严格字段类型与验证器全域性 | ✅ **本轮已落地**（int/string 严格类型、枚举不可哈希安全、Schema 条件 required；类型负例 CLI 均 exit 3） |

### 放行条件

**P0-RELEASE-GATE**（规范 §9.6）九条，全过才允许进入量产。
详见 [`ROADMAP.md` §2.3](ROADMAP.md)。

### 现在卡在哪

第一章样张等**人工签核**：把 `m1/v1/ch01/script-audit.json` 的
`reviewed_by` 填 `human:<name>`、`review_status` 改 `approved`。
签核前 `m1 novel check` 会一直卡在第 5 步——这是设计如此，不是 bug。

## 复核命令（新克隆即可复现）

```bash
python -m unittest discover -s tests     # 期望 Ran 422 tests / OK (skipped=2)
python -m panelcast m1 novel lint --work m1/v1/ch01/work   # 格式校验，应通过
python -m panelcast m1 novel check --work m1/v1/ch01/work --novel-dir <小说文本目录>
                                          # 门禁，样张应卡在第 3/4/5 步（退出码 3）
git ls-files --eol | grep -c "i/crlf"   # 期望 0
```

第一章 `script-audit.json` 保持 `review_status: pending_human`、`reviewed_by: null`，
**机器不能替人签核**；签核只能由项目负责人本人完成。
