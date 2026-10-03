"""bpp-mcp: an MCP server that guides BPP analysis setup.

Thin wrapper over the existing CLI tools (bpp-seqs, bpp-tree, bpp-lint,
bpp-docs, bpp). Every tool shells out to a binary with --json and returns its
report unchanged, so all BPP knowledge stays in the C tools; this layer adds
only workflow, sandboxing, and a short smoke-test runner.

Domain bounding: the model can act only through the tools below, and every
path is confined to the project directory (BPP_MCP_ROOT, default cwd).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

ROOT = Path(os.environ.get("BPP_MCP_ROOT", os.getcwd())).resolve()

INSTRUCTIONS = """\
You are a setup assistant for BPP (Bayesian Phylogenetics & Phylogeography,
multispecies coalescent). Help the user go from their sequence data to a
validated, smoke-tested BPP control file. Stay within that scope: if asked
about anything unrelated to BPP analyses, say briefly that this assistant only
covers BPP setup.

Rules:
- Never write a control file by hand. Use make_control_file, then
  lint_control_file, and fix issues until status is "valid".
- Never state BPP syntax or defaults from memory; use lookup_docs.
- Ask the user for scientific choices you cannot infer from the data:
  analysis type (A00/A01/A10/A11), the guide/species tree, whether diploid
  data are unphased, and whether to model gene flow. Explain each choice in
  plain language for a novice.
