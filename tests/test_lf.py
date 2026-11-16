"""跨平台换行复验：`.gitattributes` 真的能挡住 CRLF 吗？

为什么值得单独测：`novel_ref.json` / `script-audit.json` 里绑的是**文件字节**的
sha256。Windows 上 `core.autocrlf=true` 会把 LF 检出成 CRLF，哈希立刻对不上，
门禁会误报"文件被改过"。这不是理论风险——本机就是 `autocrlf=true`。

14/14 blob 一致只能证明**那一次推送**没问题，证明不了**新克隆**没问题：
blob 里存的是 LF，能不能原样落到磁盘取决于检出时的过滤规则。

所以这里做真正的新克隆验证：造一个临时仓库，用三种 `core.autocrlf` 取值
（`true` / `input` / `false`）分别克隆，逐字节比对。

> 边界说明：本机只有 Windows，Linux 侧无法实跑。但 Linux 的默认值是
> `false`（或 `input`），两者都在覆盖范围内；真正决定结果的是 `.gitattributes`，
> 不是操作系统。
"""

import hashlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

GITATTRIBUTES = """* text=auto eol=lf

*.jpg binary
"""

JSON_BODY = ('{\n  "schema": "script-audit/v2",\n'
             '  "chapter_uid": "konosuba-manga-v01-ch01"\n}\n')
TEXT_BODY = "第一行\n第二行\n"


def git(*args, cwd):
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t",
         "-c", "commit.gpgsign=false"] + list(args),
        cwd=str(cwd), capture_output=True, text=True)


def git_available():
    try:
        return subprocess.run(["git", "--version"], capture_output=True).returncode == 0
    except OSError:
        return False


@unittest.skipUnless(git_available(), "git 不可用")
class TestLineEndingsSurviveFreshClone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.origin = self.root / "origin"
        self.origin.mkdir()
        (self.origin / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8",
                                                    newline="\n")
        (self.origin / "audit.json").write_text(JSON_BODY, encoding="utf-8",
                                               newline="\n")
        (self.origin / "note.md").write_text(TEXT_BODY, encoding="utf-8",
                                            newline="\n")
        for args in (("init", "-b", "main"), ("add", "-A"),
                     ("commit", "-m", "init")):
            r = git(*args, cwd=self.origin)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.want = {
            "audit.json": hashlib.sha256(JSON_BODY.encode()).hexdigest(),
            "note.md": hashlib.sha256(TEXT_BODY.encode()).hexdigest(),
        }

    def tearDown(self):
        self.tmp.cleanup()

    def _clone(self, autocrlf):
        dst = self.root / f"clone-{autocrlf or 'default'}"
        r = subprocess.run(
            ["git", "-c", f"core.autocrlf={autocrlf}", "clone", "--no-local",
             str(self.origin), str(dst)],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return dst

    def test_lf_survives_every_autocrlf_setting(self):
        for setting in ("true", "input", "false"):
            with self.subTest(core_autocrlf=setting):
                dst = self._clone(setting)
                for name, want in self.want.items():
                    raw = (dst / name).read_bytes()
                    self.assertNotIn(b"\r\n", raw,
                                     f"{name} 在 autocrlf={setting} 下被检出成 CRLF")
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), want,
                                     f"{name} 在 autocrlf={setting} 下哈希变了")

    def test_without_gitattributes_crlf_does_leak(self):
        """反证：去掉 `.gitattributes`，`autocrlf=true` 确实会改字节。

        这条用例存在的意义是证明上一条**不是空跑**——如果环境本身不会转换，
        上一条测不出任何东西。
        """
        (self.origin / ".gitattributes").unlink()
        for args in (("add", "-A"), ("commit", "-m", "drop attrs")):
            r = git(*args, cwd=self.origin)
            self.assertEqual(r.returncode, 0, r.stderr)
        dst = self._clone("true")
        raw = (dst / "note.md").read_bytes()
        self.assertIn(b"\r\n", raw,
                      "本机 git 没有做 CRLF 转换，这条反证失效——"
                      "请检查 core.autocrlf 或 git 配置")
        self.assertNotEqual(hashlib.sha256(raw).hexdigest(), self.want["note.md"])

    def test_repo_has_gitattributes(self):
        """本仓库必须带 `.gitattributes`，否则哈希绑定的文件一克隆就废。"""
        attrs = ROOT / ".gitattributes"
        self.assertTrue(attrs.exists(), "缺 .gitattributes")
        text = attrs.read_text(encoding="utf-8")
        self.assertIn("eol=lf", text)


