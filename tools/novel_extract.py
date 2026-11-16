"""小说 epub → 纯文本 + 分章索引（S1' / §5.6.1 第一步）。

为什么单独一个脚本：讲稿的底稿是小说，不是漫画。漫画会省略、会改顺序、
甚至有整章是原创的（第一卷第七章「梦幻竹笋」在 18 卷正文里只命中 1 次）。
没有小说原文在手，写稿只能靠猜，实测已经猜错过一次（铁笼泡湖被写成哥布林绑票）。

用法：
    python tools/novel_extract.py --epub "この素晴らしい世界に祝福を！/正文/1.epub" \
        --out .local/source/epub/text

产物：
    novel.txt          逐段一行，段号全局连续（跨章引用不会歧义），强制 LF
    novel_index.json   章 → 段区间 + 字数 + 两个哈希

`novel_index.json` 里的两个哈希用途不同：
    sha256       纯文本内容哈希（不含文件尾部换行）
    file_sha256  落盘文件字节哈希 —— `novel_ref.json` 的 source.text_sha256 对齐这个

只取正文（chapter00..chapter05）。colorpages / Houji / Message / Writer 等
一律排除，否则字数虚高约 6,000，sha256 也会跟着变。
"""

import argparse
import hashlib
import html
import json
import pathlib
import re
import sys
import zipfile

#: 只认正文文件。本卷的 chapter00..chapter05 恰好是 spine 顺序；
#: 换出版社的 epub 若文件名排序 ≠ spine 顺序，要改成读 OPF 的 <spine><itemref>。
BODY_RE = re.compile(r".*/chapter\d+\.xhtml")


def _clean(raw):
    """XHTML → 段落列表。去 script/style、br 与 </p> 转换行、去标签、反转义。"""
    b = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
    b = re.sub(r"(?i)<br\s*/?>", "\n", b)
    b = re.sub(r"(?i)</p>", "\n", b)
    b = re.sub(r"<[^>]+>", "", b)
    return [line.strip() for line in html.unescape(b).splitlines() if line.strip()]


def extract(epub_path):
    """返回 (text, index)。text 每段一行；index 记录全局段号。

    index 里有两个哈希，含义不同，不要混用：
    - `sha256`      纯文本内容的哈希（段之间用 \\n 连接，不含文件尾部换行）
    - `file_sha256` 落盘后 novel.txt 文件字节的哈希
    文件写入时强制 LF，所以同一份 epub 在任何平台产出的 file_sha256 都相同。
    `novel_ref.json` 的 `source.text_sha256` 对齐的是 `file_sha256`。
    """
    z = zipfile.ZipFile(str(epub_path))
    names = sorted(n for n in z.namelist() if BODY_RE.fullmatch(n))
    if not names:
        raise RuntimeError(
            f"error: no chapter*.xhtml in {epub_path}; "
            f"files: {[n for n in z.namelist() if n.endswith('.xhtml')][:6]}"
        )

    chapters, lines = [], []
    for name in names:
        raw = z.read(name).decode("utf-8", "replace")
        paras = _clean(raw)
        if not paras:
            continue
        start = len(lines)
        lines.extend(paras)
        chapters.append({
            "file": name.split("/")[-1],
            "title": paras[0][:40],
            "para_from": start,
            "para_to": len(lines) - 1,
            "paras": len(paras),
            "chars": sum(len(p) for p in paras),
        })

    text = "\n".join(lines)
    index = {
        "schema": "novel-index/v1",
        "source_file": pathlib.Path(epub_path).name,
        "chapters": chapters,
        "total_paras": len(lines),
        "total_chars": sum(c["chars"] for c in chapters),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "file_sha256": hashlib.sha256(render(text).encode("utf-8")).hexdigest(),
    }
    return text, index


def render(text):
    """落盘内容：每段一行 + 一个尾部换行。哈希与写盘都走这里，避免两处不一致。"""
    return text + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="epub → novel.txt + novel_index.json")
    ap.add_argument("--epub", required=True, help="小说 epub 路径")
    ap.add_argument("--out", required=True, help="输出目录（不存在会创建）")
    args = ap.parse_args(argv)

    src = pathlib.Path(args.epub)
    if not src.exists():
        print(f"error: epub not found: {src}", file=sys.stderr)
        return 4

    try:
        text, index = extract(src)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # newline="\n" 是必须的：默认文本模式在 Windows 上会把 \n 翻成 \r\n，
    # 导致同一份 epub 在不同平台算出不同的 file_sha256。
    (out / "novel.txt").write_text(render(text), encoding="utf-8", newline="\n")
    (out / "novel_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")

    print(f"{index['source_file']}: {index['total_paras']} 段 "
          f"{index['total_chars']} 字 sha256 {index['sha256'][:12]}…")
    for c in index["chapters"]:
        print(f"  {c['file']:16s} {c['para_from']:>5}-{c['para_to']:<5} "
              f"{c['chars']:>6} 字  {c['title']}")
    print(f"  file_sha256 {index['file_sha256'][:12]}…（novel_ref 的 source.text_sha256 用这个）")
    print(f"→ {out / 'novel.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
