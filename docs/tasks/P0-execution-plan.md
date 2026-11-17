# P0 执行计划：内容可信度与规范闭环

> 依据：`docs/ROADMAP.md` §2、2026-11-16 审核意见。
> **本文是 P0 九项任务的任务书**，执行方按此逐项交付。
> P1（横版切格工具）在 P0 全部完成前**不得开始**。

---

## 0. P0 要解决什么

十章成片技术验收 15/15 全绿，但：

- 讲稿产出于 S5a（底稿对齐）写进规范之前，**没有一段旁白能追溯到小说段落**；
- 已出现事实错误：第六章把"铁笼泡湖净化"写成"哥布林绑票 + 竹筏 + 大青蛙吞笼"；
- 第一～五章用同一套"只看画面"方法写成，**风险同级，未逐章复核**。

所以 P0 的目标不是"补十份 JSON"，而是**把十章从技术验证片升级为内容合格片**，
并且**让以后的正式出片无法绕过来源门禁**。

### P0 完成标准（总）

1. 十章都有 `novel_ref.json`，`m1 novel --check` 全过；
2. 十章讲稿 **100%** 段落有来源结论（不是抽查），无来源段落已改写；
3. 重出的十章成片，`delivery.md` 明确区分"技术合格"与"内容合格"；
4. 正式出片路径无法绕过来源门禁，**且无法绕过 `script-audit.json` 审核门禁**，**有测试证明**；
5. 主规范 / PROJECT-MAP / README / CLI 帮助文本四者一致；
6. 章节身份有全书唯一 ID，人工不再依赖模糊的 `id/number`，
   **且 `novel_ref` / `script` / 交付清单三处用同一个 `chapter_uid`**；
7. 十章脚本迁到 v2 schema，`source_refs` 无一条是自动推断出来的；
8. `m1 verify --visual` 能对十章真实帧给出通过/不通过结论，且能抓到 5 类注入故障；
9. **P0-RELEASE-GATE 九条全过**（见下节）。

---

## 1. 依赖图与执行批次

```
批次 1　基础与内容可信度
  P0-07/08/09 文档与身份（最便宜，先做）
            ↓
  P0-05 m1 novel --align/--check   ← 没有它，P0-02 只能手写 10 份 JSON
            ↓
  P0-01 对应表 → P0-02 novel_ref → P0-03 讲稿审计 → P0-04 重出片（×10 章）
            │
批次 2　Schema 迁移            ▼
  P0-11 script v1→v2            ← 前置 P0-02（要有 beat 才能填 source_refs）
            │
批次 3　审核门禁               ▼
  P0-06 正式出片门禁            ← 含 script-audit.json 校验，依赖 P0-11 的 v2 与审核流程
            │
批次 4　验收与文档统一         ▼
  P0-10 verify --visual
  P0-09 补：1/2/3 页映射下的密度可行性验证
  P0-07 收尾：run_report / chapter_index 状态核对
            │
批次 5　总验收                 ▼
  P0-RELEASE-GATE 九条（不是第十二个任务，是放行条件）
```

**批次顺序依据（三审意见）**：先让内容可信（批次 1），再让数据模型统一（批次 2），
再让门禁拦得住（批次 3），再让验收看得见（批次 4），最后总验收（批次 5）。
`P0-11` 从原计划的批次 4 前移到批次 2——迁移依赖 beat，而 beat 在批次 1 就齐了；
把它排在门禁之后会导致 P0-06 要同时处理 v1/v2 两套 schema，徒增复杂度。

**为什么 P0-08 要排在 P0-02 前面**：`novel_ref.json` 会引用章身份。
如果先做十份底稿再改章节 ID，十份都要返工。

**为什么 P0-05 要排在 P0-02 前面**：`--align` 能给候选段区间和骨架，
手写十份 `novel_ref.json` 是纯体力活且容易漏页。

**为什么 P0-11 要排在 P0-02 后面**：v2 schema 的核心是逐段 `source_refs`，
而 `source_refs` 只能来自 `novel_ref.json` 的 beat。没有 beat 就迁移，
只能靠"看画面猜来源"，这正是规范明令禁止的（§4.3.4 迁移第 5 步）。

### 工作量预估（诚实版）

| 项 | 量 | 说明 |
| --- | --- | --- |
| P0-01 对应表 | 十章 × 约 30 分钟 | 读小说原文 + 对页 |
| P0-02 底稿 | 十章 × 约 40 分钟 | 建 beat、判 fidelity |
| P0-03 讲稿审计 | 十章 × 约 60 分钟 | **逐段**核，249 页约 190 段 |
| P0-04 重出片 | 十章 × 约 5 分钟机时 | 只重算改动段 |
| P0-05/06 代码 | 约 1.5 天 | 含测试 |
| P0-07/08/09 文档 | 约 0.5 天 | 最便宜，先做 |
| P0-10 视觉验收 | 约 1 天 | 三层 12 项判据 + 切页全查，比原估 0.5 天上调 |
| P0-11 Schema 迁移 | 约 0.5 天代码 + 十章 × 10 分钟 | 迁移脚本 + 三态 + 逐章核对不推断 |
| P0-RELEASE-GATE | 约 0.5 天 | 含故障注入验证 |

合计约 **22 小时人工 + 3.5 天编码**。这不是"跑个脚本"的活。

---

## 2. 任务书

### P0-09 规则冲突核查（先做，最便宜）

**目标**：把"文档说的"和"代码做的"对齐，确认是文档过时还是代码有缺陷。

**当前事实（已核实）**

| 冲突点 | 代码实际 | 结论 |
| --- | --- | --- |
| §5.8 写"段内页时长均分" | `timeline.py` 是 `_segment_cuts` 段内切分 + 句边界吸附 | **文档过时**，改文档 |
| "每段 ≤130 字" vs "45–90 字/页" | 130 上限**代码里不存在**；第 15 条密度是章级 `chars/页数` | **文档规则冲突**，改文档 |
| S4 分格是否硬门禁 | `--skip-panel-gate` 开关已存在 | 竖版合法默认，横版才强制 |

**范围**：`docs/WORKFLOW-v1-vertical-manga-narration.md` 的 §5.6.2 / §5.8 / §9.1。
**不做**：不改 `timeline.py`、`verify.py`（已核实无缺陷）。

**验收**
1. §5.8 明确写出 5 步算法（累加→均分理想点→吸附句边界→不越段→体检停留）；
2. §5.6.2 给出按页数的字数表（1 页 45–90 / 2 页 90–180 / 3 页 135–180）；
3. 文档不再出现"段内页时长均分"这句；
4. `python -m unittest discover -s tests -q` 仍全绿。

