"""Tool behaviour that needs no real BPP binaries (fakes stand in where needed)."""
import stat
import textwrap
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from bpp_mcp import runner, sandbox
from bpp_mcp.tools import ctl, data, docs, run, tree

TINY = Path(__file__).parent / "fixtures" / "tiny"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    p.mkdir()
    for f in TINY.iterdir():
        (p / f.name).write_bytes(f.read_bytes())
    monkeypatch.setattr(sandbox, "current", sandbox.Sandbox(p))
    return p


def fake(tmp_path, monkeypatch, name, script):
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text("#!/bin/sh\n" + textwrap.dedent(script))
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv(runner._env_override(name), str(f))
    return f


def test_explain_code_format():
    for bad in ["", "abc", "BPP1", "1234"]:
        with pytest.raises(ToolError, match="not a bpp-lint code"):
            docs.explain_diagnostic(bad)


def test_canonical_keyword(monkeypatch):
    monkeypatch.setattr(ctl, "keywords", lambda: ["Imapfile", "wprior", "threads"])
    assert ctl._canonical_keyword("imapfile") == "Imapfile"
    assert ctl._canonical_keyword(" WPRIOR ") == "wprior"
    with pytest.raises(ToolError, match="not a BPP control-file keyword"):
        ctl._canonical_keyword("speciesdelimitations")


def test_make_control_file_refuses(proj):
    (proj / "a.ctl").write_text("x")
    with pytest.raises(ToolError, match="already exists"):
        ctl.make_control_file("A00", "tiny.txt", "tiny.imap", "x.stree", "a.ctl", 2)
    with pytest.raises(ToolError, match="analysis must be"):
        ctl.make_control_file("B00", "tiny.txt", "tiny.imap", "x.stree", "b.ctl", 2)
    with pytest.raises(ToolError, match="outside the project"):
        ctl.make_control_file("A00", "../tiny.txt", "tiny.imap", "x.stree", "b.ctl", 2)


def test_convert_refuses_overwrite(proj):
    (proj / "out.txt").write_text("")
    with pytest.raises(ToolError, match="overwrite=true"):
        data.convert_data(["tiny.txt"], "tiny.imap", "out")


def test_globs(proj):
    (proj / "loci").mkdir()
    for n in ("b.fa", "a.fa"):
        (proj / "loci" / n).write_text(">x\nA\n")
    assert data._files(["loci/*.fa"]) == ["loci/a.fa", "loci/b.fa"]
    with pytest.raises(ToolError, match="no files"):
        data._files(["loci/*.nex"])
    with pytest.raises(ToolError, match="stay inside"):
        data._files(["../*"])
    with pytest.raises(ToolError, match="does not exist"):
        data._files(["nope.fa"])


def test_tree_diagram_parsing():
    text = "bpp-tree: valid\n\nTree:\n  + A_B\n  |-- A\n  `-- B\n\nBPP species&tree block:\n  x\n"
    assert tree._diagram(text) == "  + A_B\n  |-- A\n  `-- B"
    assert tree._diagram("no tree here") is None


def test_smoke_success_uses_short_chain(proj, tmp_path, monkeypatch):
    # The fake bpp prints the control file it was given, then succeeds.
    fake(tmp_path, monkeypatch, "bpp", 'cat "$2"; echo "Ran from $(pwd)"\n')
    out = run.smoke_test("ok.ctl", nsample=7, burnin=3)
    assert out["ok"] is True and out["error_line"] is None
    assert "nsample = 7" in out["output_tail"] and "burnin = 3" in out["output_tail"]
    assert f"Ran from {proj}" in out["output_tail"]          # cwd = control file folder
    assert "jobname = .bpp-smoke-" not in out["output_tail"]  # scratch prefix hidden
    assert not list(proj.glob(".bpp-smoke-*"))                # scratch folder removed
    assert (proj / "ok.ctl").read_text() == (TINY / "ok.ctl").read_text()


def test_smoke_failure_reports_bpp_error(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp",
         'echo "Reading file"; echo "Erroneous format of option speciesdelimitation = 1 (line 11)"; exit 1\n')
    out = run.smoke_test("ok.ctl")
    assert out["ok"] is False and out["exit_code"] == 1
    assert out["error_line"] == "Erroneous format of option speciesdelimitation = 1 (line 11)"


def test_smoke_unrecognised_failure(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp", 'echo "something odd"; exit 3\n')
    out = run.smoke_test("ok.ctl")
    assert out["ok"] is False and out["error_line"] is None and "note" in out


def test_smoke_success_ignores_error_words(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp", 'echo "Expected sample size reached"; exit 0\n')
    assert run.smoke_test("ok.ctl")["ok"] is True


def test_smoke_timeout_means_accepted(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp", 'echo "MCMC started"; sleep 30\n')
    out = run.smoke_test("ok.ctl", timeout_s=10)
    assert out["ok"] is None and "accepted" in out["note"]
    assert not list(proj.glob(".bpp-smoke-*"))


def test_smoke_rejects_bad_args(proj):
    with pytest.raises(ToolError):
        run.smoke_test("ok.ctl", nsample=0)
    with pytest.raises(ToolError):
        run.smoke_test("../ok.ctl")
