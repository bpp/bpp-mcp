"""`bpp-mcp install-tools`: download the pinned BPP tool releases. No root needed.

Each release tarball (listed with its sha256 in toolset.json) is verified and
unpacked into ``<home>/tools/<name>-<version>/``, examples included, and its
binary is linked as ``<home>/bin/<name>``. ``runner.find()`` looks there before
PATH, so hosts with a minimal PATH (desktop apps) still find the tools.

``<home>`` is $BPP_MCP_HOME, else $XDG_DATA_HOME/bpp-mcp, else
~/.local/share/bpp-mcp.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from importlib import resources
from pathlib import Path

from . import __version__

MANIFEST: dict = {k: v for k, v in json.loads(
    resources.files("bpp_mcp").joinpath("toolset.json").read_text()).items()
    if not k.startswith("_")}

RELEASE_BASE = "https://github.com"


def home() -> Path:
    if os.environ.get("BPP_MCP_HOME"):
        return Path(os.environ["BPP_MCP_HOME"]).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share") / "bpp-mcp"


def bin_dir() -> Path:
    return home() / "bin"


def platform_key(system: str | None = None, machine: str | None = None) -> str | None:
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    os_name = {"linux": "linux", "darwin": "macos"}.get(system)
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
    if not os_name or not arch:
        return None
    if os_name == "macos" and arch == "aarch64":
        arch = "arm64"
    return f"{os_name}-{arch}"


def available(name: str, key: str | None = None) -> bool:
    key = key or platform_key()
    return bool(key and key in MANIFEST.get(name, {}).get("assets", {}))


def source_hint(name: str) -> str:
    return f"build it from source: https://github.com/{MANIFEST[name]['repo']}"


def _download(url: str, dest: Path, timeout: float = 60) -> str:
    """Stream url to dest; return the sha256 hex digest."""
    req = urllib.request.Request(url, headers={"User-Agent": f"bpp-mcp/{__version__}"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 16):
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def _safe_extract(tar_path: Path, dest: Path) -> None:
    with tarfile.open(tar_path) as tf:
        if hasattr(tarfile, "data_filter"):
            tf.extractall(dest, filter="data")
            return
        # Python without extraction filters: allow only plain files and
        # directories with relative paths that stay inside dest.
        for m in tf.getmembers():
            p = Path(m.name)
            if p.is_absolute() or ".." in p.parts or not (m.isfile() or m.isdir()):
                raise RuntimeError(f"refusing unsafe archive member {m.name!r}")
        tf.extractall(dest)


def _version_ok(name: str, exe: Path, version: str) -> tuple[bool, str]:
    from .tools.env import parse_version
    try:
        r = subprocess.run([str(exe), "--version"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"installed binary does not run: {e}"
    got = parse_version(name, r.stdout + r.stderr)
    if got != version:
        return False, f"installed binary reports version {got}, expected {version}"
    return True, ""


def install_tool(name: str, *, force: bool = False, key: str | None = None) -> dict:
    spec = MANIFEST[name]
    version = spec["version"]
    key = key or platform_key()
    asset = spec["assets"].get(key) if key else None
    if not asset:
        why = f"no {key or 'release for this platform'} release" if spec["tag"] else "no release published yet"
        return {"tool": name, "status": "unavailable", "detail": f"{why}; {source_hint(name)}"}

    tools_dir, link = home() / "tools", bin_dir() / name
    target = tools_dir / f"{name}-{version}"
    if not force and link.is_symlink() and target in link.resolve().parents:
        ok, msg = _version_ok(name, link, version)
        if ok:
            return {"tool": name, "status": "up to date", "detail": version}

    tools_dir.mkdir(parents=True, exist_ok=True)
    bin_dir().mkdir(parents=True, exist_ok=True)
    url = f"{RELEASE_BASE}/{spec['repo']}/releases/download/{spec['tag']}/{asset['name']}"
    with tempfile.TemporaryDirectory(dir=tools_dir, prefix=".download-") as tmp:
        tmpd = Path(tmp)
        archive = tmpd / asset["name"]
        try:
            digest = _download(url, archive)
        except OSError as e:
            return {"tool": name, "status": "failed", "detail": f"download failed: {url}: {e}"}
        if digest != asset["sha256"]:
            return {"tool": name, "status": "failed",
                    "detail": f"checksum mismatch for {asset['name']} (got {digest}); not installed"}
        unpacked = tmpd / "unpacked"
        try:
            _safe_extract(archive, unpacked)
        except (tarfile.TarError, RuntimeError, OSError) as e:
            return {"tool": name, "status": "failed", "detail": f"could not unpack {asset['name']}: {e}"}
        found = [p for p in unpacked.rglob(name) if p.is_file() and os.access(p, os.X_OK)]
        if len(found) != 1:
            return {"tool": name, "status": "failed",
                    "detail": f"expected one '{name}' executable in {asset['name']}, found {len(found)}"}
        # Keep the release's own top-level folder contents (examples, README).
        tops = list(unpacked.iterdir())
        root = tops[0] if len(tops) == 1 and tops[0].is_dir() else unpacked
        rel_exe = found[0].relative_to(root)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(root), str(target))

    tmp_link = link.with_name(f".{name}.tmp")
    tmp_link.unlink(missing_ok=True)
    tmp_link.symlink_to(target / rel_exe)
    os.replace(tmp_link, link)

    ok, msg = _version_ok(name, link, version)
    if not ok:
        return {"tool": name, "status": "failed", "detail": msg}
    _remove_old_versions(name, keep=target)
    return {"tool": name, "status": "installed", "detail": version}


def _remove_old_versions(name: str, keep: Path) -> None:
    pat = re.compile(rf"{re.escape(name)}-\d[\d.]*")
    for d in (home() / "tools").iterdir():
        if d != keep and d.is_dir() and pat.fullmatch(d.name):
            shutil.rmtree(d, ignore_errors=True)


def _self_path() -> str:
    exe = shutil.which("bpp-mcp")
    return exe or str(Path(sys.argv[0]).absolute())


def next_steps() -> str:
    exe = _self_path()
    projects = Path.home() / "bpp-projects"
    desktop = json.dumps({"mcpServers": {"bpp": {
        "command": exe, "env": {"BPP_MCP_PROJECTS_DIR": str(projects)}}}}, indent=2)
    return f"""\
