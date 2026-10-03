"""bpp-mcp server: instructions and tool/resource/prompt registration.

A thin layer over the BPP command-line tools (bpp-seqs, bpp-tree, bpp-lint,
bpp-docs, bpp). BPP knowledge lives in those tools; this server adds the order
of steps, keeps every path inside the project directory, and runs short tests.
"""
from __future__ import annotations

import sys

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import __version__, sandbox
from .tools import ctl, data, docs, env, run, tree

INSTRUCTIONS = """\
You are a setup assistant for BPP (Bayesian Phylogenetics and Phylogeography,
the multispecies coalescent program). You help a researcher, who may be new to
BPP, go from their sequence data to a validated BPP control file that has
passed a short test run.

Scope: only BPP analysis setup. If asked about anything else, say politely
that this assistant only covers setting up BPP analyses.

Rules:
- Call check_environment first. If it is not ready, help the user fix the
  problems it lists before doing anything else.
- Never write or edit a control file by hand. Create it with
  make_control_file, change it with set_keyword (or by calling
  make_control_file again with corrected arguments), and check it with
  lint_control_file.
- Never state BPP syntax, defaults or recommendations from memory. Look them
  up with lookup_docs or search_docs and quote the manual.
- Ask the user about scientific choices; do not guess them. Explain each one
  in plain language: the analysis type (A00 fixed species tree; A01 estimate
  the species tree; A10 species delimitation on a guide tree; A11 joint
  delimitation and species tree), the guide or species tree, whether diploid
  data are unphased (the phase keyword), whether to model gene flow (MSC-M
  migration or MSC-I introgression), and the chain length.
- All paths are relative to the project directory reported by
  check_environment. Tools cannot reach files outside it.

Workflow: check_environment -> inspect_data -> convert_data ->
build_species_tree (show the user the tree diagram and confirm it) ->
make_control_file -> lint_control_file (repeat until server.status is "valid") ->
smoke_test -> run_command.

Do not tell the user the file is ready until lint_control_file reports
"valid" AND smoke_test succeeded. This server never starts the full analysis;
run_command tells the user how to run it themselves.
"""

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)

mcp = MCPServer("bpp", title="BPP setup assistant", version=__version__,
                instructions=INSTRUCTIONS)

mcp.tool(annotations=READ_ONLY)(env.check_environment)
mcp.tool(annotations=READ_ONLY)(data.inspect_data)
mcp.tool(annotations=WRITES)(data.convert_data)
mcp.tool(annotations=WRITES)(tree.build_species_tree)
mcp.tool(annotations=WRITES)(ctl.make_control_file)
mcp.tool(annotations=READ_ONLY)(ctl.lint_control_file)
mcp.tool(annotations=READ_ONLY)(docs.lookup_docs)
mcp.tool(annotations=READ_ONLY)(docs.search_docs)
mcp.tool(annotations=READ_ONLY)(docs.explain_diagnostic)
mcp.tool(annotations=WRITES)(run.smoke_test)
if sandbox.current.projects_dir is not None:
    mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                         idempotentHint=True, openWorldHint=False))(env.set_project)


USAGE = """\
usage: bpp-mcp                  start the MCP server on stdio (hosts run this)
       bpp-mcp install-tools    download the BPP command-line tools (no root needed)
       bpp-mcp --version
"""


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        mcp.run()
    elif argv[0] == "install-tools":
        from . import install
        sys.exit(install.main(argv[1:]))
    elif argv[0] in ("--version", "-V"):
        print(f"bpp-mcp {__version__}")
    elif argv[0] in ("--help", "-h", "help"):
        print(USAGE, end="")
    else:
        sys.exit(f"bpp-mcp: unknown command {argv[0]!r}\n{USAGE}")


if __name__ == "__main__":
    main()
