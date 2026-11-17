"""P0-08 章节身份：一个权威身份 + 三种编号分开 + 不一致就报错。

## 为什么需要这个模块

实测五章（`m1/v2/ch06–ch10`）都有同一个毛病：**三套编号在同一个目录里对不上**。

| 身份来源 | `m1/v2/ch06` 的值 |
| --- | --- |
| 目录名 | `ch06` |
| `chapter.json` 的 `id` | `ch01` |
| `chapter.json` 的 `number` | 第六章 |
| 真实身份 | 第二卷第一章（全书第六章） |

三个值单看都对，合起来就是错的。危险不在难看，在**门禁抓不到**：
`script-audit.json` 的哈希绑的是文件内容，不是章节身份。
底稿/审计/讲稿一旦写进错误工作区，整章内容张冠李戴，五步门禁照样全过。

所以这里做两件事：

1. **`chapter_uid` 成为唯一权威身份**，格式 `<系列slug>-v<卷两位>-ch<全书两位>`，
   跨文件引用只用它。`id` / `number` 降级为展示或兼容字段。
2. **四种来源交叉比对，不一致就抛错**，报错要同时列出所有值。
   **不许程序挑一个"看起来最接近"的继续跑**——猜对是运气，猜错是静默错配。

## 三层身份字段的分工

| 字段 | 谁在用 | 能不能用来定位章节 |
| --- | --- | --- |
| `chapter_uid` | 全部机器引用 | **能，且只能用它** |
| `volume_chapter_number` | 卷内排序、`id` 的推导来源 | 不能跨卷 |
| `global_chapter_number` | 全书连续编号、目录名 | 不能跨系列 |
| `id`（`ch01`） | 兼容旧代码 | **不能**（两卷都从 `ch01` 起） |
| `number`（第六章） | 展示、人工对数 | 不能（中文串，可能重名） |
"""

import json
import pathlib
import re

#: 中文数字 → 整数。漫画章节号只到十几，不需要通用转换。
CN_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10,
}

#: `chapter_uid` 的严格格式。**必须两位补零**，否则 `v1` 与 `v01` 会并存。
UID_RE = re.compile(r"^(?P<slug>[a-z][a-z0-9-]*)-v(?P<vol>\d{2})-ch(?P<ch>\d{2})$")

#: 目录名的章节编号形式（`ch06`）。命中就参与交叉比对。
DIR_RE = re.compile(r"^ch(?P<n>\d{2,3})$")

#: 索引/章级文档里必须存在的身份字段。
IDENTITY_FIELDS = ("chapter_uid", "volume_number", "global_chapter_number",
                   "volume_chapter_number")


class IdentityError(RuntimeError):
    """身份不一致。CLI 统一转退出码 3。"""


def cn_to_int(text):
    """`第六章` / `十二` → 整数。解析不了返回 `None`（**不猜**）。"""
    digits = re.search(r"[一二三四五六七八九十]+", str(text or ""))
    if not digits:
        return None
    s = digits.group(0)
    if s in CN_NUM:
        return CN_NUM[s]
    if s.startswith("十") and len(s) == 2:
        return 10 + CN_NUM.get(s[1], 0)
    if s.endswith("十") and len(s) == 2:
        return CN_NUM.get(s[0], 0) * 10
    if len(s) == 3 and s[1] == "十":
        return CN_NUM.get(s[0], 0) * 10 + CN_NUM.get(s[2], 0)
    return None


def _is_int(value):
    """严格整数：拒绝 `bool`（Python 里 `True == 1`）与 `1.0`。"""
    return type(value) is int


