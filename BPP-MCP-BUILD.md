# bpp-mcp: build instructions for Claude Code

Put this file in the root of the new `bpp-mcp` repository, alongside or merged
into `CLAUDE.md`. Read all of it before you write any code.

## What you are building

`bpp-mcp` is an MCP (Model Context Protocol) server. Through it, any
MCP-capable assistant can guide a researcher, including a novice, from raw
sequence data to a validated BPP control file that has passed a test run.
Hosts it should work with include Claude Code, Claude Desktop, Codex, Gemini
CLI, and a local model's agent loop.

The server is a thin orchestration layer over existing command-line tools:

| Tool | Repo | What it gives us |
|---|---|---|
| `bpp-seqs` | bpp/bpp-seqs | detect input file types, cross-validate them, convert to a BPP seqfile and Imap; `--json` |
| `bpp-tree` | bpp/bpp-trees | species tree from a join formula, migration (MSC-M) and introgression (MSC-I), reads existing trees; `--json` |
| `bpp-lint` | bpp/bpp-lint | control-file validation, `--template A00..A11`, `--suggest-priors`, `--check-priors`, `--fix`/`--diff` for old files; `--json` |
| `bpp-docs` | bpp/bpp-docs | verbatim BPP manual lookup and search; `--json` |
| `bpp` | bpp/bpp | the program itself (used only for short test runs) |

**Design rule:** BPP knowledge belongs in those tools, not in this repo. This
server calls them, passes along their JSON, adds the order of steps, keeps
everything inside the project directory, and runs the test. If you find
yourself writing BPP syntax rules or prior heuristics in Python, stop. Write
an issue for the relevant tool instead (see "Workarounds").

## A prototype already exists

An earlier session wrote and tested a prototype, `bpp_mcp/server.py` with
`test_client.py`, about 200 lines in total. If the repo owner has added it
under `reference/`, read it first. It covered the whole path end to end on the
Anastrepha FASTA example: inspect → convert → tree → A10 control file → lint
reports `valid` → a short BPP run. Build on its structure. Most of the
lessons below came from it.

## Lessons from the prototype

1. **The SDK is `mcp` 2.x.**
   - `FastMCP` was renamed: use `from mcp.server.mcpserver import MCPServer`.
   - Results use snake_case, e.g. `CallToolResult.is_error`.
   - Pin `mcp>=2,<3`. When unsure of an API, check the installed package with
     `inspect`, not your memory.
2. **Raise `mcp.server.mcpserver.exceptions.ToolError` for any error the model
   should read.** Other exceptions reach the model only as
   "Error executing tool X", without the reason.
3. **Synchronous tool functions run in a worker thread,** so blocking
   `subprocess.run` calls are fine. Still, give every subprocess a timeout.
4. **`bpp-lint --template A10/A11` writes a bare `speciesdelimitation = 1`,
   which BPP 4.8.7 rejects.** The prototype patched the output to `1 0 2`.
   See "Workarounds".
5. **BPP opens `seqfile` and `Imapfile` relative to the directory it is run
   from. bpp-lint resolves them relative to the control file's directory.**
   Pick one rule and enforce it (see "Path policy").
6. **bpp-lint does not yet check the control file against the data files.**
   A file can lint "valid" and still fail in BPP because of:
   - a missing file,
   - `nloci` larger than the data,
   - a sequence tag missing from the Imap,
   - a species mismatch between the Imap and the tree,
   - a `phase` with the wrong number of digits that contains a `1`.

   A fix is specified for bpp-lint separately (`BPP-LINT-FIXES.md`, codes
   BPP150–156). Until it ships, the `smoke_test` tool is the safety net.

## Architecture

```
bpp-mcp/
  pyproject.toml          # package "bpp-mcp", console script `bpp-mcp`, requires-python >=3.10
  src/bpp_mcp/
    __init__.py           # __version__
    server.py             # MCPServer instance, instructions, tool/resource/prompt registration
    runner.py             # locate binaries, run with timeout, parse JSON, size-cap output
    sandbox.py            # project-root confinement and path policy
    tools/
      env.py              # check_environment
      data.py             # inspect_data, convert_data, make_loci_bed, subset_loci
      tree.py             # build_species_tree, read_species_tree
      ctl.py              # make_control_file, lint_control_file, upgrade_control_file, set_keyword
      docs.py             # lookup_docs, search_docs, explain_diagnostic
      run.py              # smoke_test, run_command
    workarounds.py        # every patch for a known upstream bug, each with a version gate
  tests/
    fixtures/             # small data sets (see Testing)
    test_unit_*.py        # pure-Python units (sandbox, runner, workarounds)
    test_e2e.py           # drives the server over stdio, as a host would
  evals/
    tasks/*.yaml          # novice scenarios (see Evaluation)
    run_evals.py
  README.md
  CLAUDE.md
```

