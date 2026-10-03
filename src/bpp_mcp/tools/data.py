"""inspect_data, convert_data, make_loci_bed, subset_loci: wrap bpp-seqs."""
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


def make_loci_bed(input: str, window_size: int, out: str, step: int | None = None,
                  include_chrom: list[str] | None = None,
                  exclude_chrom: list[str] | None = None, autosomes_only: bool = False,
                  skip_edges: int | None = None, exclude_regions: str | None = None,
                  min_spacing: int | None = None, n_loci: int | None = None,
                  seed: int | None = None, overwrite: bool = False) -> dict:
    """Make a BED file of candidate loci by tiling a genome into windows (bpp-seqs windows).

    Use when the user has BAM/CRAM or gVCF data but no BED file saying which
    regions are the loci (inspect_data then lists a BED under `missing`).
    `input` is anything holding chromosome names and lengths: the reference
    FASTA, a BAM/CRAM or a VCF/gVCF. `out` is the BED file to write; pass it
    to inspect_data and convert_data with the other files.

    Ask the user for the locus size and spacing; do not choose them yourself.
    All options are passed to bpp-seqs unchanged:
    - `window_size`: locus length in bp. `step`: distance between window
      starts (default: window_size, so windows do not overlap).
    - `min_spacing`: least distance in bp between kept loci on a chromosome.
    - `n_loci`: sample this many windows at random (`seed` fixes the sample);
      omit to keep them all.
    - `include_chrom` / `exclude_chrom`: chromosome names. `autosomes_only`:
      skip sex chromosomes, mitochondria and unplaced contigs (by name).
    - `skip_edges`: drop this many bp at both ends of each chromosome.
    - `exclude_regions`: a BED file of intervals to avoid.
    - `overwrite`: an existing file is refused unless true. Ask the user.

    Read in the report: `n_windows_emitted` (loci written) and the counts
    before it, which show what each filter removed. Next: inspect_data.
    """
    root = sandbox.current.require_root()
    dst = sandbox.resolve(out)
    if dst.is_dir() or dst.suffix == "":
        raise ToolError("`out` must be a file name such as 'loci.bed'")
    if dst.exists() and not overwrite:
        raise ToolError(f"{sandbox.rel(dst)} already exists. Ask the user whether to replace it "
                        "(then call again with overwrite=true) or choose another name.")
    dst.parent.mkdir(parents=True, exist_ok=True)
    args = ["windows", sandbox.rel(sandbox.resolve(input, must_exist=True)),
            "--window-size", str(window_size), "--out", sandbox.rel(dst), "--json"]
    for flag, val in (("--step", step), ("--skip-edges", skip_edges),
                      ("--min-spacing", min_spacing), ("--n-loci", n_loci), ("--seed", seed)):
        if val is not None:
            args += [flag, str(val)]
    for flag, names in (("--include-chrom", include_chrom), ("--exclude-chrom", exclude_chrom)):
        if names:
            args += [flag, ",".join(names)]
    if autosomes_only:
        args.append("--autosomes-only")
    if exclude_regions:
        args += ["--exclude-regions", sandbox.rel(sandbox.resolve(exclude_regions, must_exist=True))]
    out_ = runner.run_tool("bpp-seqs", args, cwd=root, timeout=600)
    if out_["exit_code"] == 0:
        out_.setdefault("server", {})["bed_file"] = sandbox.rel(dst)
    return out_


def subset_loci(seqfile: str, out_prefix: str, first: int | None = None, last: int | None = None,
                range: str | None = None, loci: list[str] | None = None,
                chrom: str | None = None, min_sites: int | None = None,
                max_sites: int | None = None, invert: bool = False, imap: str | None = None,
                overwrite: bool = False) -> dict:
    """Write a new BPP seqfile holding a subset of the loci of an existing one (bpp-seqs extract).

    Use to make a small data set for a trial run, or to drop or keep
    particular loci. `seqfile` is a PREFIX.txt from convert_data. Writes
    `out_prefix`.txt, plus .imap and .loci.tsv when the input has them next to
    it. The original files are not changed.

    Selection (at least one; passed to bpp-seqs unchanged):
    - `first` / `last`: the first or last N loci. `range`: 1-based positions
      such as "1-50" or "1-10,41-50". These three add together.
    - `loci`: locus names. `chrom`: loci from this chromosome (needs the
      .loci.tsv). `min_sites` / `max_sites`: by alignment length.
    - Different kinds of selection combine with AND. `invert`: keep the loci
      that do NOT match.
    - `imap`: use this Imap instead of the one next to the seqfile.
    - `overwrite`: existing outputs are refused unless true. Ask the user.

    Read in the report: `n_loci_input`, `n_loci_kept` (also `server.nloci`:
    the nloci value for make_control_file with the new seqfile) and
    `output_files`. Next: make_control_file with the new seqfile, or
    set_keyword for seqfile and nloci on an existing control file.
    """
    root = sandbox.current.require_root()
    src = sandbox.resolve(seqfile, must_exist=True)
    selection: list[str] = []
    for flag, val in (("--first", first), ("--last", last), ("--range", range),
                      ("--chrom", chrom), ("--min-sites", min_sites), ("--max-sites", max_sites)):
        if val is not None:
            selection += [flag, str(val)]
    if loci:
        selection += ["--loci", ",".join(loci)]
    if not selection:
        raise ToolError("give at least one selection: first, last, range, loci, chrom, "
                        "min_sites or max_sites")
    prefix = sandbox.resolve(out_prefix)
    dst = prefix.with_name(prefix.name + ".txt")
    if dst.exists() and not overwrite:
        raise ToolError(f"{sandbox.rel(dst)} already exists. Ask the user whether to replace "
                        "it (then call again with overwrite=true) or choose another out_prefix.")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    args = ["extract", sandbox.rel(src), "--out", sandbox.rel(prefix), "--json", *selection]
    if invert:
        args.append("--invert")
    if imap:
        args += ["--imap", sandbox.rel(sandbox.resolve(imap, must_exist=True))]
    out = runner.run_tool("bpp-seqs", args, cwd=root, timeout=3600)
    kept = (out.get("report") or {}).get("n_loci_kept")
    if kept is not None:
        out.setdefault("server", {})["nloci"] = kept
    return out
