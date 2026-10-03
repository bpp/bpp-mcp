# bpp-mcp

An MCP server that guides a researcher, including one new to BPP, from raw
sequence data to a validated BPP control file that has passed a short test
run. You talk to an AI assistant (Claude Code, Claude Desktop, Codex, Gemini
CLI or any other MCP host); the assistant uses this server's tools to inspect
your data, build the species tree, write and check the control file, and test
it.

What it is not:

- It does not run your analysis. It runs BPP for a few seconds to prove the
  control file and data load, then tells you the command to start the real
  run yourself.
- It does not read BPP results or judge MCMC convergence.
- It holds no BPP knowledge of its own. Syntax, defaults and checks come from
  the bpp command-line tools it wraps (`bpp-seqs`, `bpp-tree`, `bpp-lint`,
  `bpp-docs`, `bpp`), and the assistant is told to quote the manual rather
  than answer from memory.

## Install

Linux or macOS, no root needed:

```
curl -fsSL https://raw.githubusercontent.com/bpp/bpp-mcp/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if you
don't have it (uv fetches a suitable Python if needed), installs the latest
`bpp-mcp` release with it, and runs `bpp-mcp install-tools`, which downloads
the tested releases of the BPP tools into `~/.local/share/bpp-mcp` and checks
their SHA-256 hashes. Your shell startup files are not changed. At the end it
prints the command for registering the server with Claude Code or Claude
Desktop.

To do the same steps by hand, with any Python >= 3.10, install the release
with the tool you prefer and then fetch the BPP tools:

```
pipx install https://github.com/bpp/bpp-mcp/releases/latest/download/bpp-mcp.tar.gz
bpp-mcp install-tools
```

`uv tool install <that URL>` and `pip install <that URL>` in a virtual
environment work the same way. bpp-mcp is not on PyPI yet, so
`pipx install bpp-mcp` does not work.

Run `bpp-mcp install-tools` again at any time; it only downloads what is
missing or out of date.

Prebuilt tool releases currently cover:

| Tool | Linux x86_64 | Linux aarch64 | macOS arm64 | macOS x86_64 |
|---|---|---|---|---|
| bpp | yes | yes | yes | yes |
| bpp-seqs | yes | – | yes | yes |
| bpp-tree | yes | – | yes | yes |
| bpp-lint | yes | – | yes | yes |
| bpp-docs | yes | – | yes | yes |

For anything missing, build the tool from its repository and put it on PATH
(or set `BPP_MCP_<TOOL>`, e.g. `BPP_MCP_BPP_DOCS=/path/to/bpp-docs`). The
`check_environment` tool reports what was found.

## Register it with your AI host

The server is one command, `bpp-mcp`, speaking MCP over stdio. `bpp-mcp
install-tools` prints its full path; use that path below in place of
`/path/to/bpp-mcp`.

The server only reads and writes inside one **project directory**:

- `BPP_MCP_ROOT`, if set; otherwise the directory the host starts the server
  in.
- With `BPP_MCP_PROJECTS_DIR` set instead, the assistant asks which folder
  under it to use (the `set_project` tool). This is for desktop apps, which
  start servers in no particular directory.

The first thing the assistant does is call `check_environment`, which reports
the project directory. If it is not the folder holding your data, set
`BPP_MCP_ROOT` to that folder's absolute path.

### Claude Code

```
claude mcp add --scope user bpp -- /path/to/bpp-mcp
```

Start `claude` in the folder holding your data; that folder is the project
directory. `/mcp` inside a session shows whether the server is connected,
and `claude mcp get bpp` and `claude mcp remove bpp` inspect and remove it.
To share the server with everyone working in one repository, use
`--scope project`, which writes `.mcp.json` there. This registration was
tested with Claude Code on macOS.

### Claude Desktop

Settings > Developer > Edit Config opens `claude_desktop_config.json`
(`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on
Windows; bpp-mcp itself supports only macOS and Linux). Add:

```json
{
  "mcpServers": {
    "bpp": {
      "command": "/path/to/bpp-mcp",
      "env": { "BPP_MCP_PROJECTS_DIR": "/Users/you/bpp-projects" }
    }
  }
}
```

Quit and reopen the app. Put each analysis in its own folder under that
directory. The app's log for the server is
`~/Library/Logs/Claude/mcp-server-bpp.log`.

### Codex CLI

```
codex mcp add bpp -- /path/to/bpp-mcp
```