def make_uid(series_slug, volume_number, global_chapter_number):
    """拼 `chapter_uid`。参数不合法就抛错，不做兜底。"""
    if not isinstance(series_slug, str) or not re.fullmatch(
            r"[a-z][a-z0-9-]*", series_slug):
        raise IdentityError(
            f"error: series_slug 必须是小写 ASCII 字符串（a-z0-9-），"
            f"实为 {series_slug!r}；中文系列名不能直接进 uid")
    for name, val in (("volume_number", volume_number),
                      ("global_chapter_number", global_chapter_number)):
        if not _is_int(val) or val < 1:
            raise IdentityError(f"error: {name} 必须是正整数，实为 {val!r}")
    return f"{series_slug}-v{volume_number:02d}-ch{global_chapter_number:02d}"


def parse_uid(uid):
    """拆 `chapter_uid` → `(slug, volume, global)`。格式不对抛错。"""
    if not isinstance(uid, str):
        raise IdentityError(
            f"error: chapter_uid 必须是字符串，实为 {_json_kind(uid)} {uid!r}")
    m = UID_RE.match(uid)
    if not m:
        raise IdentityError(
            f"error: chapter_uid 格式非法 {uid!r}；"
            f"应为 <slug>-v<卷两位>-ch<全书两位>，如 konosuba-manga-v02-ch06")
    return m.group("slug"), int(m.group("vol")), int(m.group("ch"))


def chapter_problems(ch, series_slug=None, volume_number=None):
    """单章身份自检。返回问题列表（空 = 合法）。

    `series_slug` / `volume_number` 给了就一并核对——它们是卷级常量，
    单章不该自己另写一个值。

    **先验类型，再做比较/格式化/哈希**。Python 的 `True == 1`、`1.0 == 1`
    会让"比较相等"冒充"类型正确"，所以整数一律用 `type(v) is int`，
    不接受 bool / float / 字符串 / 数组 / 对象。
    """
    if not isinstance(ch, dict):
        return [f"章节身份必须是 JSON 对象，实为 {_json_kind(ch)}"]
    out = []
    raw_label = ch.get("chapter_uid") or ch.get("id") or "?"
    label = raw_label if isinstance(raw_label, str) else "?"

    # 字符串字段：存在时必须是字符串。None 交给下面的 missing 逻辑。
    for field in ("chapter_uid", "series_slug", "id", "number"):
        if field in ch and ch[field] is not None and not isinstance(ch[field], str):
            out.append(f"{label}: {field} 必须是字符串，实为 "
                       f"{_json_kind(ch[field])} {ch[field]!r}")

    # 整数字段：必须是真正的正整数，不能靠 `==` 蒙混过关。
    for field in ("volume_number", "global_chapter_number",
                  "volume_chapter_number"):
        if field not in ch:
            continue
        value = ch[field]
        if not _is_int(value):
            out.append(f"{label}: {field} 必须是正整数（JSON integer，"
                       f"不接受 bool / float / 字符串 / 数组），实为 "
                       f"{_json_kind(value)} {value!r}")
        elif value < 1:
            out.append(f"{label}: {field} 必须是正整数，实为 {value}")

    missing = [f for f in IDENTITY_FIELDS if ch.get(f) in (None, "")]
    if missing:
        out.append(f"{label}: 缺身份字段 {missing}；"
                   f"没有这些字段就只能靠猜，P0-08 之后不许猜")
        return out  # 缺字段时后面的比对没有意义

    try:
        slug, vol, glob = parse_uid(ch["chapter_uid"])
    except IdentityError as exc:
        out.append(f"{label}: {exc}")
        return out

    series_ok = isinstance(series_slug, str) and bool(series_slug)
    if series_ok and slug != series_slug:
        out.append(f"{label}: chapter_uid 的系列 {slug!r} != 索引的 {series_slug!r}")
    if _is_int(volume_number) and vol != volume_number:
        out.append(f"{label}: chapter_uid 的卷号 {vol} != 索引的 {volume_number}")

    vol_field = ch["volume_number"]
    glob_field = ch["global_chapter_number"]
    vcn_field = ch["volume_chapter_number"]
    if _is_int(vol_field) and vol != vol_field:
        out.append(f"{label}: chapter_uid 卷号 {vol} != volume_number "
                   f"{vol_field}；两个字段各说一套")
    if _is_int(glob_field) and glob != glob_field:
        out.append(f"{label}: chapter_uid 全书号 {glob} != global_chapter_number "
                   f"{glob_field}")

    # `number` 是展示用中文串，但它必须与全书号一致——否则人工对数会数错章
    number = ch.get("number")
    if isinstance(number, str):
        from_number = cn_to_int(number)
        if from_number is None:
            out.append(f"{label}: number={number!r} 解析不出章节号")
        elif _is_int(glob_field) and from_number != glob_field:
            out.append(f"{label}: number={number!r} 是第 {from_number} 章，"
                       f"但 global_chapter_number={glob_field}")
    elif number is None or number == "":
        out.append(f"{label}: number={number!r} 解析不出章节号")

    # `id` 是卷内短 id，必须能从 volume_chapter_number 推导出来。
    # 先验类型，避免对字符串/浮点数执行 `:02d` 直接抛 ValueError。
    if _is_int(vcn_field) and vcn_field >= 1:
        want_id = f"ch{vcn_field:02d}"
        if ch.get("id") != want_id:
            out.append(f"{label}: id={ch.get('id')!r} 与 volume_chapter_number="
                       f"{vcn_field} 不符（应为 {want_id!r}）；"
                       f"id 只作兼容字段，不许承载第二种含义")
    return out