**状态：本轮已完成**（见主规范 §5.6.2、§5.8）。

---

### P0-07 文档与实现统一

**目标**：主规范 / PROJECT-MAP / README / CLI 帮助四者不再互相矛盾。

**当前事实（已核实）**

| 项 | 原状态 | 已改 |
| --- | --- | --- |
| S2 章节定界 | 主规范写【待建】，地图写半自动 | 统一为"半自动：人工确认 + 程序辅助" |
| `run_report.json` | 主规范写【待建】 | 改【已实现】 |
| `chapter_index.json` | schema 标【待建】 | 改"半自动：人工数据 + 程序辅助测量" |
| CLI 子命令 | 文档混用 `m1 chapter` / `m1 slice` | 明确 `chapter`=定界，`slice`=切章 |
| `m1 verify` 帮助 | 写"13 acceptance checks" | 改 15 |
| README | 仍写"只做 ingest" | **待改** |

**范围**：`README.md`、`docs/*.md`、`panelcast/__main__.py` 的帮助字符串。
**不做**：不改任何行为逻辑。

**验收**
1. `README.md` 反映当前能力（摄取 + 切章 + 出片 + 验收 + 编辑器），并链到 ROADMAP；
2. `python -m panelcast m1 --help` 列出的每个子命令都在文档里有对应小节；
3. 文档里不再出现 `python -m panelcast s0`（该子命令不存在）；
4. 状态标注只有四种：【已实现】【半自动】【占位】【待建】。

---

### P0-08 章节身份统一

**目标**：全书唯一 ID + 三种编号分开，人工不再靠猜 `id` 是卷内还是全书。

**当前事实（已核实）**

- 目录用 `ch06..ch10`（全书编号）；
- `chapter_index.json` 用 `ch01..ch07`（卷内编号）；
- `find_chapter` 按 `id` 或 `number` 匹配，实际调用都传「第六章」才没炸。

**P0-REVIEW-04 登记为明确问题（不是命名不统一）**

五章实测，三套编号在同一目录里对不上：

| 目录 | `chapter.json.id` | `number` | 真实身份 |
| --- | --- | --- | --- |
| `m1/v2/ch06` | `ch01` | 第六章 | 第二卷第一章（全书第六） |
| `m1/v2/ch07` | `ch02` | 第七章 | 第二卷第二章 |
| `m1/v2/ch08` | `ch03` | 第八章 | 第二卷第三章 |
| `m1/v2/ch09` | `ch04` | 第九章 | 第二卷第四章 |
| `m1/v2/ch10` | `ch05` | 第十章 | 第二卷第五章 |

危险不在难看，在**门禁抓不到**：哈希绑的是文件内容，不是章节身份。
底稿 / 审计 / 讲稿一旦写进错误工作区，整章内容张冠李戴，五步门禁照样全过。
**这是 P0-01 的前置风险**：对应关系人工做对了也没用，写错目录就全废。

**目标结构**

```json
{"chapter_uid": "konosuba-manga-v02-ch06",
 "volume_number": 2,
 "global_chapter_number": 6,
 "volume_chapter_number": 1,
 "id": "ch01",
 "number": "第六章",
 "label_zh": "第六章 为这片湖献上自称女神的圣水！"}
```

**范围**：`panelcast/chapters.py`（`find_chapter` / `build_index`）、
两份 `chapter_index.json`、`m1 slice` 参数解析、相关测试。
**不做**：不改目录名（`m1/v2/ch06` 保持，避免十处路径全动）。

**验收**
1. 两份 `chapter_index.json` 都有 `chapter_uid`，格式 `<系列>-v<卷两位>-ch<全书两位>`；
2. `find_chapter` 支持 `chapter_uid` / `id` / `number` 三种入参，且三者歧义时**报错**而不是猜；
3. 新增测试：两卷各一章用 `chapter_uid` 查找成功；传 `ch01` 给第二卷能正确解析为「第六章」；
4. `m1 slice` 用 `--chapter 第六章` 与 `--chapter konosuba-manga-v02-ch06` 结果一致。

**执行结果【已完成】**

| 项 | 结果 |
| --- | --- |
| 身份模块 | `panelcast/identity.py`（uid 生成/解析、单章自洽、整卷自洽、跨文件核对） |
| 命令行 | `m1 chapter --verify`（卷级验索引、章级验跨文件） |
| 门禁 | `m1 novel check` 第 1 步先验身份 |
| 数据迁移 | 2 份索引 + 10 份 `chapter.json` + 2 份 labels 全部补齐 |
| 实测 | 两卷索引 + 十个章级 work `--verify` 全过 |
| 测试 | `tests/test_identity.py` 68 例 + `tests/test_novel.py` 105 例 + `tests/test_lf.py` 6 例；全量 **430 tests OK (skipped=2)**（P0-REVIEW-10 后） |

**审核意见里的反例已写成测试**（`test_counter_example_from_review`）：
目录 `ch06` + `chapter.json` 说 A + `novel_ref` 说 B + `script-audit` 说 C
→ 报错，且报错信息里 A/B/C 与基准值全部出现。**不选"最接近的"。**

**身份测试矩阵（P0-REVIEW-06 追加，10 例）**。完整反例之外，逐类只破坏一对关系，
验证校验器不会因为"其余四处都对"就放过：

| # | 场景 | 必须拒绝 |
| --- | --- | --- |
| 1 | 工作区目录名 vs `chapter.json` | 目录名报全书号不符 |
| 2 | `chapter.json` vs `novel_ref.json` | 列出两个 uid |
| 3 | `novel_ref.json` vs `script.json` | 两两冲突汇总 |
| 3b | 上面这对冲突 + `chapter.json` 缺 uid（逐项比对整轮空转） | **仍须两两冲突汇总** |
| 4 | `script.json` vs `script-audit.json` | 两两冲突汇总 |
| 5 | 五处一致但 uid 不在权威章节表 | 报"不在权威章节映射表" |
| 6 | 缺 `chapter_uid`（三份绑定文件） | 一律 error；v1 `script.json` 是唯一 warning 例外 |
| 7 | 权威表里 uid 重复 | 报"重复" |
| 8 | CLI `m1 chapter --verify` 命中场景 5 | **退出码 3**，证明拒绝路径接入 CLI |

