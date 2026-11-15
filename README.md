# PanelCast

PanelCast 把轻小说 / 漫画电子书源文件规整为结构化的「章节文本 + 页面图片」，
供后续的分镜、配音、成片流水线使用。当前阶段只做**源素材摄取（ingest）**。

## 环境要求

- Python 3.11+（仅标准库，无第三方运行时依赖）
- Windows / macOS / Linux 均可

## 使用

```bash
# 安装（可选，提供 panelcast 命令）
pip install .

# 扫描当前目录下的 *.epub / *.mobi（跳过 .local），输出到 .local/source/
panelcast ingest        # 或 python -m panelcast ingest

# 显式指定输入与输出
python -m panelcast ingest "この素晴らしい世界に祝福を！/1.epub" "この素晴らしい世界に祝福を！/1卷.mobi" -o .local/source
```

**单次 ingest 只处理一对输入**：至多一个 EPUB + 一个 MOBI；仅提供其中
一种也可以。传入多于一个同类型文件会直接报错退出（退出码 2），
且不会写出任何文件，避免输出互相覆盖。

**成功运行后，输出目录与 manifest 严格一致**：本次运行缺失的输入类型会
删除其对应子树（如 pair → 仅 EPUB 会移除旧 `mobi/`；仅 MOBI 会移除旧
`epub/`），MOBI 页数减少时也会清除超出当前页数的旧 `pages/*.jpg`。
实现上新产物先写入输出目录下的临时 staging 目录（`.panelcast-stage-*`），
解析、提取、构建全部成功后才在提交阶段整体替换旧子树并写 manifest——
因此任一步骤失败（含写失败）都不会破坏上一次有效输出与 manifest，
失败运行后输出保持为最后一次成功运行的结果。清理只作用于输出目录内
工具自管的 `epub/`、`mobi/` 子树与 staging 目录，源文件（`*.epub` /
`*.mobi`）绝不会被修改或删除。

## 输出结构

```
.local/source/
├── source_manifest.json      # 清单（schema_version 1；除 created_at 外确定可重现）
├── epub/
│   └── chapters.json         # 六章文本记录
└── mobi/
    ├── pages.json            # 页面元数据
    └── pages/
        ├── page_0001.jpg
        ├── ...
        └── page_0169.jpg     # 重复页保留在磁盘，仅用 duplicate_of 标记
```

### source_manifest.json 顶层字段

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 清单结构版本（当前 `1`） |
| `extractor_version` | 提取器版本（panelcast 包版本号） |
| `created_at` | 首次生成时间（UTC ISO-8601）；**重复运行保留原值，不刷新** |
| `language` | EPUB `dc:language`（如 `ja`）；无 EPUB 输入时为 `null` |
| `reading_direction` | 页面阅读方向，漫画固定 `rtl` |
| `source_files` | 输入文件列表，元素含 `role` / `path` / `bytes` / `sha256` |
| `chapter_count` | EPUB 章节数；无 EPUB 输入时为 `null` |
| `page_count` / `unique_page_count` | MOBI 页数 / 去重后页数；无 MOBI 输入时为 `null` |
| `epub` / `mobi` | 各自明细小节（同下表字段）；对应输入缺席时为 `null` |

### EPUB 章节记录字段（chapters.json 数组元素）

| 字段 | 含义 |
| --- | --- |
| `id` | OPF manifest id，如 `chapter00.xhtml` |
| `order` | 章节序号（0 起） |
| `title` | XHTML `<title>` |
| `text` | 提取的正文文本（按 `<p>` 段落拼接，空段剔除） |
| `char_count` | `text` 的字符数 |
| `source_entry` | EPUB 内的 zip 条目路径 |
| `sha256` | 原 XHTML 字节的 SHA-256 |

只从 OPF spine 取 `chapter00.xhtml` ~ `chapter05.xhtml` 六章；封面、版权页、
字体、插图等版权素材不进入输出。

### MOBI 页面记录字段（pages.json 数组元素）

| 字段 | 含义 |
| --- | --- |
| `page` | 页序（1 起，按 PDB record 顺序） |
| `file` | `page_NNNN.jpg` |
| `pdb_record` | 来源 PDB record 序号 |
| `width` / `height` | 从 JPEG SOF 标记读出的宽高 |
| `sha256` | 图像字节 SHA-256 |
| `duplicate_of` | 与之重复的首页文件名；无重复为 `null` |

## 测试

```bash
python -m unittest discover -s tests -v
```

覆盖：EPUB spine/文本/语言解析、合成样例 EPUB、JPEG SOF 宽高解析
（SOF0/SOF2）、PDB 头校验（type=BOOK 且 creator=MOBI）、record 偏移、
重复页标记、manifest 构建（双输入 / 单类型 / created_at 保留）、
CLI 行为（单类型 ingest、多同类型拒绝）、输出目录一致性回归
（pair→仅 EPUB 清理旧 MOBI 子树、pair→仅 MOBI 清理旧 EPUB 子树、
页数减少清除多余 JPEG、失败运行逐字节保留旧输出与 manifest），以及
真实文件冒烟测试（源文件存在时）。

## 文档

- [docs/ADR-001-source-ingestion.md](docs/ADR-001-source-ingestion.md) — 摄取方案决策记录

## 边界

本仓库**不包含** UI、OCR、AI、TTS、视频合成等能力，当前仅实现 `ingest`。
