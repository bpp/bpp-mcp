# bpp-mcp

An MCP server that guides a researcher, including one new to BPP, from raw
sequence data to a validated BPP control file that has passed a short test
run. It wraps the bpp command-line tools (`bpp-seqs`, `bpp-tree`, `bpp-lint`,
`bpp-docs`, `bpp`) and never runs long analyses itself.

Status: early development (milestone 1 of 5). See `BPP-MCP-BUILD.md`.

## Install

Linux or macOS, no root needed:

```
curl -fsSL https://raw.githubusercontent.com/bpp/bpp-mcp/main/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) into `~/.local/bin` if you
don't have it (uv fetches a suitable Python if needed), installs `bpp-mcp`
with it, and runs `bpp-mcp install-tools`, which downloads the tested releases
of the BPP tools into `~/.local/share/bpp-mcp` and checks their SHA-256
hashes. Your shell startup files are not changed. At the end it prints the
command for registering the server with Claude Code or Claude Desktop.

To do the same steps by hand, with any Python >= 3.10:

```
python3 -m venv ~/.local/share/bpp-mcp/venv
~/.local/share/bpp-mcp/venv/bin/pip install https://github.com/bpp/bpp-mcp/archive/refs/heads/main.tar.gz
~/.local/share/bpp-mcp/venv/bin/bpp-mcp install-tools
```

Run `bpp-mcp install-tools` again at any time; it only downloads what is
missing or out of date.

Prebuilt tool releases currently cover:

| Tool | Linux x86_64 | Linux aarch64 | macOS arm64 | macOS x86_64 |
|---|---|---|---|---|
| bpp | yes | yes | yes | yes |
| bpp-seqs | yes | – | – | – |
| bpp-tree | yes | – | yes | yes |
| bpp-lint | yes | – | yes | yes |
| bpp-docs | yes | – | yes | yes |

For anything missing, build the tool from its repository and put it on PATH
(or set `BPP_MCP_<TOOL>`, e.g. `BPP_MCP_BPP_DOCS=/path/to/bpp-docs`). The
`check_environment` tool reports what was found.