其中 3b 是矩阵的关键：`check_work_identity` 原本只做"每份 vs `chapter.json`"，
基准自身缺失时整轮空转。现在补了"每份 vs 每份"的两两交叉比对。
权威表由 CLI 从卷级 `chapter_index.json` **自动加载**——五份文件一起抄错一个
不存在的章号，自洽也照样拒绝。

**一个刻意的取舍**：`id` 仍保留 `ch01–ch05`（卷内），**目录名不改**。
理由是改名要动十处路径与所有引用，而身份统一并不需要改目录——
需要的是"目录名的含义固定为全书号"并且**被校验**。
`m1/v2/ch09` 里放第六章的 `chapter.json` 会立刻报错，这就够了。

---

### P0-05 `m1 novel --align` / `--check`

**目标**：把 S5a 从文档流程变成可执行门禁。

**当前事实**

- 抽取半边已有：`tools/novel_extract.py`（2,627 段 / 83,599 字，11 个测试）；
- 对齐与校验**完全没有**；
- `m1 run` 不读 `novel_ref.json`。

**子命令设计**

```bash
# 只生成候选与骨架，绝不自动标成人工确认
python -m panelcast m1 novel --align --work m1/v1/ch02/work

# 五步门禁链，任一不过退出码 3
python -m panelcast m1 novel --check --work m1/v1/ch02/work
```

`--align` 输出：按人物/事件锚点给候选小说段区间 + 生成 `beats` 骨架，
所有 beat 标 `fidelity: "unconfirmed"`、`review_status: "needs_review"`。
**候选不得伪装成已确认**。

`--check` 五步（对应主规范 §9.1）：

```
1. novel_ref.json 存在？
2. novel_ref.source.text_sha256 == novel_index.json 的 file_sha256？
3. 每段 source_refs 非空且 beat 存在？
4. beat 页映射合法（页在本章、original 必带 pages）？
5. script-audit.json 有效？（script_sha256 / novel_ref_sha256 / 逐段 text_sha256
   与当前文件一致，且每段 reviewed_by 是人）
```

> 第 2 步比的是 `text_sha256`（`novel.txt` 落盘字节，含尾换行，= `novel_index.json`
> 的 `file_sha256`），**不是** `source.sha256`（EPUB 原文件）。两者永远不相等，
> 写错会让底稿永远判定为失效。见主规范 §4.3.9 的双哈希对照表。
> 第 5 步对应 P0-C（审核报告门禁），`--check` 实现时若 `script-audit.json`
> 尚不存在，应报"未审核"而不是静默跳过。

**范围**：新增 `panelcast/novel.py` + `__main__.py` 子命令 + `tests/test_novel.py`。
**不做**：`--align` 不调用视觉模型（那是 S3 的事），只做文本锚点匹配。

**验收**
1. `--check` 在缺 `novel_ref.json` 时退出码 3，输出一行 `error:`；
2. 篡改 `novel.txt` 后 `--check` 报"底稿失效"并指出 hash 不一致；
3. 某段 `source_refs` 为空 → `--check` 报出**具体段 id**；
4. `original` 的 beat 缺 `pages` → 报错；
5. `--align` 生成的 beat 全部 `needs_review`，`--check` 对未确认的 beat **报错而不是放过**；
6. 缺 `script-audit.json` → `--check` 报"未审核"（退出码 3），**不得静默通过**；
7. 改动 `script.json` 任一段文字后，原 `script-audit.json` 判定失效并指出是哪一段的 `text_sha256` 变了；
8. 新增测试 ≥15 个，全量 250+ 通过。

---

### P0-REVIEW-04 审核口径与 Schema 修订【已完成】

**来源**：项目负责人对第一章样张的审核意见。三项决定 + 一条要求：
认可 `alteration_origin`；接受"待改写"状态但要用 `pending_rewrite` 并写进正式 Schema；
同意 `seg_0025` 判 `altered` 不改稿；要求把 P0-08 编号冲突登记为明确问题。

**做完的四件事**

| # | 事项 | 产物 |
| --- | --- | --- |
| 1 | 判据写进规范 | §4.3.10 重写：`alteration_origin` 四值 + 无差异留空、`status` 四值、`judgement_scope`、证据可定位、`disposition` |
| 2 | 机器可读 Schema | `docs/schemas/script-audit.schema.json`（draft-07，含 if/then 条件规则） |
| 3 | 校验器 + CLI | `lint_audit()` / `m1 novel lint`（只校验格式、不要求签核）；`check` 第 5 步改为先 lint 后哈希 |
| 4 | 样张升级 | `script-audit.json` → v2，**保持未签核**；`seg_0024` 自相矛盾已改正 |

**关键设计：为什么把 `lint` 单独拆出来**

门禁第 5 步原本把"格式合法"和"人已签核"混在一个判定里，
结果一份**未签核**的报告根本没法被机器校验——它连"我格式对不对"都问不出来。
而样张恰恰必须保持未签核。拆开后：

- `m1 novel lint` → 格式合法就过（样张能过）
- `m1 novel check` → 还要哈希 + 签核（样张必须不过）

**验收（8 条，全部有测试）**

1. `status="pending"` 被拒，报错提示改用 `pending_rewrite`；
2. `alteration_origin="none"` 被拒（伪值），无差异必须留空；
3. `fidelity=altered` 但 `alteration_origin` 为空 → 被拒；
4. `alteration_origin=manga` 但 `pages_declared` 为空 → 被拒；
5. `mixed` / `unknown` 被接受（不许为了凑枚举硬挑）；
6. 缺 `judgement_scope` 或写成 `manga_vs_novel` → 被拒；
7. `novel_ref` 缺 `judgement_scope=manga_vs_novel` → 第 4 步报错；
8. `docs/schemas/script-audit.schema.json` 的枚举与代码常量一致（防两边分叉）。

**不做**：不改任何一段旁白（改写属 P0-03）；不签核（只能由人做）；不碰 `m1 run`。

---

### P0-REVIEW-05 审核口径补强【已完成】

**来源**：项目负责人对 `77735c0` 的复审，点出四个"应该锁住"的风险。
这四个都不是"本轮一定错了"，而是"以后会错"。

