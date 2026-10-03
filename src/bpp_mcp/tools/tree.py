"""build_species_tree, read_species_tree: wrap bpp-tree."""
from __future__ import annotations

from mcp.server.mcpserver.exceptions import ToolError

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


def _run(common: list[str], out_prefix: str | None) -> dict:
    """bpp-tree --json with ``common`` args, plus the ASCII diagram from a second call."""
    root = sandbox.current.require_root()
    args, prefix = ["--json", *common], None
    if out_prefix:
        prefix_path = sandbox.resolve(out_prefix)
        prefix_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = sandbox.rel(prefix_path)
        args += ["--out", prefix]
    out = runner.run_tool("bpp-tree", args, cwd=root, timeout=60)
    if out["exit_code"] == 0:
        res = runner.run([runner.require("bpp-tree"), "--display", "--ascii", *common],
                         cwd=root, timeout=60)
        diagram = _diagram(res.stdout)
        if diagram:
            out.setdefault("server", {})["diagram"] = diagram
        if prefix:
            out.setdefault("server", {})["stree_file"] = prefix + ".stree"
    return out


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
    common = ["--joins", joins, "--imap", sandbox.rel(sandbox.resolve(imap, must_exist=True))]
    if migration:
        common += ["--migration", migration]
    if introgression:
        common += ["--introgression", introgression]
    return _run(common, out_prefix)


def read_species_tree(path: str, imap: str | None = None, out_prefix: str | None = None) -> dict:
    """Read a species tree the user already has (bpp-tree --read).

    Use instead of build_species_tree when the user has a tree file: a Newick
    (or extended Newick with introgression), a species&tree block, or an old
    control file containing one. Migration and introgression in the file are
    recovered too.

    - `imap`: the Imap from convert_data; fills in the individual counts.
      Without it the block has '?' for the counts and cannot be used yet.
    - `out_prefix`: also write PREFIX.stree and PREFIX.nwk, for
      make_control_file's `stree_file`. Give it together with `imap`.

    Read in the report: `status`, `newick`, `taxa`, `species_and_tree_block`,
    `individual_counts_filled`, `migration`, `introgression`, `warnings` and
    `errors`. `server.diagram` is an ASCII drawing of the tree: ALWAYS show
    it to the user and ask them to confirm it is the tree they meant.
    `server.stree_file` is set when `out_prefix` was given.
    """
    src = sandbox.resolve(path, must_exist=True)
    if not src.is_file():
        raise ToolError(f"'{path}' is not a file")
    common = ["--read", sandbox.rel(src)]
    if imap:
        common += ["--imap", sandbox.rel(sandbox.resolve(imap, must_exist=True))]
    return _run(common, out_prefix)