Transport: stdio by default. Streamable HTTP is out of scope for v1.

## The tools

Every tool should do the following:

- Have a docstring written for the *model*. Say what the tool does, when to
  call it, what to do next, and how to interpret the key output fields. Keep
  the wording precise, because the docstrings are most of the prompt.
- Take paths relative to the project root, and go through `sandbox.resolve()`.
- Return a dict. For wrapped CLIs, return
  `{"exit_code", "report": <parsed JSON>, "stderr"?}`. Put any server
  additions under a separate `"server"` key, so the upstream JSON passes
  through unchanged.
- **Never return raw sequences.** Return summaries only, such as counts,
  sample names, and per-locus statistics. Users may have unpublished data,
  and whatever a tool returns goes into a third-party model's context. Cap the
  size of every returned field and say when something was truncated.

| Tool | Wraps | Notes |
|---|---|---|
| `check_environment` | `<tool> --version` for every binary | Which tools are found, their versions, and any minimum versions not met, with install hints (`brew install bpp/tap/<tool>`). The instructions should tell the model to call this first. |
| `inspect_data(files, imap?)` | `bpp-seqs --json --dry-run` | Read-only. Summarise `workflow`, `ready_to_run`, `missing[]`, `cross_validation.issues`, and per-file types. Drop `sample_names` lists longer than about 50 and give counts instead. |
| `convert_data(files, imap, out_prefix, phasing="iupac", filters?)` | `bpp-seqs --json --out` | Pass through the filter options (min-length, max-missing, min-snps, caller). Return `summary.n_loci_passed` as `nloci`. Long timeout. |
| `make_loci_bed(input, window_size, ...)` | `bpp-seqs windows` | For BAM or gVCF input with no BED file. |
| `subset_loci(seqfile, out_prefix, first?/range?/...)` | `bpp-seqs extract` | Used to make a small data set for a test run. |
| `build_species_tree(joins, imap, out_prefix, migration?, introgression?)` | `bpp-tree --json --out` | Return the Newick and an ASCII diagram (a second call with `--display --ascii`), so the model can show the user the tree to confirm. |
| `read_species_tree(path)` | `bpp-tree --json --read` | Import an existing Newick, `.stree` file or control file. |
| `make_control_file(analysis, seqfile, imapfile, stree_file, out, nloci, jobname, phase?, priors?, mcmc?, extra?)` | `bpp-lint --template … --suggest-priors` | Typed arguments for the common keywords. `extra` holds other keywords, and each is checked against `bpp-docs --list` before it is written. Apply `workarounds`. Return the file text. |
| `set_keyword(ctl, keyword, value)` | edit, then re-lint | Change one keyword safely. Check the keyword exists, keep comments, return the new lint result. Saves the model from editing files by hand. |
| `lint_control_file(ctl)` | `bpp-lint --json --no-defaults --check-priors` | The model loops on this until `status == "valid"`. |
| `upgrade_control_file(ctl, apply=False)` | `bpp-lint --diff` / `--fix` | For users bringing in BPP 2.x/3.x files. Show the diff first. Apply only when `apply=True`. |
| `explain_diagnostic(code)` | `bpp-lint --explain` | |
| `lookup_docs(keyword)` / `search_docs(query)` | `bpp-docs --json` | Manual text, quoted exactly. |
| `smoke_test(ctl, nsample=500, burnin=200, timeout_s=300)` | `bpp --cfile` on a copy | Runs in a scratch directory inside the project. Overrides `nsample`, `burnin` and `jobname`. Runs from the control file's directory. Return `ok`, the exit code, the first BPP error line found (see the patterns in "Testing"), and the last ~3 KB of output. If it is still running at the timeout, return `ok: null` and note that BPP parsed the file. |
| `run_command(ctl)` | none | Does **not** run BPP. Returns the exact command line and working directory for the real run, plus a note on threads and HPC submission. v1 never starts long runs. |

