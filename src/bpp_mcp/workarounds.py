"""Patches for known bugs in the upstream tools.

Every workaround names the bug, the tool and the last version it was seen in
(``max_affected``). It is active only while the installed version is at most
``max_affected`` (or cannot be read), so it switches off once a fixed release
is installed. If a newer release still has the bug, raise ``max_affected``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from . import ctlfile, runner, sandbox


@dataclass(frozen=True)
class Workaround:
    id: str
    tool: str
    max_affected: str
    description: str

    def active(self) -> bool:
        from .tools.env import version_tuple
        v = runner.tool_version(self.tool)
        return v is None or version_tuple(v) <= version_tuple(self.max_affected)


SD_BARE = Workaround(
    "speciesdelimitation-bare", "bpp-lint", "0.3.5",
    "bpp-lint --template A10/A11 writes a bare 'speciesdelimitation = 1', which BPP 4.8.7 "
    "rejects ('Erroneous format of option speciesdelimitation = 1'). Rewritten to '1 0 2': "
    "rjMCMC algorithm 0 with epsilon = 2 (the manual gives 1, 2 or 5 as reasonable). "
    "Upstream fix: BPP-LINT-FIXES.md, Fix 1.")

DATA_CHECKS = Workaround(
    "data-checks", "bpp-lint", "0.3.5",
    "bpp-lint does not check the control file against its data files, so a file can lint "
    "'valid' and still fail in BPP. Until bpp-lint reports BPP150-156 itself, "
    "lint_control_file adds cheap checks of its own under server.data_checks. "
    "Upstream fix: BPP-LINT-FIXES.md, Fix 2.")

_SD_BARE_LINE = re.compile(r"^([ \t]*speciesdelimitation[ \t]*=[ \t]*)1[ \t]*$", re.M | re.I)


def fix_speciesdelimitation(text: str) -> tuple[str, bool]:
    if not SD_BARE.active():
        return text, False
    new = _SD_BARE_LINE.sub(r"\g<1>1 0 2", text)
    return new, new != text


# ---------------------------------------------------------------- data checks
# TEMPORARY: the only place BPP checks live in Python. Remove once bpp-lint
# reports BPP150-156 (DATA_CHECKS.active() then returns False).

_LOCUS_HEADER = re.compile(r"^[ \t]*\d+[ \t]+\d+[ \t]*$", re.M)


def _issue(check: str, severity: str, message: str) -> dict:
    return {"check": check, "severity": severity, "message": message}


def _data_path(ctl: Path, value: str, what: str, issues: list) -> Path | None:
    try:
        p = sandbox.resolve(str(ctl.parent / value))
    except ToolError as e:
        issues.append(_issue("file_exists", "error", f"{what} '{value}': {e}"))
        return None
    if not p.is_file():
        issues.append(_issue("file_exists", "error",
                             f"{what} '{value}' not found (looked in {sandbox.rel(ctl.parent)}/, the "
                             "control file's folder; BPP is run from there)"))
        return None
    return p


def _imap_species(path: Path) -> set[str]:
    out = set()
    for line in path.read_text(errors="replace").splitlines():
        toks = line.split()
        if len(toks) >= 2 and not toks[0].startswith(("#", "*")):
            out.add(toks[1])
    return out


def data_checks(ctl: Path, text: str) -> list[dict]:
    issues: list[dict] = []
    usedata = ctlfile.get(text, "usedata")
    seq_v, imap_v = ctlfile.get(text, "seqfile"), ctlfile.get(text, "Imapfile")
    tree_species = ctlfile.species(text)

    if usedata != "0":
        if not seq_v:
            issues.append(_issue("file_exists", "error", "no seqfile is set"))
        else:
            seq = _data_path(ctl, seq_v, "seqfile", issues)
            nloci_v = ctlfile.get(text, "nloci")
            if seq and nloci_v and nloci_v.lstrip("-").isdigit():
                found = len(_LOCUS_HEADER.findall(seq.read_text(errors="replace")))
                nloci = int(nloci_v)
                if nloci > found:
                    issues.append(_issue("nloci", "error",
                                         f"nloci = {nloci} but the seqfile has {found} loci "
                                         f"(BPP: 'Expected {nloci} loci but found only {found}')"))
                elif 0 < nloci < found:
                    issues.append(_issue("nloci", "info",
                                         f"nloci = {nloci}; the seqfile has {found} loci and BPP "
                                         f"uses only the first {nloci}"))

    if imap_v:
        imap = _data_path(ctl, imap_v, "Imapfile", issues)
        if imap and tree_species is not None:
            imap_sp, tree_sp = _imap_species(imap), set(tree_species)
            if imap_sp - tree_sp:
                issues.append(_issue("species_match", "error",
                                     "species in the Imap but not in species&tree: "
                                     + ", ".join(sorted(imap_sp - tree_sp))))
            if tree_sp - imap_sp:
                issues.append(_issue("species_match", "error",
                                     "species in species&tree with no individuals in the Imap: "
                                     + ", ".join(sorted(tree_sp - imap_sp))))

    phase = ctlfile.get(text, "phase")
    if phase and tree_species is not None and "1" in phase.split():
        n = len(phase.split())
        if n != len(tree_species):
            issues.append(_issue("phase", "error",
                                 f"phase has {n} digits but there are {len(tree_species)} species "
                                 "(BPP: 'Number of digits in 'phase' does not match number of species')"))
    return issues
