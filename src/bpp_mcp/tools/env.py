"""check_environment: which bpp tools are installed, and are they new enough."""
from __future__ import annotations

import importlib.metadata
import platform
import re
from pathlib import Path

from .. import __version__, runner, sandbox

# (binary, minimum version). Minimums are the versions this server was
# written against; older ones lack JSON fields or flags the tools rely on.
TOOLS: list[tuple[str, str]] = [
    ("bpp-seqs", "0.2.0"),
    ("bpp-tree", "0.1.2"),
    ("bpp-lint", "0.3.5"),
    ("bpp-docs", "0.1.0"),
    ("bpp", "4.8.7"),
]


def parse_version(name: str, text: str) -> str | None:
    """Version from ``<name> [v]X.Y.Z`` anywhere in the --version output."""
    m = re.search(rf"(?m)^{re.escape(name)}\s+v?(\d+(?:\.\d+)+)", text)
    return m.group(1) if m else None


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def probe(name: str, minimum: str) -> dict:
    info: dict = {"found": False, "minimum_version": minimum}
    path = runner.find(name)
    if not path:
        info["install_hint"] = runner.install_hint(name)
        return info
    info.update(found=True, path=path)
    res = runner.run([path, "--version"], cwd=Path.cwd(), timeout=20)
    text = res.stdout + res.stderr
    version = parse_version(name, text)
    info["version"] = version
    if version is None:
        info["ok"] = False
        info["problem"] = "could not read the version from `--version`"
        info["version_output"], _ = runner.cap_text(text.strip(), 300, keep="head")
    elif version_tuple(version) < version_tuple(minimum):
        info["ok"] = False
        info["problem"] = f"version {version} is older than the required {minimum}"
        info["install_hint"] = runner.install_hint(name)
    else:
        info["ok"] = True
    return info


def check_environment() -> dict:
    """Check that the BPP command-line tools are installed and new enough.

    Call this FIRST in every session, before any other tool. It runs
    `<tool> --version` for bpp-seqs, bpp-tree, bpp-lint, bpp-docs and bpp.

    Output:
    - `ready`: true only when every tool is found and new enough AND a project
      directory is set. If false, read `problems` and help the user fix them
      before doing anything else; tell them the exact `install_hint` command.
    - `tools.<name>`: `found`, `path`, `version`, `minimum_version`, `ok`, and
      `problem` / `install_hint` when something is wrong.
    - `project_root`: the only directory the tools can read or write. Every
      path you pass to other tools is relative to it. If it is null, no
      project is set: ask the user which project folder to use and call
      set_project (if available), or explain that the host configuration must
      set BPP_MCP_ROOT.
    """
    tools = {name: probe(name, minimum) for name, minimum in TOOLS}
    problems = []
    for name, info in tools.items():
        if not info["found"]:
            problems.append(f"{name} is not installed ({info['install_hint']})")
        elif not info["ok"]:
            problems.append(f"{name}: {info['problem']}")
    root = sandbox.current.root
    if root is None:
        problems.append("no project directory is set")
    return {
        "ready": not problems,
        "problems": problems,
        "project_root": str(root) if root else None,
        "set_project_available": sandbox.current.projects_dir is not None,
        "tools": tools,
        "server": {
            "bpp_mcp_version": __version__,
            "mcp_version": importlib.metadata.version("mcp"),
            "python": platform.python_version(),
            "platform": platform.platform(terse=True),
        },
    }


def set_project(path: str) -> dict:
    """Select the project folder that all other tools work in.

    Only available when the server was configured with BPP_MCP_PROJECTS_DIR
    (typical in desktop chat apps). `path` is a folder inside that directory,
    e.g. "anastrepha-2026". Ask the user which folder to use; do not guess.
    After this, every path you pass to other tools is relative to the new
    project root. Returns the new `project_root` and the files in it.
    """
    root = sandbox.current.set_project(path)
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in root.iterdir()
                     if not p.name.startswith("."))
    notes: list[str] = []
    listing = runner.sanitize(entries, notes, max_list=100)
    out = {"project_root": str(root), "files": listing}
    if notes:
        out["server"] = {"truncated": notes}
    return out