| # | 风险 | 处理 |
| --- | --- | --- |
| 1 | `mixed` 变成逃避举证的逃生门 | 新增必填字段 `mixed_note`，要求分开写"漫画给的"与"旁白新增的"；`mixed` 也必须给 `pages_declared` |
| 2 | `rewritten` 被当成 `approved` | 规则：`rewritten` + `pending_human` 是**合法**组合；`reviewed_by` 不得等于 `prepared_by`（机器不许给自己发合格证） |
| 3 | `judgement_scope` 只是字符串 | Schema 里是 `const`；`lint` 拒绝错值；`check` 第 4 步验 novel_ref 的另一个值；**审核报告里出现 `beats` 等 novel_ref 专有字段直接报错**（两层混在一份文件里） |
| 4 | `.gitattributes` 没做过新克隆复验 | 新增 `tests/test_lf.py`：造临时仓库，用 `autocrlf=true/input/false` 三种设置分别克隆，逐字节比对；**另加反证**——去掉 `.gitattributes` 后 `autocrlf=true` 确实会把 LF 变成 CRLF，证明前一条不是空跑 |

**额外收紧的两条**（顺着同一逻辑推出来的）：

- `narration` + `disposition=keep` → 报错。旁白自己编的内容保留，等于承认这段没有来源。
- `unknown` + `status=approved` → 报错；有 `unknown` 时整份不许 `review_status=approved`。
  `unknown` 是待办，不是结论。

**边界说明（诚实版）**：本机只有 Windows，Linux 侧无法实跑。
但 Linux 的默认 `core.autocrlf` 是 `false`（或 `input`），两者都在覆盖范围内；
真正决定检出结果的是 `.gitattributes` 而不是操作系统。
真仓库那条用例用 `--depth 1 --no-local` 克隆当前仓库、比 `novel_ref` 与 `script-audit`
的字节哈希，跑在 `autocrlf=true` 下——这是最接近"新克隆"的验证。

---

### P0-REVIEW-07 fail-closed 身份与审计完整性【已完成】

**来源**：项目负责人基于源码（`PanelCast-Code-main.zip`）做的独立代码复核，
给出可直接复现的反例。审核结论：**P0-08 暂不签最终验收**，因为存在静默放行路径。

**六个问题与处理**：

| # | 问题 | 实测表现 | 处理 |
| --- | --- | --- | --- |
| 1 | 权威表缺失时静默放行 | `chapter_index.json` 不存在 → `([], [])` | `authority=None` 找不到表即报错；唯一跳过方式是显式传 `authority=False` |
| 2 | 损坏 JSON 被当成不存在 | `novel_ref.json` 写成 `{broken` → `([], [])` | `_read_json` 返回 `(data, status)`，区分 `missing` / `corrupt`；损坏一律报错 |
| 3 | 章级不验整份权威索引 | 索引里另一章 `id` 重复、编号跳号，章级仍通过 | 加载权威表后先跑 `index_problems`，再查当前 uid |
| 4 | 重复 `segment_id` 可藏无效判定 | 无效记录在前、合法记录在后 → `[]` | 检测重复并报错，不做 first-wins / last-wins；另查"多余记录"与"未覆盖该段" |
| 5 | Schema 与 Linter 不一致 | `severity="catastrophic"` → `[]` | 补齐 `severity` 枚举、必填字段、`text_sha256` / `page_XXXX` 格式、`script_schema` 枚举 |
| 6 | 文档过期 | README 仍写 `250 tests`；PROJECT-MAP 同一文件内 P0-08 一处"待修"、一处"已完成" | 全部改为已实现 + 384 tests |

**额外查出一个比审核意见更严重的问题**：

真实布局 `m1/v1/ch01/work` 的索引在 `m1/v1/work/chapter_index.json`，
而旧实现只找 `work.parent` / `work.parent.parent`（= `m1/v1/ch01` / `m1/v1`），
**两个都不对**。所以真实仓库的章级 `--verify` 从来没有加载过权威表——
审核意见里"正常路径通过"的十次，实际是"根本没校验权威表就通过"。
已改为依次尝试 `<work>/`、`<work>/work/`、`<父>/`、`<父>/work/`、`<祖父>/`、`<祖父>/work/`。

**验收（逐条实跑，均为退出码 3）**：

| 场景 | 命令 | 结果 |
| --- | --- | --- |
| 无权威表 | `m1 chapter --verify --work <无索引的章级 work>` | exit 3，"找不到权威章节映射表" |
| 权威表损坏 | 同上，索引写成 `{broken` | exit 3，"无法解析（corrupt）" |
| 索引重复 id / 跳号 | 章级 `--verify` | exit 3，"权威索引自身不合格"（3 项） |
| 同上，卷级 | `m1 chapter --verify --work m1/v2/work` | exit 3 |
| `novel_ref.json` 损坏 | 章级 `--verify` | exit 3 |
| 重复审计段落 | `m1 novel lint` | exit 3，"segment_id 重复" |
| `severity=catastrophic` | `m1 novel lint` | exit 3，"severity 非法" |
| 审计 JSON 损坏 | `m1 novel lint` | exit 3，"存在但无法解析" |

**测试**：`test_identity.py` 41 → 50 例（新增 `TestFailClosed` 9 例）、
`test_novel.py` 64 → 78 例（新增 `TestAuditIntegrity` 12 例 + Schema 枚举 2 例）。
全量 **384 tests OK (skipped=2)**。第一章样张 `lint` 仍全过、`check` 仍卡在第 5 步。

**未变**：第一章 `review_status` 仍是 `pending_human`、`reviewed_by` 为 `null`；
第二章、九章批量、P0-06、P0-10、横版继续冻结。

---

### P0-REVIEW-08 JSON 结构 fail-closed 与 Schema/Linter 完整对齐【部分通过；由 P0-REVIEW-09 补齐】

**来源**：项目负责人独立复审（2026-11-16）。P0-REVIEW-07 的修复成立，
但 `_read_json()` 对合法 JSON `null` 返回 `(None, "ok")`，`load()` 只看
`corrupt`，所以 `chapter.json = null` 仍可能静默通过；Linter 也有
`severity: null`、`narration + fix_pages`、`reviewed_by: []`、
`pages_actual` 未校验等缺口。

**三块处理**：

| 块 | 处理 |
| --- | --- |
| A 身份 JSON 结构 | 缺失 / 语法损坏 / 顶层类型错误三分；`chapter.json`、`novel_ref.json`、`script.json`、`script-audit.json` 存在时必须为对象；权威表必须是对象且 `chapters` 为章节对象数组；多份权威表直接拒绝；索引系列/卷号必须与本章一致 |
| B 审计 JSON 结构 | `lint_audit()` 先验顶层对象、`audited_segments` 数组、每条记录对象；任何结构错误返回 `(sid, msg)`，不抛 traceback |
| C Schema/Linter 对齐 | `severity=null`、`pages_actual=null` / `["p45"]`、`narration + fix_pages`、`reviewed_by=[]` 等全部拒绝；补齐 `source_type` / `review_note` / `mixed_note` / `novel_para` / `pages_declared` 类型 |

