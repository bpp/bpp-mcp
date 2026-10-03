# bpp-mcp: status and next steps

Handoff notes for a Claude Code session picking this project up on another
machine. Read `CLAUDE.md` (conventions) and `BPP-MCP-BUILD.md` (the full spec)
too. Last updated 2026-10-02.

## Set up on a new machine

```
git clone git@github.com:bpp/bpp-mcp.git && cd bpp-mcp
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/bpp-mcp install-tools      # pinned BPP tools -> ~/.local/share/bpp-mcp
.venv/bin/pytest -q                  # expect all passing, nothing skipped
```

To use it as a server: `claude mcp add --scope user bpp -- <path>/bpp-mcp`,
then `/mcp` in a session to confirm it is connected. End users install with
`curl -fsSL https://raw.githubusercontent.com/bpp/bpp-mcp/main/install.sh | sh`,
which installs the latest GitHub release (the development version from `main`
only while no release exists).

## Status

| Milestone | State |
|---|---|
| 1. Skeleton: runner, sandbox, check_environment, CI | done |
| Install path (not in the original spec) | done |
| 2. Core path, Anastrepha end-to-end | done |
| 3. Completeness | done |
| 4. Docs and packaging | done; v0.1.0 released 2026-10-02 |
| 5. Evaluation | harness and 13 scenarios done and tested offline; **the baseline run and `evals/RESULTS.md` are still to do** |

**Tools implemented (17):** check_environment, set_project (only with
`BPP_MCP_PROJECTS_DIR`), inspect_data, convert_data, make_loci_bed,
subset_loci, build_species_tree, read_species_tree, make_control_file,
set_keyword, lint_control_file, upgrade_control_file, lookup_docs,
search_docs, explain_diagnostic, smoke_test, run_command.

**Resources:** `bpp://manual/{keyword}`, `bpp://examples` (the list),
`bpp://examples/{name}`. **Prompts:** `novice_setup`, `upgrade_old_file`,
`check_my_ctl`.

**Verified:** over stdio, Anastrepha (10 loci, 5 species) goes inspect →
convert → tree → A10 / A00 / A11 control file → lint valid → smoke test ok, in
CI on Ubuntu and macOS (Apple Silicon). The owner has also tested it by hand in
Claude Code on a Mac (Milestone 2 tools only). The Milestone 3 tests pass in
CI on all four jobs (116 passed, none skipped). All 13 defect cases of `reference/BPP-LINT-FIXES.md` are covered
end-to-end, and the privacy check covers every registered tool.

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
- **set_keyword:** one line only. A keyword whose value continues over
  following lines in the file (`ctlfile.continuation_lines`, e.g.
  `species&tree`) is refused, and the model is told to remake the file. A
  trailing comment on the line is kept (`ctlfile.set_value` now does this
  for every caller). A new keyword is appended. There is no way to remove a
  keyword yet. The speciesdelimitation workaround is not applied to values
  the model sets; the re-lint and smoke test judge them.
- **run_command:** returns the absolute folder and the full path of the bpp
  binary the smoke test used, because `install-tools` does not put bpp on
  the user's PATH. It states no BPP rules: it reports the file's `jobname`
  and `threads` and sends the model to `lookup_docs` for `threads`.
- **Temporary data checks grew by two** (in `workarounds.data_checks`, same
  version gate): `imap_tags` (a `^tag` in the loci BPP reads with no Imap
  line, BPP153) and `speciesdelimitation` (argument count per algorithm,
  BPP017). Without them defect cases 1–3 and 7 lint "valid" and only the
  smoke test catches them. `BPP-MCP-BUILD.md` lists them.
- **Defect case 13** (`sub/rel.ctl`) is not a defect here: the server always
  runs BPP from the control file's folder, so it lints valid and runs.
- **upgrade_control_file** returns the lint result plus `server.upgrade`
  (`fixes_available`, `diff`, `applied`, `backup`). `apply=true` refuses to
  run when `<name>.bak` already exists, because `bpp-lint --fix` would
  overwrite it. With nothing to fix it does nothing.
