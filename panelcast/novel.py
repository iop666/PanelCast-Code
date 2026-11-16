"""S5a 底稿对齐：`m1 novel --align` / `--check`（P0-05）。

这个模块存在的理由：十章旧讲稿产出于 S5a 之前，**没有任何一段能追溯到小说段落**，
已经因此出过事实错误（第六章把"铁笼泡湖净化"写成"哥布林绑票 + 竹筏 + 大青蛙吞笼"，
画面里没有、小说里也没有）。所以底稿对齐不能靠记忆，必须是可校验的产物。

两个入口：

    --align  生成 `novel_ref.json` **骨架**。候选段区间只作提示，所有 beat 一律
             `fidelity="unconfirmed"` + `review_status="needs_review"`。
             **不把候选标成已确认**——这是本模块最重要的一条纪律。
    --check  跑 §9.1 的五步门禁链，任一不过退出码 3。

五步门禁（顺序即规范 §9.1 的顺序）：

    1. novel_ref.json 存在
    2. novel_ref.source.text_sha256 == novel_index.json 的 file_sha256
       （并顺带验证磁盘上的 novel.txt 字节确实等于该哈希，防止索引撒谎）
    3. 每段 source_refs 非空且 beat 存在
    4. beat 的页映射合法（页在本章；original 必带 pages）
    5. script-audit.json 有效（三层哈希 + 逐段哈希 + 人签）

第 3 步对 v1 脚本会直接报"需先迁到 v2"——这是**正确行为**：
v1 结构里根本没有 `source_refs` 字段，无从判断来源，不能放行。

哈希口径（最容易实现错的地方）：`source.sha256` 是 **EPUB 原文件**哈希，
`source.text_sha256` 是 **novel.txt 落盘字节**哈希（= `novel_index.json` 的
`file_sha256`，含一个尾部换行）。两者永远不相等，混用会让底稿永远判定失效。
"""

import hashlib
import json
import pathlib

NOVEL_REF_SCHEMA = "novel-ref/v1"
AUDIT_SCHEMA = "script-audit/v1"

#: 一个 beat 最多映射几页。超过这个数说明这一段覆盖太宽，该拆。
MAX_PAGES_PER_BEAT = 3

#: `fidelity` 的合法取值（规范 §3.4）。骨架用的 `unconfirmed` **不在其中**——
#: 它是"还没判"的占位，不是一种判定结果，门禁必须拒绝它。
FIDELITIES = {"drawn", "omitted", "altered", "original"}

#: 全书中出现次数不超过这个值的二元组才算"稀有锚点"。
#: 调高会放进"的一""了。"这类到处都有的组合，候选立刻变成随机数。
RARE_DF = 3

#: 候选最多给几个。
MAX_CANDIDATES = 3


class GateError(RuntimeError):
    """门禁不过。CLI 统一转成退出码 3。"""


def render(text):
    """落盘内容：每段一行 + 一个尾部换行。

    **这是 novel.txt 的唯一写入口。** 哈希与写盘都走这里，
    任何新代码要写 novel.txt 都必须调用它，不得直接 `write_text`——
    一旦出现旁路，`file_sha256` 与磁盘字节就会分叉，第 2 步门禁变成随机通过/失败。
    """
    return text + "\n"


