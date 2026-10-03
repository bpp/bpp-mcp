"""Locate the bpp binaries, run them with a timeout, parse JSON, cap output.

Everything a tool returns goes into a third-party model's context, so
``sanitize()`` caps list lengths and string sizes, and redacts anything that
looks like raw sequence data (users may have unpublished data).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_TIMEOUT = 300
MAX_TEXT = 8000          # chars of raw stdout/stderr returned
MAX_STR = 2000           # chars of any single string inside a report
MAX_LIST = 50            # items of any list inside a report
MAX_RESULT = 60000       # chars of the whole serialized report

# Hosts launched from a GUI (Claude Desktop on macOS in particular) often get
# a minimal PATH without Homebrew, so look in the usual install places too.
EXTRA_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin",
              "~/.linuxbrew/bin", "~/.local/bin"]

INSTALL_HINTS = {
    "bpp": "build from source: https://github.com/bpp/bpp",
}

# IUPAC nucleotide codes plus gap/missing; 31+ in a row is treated as sequence.
_SEQ_RUN = re.compile(r"[ACGTUNRYKMSWBDHVacgtunrykmswbdhv?\-.]{31,}")


def install_hint(name: str) -> str:
    return INSTALL_HINTS.get(name, f"brew install bpp/tap/{name}")


def _env_override(name: str) -> str:
    return "BPP_MCP_" + re.sub(r"[^A-Za-z0-9]", "_", name).upper()


def find(name: str) -> str | None:
    """Path of binary ``name``: $BPP_MCP_<NAME>, then PATH, then EXTRA_DIRS."""
    override = os.environ.get(_env_override(name))
    if override:
        p = Path(override).expanduser()
        return str(p) if p.is_file() and os.access(p, os.X_OK) else None
    found = shutil.which(name)
    if found:
        return found
    extra = os.pathsep.join(str(Path(d).expanduser()) for d in EXTRA_DIRS)
    return shutil.which(name, path=extra)


def require(name: str) -> str:
    path = find(name)
    if not path:
        raise ToolError(
            f"'{name}' was not found (looked on PATH, in {', '.join(EXTRA_DIRS)}, and "
            f"${_env_override(name)}). Install it with: {install_hint(name)}. "
            "Then call check_environment again.")
    return path


@dataclass
class RunResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    seconds: float


def _text(x: Any) -> str:
    if x is None:
        return ""
    return x.decode(errors="replace") if isinstance(x, bytes) else x


def run(argv: list[str], *, cwd: Path, timeout: float = DEFAULT_TIMEOUT) -> RunResult:
    """Run argv; never raises on a non-zero exit or a timeout."""
    t0 = time.monotonic()
    try:
        r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        return RunResult(argv, None, _text(e.stdout), _text(e.stderr), True,
                         time.monotonic() - t0)
    except OSError as e:
        raise ToolError(f"could not run {argv[0]}: {e}") from e
    return RunResult(argv, r.returncode, r.stdout, r.stderr, False, time.monotonic() - t0)


def cap_text(s: str, limit: int = MAX_TEXT, keep: str = "tail") -> tuple[str, bool]:
    """Redact sequences, then keep the head or tail of ``s`` within ``limit``."""
    s = redact(s)
    if len(s) <= limit:
        return s, False
    return (s[-limit:] if keep == "tail" else s[:limit]), True


def redact(s: str) -> str:
    def sub(m: re.Match) -> str:
        run = m.group()
        # Leave separator lines such as '-----' or '.....' alone.
        if sum(c.isalpha() for c in run) < 20:
            return run
        return f"<{len(run)} chars of sequence data redacted>"
    return _SEQ_RUN.sub(sub, s)


def sanitize(obj: Any, notes: list[str], *, max_list: int = MAX_LIST,
             max_str: int = MAX_STR, _path: str = "") -> Any:
    """Copy of ``obj`` with long lists/strings cut and sequences redacted.

    Each cut is recorded in ``notes`` as a human-readable message.
    """
    if isinstance(obj, str):
        s = redact(obj)
        if len(s) > max_str:
            notes.append(f"{_path or 'value'}: string cut from {len(s)} to {max_str} chars")
            s = s[:max_str]
        return s
    if isinstance(obj, dict):
        return {k: sanitize(v, notes, max_list=max_list, max_str=max_str,
                            _path=f"{_path}.{k}" if _path else str(k))
                for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        items = list(obj)
        if len(items) > max_list:
            notes.append(f"{_path or 'list'}: showing {max_list} of {len(items)} items")
            items = items[:max_list]
        return [sanitize(v, notes, max_list=max_list, max_str=max_str, _path=f"{_path}[{i}]")
                for i, v in enumerate(items)]
    return obj


def sanitize_capped(obj: Any, notes: list[str], limit: int = MAX_RESULT) -> Any:
    """sanitize(), tightening the caps until the serialized result fits ``limit``."""
    for max_list, max_str in ((MAX_LIST, MAX_STR), (20, 500), (5, 200)):
        trial: list[str] = []
        out = sanitize(obj, trial, max_list=max_list, max_str=max_str)
        if len(json.dumps(out)) <= limit:
            notes.extend(trial)
            return out
    notes.append(f"report omitted: larger than {limit} chars even after truncation")
    return None


def json_result(res: RunResult) -> dict:
    """Standard tool result for a CLI run with --json.

    ``{"exit_code", "report", "stderr"?, "server"?}``: the parsed report passes
    through unchanged apart from size caps and redaction, which are listed in
    ``server.truncated``. A timeout is an error the model must read.
    """
    name = Path(res.argv[0]).name
    if res.timed_out:
        raise ToolError(f"{name} did not finish within {res.seconds:.0f}s and was stopped")
    out: dict[str, Any] = {"exit_code": res.exit_code}
    notes: list[str] = []
    text = res.stdout.strip()
    try:
        out["report"] = sanitize_capped(json.loads(text), notes) if text else None
    except json.JSONDecodeError:
        out["report"] = None
        out["stdout"], cut = cap_text(res.stdout)
        if cut:
            notes.append(f"stdout: showing the last {MAX_TEXT} chars")
    if res.stderr.strip():
        out["stderr"], cut = cap_text(res.stderr)
        if cut:
            notes.append(f"stderr: showing the last {MAX_TEXT} chars")
    if notes:
        out["server"] = {"truncated": notes}
    return out
