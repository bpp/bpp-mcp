"""make_control_file, lint_control_file: wrap bpp-lint."""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from .. import ctlfile, runner, sandbox, workarounds
from .docs import keywords

ANALYSES = ("A00", "A01", "A10", "A11")


def _rel_to(target: Path, base: Path) -> str:
    """Path of ``target`` relative to directory ``base`` (both inside the project)."""
    return os.path.relpath(target, base)


def _canonical_keyword(key: str) -> str:
    known = {k.lower(): k for k in keywords()}
    k = known.get(key.strip().lower())
    if k is None:
        raise ToolError(f"'{key}' is not a BPP control-file keyword according to the manual "
                        "(bpp-docs --list). Check the name with search_docs.")
    return k


def make_control_file(analysis: str, seqfile: str, imapfile: str, stree_file: str, out: str,
                      nloci: int, jobname: str = "out", phase: str | None = None,
                      thetaprior: str | None = None, tauprior: str | None = None,
                      nsample: int | None = None, burnin: int | None = None,
                      sampfreq: int | None = None, seed: int | None = None,
                      extra: dict[str, str] | None = None, overwrite: bool = False) -> dict:
    """Create a BPP control file (bpp-lint --template --suggest-priors).

    Never write a control file yourself; use this, then lint_control_file.

    - `analysis`: A00 = estimate parameters on a fixed species tree;
      A01 = estimate the species tree; A10 = species delimitation on a fixed
      guide tree; A11 = joint species delimitation and species tree. Ask the
      user, explaining the choices in plain language.
    - `seqfile`, `imapfile`: from convert_data (PREFIX.txt, PREFIX.imap).
      `stree_file`: from build_species_tree (PREFIX.stree). `nloci`: from
      convert_data's server.nloci. `out`: the control file to write.
      Data paths are written relative to the control file's folder.
    - `phase`: for unphased diploid data, one digit per species in
      species&tree order (look up 'phase' with lookup_docs and ask the user).
    - `thetaprior`, `tauprior`: leave unset to use priors derived from the
      data (inverse-gamma, alpha = 3); set only if the user asks.
    - `nsample`, `burnin`, `sampfreq`, `seed`: chain settings; template
      defaults apply when unset. Discuss chain length with the user.
    - `extra`: any other keywords as {"keyword": "value"}, e.g.
      {"wprior": "...", "threads": "..."}. Each name is checked against the
      manual's keyword list. Look up the syntax with lookup_docs first.
    - `overwrite`: an existing file is refused unless true. Ask the user.

    Returns the file's `text` and path. `server.workarounds_applied` lists
    patches for known bpp-lint bugs. Next: lint_control_file.
    """
    if analysis not in ANALYSES:
        raise ToolError(f"analysis must be one of {', '.join(ANALYSES)}")
    dst = sandbox.resolve(out)
    if dst.exists() and not overwrite:
        raise ToolError(f"{sandbox.rel(dst)} already exists. Ask the user whether to replace it "
                        "(then call again with overwrite=true) or choose another name.")
    if dst.suffix == "" or dst.is_dir():
        raise ToolError("`out` must be a file name such as 'a10.ctl'")
    here = dst.parent
    here.mkdir(parents=True, exist_ok=True)
    extra_items = [(_canonical_keyword(k), str(v)) for k, v in (extra or {}).items()]

    args = ["--template", analysis, "--suggest-priors",
            "--seqfile", _rel_to(sandbox.resolve(seqfile, must_exist=True), here),
            "--imapfile", _rel_to(sandbox.resolve(imapfile, must_exist=True), here),
            "--species-tree-file", _rel_to(sandbox.resolve(stree_file, must_exist=True), here),
            "--nloci", str(nloci), "--jobname", jobname]
    for flag, val in (("--phase", phase), ("--thetaprior", thetaprior), ("--tauprior", tauprior),
                      ("--nsample", nsample), ("--burnin", burnin), ("--sampfreq", sampfreq),
                      ("--seed", seed)):
        if val is not None:
            args += [flag, str(val)]
    tmp = dst.with_name(f".{dst.name}.tmp")
    res = runner.run([runner.require("bpp-lint"), *args, "--out", tmp.name], cwd=here, timeout=600)
    if res.exit_code != 0 or not tmp.exists():
        tmp.unlink(missing_ok=True)
        msg, _ = runner.cap_text((res.stderr or res.stdout).strip(), 2000)
        raise ToolError(f"bpp-lint --template failed (exit {res.exit_code}): {msg}")
    text = tmp.read_text()
    tmp.unlink()

    applied = []
    text, fixed = workarounds.fix_speciesdelimitation(text)
    if fixed:
        applied.append({"id": workarounds.SD_BARE.id, "description": workarounds.SD_BARE.description})
    for k, v in extra_items:
        try:
            text = ctlfile.set_value(text, k, v)
        except ValueError as e:
            raise ToolError(f"extra[{k!r}]: {e}") from e
    dst.write_text(text)

    server: dict = {"next": "lint_control_file"}
    if applied:
        server["workarounds_applied"] = applied
    if extra_items:
        server["extra_keywords"] = [k for k, _ in extra_items]
    if res.stderr.strip():
        server["bpp_lint_stderr"], _ = runner.cap_text(res.stderr.strip(), 2000)
    notes: list[str] = []
    text_out = runner.sanitize(text, notes, max_str=20000)
    if notes:
        server["truncated"] = notes
    return {"control_file": sandbox.rel(dst), "text": text_out, "server": server}


def lint_control_file(ctl: str) -> dict:
    """Validate a control file (bpp-lint --json --check-priors) and check it against its data.

    Call after make_control_file and after every change. Loop until
    `server.status` is "valid": fix each error (by remaking the file with
    make_control_file and the corrected arguments), then lint again.

    Read in the result:
    - `server.status`: "valid" only if bpp-lint reports no errors AND the
      temporary `server.data_checks` found none. Use this, not report.status.
    - `report.diagnostics[]`: each has `code`, `severity`, `message`,
      `suggestion`, `suggested_fix`. Use explain_diagnostic(code) to explain
      one to the user.
    - `report.prior_check`: priors compared with estimates from the data.
    - `server.data_checks.issues[]` (temporary, until bpp-lint checks data
      files itself): missing data files, nloci larger than the data, Imap
      species that differ from the tree, phase digit count.
    A valid lint does not prove BPP will run: smoke_test next.
    """
    path = sandbox.resolve(ctl, must_exist=True)
    if not path.is_file():
        raise ToolError(f"'{ctl}' is not a file")
    out = runner.run_tool("bpp-lint", ["--json", "--no-defaults", "--check-priors", path.name],
                          cwd=path.parent, timeout=600)
    report = out.get("report") or {}
    errors = (report.get("counts") or {}).get("errors")
    status = "valid" if report.get("status") == "valid" and not errors else "invalid"
    server = out.setdefault("server", {})
    if workarounds.DATA_CHECKS.active():
        issues = workarounds.data_checks(path, path.read_text(errors="replace"))
        server["data_checks"] = {
            "temporary": True,
            "why": workarounds.DATA_CHECKS.description,
            "issues": issues,
        }
        if any(i["severity"] == "error" for i in issues):
            status = "invalid"
    if report.get("status") is None:
        status = "invalid"
    server["status"] = status
    return out