**Resources** (read-only context the host can load):

- `bpp://manual/{keyword}` (from `bpp-docs`).
- `bpp://examples/{name}`: the example control files shipped with bpp-lint
  and BPP, if they can be found.

**Prompts:**

- `novice_setup`: from raw data to a tested control file.
- `upgrade_old_file`: bring an old control file up to date.
- `check_my_ctl`: review an existing control file.

## Server instructions

Pass these as `instructions` to `MCPServer`. Start from the prototype's text
and make sure it says all of the following:

- **Scope:** only BPP analysis setup. Politely decline anything else.
- **Never write or edit a control file by hand.** Use `make_control_file`,
  then `set_keyword` for changes, then `lint_control_file`.
- **Never state BPP syntax, defaults or recommendations from memory.** Use
  `lookup_docs` / `search_docs` and quote them.
- **Ask the user about scientific choices and don't guess them.** Explain
  each in plain language:
  - analysis type (A00 / A01 / A10 / A11),
  - the guide or species tree,
  - whether diploid data are unphased (`phase`),
  - whether to model gene flow (MSC-M or MSC-I),
  - chain length.
- **Workflow:** `check_environment` → `inspect_data` → `convert_data` →
  `build_species_tree` (show the diagram and confirm) → `make_control_file`
  → `lint_control_file` (loop until valid) → `smoke_test` → `run_command`.
- **Don't claim a file is ready** until both lint is valid and the test run
  succeeded.

## Path policy

- `BPP_MCP_ROOT` (default: the current directory at startup) is the project
  root. `sandbox.resolve()` must reject any path that resolves outside it,
  including through symlinks (use `Path.resolve()`). Return a `ToolError`
  explaining the refusal.
- In generated control files, write data paths **relative to the control
  file's directory**.
