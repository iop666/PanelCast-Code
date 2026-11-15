# ADR-001: 源素材摄取方案（EPUB 章节文本 + MOBI 页面图）

- 状态：已采纳（Accepted）
- 日期：2026-11-15
- 背景：PanelCast 需要《この素晴らしい世界に祝福を！》第 1 卷的章节文本与漫画页图片，
  作为后续分镜 / 配音流水线的输入。

## 决策

1. **仅用 Python 标准库**，以 `panelcast` 包 + `python -m panelcast ingest` CLI 实现。
   不引入 Pillow / mobi 解包 / ebooklib 等第三方依赖：本项目长期在无网络依赖约束的
   环境运行，且所需解析（zip、XML、HTML、JPEG 头、PDB 头）标准库均能胜任。

2. **EPUB：按 OPF spine 取固定六章**（`chapter00.xhtml` ~ `chapter05.xhtml`）。
   - 通过 `META-INF/container.xml` → OPF，读取 manifest id→href 映射与 spine 顺序；
   - 输出顺序按 chapter 编号规范化，而非 spine 中可能被排版工具打乱的顺序；
   - 文本用 `html.parser.HTMLParser` 逐 `<p>` 提取，`<br/>` 空段剔除；
   - 每章记录 `id/order/title/text/char_count/source_entry/sha256`。
   - 备选方案（直接按文件名 glob 而不看 spine）被否决：spine 才是 EPUB 的阅读顺序
     权威来源，后续若章节扩展只需扩常量表。

3. **MOBI：按 PDB record 顺序扫描 JPEG**。
   - 校验 PDB type=`BOOK` **且** creator=`MOBI`，读 78 字节头 + record 偏移表；
   - 在每条 record 载荷内以 SOI（FFD8FF）— EOI（FFD9）截取完整 JPEG，
     扫描以单条 record 为边界，不跨 record 重组数据流；
   - 从首个 SOF0/SOF2 标记读 `width/height`，记录 `sha256`；
   - 输出 `page_0001.jpg` 起连续编号；**重复页不删除**，仅以 `duplicate_of`
     指向首个同 hash 页面。重复页是扫描产物的一部分，删除会破坏
     页号 ↔ 实体页的对应关系，且后续流水线可自行按 `duplicate_of` 跳过。

4. **manifest（schema_version 1）**：`source_manifest.json` 记录
   `schema_version`、`extractor_version`、`created_at`、`language`
   （EPUB `dc:language`）、`reading_direction`（漫画固定 `rtl`）、
   `source_files`（role/path/bytes/sha256）及 `chapter_count` /
   `page_count` / `unique_page_count`（对应输入缺席时为 null，仅 EPUB 或
   仅 MOBI 的单类型运行同样产出有效 manifest）。`created_at` 仅首次生成时
   写入、重复运行保留原值；其余内容键排序稳定、输入顺序确定性遍历，
   因此重复运行字节一致，可用 diff 检测漂移。

5. **单次一对输入**：`ingest` 至多接受一个 EPUB 与一个 MOBI；多于一个
   同类型输入立即报错退出（退出码 2），在任何输出写出之前拒绝，
   避免两次摄取互相覆盖 `chapters.json` / `pages.json`。

6. **输出目录与 manifest 严格一致：staging + 提交式替换**。对同一输出目录
   先后处理不同输入时，成功运行后输出目录不得残留上一次的生成物。ingest
   的全部新产物（chapters.json、pages/*.jpg、pages.json、manifest）先写入
   输出目录下的临时 staging 目录（`.panelcast-stage-*`）；解析、提取、构建
   全部成功后才进入提交阶段：删除本次运行缺失输入类型的旧子树、把 staging
   子树整体 `os.replace` 到位（旧页数超出新 manifest 的 `pages/*.jpg` 随之
   清除），最后写 manifest（temp + 原子替换）。因此任一步骤失败（含写失败）
   都不会"先删旧结果再失败"，输出与 manifest 保持为最后一次成功运行的结果；
   启动时还会顺带清掉此前崩溃残留的 staging 目录。清理范围仅限输出目录内
   工具自管的 `epub/` / `mobi/` 子树与 staging 目录，源文件永不被修改或删除。

7. **版权素材与本地产物不入库**：源书目录、`*.epub`/`*.mobi`、`.local/`
   均在 `.gitignore` 中；EPUB 的封面、字体、插图、版权页不进入输出，
   输出仅含章节文本 JSON 与漫画页 JPEG（`text` 与页面图是流水线必需的最小集合）。

8. **测试**：`unittest`（标准库），合成最小 EPUB / PDB / JPEG 样例做确定性断言；
   真实文件（1.epub / 1卷.mobi）存在时附加冒烟测试（六章、169 页），
   缺席时 `skipUnless` 跳过，保证 CI 无版权素材也能跑。输出目录一致性有
   专门回归：pair→仅 EPUB 清理旧 MOBI 子树、pair→仅 MOBI 清理旧 EPUB 子树、
   3 页→1 页只留 1 张 JPEG、失败运行逐字节保留旧输出与 manifest
   （均用小型临时 fixture，不依赖真实素材）。

## 后果

- 正面：零依赖、可审计、除 `created_at` 外幂等、重复页可追溯；成功运行后
  输出目录与 manifest 严格一致，失败保留最后一次有效输出。
- 限制：不做 OCR / 分割 / AI 处理（明确超出本期范围）；JPEG 扫描以单条
  PDB record 载荷为单位，SOI..EOI 不会跨 record 拼接——跨 record 存储
  的 JPEG 变体无法完整取回。当前素材为整页 JPEG 单 record 存储，不受
  影响；若日后需要支持该变体，须先按偏移表把 record 数据流重组后再扫描。
