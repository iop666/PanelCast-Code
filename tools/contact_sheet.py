"""把 N 页拼成一张对照图，便于一次读多页（人工审阅用，不进出片管线）。

用法：
    python tools/contact_sheet.py --pages m1/v1/work/pages --from 45 --to 48 \
        --out /tmp/sheet_45_48.jpg [--cols 2]

为什么不用纯 Python 拼 JPEG：本仓库是 stdlib-only，没有 Pillow；ffmpeg 已在
依赖里（panels.find_ffmpeg），hstack/vstack 足够，且不会二次压缩源页。
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from panelcast.panels import find_ffmpeg  # noqa: E402


def sheet(pages_dir, first, last, out, cols=2, cell=None):
    ffmpeg = find_ffmpeg()
    files = [Path(pages_dir) / f"page_{i:04d}.jpg" for i in range(first, last + 1)]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        raise SystemExit(f"missing pages: {', '.join(missing)}")
    if cell is None:
        # 一卷里有 62 种页尺寸，格子必须统一，否则 hstack 直接报错。
        from panelcast.panels import find_ffprobe, probe_size
        probe = find_ffprobe()
        sizes = [probe_size(probe, f) for f in files]
        cell = (max(w for w, _ in sizes), max(h for _, h in sizes))
    # yuv420p 要求偶数边长：1009 这种奇数高度会被 scale 抬到 1010，
    # 于是 pad 目标反而比输入小，ffmpeg 直接报 "Padded dimensions cannot be
    # smaller than input dimensions"。格子先取偶数，缩放再强制偶数对齐。
    cw, ch = (cell[0] + cell[0] % 2, cell[1] + cell[1] % 2)
    n = len(files)
    cols = max(1, min(cols, n))
    rows = (n + cols - 1) // cols
    inputs = []
    for f in files:
        inputs += ["-i", str(f)]
    fit = (f"scale={cw}:{ch}:force_original_aspect_ratio=decrease"
           f":force_divisible_by=2,"
           f"pad={cw}:{ch}:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1,"
           f"format=yuvj420p")
    parts = []
    for i in range(n):
        parts.append(f"[{i}:v]{fit}[p{i}]")
    # 补空白格，保证网格完整
    pad = rows * cols - n
    for j in range(pad):
        parts.append(f"color=c=white:s={cw}x{ch}:d=1,format=yuvj420p[p{n + j}]")
    total = rows * cols
    assert total == n + pad
    layout_rows = []
    for r in range(rows):
        cells = "".join(f"[p{r * cols + c}]" for c in range(cols))
        parts.append(f"{cells}hstack=inputs={cols}[r{r}]")
        layout_rows.append(f"[r{r}]")
    joined = "".join(layout_rows)
    if rows == 1:
        # vstack 至少需要 2 路输入；单行时直接把唯一那行当输出
        parts.append(f"{joined}null[out]")
    else:
        parts.append(f"{joined}vstack=inputs={rows}[out]")
    cmd = [str(ffmpeg), "-v", "error", "-y", *inputs,
           "-filter_complex", ";".join(parts), "-map", "[out]",
           "-frames:v", "1", "-q:v", "3", str(out)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise SystemExit(f"ffmpeg failed: {res.stderr.strip()[:400]}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="拼对照图")
    ap.add_argument("--pages", required=True)
    ap.add_argument("--from", dest="first", type=int, required=True)
    ap.add_argument("--to", dest="last", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cols", type=int, default=2)
    a = ap.parse_args(argv)
    path = sheet(a.pages, a.first, a.last, a.out, a.cols)
    print(path)


if __name__ == "__main__":
    main()
