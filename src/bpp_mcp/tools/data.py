"""inspect_data, convert_data: wrap bpp-seqs."""
from __future__ import annotations

from collections import Counter

from mcp.server.mcpserver.exceptions import ToolError

from .. import runner, sandbox


def _files(files: list[str]) -> list[str]:
    if not files:
        raise ToolError("give at least one data file (glob patterns such as 'loci/*.fasta' work)")
    return [sandbox.rel(p) for p in sandbox.expand(files)]


def _file_summary(out: dict) -> None:
    rep = out.get("report") or {}
    files = rep.get("files_provided")
    if isinstance(files, list):
        out.setdefault("server", {})["file_types"] = dict(Counter(f.get("type") for f in files))


def inspect_data(files: list[str], imap: str | None = None) -> dict:
    """Inspect the user's data files without changing anything (bpp-seqs --dry-run).

    Call after check_environment, on whatever the user has: aligned loci
    (FASTA/PHYLIP/NEXUS, one or many per file), BAM/CRAM, gVCF, BED, a reference
    FASTA, and the Imap (sample -> species table). File types are detected from
    content. `files` may contain glob patterns relative to the project, e.g.
    ["loci/*.fasta"].

    Read in the report:
    - `workflow` (e.g. fasta2bpp) and `ready_to_run`: whether convert_data can
      run with these inputs.
    - `missing[]`: inputs still needed (often the Imap). Ask the user for them.
    - `cross_validation.issues`: mismatches between files, e.g. samples in the
      data but not the Imap. Explain them to the user before converting.
    - `files_provided[]`: per-file type and counts; `server.file_types` counts
      the types.
    Next: convert_data with the same files and Imap.
    """
    args = ["--json", "--dry-run", *_files(files)]
    if imap:
        args += ["--imap", sandbox.rel(sandbox.resolve(imap, must_exist=True))]
    out = runner.run_tool("bpp-seqs", args, cwd=sandbox.current.require_root(), timeout=600)
    _file_summary(out)
    return out


def convert_data(files: list[str], imap: str, out_prefix: str, phasing: str = "iupac",
                 reference: str | None = None, phased_vcf: str | None = None,
                 min_length: int | None = None, max_missing: float | None = None,
                 min_snps: int | None = None, keep_invariant: bool = False,
                 min_bq: int | None = None, min_mq: int | None = None,
                 min_dp: int | None = None, het_freq: float | None = None,
                 overwrite: bool = False) -> dict:
    """Convert the inspected data into BPP input files (bpp-seqs).

    Writes PREFIX.txt (the BPP seqfile), PREFIX.imap, PREFIX.stats.tsv and
    PREFIX.loci.tsv, where PREFIX is `out_prefix` relative to the project.
    Use the same `files` (globs allowed) and `imap` as inspect_data.

    Options, all passed to bpp-seqs unchanged:
    - `phasing` (BAM/CRAM and gVCF input only): iupac | split | haploid | vcf.
      Ask the user whether their diploid data are phased; for vcf also give
      `phased_vcf`. It does not apply to alignments.
    - `reference`: designate the reference FASTA explicitly.
    - Locus filters (bpp-seqs defaults apply when omitted): `min_length`,
      `max_missing`, `min_snps`, `keep_invariant`; read-based calling:
      `min_bq`, `min_mq`, `min_dp`, `het_freq`.
    - `overwrite`: existing outputs are refused unless true. Ask the user first.

    Read in the report: `summary.n_loci_passed` (also `server.nloci`) is the
    nloci value for make_control_file; `summary.failure_reasons` and `loci[]`
    say which loci were dropped and why; `output_files` names the files
    written. Tell the user how many loci passed. Next: build_species_tree.
    """
    root = sandbox.current.require_root()
    prefix = sandbox.resolve(out_prefix)
    seqfile = prefix.with_name(prefix.name + ".txt")
    if seqfile.exists() and not overwrite:
        raise ToolError(f"{sandbox.rel(seqfile)} already exists. Ask the user whether to replace "
                        "it (then call again with overwrite=true) or choose another out_prefix.")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    args = ["--json", "--out", sandbox.rel(prefix), "--phasing", phasing]
    for flag, path in (("--reference", reference), ("--phased-vcf", phased_vcf)):
        if path:
            args += [flag, sandbox.rel(sandbox.resolve(path, must_exist=True))]
    for flag, val in (("--min-length", min_length), ("--max-missing", max_missing),
                      ("--min-snps", min_snps), ("--min-bq", min_bq), ("--min-mq", min_mq),
                      ("--min-dp", min_dp), ("--het-freq", het_freq)):
        if val is not None:
            args += [flag, str(val)]
    if keep_invariant:
        args.append("--keep-invariant")
    args += [*_files(files), "--imap", sandbox.rel(sandbox.resolve(imap, must_exist=True))]
    out = runner.run_tool("bpp-seqs", args, cwd=root, timeout=3600)
    _file_summary(out)
    summary = (out.get("report") or {}).get("summary") or {}
    if "n_loci_passed" in summary:
        out.setdefault("server", {})["nloci"] = summary["n_loci_passed"]
    return out
