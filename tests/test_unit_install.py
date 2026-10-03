import hashlib
import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from bpp_mcp import install, runner
from bpp_mcp import server

KEY = "linux-x86_64"


def _exe(text: str) -> bytes:
    return f"#!/bin/sh\necho '{text}'\n".encode()


def make_release(base: Path, name: str, version: str, *, exe_version: str | None = None,
                 extra: dict[str, bytes] | None = None, top: str | None = None,
                 evil: bool = False) -> dict:
    """Write a fake GitHub release tarball under ``base``; return its manifest entry."""
    tag = f"v{version}"
    asset = f"{name}-{version}-{KEY}.tar.gz"
    top = top if top is not None else f"{name}-{version}-{KEY}"
    files = {f"{name}": (_exe(f"{name} {exe_version or version}"), 0o755),
             "examples/demo.ctl": (b"seed = 1\n", 0o644)}
    for k, v in (extra or {}).items():
        files[k] = (v, 0o644)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, (data, mode) in files.items():
            ti = tarfile.TarInfo(f"{top}/{rel}" if top else rel)
            ti.size, ti.mode = len(data), mode
            tf.addfile(ti, io.BytesIO(data))
        if evil:
            ti = tarfile.TarInfo("../escaped.txt")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
    data = buf.getvalue()
    d = base / "bpp" / name / "releases" / "download" / tag
    d.mkdir(parents=True, exist_ok=True)
    (d / asset).write_bytes(data)
    return {"repo": f"bpp/{name}", "tag": tag, "version": version,
            "assets": {KEY: {"name": asset, "sha256": hashlib.sha256(data).hexdigest()}}}


@pytest.fixture
def releases(tmp_path, monkeypatch):
    base = tmp_path / "gh"
    base.mkdir()
    monkeypatch.setattr(install, "RELEASE_BASE", base.as_uri())
    manifest = {}
    monkeypatch.setattr(install, "MANIFEST", manifest)
    return base, manifest


def test_platform_key():
    assert install.platform_key("Linux", "x86_64") == "linux-x86_64"
    assert install.platform_key("Linux", "aarch64") == "linux-aarch64"
    assert install.platform_key("Darwin", "arm64") == "macos-arm64"
    assert install.platform_key("Darwin", "x86_64") == "macos-x86_64"
    assert install.platform_key("Windows", "AMD64") is None
    assert install.platform_key("Linux", "ppc64le") is None


def test_home_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("BPP_MCP_HOME", str(tmp_path / "h"))
    assert install.home() == tmp_path / "h"
    monkeypatch.delenv("BPP_MCP_HOME")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert install.home() == tmp_path / "xdg" / "bpp-mcp"
    monkeypatch.delenv("XDG_DATA_HOME")
    assert install.home() == Path.home() / ".local" / "share" / "bpp-mcp"


def test_real_manifest_is_well_formed():
    m = install.MANIFEST
    assert set(m) == {"bpp-seqs", "bpp-tree", "bpp-lint", "bpp-docs", "bpp"}
    for spec in m.values():
        assert spec["version"] and spec["repo"].startswith("bpp/")
        for key, a in spec["assets"].items():
            assert key in {"linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-arm64"}
            assert len(a["sha256"]) == 64 and a["name"].endswith(".tar.gz")


def test_install_and_up_to_date(releases):
    base, manifest = releases
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.2.0")
    r = install.install_tool("bpp-zzz", key=KEY)
    assert r == {"tool": "bpp-zzz", "status": "installed", "detail": "1.2.0"}
    link = install.bin_dir() / "bpp-zzz"
    target = install.home() / "tools" / "bpp-zzz-1.2.0"
    assert link.is_symlink() and link.resolve() == target / "bpp-zzz"
    assert (target / "examples" / "demo.ctl").is_file()
    assert install.install_tool("bpp-zzz", key=KEY)["status"] == "up to date"
    assert install.install_tool("bpp-zzz", key=KEY, force=True)["status"] == "installed"
    # no leftover download folders
    assert [p.name for p in (install.home() / "tools").iterdir()] == ["bpp-zzz-1.2.0"]


def test_upgrade_removes_old_version_only(releases):
    base, manifest = releases
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.0.0")
    manifest["bpp-zzz-extra"] = make_release(base, "bpp-zzz-extra", "1.0.0")
    install.install_tool("bpp-zzz", key=KEY)
    install.install_tool("bpp-zzz-extra", key=KEY)
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.1.0")
    assert install.install_tool("bpp-zzz", key=KEY)["status"] == "installed"
    names = sorted(p.name for p in (install.home() / "tools").iterdir())
    assert names == ["bpp-zzz-1.1.0", "bpp-zzz-extra-1.0.0"]