- Always run BPP with `cwd` set to the control file's directory. Then BPP's
  rule (relative to where it's run) and bpp-lint's rule (relative to the
  control file) agree.
- `run_command` must tell the user to run BPP from that directory.

## Workarounds

Keep every patch for an upstream bug in `workarounds.py`. Each one needs:

- the upstream issue or a description of the bug,
- the tool version where it was seen,
- a version check, so it switches off automatically once the fixed version is
  installed.

Known so far:

1. **The bare `speciesdelimitation = 1` from `bpp-lint --template A10/A11`
   (seen in bpp-lint 0.3.5).** Rewrite it to `1 0 2`, which is algorithm 0
   with ε = 2; the manual says ε values of 1, 2 or 5 are reasonable.
2. **No data checks in bpp-lint (0.3.5).** Until bpp-lint has BPP150–156, have
   `lint_control_file` add a `server.data_checks` list with cheap Python
   checks:
   - `seqfile` and `imapfile` exist;
   - the number of loci in the seqfile (count the `n_seq n_sites` header
     lines) is at least `nloci`;
   - the species in the Imap equal the species in the tree;
   - when `phase` contains a `1`, its number of digits equals the number of
     species.

   Mark this list clearly as temporary. Remove it once bpp-lint reports these
   checks itself. This is the one place where BPP checks are allowed in
   Python.

## Testing

**Fixtures:**

- `tests/fixtures/tiny/`: a tiny data set of 2 loci, 3 species (A, B, C) and
  2 sequences each. It is defined in `BPP-LINT-FIXES.md`, so reuse those
  exact files.
- One of the bpp-seqs real-data examples, e.g. `examples/01-fasta-anastrepha`
  (10 loci, 5 species). Copy it into the repo or fetch it in CI, and keep the
  licence and citation notes.

**Unit tests (no binaries needed):**

- Sandbox escapes: `../`, absolute paths, symlinks.
- Runner timeouts and output size caps.
- Each workaround's patch and its version check.
- `set_keyword` editing that keeps comments.

**End-to-end tests (`test_e2e.py`):**

- Start the server over stdio with `mcp.client.stdio` and call each tool as a
  host would, following the prototype's `test_client.py`.
- Skip with a clear reason when a binary is missing:
  `pytest.mark.skipif(shutil.which("bpp") is None)`.

**Required end-to-end paths:**

- **Anastrepha:** inspect → convert (`nloci == 10`) → tree → A10 → lint valid
  → smoke test ok. Then repeat with A00 and A11.
- **Tiny data set:** each defect case from `BPP-LINT-FIXES.md` gives either a
  lint error or a `server.data_checks` entry, and `smoke_test` reports
  `ok: false` with the BPP error line. BPP's fatal messages begin with
  `Erroneous format`, `Unable to open`, `Cannot find`, `Expected`, or
  `Number of digits`.
- **Upgrade path:** `upgrade_control_file` on bpp-lint's
  `examples/legacy-3x.bpp.ctl` shows a diff. With `apply=True` it writes a
  `.bak` backup.

**Privacy test:** no tool's output contains a nucleotide string longer than
30 characters from the fixture data.

**CI (GitHub Actions):**

- Ubuntu and macOS, Python 3.10 and 3.13.
- Install the tools with Homebrew (`brew install bpp/tap/...`; Homebrew also
  runs on the Linux runners), or download the release binaries.
- Build `bpp` from source.
- Run the unit tests on every push, and the end-to-end tests when the
  binaries install.

## Evaluation

This decides whether the project works, as distinct from whether the code
runs.

Create `evals/tasks/*.yaml`, starting with 10–20 scenarios. Each one has:

- a short novice request written the way a user would say it, e.g. "I have
  aligned FASTA loci for five fruit-fly species and want to know how many
  species there are";
- fixture data;
- the decisions the user would make if asked;
- the expected result: analysis type, keywords that must appear, lint valid,
  smoke test ok.

`evals/run_evals.py` runs each scenario through a model against this server.
Make the model pluggable. Start with the Anthropic API and Claude tool use,
and design it so other providers, or a local model's agent loop, can be added.
Simulate the user with a second model that answers from the scenario's
decisions. Score each scenario on:

- final validity (lint and smoke test),
- correct scientific choices,
- number of tool calls,
- whether it ever wrote a file by hand or stated syntax without a docs lookup
  (detect this from the tool trace).

This same harness is how the owner will compare a frontier model with the
local fine-tuned bpp-agent model on equal terms. Keep it independent of any
one model.

## Packaging and docs

- **`pyproject.toml`:** console script `bpp-mcp = bpp_mcp.server:main`. It
  should install with `pipx install bpp-mcp` or run with `uvx bpp-mcp`.
  Later, add a Homebrew formula in `bpp/homebrew-tap` that depends on the
  other bpp tools.
- **README:**
  - what it is, and what it is not (it doesn't run long analyses);
  - install;
  - how to register it with each host;
  - the tool list;
  - a privacy note: what data reach the model;
  - how to switch hosts or models.
- **Host registration.** Check the current syntax against each host's docs
  before writing it down. As of late 2026:
  - Claude Code: `claude mcp add bpp -- bpp-mcp`. Add `--scope project` to
    write a shared `.mcp.json`.
  - Gemini CLI: an `mcpServers` entry in `settings.json`.
  - Codex: an `[mcp_servers.bpp]` table in `~/.codex/config.toml`.
- **`CLAUDE.md`:** project conventions, a one-line summary of the design rule,
  how to run the tests, and the workaround policy.

## Milestones

Commit at each one. Don't move on until the current milestone's tests pass.

1. **Skeleton:** package, `runner`, `sandbox`, `check_environment`, unit tests,
   CI for the unit tests.
2. **Core path:** `inspect_data`, `convert_data`, `build_species_tree`,
   `make_control_file` (with workarounds), `lint_control_file`,
   `lookup_docs`, `search_docs`, `explain_diagnostic`, `smoke_test`. The
   Anastrepha end-to-end test passes.
3. **Completeness:** `read_species_tree`, `set_keyword`,
   `upgrade_control_file`, `make_loci_bed`, `subset_loci`, `run_command`,
   resources, prompts, the defect-case and privacy tests.
4. **Docs and packaging:** README, host registration tested by hand in at
   least Claude Code, `pipx` install.
5. **Evaluation:** the task set and runner, with a baseline report in
   `evals/RESULTS.md`.

## Out of scope for v1

- Starting or monitoring long BPP runs, or submitting cluster jobs.
- Parsing BPP results and MCMC diagnostics. This is a good v2 tool:
  `summarize_results(jobname)`, reading the `.out` file and the MCMC sample
  file.
- HTTP transport and authentication.
- Any change to the upstream tools. File issues instead.
