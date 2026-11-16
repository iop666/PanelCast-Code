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


def make_uid(series_slug, volume_number, global_chapter_number):
    """拼 `chapter_uid`。参数不合法就抛错，不做兜底。"""
    if not re.fullmatch(r"[a-z][a-z0-9-]*", str(series_slug or "")):
        raise IdentityError(
            f"error: series_slug 必须是小写 ASCII（a-z0-9-），实为 {series_slug!r}；"
            f"中文系列名不能直接进 uid")
    for name, val in (("volume_number", volume_number),
                      ("global_chapter_number", global_chapter_number)):
        if not isinstance(val, int) or val < 1:
            raise IdentityError(f"error: {name} 必须是正整数，实为 {val!r}")
    return f"{series_slug}-v{volume_number:02d}-ch{global_chapter_number:02d}"


def parse_uid(uid):
    """拆 `chapter_uid` → `(slug, volume, global)`。格式不对抛错。"""
    m = UID_RE.match(str(uid or ""))
    if not m:
        raise IdentityError(
            f"error: chapter_uid 格式非法 {uid!r}；"
            f"应为 <slug>-v<卷两位>-ch<全书两位>，如 konosuba-manga-v02-ch06")
    return m.group("slug"), int(m.group("vol")), int(m.group("ch"))


def chapter_problems(ch, series_slug=None, volume_number=None):
    """单章身份自检。返回问题列表（空 = 合法）。

    `series_slug` / `volume_number` 给了就一并核对——它们是卷级常量，
    单章不该自己另写一个值。
    """
    out = []
    label = ch.get("chapter_uid") or ch.get("id") or "?"
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

    if series_slug and slug != series_slug:
        out.append(f"{label}: chapter_uid 的系列 {slug!r} != 索引的 {series_slug!r}")
    if volume_number is not None and vol != volume_number:
        out.append(f"{label}: chapter_uid 的卷号 {vol} != 索引的 {volume_number}")
    if vol != ch["volume_number"]:
        out.append(f"{label}: chapter_uid 卷号 {vol} != volume_number "
                   f"{ch['volume_number']}；两个字段各说一套")
    if glob != ch["global_chapter_number"]:
        out.append(f"{label}: chapter_uid 全书号 {glob} != global_chapter_number "
                   f"{ch['global_chapter_number']}")

    # `number` 是展示用中文串，但它必须与全书号一致——否则人工对数会数错章
    from_number = cn_to_int(ch.get("number"))
    if from_number is None:
        out.append(f"{label}: number={ch.get('number')!r} 解析不出章节号")
    elif from_number != ch["global_chapter_number"]:
        out.append(f"{label}: number={ch.get('number')!r} 是第 {from_number} 章，"
                   f"但 global_chapter_number={ch['global_chapter_number']}")

    # `id` 是卷内短 id，必须能从 volume_chapter_number 推导出来
    want_id = f"ch{ch['volume_chapter_number']:02d}"
    if ch.get("id") != want_id:
        out.append(f"{label}: id={ch.get('id')!r} 与 volume_chapter_number="
                   f"{ch['volume_chapter_number']} 不符（应为 {want_id!r}）；"
                   f"id 只作兼容字段，不许承载第二种含义")
    return out


def index_problems(index):
    """整卷身份自检：逐章 + 唯一性 + 卷内编号连续。"""
    chapters = index.get("chapters") or []
    if not chapters:
        return ["索引里没有 chapters"]

    out = []
    slug = index.get("series_slug")
    vol = index.get("volume_number")
    if not slug:
        out.append("索引缺 series_slug：没有它就没法生成 chapter_uid")
    if not isinstance(vol, int):
        out.append(f"索引缺 volume_number（整数），实为 {vol!r}")
    for ch in chapters:
        out.extend(chapter_problems(ch, series_slug=slug, volume_number=vol))

    # 唯一性：uid / id / number 都不许重复，否则查找必然歧义
    for field in ("chapter_uid", "id", "number"):
        seen = {}
        for ch in chapters:
            v = ch.get(field)
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


def _read_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _authority_chapters(authority):
    """把权威表输入规范成章节列表。

    接受卷索引 dict、`chapters` 列表、uid 集合或 uid 字符串列表。
    返回空列表表示"没有可用的权威表"。
    """
    if isinstance(authority, dict):
        return list(authority.get("chapters") or [])
    if isinstance(authority, (set, frozenset)):
        return [{"chapter_uid": u} for u in authority]
    if isinstance(authority, (list, tuple)):
        return [{"chapter_uid": x} if isinstance(x, str) else x for x in authority]
    return []


