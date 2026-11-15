"""S1 分格器：灰度投影分析产出候选格（ffmpeg 仅作解码器，纯标准库）。

算法（确定性，无随机源）：
1. ffmpeg 把整页解码为 8-bit 灰度原始字节；
2. Otsu 自适应阈值二值化（墨线 = 暗）；
3. 行/列最长暗游程 > 页宽/高 30% 视为分格线，相邻行/列并成"线带"；
4. 线带之间的空白区间为候选格区间，行区间 × 列区间做初始框；
5. 去掉面积 < 页面 1% 的碎块、几乎全白的空隙条（gutter，暗像素 < 0.2%）；
6. 过切合并：相邻两框之间分隔线带在框跨度上的暗覆盖率 < 60% 判为
   "不是真分隔"（处理 page_0006 上方全幅大格被下方分栏线过切的情形）；
7. confidence = 0.35 + 0.55 * 真边比例（真边 = 分隔线带且覆盖率 ≥ 60%；
   页边缘算半条），四边齐全 ≈ 0.90，无边框 ≈ 0.35，供人工修正参考；
8. RTL 阅读顺序：先上后下、先右后左。

边界情况（纯白/纯黑/无长线）不抛异常，返回空列表或整页低置信度框 + 警告。
ffmpeg/ffprobe 按 ADR-M1 2.3 的顺序解析，本模块是唯一定义处。
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_KNOWN_BIN = Path(
    r"D:\Windows\Apps\ffmpeg\ffmpeg-master-latest-win64-gpl-shared\bin"
)
_READING_DIRECTION = "rtl"
_RUN = re.compile(rb"\x01+")


def find_ffmpeg():
    """2.3 解析顺序：PANELCAST_FFMPEG → shutil.which → 已知路径。"""
    env = os.environ.get("PANELCAST_FFMPEG")
    if env:
        p = Path(env)
        cand = p / "ffmpeg.exe" if p.is_dir() else p
        if cand.is_file():
            return cand
    which = shutil.which("ffmpeg")
    if which:
        return Path(which)
    cand = _KNOWN_BIN / "ffmpeg.exe"
    if cand.is_file():
        return cand
    raise RuntimeError(
        "error: ffmpeg not found (tried PANELCAST_FFMPEG, PATH, "
        f"{_KNOWN_BIN})"
    )


def find_ffprobe():
    """与 ffmpeg 同目录定位 ffprobe（S0/验收要用）。"""
    env = os.environ.get("PANELCAST_FFMPEG")
    if env:
        p = Path(env)
        base = p if p.is_dir() else p.parent
        cand = base / "ffprobe.exe"
        if cand.is_file():
            return cand
    which = shutil.which("ffprobe")
    if which:
        return Path(which)
    cand = _KNOWN_BIN / "ffprobe.exe"
    if cand.is_file():
        return cand
    raise RuntimeError(
        "error: ffprobe not found next to ffmpeg (tried PANELCAST_FFMPEG "
        "dir, PATH, "
        f"{_KNOWN_BIN})"
    )


def probe_size(ffprobe, path):
    """返回 (width, height)，解析失败抛 RuntimeError。"""
    out = subprocess.run(
        [str(ffprobe), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"error: ffprobe failed for {path}: {out.stderr.strip()}")
    try:
        w, h = (int(v) for v in out.stdout.strip().splitlines()[0].split(","))
    except ValueError:
        raise RuntimeError(f"error: cannot parse size for {path}: {out.stdout!r}")
    return w, h


def decode_gray(ffmpeg, path, w, h):
    """整页解码为 w*h 字节灰度；字节数不符抛 RuntimeError。"""
    out = subprocess.run(
        [str(ffmpeg), "-v", "error", "-i", str(path),
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(
            f"error: ffmpeg decode failed for {path}: "
            f"{out.stderr.decode(errors='replace').strip()}"
        )
    if len(out.stdout) != w * h:
        raise RuntimeError(
            f"error: decode size mismatch for {path}: "
            f"got {len(out.stdout)} bytes, want {w * h}"
        )
    return out.stdout


def detect_content_box(ffmpeg, ffprobe, path, threshold=20):
    """检测页面四周的纯色边（扫描黑边/白边），返回建议裁切框 (x, y, w, h)。

    逐行/逐列看灰度极差：极差 < threshold 视为纯色边。只裁真正贴边的纯色带，
    且裁完不得小于原尺寸的 60%（否则判定为误检，返回整页）。
    """
    w, h = probe_size(ffprobe, path)
    gray = decode_gray(ffmpeg, path, w, h)

    def row_spread(y):
        row = gray[y * w:(y + 1) * w]
        return max(row) - min(row)

    def col_spread(x):
        col = gray[x::w]
        return max(col) - min(col)

    top = 0
    while top < h - 1 and row_spread(top) < threshold:
        top += 1
    bottom = h - 1
    while bottom > top and row_spread(bottom) < threshold:
        bottom -= 1
    left = 0
    while left < w - 1 and col_spread(left) < threshold:
        left += 1
    right = w - 1
    while right > left and col_spread(right) < threshold:
        right -= 1

    cw, ch = right - left + 1, bottom - top + 1
    if cw < w * 0.6 or ch < h * 0.6:      # 误检保护：别把整页裁没了
        return 0, 0, w, h
    return left, top, cw, ch


def _hist256(gray):
    """灰度直方图（256 次 C 级 bytes.count 扫描）。"""
    return [gray.count(v) for v in range(256)]


def otsu_threshold(gray):
    """Otsu 自适应阈值（0-255）。"""
    counts = _hist256(gray)
    total = len(gray)
    sum_all = sum(i * n for i, n in enumerate(counts))
    sum_b = 0
    w_b = 0
    best_t, best_var = 127, -1.0
    for t in range(256):
        w_b += counts[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * counts[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) * (m_b - m_f)
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def _runs(data):
    """bytes 中连续 1 段的 (start, end) 列表。"""
    return [(m.start(), m.end()) for m in _RUN.finditer(data)]


def _max_run_len(data):
    return max((e - s for s, e in _runs(data)), default=0)


def _group_bands(line_idxs):
    """相邻行/列号并成线带 (start, end)。"""
    bands = []
    for i in line_idxs:
        if bands and i == bands[-1][1]:
            bands[-1] = (bands[-1][0], i + 1)
        else:
            bands.append((i, i + 1))
    return bands


def _intervals(size, bands):
    """线带之间的空白区间（面板可能所在）。"""
    ivals = []
    pos = 0
    for s, e in bands:
        if s > pos:
            ivals.append((pos, s))
        pos = e
    if pos < size:
        ivals.append((pos, size))
    return ivals


def _coverage(runs, lo, hi):
    """runs 在 [lo, hi) 上的覆盖率。"""
    if hi <= lo:
        return 0.0
    hit = 0
    for s, e in runs:
        hit += max(0, min(e, hi) - max(s, lo))
    return hit / (hi - lo)


def _find_band(bands, lo, hi):
    """覆盖 [lo, hi] 间隙的线带。"""
    for s, e in bands:
        if s <= lo and e >= hi:
            return (s, e)
    return None


def _dark_fraction(dark, w, x0, y0, x1, y1):
    """框区域暗像素占比（逐行 bytes.count，C 级）。"""
    hit = 0
    area = 0
    for y in range(y0, y1):
        row = dark[y * w + x0:y * w + x1]
        hit += row.count(1)
        area += len(row)
    return hit / area if area else 0.0


def _merge_cells(cells, row_bands, col_bands, dark, w):
    """过切合并：分隔带在相邻框跨度上的暗覆盖率 < 60% 则合并，直到稳定。"""
    vrun_cache = {}
    hrun_cache = {}
    for b in col_bands:
        xm = (b[0] + b[1]) // 2
        vrun_cache[b] = _runs(dark[xm::w])
    for b in row_bands:
        ym = (b[0] + b[1]) // 2
        hrun_cache[b] = _runs(dark[ym * w:(ym + 1) * w])

    changed = True
    while changed:
        changed = False
        # 水平相邻（同一行区间，中间隔着竖线带）
        cells.sort(key=lambda c: (c["y0"], c["x0"]))
        for i in range(len(cells) - 1):
            a, b = cells[i], cells[i + 1]
            if a["y0"] == b["y0"] and a["y1"] == b["y1"] and b["x0"] > a["x1"]:
                band = _find_band(col_bands, a["x1"], b["x0"])
                if band and _coverage(vrun_cache[band], a["y0"], a["y1"]) < 0.6:
                    a["x1"] = b["x1"]
                    cells.remove(b)
                    changed = True
                    break
        if changed:
            continue
        # 垂直相邻（同一列区间，中间隔着横线带）
        cells.sort(key=lambda c: (c["x0"], c["y0"]))
        for i in range(len(cells) - 1):
            a, b = cells[i], cells[i + 1]
            if a["x0"] == b["x0"] and a["x1"] == b["x1"] and b["y0"] > a["y1"]:
                band = _find_band(row_bands, a["y1"], b["y0"])
                if band and _coverage(hrun_cache[band], a["x0"], a["x1"]) < 0.6:
                    a["y1"] = b["y1"]
                    cells.remove(b)
                    changed = True
                    break
    return cells


def _bordered_sides(c, row_bands, col_bands, dark, w, h):
    """四边中真边的数量（线带覆盖率 ≥ 60% 计 1，页边缘计 0.5）。"""
    score = 0.0
    x0, y0, x1, y1 = c["x0"], c["y0"], c["x1"], c["y1"]
    for (edge, lo, hi, bands, vertical) in (
        ("left", x0 - 1, x0, col_bands, True),
        ("right", x1, x1 + 1, col_bands, True),
        ("top", y0 - 1, y0, row_bands, False),
        ("bottom", y1, y1 + 1, row_bands, False),
    ):
        if vertical:
            if (x0 == 0 and edge == "left") or (x1 == w and edge == "right"):
                score += 0.5
                continue
        else:
            if (y0 == 0 and edge == "top") or (y1 == h and edge == "bottom"):
                score += 0.5
                continue
        band = _find_band(bands, lo, hi)
        if not band:
            continue
        if vertical:
            xm = (band[0] + band[1]) // 2
            cov = _coverage(_runs(dark[xm::w]), y0, y1)
        else:
            ym = (band[0] + band[1]) // 2
            cov = _coverage(_runs(dark[ym * w:(ym + 1) * w]), x0, x1)
        if cov >= 0.6:
            score += 1.0
    return score


def analyze_gray(gray, w, h):
    """纯函数：灰度字节 → (候选框列表, 警告列表)。确定性输出。"""
    warnings = []
    total = w * h
    counts = _hist256(gray)
    dark_count = sum(n for k, n in enumerate(counts) if k <= 127)
    if dark_count < 0.02 * total:
        warnings.append("near-blank page: no panels detected")
        return [], warnings
    if dark_count > 0.98 * total:
        warnings.append("near-black page: no panels detected")
        return [], warnings

    t = otsu_threshold(gray)
    table = bytes(1 if i <= t else 0 for i in range(256))
    dark = gray.translate(table)

    # 行/列长直线
    min_run_w = max(int(0.30 * w), 24)
    min_run_h = max(int(0.30 * h), 24)
    line_rows = [y for y in range(h)
                 if _max_run_len(dark[y * w:(y + 1) * w]) >= min_run_w]
    line_cols = [x for x in range(w)
                 if _max_run_len(dark[x::w]) >= min_run_h]
    row_bands = _group_bands(line_rows)
    col_bands = _group_bands(line_cols)

    if not row_bands and not col_bands:
        warnings.append(
            "no separator lines found: whole page as one low-confidence candidate"
        )
        # 无任何边框证据 → 固定最低档置信度
        return [{
            "x": 0, "y": 0, "w": w, "h": h, "confidence": 0.35,
        }], warnings
    else:
        row_ivals = _intervals(h, row_bands)
        col_ivals = _intervals(w, col_bands)
        min_area = 0.01 * total
        cells = []
        for y0, y1 in row_ivals:
            for x0, x1 in col_ivals:
                if (x1 - x0) * (y1 - y0) < min_area:
                    continue
                cells.append({
                    "x0": x0, "y0": y0, "x1": x1, "y1": y1,
                    "_dark": _dark_fraction(dark, w, x0, y0, x1, y1),
                })
        cells = _merge_cells(cells, row_bands, col_bands, dark, w)
        kept = []
        dropped = 0
        for c in cells:
            dark_frac = c.pop("_dark")
            cell_w, cell_h = c["x1"] - c["x0"], c["y1"] - c["y0"]
            thin_strip = cell_h < 0.05 * h or cell_w < 0.05 * w
            if dark_frac < 0.002 and thin_strip:
                # 近全空且为细条 → 分格间的 gutter，不是面板
                dropped += 1
                continue
            kept.append(c)
        if dropped:
            warnings.append(f"dropped {dropped} empty gutter strip(s)")
        if not kept:
            warnings.append("no panels detected")
            return [], warnings
        cells = kept

    panels = []
    for c in sorted(cells, key=lambda c: (c["y0"], -c["x0"])):
        bordered = _bordered_sides(c, row_bands, col_bands, dark, w, h)
        panels.append({
            "x": c["x0"], "y": c["y0"],
            "w": c["x1"] - c["x0"], "h": c["y1"] - c["y0"],
            "confidence": round(0.35 + 0.55 * bordered / 4, 2),
        })
    return panels, warnings


def candidates_dict(page, width, height, panels, warnings):
    """3.1 的 *.candidates.json 结构（source=auto，RTL order）。"""
    out = {
        "page": page,
        "width": width,
        "height": height,
        "reading_direction": _READING_DIRECTION,
        "source": "auto",
        "panels": [],
        "warnings": warnings,
    }
    for i, p in enumerate(sorted(panels, key=lambda p: (p["y"], -p["x"]))):
        out["panels"].append({
            "id": f"p{i + 1}",
            "order": i + 1,
            "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
            "confidence": p["confidence"],
            "locked": False,
        })
    return out


def generate_candidates(work_dir, ffmpeg=None, ffprobe=None):
    """对 work/pages 下每页产出 candidates.json；已存在的一律跳过（只写一次）。"""
    work = Path(work_dir)
    pages_dir = work / "pages"
    panels_dir = work / "panels"
    panels_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg or find_ffmpeg()
    ffprobe = ffprobe or find_ffprobe()
    results = []
    for jpg in sorted(pages_dir.glob("*.jpg")):
        page = jpg.stem
        target = panels_dir / f"{page}.candidates.json"
        if target.exists():
            results.append((page, "kept (exists)"))
            continue
        w, h = probe_size(ffprobe, jpg)
        gray = decode_gray(ffmpeg, jpg, w, h)
        panels, warnings = analyze_gray(gray, w, h)
        doc = candidates_dict(page, w, h, panels, warnings)
        target.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        results.append((page, f"{len(doc['panels'])} panels"))
    return results
