"""build_species_tree: wrap bpp-tree."""
from __future__ import annotations

from .. import runner, sandbox


def _diagram(text: str) -> str | None:
    """The 'Tree:' section of bpp-tree's --display --ascii output."""
    lines, out, inside = text.splitlines(), [], False
    for line in lines:
        if line.strip() == "Tree:":
            inside = True
            continue
        if inside:
            if not line.strip():
                break
            out.append(line)
    return "\n".join(out) or None


def build_species_tree(joins: str, imap: str, out_prefix: str,
                       migration: str | None = None,
                       introgression: str | None = None) -> dict:
    """Build the species (or guide) tree from a join formula (bpp-tree).

    Writes PREFIX.stree (the species&tree block, with individual counts taken
    from the Imap, plus any migration block) and PREFIX.nwk. Pass PREFIX.stree
    to make_control_file as `stree_file`.

    - `joins`: comma-separated joins, each 'X+Y' or 'X+Y=name', e.g.
      'chimp+bonobo=pan, pan+human, gorilla+pan_human'. A label like A_B
      refers to the clade of A and B. Tip names are the Imap's species names.
      Ask the user for the tree (or guide tree for delimitation); do not
      invent one.
    - `migration` (MSC-M): bands 'SRC->DST, ...'. Mutually exclusive with
      `introgression`. The control file then also needs a wprior.
    - `introgression` (MSC-I): events 'DONOR->RECIP phi=0.1, ...'. The control
      file then also needs a phiprior.
    Look up those priors with lookup_docs; lint_control_file reports what is
    missing.

    Read in the report: `newick`, `taxa`, `species_counts`,
    `species_and_tree_block`, and `warnings` (e.g. ROOT_AUTO_JOINED: two
    clades were joined at the root automatically) and `errors`.
    `server.diagram` is an ASCII drawing of the tree. ALWAYS show the user the
    diagram and ask them to confirm the topology before going on.
    """
    root = sandbox.current.require_root()
    common = ["--joins", joins, "--imap", sandbox.rel(sandbox.resolve(imap, must_exist=True))]
    if migration:
        common += ["--migration", migration]
    if introgression:
        common += ["--introgression", introgression]
    prefix_path = sandbox.resolve(out_prefix)
    prefix_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = sandbox.rel(prefix_path)
    out = runner.run_tool("bpp-tree", ["--json", *common, "--out", prefix], cwd=root, timeout=60)
    if out["exit_code"] == 0:
        res = runner.run([runner.require("bpp-tree"), "--display", "--ascii", *common],
                         cwd=root, timeout=60)
        diagram = _diagram(res.stdout)
        if diagram:
            out.setdefault("server", {})["diagram"] = diagram
        out.setdefault("server", {})["stree_file"] = prefix + ".stree"
    return out
