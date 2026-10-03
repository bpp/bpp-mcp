#!/bin/sh
# Install bpp-mcp and the BPP command-line tools into your home directory.
# No root, no conda, no Python needed in advance; needs curl or wget.
#
#   curl -fsSL https://raw.githubusercontent.com/bpp/bpp-mcp/main/install.sh | sh
#
# What it does:
#   1. installs uv (https://docs.astral.sh/uv/) into ~/.local/bin if missing;
#      uv downloads a suitable Python itself if the system has none
#   2. uv tool install bpp-mcp      (the server, in its own environment)
#   3. bpp-mcp install-tools        (bpp, bpp-seqs, bpp-tree, bpp-lint, bpp-docs)
# Shell startup files are not modified.
#
# Environment:
#   BPP_MCP_SPEC   what to install (default: the main branch on GitHub;
#                  a local checkout path also works)
#   BPP_MCP_HOME   where the BPP tools go (default: ~/.local/share/bpp-mcp)

set -eu

SPEC=${BPP_MCP_SPEC:-https://github.com/bpp/bpp-mcp/archive/refs/heads/main.tar.gz}
UV_INSTALLER=https://astral.sh/uv/install.sh

die() {
    printf 'install.sh: %s\n' "$*" >&2
    exit 1
}

fetch() {  # fetch URL FILE
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -q "$1" -O "$2"
    else
        die "need curl or wget to download files"
    fi
}

find_uv() {
    if command -v uv >/dev/null 2>&1; then
        command -v uv
    elif [ -x "$HOME/.local/bin/uv" ]; then
        printf '%s\n' "$HOME/.local/bin/uv"
    fi
}

main() {
    case $(uname -s) in
        Linux | Darwin) ;;
        *) die "only Linux and macOS are supported" ;;
    esac

    UV=$(find_uv)
    if [ -z "$UV" ]; then
        echo "Installing uv into ~/.local/bin ..."
        tmp=$(mktemp)
        fetch "$UV_INSTALLER" "$tmp" || die "could not download $UV_INSTALLER"
        UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$tmp" --quiet \
            || die "uv installation failed"
        rm -f "$tmp"
        UV="$HOME/.local/bin/uv"
        [ -x "$UV" ] || die "uv installed but not found at $UV"
    fi

    echo "Installing bpp-mcp from $SPEC ..."
    "$UV" tool install --quiet --force --python '>=3.10' "$SPEC" \
        || die "uv could not install bpp-mcp"

    BPP_MCP="$("$UV" tool dir --bin)/bpp-mcp"
    [ -x "$BPP_MCP" ] || die "bpp-mcp installed but not found at $BPP_MCP"
    "$BPP_MCP" install-tools
}

# Everything runs from here, so a partially downloaded script does nothing.
main "$@"