def index_problems(index):
    """整卷身份自检：逐章 + 唯一性 + 卷内编号连续。

    索引是 fail-closed 的输入：顶层必须是对象，`chapters` 必须是数组，
    每个元素必须是章节对象。结构都不对时不能调用一轮 `.get()` 然后
    靠 traceback 告诉调用方——那既不是"通过"，也不是可读的校验错误。
    """
    if not isinstance(index, dict):
        return [f"索引顶层必须是 JSON 对象，实为 {_json_kind(index)}"]
    chapters = index.get("chapters")
    if not isinstance(chapters, list):
        return [f"索引的 chapters 必须是数组，实为 {_json_kind(chapters)}"]
    if not chapters:
        return ["索引里没有 chapters"]
    bad = [(i, ch) for i, ch in enumerate(chapters) if not isinstance(ch, dict)]
    if bad:
        return [f"chapters[{i}] 必须是章节对象，实为 {_json_kind(ch)}"
                for i, ch in bad]

    out = []
    slug = index.get("series_slug")
    vol = index.get("volume_number")
    if slug is None or slug == "":
        out.append("索引缺 series_slug：没有它就没法生成 chapter_uid")
    elif not isinstance(slug, str):
        out.append(f"索引 series_slug 必须是字符串，实为 "
                   f"{_json_kind(slug)} {slug!r}")
    if not _is_int(vol):
        out.append(f"索引 volume_number 必须是正整数（JSON integer），实为 "
                   f"{_json_kind(vol)} {vol!r}")
    elif vol < 1:
        out.append(f"索引 volume_number 必须是正整数，实为 {vol}")
    for ch in chapters:
        out.extend(chapter_problems(
            ch,
            series_slug=slug if isinstance(slug, str) else None,
            volume_number=vol if _is_int(vol) else None))

    # 唯一性：uid / id / number 都不许重复，否则查找必然歧义。
    # 只把字符串放进字典键——数组/对象不可哈希，直接 `seen[v]` 会抛 TypeError。
    for field in ("chapter_uid", "id", "number"):
        seen = {}
        for ch in chapters:
            v = ch.get(field)
            if not isinstance(v, str):
                continue  # 类型错误已由 chapter_problems 报出
            if v in seen:
                out.append(f"{field} 重复：{v!r} 同时出现在 "
                           f"{seen[v]} 与 {ch.get('chapter_uid') or ch.get('id')}")
            seen[v] = ch.get("chapter_uid") or ch.get("id")

    # 卷内编号必须 1..N 连续且与数组顺序一致
    want = list(range(1, len(chapters) + 1))
    got = [c.get("volume_chapter_number") for c in chapters]
    if got != want:
        out.append(f"volume_chapter_number 必须是 1..{len(chapters)} 且按顺序，实为 {got}")
    return out


