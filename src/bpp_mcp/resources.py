"""Read-only resources: manual entries (bpp-docs) and the example control files.

The examples are the control files the tool releases ship, which
`bpp-mcp install-tools` unpacks under ``<home>/tools/<tool>-<version>/examples``.
"""
from __future__ import annotations

import json
from pathlib import Path

from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError, ToolError

from . import install, runner

MAX_CHARS = 20000


def _examples() -> dict[str, Path]:
    """Example name -> file. The name is the path below `examples/`, joined with '-'."""
    out: dict[str, Path] = {}
    for folder in sorted((install.home() / "tools").glob("*/examples")):
        for f in sorted(folder.rglob("*.ctl")):
            out.setdefault("-".join(f.relative_to(folder).parts), f)
    return out


def manual(keyword: str) -> str:
    """The BPP manual's section for one control-file keyword, verbatim (bpp-docs)."""
    try:
        res = runner.run([runner.require("bpp-docs"), "--json", keyword], cwd=Path.cwd(), timeout=30)
    except ToolError as e:
        raise ResourceError(str(e)) from e
    try:
        report = json.loads(res.stdout)
    except json.JSONDecodeError as e:
        raise ResourceError(f"bpp-docs gave no JSON for '{keyword}'") from e
    if not report.get("found") or not report.get("text"):
        raise ResourceNotFoundError(f"the manual has no entry for '{keyword}'")
    return report["text"][:MAX_CHARS]


def examples() -> str:
    """Names of the example control files, as JSON; read one at bpp://examples/{name}."""
    found = _examples()
    return json.dumps({
        "examples": [{"name": n, "uri": f"bpp://examples/{n}",
                      "from": f.relative_to(install.home() / "tools").parts[0]}
                     for n, f in found.items()],
        "note": ("Example control files shipped with bpp-lint and BPP. Their data files are not "
                 "in the user's project; use them to see syntax, not as the user's analysis."
                 if found else "No examples found; run `bpp-mcp install-tools`."),
    }, indent=2)


def example(name: str) -> str:
    """One example control file shipped with bpp-lint or BPP."""
    f = _examples().get(name)
    if f is None:
        raise ResourceNotFoundError(f"no example named '{name}'; read bpp://examples for the list")
    text, _ = runner.cap_text(f.read_text(errors="replace"), MAX_CHARS, keep="head")
    return text
