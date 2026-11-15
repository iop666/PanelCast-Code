"""把连续 N 页的**同一条横带**裁下来竖着拼成一张图，用来快速找章节横幅。

为什么需要它：本作的章节横幅位置不固定（第一卷 p45 在页首，p75/p105/p137
在页脚），只按页首找会漏章。逐页看整幅太贵，但横幅一定落在页首或页脚那条
窄带里，所以只看带子就够了。

用法：
    python tools/strip_sheet.py --pages m1/v2/work/pages --from 1 --to 146 \
        --band bottom --out D:/tmp/bottom.jpg [--count 10] [--ratio 0.16]
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panelcast.panels import find_ffmpeg  # noqa: E402


def strip(band, ratio):
    """单页裁剪表达式：返回 ffmpeg -vf 字符串。"""
    h = f"ih*{ratio}"
    if band == "bottom":
        return f"crop=iw:{h}:0:ih-{h}"
    return f"crop=iw:{h}:0:0"


# vstack 要求每格等宽，扫描页宽度在 640~680 之间浮动，统一缩到 672 保证能拼。
CELL_W = 672


def build(pages_dir, first, last, out, band="bottom", count=10, ratio=0.16):
    ffmpeg = find_ffmpeg()
    pages_dir = Path(pages_dir)
    nums = list(range(first, last + 1))
    if not nums:
        raise SystemExit("empty range")
    sheets = []
    for start in range(0, len(nums), count):
        chunk = nums[start:start + count]
        files = [pages_dir / f"page_{n:04d}.jpg" for n in chunk]
        missing = [f.name for f in files if not f.exists()]
        if missing:
            raise SystemExit(f"missing: {', '.join(missing)}")
        inputs = []
        for f in files:
            inputs += ["-i", str(f)]
        parts = []
        for i in range(len(files)):
            parts.append(
                f"[{i}:v]{strip(band, ratio)},"
                f"scale={CELL_W}:-2,setsar=1,format=yuvj420p[s{i}]"
            )
        if len(files) == 1:
            parts.append("[s0]null[v]")
        else:
            joined = "".join(f"[s{i}]" for i in range(len(files)))
            parts.append(f"{joined}vstack=inputs={len(files)}[v]")
        dst = Path(str(out).replace(".jpg", f"_{chunk[0]:04d}.jpg"))
        cmd = [str(ffmpeg), "-v", "error", "-y", *inputs,
               "-filter_complex", ";".join(parts), "-map", "[v]",
               "-frames:v", "1", "-q:v", "3", str(dst)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            raise SystemExit(f"ffmpeg failed on {chunk[0]}: "
                             f"{res.stderr.strip()[:300]}")
        sheets.append(str(dst))
    return sheets


def main(argv=None):
    ap = argparse.ArgumentParser(description="横带对照图（找章节横幅）")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--from", dest="first", type=int, required=True)
    ap.add_argument("--to", dest="last", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--band", choices=["bottom", "top"], default="bottom")
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--ratio", type=float, default=0.16)
    a = ap.parse_args(argv)
    for p in build(a.pages, a.first, a.last, a.out, a.band, a.count, a.ratio):
        print(p)


if __name__ == "__main__":
    main()