Register bpp-mcp with your AI host:

  Claude Code (all projects; tools see the folder you start claude in):
    claude mcp add --scope user bpp -- {exe}

  Claude Desktop: add this to claude_desktop_config.json, then restart the app.
  Put each analysis in its own folder under {projects} (mkdir -p {projects}).
{desktop}

  Other hosts: https://github.com/bpp/bpp-mcp#readme
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bpp-mcp install-tools",
        description="Download the BPP command-line tools this bpp-mcp version is tested with "
                    f"into {home()} (no root needed).")
    ap.add_argument("tools", nargs="*", metavar="TOOL",
                    help=f"tools to install (default: all of {', '.join(MANIFEST)})")
    ap.add_argument("--force", action="store_true", help="reinstall even if up to date")
    args = ap.parse_args(argv)
    unknown = [t for t in args.tools if t not in MANIFEST]
    if unknown:
        ap.error(f"unknown tool(s): {', '.join(unknown)}; choose from {', '.join(MANIFEST)}")

    key = platform_key()
    print(f"Installing BPP tools for {key or platform.platform()} into {home()}")
    results = [install_tool(n, force=args.force, key=key) for n in (args.tools or MANIFEST)]
    width = max(len(r["tool"]) for r in results)
    for r in results:
        print(f"  {r['tool']:<{width}}  {r['status']:<11}  {r['detail']}")
    failed = [r for r in results if r["status"] == "failed"]
    missing = [r for r in results if r["status"] == "unavailable"]
    if missing:
        print(f"\n{len(missing)} tool(s) have no prebuilt release for this platform. Install them "
              "another way (see above), or put them on PATH; check_environment will find them.")
    if failed:
        print(f"\n{len(failed)} tool(s) failed to install.", file=sys.stderr)
        return 1
    print("\n" + next_steps())
    return 0
