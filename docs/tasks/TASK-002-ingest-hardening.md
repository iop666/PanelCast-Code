# TASK-002：摄取层硬化（空摄取守卫 + 干净错误出口）

- 基线：`3c722ff`（Phase 0 baseline，30/30 测试通过）
- 前置阅读：`README.md`、`docs/ADR-001-source-ingestion.md`、`panelcast/__main__.py`
- 性质：**缺陷修复 + 小范围硬化**，不是重构，不是新功能

---

## 0. 执行纪律（先读这段）

1. **不要探索仓库**。只需读上面列出的 3 个文件和 `panelcast/epub_ingest.py`、
   `panelcast/mobi_ingest.py`、`tests/test_cli.py`。读别的文件属于超范围。
2. **不要重新推演 EPUB / MOBI 格式**。现有解析器已经在真实素材上跑通
   （6 章 / 169 页），格式问题不存在，不要再研究 PDB 记录结构。
3. **不要读 `.local/` 下的图片**，不要逐张查看漫画页。
4. **不要引入任何第三方依赖**。只允许 Python 标准库。
5. **不要改动 `__main__.py` 的整体结构**（staging / 提交 / `finally` 清理保持原样），
   只做本任务书列出的最小改动。
6. **改动文件上限 7 个，且只允许这 7 个**：`panelcast/errors.py`(新增)、
   `panelcast/epub_ingest.py`、`panelcast/mobi_ingest.py`、`panelcast/__main__.py`、
   `tests/test_cli.py`、`README.md`、`docs/ADR-001-source-ingestion.md`。
   其余文件一律不许动。
7. 完成后**不要**自行 commit，也不要 `git add`。由审查方验收后再提交。

---

## 1. 问题陈述

当前摄取层有两个真实缺陷，测试没有覆盖：

**缺陷 A（严重）——静默空摄取。**
`extract_chapters()` 只认 `chapter00.xhtml` ~ `chapter05.xhtml`。若传入一本
章节 id 不同的 EPUB，`wanted` 为空 → 返回 `[]`；`scan_jpeg_pages()` 若在 MOBI 中
扫不到 JPEG 同样返回 `[]`。两种情况 CLI **都退出码 0**，写出一份
`chapter_count: 0` / `page_count: 0` 的"成功" manifest。
下游会把这份空数据当成有效输入，且没有任何报错。

**缺陷 B——坏输入以 traceback 退出。**
传入损坏的 EPUB（非 zip）或损坏的 MOBI（PDB 头非法）时，异常直接冒泡，
用户看到的是 Python traceback 而不是一行错误信息。

---

## 2. 要实现的改动

### 2.1 新增 `panelcast/errors.py`

```python
class IngestError(Exception):
    """Input file is structurally valid enough to open but yields no usable data."""
```

只放这一个类，不要加别的。

### 2.2 空摄取守卫

- `epub_ingest.extract_chapters()`：循环结束后若 `chapters` 为空，
  抛 `IngestError`。消息必须包含：期望的章节 id 列表（`chapter00.xhtml`~`chapter05.xhtml`）
  和 EPUB 文件名。
- `mobi_ingest.ingest_mobi()`：`scan_jpeg_pages()` 返回空列表时，**在创建
  `pages/` 目录和写 `pages.json` 之前**抛 `IngestError`。消息包含 MOBI 文件名。
- 守卫必须发生在**写盘之前**，保证 staging 目录里不会留下半成品。

### 2.3 CLI 干净错误出口

在 `cmd_ingest` 的 staging 区块外加一层 `try/except`，捕获
`(IngestError, zipfile.BadZipFile, ValueError, KeyError, ElementTree.ParseError, OSError)`：

- 向 **stderr** 打印单行：`error: <原因>`（不要 traceback，不要多行堆栈）
- 返回退出码 **4**
- `finally` 中的 staging 清理必须保留（失败不得残留 `.panelcast-stage-*`）
- 不得捕获 `SystemExit` / `KeyboardInterrupt`

### 2.4 退出码语义（写进 README 和 ADR）

