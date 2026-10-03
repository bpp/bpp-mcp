"""lookup_docs, search_docs, explain_diagnostic: wrap bpp-docs and bpp-lint --explain."""
from __future__ import annotations

import json
import re
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from .. import runner

DOC_MAX_STR = 20000      # manual sections are quoted whole, so allow long strings

_keywords: dict[str, list[str]] = {}


def keywords() -> list[str]:
    """Control-file keywords known to the manual (bpp-docs --list), cached."""
    path = runner.require("bpp-docs")
    if path not in _keywords:
        res = runner.run([path, "--json", "--list"], cwd=Path.cwd(), timeout=30)
        try:
            _keywords[path] = [e["keyword"] for e in json.loads(res.stdout)]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            raise ToolError(f"could not read the keyword list from bpp-docs --list: {e}") from e
    return _keywords[path]


def lookup_docs(keyword: str) -> dict:
    """The BPP manual's entry for one control-file keyword, quoted verbatim (bpp-docs).

    Use this instead of your own knowledge whenever you state BPP syntax,
    defaults, allowed values or keyword dependencies, and quote it to the user.
    `keyword` is a control-file variable such as 'thetaprior', 'phase' or
    'speciesdelimitation'.

    Read in the report: `found`; `syntax`, `values`, `default`,
    `dependencies`, `description`, and `text` (the whole section). If
    `found` is false, use search_docs.
    """
    return runner.run_tool("bpp-docs", ["--json", keyword], cwd=Path.cwd(), timeout=30,
                           max_str=DOC_MAX_STR, redact_seqs=False)


def search_docs(query: str) -> dict:
    """Ranked full-text search of the BPP manual (bpp-docs --search).

    Use for concepts rather than single keywords, e.g. 'migration prior',
    'unphased diploid', 'species delimitation algorithm'. Returns the best
    matching sections with `heading`, `score` and `snippet`. Follow up with
    lookup_docs for a keyword, and quote the manual to the user.
    """
    return runner.run_tool("bpp-docs", ["--json", "--search", query], cwd=Path.cwd(), timeout=30,
                           max_str=DOC_MAX_STR, redact_seqs=False)


def explain_diagnostic(code: str) -> dict:
    """Long explanation of a bpp-lint diagnostic code, e.g. 'BPP101' or '101'.

    Use it to explain a lint_control_file diagnostic to the user in plain
    language. Returns `code` and `text`.
    """
    m = re.fullmatch(r"\s*(?:BPP)?(\d{3})\s*", code, re.I)
    if not m:
        raise ToolError(f"'{code}' is not a bpp-lint code; codes look like BPP101 or 101")
    res = runner.run([runner.require("bpp-lint"), "--explain", m.group(1)], cwd=Path.cwd(), timeout=30)
    if res.exit_code != 0:
        raise ToolError((res.stderr or res.stdout).strip() or f"unknown code {code}")
    text, _ = runner.cap_text(res.stdout.strip(), DOC_MAX_STR, keep="head")
    return {"code": f"BPP{m.group(1)}", "text": text}