def test_flat_tarball_without_top_folder(releases):
    base, manifest = releases
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.0.0", top="")
    assert install.install_tool("bpp-zzz", key=KEY)["status"] == "installed"
    assert (install.home() / "tools" / "bpp-zzz-1.0.0" / "examples" / "demo.ctl").is_file()


def test_checksum_mismatch_installs_nothing(releases):
    base, manifest = releases
    spec = make_release(base, "bpp-zzz", "1.0.0")
    spec["assets"][KEY]["sha256"] = "0" * 64
    manifest["bpp-zzz"] = spec
    r = install.install_tool("bpp-zzz", key=KEY)
    assert r["status"] == "failed" and "checksum mismatch" in r["detail"]
    assert not (install.bin_dir() / "bpp-zzz").exists()
    assert list((install.home() / "tools").iterdir()) == []


def test_unsafe_archive_rejected(releases, tmp_path):
    base, manifest = releases
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.0.0", evil=True)
    r = install.install_tool("bpp-zzz", key=KEY)
    assert r["status"] == "failed" and "unpack" in r["detail"]
    assert not list(tmp_path.rglob("escaped.txt"))


def test_wrong_version_in_binary(releases):
    base, manifest = releases
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.0.0", exe_version="0.9.0")
    r = install.install_tool("bpp-zzz", key=KEY)
    assert r["status"] == "failed" and "0.9.0" in r["detail"]


def test_download_failure(releases):
    _, manifest = releases
    manifest["bpp-zzz"] = {"repo": "bpp/nowhere", "tag": "v1", "version": "1",
                           "assets": {KEY: {"name": "x.tar.gz", "sha256": "0" * 64}}}
    r = install.install_tool("bpp-zzz", key=KEY)
    assert r["status"] == "failed" and "download failed" in r["detail"]


def test_unavailable(releases):
    _, manifest = releases
    manifest["bpp-none"] = {"repo": "bpp/bpp-none", "tag": None, "version": "0.1.0", "assets": {}}
    manifest["bpp-mac"] = {"repo": "bpp/bpp-mac", "tag": "v1", "version": "1",
                           "assets": {"macos-arm64": {"name": "a", "sha256": "0" * 64}}}
    r1 = install.install_tool("bpp-none", key=KEY)
    r2 = install.install_tool("bpp-mac", key=KEY)
    assert r1["status"] == r2["status"] == "unavailable"
    assert "no release published" in r1["detail"] and "github.com/bpp/bpp-none" in r1["detail"]
    assert KEY in r2["detail"]


def test_main_exit_codes_and_next_steps(releases, monkeypatch, capsys):
    base, manifest = releases
    monkeypatch.setattr(install, "platform_key", lambda *a: KEY)
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.0.0")
    manifest["bpp-none"] = {"repo": "bpp/bpp-none", "tag": None, "version": "0.1.0", "assets": {}}
    assert install.main([]) == 0
    out = capsys.readouterr().out
    assert "claude mcp add --scope user bpp --" in out and "BPP_MCP_PROJECTS_DIR" in out
    assert "no prebuilt release" in out
    spec = make_release(base, "bpp-bad", "1.0.0")
    spec["assets"][KEY]["sha256"] = "0" * 64
    manifest["bpp-bad"] = spec
    assert install.main(["bpp-bad"]) == 1
    with pytest.raises(SystemExit):
        install.main(["not-a-tool"])


def test_runner_prefers_installed_tools(releases, tmp_path, monkeypatch):
    base, manifest = releases
    manifest["bpp-zzz"] = make_release(base, "bpp-zzz", "1.0.0")
    other = tmp_path / "path-bin"
    other.mkdir()
    p = other / "bpp-zzz"
    p.write_bytes(_exe("bpp-zzz 9.9.9"))
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(other))
    assert runner.find("bpp-zzz") == str(p)
    install.install_tool("bpp-zzz", key=KEY)
    assert runner.find("bpp-zzz") == str(install.bin_dir() / "bpp-zzz")


def test_cli_dispatch(capsys):
    server.main(["--version"])
    assert capsys.readouterr().out.startswith("bpp-mcp ")
    server.main(["--help"])
    assert "install-tools" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        server.main(["bogus"])
    assert "unknown command" in str(e.value.code)