def sha256_file(path):
    """文件字节的 sha256。分块读，避免整本 epub 进内存。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_novel(novel_dir):
    """读 novel.txt + novel_index.json。

    返回 `(lines, index)`。lines 是段落列表（不含尾部空行），段号即下标。
    """
    novel_dir = pathlib.Path(novel_dir)
    txt = novel_dir / "novel.txt"
    idx = novel_dir / "novel_index.json"
    for p in (txt, idx):
        if not p.exists():
            raise GateError(f"error: {p} not found")
    raw = txt.read_text(encoding="utf-8")
    lines = raw.split("\n")
    # render() 保证末尾有一个换行，split 后会多出一个空串，去掉它。
    if lines and lines[-1] == "":
        lines.pop()
    return lines, _read_json(idx)


def novel_chapter_range(index, chapter_key=None):
    """小说章 → (para_from, para_to)。

    `chapter_key` 可给 `ch02` 或 `chapter02.xhtml`。不给则覆盖全书。
    找不到抛 GateError——不静默退化成"全书"，那会让候选区间离谱。
    """
    chapters = index.get("chapters") or []
    if not chapter_key:
        if not chapters:
            raise GateError("error: novel_index.json has no chapters")
        return chapters[0]["para_from"], chapters[-1]["para_to"], chapters
    key = str(chapter_key)
    for c in chapters:
        name = c.get("file", "")
        stem = name.rsplit(".", 1)[0]  # chapter02
        num = stem.replace("chapter", "") if stem.startswith("chapter") else ""
        aliases = {name, stem, f"ch{num}" if num else ""}
        if key in aliases:
            return c["para_from"], c["para_to"], [c]
    raise GateError(
        f"error: novel chapter {key!r} not in novel_index.json; "
        f"have: {[c.get('file') for c in chapters]}"
    )


def _bigrams(text):
    """汉字二元组集合。比整句匹配宽松，比单词匹配稳（中文没有空格分词）。"""
    t = "".join(ch for ch in text if ch.strip())
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else set()


def global_df(lines):
    """全书每段的二元组文档频次。用来判断哪些组合"稀有"（有区分度）。"""
    df = {}
    for line in lines:
        for g in _bigrams(line):
            df[g] = df.get(g, 0) + 1
    return df


def candidate_ranges(seg_text, lines, lo, hi, df=None, top=MAX_CANDIDATES):
    """给一段旁白找候选小说段。

    **只返回候选，不返回结论。** 调用方必须放进 `para_candidates`，
    绝不能写进 `para`——写进 `para` 就等于声称"人已经确认过了"。

    ## 为什么这里只做"稀有词命中"，不做相似度打分

    实测过一版二元组 Jaccard 打分，结论是**不可靠**：旁白是**改写**的，
    不是原文摘抄。例如第一段旁白写"冒险者公会的后院有一口大浴池"，
    小说原文是"这里的入浴费比日本还贵……我将肩膀以下都浸泡在热水浴池里"，
    只有"浴池""热水"两个词重合，任何相似度都会把它排到很后面，
    而排到前面的往往是"从地底""高阶"这种巧合命中的无关段落。

    所以这里退一步，只回答一个能站得住的问题：
    **"这一段旁白里，有哪些全书中很罕见的词？它们在候选范围内出现在哪几段？"**
    命中词一并返回（`anchors`），人一眼就能看出这个候选是靠什么猜的、
    值不值得去看。

    候选是**弱提示**，价值在于把 563 段缩到 3 段，不保证第 1 名是对的。
    """
    if df is None:
        df = global_df(lines)
    rare = {g for g in _bigrams(seg_text) if df.get(g, 0) <= RARE_DF}
    if not rare:
        return []

    scored = []
    for i in range(lo, hi + 1):
        hits = sorted(rare & _bigrams(lines[i]), key=lambda g: df.get(g, 0))
        if not hits:
            continue
        # 越罕见的词权重越高；命中多个词优于只命中一个
        score = sum(1.0 / max(df.get(g, 1), 1) for g in hits)
        scored.append((score, len(hits), i, hits))
    if not scored:
        return []

    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    picked, used = [], []
    for score, nhits, para, hits in scored:
        # 相邻段合并成一个区间，避免把同一句话拆成三条候选
        if any(abs(para - p) <= 1 for p in used):
            continue
        used.append(para)
        picked.append({
            "para_from": para, "para_to": para,
            "score": round(score, 2), "hits": nhits,
            "anchors": hits[:4],
        })
        if len(picked) >= top:
            break
    picked.sort(key=lambda d: d["para_from"])
    return picked


def chapter_pages(work):
    """章级 work 的页列表（`page_0045` 形式）。"""
    p = pathlib.Path(work) / "chapter.json"
    if not p.exists():
        raise GateError(f"error: {p} not found")
    doc = _read_json(p)
    pages = doc.get("pages") or []
    if not pages:
        raise GateError(f"error: {p} has no pages")
    return doc, pages


def script_segments(work):
    """读讲稿，返回 `(doc, [(seg_id, text)], schema)`。

    schema 判定：有 `schema` 字段就用它；没有则是 v1（当前十章都是这样）。
    """
    p = pathlib.Path(work) / "script.json"
    if not p.exists():
        raise GateError(f"error: {p} not found")
    doc = _read_json(p)
    schema = doc.get("schema") or "script/v1"
    segs = [(s.get("id"), s.get("text") or s.get("narration", {}).get("text") or "")
            for s in doc.get("segments") or []]
    return doc, segs, schema


def _segment_source_refs(seg):
    """取一段的来源引用，兼容 v1（无此字段）与 v2（在 narration 下）。"""
    if "source_refs" in seg:
        return seg.get("source_refs") or []
    narration = seg.get("narration")
    if isinstance(narration, dict):
        return narration.get("source_refs") or []
    return []


def build_novel_ref(work, novel_dir, chapter_uid, epub=None, novel_chapter=None,
                    volume=1, order="in_order"):
    """生成 `novel_ref.json` 骨架。

    所有 beat 都是 `fidelity="unconfirmed"` + `review_status="needs_review"`，
    `para` 一律 `null`，候选区间放 `para_candidates`。
    这是**骨架**，不是结论——人要逐 beat 填 `para` 与 `fidelity`。
    """
    lines, index = load_novel(novel_dir)
    lo, hi, chapters = novel_chapter_range(index, novel_chapter)
    chapter_doc, pages = chapter_pages(work)
    _script_doc, segs, _schema = script_segments(work)

    source = {
        "file": None,
        "volume": volume,
        "sha256": None,
        "text_sha256": index.get("file_sha256"),
    }
    if epub:
        ep = pathlib.Path(epub)
        if not ep.exists():
            raise GateError(f"error: epub not found: {ep}")
        source["file"] = ep.name
        source["sha256"] = sha256_file(ep)

    beats = []
    df = global_df(lines)  # 全书算一次，逐段复用
    for i, (seg_id, text) in enumerate(segs, 1):
        cands = candidate_ranges(text, lines, lo, hi, df=df)
        beats.append({
            "id": f"b{i:02d}",
            "segment_id": seg_id,
            "para": None,
            "para_candidates": cands,
            "gist": (text[:40] + "…") if len(text) > 40 else text,
            "pages": [],
            "fidelity": "unconfirmed",
            "review_status": "needs_review",
            "note": "候选仅供参考；para 与 fidelity 必须人工判定",
        })

    doc = {
        "schema": NOVEL_REF_SCHEMA,
        "chapter_uid": chapter_uid,
        "chapter_id": chapter_doc.get("id"),
        "label": chapter_doc.get("label"),
        "pages": [int(p.rsplit("_", 1)[-1]) for p in pages],
        "source": source,
        "novel_chapters": [
            {"index": f"ch{(c.get('file') or '').replace('chapter', '').rsplit('.', 1)[0]}",
             "title": c.get("title"),
             "para_from": c["para_from"], "para_to": c["para_to"],
             "chars": c.get("chars")}
            for c in chapters
        ],
        "order": order,
        "beats": beats,
        "coverage": {
            "novel_chars": sum(c.get("chars") or 0 for c in chapters),
            "script_chars": sum(len(t) for _, t in segs),
            "beats_total": len(beats),
            "by_fidelity": {"drawn": 0, "omitted": 0, "altered": 0,
                            "original": 0, "unconfirmed": len(beats)},
            "note": "骨架：unconfirmed 全部待人工判定",
        },
        "align_meta": {
            "tool": "panelcast.novel --align",
            "segments": len(segs),
            "novel_para_range": [lo, hi],
            "auto_confirmed": False,
        },
    }
    return doc


def write_novel_ref(work, doc):
    path = pathlib.Path(work) / "novel_ref.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path


def _preview(items, n=5):
    """把一长串 id 压成"前几个 … 共 N 个"，避免门禁输出刷屏。"""
    items = list(items)
    head = "、".join(str(x) for x in items[:n])
    return head + (f" … 共 {len(items)} 个" if len(items) > n else "")


def check(work, novel_dir):
    """五步门禁链。返回 `(ok, problems)`，problems 是 `[(step, msg)]`。

    不抛异常——调用方要能把全部问题一次列出来，而不是修一个跑一次。
    """
    work = pathlib.Path(work)
    novel_dir = pathlib.Path(novel_dir)
    problems = []

    # ---- 第 1 步：底稿存在 ----
    ref_path = work / "novel_ref.json"
    if not ref_path.exists():
        return False, [(1, f"novel_ref.json 不存在（{ref_path}）；先跑 --align")]
    ref = _read_json(ref_path)

    # ---- 第 2 步：纯文本哈希一致 ----
    try:
        _lines, index = load_novel(novel_dir)
    except GateError as exc:
        problems.append((2, str(exc)))
        index = {}
    want = (ref.get("source") or {}).get("text_sha256")
    have = index.get("file_sha256")
    if not want:
        problems.append((2, "novel_ref.source.text_sha256 缺失"))
    elif want != have:
        problems.append(
            (2, f"底稿失效：novel_ref.source.text_sha256={want[:12]}… "
                f"!= novel_index.file_sha256={str(have)[:12]}…"))
    # 顺带验证磁盘字节：索引可能过期，不能只信索引
    txt = novel_dir / "novel.txt"
    if txt.exists() and have:
        disk = hashlib.sha256(txt.read_bytes()).hexdigest()
        if disk != have:
            problems.append(
                (2, f"novel.txt 磁盘字节 {disk[:12]}… 与索引 {have[:12]}… 不符；"
                    f"文本被改过但索引没重算"))

    # ---- 第 3 步：每段来源非空且 beat 存在 ----
    try:
        _doc, segs, schema = script_segments(work)
    except GateError as exc:
        problems.append((3, str(exc)))
        segs, schema = [], "script/v1"
    beat_ids = {b.get("id") for b in ref.get("beats") or []}
    if schema != "script/v2":
        problems.append(
            (3, f"讲稿是 {schema}，没有 source_refs 字段，无法校验来源；"
                f"需先迁到 script/v2（P0-11）"))
    else:
        script_doc = _read_json(work / "script.json")
        for seg in script_doc.get("segments") or []:
            sid = seg.get("id")
            refs = _segment_source_refs(seg)
            if not refs:
                problems.append((3, f"{sid}: source_refs 为空（无来源结论）"))
                continue
            for r in refs:
                bid = r.get("beat") or r.get("id")
                if bid and bid not in beat_ids:
                    problems.append((3, f"{sid}: 引用的 beat {bid} 不在 novel_ref.json"))

    # ---- 第 4 步：页映射合法 ----
    try:
        _cdoc, pages = chapter_pages(work)
    except GateError as exc:
        problems.append((4, str(exc)))
        pages = []
    page_set = set(pages)
    unconfirmed, bad_fidelity, missing_para = [], [], []
    for b in ref.get("beats") or []:
        bid = b.get("id")
        bpages = b.get("pages") or []
        fid = b.get("fidelity")
        if fid not in FIDELITIES:
            bad_fidelity.append(f"{bid}={fid!r}")
        # 候选/骨架不等于结论：没人工确认过的 beat 一律不放行。
        # 这条是 P0-05 验收第 5 条，漏掉它，`--align` 的骨架就能直接过门禁。
        if b.get("review_status") != "confirmed":
            unconfirmed.append(bid)
        # 非 original 的 beat 必须指到具体段落，否则"来源"是空的。
        if fid != "original" and not b.get("para"):
            missing_para.append(bid)
        if fid == "original" and not bpages:
            problems.append((4, f"{bid}: fidelity=original 但 pages 为空"))
        for p in bpages:
            if p not in page_set:
                problems.append((4, f"{bid}: 页 {p} 不在本章"))
    if bad_fidelity:
        problems.append(
            (4, f"fidelity 非法：{_preview(bad_fidelity)}；只能是 "
                f"{'/'.join(sorted(FIDELITIES))}。unconfirmed 是骨架占位，必须人工判定"))
    if missing_para:
        problems.append(
            (4, f"{len(missing_para)} 个非 original 的 beat 没有 para："
                f"{_preview(missing_para)}；没有段落区间就是没有来源"))
    if unconfirmed:
        problems.append(
            (4, f"{len(unconfirmed)} 个 beat 仍是 needs_review：{_preview(unconfirmed)}；"
                f"候选与骨架不等于结论，必须人工确认后才能过门禁"))

    # ---- 第 5 步：审核报告有效 ----
    problems.extend(_check_audit(work, ref_path, ref, segs, schema))

    return not problems, problems


def _check_audit(work, ref_path, ref, segs, schema):
    """第 5 步：`script-audit.json` 三层哈希 + 逐段 + 人签。"""
    out = []
    audit_path = pathlib.Path(work) / "script-audit.json"
    if not audit_path.exists():
        return [(5, "script-audit.json 不存在：内容未经审核，禁止正式出片")]
    audit = _read_json(audit_path)

    if audit.get("schema") != AUDIT_SCHEMA:
        out.append((5, f"审核报告 schema 应为 {AUDIT_SCHEMA}，"
                       f"实为 {audit.get('schema')!r}"))
    if not audit.get("audit_spec_version"):
        out.append((5, "审核报告缺 audit_spec_version（审核标准版本）"))

    script_path = pathlib.Path(work) / "script.json"
    if script_path.exists():
        actual = hashlib.sha256(script_path.read_bytes()).hexdigest()
        if audit.get("script_sha256") != actual:
            out.append((5, f"script_sha256 不符（报告 {str(audit.get('script_sha256'))[:12]}… "
                           f"!= 当前 {actual[:12]}…）：讲稿改过但审计没重做"))
    actual_ref = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    if audit.get("novel_ref_sha256") != actual_ref:
        out.append((5, "novel_ref_sha256 不符：底稿改过但审计没重做"))

    if audit.get("script_schema") != schema:
        out.append((5, f"script_schema 不符：报告写 {audit.get('script_schema')!r}，"
                       f"当前讲稿是 {schema!r}"))

    reviewed_by = str(audit.get("reviewed_by") or "")
    if not reviewed_by.startswith("human:"):
        out.append((5, f"reviewed_by 必须是 human:<name>，实为 {reviewed_by!r}"))

    if audit.get("review_status") != "approved":
        out.append((5, f"review_status={audit.get('review_status')!r}，只有 approved 允许出片"))

    audited = {a.get("segment_id"): a for a in audit.get("audited_segments") or []}
    for sid, text in segs:
        rec = audited.get(sid)
        if not rec:
            out.append((5, f"{sid}: 审核报告未覆盖该段"))
            continue
        want = rec.get("text_sha256")
        have = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if want != have:
            out.append((5, f"{sid}: text_sha256 不符，该段文字在审计后被改过"))
    return out


def format_problems(problems):
    """把 `[(step, msg)]` 渲染成给人看的多行文本。"""
    if not problems:
        return ""
    lines = [f"error: 底稿门禁不过（{len(problems)} 项）："]
    for step, msg in sorted(problems, key=lambda x: x[0]):
        lines.append(f"  [step {step}] {msg}")
    return "\n".join(lines)
