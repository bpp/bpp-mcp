import shutil
from pathlib import Path

import pytest

from bpp_mcp import ctlfile, runner, sandbox, workarounds

TINY = Path(__file__).parent / "fixtures" / "tiny"


@pytest.fixture
def lint_version(monkeypatch):
    versions = {"bpp-lint": "0.3.5"}
    monkeypatch.setattr(runner, "tool_version", lambda name: versions.get(name))
    return versions


@pytest.fixture
def proj(tmp_path, monkeypatch):
    for f in TINY.iterdir():
        shutil.copy(f, tmp_path)
    monkeypatch.setattr(sandbox, "current", sandbox.Sandbox(tmp_path))
    return tmp_path


def variant(proj, name, **changes):
    text = (proj / "ok.ctl").read_text()
    for k, v in changes.items():
        text = ctlfile.set_value(text, k.replace("_", "&"), v)
    (proj / name).write_text(text)
    return proj / name, text


def test_version_gate(lint_version):
    assert workarounds.SD_BARE.active()
    lint_version["bpp-lint"] = "0.3.6"
    assert not workarounds.SD_BARE.active()
    lint_version["bpp-lint"] = None   # unreadable version: keep patching
    assert workarounds.SD_BARE.active()


def test_fix_speciesdelimitation(lint_version):
    text = "  speciesdelimitation = 1\nspeciestree = 0\n"
    assert workarounds.fix_speciesdelimitation(text) == (
        "  speciesdelimitation = 1 0 2\nspeciestree = 0\n", True)
    for ok in ["speciesdelimitation = 0\n", "speciesdelimitation = 1 1 2 1\n",
               "speciesdelimitation = 1 0 5\n"]:
        assert workarounds.fix_speciesdelimitation(ok) == (ok, False)
    lint_version["bpp-lint"] = "0.4.0"
    assert workarounds.fix_speciesdelimitation(text) == (text, False)


def test_ok_ctl_is_clean(proj):
    path = proj / "ok.ctl"
    assert workarounds.data_checks(path, path.read_text()) == []


@pytest.mark.parametrize("name,change,check,severity,needle", [
    ("nofile.ctl", {"seqfile": "missing.txt"}, "file_exists", "error", "missing.txt"),
    ("nloci.ctl", {"nloci": "3"}, "nloci", "error", "Expected 3 loci but found only 2"),
    ("fewer.ctl", {"nloci": "1"}, "nloci", "info", "first 1"),
    ("phase_ones.ctl", {"phase": "1 1"}, "phase", "error", "2 digits but there are 3 species"),
    ("escape.ctl", {"Imapfile": "../../etc/passwd"}, "file_exists", "error", "outside"),
])
def test_defects(proj, name, change, check, severity, needle):
    path, text = variant(proj, name, **change)
    issues = workarounds.data_checks(path, text)
    assert [(i["check"], i["severity"]) for i in issues] == [(check, severity)]
    assert needle in issues[0]["message"]


def test_phase_zeros_is_fine(proj):
    path, text = variant(proj, "phase_zeros.ctl", phase="0 0")
    assert workarounds.data_checks(path, text) == []


def test_imap_extra_species(proj):
    (proj / "extra.imap").write_text((proj / "tiny.imap").read_text().replace("c2 C", "c2 D"))
    path, text = variant(proj, "x.ctl", Imapfile="extra.imap")
    issues = workarounds.data_checks(path, text)
    assert [i["check"] for i in issues] == ["species_match"]
    assert "D" in issues[0]["message"]


def test_tree_species_not_in_imap(proj):
    text = (proj / "ok.ctl").read_text().replace("A  B  C", "A  B  Cx").replace("((A,B),C)", "((A,B),Cx)")
    (proj / "t.ctl").write_text(text)
    msgs = [i["message"] for i in workarounds.data_checks(proj / "t.ctl", text)]
    assert any("not in species&tree: C" in m for m in msgs)
    assert any("no individuals in the Imap: Cx" in m for m in msgs)


def test_paths_relative_to_ctl_folder(proj):
    (proj / "sub").mkdir()
    text = (proj / "ok.ctl").read_text()
    text = ctlfile.set_value(ctlfile.set_value(text, "seqfile", "../tiny.txt"), "Imapfile", "../tiny.imap")
    (proj / "sub" / "rel.ctl").write_text(text)
    assert workarounds.data_checks(proj / "sub" / "rel.ctl", text) == []


def test_usedata_0_skips_seqfile(proj):
    path, text = variant(proj, "nodata.ctl", usedata="0", seqfile="missing.txt")
    assert workarounds.data_checks(path, text) == []


@pytest.mark.parametrize("value,needle", [
    ("1", "algorithm number"),
    ("1 0", "exactly 1 number after it, found 0"),
    ("1 1 2", "exactly 2 numbers after it, found 1"),
    ("1 2 2", "algorithm number"),
    ("0 1", "nothing may follow 0"),
])
def test_speciesdelimitation_arity(proj, value, needle):
    path, text = variant(proj, "sd.ctl", speciesdelimitation=value)
    issues = workarounds.data_checks(path, text)
    assert [(i["check"], i["severity"]) for i in issues] == [("speciesdelimitation", "error")]
    assert needle in issues[0]["message"]


@pytest.mark.parametrize("value", ["0", "1 0 2", "1 1 2 1", "1 0 5   * eps"])
def test_speciesdelimitation_ok(proj, value):
    path, text = variant(proj, "sd.ctl", speciesdelimitation=value)
    assert workarounds.data_checks(path, text) == []


def test_imap_missing_tag(proj):
    (proj / "short.imap").write_text((proj / "tiny.imap").read_text().replace("a1 A\n", ""))
    path, text = variant(proj, "x.ctl", Imapfile="short.imap")
    issues = workarounds.data_checks(path, text)
    assert [(i["check"], i["severity"]) for i in issues] == [("imap_tags", "error")]
    assert "1 sequence tag(s)" in issues[0]["message"] and ": a1 (" in issues[0]["message"]


def test_imap_tags_only_in_loci_bpp_reads(proj):
    seq = (proj / "tiny.txt").read_text()
    first, second = seq.split("\n\n", 1)
    (proj / "odd.txt").write_text(first + "\n\n" + second.replace("^c2", "^zz"))
    path, text = variant(proj, "two.ctl", seqfile="odd.txt")
    assert [i["check"] for i in workarounds.data_checks(path, text)] == ["imap_tags"]
    path, text = variant(proj, "one.ctl", seqfile="odd.txt", nloci="1")   # locus 2 is not read
    assert [i["check"] for i in workarounds.data_checks(path, text)] == ["nloci"]