**验收（逐条实跑，均为退出码 3）**：

| 场景 | 命令 |
| --- | --- |
| `chapter.json = null` | `m1 chapter --verify` |
| `novel_ref.json = null` | `m1 chapter --verify` |
| `script.json = []` | `m1 chapter --verify` |
| `script-audit.json = null` | `m1 chapter --verify` / `m1 novel lint` |
| `audited_segments = [null]` | `m1 novel lint` |
| `severity = null` | `m1 novel lint` |
| `pages_actual = null` | `m1 novel lint` |
| `pages_actual = ["p45"]` | `m1 novel lint` |
| `narration + fix_pages` | `m1 novel lint` |
| `reviewed_by = []` | `m1 novel lint` |

**正向回归**：第一章样张 `m1 novel lint` exit 0；`m1 novel check` exit 3
（`script/v1` 无 `source_refs`、34 beat 未确认、未签核）；10 个章级 work 与
两卷 `chapter_index.json` 的 `--verify` 全部 exit 0。

**测试**：`test_identity.py` 50 → 56 例、`test_novel.py` 78 → 89 例；
全量 **401 tests OK (skipped=2)**（缺真实 EPUB / MOBI 各 1）。
第一章 `review_status` 仍为 `pending_human`、`reviewed_by` 为 `null`。

**复审结论**：本项判 **PARTIAL**。顶层结构修复成立，但身份数字字段仍接受
`true` / `1.0`；章节对象内部字段与审计枚举字段遇数组/对象会抛 traceback；
Schema 条件分支缺 `required`。由 P0-REVIEW-09 关闭。

**边界**：P0-08 最终签核仍由项目负责人完成；本轮不替代人工签核。

---

### P0-REVIEW-09 严格字段类型与验证器全域性【部分通过；由 P0-REVIEW-10 补齐】

**来源**：项目负责人独立复审。P0-REVIEW-08 判 PARTIAL：`True == 1`、`1.0 == 1`
让错误类型通过身份比较；数组/对象进入枚举集合检查会抛 `TypeError`；
Schema 的条件分支只写 `minItems` 不写 `required`。

**三块处理**：

| 块 | 处理 |
| --- | --- |
| A 身份严格类型 | `volume_number` / `global_chapter_number` / `volume_chapter_number` 必须是 `type(v) is int` 且 ≥ 1，拒绝 `true` / `false` / `1.0` / 字符串 / 数组 / 对象；`chapter_uid` / `series_slug` / `id` / `number` 必须是字符串；唯一性检查只对字符串建键；`f"ch{vcn:02d}"` 前先验类型 |
| B 审计枚举安全 | `review_status` / `script_schema` / `severity` / `fidelity` / `status` / `disposition` / `alteration_origin` 先验类型再查枚举；数组/对象/数字/布尔一律返回 `(sid, msg)`，不抛 `TypeError` |
| C Schema/Linter 对齐 | `alteration_origin=manga` 与 `fidelity=drawn/altered` 分支补 `required: pages_declared`；非 `original` 分支补 `required: novel_para`；origin 条件 `if` 要求字段存在；`mixed_note=""` 拒绝；文档区分 Schema 层与业务纪律 |

**验收（逐条实跑，均为退出码 3，无 traceback）**：

| 场景 | 命令 |
| --- | --- |
| 身份整数 = `true` / `1.0` / `"one"` | `m1 chapter --verify` |
| `chapter_uid` / `series_slug` / `id` / `number` = `[]` / `{}` | `m1 chapter --verify` |
| 索引章节字段 = `[]` / 索引卷号 = `true` / `1.0` | `m1 chapter --verify`（卷级） |
| 审计枚举 = `[]` / `{}` / 数字 / 布尔 / 错误字符串 / `null` | `m1 novel lint` |
| `alteration_origin = []` + `fidelity=altered` | `m1 novel lint` |

**正向回归**：第一章样张 `m1 novel lint` exit 0；`m1 novel check` exit 3
（`script/v1` 无 `source_refs`、34 beat 未确认、未签核）；10 个章级 work 与
两卷 `chapter_index.json` 的 `--verify` 全部 exit 0。

**Schema/Linter 对照**：新增 `TestSchemaLinterParity`，用 Draft-07 校验器与
`lint_audit()` 跑同一批正反例；`jsonschema` 仅为测试可选依赖，缺失时 3 条
对照测试跳过并给出原因。另新增 `TestSchemaConditionalRequired` 直接锁 Schema
的 `required` 列表，不依赖该库。

**测试**：`test_identity.py` 56 → 64 例、`test_novel.py` 89 → 102 例；
全量 **422 tests OK (skipped=2)**（缺真实 EPUB / MOBI 各 1）。
第一章 `review_status` 仍为 `pending_human`、`reviewed_by` 为 `null`。

**复审结论**：本项判 **PARTIAL**。A/B 两项成立，但 `series_slug` 缺失/null
仍可放行，章节索引记录内的 `series_slug` 未参与一致性检查；`mixed_note` /
`evidence` 的纯空白仍是 Schema 通过、Linter 拒绝。由 P0-REVIEW-10 关闭。

**边界**：P0-08 最终签核仍由项目负责人完成；本轮不替代人工签核。

---

### P0-REVIEW-10 `series_slug` 契约 + 空白文本一致性【本轮已落地】

**来源**：项目负责人独立复审。只处理两个边界，不扩大架构范围。

| 块 | 处理 |
| --- | --- |
| A `series_slug` | 加入 `IDENTITY_FIELDS`；`chapter.json` 与索引 `chapters[]` 的 `series_slug` 缺失/null 直接失败；每条记录必须与 `chapter_uid` 解析出的 slug、索引顶层 `series_slug` 一致；`build_index()` 与两份真实索引同步补字段 |
| B 空白文本 | Schema 的 `mixed_note` / `evidence` 增加 `pattern: "\\S"`，与 Linter `.strip()` 对齐；`""`、`" "`、`"\t\n"` 两边都拒绝，有实际内容两边都通过 |

**验收（逐条实跑，均为退出码 3，无 traceback）**：

| 场景 | 命令 |
| --- | --- |
| `chapter.json.series_slug` 缺失 / `null` / 错配 / 非字符串 | `m1 chapter --verify` |
| `chapter_index.chapters[].series_slug` 缺失 / `null` / 错配 | `m1 chapter --verify`（卷级） |
| `mixed_note` / `evidence` = `""` / `" "` / `"\t\n"` | `m1 novel lint` |