#: 绑了字节哈希的文件。换行一变，`m1 novel check` 就会误报"被改过"。
HASH_BOUND = [
    "m1/v1/ch01/work/novel_ref.json",
    "m1/v1/ch01/work/script-audit.json",
]


@unittest.skipUnless(git_available(), "git 不可用")
class TestRealRepoClonesByteIdentical(unittest.TestCase):
    """真仓库新克隆：检出结果必须与工作区逐字节一致。

    这是比"blob sha 一致"更强的一条：blob 里存的是 LF，能不能原样落到磁盘
    还取决于检出时的 `core.autocrlf` 与 `.gitattributes`。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # 工作区有未提交改动时比不了——那不是换行问题，是内容本来就不同
        r = subprocess.run(["git", "status", "--porcelain"] + HASH_BOUND,
                           cwd=str(ROOT), capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("不是 git 仓库")
        if r.stdout.strip():
            self.skipTest("哈希绑定文件有未提交改动，先提交再跑这条")

    def tearDown(self):
        self.tmp.cleanup()

    def test_fresh_clone_matches_working_tree(self):
        dst = Path(self.tmp.name) / "clone"
        r = subprocess.run(
            ["git", "-c", "core.autocrlf=true", "clone", "--no-local", "--depth", "1",
             str(ROOT), str(dst)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        for rel in HASH_BOUND:
            want = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
            raw = (dst / rel).read_bytes()
            self.assertNotIn(b"\r\n", raw, f"{rel} 克隆后变成 CRLF")
            self.assertEqual(hashlib.sha256(raw).hexdigest(), want,
                             f"{rel} 克隆后哈希与工作区不一致")


@unittest.skipUnless(git_available(), "git 不可用")
class TestIndexStoresLF(unittest.TestCase):
    """索引侧守卫：仓库里到底存的是 LF 还是 CRLF。

    这一条比"克隆后比对"更直接。`git ls-files --eol` 的 `i/` 列就是 blob 里
    实际存的字节。只要 `i/crlf` 数量为 0，**任何平台**克隆出来的文本文件都不可能
    是 CRLF——换行在入库那一刻就定死了，跟检出机器的操作系统无关。

    上一类用例只覆盖 2 个哈希绑定文件，这一条覆盖**全仓**。
    """

    def _eol_rows(self):
        r = subprocess.run(["git", "ls-files", "--eol"], cwd=str(ROOT),
                           capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("不是 git 仓库")
        rows = []
        for line in r.stdout.splitlines():
            if "\t" not in line:
                continue
            info, path = line.split("\t", 1)
            rows.append((info.split(), path))
        return rows

    def test_no_crlf_blob_in_index(self):
        rows = self._eol_rows()
        self.assertTrue(rows, "索引为空？")
        bad = [p for info, p in rows if info and info[0] == "i/crlf"]
        self.assertEqual(bad, [],
                         "以下文件在仓库里存的是 CRLF，新克隆到 Linux 也会是 CRLF，"
                         "所有字节哈希会失效：" + ", ".join(bad[:10]))

    def test_every_file_has_lf_attribute(self):
        """`* text=auto eol=lf` 必须真的匹配到每一个文件。

        漏掉一类扩展名，那类文件就会按 `core.autocrlf` 走，行为随机器而变。
        """
        rows = self._eol_rows()
        missing = [p for info, p in rows
                   if not any("eol=lf" in part for part in info[2:])]
        self.assertEqual(missing, [],
                         "以下文件没有命中 eol=lf 规则：" + ", ".join(missing[:10]))


if __name__ == "__main__":
    unittest.main()