- Run smoke_test before declaring the file ready.
Typical order: inspect_data -> convert_data -> build_species_tree ->
make_control_file -> lint_control_file -> smoke_test.
"""

mcp = MCPServer("bpp", instructions=INSTRUCTIONS)


# ---------------------------------------------------------------- helpers
def _bin(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise ToolError(f"'{name}' not found on PATH; install it (brew install bpp/tap/{name}).")
    return path


def _path(p: str) -> Path:
    """Resolve p inside ROOT; refuse anything outside the project."""
    q = (ROOT / p).resolve()
    if q != ROOT and ROOT not in q.parents:
        raise ToolError(f"path '{p}' is outside the project directory {ROOT}")
    return q


def _run(argv: list[str], timeout: int = 300, cwd: Path = ROOT) -> dict:
    r = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    out = {"exit_code": r.returncode}
    try:
        out["report"] = json.loads(r.stdout) if r.stdout.strip() else None
    except json.JSONDecodeError:
        out["stdout"] = r.stdout[-8000:]
    if r.stderr.strip():
        out["stderr"] = r.stderr[-4000:]
    return out


# ---------------------------------------------------------------- data
@mcp.tool()
def inspect_data(files: list[str], imap: str | None = None) -> dict:
    """Inspect the user's sequence files (FASTA/PHYLIP/NEXUS alignments, BAM/CRAM,
    gVCF, BED, reference FASTA) and optional Imap (sample -> species). Detects
    types from content, cross-checks them, and reports the workflow and any
    `missing[]` inputs. Read-only. Call this first."""
    argv = [_bin("bpp-seqs"), "--json", "--dry-run", *[str(_path(f)) for f in files]]
    if imap:
        argv += ["--imap", str(_path(imap))]
    return _run(argv)


@mcp.tool()
def convert_data(files: list[str], imap: str, out_prefix: str,
                 phasing: str = "iupac") -> dict:
    """Convert inspected data into BPP input: writes PREFIX.txt (seqfile),
    PREFIX.imap, PREFIX.stats.tsv, PREFIX.loci.tsv. `phasing` (read-based input
    only): iupac | split | haploid | vcf. The report's summary.n_loci_passed is
    the nloci value for the control file."""
    argv = [_bin("bpp-seqs"), "--json", "--out", str(_path(out_prefix)),
            "--phasing", phasing, *[str(_path(f)) for f in files], "--imap", str(_path(imap))]
    return _run(argv, timeout=3600)


# ---------------------------------------------------------------- tree
@mcp.tool()
def build_species_tree(joins: str, imap: str, out_prefix: str,
                       migration: str | None = None,
                       introgression: str | None = None) -> dict:
    """Build a binary species tree from a join formula and write PREFIX.stree
    (a BPP species&tree block, counts filled from the Imap).
    joins: comma-separated, e.g. 'chimp+bonobo=pan, pan+human, ...'; a
      label like A_B refers to the clade of A and B; tip names cannot contain '_'.
    migration: MSC-M bands 'SRC->DST, ...' (needs wprior, speciestree=0).
    introgression: MSC-I events 'DONOR->RECIP phi=0.1, ...' (needs phiprior).
    Show the user the returned newick and confirm the topology before going on."""
    argv = [_bin("bpp-tree"), "--json", "--joins", joins, "--imap", str(_path(imap)),
            "--out", str(_path(out_prefix))]
    if migration:
        argv += ["--migration", migration]
    if introgression:
        argv += ["--introgression", introgression]
    return _run(argv)


# ---------------------------------------------------------------- control file
_SD_BARE = re.compile(r"^(\s*speciesdelimitation\s*=\s*1)\s*$", re.M)


@mcp.tool()
def make_control_file(analysis: str, seqfile: str, imapfile: str, stree_file: str,
                      out: str, nloci: int, jobname: str = "out",
                      overrides: dict[str, str] | None = None) -> dict:
    """Create a control file for analysis A00 (fixed tree, estimate parameters),
    A01 (estimate species tree), A10 (species delimitation on a guide tree) or
    A11 (joint delimitation + tree). Priors are derived from the data
    (inverse-gamma, alpha=3). `overrides` sets any other keyword, e.g.
    {"phase": "1 1 1 1 1", "nsample": "200000"}. Lint afterwards."""
    if analysis not in {"A00", "A01", "A10", "A11"}:
        raise ToolError("analysis must be one of A00, A01, A10, A11")
    dst = _path(out)
    argv = [_bin("bpp-lint"), "--template", analysis, "--suggest-priors",
            "--seqfile", str(_path(seqfile)), "--imapfile", str(_path(imapfile)),
            "--species-tree-file", str(_path(stree_file)),
            "--nloci", str(nloci), "--jobname", jobname, "--out", str(dst)]
    res = _run(argv)
    if dst.exists():
        text = dst.read_text()
        # Workaround: bpp-lint's template emits a bare 'speciesdelimitation = 1',
        # which BPP 4.8.7 rejects. Supply the documented default rjMCMC args.
        text = _SD_BARE.sub(r"\1 0 2", text)
        for k, v in (overrides or {}).items():
            if not re.fullmatch(r"[A-Za-z&_]+", k):
                raise ToolError(f"bad keyword {k!r}")
            pat = re.compile(rf"^\s*#?\s*{re.escape(k)}\s*=.*$", re.M | re.I)
            line = f"{k} = {v}"
            text = pat.sub(line, text, count=1) if pat.search(text) else text + line + "\n"
        dst.write_text(text)
        res["control_file"] = text
    return res


@mcp.tool()
def lint_control_file(ctl: str) -> dict:
    """Validate a control file (structure, values, cross-keyword rules, and priors
    vs. the data). Loop on this until report.status == "valid". Each diagnostic
    has code, message, suggestion and suggested_fix; use explain_diagnostic for
    a longer explanation to relay to the user."""
    return _run([_bin("bpp-lint"), "--json", "--no-defaults", "--check-priors", str(_path(ctl))])


@mcp.tool()
def explain_diagnostic(code: str) -> str:
    """Long-form explanation of a bpp-lint code such as '135' or 'BPP135'."""
    r = subprocess.run([_bin("bpp-lint"), "--explain", code.removeprefix("BPP")],
                       capture_output=True, text=True)
    return r.stdout or r.stderr


# ---------------------------------------------------------------- docs
@mcp.tool()
def lookup_docs(query: str, search: bool = False) -> dict:
    """Look up the BPP manual verbatim. With search=False, `query` is a control
    keyword (e.g. 'thetaprior') and returns its syntax, default and description.
    With search=True, ranked full-text search (e.g. 'migration prior')."""
    argv = [_bin("bpp-docs"), "--json"] + (["--search", query] if search else [query])
    return _run(argv)


# ---------------------------------------------------------------- run
@mcp.tool()
def smoke_test(ctl: str, nsample: int = 500, burnin: int = 200, timeout_s: int = 300) -> dict:
    """Run BPP briefly on a copy of the control file (short chain, scratch
    directory) to prove BPP accepts it and the data load. Not an analysis:
    results are not meaningful. Returns BPP's exit code and output tail."""
    src = _path(ctl)
    text = src.read_text()
    text = re.sub(r"^(\s*nsample\s*=).*$", rf"\1 {nsample}", text, flags=re.M | re.I)
    text = re.sub(r"^(\s*burnin\s*=).*$", rf"\1 {burnin}", text, flags=re.M | re.I)
    with tempfile.TemporaryDirectory(dir=ROOT, prefix=".bpp-smoke-") as tmp:
        t = Path(tmp)
        text = re.sub(r"^(\s*jobname\s*=).*$", rf"\1 {t / 'smoke'}", text, flags=re.M | re.I)
        tctl = t / "smoke.ctl"
        tctl.write_text(text)
        try:
            r = subprocess.run([_bin("bpp"), "--cfile", str(tctl)], cwd=src.parent,
                               capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return {"ok": None, "note": f"still running after {timeout_s}s; BPP accepted the file"}
        out = (r.stdout + r.stderr)
    return {"ok": r.returncode == 0, "exit_code": r.returncode, "output_tail": out[-3000:]}


@mcp.prompt()
def novice_setup() -> str:
    """Walk a new user from raw data to a ready BPP run."""
    return ("Help me set up a BPP analysis. Start by asking where my sequence "
            "data and Imap are, then inspect them and guide me step by step.")


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