def check_work_identity(work, authority=None):
    """章级 work 目录的跨文件身份核对。

    比对六个来源：目录名、`chapter.json`、`novel_ref.json`、`script.json`、
    `script-audit.json`，以及**权威章节映射表**（卷级 `chapter_index.json`）。

    `authority`：

    - `None`（默认）：自动从工作区的卷目录找 `chapter_index.json`
    - `False`：显式关闭，只用于没有卷级索引的临时实验目录
    - 显式 dict / list / set：直接作为权威表

    返回 `(errors, warnings)`。errors 分三类：

    1. 两份文件声明了不同的 `chapter_uid`，或目录名与全书号不符；
    2. 所有来源两两之间的冲突（**即使 `chapter.json` 缺 uid 也照样抓**）；
    3. uid 不在权威表里、在权威表里重复、或与权威表的编号不符。

    **五份文件自己一致也不作数**——它们可能一起抄错了一个不存在的章号。
    权威表是唯一能发现这种"集体一致地错"的东西。

    唯一的 warning 例外是 v1 `script.json` 没有章节声明（P0-11 迁移前合法），
    以及 `novel_ref.json` / `script-audit.json` 文件本身不存在。
    """
    work = pathlib.Path(work)
    errors, warnings = [], []

    if authority is None:
        # 真实布局 `m1/v1/ch01/work` → 卷目录是 `work.parent.parent`；
        # 也容忍直接传章目录 `m1/v1/ch01` → 卷目录是 `work.parent`。
        for parent in (work.parent.parent, work.parent):
            candidate = parent / "chapter_index.json"
            if candidate.exists():
                loaded = _read_json(candidate)
                if loaded is not None:
                    authority = loaded
                break

    chapter = _read_json(work / "chapter.json")
    if chapter is None:
        return [f"{work}: 缺 chapter.json，无法核对章节身份"], []

    uid = chapter.get("chapter_uid")
    if not uid:
        errors.append("chapter.json 缺 chapter_uid：它是唯一权威身份，不能省")
    else:
        try:
            parse_uid(uid)
        except IdentityError as exc:
            errors.append(f"chapter.json: {exc}")
        errors.extend(chapter_problems(
            {**chapter, "chapter_uid": uid},
            series_slug=chapter.get("series_slug"),
            volume_number=chapter.get("volume_number")))

    # 目录名（ch06）指的是**全书号**，不是卷内号。
    # 章级 work 通常长这样：`m1/v2/ch06/work`——目录名在**上一层**，
    # 所以 `work` 自己不算，要看它的父目录。
    candidates = [work.name]
    if work.name in ("work", "out"):
        candidates.append(work.parent.name)
    for name in candidates:
        m = DIR_RE.match(name)
        if not m or chapter.get("global_chapter_number") is None:
            continue
        if int(m.group("n")) != chapter["global_chapter_number"]:
            errors.append(
                f"目录名 {name!r} 表示全书第 {int(m.group('n'))} 章，"
                f"但 chapter.json 的 global_chapter_number="
                f"{chapter['global_chapter_number']}（chapter_uid={uid}）")

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
    for name, getter in sources.items():
        doc = _read_json(work / name)
        if doc is None:
            continue
        val = getter(doc)
        if not val:
            if name == "script.json":
                # 唯一例外：十章 v1 讲稿没有章节声明，P0-11 迁移后消失。
                warnings.append("script.json 没有声明所属章节（P0-11 迁移后补 chapter_uid）")
            else:
                errors.append(f"{name} 缺 chapter_uid：身份绑定文件不能省，"
                              f"缺了就无法证明它属于这一章")
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
    ref = _read_json(work / "novel_ref.json")
    if ref and ref.get("chapter_id") and chapter.get("id"):
        if ref["chapter_id"] != chapter["id"]:
            errors.append(
                f"novel_ref.json 的 chapter_id={ref['chapter_id']!r} "
                f"与 chapter.json 的 id={chapter['id']!r} 不符")

    # 权威表：五份文件一致也可能一起抄错了一个不存在的章。
    if authority is not False:
        auth = _authority_chapters(authority)
        if auth and uid:
            matches = [c for c in auth if c.get("chapter_uid") == uid]
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
                    if want is not None and got is not None and want != got:
                        errors.append(
                            f"chapter.json 的 {field}={got!r} "
                            f"与权威表中 {uid!r} 的 {want!r} 不符")
        elif authority is not None and not auth:
            warnings.append("权威章节映射表为空，无法核对 uid 是否真实存在")
    return errors, warnings
