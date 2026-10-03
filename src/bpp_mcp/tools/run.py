"""smoke_test: a short BPP run on a copy of the control file."""
from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from .. import ctlfile, runner, sandbox

# BPP's fatal messages start with one of these.
FATAL = re.compile(r"^.*\b(Erroneous format|Unable to open|Cannot find|Expected|"
                   r"Number of digits).*$", re.M)
TAIL = 3000


def smoke_test(ctl: str, nsample: int = 500, burnin: int = 200, timeout_s: int = 300) -> dict:
    """Run BPP briefly to prove it accepts the control file and loads the data.

    Call after lint_control_file reports server.status "valid". Runs a copy of
    the file with a short chain (`nsample`, `burnin`) in a scratch folder that
    is deleted afterwards, from the control file's folder (as the real run
    will be). The results are NOT an analysis; never report them as findings.

    Read in the result:
    - `ok`: true if BPP finished; false if it failed (see `error_line`, BPP's
      fatal message, and `output_tail`); null if still running at `timeout_s`
      without an error, which means BPP read the file and data and started
      the MCMC.
    Only when lint is valid AND ok is not false is the file ready. Then
    explain how to run the full analysis.
    """
    src = sandbox.resolve(ctl, must_exist=True)
    if not src.is_file():
        raise ToolError(f"'{ctl}' is not a file")
    if nsample < 1 or burnin < 0 or not 10 <= timeout_s <= 3600:
        raise ToolError("need nsample >= 1, burnin >= 0 and 10 <= timeout_s <= 3600")
    text = src.read_text(errors="replace")
    text = ctlfile.set_value(text, "nsample", str(nsample))
    text = ctlfile.set_value(text, "burnin", str(burnin))
    bpp = runner.require("bpp")

    # Scratch folder next to the control file, named relative to it, so the
    # jobname has no spaces even if the project path does.
    tmp = Path(tempfile.mkdtemp(dir=src.parent, prefix=".bpp-smoke-"))
    try:
        text = ctlfile.set_value(text, "jobname", f"{tmp.name}/smoke")
        tctl = tmp / "smoke.ctl"
        tctl.write_text(text)
        res = runner.run([bpp, "--cfile", str(tctl)], cwd=src.parent, timeout=timeout_s)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    output = (res.stdout + "\n" + res.stderr).replace("\r", "\n")
    output = re.sub(r"\n{2,}", "\n", output).replace(tmp.name + "/", "")
    failed = res.exit_code not in (0, None)
    m = FATAL.search(output) if failed else None
    tail, cut = runner.cap_text(output.strip(), TAIL)
    out: dict = {"exit_code": res.exit_code, "seconds": round(res.seconds, 1),
                 "error_line": m.group(0).strip() if m else None, "output_tail": tail}
    if res.timed_out:
        out["ok"] = None
        out["note"] = (f"BPP was still running after {timeout_s}s with no error: it accepted "
                       "the control file and data. Stopped here; this was only a test.")
    else:
        out["ok"] = not failed
        if failed and not m:
            out["note"] = "BPP failed without a recognised error message; read output_tail."
    if cut:
        out["server"] = {"truncated": [f"output_tail: last {TAIL} chars"]}
    return out
