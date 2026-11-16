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
import re

NOVEL_REF_SCHEMA = "novel-ref/v1"
AUDIT_SCHEMA = "script-audit/v2"

#: 一个 beat 最多映射几页。超过这个数说明这一段覆盖太宽，该拆。
MAX_PAGES_PER_BEAT = 3

#: `fidelity` 的合法取值（规范 §3.4）。骨架用的 `unconfirmed` **不在其中**——
#: 它是"还没判"的占位，不是一种判定结果，门禁必须拒绝它。
FIDELITIES = {"drawn", "omitted", "altered", "original"}

#: `judgement_scope`：声明这份文件里的 `fidelity` 判的是**谁和谁**的关系。
#:
#: `novel_ref.beats[].fidelity` 判「**漫画** vs 小说」——漫画有没有照画小说。
#: `script-audit.audited_segments[].fidelity` 判「**旁白** vs 它的来源」——讲稿有没有讲对。
#:
#: 两层同名不同义。混用的后果是双向的：把"旁白忠于漫画的改编"当成"漫画不忠于小说"
#: 去纠错，或者把"旁白自己编的"当成"漫画改的"放过。所以两边都必须显式声明 scope，
#: 校验器只认与本文件类型匹配的那个值。
SCOPES = {
    "novel_ref": "manga_vs_novel",
    "script_audit": "narration_vs_source",
}

#: 差异的**责任来源**（规范 §4.3.10）。只回答"这个差异是谁造成的"，
#: **不代替来源引用**——标了 manga 仍然必须给出具体页码。
#:
#: - `manga`     漫画改的，旁白只是忠实复述漫画 → 保留旁白，记录差异
#: - `narration` 旁白自己编的或改的 → 必须改写或删除
#: - `mixed`     漫画改了一部分、旁白又追加编造了一部分 → 要拆开说明
#: - `unknown`   查不清是谁改的 → 保留疑问，不许硬塞进前两个
#:
#: 没有差异时**留空**（`null`），不许用 `"none"` 之类的伪值冒充一个枚举成员。
ALTERATION_ORIGINS = {"manga", "narration", "mixed", "unknown"}

#: 逐段的**处理状态**。与人工签核（`review_status`）是两件事：
#: `pending_rewrite` 表示"审出问题了、还没改"，**不代表已经通过**。
AUDIT_STATUSES = {"approved", "pending_rewrite", "rewritten", "removed"}

#: 逐段的**处理决定**。`fix_pages` 是只改页映射不改文字。
DISPOSITIONS = {"keep", "fix_pages", "rewrite", "remove"}

#: 人工签核状态。`approved` 才允许出片；`pending_human` 表示机器出了结论但没人签。
REVIEW_STATUSES = {"pending_human", "approved", "rejected"}

#: 逐段 `severity` 的合法取值。Schema 里有这个 enum，Linter 以前没查——
#: `severity="catastrophic"` 能一路通过（P0-REVIEW-07）。枚举必须两边都锁。
SEVERITIES = {"high", "medium", "low", "none"}

#: 讲稿 schema 版本（Schema `script_schema` 的 enum）。
SCRIPT_SCHEMAS = {"script/v1", "script/v2"}