**正向回归**：第一章样张 `m1 novel lint` exit 0；`m1 novel check` exit 3；
10 个章级 work 与两卷索引 `--verify` 全部 exit 0。

**测试**：`test_identity.py` 64 → 68 例、`test_novel.py` 102 → 105 例、
`test_chapters.py` +1 例；全量 **430 tests OK (skipped=2)**。

**边界**：第一章 `pending_human` / `reviewed_by=null` 不变；第二章、九章批量、
P0-06、P0-10、横版继续冻结；P0-08 最终签核仍待独立复审。

---

### P0-01 十章对应关系核实

**目标**：一张表，把"章 → 小说段区间 → 讲稿段数 → 成片 hash"钉死。

**当前事实（已核实，可直接用）**

- 小说第一卷 `1.epub`：2,627 段 / 83,599 字；序章 0–148、一章 149–711、
  二章 712–1280、三章 1281–2013、四章 2014–2550、终章 2551–2626；
- 漫画第一卷 5 章（p5/45/75/105/137），第二卷 7 章（p3/31/39/67/83/107/138）；
- **章标题是两套命名**，不能用标题对齐；
- **漫画会重排小说**：「圣水」在小说第四章第 87 段，漫画放到第一卷第五章；
- 第七章「梦幻竹笋」在 18 卷正文里只命中 1 次（vol.13），**第一卷 0 次 = 漫画原创**。

**产物**：`m1/audit/chapter-map.md`，每章一行：

| 章 | 漫画页 | 小说段区间 | order | 讲稿段数 | 成片 sha256 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 第六章 | p3–30 | 1281–1500（估） | in_order | 15 | `a1b2…` | 湖净化 |

**范围**：新建 `m1/audit/`。
**不做**：不在此任务改讲稿。

**验收**
1. 十章齐全，无 `TBD` 残留；
2. 每章的小说段区间**必须能被 `novel.txt` 实际取到内容**（贴出前 30 字作证）；
3. `order` 字段只有 `in_order / reordered / partial`，`reordered` 必须写明挪动方向；
4. 成片 hash 用 `sha256sum` 实测，不是抄 `delivery.md`。

**进度（2026-11-16）：第一章样张已完成，其余九章未动。**
**2026-11-17 复核状态：`P0-01-CH01-BEAT-MAPPING-FIX = MAPPING_REVIEW_PASS / SEGMENT_SOURCE_SYNC_RETURNED`；`P0-01-CH01-OWNER-REVIEW-CLOSEOUT = OPEN`。映射主体已获复核通过；seg_0014 来源范围已由 259–278 收窄为 259–277，待针对性复核（beat 数 34 → 37，37/37 仍 needs_review）。**

- 产物：`m1/audit/chapter-map.md`（第一章 30 条段落锚点 + 十章总表）
- 第一章结论：漫画 ch01 p5–42 = 小说 **序章 0–148 + 第一章 149–711（部分）**，
  `order: reordered`（漫画把序章后置成插叙）
- 小说有、漫画没画：ch01 309–387（两周土木工/浴场/马厩，约 3,400 字）、562–619、620–711
- 新增副产物：`m1/v2/ch06–ch10` 的目录名（ch06–ch10）与 `chapter.json` 的 `id`
  （ch01–ch05）、`number`（第六–十章）三者不一致 → P0-08 的直接证据
- 未完成：另九章的段区间与成片 hash（211 页 / 143 段）
- 方法修正：`contact_sheet.py` 拼图只用于初筛，**判读必须回单页**——
  第一轮用 6 页拼图看错了格序，第二轮改逐页读才纠正
- 复核修订（2026-11-17）：b18/b19、b25/b26 段号边界修正；
  b01 扉页描述修正；`seg_0005/0016/0018/0023` 按裁定修订；
  `novel_ref.json` 重绑 `novel_ref_sha256`；37 beats 仍全部 `needs_review`
- BEAT-MAPPING-FIX（2026-11-17）：b16 230–258、b17 259–277、b18 278–291；
  b23 拆为 b23a/b23b/b23c，b34 拆为 b34a/b34b；beat 数 34 → 37，
  37/37 仍 `needs_review`
- 映射复核通过后的来源同步（2026-11-17）：seg_0014 `novel_para`
  `[259,278] → [259,277]`，`evidence` 同步；`novel_ref.json` 未改

---

### P0-02 十章 `novel_ref.json`

**目标**：每章一份底稿对齐表，schema 见主规范 §4.3.9。

**输入**：P0-01 的区间 + `m1 novel --align` 的候选。
**产物**：`m1/v{n}/chNN/work/novel_ref.json` × 10。

**做法**
1. 跑 `--align` 得候选；
2. **逐 beat 人工判 fidelity**（`drawn / omitted / altered / original`）；
3. 每 beat 映射 0–3 个漫画页；页上没画就留空数组；
4. 填 `coverage`（`novel_chars` / `script_chars` / `by_fidelity` 计数）。

**门禁**
- `beats` 覆盖本章**全部**漫画页（每页至少出现在一个 beat 的 `pages` 里）；
- 四类 `fidelity` 计数之和 = `beats_total`；
- `original` 必带 `pages`（否则就是凭空写的）；
- `source.text_sha256` == `novel_index.json` 的 `file_sha256`
  （**不是** `source.sha256`，那是 EPUB 原文件哈希，永远对不上）。

**不做**：不为了"覆盖全"把没读过的段标成 `drawn`。宁可 8 条 `omitted`。

**验收**
1. `m1 novel --check` 十章全过；
2. 每章 `by_fidelity` 四类计数可在报告里逐条对上 `beats` 列表；
3. 抽查 3 章：随机取一个 `drawn` beat，其 `pages` 上确实画了这件事。

---

### P0-03 讲稿来源复核（100%，不是抽查）

**目标**：逐段确认"这句话从哪来"，两边都没有的必须改。

**为什么不能抽查**：这十章的原始生产方法已被证明有系统性风险
（第六章整段编造），随机抽 3 段证明不了剩下 190 段可靠。

**产物**：`m1/audit/script-audit.md`，逐段一行：

| 章 | 段 id | 页 | 原文摘要 | 结论 | 处理 |
| --- | --- | --- | --- | --- | --- |
| 第六章 | seg_0007 | p9 | 铁笼被鳄鱼啃 | 画面可见 | 保留 |
| 第六章 | seg_0012 | p14 | 哥布林从芦苇窜出 | **两边都没有** | **改写** |

