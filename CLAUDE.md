# bpp-mcp

MCP server that guides a BPP user from raw data to a linted, smoke-tested
control file. The full spec is `BPP-MCP-BUILD.md`; read it before changing
anything. `reference/` holds the earlier prototype and the bpp-lint fix spec.

**Current status and next steps: `claude_next.md`. Read it at the start of a
session, and update it when a milestone or decision changes.**

**Design rule:** BPP knowledge (syntax, defaults, prior heuristics) belongs in
bpp-seqs / bpp-tree / bpp-lint / bpp-docs, not here. This server calls them
with `--json`, passes their reports through, orders the steps, confines paths
to the project, and runs short tests. If you need a BPP rule, file an issue on
the tool instead.

## Layout

- `src/bpp_mcp/server.py`: `MCPServer` instance, instructions, registration.
- `src/bpp_mcp/runner.py`: find binaries, run with timeout, `json_result()`
  (exit_code/report/stderr, server additions under `"server"`), size caps and
  sequence redaction. Every tool result goes through it or `sanitize()`.
- `src/bpp_mcp/sandbox.py`: project root (`BPP_MCP_ROOT`, or `set_project`
  under `BPP_MCP_PROJECTS_DIR`); every path goes through `sandbox.resolve()`.
- `src/bpp_mcp/install.py` + `toolset.json`: `bpp-mcp install-tools`, which
  downloads the pinned tool releases (sha256-checked) into
  `~/.local/share/bpp-mcp` (`$BPP_MCP_HOME`). The pinned versions are also
  the minimums `check_environment` enforces. `install.sh` bootstraps uv,
  bpp-mcp and the tools in one command.
- `src/bpp_mcp/resources.py`, `prompts.py`: the `bpp://manual/{keyword}`,
  `bpp://examples` and `bpp://examples/{name}` resources, and the three
  prompts. Prompts only order tool calls; they state no BPP facts.
- `evals/`: the evaluation harness (`harness.py`, `run_evals.py`), scenarios
  (`tasks/*.yaml`) and a reference solution for each (`reference.py`). See
  `evals/README.md`. Running it against a model costs API money; ask first.
- `src/bpp_mcp/tools/*.py`: tool functions. Docstrings are written for the
  model: what it does, when to call it, what to do next, key output fields.
- `src/bpp_mcp/workarounds.py`: every patch for an upstream bug, with the bug,
  the last affected version (`max_affected`) and a version gate. The
  temporary `data_checks` there are the only BPP checks allowed in Python.
- `src/bpp_mcp/ctlfile.py`: generic `keyword = value` line access (get, set,
  species list). No knowledge of what keywords mean.
- Tools run with `cwd` = project root (data, tree) or the control file's
  folder (lint, smoke test), and get root-relative paths, so reports never
  show absolute paths. Control files hold data paths relative to themselves.

## Conventions

- SDK is `mcp` 2.x (`from mcp.server.mcpserver import MCPServer`; results use
  snake_case, e.g. `is_error`). Check the installed package with `inspect`
  rather than memory.
- Raise `mcp.server.mcpserver.exceptions.ToolError` for any error the model
  should read; other exceptions lose their message.
- Every subprocess has a timeout. Never return raw sequences.
- Python >= 3.10.

## Tests

```
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/pytest -q
```

Unit tests need no binaries (fake scripts stand in). End-to-end tests drive
the server over stdio with the tools from `bpp-mcp install-tools`, and skip
with a reason when one is missing. Fixtures: `tests/fixtures/anastrepha`
(real data, CC0) and `tests/fixtures/tiny` (from BPP-LINT-FIXES.md). Binary locations can be
overridden with `BPP_MCP_<NAME>` (e.g. `BPP_MCP_BPP_LINT=/path/to/bpp-lint`).

Commit at each milestone, only when its tests pass.

## Releases

Set `__version__` in `src/bpp_mcp/__init__.py`, tag `vX.Y.Z` to match and
push the tag; `.github/workflows/release.yml` builds, tests the wheel and
publishes a GitHub release. `install.sh` installs the latest release.