| 码 | 含义 |
| --- | --- |
| 0 | 成功 |
| 1 | 没找到任何 `.epub` / `.mobi` 输入 |
| 2 | 输入组合被拒（同类型多于一个；也包含 argparse 用法错误） |
| 3 | 输入存在但产出 0 条记录（空摄取） |
| 4 | 输入无法解析 / IO 失败 |

注意：**3 和 4 必须区分开**。3 是"文件能打开但没内容"，4 是"文件根本读不了"。
这是本任务的重点，不要合并成一个码。

---

## 3. 测试要求

### 3.1 必须新增（名字照抄）

在 `tests/test_cli.py` 中新增，全部使用合成 fixture，**不依赖真实素材**：

| 测试名 | 断言 |
| --- | --- |
| `test_epub_without_known_chapters_exits_3` | 构造 spine 里没有 `chapter00~05` 的合法 EPUB → 退出码 3，stderr 含 `error:`，输出目录**没有** `source_manifest.json` |
| `test_mobi_without_jpeg_pages_exits_3` | 构造 PDB 头合法但 record 内无 JPEG 的 MOBI → 退出码 3，无 manifest |
| `test_empty_ingestion_keeps_previous_output` | 先跑成功的一对输入，再跑"空 EPUB" → 退出码 3，且旧 manifest / chapters.json / pages/*.jpg **逐字节不变** |
| `test_corrupt_epub_reports_clean_error` | 非 zip 的 `.epub` → 退出码 4，stderr 含 `error:` 且**不含 `Traceback`** |
| `test_corrupt_mobi_reports_clean_error` | 8 字节垃圾 `.mobi` → 退出码 4，stderr 含 `error:` 且**不含 `Traceback`** |
| `test_failure_leaves_no_staging_residue` | 上述任一失败路径后，`out.glob(".panelcast-stage-*")` 为空 |

### 3.2 必须修改（只改这两处断言）

现有两个测试把"抛异常"固化成了预期行为，与新语义冲突：

- `test_failed_run_preserves_previous_output`：`assertRaises(ValueError)` → 改为断言退出码 4
- `test_failed_epub_only_run_keeps_everything`：`assertRaises(zipfile.BadZipFile)` → 改为断言退出码 4

**这两个测试里所有"旧输出逐字节保留"的断言必须原样保留**，只换掉异常断言那一行。
除这两处外，**不得修改、删除、放宽任何现有测试**。

---

## 4. 明确不做（超范围）

- 页面角色分类（封面 / 彩页 / 正文 / 版权页）
- OCR、分格、切图、AI、TTS、视频渲染
- 提交阶段的原子性改造（`rmtree` + `os.replace` 之间崩溃会半提交）
  —— **本次只在 ADR 里如实写成已知限制，不修**
- 多 EPUB / 多 MOBI 支持
- 性能优化、日志框架、配置文件

---

## 5. 验收标准（审查方会逐条独立复验）

1. `python -m unittest discover -s tests -v` 全绿，用例数 ≥ 36（原 30 + 新增 6）。
2. 真实素材仍正常：`python -m panelcast ingest "この素晴らしい世界に祝福を！" -o <tmp>`
   → 6 章、86062 字、169 页。
3. 先跑真实素材成功，再喂损坏 EPUB → 退出码 4，输出目录逐字节不变。
4. 空 EPUB → 退出码 3，**不是** 4，也**不是** 0。
5. 任何失败路径的 stderr 里都不出现 `Traceback`。
6. 失败后输出目录内无 `.panelcast-stage-*` 残留。
7. `git diff` 只触及第 0 节允许的文件；`git diff` 中不出现对现有测试断言的
   削弱（除 3.2 指定的两行）。
8. README 与 ADR 都有退出码表，且 ADR 写明了非原子提交这一已知限制。

---

## 6. 交付报告格式

完成后用不超过 15 行汇报，只写：

```
改动文件：<逐个列出>
新增测试：<数量>，全量用例数：<n>
自测：unittest 全绿 / 真实素材 6章169页 / 空摄取=3 / 损坏输入=4
未做（如有）：
不确定点（如有）：
```

不要粘贴大段代码，不要复述本任务书。