**三种结论**（只允许这三种）
- `画面可见` → 保留
- `小说有但没画`（`fidelity: omitted`）→ 保留，但确认没写在错的页上
- `两边都没有` → **必须改写或删除**

**范围**：`m1/audit/`、必要时改 `m1/v{n}/chNN/work/script.json`。
**不做**：不因为"成片已经出了"就迁就原稿。

**验收**
1. 十章共约 190 段，**每一段都有结论**，无空白行；
2. `两边都没有` 的段落数为 0（全部已改写或删除）；
3. 改稿后每章密度仍在 45–90 字/页（第 15 条）；
4. 审计表里每行的"原文摘要"必须能在对应 `script.json` 里搜到。

---

### P0-04 重出受影响的成片

**目标**：改稿后重跑 S6–S9，产出内容合格版。

**做法**
```bash
for ch in ch01 ch02 ...; do
  python -m panelcast m1 run --work ... --out ... --skip-panel-gate ...
  python -m panelcast m1 verify --work ... --out ... --name ...
done
```

TTS 是内容寻址缓存，未改的段会自动命中，只重算改动段。

**验收**
1. 十章 15/15；
2. `m1/delivery.md` 新增两列：`内容审计`（`已审计/未审计`）、`底稿`（`novel_ref.json` 的 sha256 前 8 位）；
3. 每章 `run_report.json` 的 `total_duration` 与 `delivery.md` 对得上；
4. 抽查 3 章抽 3 帧，字幕/标签/画面与改动前一致（除改写的段落）。

---

### P0-06 正式出片门禁

**目标**：正式出片不能绕过来源校验；预览有明确的 draft 通道。

**设计**

```bash
# 正式：走 S5a 五步链，不过就退出码 3
python -m panelcast m1 run --work ... --out ...

# 预览：显式声明草稿，产物文件名带 .draft
python -m panelcast m1 run --work ... --out ... --draft
```

**关键约束**：`--draft` 产物文件名必须是 `<章名>.draft.mp4`，
且 `run_report.json` 里 `"draft": true`、`"content_audited": false`。
**draft 不得改名冒充正式交付。**

**五步链里的第 5 步（审核报告）单独说清楚**：`m1 run` 正式路径必须读
`script-audit.json`，并校验四样东西对得上当前文件：
`script_sha256`、`novel_ref_sha256`、`script_schema`、逐段 `text_sha256`。
只要有一段文字改过而审计没重做，就判定失效 → 拒绝出片。
这一条比前四步更硬：前四步错了是"引错来源"，这一步漏了是"没人读过就发片"。

**审核报告只由审核流程生成**（P0-C 第二条约束）：
`script-audit.json` 的唯一写入者是审核入口，`m1 run`、迁移脚本、普通编辑一律不得写它。
讲稿改动后审核流程**不得继承旧结论**，必须重新逐段判。

**范围**：`panelcast/__main__.py`、`panelcast/verify.py`（报告字段）、测试。
**不做**：不移除 `--skip-panel-gate`（那是竖版合法路径，与内容门禁是两件事）。

**验收**
1. 缺 `novel_ref.json` 时正式 `run` 退出码 3，且**不产生 mp4**；
2. `--draft` 能出片，文件名含 `.draft`，报告里 `draft: true`；
3. 把 draft 产物手工改名为正式名后，`m1 verify` 能识别并报错（靠报告字段，不靠文件名）；
4. 缺 `script-audit.json` 时正式 `run` 退出码 3；
5. 改一句台词后不重做审计，正式 `run` 退出码 3 并指出失效段 id；
6. `script_schema` 与讲稿实际 schema 不一致时退出码 3；
7. `migration-state.json` 为 `migrated_unreviewed` 时正式 `run` 退出码 3；
8. 新增测试 ≥12 个（含第 4–7 条四个用例）。

---

### P0-10 `m1 verify --visual` 视觉验收

**目标**：把"画面合格"从纯人工抽检变成可复现的自动检查。

**为什么它是 P0**：现有 15 条验收全是**技术指标**（分辨率、帧率、时长、音轨、字幕时序），
没有一条看画面本身。结果就是：字幕带遮住了漫画关键格、某页渲染成空白、
章节横幅被裁掉一半——**15/15 照样全绿**。这是当前最大的验收盲区。

**三层结构（不要做成"抽六帧看看"）**

| 层次 | 查什么 | 具体检查 |
| --- | --- | --- |
| **L1 渲染完整性** | 画面有没有东西 | ① 首尾帧非黑非纯色 ② 空白页（灰度均值 > 250）③ 黑屏（< 5）④ 冻结帧（相邻帧直方图差 = 0 且跨切页点）⑤ 缺失图片（漫画区边缘密度 = 0） |
| **L2 视觉布局** | 画面摆得对不对 | ⑥ 字幕带遮挡（字幕带以上被图片侵入）⑦ 画面越界（白边宽 > 阈值 = 页图被裁）⑧ 比例异常（漫画区宽高比 ≠ 源页）⑨ 章节标签可见（右上角有文字像素） |
| **L3 时间同步** | 画面换得对不对 | ⑩ **每个切页点前后各一帧**（`cut±0.1s`）⑪ 最长停留页首尾各一帧 ⑫ 每个字幕段抽一时刻比对 `.ass` |

**L3 的 ⑩ 不能抽样**：249 次切页就是 249 个必查点。随机抽帧恰好漏掉切换瞬间的
闪黑、滞后、两页叠一起——而这类错误在随机帧上看不出来。

**命令**

```bash
python -m panelcast m1 verify --work ... --visual --cuts all
```

`--cuts all` 表示全查切页点；`--cuts sample` 只抽样，**仅允许用于开发调试，
不得用于正式验收**（报告里要标 `cuts_mode`）。

**硬边界：机器只能标记疑似，不能判内容正确**

- `--visual` 的 PASS 只表示"这帧渲染正常"，**不表示"这页讲对了"**。
- 剧情正确性永远归 §9.4 人工 + `script-audit.json`。
- 所以 `--visual` 通过**不得**作为 `content_reviewed` / `approved` 的置位依据。
- 反过来 FAIL 可以直接阻断出片——画面坏了没有争议。

**明确不做**：不判断"画面内容是否对得上旁白"——那需要视觉模型，属 S3/V2。

**范围**：`panelcast/verify.py` + 新增 `tests/test_verify_visual.py`。
**验收**
1. 十章各跑一遍，输出逐帧/逐切页点结论表；
2. **故障注入**：人为制造 5 类故障（空白页、黑屏、字幕遮挡、画面越界、切页未生效），
   `--visual` 必须全部报出并定位到**具体页/具体切页点**；
