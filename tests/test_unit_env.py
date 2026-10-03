import stat
from pathlib import Path

import pytest

from bpp_mcp import runner, sandbox
from bpp_mcp.tools import env

BPP_VERSION_OUTPUT = """\
Detected CPU features: mmx sse sse2 sse3 ssse3 sse4.1 sse4.2 popcnt avx avx2
bpp v4.8.7_linux_x86_64, 15GB RAM, 32 cores
"""


@pytest.mark.parametrize("name,text,expected", [
    ("bpp", BPP_VERSION_OUTPUT, "4.8.7"),
    ("bpp-lint", "bpp-lint 0.3.5\n", "0.3.5"),
    ("bpp-docs", "bpp-docs 0.1.0\nmanual: 2025-01-01 (embedded)\n", "0.1.0"),
    ("bpp-tree", "bpp-tree 0.1.2\n", "0.1.2"),
    ("bpp", "bpp-lint 0.3.5\n", None),   # must not match another tool's name
    ("bpp-seqs", "garbage\n", None),
])
def test_parse_version(name, text, expected):
    assert env.parse_version(name, text) == expected


def test_version_compare():
    assert env.version_tuple("0.10.0") > env.version_tuple("0.9.9")
    assert env.version_tuple("4.8.7") == (4, 8, 7)


def _install_fakes(d: Path, versions: dict[str, str]):
    for name, out in versions.items():
        p = d / name
        p.write_text(f"#!/bin/sh\nprintf '%s\\n' '{out}'\n")
        p.chmod(p.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setattr(runner, "EXTRA_DIRS", [])
    for name, _ in env.TOOLS:
        monkeypatch.delenv(runner._env_override(name), raising=False)
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(sandbox, "current", sandbox.Sandbox(proj))
    return bindir


def test_all_ready(fake_env):
    _install_fakes(fake_env, {name: f"{name} {minimum}" for name, minimum in env.TOOLS})
    out = env.check_environment()
    assert out["ready"] is True, out["problems"]
    assert all(t["ok"] for t in out["tools"].values())


def test_missing_old_and_unreadable(fake_env):
    fakes = {name: f"{name} {minimum}" for name, minimum in env.TOOLS}
    del fakes["bpp-docs"]
    fakes["bpp-lint"] = "bpp-lint 0.1.0"
    fakes["bpp-tree"] = "something odd"
    _install_fakes(fake_env, fakes)
    out = env.check_environment()
    t = out["tools"]
    assert out["ready"] is False
    assert t["bpp-docs"] == {"found": False, "minimum_version": "0.1.0",
                             "install_hint": "brew install bpp/tap/bpp-docs"}
    assert t["bpp-lint"]["ok"] is False and "older" in t["bpp-lint"]["problem"]
    assert t["bpp-tree"]["ok"] is False and t["bpp-tree"]["version"] is None
    assert len(out["problems"]) == 3


def test_no_project_not_ready(fake_env, monkeypatch):
    _install_fakes(fake_env, {name: f"{name} {minimum}" for name, minimum in env.TOOLS})
    monkeypatch.setattr(sandbox, "current", sandbox.Sandbox(Path("/")))
    out = env.check_environment()
    assert out["ready"] is False and out["project_root"] is None
    assert "no project directory is set" in out["problems"]


def test_set_project_lists_files(tmp_path, monkeypatch):
    (tmp_path / "p" / "loci").mkdir(parents=True)
    (tmp_path / "p" / "imap.txt").write_text("")
    (tmp_path / "p" / ".hidden").write_text("")
    monkeypatch.setattr(sandbox, "current", sandbox.Sandbox(None, tmp_path))
    out = env.set_project("p")
    assert out == {"project_root": str((tmp_path / "p").resolve()),
                   "files": ["imap.txt", "loci/"]}
