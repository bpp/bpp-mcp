import os
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from bpp_mcp.sandbox import Sandbox


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "data" / "a.txt").write_text("x")
    (tmp_path / "secret.txt").write_text("s")
    return root


def test_relative_inside(proj):
    sb = Sandbox(proj)
    assert sb.resolve("data/a.txt") == proj / "data" / "a.txt"
    assert sb.resolve(".") == proj.resolve()
    assert sb.resolve("data/../data/a.txt") == proj / "data" / "a.txt"


def test_dotdot_escape(proj):
    sb = Sandbox(proj)
    for p in ["../secret.txt", "data/../../secret.txt", "..", "../../etc/passwd"]:
        with pytest.raises(ToolError, match="outside the project"):
            sb.resolve(p)


def test_absolute_paths(proj):
    sb = Sandbox(proj)
    assert sb.resolve(str(proj / "data" / "a.txt")) == proj / "data" / "a.txt"
    with pytest.raises(ToolError, match="outside the project"):
        sb.resolve("/etc/passwd")
    with pytest.raises(ToolError, match="outside the project"):
        sb.resolve(str(proj.parent / "secret.txt"))


def test_prefix_sibling_is_outside(proj):
    sibling = proj.parent / (proj.name + "-other")
    sibling.mkdir()
    with pytest.raises(ToolError, match="outside the project"):
        Sandbox(proj).resolve(str(sibling))


def test_symlink_escape(proj):
    (proj / "link").symlink_to(proj.parent / "secret.txt")
    (proj / "dirlink").symlink_to(proj.parent)
    sb = Sandbox(proj)
    with pytest.raises(ToolError, match="outside the project"):
        sb.resolve("link")
    with pytest.raises(ToolError, match="outside the project"):
        sb.resolve("dirlink/secret.txt")


def test_symlink_inside_is_fine(proj):
    (proj / "alias.txt").symlink_to(proj / "data" / "a.txt")
    assert Sandbox(proj).resolve("alias.txt") == proj / "data" / "a.txt"


def test_symlinked_root(proj, tmp_path):
    link_root = tmp_path / "rootlink"
    link_root.symlink_to(proj)
    assert Sandbox(link_root).resolve("data/a.txt") == proj / "data" / "a.txt"


def test_bad_inputs(proj):
    sb = Sandbox(proj)
    for p in ["", "  ", "a\0b"]:
        with pytest.raises(ToolError):
            sb.resolve(p)


def test_must_exist(proj):
    sb = Sandbox(proj)
    assert sb.resolve("new.ctl") == proj / "new.ctl"
    with pytest.raises(ToolError, match="does not exist"):
        sb.resolve("new.ctl", must_exist=True)


def test_filesystem_root_means_no_project():
    sb = Sandbox(Path("/"))
    assert sb.root is None
    with pytest.raises(ToolError, match="BPP_MCP_ROOT"):
        sb.resolve("x")


def test_from_env(monkeypatch, proj):
    monkeypatch.setenv("BPP_MCP_ROOT", str(proj))
    monkeypatch.delenv("BPP_MCP_PROJECTS_DIR", raising=False)
    sb = Sandbox.from_env()
    assert sb.root == proj.resolve() and sb.projects_dir is None


def test_set_project(tmp_path):
    projects = tmp_path / "projects"
    (projects / "p1").mkdir(parents=True)
    (projects / "file.txt").write_text("")
    sb = Sandbox(None, projects)
    with pytest.raises(ToolError, match="set_project"):
        sb.resolve("x")
    assert sb.set_project("p1") == projects / "p1"
    assert sb.resolve("a") == projects / "p1" / "a"
    for bad, msg in [("..", "outside"), ("../..", "outside"), (".", "inside the projects"),
                     ("missing", "not an existing folder"), ("file.txt", "not an existing folder")]:
        with pytest.raises(ToolError, match=msg):
            sb.set_project(bad)
    assert sb.root == projects / "p1"  # unchanged by the failed calls


def test_set_project_disabled(proj):
    with pytest.raises(ToolError, match="disabled"):
        Sandbox(proj).set_project("x")


def test_rel(proj):
    sb = Sandbox(proj)
    assert sb.rel(sb.resolve("data/a.txt")) == os.path.join("data", "a.txt")
    assert sb.rel(sb.resolve(".")) == "."


def test_from_env_projects_dir_ignores_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("BPP_MCP_ROOT", raising=False)
    monkeypatch.setenv("BPP_MCP_PROJECTS_DIR", str(tmp_path))
    sb = Sandbox.from_env()
    assert sb.root is None and sb.projects_dir == tmp_path.resolve()
