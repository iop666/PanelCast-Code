# M1：最小闭环（分格 → 人工修正 → 讲稿 → TTS → MP4）

- 状态：待执行
- 前置：M0 已验收（`3350718`）、TASK-002 已冻结（`489856f`）
- 性质：**第一条端到端闭环**。目标是"能跑出一个真能看的样片"，不是"功能齐全"

---

## 0. 执行纪律

1. **先跑 S0 能力探测，探测不过就停**。不要为了"让流程跑完"而造假数据
   （不生成静音冒充配音、不跳过页面、不伪造时长）。
2. **不要探索仓库**。只读 `panelcast/` 现有 6 个模块、`docs/ADR-001`、本文件。
3. **不要重新推演 EPUB/MOBI 格式**，摄取层已冻结，不许改。
4. **不新增 Python 第三方依赖**（详见第 2 节，这是硬约束）。
5. **不要自行安装系统软件**（ffmpeg）。缺了就停，报告，等人装。
6. 允许改/新增的文件：
   - 新增 `panelcast/panels.py`、`panelcast/tts.py`、`panelcast/timeline.py`、
     `panelcast/render.py`、`panelcast/editor/`（`server.py` + `static/index.html`）
   - 修改 `panelcast/__main__.py`（只加 `m1` 子命令，不动 `ingest`）
   - 新增 `tests/test_panels.py`、`tests/test_timeline.py`、`tests/test_render.py`、
     `tests/test_tts.py`
   - 新增 `docs/ADR-002-m1-render-stack.md`
   - 修改 `README.md`
   - **`panelcast/epub_ingest.py`、`mobi_ingest.py`、`manifest.py`、`jpeg.py`、
     `errors.py` 一律不许动**
7. 完成后**不要 commit、不要 git add**。

---

## 1. 范围

### 1.1 M1 只做 8 页样片

用 M0 同一批页：`m0/pages/page_0005.jpg` ~ `page_0012.jpg`，产出 **2–3 分钟** MP4。

不扩到整章 169 页。**先证明闭环成立，再谈覆盖长度**（扩章属 M2）。

### 1.2 一句话目标

```
一张张漫画页 + 一份讲稿  →  一条带旁白的 1080p MP4，且改一句稿只重算受影响的部分
```

---

## 2. 已探明的环境事实（别再重复探测，直接按此设计）

| 能力 | 实测结果 | 结论 |
| --- | --- | --- |
| `ffmpeg` | **已存在但不在 PATH**：`D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\`（含 `ffmpeg.exe` / `ffprobe.exe` / libx264） | 按 2.3 顺序解析，**不要装** |
| `Pillow` / `numpy` | 未安装 | **不装**，见 2.1 |
| 中文 TTS | SAPI5：`Microsoft Huihui Desktop`；OneCore：Kangkang / Yaoyao | 离线可用 |
| Python | 3.13，pip 可用 | 但本任务**不新增依赖** |

### 2.3 ffmpeg 解析顺序（必须实现，不要硬编码）

1. 环境变量 `PANELCAST_FFMPEG`（指向 ffmpeg 可执行文件或 bin 目录）
2. `shutil.which("ffmpeg")`
3. 已知路径：`D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe`

找到后必须**同时**定位同目录的 `ffprobe`（验收要用它读成片参数）。
实际使用的路径写进 `capability_report.md` 和 `timeline.json`。

**禁止**为了跑通而去安装/下载 ffmpeg——本机已经有了。

### 2.1 为什么分格不用 Pillow

图像处理通常要 Pillow，但本项目 ADR-001 立了"仅标准库"的规矩。M1 沿用：

```
ffmpeg -i page.jpg -pix_fmt gray -f rawvideo -   →  纯字节灰度图
```

拿到的字节直接做行/列投影分析，纯 Python 即可，656×1009 也就 66 万像素。
**反正 ffmpeg 是硬依赖，顺手拿它当解码器，比引一个图像库更干净。**

> 若后续证明纯 Python 投影慢到不可用（单页 > 2 秒），再单独提 Pillow 的 ADR，
> 本任务不许擅自引入。

### 2.2 TTS 后端优先级

按顺序探测，用第一个可用的，并把实际用的后端与音色写进 `timeline.json`：

1. `edge-tts`（若已装且网络通）——音质最好
2. Windows SAPI5 + `Microsoft Huihui Desktop`——离线，机械音，可接受
3. 都不可用 → **停止并报告**，不要生成无声视频

---

## 3. 目录与数据模型

```
m1/
  work/
    pages/                     # 输入页（从 m0/pages 复制，只读）
    panels/
      page_0005.candidates.json   # 自动候选，只写一次，之后不可变
      page_0005.panels.json       # 人工确认结果，可反复编辑
    audio/
      seg_0005_1.wav              # 按段缓存
    cache/
      tts_index.json              # (text,voice,params) → 音频文件名 + 时长
    timeline.json
  out/
    sample.mp4
    sample.srt
