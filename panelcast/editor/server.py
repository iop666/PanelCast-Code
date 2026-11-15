"""S2 分格人工修正编辑器：标准库 http.server，只读写 m1/work/ 下文件。

路由：
- GET  /                        → 编辑器页面（static/index.html）
- GET  /api/pages               → 页面列表（候选数/确认状态）
- GET  /api/page/<n>/panels     → panels.json 优先，否则 candidates.json
- POST /api/page/<n>/panels     → 保存人工确认结果（source=manual，temp+replace 原子写）
- GET  /api/page/<n>/image      → 页面原图

安全：页名只允许 [A-Za-z0-9_-]+，解析后必须仍落在 work/ 内（路径穿越一律 404）。
启动：python -m panelcast m1 edit --work m1/work [--port 8642]
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_STATIC = Path(__file__).resolve().parent / "static"
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class _Editor:
    """work 目录绑定 + 请求处理（不继承 handler，便于测试）。"""

    def __init__(self, work_dir):
        self.work = Path(work_dir).resolve()
        self.pages_dir = self.work / "pages"
        self.panels_dir = self.work / "panels"

    # ---- 路径安全 ----
    def safe_page_dir(self, name):
        if not _NAME_RE.match(name or ""):
            return None
        d = self.pages_dir / name
        try:
            if d.resolve().parent != self.pages_dir.resolve():
                return None
        except OSError:
            return None
        return d

    def page_file(self, name, suffix):
        if self.safe_page_dir(name) is None:
            return None
        f = self.pages_dir / f"{name}{suffix}"
        try:
            if f.resolve().parent != self.pages_dir.resolve():
                return None
        except OSError:
            return None
        return f

    def panels_file(self, name, suffix):
        f = (self.panels_dir / f"{name}{suffix}")
        if not _NAME_RE.match(name):
            return None
        try:
            if f.resolve().parent != self.panels_dir.resolve():
                return None
        except OSError:
            return None
        return f

    # ---- API ----
    def list_pages(self):
        pages = []
        for jpg in sorted(self.pages_dir.glob("*.jpg")):
            name = jpg.stem
            cand = self.panels_file(name, ".candidates.json")
            manual = self.panels_file(name, ".panels.json")
            cand_count = manual_count = 0
            confirmed = False
            source = "auto"
            if cand and cand.exists():
                try:
                    cand_count = len(json.loads(cand.read_text(encoding="utf-8"))
                                     .get("panels", []))
                except (OSError, ValueError):
                    pass
            if manual and manual.exists():
                try:
                    doc = json.loads(manual.read_text(encoding="utf-8"))
                    manual_count = len(doc.get("panels", []))
                    source = doc.get("source", "auto")
                    confirmed = source == "manual"
                except (OSError, ValueError):
                    pass
            pages.append({
                "name": name,
                "candidates": cand_count,
                "manual": manual_count,
                "confirmed": confirmed,
                "source": source,
            })
        return {"pages": pages}

    def get_panels(self, name):
        manual = self.panels_file(name, ".panels.json")
        cand = self.panels_file(name, ".candidates.json")
        if manual is None or cand is None:
            return None, 404
        if manual.exists():
            try:
                return {
                    "data": json.loads(manual.read_text(encoding="utf-8")),
                    "is_manual": True,
                }, 200
            except (OSError, ValueError) as exc:
                return {"error": f"bad panels.json: {exc}"}, 500
        if cand.exists():
            try:
                return {
                    "data": json.loads(cand.read_text(encoding="utf-8")),
                    "is_manual": False,
                }, 200
            except (OSError, ValueError) as exc:
                return {"error": f"bad candidates.json: {exc}"}, 500
        return {"error": f"no panels for {name}"}, 404

    def save_panels(self, name, body):
        manual = self.panels_file(name, ".panels.json")
        cand = self.panels_file(name, ".candidates.json")
        if manual is None or cand is None:
            return None, 404
        meta = {}
        if cand.exists():
            try:
                meta = json.loads(cand.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return {"error": f"bad candidates.json: {exc}"}, 500
        elif manual.exists():
            try:
                meta = json.loads(manual.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return {"error": f"bad panels.json: {exc}"}, 500
        else:
            return {"error": "no candidates/panels metadata for page"}, 400

        try:
            raw = body["panels"]
            assert isinstance(raw, list) and raw
            panels = []
            for p in raw:
                panels.append({
                    "id": str(p["id"]),
                    "order": int(p["order"]),
                    "x": max(0, int(p["x"])),
                    "y": max(0, int(p["y"])),
                    "w": max(1, int(p["w"])),
                    "h": max(1, int(p["h"])),
                    "confidence": float(p.get("confidence", 0.5)),
                    "locked": bool(p.get("locked", False)),
                })
        except (KeyError, TypeError, ValueError, AssertionError):
            return {"error": "malformed panels payload"}, 400

        width = int(meta.get("width", 0))
        height = int(meta.get("height", 0))
        if width <= 0 or height <= 0:
            return {"error": "missing page metadata (width/height)"}, 400
        for p in panels:
            p["x"] = min(p["x"], max(0, width - 1))
            p["y"] = min(p["y"], max(0, height - 1))
            p["w"] = min(p["w"], width - p["x"])
            p["h"] = min(p["h"], height - p["y"])
        panels.sort(key=lambda p: p["order"])
        for i, p in enumerate(panels):
            p["order"] = i + 1

        doc = {
            "page": meta.get("page", name),
            "width": width,
            "height": height,
            "reading_direction": meta.get("reading_direction", "rtl"),
            "source": "manual",
            "panels": panels,
        }
        tmp = manual.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, manual)
        return {"ok": True, "confirmed": True, "count": len(panels)}, 200


def make_handler(editor):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # 静默访问日志
            pass

        def _json(self, obj, status=200):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _file(self, path, ctype):
            try:
                data = path.read_bytes()
            except OSError:
                self._json({"error": f"cannot read {path.name}"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                return self._file(_STATIC / "index.html",
                                  "text/html; charset=utf-8")
            m = re.match(r"^/api/pages$", path)
            if m:
                return self._json(editor.list_pages())
            m = re.match(r"^/api/page/([^/]+)/panels$", path)
            if m:
                data, status = editor.get_panels(m.group(1))
                return self._json(data, status)
            m = re.match(r"^/api/page/([^/]+)/image$", path)
            if m:
                f = editor.page_file(m.group(1), ".jpg")
                if f is None or not f.exists():
                    return self._json({"error": "not found"}, 404)
                return self._file(f, "image/jpeg")
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            m = re.match(r"^/api/page/([^/]+)/panels$", path)
            if not m:
                return self._json({"error": "not found"}, 404)
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (OSError, ValueError):
                return self._json({"error": "bad request body"}, 400)
            data, status = editor.save_panels(m.group(1), body)
            return self._json(data, status)

    return Handler


def serve(work_dir, port=8642):
    """阻塞式启动本地编辑器（Ctrl-C 退出）。"""
    editor = _Editor(work_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(editor))
    print(f"panelcast m1 editor: http://127.0.0.1:{port}/  (work={editor.work})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
