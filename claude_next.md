# bpp-mcp: status and next steps

Handoff notes for a Claude Code session picking this project up on another
machine. Read `CLAUDE.md` (conventions) and `BPP-MCP-BUILD.md` (the full spec)
too. Last updated 2026-10-03.

## Set up on a new machine

```
git clone git@github.com:bpp/bpp-mcp.git && cd bpp-mcp
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/bpp-mcp install-tools      # pinned BPP tools -> ~/.local/share/bpp-mcp
.venv/bin/pytest -q                  # expect all passing, nothing skipped
```

To use it as a server: `claude mcp add --scope user bpp -- <path>/bpp-mcp`,
then `/mcp` in a session to confirm it is connected. End users install with
`curl -fsSL https://raw.githubusercontent.com/bpp/bpp-mcp/main/install.sh | sh`.

## Status

| Milestone | State |
|---|---|
| 1. Skeleton: runner, sandbox, check_environment, CI | done |
| Install path (not in the original spec) | done |
| 2. Core path, Anastrepha end-to-end | done |
| 3. Completeness | **next** |
| 4. Docs and packaging | partly done (install docs, CI install job) |
| 5. Evaluation | not started |

**Tools implemented (11):** check_environment, set_project (only with
`BPP_MCP_PROJECTS_DIR`), inspect_data, convert_data, build_species_tree,
make_control_file, lint_control_file, lookup_docs, search_docs,
explain_diagnostic, smoke_test.

**Verified:** over stdio, Anastrepha (10 loci, 5 species) goes inspect →
convert → tree → A10 / A00 / A11 control file → lint valid → smoke test ok, in
CI on Ubuntu and macOS (Apple Silicon). The owner has also tested it by hand in
Claude Code on a Mac.

## Decisions already made (don't relitigate)