def require_index_identity(index):
    """索引身份不合格就抛错（CLI 退出码 3）。"""
    problems = index_problems(index)
    if problems:
        raise IdentityError(
            "error: 章节身份不合格（%d 项）：\n  - %s"
            % (len(problems), "\n  - ".join(problems)))
    return index


def find_chapter(index, key):
    """按 `chapter_uid` / `id` / `number` / `label_zh` 找一章。

    **三种情况必须区分开**：

    - 唯一命中 → 返回
    - 零命中 → 报错并列出全部已知章节
    - 多命中 → **报错并列出全部候选**。这是 P0-08 的核心纪律：
      有歧义就说有歧义，不许挑一个"最像的"。猜对是运气，猜错是静默错配。
    """
    key = str(key or "")
    hits = [ch for ch in index.get("chapters") or []
            if key and key in (ch.get("chapter_uid"), ch.get("id"),
                               ch.get("number"), ch.get("label_zh"))]
    if len(hits) == 1:
        return hits[0]
    known = "; ".join(
        f"{c.get('chapter_uid') or c.get('id')} (id={c.get('id')}, "
        f"number={c.get('number')})" for c in index.get("chapters") or [])
    if not hits:
        raise IdentityError(f"error: 找不到章节 {key!r}；已知：{known}")
    raise IdentityError(
        "error: 章节键 %r 有歧义，命中 %d 个：%s\n"
        "  已知：%s\n"
        "  请改用 chapter_uid（唯一权威身份）。程序不替你挑。"
        % (key, len(hits),
           ", ".join(c.get("chapter_uid") or c.get("id") for c in hits), known))


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


