"""Project-root confinement and path policy.

Every path a tool accepts goes through ``resolve()``. A path is accepted only
if, after resolving symlinks, it lies inside the project root.

The root comes from, in order:

1. ``set_project()``, when ``BPP_MCP_PROJECTS_DIR`` is set. This is for hosts
   such as Claude Desktop, where one server process serves many projects and
   the working directory at startup means nothing. The new root must be a
   directory inside ``BPP_MCP_PROJECTS_DIR``.
2. ``BPP_MCP_ROOT``.
3. The working directory at startup, unless ``BPP_MCP_PROJECTS_DIR`` is set
   or the working directory is the filesystem root (some desktop hosts start
   servers in ``/``). Then no project is set, and every path is refused until
   one is.
"""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError


class Sandbox:
    def __init__(self, root: Path | None = None, projects_dir: Path | None = None):
        self.projects_dir = projects_dir.resolve() if projects_dir else None
        self.root = root.resolve() if root else None
        if self.root is not None and self.root == Path(self.root.anchor):
            self.root = None

    @classmethod
    def from_env(cls) -> Sandbox:
        env_root = os.environ.get("BPP_MCP_ROOT")
        projects = os.environ.get("BPP_MCP_PROJECTS_DIR")
        if env_root:
            root = Path(env_root).expanduser()
        else:
            # With a projects directory the user picks the project; the
            # startup directory says nothing about it.
            root = None if projects else Path.cwd()
        return cls(root, Path(projects).expanduser() if projects else None)

    def require_root(self) -> Path:
        if self.root is None:
            if self.projects_dir is not None:
                raise ToolError(
                    "No project directory is selected. Ask the user which project "
                    f"folder under {self.projects_dir} to use, then call set_project.")
            raise ToolError(
                "No project directory is configured. The server was started without "
                "BPP_MCP_ROOT in the filesystem root; set BPP_MCP_ROOT (or "
                "BPP_MCP_PROJECTS_DIR) in the host's MCP server configuration.")
        return self.root

    def resolve(self, p: str, *, must_exist: bool = False) -> Path:
        """Resolve ``p`` (relative to the root, or absolute) inside the root."""
        root = self.require_root()
        if not isinstance(p, str) or not p.strip():
            raise ToolError("empty path")
        if "\0" in p:
            raise ToolError("path contains a null byte")
        q = (root / Path(p).expanduser()).resolve()
        if not _inside(q, root):
            raise ToolError(
                f"path '{p}' resolves outside the project directory {root}; "
                "only files inside the project can be used")
        if must_exist and not q.exists():
            raise ToolError(f"'{p}' does not exist in the project directory {root}")
        return q

    def rel(self, q: Path) -> str:
        """Display form of a resolved path: relative to the root."""
        root = self.require_root()
        return "." if q == root else str(q.relative_to(root))

    def set_project(self, p: str) -> Path:
        if self.projects_dir is None:
            raise ToolError(
                "set_project is disabled: the server was started with a fixed project "
                "directory. Set BPP_MCP_PROJECTS_DIR in the host configuration to enable it.")
        q = (self.projects_dir / Path(p).expanduser()).resolve()
        if not _inside(q, self.projects_dir):
            raise ToolError(f"'{p}' is outside the projects directory {self.projects_dir}")
        if q == self.projects_dir:
            raise ToolError("choose a project folder inside the projects directory, not the directory itself")
        if not q.is_dir():
            raise ToolError(f"'{p}' is not an existing folder in {self.projects_dir}")
        self.root = q
        return q


def _inside(q: Path, root: Path) -> bool:
    return q == root or root in q.parents


current = Sandbox.from_env()


def resolve(p: str, *, must_exist: bool = False) -> Path:
    return current.resolve(p, must_exist=must_exist)