- **Example resources** are only `*.ctl` files under
  `$BPP_MCP_HOME/tools/*/examples`; the name is the path below `examples/`
  joined with `-` (e.g. `frogs-A00.bpp.ctl`). Example data files are not
  served.
- **Releases are GitHub releases, not PyPI.** Pushing a tag `vX.Y.Z` that
  matches `__version__` runs `.github/workflows/release.yml`: build, run the
  tests against the built wheel, publish the wheel, the sdist, the same sdist
  as `bpp-mcp.tar.gz` (a fixed name, so
  `releases/latest/download/bpp-mcp.tar.gz` always works), `install.sh` and
  `SHA256SUMS`. "Run workflow" does all but publish. `install.sh` downloads
  that fixed-name file and falls back to `main` if there is no release.
  PyPI (so that `pipx install bpp-mcp` works) is left for the owner to
  decide; it needs a PyPI project and trusted publishing set up.
- **Host docs in the README** were checked on 2026-10-02 against
  code.claude.com/docs/en/mcp, modelcontextprotocol.io (Claude Desktop),
  developers.openai.com/codex/mcp and gemini-cli's docs/tools/mcp-server.md.
  None of the hosts documents the server's starting directory. Claude Code
  does start it in the launch directory (tested) and also sets
  `CLAUDE_PROJECT_DIR`, which `sandbox.from_env` could use as a fallback but
  does not yet. Codex and Gemini are untested by hand.
- **Evaluation design** (`evals/README.md` has the detail): two models per
  scenario, the assistant under test and a simulated user that answers from
  the scenario's `decisions`. Scores come only from the tool trace and the
  final files; the harness lints and smoke-tests the final control file
  itself. The assistant is also given `host_*` file tools so that writing a
  control file by hand is possible and detectable; doing so fails the
  scenario. "Set a keyword before looking it up" is reported but does not
  decide a pass. Providers plug in through `Model` / `Chat` in
  `evals/harness.py`; only `AnthropicModel` exists. Transcripts go to
  `evals/runs/` (git-ignored).
- **No comparison with the local bpp-agent model** (owner, 2026-10-03). The
  spec names that comparison as a purpose of the harness; it is dropped. The
  evaluation is only about whether a frontier model does the job with this
  server. Don't write a local-model adapter.
- **Every scenario has a reference solution** in `evals/reference.py`, replayed
  with no model by `tests/test_evals.py` (needs pyyaml, which is in the
  `test` extra). A new scenario without one fails the tests.
- **License:** AGPL-3.0-or-later, matching the other bpp tools.

## Next

1. **Release v0.1.0 is out** (https://github.com/bpp/bpp-mcp/releases/tag/v0.1.0),
   and `install.sh` installs it. Still worth doing once (owner): the
   `curl ... | sh` line from the README on a clean account or machine.
2. **By hand in an interactive Claude Code session** (owner): the prompts as
   slash commands and the resources. A headless `claude -p` session against
   the built 0.1.0 package did drive check_environment, lint, set_keyword,
   smoke_test and run_command on the tiny fixture (2026-10-02).
3. **Milestone 5 baseline** (needs the owner's go-ahead, it costs API
   money): `pip install -e '.[evals]'`, then
   `python evals/run_evals.py run --model claude-opus-5-5 -v` and
   `python evals/run_evals.py report evals/runs/* > evals/RESULTS.md`.
   `AnthropicModel` has not yet made a real API call; run one scenario first
   (`--tasks tiny_bpp_format`). Read the transcripts of any failures before
   concluding anything, then commit `RESULTS.md`.
4. After the baseline: more trials per scenario.

Possible small additions, not in the spec: a way to remove a keyword from a
control file; a `subset_loci` + `smoke_test` shortcut for very large data;
`CLAUDE_PROJECT_DIR` as a project-root fallback; PyPI.

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
- **bpp-lint 0.3.5, `--fix` on `legacy-3x.bpp.ctl`:** `outfile` and
  `mcmcfile` both become `jobname`, leaving two `jobname` lines (lint then
  warns BPP005, and BPP uses the last one). `--fix` also overwrites an
  existing `.bak` without asking.
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
