"""页面介绍页（page profile）校验。

两个层次：

1. **结构校验** —— 拿 `docs/schemas/page-profile.schema.json` 校验实例。
   项目只用标准库，所以这里实现 JSON Schema draft-07 的一个子集：
   `type / enum / const / required / properties / additionalProperties /
   items / minItems / maxItems / pattern / minLength / maxLength /
   minimum / maximum / if-then`。schema 里出现的关键字都在支持列表内，
   `tests/test_profile.py` 有一条用例专门守这件事——一旦有人往 schema 里
   加了未支持的关键字，测试会失败，而不是让校验静默放过。

2. **语义校验** —— 规范 §6.6 那几条光靠 schema 表达不了的规则
   （不编人名、转录自洽、黑白页不许编彩色、已审才可出片）。

用法：

    errors = check_profile(profile, schema)   # 结构 + 语义
    if errors:
        ...
"""

from __future__ import annotations

import re
from datetime import datetime

SCHEMA_PATH = "docs/schemas/page-profile.schema.json"

#: 本模块认识的 schema 关键字。schema 里出现别的关键字 → 视为未实现，报错。
SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "title", "description",
    "type", "enum", "const", "required", "properties", "additionalProperties",
    "items", "minItems", "maxItems", "pattern", "minLength", "maxLength",
    "minimum", "maximum", "if", "then", "format",
})

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}

#: 规范 §6.6 —— 黑白页的 palette 各通道极差上限。
MAX_GRAY_SPREAD = 8


def _type_ok(value, spec) -> bool:
    names = spec if isinstance(spec, list) else [spec]
    for name in names:
        check = _TYPE_CHECKS.get(name)
        if check is None:
            raise ValueError(f"unsupported type {name!r}")
        if check(value):
            return True
    return False


def _json_type(value) -> str:
    for name, check in _TYPE_CHECKS.items():
        if check(value):
            return name
    return type(value).__name__


def validate(instance, schema, path="$"):
    """按 schema 校验 instance，返回错误信息列表（空列表表示通过）。"""
    errors: list[str] = []

    def _walk(value, node, where):
        if not isinstance(node, dict):
            return

        unknown = set(node) - SUPPORTED_KEYWORDS
        if unknown:
            errors.append(f"{where}: schema 用了未支持的关键字 {sorted(unknown)}")
            return

        if "type" in node and not _type_ok(value, node["type"]):
            errors.append(f"{where}: 期望 {node['type']}，实际 {_json_type(value)}")
            return  # 类型不对，后续约束没有意义

        if "const" in node and value != node["const"]:
            errors.append(f"{where}: 必须是 {node['const']!r}，实际 {value!r}")

        if "enum" in node and value not in node["enum"]:
            errors.append(f"{where}: {value!r} 不在允许值 {node['enum']} 内")

        if isinstance(value, str):
            _check_string(value, node, where)
        elif isinstance(value, bool):
            pass
        elif isinstance(value, (int, float)):
            _check_number(value, node, where)
        elif isinstance(value, list):
            _check_array(value, node, where)
        elif isinstance(value, dict):
            _check_object(value, node, where)

        # if/then：只支持「条件成立则追加约束」，够本 schema 用
        if "if" in node and not validate(value, node["if"], where):
            _walk(value, node.get("then"), where)

    def _check_string(value, node, where):
        if "minLength" in node and len(value) < node["minLength"]:
            errors.append(f"{where}: 长度 {len(value)} < {node['minLength']}")
        if "maxLength" in node and len(value) > node["maxLength"]:
            errors.append(f"{where}: 长度 {len(value)} > {node['maxLength']}")
        if "pattern" in node and not re.search(node["pattern"], value):
            errors.append(f"{where}: {value!r} 不匹配 {node['pattern']}")
        if node.get("format") == "date-time":
            try:
                datetime.fromisoformat(value)
            except ValueError:
                errors.append(f"{where}: {value!r} 不是 ISO8601 时间")

    def _check_number(value, node, where):
        if "minimum" in node and value < node["minimum"]:
            errors.append(f"{where}: {value} < 最小 {node['minimum']}")
        if "maximum" in node and value > node["maximum"]:
            errors.append(f"{where}: {value} > 最大 {node['maximum']}")

    def _check_array(value, node, where):
        if "minItems" in node and len(value) < node["minItems"]:
            errors.append(f"{where}: 元素 {len(value)} 个 < {node['minItems']}")
        if "maxItems" in node and len(value) > node["maxItems"]:
            errors.append(f"{where}: 元素 {len(value)} 个 > {node['maxItems']}")
        if "items" in node:
            for i, item in enumerate(value):
                _walk(item, node["items"], f"{where}[{i}]")

    def _check_object(value, node, where):
        for key in node.get("required", []):
            if key not in value:
                errors.append(f"{where}: 缺必填字段 {key!r}")
        props = node.get("properties", {})
        extra = node.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _walk(item, props[key], f"{where}.{key}")
            elif extra is False:
                errors.append(f"{where}: 不允许的字段 {key!r}")
            elif isinstance(extra, dict):
                _walk(item, extra, f"{where}.{key}")

    _walk(instance, schema, path)
    return errors