3. 正常帧不得误报（十张干净帧跑出 0 个 FAIL）；
4. `--cuts sample` 的报告里 `cuts_mode` 字段为 `sample`，正式验收脚本拒绝接受该报告；
5. 新增测试 ≥12 个（L1–L3 各判据 + 故障注入 + 不误报）；
6. 全量 250+ 通过。

---

### P0-11 `script.json` v1 → v2 Schema 迁移

**目标**：十章脚本迁到 v2，让"每句话从哪来"成为结构化字段而不是注释。

**前置**：P0-02（十章 `novel_ref.json` 齐备）。没有 beat 就没有合法的 `source_refs` 来源。

**做法**（严格按主规范 §4.3.4 五步，不得跳步）
1. 读 v1，按 `chapter_uid` 补章身份（依赖 P0-08）；
2. 逐段补 `source_refs`，**只允许两种来源**：`novel_ref.json` 里的 beat id，或人工新标的
   `page_visual` / `setting`；
3. 计算每段 `text_sha256`（与 `script-audit.json` 同口径）；
4. 写 v2，保留 v1 为 `script.v1.json.bak`；
5. **核对：任何一段的 `source_refs` 都不得由脚本自动推断**。

**第 5 步是硬约束**：迁移脚本可以把 beat 列出来给人挑，但**不能**用"这段文字和这个 beat
关键词重合度最高"之类的规则自动填。一旦自动填，`source_refs` 就变成了伪证——
它看起来有来源，实际是机器猜的。这正是第六章"哥布林绑票"那类错误的温床。

**三态约束（不可跳级）**

迁移后每章落一个状态，存 `work/migration-state.json`：

| 状态 | 含义 | 允许做什么 | 谁能置位 |
| --- | --- | --- | --- |
| `migrated_unreviewed` | 结构转换完成，内容未审 | 可跑结构校验；**禁止正式出片** | 迁移脚本自动 |
| `content_reviewed` | 人工完成来源与剧情审核 | 可跑 `--draft` 预览 | **只能由审核流程**（需 `reviewed_by`） |
| `approved` | 满足正式出片全部条件 | 允许正式出片 | 审核流程 + 门禁全过 |

**迁移脚本跑完只能落到 `migrated_unreviewed`。**
"JSON 转换无报错" ≠ "内容审过"，不许直接进第二态。

**范围**：新增 `tools/migrate_script_v2.py`、十章 `script.json`、`tests/test_migrate_script.py`。
**不做**：不在迁移中改台词内容。改台词是 P0-03 的事，两件事分开做才不会互相污染。

**验收**
1. 十章全部通过 v2 schema 校验；
2. `script.v1.json.bak` 与原文件逐字节一致（可回滚）；
3. 抽查任意 10 段，`source_refs` 指向的 beat 确实在 `novel_ref.json` 里存在且页对得上；
4. 迁移脚本的 `--auto` 模式**不存在**（或存在但会直接报错退出）；
5. 迁移后十章 `migration-state.json` **全部**为 `migrated_unreviewed`；
6. 有测试证明：`migrated_unreviewed` 状态下 `m1 run` 正式路径退出码 3；
7. 新增测试 ≥10 个。

---

## 2.5 P0-RELEASE-GATE 正式内容生产资格

> **这不是第十二个开发任务**，是 P0 全部做完时的**放行条件**。
> 九条必须同时满足，缺一条就是"不具备量产资格"。
> 对应主规范 §9.6。

**产物**：`m1/audit/p0-release-gate.md`，逐条写实测值 + 证据路径，不写"应该可以"。

| # | 条件 | 验收命令 / 方法 | 判据 |
| --- | --- | --- | --- |
| 1 | 十章 100% 内容审计 | 遍历十章 `work/script-audit.json` | 全部 `review_status=approved`，`audited_segments` 段数 == 讲稿段数 |
| 2 | 新旧 Schema 迁移通过 | `python -m panelcast m1 script --validate --schema v2` ×10 | 十章全过；`script.v1.json.bak` 存在且可回滚 |
| 3 | 小说来源哈希门禁通过 | `python -m panelcast m1 novel --check` ×10 | 十章全过（含 `text_sha256` 第 2 步） |
| 4 | 审核报告与讲稿版本一致 | 重算三层哈希比对 | `script_sha256` / `novel_ref_sha256` / 逐段 `text_sha256` 全对得上 |
| 5 | 出片门禁无法绕过审核 | 跑 `tests/test_gate_bypass.py` | 缺报告、改台词不重审、`migrated_unreviewed` 三种情况均退出码 3 |
| 6 | 竖版完整页面路径正常 | 十章 `visual_mode=page` 全链路出片 | 十章 15/15，且 `run_report.json` 里无 `skip_panel_gate` 告警 |
| 7 | 横版未被设为竖版依赖 | 检查竖版路径的文件读取 | 竖版出片不读 `*.panels.json`、不读 `page_*.profile.json` |
| 8 | 视觉验收能抓注入故障 | 注入 5 类故障后跑 `--visual` | 5/5 全部报出并定位到具体页/切页点 |
| 9 | 全量测试通过并如实记录 | `python -m unittest discover -s tests` | 报告写 `Ran N / OK (skipped=M)`，**跳过项逐条列原因** |

**第 8 条是唯一容易被做成走过场的一条**。做法固定：

1. 复制一章成片到临时目录；
2. 用 ffmpeg 注入 5 类故障：① 中间一页替换为纯白 ② 切页点前插 2 帧全黑
   ③ 把字幕带下移 200px 压住画面 ④ 页图放大 1.2 倍造成越界 ⑤ 删掉一次切页（两页合并）；
3. 对每个故障副本跑 `--visual`，确认**报出的类别和位置都对**；
4. 对未注入的干净副本跑一遍，确认 **0 FAIL**（不误报）。

**放行结论只有两种**：`RELEASED` / `BLOCKED`（附未过条目编号）。
不许出现"基本可以"。

---

## 3. 交付格式（每个任务）

```markdown
# P0-XX 任务名称

## 当前事实（已核实）
## 范围 / 文件白名单
## 明确不做
## 验收标准（逐条，附命令）
## 执行结果
- commands:
- tests: total / passed / failed / skipped
- artifacts:
- hashes:
- manual_review:
- blocked:
## 未解决问题
```

**禁止**：
- 把 `--check` 通过写成"内容合格"（它只证明结构完整）；
- 把未跑的测试写成通过；
- 把 P0 说完成但 `delivery.md` 里还有"未审计"的章。