- **Install:** `install.sh` installs uv, then `uv tool install bpp-mcp`, then
  `bpp-mcp install-tools`. No root, no conda, shell rc files untouched.
  `install-tools` downloads the releases pinned in `src/bpp_mcp/toolset.json`
  and checks their sha256. The pinned versions are also the minimums
  `check_environment` enforces. To move to a new tool release, update
  `toolset.json` (hashes from the release's `SHA256SUMS`) and run the tests.
- **Binary lookup order:** `$BPP_MCP_<TOOL>`, then
  `~/.local/share/bpp-mcp/bin` (`$BPP_MCP_HOME`), then PATH, then common
  Homebrew folders. Desktop apps start servers with a minimal PATH, which is
  why the managed folder comes first.
- **Project root:** `BPP_MCP_ROOT`, else the startup directory. With
  `BPP_MCP_PROJECTS_DIR` set (Claude Desktop), the startup directory is
  ignored and the model calls `set_project`. A startup directory of `/` means
  no project is set.
- **Paths:** tools run with cwd = project root (data, tree) or the control
  file's folder (lint, smoke test), and get relative paths, so reports never
  show absolute paths. Control files hold data paths relative to themselves.
- **lint_control_file adds `server.status`**, which is "valid" only if
  bpp-lint and the temporary data checks both find no errors. The model is
  told to loop on that, not on `report.status`.
- **Workarounds** (`workarounds.py`, gated on bpp-lint <= 0.3.5): bare
  `speciesdelimitation = 1` is rewritten to `1 0 2`; temporary data checks
  (files exist, nloci, Imap vs tree species, phase digits). Both switch off
  automatically when a newer bpp-lint is pinned. If that release still has
  the bug, raise `max_affected`.
- **License:** AGPL-3.0-or-later, matching the other bpp tools.

## Next: Milestone 3

From `BPP-MCP-BUILD.md`, still to do:

1. **`set_keyword(ctl, keyword, value)`**: check the keyword against
   `docs.keywords()`, edit with `ctlfile.set_value` (keeps layout and
   comments), re-lint, return the lint result. The server instructions
   already refer to it.
2. **`run_command(ctl)`**: does not run BPP. Returns the exact command
   (`bpp --cfile <name>`), the folder to run it from (the control file's),
   and a note on `threads` and HPC submission. The instructions already refer
   to it.
3. **`read_species_tree(path)`**: `bpp-tree --json --read`.
4. **`upgrade_control_file(ctl, apply=False)`**: `bpp-lint --diff`, or
   `--fix` (which writes `.bak`) only when `apply=True`. Test on
   `legacy-3x.bpp.ctl`, which install-tools unpacks to
   `~/.local/share/bpp-mcp/tools/bpp-lint-0.3.5/examples/`.
5. **`make_loci_bed`** (`bpp-seqs windows`) and **`subset_loci`**
   (`bpp-seqs extract`): check each subcommand's `--help` in bpp-seqs 0.2.0
   first.
6. **Resources:** `bpp://manual/{keyword}` (bpp-docs) and
   `bpp://examples/{name}` (the examples unpacked under
   `~/.local/share/bpp-mcp/tools/*/examples`).
7. **Prompts:** `novice_setup`, `upgrade_old_file`, `check_my_ctl`.
8. **Tests:** every defect case in `reference/BPP-LINT-FIXES.md` (table rows
   1–13) on `tests/fixtures/tiny` must give a lint error or a
   `server.data_checks` issue, plus `smoke_test` ok=false with BPP's error
   line. Extend the privacy test (`assert_private` in `tests/test_e2e.py`)
   to every tool. Narrow `needs_tools` so tests that need only bpp-lint and
   bpp don't skip when bpp-seqs is missing.

Then Milestone 4 (README host registration for Claude Desktop, Codex and
Gemini CLI, checked against their current docs; PyPI or tagged releases so
`install.sh` stops tracking `main`) and Milestone 5 (evaluation harness).

## Related changes made in other repos

- **bpp/bpp-docs v0.1.0:** first release. Linux static (`make NO_CURL=1
  STATIC=1`; `--update` runs the `curl` command), macOS arm64 and x86_64.
  `release.yml` has a manual "Run workflow" option that builds without
  publishing. Formula added to bpp/homebrew-tap; the `HOMEBREW_TAP_TOKEN4`
  secret was set by the owner but hasn't been exercised by a release yet.
- **bpp/bpp-seqs v0.2.0:** macOS arm64 and x86_64 builds added (static
  htslib, no lzma), the smoke test moved to the current examples, and the
  same manual dry-run option. The Homebrew bump worked.

## Known upstream issues (fix there, not here)

- **bpp-lint 0.3.5:** the A10/A11 template bug and missing data checks. The
  full fix spec is `reference/BPP-LINT-FIXES.md` (codes BPP150–156).
- **bpp-lint, bpp-tree:** Linux binaries need glibc >= 2.34, so they won't
  run on RHEL 8 / older clusters. Build them statically as bpp-seqs and
  bpp-docs now do.
- **Linux aarch64:** only bpp has a release.
- **bpp-seqs, CRAM:** a reference FASTA given on the command line isn't used
  to decode CRAM, so htslib falls back to the path in the CRAM header (the
  test CRAMs point at `/Users/bruce/...`). It was dropped from the release
  smoke test.
- **bpp-seqs, `n_snps`:** reported as 1791 of 2028 sites for an Anastrepha
  locus, which looks like gap or missing columns being counted. Not
  investigated.
- **bpp:** releases have no `SHA256SUMS` (hashes are pinned in
  `toolset.json` anyway).
- **bpp-lint `--template --out -`** writes a file named `-`, so always pass a
  real path.

## Gotchas learned the hard way

- `pytest | tail` hides pytest's exit code. Check `$?` of pytest itself
  before committing; one red commit reached `main` this way.
- `tests/conftest.py` points `BPP_MCP_HOME` at an empty temp folder for
  every test. The end-to-end tests pass the real install location to the
  server subprocess (`REAL_HOME` in `test_e2e.py`).
- `gh secret set` run through Claude Code's `!` prefix has no terminal to
  prompt in, so it may store an empty value. Set secrets in a real terminal
  or on the web.
- Release workflows in bpp-docs and bpp-seqs: use "Run workflow" (dry run)
  before pushing a tag.