SEG_ID_RE = re.compile(r"^seg_[0-9]{4}$")
PAGE_RE = re.compile(r"^page_[0-9]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

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


def _json_kind(value):
    """给错误信息用的 JSON 类型名。"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "布尔值"
    if isinstance(value, dict):
        return "对象"
    if isinstance(value, list):
        return "数组"
    if isinstance(value, str):
        return "字符串"
    if isinstance(value, (int, float)):
        return "数字"
    return type(value).__name__


def _read_json(path):
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _read_json_checked(path, label=None, expect=dict):
    """读 JSON；文件损坏或顶层类型不对抛 `GateError`。

    门禁的职责是把"某一步失败"讲清楚，而不是让 CLI 崩在 traceback 里。
    **损坏 ≠ 不存在**：不存在由调用方按阶段规则处理，损坏必须报错。
    **合法 JSON 也不等于结构合法**：`null` / `[]` / `123` 能解析，
    但顶部不是对象，不能继续 `.get()`。
    """
    p = pathlib.Path(path)
    try:
        doc = _read_json(p)
    except (OSError, ValueError) as exc:
        raise GateError(
            f"error: {label or p.name} 存在但无法解析（{exc}）；"
            f"损坏的文件不能当成不存在") from exc
    if expect is not None and not isinstance(doc, expect):
        raise GateError(
            f"error: {label or p.name} 顶层必须是 JSON 对象，实为 "
            f"{_json_kind(doc)}；合法 JSON 不等于结构合法")
    return doc


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
    doc = _read_json_checked(p, "chapter.json")
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
    doc = _read_json_checked(p, "script.json")
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
        "judgement_scope": SCOPES["novel_ref"],
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


def lint_audit(audit, segs=None, page_set=None):
    """只校验 `script-audit.json` 的 **Schema**，不要求签核。

    存在的理由：门禁第 5 步把"结构合法"和"人已签核"混在一起判，导致一份
    **尚未签核**的报告根本没法被机器校验——它连"我这份格式对不对"都问不出来。
    而样张恰恰必须保持未签核状态。所以把 Schema 校验单独抽出来，
    签核是另一层（`_check_audit` 在 lint 之上再加哈希与签名）。

    返回 `[(segment_id 或 None, msg)]`，空列表表示格式合法。
    """
    out = []
    if not isinstance(audit, dict):
        return [(None, f"审核报告顶层必须是对象（JSON object），实为 "
                       f"{_json_kind(audit)}；合法 JSON 不等于结构合法")]
    if audit.get("schema") != AUDIT_SCHEMA:
        out.append((None, f"schema 应为 {AUDIT_SCHEMA!r}，实为 {audit.get('schema')!r}"))
    scope = audit.get("judgement_scope")
    if scope != SCOPES["script_audit"]:
        out.append((None, f"judgement_scope 必须显式声明为 "
                          f"{SCOPES['script_audit']!r}（旁白 vs 来源），实为 {scope!r}；"
                          f"不声明就无法与 novel_ref 的 {SCOPES['novel_ref']!r} 区分"))
    if not audit.get("audit_spec_version"):
        out.append((None, "缺 audit_spec_version（审核标准版本）"))
    rs = audit.get("review_status")
    if rs not in REVIEW_STATUSES:
        out.append((None, f"review_status 非法：{rs!r}；只能是 "
                          f"{'/'.join(sorted(REVIEW_STATUSES))}"))
    reviewer = audit.get("reviewed_by")
    if ("reviewed_by" in audit and reviewer is not None
            and not isinstance(reviewer, str)):
        out.append((None, f"reviewed_by 必须是字符串或 null，实为 "
                          f"{_json_kind(reviewer)}"))
    if rs == "approved":
        if not isinstance(reviewer, str) or not reviewer.startswith("human:"):
            out.append((None, f"review_status=approved 时 reviewed_by 必须是 "
                              f"human:<name>，实为 {reviewer!r}"))
        # 机器出结论、机器签名 = 自己给自己发合格证。
        # `status=rewritten` 只是"改过了"，**不等于**"通过了"；
        # 从 rewritten 到 approved 只能由另一只手完成。
        if isinstance(reviewer, str) and reviewer and reviewer == audit.get("prepared_by"):
            out.append((None, f"reviewed_by 与 prepared_by 相同（{reviewer!r}）："
                              f"改写完成不等于审核通过，签名必须是另一只手"))
    elif reviewer is not None:
        out.append((None, f"review_status={rs!r} 却已填 reviewed_by={reviewer!r}；"
                          f"没签核就不许留签名"))

    # 两层语义混进一份文件：`beats` 是 novel_ref 的结构，不该出现在审核报告里
    for foreign in ("beats", "novel_chapters", "align_meta"):
        if foreign in audit:
            out.append((None, f"审核报告里出现 novel_ref 专有字段 {foreign!r}："
                              f"两层判定（漫画 vs 小说 / 旁白 vs 来源）不许混在一份文件里"))

    # ---- 顶层必填字段（与 Schema 的 required 对齐）----
    # 只锁枚举不锁必填，等于"字段可以缺、校验器当没看见"。
    for req in ("schema", "audit_spec_version", "judgement_scope", "chapter_uid",
                "script_schema", "script_sha256", "novel_ref_sha256",
                "audited_segments", "review_status"):
        if req not in audit or audit.get(req) in (None, ""):
            out.append((None, f"缺必填字段 {req!r}"))
    if "reviewed_by" not in audit:
        out.append((None, "缺必填字段 'reviewed_by'（未签核时必须显式写 null）"))
    for field in ("audit_spec_version", "chapter_uid"):
        v = audit.get(field)
        if v is not None and not isinstance(v, str):
            out.append((None, f"{field} 必须是字符串，实为 {_json_kind(v)}"))
    if "reviewed_at" in audit:
        v = audit.get("reviewed_at")
        if v is not None and not isinstance(v, str):
            out.append((None, f"reviewed_at 必须是字符串或 null，实为 {_json_kind(v)}"))
    for field in ("prepared_by", "prepared_at", "notes"):
        if field in audit and not isinstance(audit.get(field), str):
            out.append((None, f"{field} 必须是字符串，实为 "
                              f"{_json_kind(audit.get(field))}"))
    for field in ("coverage", "schema_migration"):
        if field in audit and not isinstance(audit.get(field), dict):
            out.append((None, f"{field} 必须是对象，实为 "
                              f"{_json_kind(audit.get(field))}"))
    ss = audit.get("script_schema")
    if ss is not None and ss not in SCRIPT_SCHEMAS:
        out.append((None, f"script_schema 非法：{ss!r}；"
                          f"只能是 {'/'.join(sorted(SCRIPT_SCHEMAS))}"))
    for field in ("script_sha256", "novel_ref_sha256"):
        v = audit.get(field)
        if v is not None and not SHA256_RE.match(str(v)):
            out.append((None, f"{field} 必须是 64 位小写十六进制，"
                              f"实为 {str(v)[:20]!r}…"))

    raw_records = audit.get("audited_segments")
    if "audited_segments" not in audit:
        records = []
    elif not isinstance(raw_records, list):
        out.append((None, f"audited_segments 必须是数组，实为 "
                          f"{_json_kind(raw_records)}"))
        records = []
    else:
        records = raw_records
    if not records:
        out.append((None, "audited_segments 为空：没有任何逐段审核记录"))

    # ---- 段落唯一性：重复 id 会让后一条覆盖前一条，把无效判定藏起来 ----
    # 这不是格式问题，是审计记录完整性问题：一条自相矛盾的记录排在前面、
    # 一条合法记录排在后面，dict 一覆盖就"看起来全对"（P0-REVIEW-07）。
    audited, order, dups = {}, [], []
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            out.append((f"第 {idx} 项", f"audited_segments[{idx}] 必须是对象，实为 "
                                        f"{_json_kind(rec)}；不能把它当成一条审核记录"))
            continue
        sid = rec.get("segment_id")
        if not isinstance(sid, str):
            out.append((f"第 {idx} 项", f"segment_id 必须是字符串，实为 "
                                        f"{_json_kind(sid)}"))
            out.extend((None, m) for m in _lint_segment(None, rec, page_set))
            continue
        if sid in audited:
            dups.append(sid)
        else:
            order.append(sid)
        audited[sid] = rec          # 保留最后一条供字段校验；重复本身已记错
    if dups:
        out.append((None, f"audited_segments 里 segment_id 重复："
                          f"{_preview(sorted(set(dups)))}；重复记录会让后一条覆盖"
                          f"前一条，把无效判定藏起来。每段必须恰好一条，"
                          f"不接受 first-wins / last-wins"))

    for sid in order:
        if not SEG_ID_RE.match(sid):
            out.append((sid, f"segment_id 格式非法：{sid!r}；应为 seg_XXXX（四位数字）"))
        out.extend((sid, m) for m in _lint_segment(sid, audited[sid], page_set))

    if segs is not None:
        known = {sid for sid, _text in segs}
        for sid, _text in segs:
            if sid not in audited:
                out.append((sid, "审核报告未覆盖该段"))
        for sid in order:
            if sid not in known:
                out.append((sid, "审核报告里有讲稿中不存在的段落（多余记录）"))

    # `unknown` 是"还没查清"，不是一种结论——有它就整份不许签核。
    unresolved = [sid for sid, rec in audited.items()
                  if rec.get("alteration_origin") == "unknown"]
    if unresolved and rs == "approved":
        out.append((None, f"{len(unresolved)} 段的 alteration_origin 仍是 unknown"
                          f"（{_preview(unresolved)}）：来源没查清就不许签核通过"))
    return out


def _lint_segment(sid, rec, page_set):
    """单段判定的合法性。枚举、证据、两层语义的一致性都在这里锁。"""
    out = []
    fid = rec.get("fidelity")
    origin = rec.get("alteration_origin")
    disp = rec.get("disposition")
    status = rec.get("status")
    raw_pages = rec.get("pages_declared")
    pages = []
    if "pages_declared" in rec:
        if isinstance(raw_pages, list):
            pages = raw_pages
        else:
            out.append(f"pages_declared 必须是数组，实为 "
                       f"{_json_kind(raw_pages)}")

    # ---- 与 Schema 对齐：必填、枚举、格式 ----
    # 以前只查了 fidelity/status/disposition 三个枚举，`severity` 的 enum 写在
    # Schema 里却没人执行，`severity="catastrophic"` 能一路通过（P0-REVIEW-07）。
    for req in ("segment_id", "text_sha256", "status", "fidelity",
                "disposition", "evidence"):
        if rec.get(req) in (None, ""):
            out.append(f"缺必填字段 {req!r}")
    # `severity` 是可选字段；但只要写了，就必须是 enum 成员。
    # `null` 不是 enum 成员——"没写"和"写了 null"必须区分。
    if "severity" in rec:
        sev = rec.get("severity")
        if sev not in SEVERITIES:
            out.append(f"severity 非法：{sev!r}；只能是 "
                       f"{'/'.join(sorted(SEVERITIES))}")
    sha = rec.get("text_sha256")
    if sha not in (None, "") and (not isinstance(sha, str)
                                  or not SHA256_RE.match(sha)):
        out.append(f"text_sha256 必须是 64 位小写十六进制，实为 {str(sha)[:20]!r}…")
    if "novel_para" in rec and not isinstance(rec.get("novel_para"), list):
        out.append(f"novel_para 必须是数组，实为 "
                   f"{_json_kind(rec.get('novel_para'))}")
    for p in pages:
        if not isinstance(p, str) or not PAGE_RE.match(p):
            out.append(f"pages_declared 里 {p!r} 不符合 page_XXXX 格式")
    if "pages_actual" in rec:
        actual = rec.get("pages_actual")
        if not isinstance(actual, list):
            out.append(f"pages_actual 必须是数组，实为 {_json_kind(actual)}")
        else:
            for p in actual:
                if not isinstance(p, str) or not PAGE_RE.match(p):
                    out.append(f"pages_actual 里 {p!r} 不符合 page_XXXX 格式")
    for field in ("source_type", "review_note"):
        if field in rec and not isinstance(rec.get(field), str):
            out.append(f"{field} 必须是字符串，实为 "
                       f"{_json_kind(rec.get(field))}")

    if fid not in FIDELITIES:
        out.append(f"fidelity 非法：{fid!r}；只能是 {'/'.join(sorted(FIDELITIES))}")
    if status not in AUDIT_STATUSES:
        hint = "（`pending` 已废弃，语义是「已审出问题、尚未改写」的请用 `pending_rewrite`）" \
            if status == "pending" else ""
        out.append(f"status 非法：{status!r}；只能是 "
                   f"{'/'.join(sorted(AUDIT_STATUSES))}{hint}")
    if disp not in DISPOSITIONS:
        out.append(f"disposition 非法：{disp!r}；只能是 {'/'.join(sorted(DISPOSITIONS))}")

    # ---- alteration_origin：只在"有差异"时才有值 ----
    if origin is not None and not isinstance(origin, str):
        out.append(f"alteration_origin 必须是字符串或 null，实为 "
                   f"{_json_kind(origin)}")
    if fid == "altered":
        if origin not in ALTERATION_ORIGINS:
            out.append(f"fidelity=altered 但 alteration_origin={origin!r}；"
                       f"必须说明差异责任方（{'/'.join(sorted(ALTERATION_ORIGINS))}），"
                       f"否则无法判断该不该改稿")
    elif fid == "original":
        if origin not in (None, "narration"):
            out.append(f"fidelity=original 的差异只能是旁白造成的，"
                       f"alteration_origin={origin!r} 不成立")
    elif origin is not None:
        out.append(f"fidelity={fid!r} 表示没有差异，alteration_origin 必须留空，"
                   f"实为 {origin!r}")

    # ---- 证据：alteration_origin 不能代替来源引用 ----
    evidence = rec.get("evidence")
    if not isinstance(evidence, str) or not evidence.strip():
        out.append(f"evidence 必须是字符串且非空，实为 {_json_kind(evidence)}；"
                   f"判定必须给出可核对的人读证据")
    if fid in ("drawn", "altered") and not pages:
        out.append(f"fidelity={fid!r} 必须给出 pages_declared（旁白描述了画面，"
                   f"就得指得出是哪几页）")
    if origin in ("manga", "mixed") and not pages:
        out.append(f"alteration_origin={origin} 但 pages_declared 为空："
                   f"「漫画改的」本身就是一条关于画面的断言，必须附页码")
    # `mixed` 是最容易被当成逃生门的分类：一句"又像漫画又像原创"就绕过了举证。
    # 所以要求把新增部分**单独写出来**，不许混在 evidence 里含糊带过。
    if "mixed_note" in rec and not isinstance(rec.get("mixed_note"), str):
        out.append(f"mixed_note 必须是字符串，实为 "
                   f"{_json_kind(rec.get('mixed_note'))}")
    if origin == "mixed" and not str(rec.get("mixed_note") or "").strip():
        out.append("alteration_origin=mixed 必须填 mixed_note，"
                   "写明哪部分是漫画给的、哪部分是旁白新增的；"
                   "混在一起写等于没有举证")
    if fid != "original" and not rec.get("novel_para"):
        out.append(f"fidelity={fid!r} 必须给出 novel_para（没有段落区间就是没有来源）")
    if page_set is not None:
        bad = [p for p in pages if p not in page_set]
        if bad:
            out.append(f"pages_declared 里有本章不存在的页：{_preview(bad)}")

    # ---- 状态与决定不许互相矛盾 ----
    if status == "approved" and disp != "keep":
        out.append(f"status=approved 却 disposition={disp!r}：通过了就不该还挂着要改")
    if status == "removed" and disp != "remove":
        out.append(f"status=removed 却 disposition={disp!r}")
    # Schema：origin=narration 时 disposition 只能是 rewrite/remove。
    # 只拒绝 keep 会放过 fix_pages——旁白自己编的内容改页码并不能让它有来源。
    if origin == "narration" and disp not in ("rewrite", "remove"):
        out.append(f"alteration_origin=narration 却 disposition={disp!r}："
                   f"旁白自己编的内容不能保留，只能改写或删除（rewrite/remove）")
    # `unknown` 不是结论，不能据它放行某一段（Schema 只允许待改写或删除）。
    if origin == "unknown" and status not in ("pending_rewrite", "removed"):
        out.append(f"alteration_origin=unknown 却 status={status!r}："
                   f"来源没查清，不许签核通过，只能是 pending_rewrite 或 removed")
    return out


def check(work, novel_dir):
    """五步门禁链。返回 `(ok, problems)`，problems 是 `[(step, msg)]`。

    不抛异常——调用方要能把全部问题一次列出来，而不是修一个跑一次。
    """
    work = pathlib.Path(work)
    novel_dir = pathlib.Path(novel_dir)
    problems = []

    # ---- 第 1 步：章节身份 + 底稿存在 ----
    # 身份先于内容：一份格式完全合法、哈希全部正确的审计，也可能属于另一章。
    # 哈希只能证明"没被改过"，证明不了"属于这一章"（P0-08）。
    try:
        from .identity import check_work_identity
        id_errors, _id_warnings = check_work_identity(work)
        for msg in id_errors:
            problems.append((1, f"章节身份：{msg}"))
    except Exception as exc:  # noqa: BLE001 — 身份模块自身出错也不能静默放行
        problems.append((1, f"章节身份校验失败：{exc}"))

    ref_path = work / "novel_ref.json"
    if not ref_path.exists():
        problems.append((1, f"novel_ref.json 不存在（{ref_path}）；先跑 --align"))
        return False, problems
    try:
        ref = _read_json_checked(ref_path, "novel_ref.json")
    except GateError as exc:
        problems.append((1, str(exc)))
        return False, problems

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
        script_doc, segs, schema = script_segments(work)
    except GateError as exc:
        problems.append((3, str(exc)))
        script_doc, segs, schema = {}, [], "script/v1"
    beat_ids = {b.get("id") for b in ref.get("beats") or []}
    if schema != "script/v2":
        problems.append(
            (3, f"讲稿是 {schema}，没有 source_refs 字段，无法校验来源；"
                f"需先迁到 script/v2（P0-11）"))
    else:
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
    # beat 的 fidelity 判的是「漫画 vs 小说」，必须在文件里写死，
    # 否则同一份报告被当成「旁白 vs 来源」去读也不会报错。
    ref_scope = ref.get("judgement_scope")
    if ref_scope != SCOPES["novel_ref"]:
        problems.append(
            (4, f"novel_ref.judgement_scope 必须显式声明为 {SCOPES['novel_ref']!r}"
                f"（漫画 vs 小说），实为 {ref_scope!r}"))
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
    """第 5 步：`script-audit.json` Schema + 三层哈希 + 逐段 + 人签。

    顺序是刻意的：**先 lint 再验哈希**。一份格式就错的报告，先告诉人"字段写错了"
    比先报"哈希不符"有用——后者会让人以为是讲稿改了。
    """
    out = []
    audit_path = pathlib.Path(work) / "script-audit.json"
    if not audit_path.exists():
        return [(5, "script-audit.json 不存在：内容未经审核，禁止正式出片")]
    try:
        audit = _read_json_checked(audit_path, "script-audit.json")
    except GateError as exc:
        return [(5, str(exc))]
    if not isinstance(audit, dict):
        return [(5, f"{sid}: {msg}" if sid else msg)
                for sid, msg in lint_audit(audit, segs=segs)]

    try:
        _cdoc, pages = chapter_pages(work)
    except GateError:
        pages = []
    for sid, msg in lint_audit(audit, segs=segs, page_set=set(pages)):
        out.append((5, f"{sid}: {msg}" if sid else msg))

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

    raw_segments = audit.get("audited_segments")
    audited = ({a.get("segment_id"): a for a in raw_segments
                if isinstance(a, dict)}
               if isinstance(raw_segments, list) else {})
    for sid, text in segs:
        rec = audited.get(sid)
        if not rec:
            continue  # 缺段已由 lint_audit 报过，不重复刷屏
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