```

### 3.1 `*.panels.json`

```json
{
  "page": "page_0005",
  "width": 672,
  "height": 984,
  "reading_direction": "rtl",
  "source": "auto|manual",
  "panels": [
    {"id": "p1", "order": 1, "x": 0, "y": 0, "w": 672, "h": 620, "confidence": 0.93, "locked": false}
  ]
}
```

- `order` 从 1 起，**RTL 阅读顺序由人确认**，算法只能给建议
- `locked: true` 的框在重新自动分格时不得被覆盖

### 3.2 `timeline.json`

```json
{
  "tts_backend": "sapi5:Microsoft Huihui Desktop",
  "total_duration": 148.3,
  "segments": [
    {"id": "seg_0001", "text": "...", "audio": "seg_0001.wav", "duration": 12.4,
     "start": 0.0, "end": 12.4, "pages": ["page_0005", "page_0006"]}
  ]
}
```

**时间轴一律由真实音频时长累加派生，禁止按字数估算。**

---

## 4. S0 能力探测（硬门禁，30 秒）

产出 `m1/capability_report.md`，逐项写实测值：

| 项 | 检查方式 | 缺失时 |
| --- | --- | --- |
| ffmpeg | 按 2.3 顺序解析，`-version` 能跑，且 `-encoders` 里有 `libx264` | **立即停止**，报告实际试过的路径 |
| ffprobe | 同目录存在，`-version` 能跑 | 停止 |
| 灰度解码 | 对 `page_0005.jpg` 走 2.1 的管线，拿到字节数 = w×h | 停止 |
| TTS | 按 2.2 顺序探测，合成一句"测试"并确认 WAV 时长 > 0 | 停止 |
| 写权限 | `m1/work`、`m1/out` 可写 | 停止 |

**S0 不过就不要往下写代码。** 先报告，等人处理。写一半再发现没 ffmpeg 是纯浪费。

---

## 5. S1 分格器（`panelcast/panels.py`）

### 5.1 目标

对**带边框**的格子给出候选框；无边框/跨格/贴边的**允许失败**，但必须标低置信度让人改。

M0 实测：本批 8 页里 `page_0007`、`page_0009`、`page_0010` 是典型带边框页；
`page_0005`（扉页全幅）、`page_0006`（上方无边框大格）属已知困难页。

### 5.2 建议算法（可实现，不必创新）

1. 灰度 → 二值化（阈值可用固定值 + Otsu 二选一，自己测哪个稳）
2. 找**长直线**：连续暗像素行/列，长度 > 页面宽/高的 30% 视为分隔线
3. 由分隔线围出的矩形即候选格；去掉面积 < 页面 1% 的碎块
4. 合并被误切的相邻格（若中间线长度明显短于两侧格宽）
5. 每格给 `confidence`：边框四边齐全 → 高；缺边/贴页边 → 低
6. **按 RTL 排 `order`**：先右后左、先上后下

### 5.3 硬要求

- 单页处理 < 2 秒
- 同一页重复跑，输出**逐字节一致**（确定性）
- 候选写 `*.candidates.json`，**永不覆盖**已存在的文件
- 边界情况必须不崩：纯白页、纯黑页、单格满页、0 格 → 返回空列表 + 警告，不许抛异常

---

## 6. S2 人工修正编辑器（`panelcast/editor/`）

### 6.1 形态

本地 HTTP 服务（**标准库 `http.server`**，不用 Flask），浏览器打开一个页面。
启动：`python -m panelcast m1 edit --work m1/work`

### 6.2 必须有的功能（多一个都不要做）

1. 左侧页面列表，显示每页"已确认/未确认"
2. 中间显示整页图，叠加候选框；框可**拖动**、**拖角缩放**、**删除**
3. 空白处拖拽**新建**框
4. 每框显示序号，可改阅读顺序（上下移或直接输入）
5. **RTL 提示**：序号 1 在右上，视觉上要能看出阅读方向
6. 保存 → 写 `*.panels.json`，`source` 置 `manual`
7. 键盘：`←/→` 切页，`S` 保存，`D` 删除选中框
8. 顶部显示本页候选数与人工修改数

### 6.3 硬要求

- 不引入任何前端构建工具、不引 CDN（离线可用）
- 只读写 `m1/work/` 下的文件，**不得访问其它路径**（路径穿越要挡）
- 保存是原子写（temp + replace），不能写坏已有 JSON

---

## 7. S3 TTS（`panelcast/tts.py`）

- 输入：讲稿段文本；输出：WAV + **真实时长**（读 WAV 头，不靠估算）
- 缓存键：`sha256(text + voice + rate + backend)`；命中直接复用，不重复合成
- `cache/tts_index.json` 记录 键 → 文件名 + 时长 + 合成时间
- 同段文本改了 → 只重算这一段
- 合成失败要**报错退出**，不许写 0 字节文件充数

---

## 8. S4 时间轴（`panelcast/timeline.py`）

- 按段顺序累加真实时长 → `start` / `end`
- 段 → 页面映射：一段可覆盖 1–3 页，按 `panels.json` 的 `order` 均分该段时长
- 派生 SRT：**一段一条字幕**，起止即段的起止（M1 不做词级对齐）
- 总时长 = 最后一段的 `end`；与音频实际总长误差必须 < 0.05 秒

---

## 9. S5 渲染（`panelcast/render.py`）

- 单条 ffmpeg 命令或 concat demuxer，**硬切，无转场，无推镜**
- 画布：1920×1080，白底，页面等比缩放居中（letterbox），**不裁切**
- 帧率 30，`-pix_fmt yuv420p`，`libx264`，`-crf 20`
- 音频：各段 WAV 拼接后混入，采样率统一 44100
- 时长以音频为准：视频流用 `-shortest` 或显式 `-t`
- 产物：`m1/out/sample.mp4`、`m1/out/sample.srt`

---

## 10. S6 一键闭环

```bash
python -m panelcast m1 run --work m1/work --out m1/out
```

行为：检查所有页已人工确认（有 `*.panels.json`）→ 有未确认页则**列出并退出码 3**，
不自动用候选凑数 → 全部确认后依次跑 S3/S4/S5。

---

## 11. 验收标准（审查方逐条独立复验）

1. `python -m unittest discover -s tests -v` 全绿，用例数 ≥ 45（现 37 + 新增 ≥ 8）。
2. 摄取层未被改动：`git diff` 中 `epub_ingest.py` / `mobi_ingest.py` / `manifest.py` /
   `jpeg.py` / `errors.py` **零改动**，`ingest` 的 37 个旧测试全部照旧通过。
3. 分格确定性：同一页连跑 3 次，`candidates.json` 逐字节一致。
4. 分格不崩：纯白图、纯黑图、单格满页、无格图四种输入均返回空/单框且不抛异常。
5. 编辑器能完成一次真实修正并落盘，`source` 变 `manual`，且路径穿越请求被拒（404/403）。
6. **缓存生效**：改一段讲稿后重跑，只有该段音频 mtime 变化，其余段音频字节不变。
7. 成片时长与 `timeline.json` 的 `total_duration` 误差 < 0.2 秒。
8. 成片可播：`ffprobe` 读出 1920×1080 / 30fps / 有音轨 / 时长 2–3 分钟。
9. 预览与成片一致：随机取 `timeline.json` 中某段的 `start` 时刻抽帧，画面与该段
   `pages` 首页一致（人工看）。
10. 无静默降级：TTS 失败、ffmpeg 失败、页面缺失，都必须非零退出并给出一行 `error:`。

---

## 12. 明确不做（超范围，做了算错）

- 整章 169 页批量、批量队列、多项目管理
- 词级字幕对齐、字幕烧进画面（只出 SRT）
- 转场、运镜、Ken Burns、BGM、音效
- 多音色/角色配音、声音克隆
- Web 端预览播放器、多人协作
- 重写摄取层、改 manifest schema
- 引入 Pillow / numpy / Flask / React / 任何 CDN

---

## 13. 交付格式

```
capability: ffmpeg=<版本> tts=<后端:音色> decode=ok
files: <逐个列出新增/修改文件>
tests: <总数> 通过
segments: <n> 段，总时长 <s> 秒
video: <w>x<h> <fps>fps <时长>s <大小>MB
manual_pages: <已人工确认页数>/8
blocked: <无 / 具体卡点>
```

不要贴代码，不要复述本文件。若某阶段失败，**如实报告停在哪一步**，不要用假数据凑一个能播的片子。