def _read_json(path, expect=None):
    """读取 JSON，并**区分「不存在」「损坏」「顶层类型错误」**。

    返回 `(data, status)`，`status` ∈ `{"ok", "missing", "corrupt",
    "wrong_type"}`。`expect` 是期望的顶层 Python 类型（例如 `dict`）。

    旧实现用同一个 `None` 表示两种失败，调用方一律 `continue`——结果
    **一份损坏的 `novel_ref.json` 会被当成不存在而静默跳过**，所谓"五处交叉
    验证"实际只验了剩下几处（P0-REVIEW-07）。缺失可能是阶段允许的，
    损坏永远不是；合法 JSON 但顶层结构不对（`null` / `[]` / `123`）同样不是。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None, "missing"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "corrupt"
    if expect is not None and not isinstance(data, expect):
        return data, "wrong_type"
    return data, "ok"


def _authority_candidates(work):
    """按真实布局列出可能存在的卷级索引路径（去重、保序）。

    真实布局 `m1/v1/ch01/work` 的索引在 `m1/v1/work/chapter_index.json`。
    旧实现只找 `work.parent` / `work.parent.parent`（= `m1/v1/ch01` / `m1/v1`），
    **两个都不对**——所以真实仓库的章级校验从来没有加载过权威表，
    "正常路径通过"其实是"根本没校验权威表就通过了"。
    这里把 `<base>/work/chapter_index.json` 也列进去。
    """
    out, seen = [], set()
    for base in (work, work.parent, work.parent.parent):
        for rel in ("chapter_index.json", "work/chapter_index.json"):
            p = base / rel
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


def _authority_chapters(authority):
    """把权威表输入规范成章节列表。

    接受卷索引 dict、`chapters` 列表、uid 集合或 uid 字符串列表。
    返回空列表表示"没有可用的权威表"。
    """
    if isinstance(authority, dict):
        chapters = authority.get("chapters")
        if not isinstance(chapters, list):
            return []
        return [ch for ch in chapters if isinstance(ch, dict)]
    if isinstance(authority, (set, frozenset)):
        return [{"chapter_uid": u} for u in authority if isinstance(u, str)]
    if isinstance(authority, (list, tuple)):
        out = []
        for item in authority:
            if isinstance(item, str):
                out.append({"chapter_uid": item})
            elif isinstance(item, dict):
                out.append(item)
        return out
    return []


def check_work_identity(work, authority=None):
    """章级 work 目录的跨文件身份核对。

    比对六个来源：目录名、`chapter.json`、`novel_ref.json`、`script.json`、
    `script-audit.json`，以及**权威章节映射表**（卷级 `chapter_index.json`）。

    `authority`：

    - `None`（默认）：自动从工作区向上找 `chapter_index.json`。**找不到即报错**
      （fail-closed）；文件损坏、为空、或索引自身不合格同样报错。
    - `False`：**显式**关闭权威表校验，只用于确实没有卷级索引的临时实验目录。
      这是唯一的关闭方式——不能靠"恰好没找到"来静默跳过。
    - 显式 dict / list / set：直接作为权威表。

    返回 `(errors, warnings)`。errors 分五类：

    1. 权威表缺失、损坏、顶层类型错误、为空，或权威索引自身不合格；
    2. 身份文件存在但 JSON 损坏，或合法 JSON 的顶层不是对象；
    3. 找到多份权威表（程序不替你挑哪一份才是"正确卷"）；
    4. 两份文件声明了不同的 `chapter_uid`，或目录名与全书号不符；
    5. 所有来源两两之间的冲突（**即使 `chapter.json` 缺 uid 也照样抓**），
       以及 uid 不在权威表里 / 在权威表里重复 / 与权威表编号不符。

    **五份文件自己一致也不作数**——它们可能一起抄错了一个不存在的章号。
    权威表是唯一能发现这种"集体一致地错"的东西。

    唯一的 warning 例外是 v1 `script.json` 没有章节声明（P0-11 迁移前合法），
    以及 `novel_ref.json` / `script-audit.json` 文件本身不存在。
    """
    work = pathlib.Path(work)
    errors, warnings = [], []

    def load(name, required=False):
        """读一个身份文件。损坏 / 顶层类型错误 / 缺失且必填 → 记 error。"""
        data, status = _read_json(work / name, expect=dict)
        if status == "corrupt":
            errors.append(f"{name} 存在但不是合法 JSON：损坏的文件不能当成不存在"
                          f"而跳过校验，否则交叉验证会悄悄少验一处")
            return None
        if status == "wrong_type":
            errors.append(
                f"{name} 存在且是合法 JSON，但顶层必须是对象，实为 "
                f"{_json_kind(data)}；结构不合法不能当成缺失跳过")
            return None
        if status == "missing" and required:
            errors.append(f"{name} 不存在；缺了它无法核对章节身份")
            return None
        return data

    # ---- 权威表：先解析，fail-closed ----
    # 五份文件自己一致，证明不了它们没有一起抄错一个不存在的章号；
    # 权威表是唯一能发现"集体一致地错"的东西，所以它不能"找不到就算了"。
    auth_doc = None
    if authority is None:
        found = [p for p in _authority_candidates(work) if p.exists()]
        if not found:
            errors.append(
                "找不到权威章节映射表 chapter_index.json（卷级）；"
                "五份文件自己一致也不能证明它们没有一起抄错。"
                "确实没有权威表的临时目录必须显式传 authority=False")
            authority = False
        elif len(found) > 1:
            errors.append(
                f"找到 {len(found)} 份权威章节映射表："
                f"{'、'.join(str(p) for p in found)}；"
                f"程序不替你挑哪一份是当前卷，请只保留一份")
            authority = False
        else:
            auth_doc, status = _read_json(found[0], expect=dict)
            if status == "wrong_type":
                errors.append(
                    f"权威表 {found[0]} 存在且是合法 JSON，但顶层必须是对象，"
                    f"实为 {_json_kind(auth_doc)}；"
                    f"结构不合法不能当成没有权威表")
                auth_doc = None
                authority = False
            elif status != "ok":
                errors.append(f"权威表 {found[0]} 无法解析（{status}）；"
                              f"损坏的权威表不能当成没有权威表")
                auth_doc = None
                authority = False
            else:
                authority = auth_doc
    elif authority is not False:
        auth_doc = authority

    chapter = load("chapter.json", required=True)
    if chapter is None:
        return errors, warnings

    raw_uid = chapter.get("chapter_uid")
    uid = None
    if raw_uid is None or raw_uid == "":
        errors.append("chapter.json 缺 chapter_uid：它是唯一权威身份，不能省")
    elif not isinstance(raw_uid, str):
        errors.append(f"chapter.json 的 chapter_uid 必须是字符串，实为 "
                      f"{_json_kind(raw_uid)} {raw_uid!r}")
    else:
        try:
            parse_uid(raw_uid)
            uid = raw_uid
        except IdentityError:
            pass  # chapter_problems 会给出具体格式错误
    errors.extend(chapter_problems(
        chapter,
        series_slug=chapter.get("series_slug"),
        volume_number=chapter.get("volume_number")))

    # 找到一份索引 ≠ 找到当前卷的索引。索引顶层声明的卷必须与本章一致，
    # 否则一份结构完全合法、内部也自洽的**别卷**索引会被拿来当权威表。
    if isinstance(auth_doc, dict):
        want_slug = auth_doc.get("series_slug")
        got_slug = chapter.get("series_slug")
        if (isinstance(want_slug, str) and isinstance(got_slug, str)
                and want_slug != got_slug):
            errors.append(
                f"权威表的 series_slug={want_slug!r} 与 chapter.json 的 "
                f"{got_slug!r} 不符：找到的索引不是本章所属系列的权威表")
        want_vol = auth_doc.get("volume_number")
        got_vol = chapter.get("volume_number")
        if _is_int(want_vol) and _is_int(got_vol) and want_vol != got_vol:
            errors.append(
                f"权威表的 volume_number={want_vol!r} 与 chapter.json 的 "
                f"{got_vol!r} 不符：找到的索引不是本章所属卷的权威表")

    # 目录名（ch06）指的是**全书号**，不是卷内号。
    # 章级 work 通常长这样：`m1/v2/ch06/work`——目录名在**上一层**，
    # 所以 `work` 自己不算，要看它的父目录。
    candidates = [work.name]
    if work.name in ("work", "out"):
        candidates.append(work.parent.name)
    for name in candidates:
        m = DIR_RE.match(name)
        glob = chapter.get("global_chapter_number")
        if not m or not _is_int(glob):
            continue
        if int(m.group("n")) != glob:
            errors.append(
                f"目录名 {name!r} 表示全书第 {int(m.group('n'))} 章，"
                f"但 chapter.json 的 global_chapter_number="
                f"{glob}（chapter_uid={uid}）")

    # 收集所有"自称属于哪一章"的来源，供逐项比对与两两交叉比对。
    # 目录名只给全书号、给不出完整 uid，所以不进 claims（它在上面单独比）。
    claims = {}
    if uid:
        claims["chapter.json"] = uid

    sources = {
        "novel_ref.json": lambda d: d.get("chapter_uid"),
        "script.json": lambda d: d.get("chapter_uid") or d.get("chapter"),
        "script-audit.json": lambda d: d.get("chapter_uid"),
    }
    docs = {}
    for name, getter in sources.items():
        doc = load(name)          # 损坏已在 load 里记成 error
        docs[name] = doc
        if doc is None:
            continue
        if name == "script.json":
            # 显式写了 chapter_uid 就必须是有效字符串；不能因为它是空值/
            # 错误类型就悄悄退回 chapter 字段。
            has_uid = "chapter_uid" in doc
            val = doc.get("chapter_uid") if has_uid else doc.get("chapter")
        else:
            has_uid = True
            val = getter(doc)
        if val is None or val == "":
            if name == "script.json" and not has_uid:
                # 唯一例外：十章 v1 讲稿没有章节声明，P0-11 迁移后消失。
                warnings.append("script.json 没有声明所属章节（P0-11 迁移后补 chapter_uid）")
            else:
                errors.append(f"{name} 缺 chapter_uid：身份绑定文件不能省，"
                              f"缺了就无法证明它属于这一章")
            continue
        if not isinstance(val, str):
            errors.append(f"{name} 的 chapter_uid/chapter 必须是字符串，实为 "
                          f"{_json_kind(val)} {val!r}")
            continue
        claims[name] = val
        if uid and val != uid:
            errors.append(
                f"{name} 声明 chapter_uid={val!r}，"
                f"与 chapter.json 的 {uid!r} 不符——这份文件属于另一章")

    # 两两交叉比对：不依赖 chapter.json 当基准。
    # 上面那一轮是"每份 vs chapter.json"，chapter.json 自己缺 uid 时整轮空转；
    # 这里补上"每份 vs 每份"，局部错配无论发生在哪一对都跑不掉。
    by_uid = {}
    for source, val in claims.items():
        by_uid.setdefault(val, []).append(source)
    if len(by_uid) > 1:
        description = " | ".join(
            f"{val} <- {','.join(srcs)}" for val, srcs in by_uid.items())
        errors.append(
            f"身份来源互相矛盾（{len(by_uid)} 个不同 chapter_uid）：{description}；"
            f"程序不替你挑")

    # novel_ref 还带 chapter_id，顺手核对（它是兼容字段，但不能自相矛盾）
    ref = docs.get("novel_ref.json")
    if ref and ref.get("chapter_id") and chapter.get("id"):
        if ref["chapter_id"] != chapter["id"]:
            errors.append(
                f"novel_ref.json 的 chapter_id={ref['chapter_id']!r} "
                f"与 chapter.json 的 id={chapter['id']!r} 不符")

    # 权威表：五份文件一致也可能一起抄错了一个不存在的章。
    if authority is not False:
        # 章级校验必须验证**整份**权威索引，不能只查"当前 uid 能否匹配到"。
        # 否则同一索引里别的章节重复 id、卷内编号跳号，章级 --verify 仍会通过，
        # 与卷级 --verify 的强度不一致（P0-REVIEW-07）。
        if isinstance(auth_doc, dict):
            for msg in index_problems(auth_doc):
                errors.append(f"权威索引自身不合格：{msg}")
        auth = _authority_chapters(auth_doc)
        if not auth:
            errors.append(
                "权威章节映射表为空或解析不出章节列表；按 fail-closed 拒绝，"
                "不许在无权威表的情况下放行身份校验")
        elif uid:
            matches = [c for c in auth
                       if isinstance(c, dict) and c.get("chapter_uid") == uid]
            if not matches:
                known = ", ".join(sorted({str(c.get("chapter_uid")) for c in auth}))
                errors.append(
                    f"chapter_uid={uid!r} 不在权威章节映射表中；权威表：{known}；"
                    f"五份文件自己一致也不作数")
            elif len(matches) > 1:
                errors.append(
                    f"chapter_uid={uid!r} 在权威章节映射表中重复 {len(matches)} 次；"
                    f"身份不唯一，查找必然歧义")
            else:
                for field in ("global_chapter_number", "volume_number", "id"):
                    want = matches[0].get(field)
                    got = chapter.get(field)
                    if field == "id":
                        same_type = isinstance(want, str) and isinstance(got, str)
                    else:
                        same_type = _is_int(want) and _is_int(got)
                    if same_type and want != got:
                        errors.append(
                            f"chapter.json 的 {field}={got!r} "
                            f"与权威表中 {uid!r} 的 {want!r} 不符")
    return errors, warnings