def check_transcript(profile):
    """§6.6 转录自洽：读不全就必须说清缺什么，不许只压低置信度蒙过去。"""
    text = profile.get("text") or {}
    if text.get("verbatim_complete", True):
        return []
    notes = (profile.get("provenance") or {}).get("reviewer_notes") or ""
    if not notes.strip():
        return [
            "$.text.verbatim_complete: false 时 provenance.reviewer_notes 必须写明缺了哪一块"
        ]
    return []


def check_palette(profile):
    """§6.6 调色板可信：黑白页不许出现彩色。"""
    if (profile.get("layout") or {}).get("is_color", True):
        return []
    errors = []
    for i, color in enumerate((profile.get("visual") or {}).get("palette") or []):
        channels = [int(color[j:j + 2], 16) for j in (1, 3, 5)]
        if max(channels) - min(channels) > MAX_GRAY_SPREAD:
            errors.append(
                f"$.visual.palette[{i}]: {color} 是彩色，但 layout.is_color=false"
                f"（R/G/B 极差 {max(channels) - min(channels)} > {MAX_GRAY_SPREAD}）"
            )
    return errors


def check_characters(profile, known_names=None):
    """§6.6 不编人名：介绍页里的人物必须出现过（台词说话人 或 已知人物表）。"""
    story = profile.get("story") or {}
    speakers = {
        b.get("speaker") for b in (profile.get("text") or {}).get("bubbles") or []
        if b.get("speaker")
    }
    allowed = speakers | set(known_names or ())
    if not allowed:
        return []
    errors = []
    for i, char in enumerate(story.get("characters") or []):
        name = char.get("name")
        if name and name not in allowed:
            errors.append(
                f"$.story.characters[{i}].name: {name!r} 既不是说话人也不在已知人物表里"
            )
    return errors


def check_shippable(profile):
    """§6.6 已审才可出片。"""
    if not (profile.get("provenance") or {}).get("reviewed"):
        return ["$.provenance.reviewed: 未审核的介绍页不允许进入出片流程"]
    return []


def check_profile(profile, schema, known_names=None, for_shipping=False):
    """结构 + 语义全检。返回错误列表，空表示通过。"""
    errors = validate(profile, schema)
    if errors:
        # 结构都不对，语义检查会在残缺数据上得出误导性结论
        return errors
    errors += check_transcript(profile)
    errors += check_palette(profile)
    errors += check_characters(profile, known_names)
    if for_shipping:
        errors += check_shippable(profile)
    return errors


def schema_file():
    """仓库内的 schema 路径（相对本文件解析，不依赖 cwd）。"""
    from pathlib import Path

    return Path(__file__).resolve().parents[1] / SCHEMA_PATH


def load_schema():
    import json

    return json.loads(schema_file().read_text(encoding="utf-8"))


def _main(argv=None):
    import json
    import sys
    from pathlib import Path

    args = list(sys.argv[1:] if argv is None else argv)
    ship = "--ship" in args
    known = []
    paths = []
    rest = iter(args)
    for arg in rest:
        if arg == "--known-names":
            known = [n.strip() for n in next(rest, "").split(",") if n.strip()]
        elif arg.startswith("--"):
            if arg != "--ship":
                print(f"error: 未知参数 {arg}", file=sys.stderr)
                return 2
        else:
            paths.append(arg)

    if not paths:
        print("用法: python -m panelcast.profile <profile.json>... [--ship] "
              "[--known-names 和真,阿克娅]", file=sys.stderr)
        return 2

    try:
        schema = load_schema()
    except OSError as exc:
        print(f"error: 读不到 schema {schema_file()}: {exc}", file=sys.stderr)
        return 4

    bad = 0
    for path in paths:
        try:
            profile = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            bad += 1
            continue
        errors = check_profile(profile, schema, known_names=known, for_shipping=ship)
        if errors:
            bad += 1
            for err in errors:
                print(f"error: {path}: {err}", file=sys.stderr)
        else:
            print(f"ok {profile.get('page', path)}")

    return 3 if bad else 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
