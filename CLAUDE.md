# bpp-mcp

MCP server that guides a BPP user from raw data to a linted, smoke-tested
control file. The full spec is `BPP-MCP-BUILD.md`; read it before changing
anything. `reference/` holds the earlier prototype and the bpp-lint fix spec.

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
- `src/bpp_mcp/tools/*.py`: tool functions. Docstrings are written for the
  model: what it does, when to call it, what to do next, key output fields.
- `src/bpp_mcp/workarounds.py` (milestone 2): every patch for an upstream bug,
  with the issue, the version where it was seen, and a version gate.

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

Unit tests need no binaries. End-to-end tests drive the server over stdio and
skip with a reason when a needed binary is missing. Binary locations can be
overridden with `BPP_MCP_<NAME>` (e.g. `BPP_MCP_BPP_LINT=/path/to/bpp-lint`).

Commit at each milestone, only when its tests pass.