or in `~/.codex/config.toml`:

```toml
[mcp_servers.bpp]
command = "/path/to/bpp-mcp"
```

`/mcp` in Codex lists the server. Codex's documentation does not say which
directory the server starts in. If `check_environment` reports the wrong
project directory, add `cwd = "/path/to/project"` to the table or pass
`--env BPP_MCP_ROOT=/path/to/project`.

### Gemini CLI

```
gemini mcp add -s user bpp /path/to/bpp-mcp
```

(no `--` before the command), or in `~/.gemini/settings.json`:

```json
{
  "mcpServers": {
    "bpp": { "command": "/path/to/bpp-mcp" }
  }
}
```

`/mcp` in Gemini CLI lists the server. As with Codex, the starting directory
is not documented; add `"cwd": "/path/to/project"` or
`"env": { "BPP_MCP_ROOT": "/path/to/project" }` if the project directory is
wrong.

The Codex and Gemini entries follow those hosts' documentation as of October
2026 and have not been tried by hand.

### Switching hosts or models

Nothing in the server depends on the host or the model. Register the same
`bpp-mcp` command with another host and point it at the same project
directory; the data, tree and control files are ordinary files there, and
any assistant can pick up where another stopped by linting the control file
again.

## What the assistant can do

The usual path is: check the installation, inspect the data, convert it,
build the tree, make the control file, lint it until valid, test it, and
hand you the run command.

| Tool | What it does |
|---|---|
| `check_environment` | Finds the BPP tools, checks their versions, reports the project directory. |
| `set_project` | Chooses the project folder (only with `BPP_MCP_PROJECTS_DIR`). |
| `inspect_data` | Summarises your data files and Imap without changing anything. |
| `convert_data` | Converts alignments, BAM/CRAM or gVCF data to a BPP sequence file. |
| `make_loci_bed` | Tiles a genome into candidate loci when you have no BED file. |
| `subset_loci` | Writes a sequence file with a subset of the loci, e.g. for a trial run. |
| `build_species_tree` | Builds the species or guide tree from joins such as `A+B, A_B+C`, and draws it. |
| `read_species_tree` | Reads a tree you already have (Newick, or an old control file). |
| `make_control_file` | Writes the control file for an A00, A01, A10 or A11 analysis, with priors derived from the data. |
| `set_keyword` | Changes one keyword in a control file and lints it again. |
| `lint_control_file` | Validates a control file and checks it against its data files. |
| `upgrade_control_file` | Shows, then applies, the fixes that bring a BPP 2.x/3.x file up to date. |
| `lookup_docs`, `search_docs` | Quote the BPP manual. |
| `explain_diagnostic` | Explains a lint diagnostic code. |
| `smoke_test` | Runs BPP briefly on a copy of the control file to prove it loads. |
| `run_command` | Gives you the command and folder for the real run. Does not start it. |

Three prompts start the common jobs (in Claude Code they appear as slash
commands): `novice_setup`, `upgrade_old_file` and `check_my_ctl`. Two
resources are available to hosts that load them: `bpp://manual/{keyword}`
and `bpp://examples/{name}` (the example control files shipped with BPP and
bpp-lint; `bpp://examples` lists them).

## Privacy: what reaches the model

Whatever a tool returns is sent to the AI model your host uses, which is
usually a service run by a third party. The server is built so that your
sequences are not:

- Tools return summaries: counts, file and sample names, species names,
  per-locus statistics, lint diagnostics, control-file text, and BPP's
  screen output from the test run.
- Any run of more than 30 nucleotide characters in a result is replaced by a
  note saying how many characters were removed, and long lists and strings
  are cut, with a note saying so.
- The tests check, for every tool, that no sequence from the test data
  appears in its output.

Sample names, species names, file names and locus coordinates do reach the
model. The server itself makes no network connections while serving; only
`bpp-mcp install-tools` downloads anything. The assistant can still read
files itself if your host gives it its own file access, which this server
does not control.

## Development

```
python3 -m venv .venv && .venv/bin/pip install -e '.[test]'
.venv/bin/bpp-mcp install-tools
.venv/bin/pytest -q
```

`BPP-MCP-BUILD.md` is the specification and `claude_next.md` the current
status. To release, set `__version__`, tag `vX.Y.Z` and push the tag; the
release workflow builds, tests and publishes. Its "Run workflow" button
does everything except publish.

Licence: AGPL-3.0-or-later.
