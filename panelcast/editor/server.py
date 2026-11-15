"""S2/S3 人工修正编辑器：标准库 http.server，只读写 m1/work/ 下文件。

两个标签页：

- 分格（S2）：拖框确认 panels.json
- 介绍页（S3）：校对 page profile 的语义字段

路由：
- GET  /                        → 编辑器页面（static/index.html）
- GET  /api/pages               → 页面列表（候选数/确认状态/介绍页状态）
- GET  /api/page/<n>/panels     → panels.json 优先，否则 candidates.json
- POST /api/page/<n>/panels     → 保存人工确认结果（source=manual，temp+replace 原子写）
- GET  /api/page/<n>/image      → 页面原图
- GET  /api/page/<n>/profile    → 介绍页 + 表单枚举 + 已知人物名
- POST /api/page/<n>/profile    → 校验后保存（reviewed=true）

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


def _collect_enums(node, path="$", out=None):
    """把 schema 里所有 enum 按 JSON 路径收集起来，供前端生成下拉框。

    不写死枚举值：schema 改了前端自动跟上，不会出现"界面里还留着旧选项"。
    """
    if out is None:
        out = {}
    if isinstance(node, dict):
        if isinstance(node.get("enum"), list):
            out[path] = list(node["enum"])
        for key, value in node.items():
            if key == "properties":
                for name, sub in value.items():
                    _collect_enums(sub, f"{path}.{name}", out)
            elif key == "items":
                _collect_enums(value, f"{path}.items", out)
            elif key in ("then", "else", "if"):
                _collect_enums(value, path, out)
            elif key in ("type", "enum", "const", "required", "pattern",
                         "minLength", "maxLength", "minimum", "maximum",
                         "format", "additionalProperties", "$schema", "$id",
                         "title", "description"):
                continue
    return out


def _ship_errors(doc, known_names):
    """出片门禁的差距（占位符/未审阅），只做提示，不阻止保存草稿。"""
    from ..profile import check_placeholders, check_shippable

    return check_placeholders(doc) + check_shippable(doc)


def _profile_state(editor, name):
    """页面列表里的介绍页标记：none / draft / reviewed。"""
    f = editor.profile_file(name)
    if f is None or not f.exists():
        return "none"
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "bad"
    return "reviewed" if (doc.get("provenance") or {}).get("reviewed") else "draft"



class _Editor:
    """work 目录绑定 + 请求处理（不继承 handler，便于测试）。"""

    def __init__(self, work_dir):
        self.work = Path(work_dir).resolve()
        self.pages_dir = self.work / "pages"
        self.panels_dir = self.work / "panels"
        self.profiles_dir = self.work / "profiles"

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

    def profile_file(self, name):
        if not _NAME_RE.match(name or ""):
            return None
        f = self.profiles_dir / f"{name}.profile.json"
        try:
            if f.resolve().parent != self.profiles_dir.resolve():
                return None
        except OSError:
            return None
        return f

    def _read_profile(self, name):
        f = self.profile_file(name)
        if f is None or not f.exists():
            return None, None
        try:
            return f, json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return f, None

    def known_names(self):
        """全卷出现过的说话人 + 已登记人物名。

        介绍页里写的人物必须在这张表里（§6.6 不编人名）。表是跨页累计的，
        所以同一页顺序校对时，后面页能引用前面页出现过的角色。
        """
        names = set()
        if not self.profiles_dir.is_dir():
            return []
        for f in sorted(self.profiles_dir.glob("*.profile.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for b in (doc.get("text") or {}).get("bubbles") or []:
                if b.get("speaker"):
                    names.add(b["speaker"])
            for c in (doc.get("story") or {}).get("characters") or []:
                if c.get("name"):
                    names.add(c["name"])
        return sorted(names)

    def get_profile(self, name):
        from ..profile import load_schema

        f, doc = self._read_profile(name)
        if f is None:
            return {"error": f"no profile dir for {name}"}, 404
        if doc is None:
            return {"error": f"no profile for {name}"}, 404
        return {
            "data": doc,
            "enums": _collect_enums(load_schema()),
            "known_names": self.known_names(),
            "shippable_errors": _ship_errors(doc, self.known_names()),
        }, 200

    def save_profile(self, name, body):
        from ..profile import check_profile, load_schema

        f = self.profile_file(name)
        if f is None:
            return {"error": "bad page name"}, 404
        _, doc = self._read_profile(name)
        if doc is None:
            return {"error": f"no profile for {name} (run m1 profile first)"}, 404
        if not isinstance(body, dict):
            return {"error": "malformed profile payload"}, 400
        # 只接受可编辑的语义字段，几何/来源字段（source/layout 尺寸）由测量决定
        for key in ("story", "text", "visual", "reuse"):
            if key in body:
                doc[key] = body[key]
        if "layout" in body and isinstance(body["layout"], dict):
            # 只允许改人工判断项，尺寸/颜色统计保持测量值
            for key in ("kind", "has_splash", "borderless", "panel_count",
                        "reading_direction", "text_density"):
                if key in body["layout"]:
                    doc.setdefault("layout", {})[key] = body["layout"][key]
        prov = doc.setdefault("provenance", {})
        prov["reviewed"] = True
        prov["generated_by"] = "editor"
        if body.get("reviewer_notes") is not None:
            prov["reviewer_notes"] = str(body["reviewer_notes"])

        errors = check_profile(doc, load_schema(), self.known_names())
        if errors:
            return {"error": "校验未通过", "errors": errors}, 400
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2,
                                  sort_keys=True), encoding="utf-8")
        os.replace(tmp, f)
        return {"ok": True, "reviewed": True,
                "shippable_errors": _ship_errors(doc, self.known_names())}, 200

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
                "profile": _profile_state(self, name),
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
            m = re.match(r"^/api/page/([^/]+)/profile$", path)
            if m:
                data, status = editor.get_profile(m.group(1))
                return self._json(data, status)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (OSError, ValueError):
                return self._json({"error": "bad request body"}, 400)
            m = re.match(r"^/api/page/([^/]+)/profile$", path)
            if m:
                data, status = editor.save_profile(m.group(1), body)
                return self._json(data, status)
            m = re.match(r"^/api/page/([^/]+)/panels$", path)
            if not m:
                return self._json({"error": "not found"}, 404)
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
