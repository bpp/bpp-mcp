"""Tool behaviour that needs no real BPP binaries (fakes stand in where needed)."""
import json
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


LINT_VALID = """echo '{"status": "valid", "counts": {"errors": 0}, "diagnostics": []}'\n"""


@pytest.fixture
def lint_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(ctl, "keywords", lambda: ["seed", "nsample", "threads", "species&tree",
                                                  "Imapfile"])
    return fake(tmp_path, monkeypatch, "bpp-lint", LINT_VALID)


def test_set_keyword_edits_and_relints(proj, lint_ok):
    (proj / "ok.ctl").write_text((TINY / "ok.ctl").read_text()
                                 .replace("nsample = 20", "nsample = 20   * short"))
    out = ctl.set_keyword("ok.ctl", "NSAMPLE", " 5000 ")
    assert out["server"]["status"] == "valid"
    assert out["server"]["changed"] == {"keyword": "nsample", "old": "20", "new": "5000"}
    assert (proj / "ok.ctl").read_text() == (TINY / "ok.ctl").read_text().replace(
        "nsample = 20", "nsample = 5000   * short")           # only that value changed

    out = ctl.set_keyword("ok.ctl", "threads", "2 1 1")       # not in the file yet
    assert out["server"]["changed"]["old"] is None
    assert (proj / "ok.ctl").read_text().endswith("nsample = 5000   * short\nthreads = 2 1 1\n")


def test_set_keyword_refuses(proj, lint_ok):
    before = (proj / "ok.ctl").read_text()
    with pytest.raises(ToolError, match="not a BPP control-file keyword"):
        ctl.set_keyword("ok.ctl", "nsamples", "5")
    with pytest.raises(ToolError, match="spans 3 lines"):
        ctl.set_keyword("ok.ctl", "species&tree", "2 A B")
    with pytest.raises(ToolError, match="multi-line"):
        ctl.set_keyword("ok.ctl", "seed", "1\nnloci = 9")
    with pytest.raises(ToolError, match="empty"):
        ctl.set_keyword("ok.ctl", "seed", "  ")
    with pytest.raises(ToolError, match="outside the project"):
        ctl.set_keyword("../ok.ctl", "seed", "2")
    assert (proj / "ok.ctl").read_text() == before


def test_run_command_does_not_run_bpp(proj, tmp_path, monkeypatch):
    bpp = fake(tmp_path, monkeypatch, "bpp", f'touch "{proj}/ran"\n')
    (proj / "runs dir").mkdir()
    (proj / "runs dir" / "a00.ctl").write_text("jobname = a00\nthreads = 4 1 1  * four\n")
    out = run.run_command("runs dir/a00.ctl")
    assert out["control_file"] == "runs dir/a00.ctl"
    assert out["directory"] == str(proj / "runs dir")
    assert out["command"] == f"{bpp} --cfile a00.ctl"
    assert out["shell"] == f"cd '{proj}/runs dir' && {bpp} --cfile a00.ctl"
    assert out["jobname"] == "a00" and out["threads"] == "4 1 1"
    assert not (proj / "ran").exists()

    assert run.run_command("ok.ctl")["threads"] is None
    with pytest.raises(ToolError, match="does not exist"):
        run.run_command("nope.ctl")


# Prints its arguments as a JSON list; `exit 0`.
ECHO_ARGS = r'''printf '{"args": ['; sep=""; for a in "$@"; do printf '%s"%s"' "$sep" "$a"; sep=", "; done; printf ']}\n'
'''


def test_read_species_tree_args(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp-tree", ECHO_ARGS)
    (proj / "t.nwk").write_text("((A,B),C);\n")
    out = tree.read_species_tree("t.nwk", imap="tiny.imap", out_prefix="trees/sp")
    assert out["report"]["args"] == ["--json", "--read", "t.nwk", "--imap", "tiny.imap",
                                     "--out", "trees/sp"]
    assert out["server"]["stree_file"] == "trees/sp.stree" and (proj / "trees").is_dir()
    out = tree.read_species_tree("t.nwk")
    assert out["report"]["args"] == ["--json", "--read", "t.nwk"] and "server" not in out
    with pytest.raises(ToolError, match="does not exist"):
        tree.read_species_tree("nope.nwk")
    with pytest.raises(ToolError, match="outside the project"):
        tree.read_species_tree("../t.nwk")


def test_make_loci_bed_args(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp-seqs", ECHO_ARGS)
    (proj / "ref.fa").write_text(">chr1\nACGT\n")
    out = data.make_loci_bed("ref.fa", 500, "beds/loci.bed", min_spacing=10000, n_loci=50, seed=3,
                             exclude_chrom=["chrX", "chrM"], autosomes_only=True)
    assert out["report"]["args"] == [
        "windows", "ref.fa", "--window-size", "500", "--out", "beds/loci.bed", "--json",
        "--min-spacing", "10000", "--n-loci", "50", "--seed", "3",
        "--exclude-chrom", "chrX,chrM", "--autosomes-only"]
    assert out["server"]["bed_file"] == "beds/loci.bed"
    (proj / "old.bed").write_text("")
    with pytest.raises(ToolError, match="overwrite=true"):
        data.make_loci_bed("ref.fa", 500, "old.bed")
    with pytest.raises(ToolError, match="file name"):
        data.make_loci_bed("ref.fa", 500, "beds")
    with pytest.raises(ToolError, match="outside the project"):
        data.make_loci_bed("ref.fa", 500, "../loci.bed")


def test_subset_loci_args(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp-seqs", ECHO_ARGS)
    out = data.subset_loci("tiny.txt", "small/t", first=1, range="3-4", loci=["L7", "L9"],
                           invert=True, imap="tiny.imap")
    assert out["report"]["args"] == ["extract", "tiny.txt", "--out", "small/t", "--json",
                                     "--first", "1", "--range", "3-4", "--loci", "L7,L9",
                                     "--invert", "--imap", "tiny.imap"]
    with pytest.raises(ToolError, match="at least one selection"):
        data.subset_loci("tiny.txt", "small/u")
    (proj / "have.txt").write_text("")
    with pytest.raises(ToolError, match="overwrite=true"):
        data.subset_loci("tiny.txt", "have", first=1)


def test_subset_loci_reports_nloci(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp-seqs", """echo '{"n_loci_input": 2, "n_loci_kept": 1}'\n""")
    assert data.subset_loci("tiny.txt", "one", first=1)["server"]["nloci"] == 1


# --diff prints a diff and exits 1 while the file still says 'outfile'; --fix
# rewrites it and leaves FILE.bak; --json lints.
FAKE_LINT = r'''
for f in "$@"; do file="$f"; done
case " $* " in
  *" --diff "*) if grep -q outfile "$file"; then printf -- '--- %s\n+++ %s\n-outfile = o\n+jobname = o\n' "$file" "$file"; exit 1; fi ;;
  *" --fix "*) cp "$file" "$file.bak"; sed 's/outfile/jobname/' "$file.bak" > "$file"; exit 1 ;;
  *) echo '{"status": "valid", "counts": {"errors": 0}, "diagnostics": []}' ;;
esac
'''


def test_upgrade_shows_diff_then_applies(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp-lint", FAKE_LINT)
    old = (TINY / "ok.ctl").read_text().replace("jobname = out", "outfile = o")
    (proj / "old.ctl").write_text(old)

    out = ctl.upgrade_control_file("old.ctl")
    up = out["server"]["upgrade"]
    assert up["fixes_available"] and not up["applied"] and "+jobname = o" in up["diff"]
    assert (proj / "old.ctl").read_text() == old and not (proj / "old.ctl.bak").exists()

    out = ctl.upgrade_control_file("old.ctl", apply=True)
    up = out["server"]["upgrade"]
    assert up["applied"] and up["backup"] == "old.ctl.bak" and out["server"]["status"] == "valid"
    assert (proj / "old.ctl.bak").read_text() == old
    assert "jobname = o" in (proj / "old.ctl").read_text()

    out = ctl.upgrade_control_file("old.ctl", apply=True)     # nothing left to fix
    assert out["server"]["upgrade"] == {"fixes_available": False, "diff": "", "applied": False}


def test_upgrade_keeps_an_existing_backup(proj, tmp_path, monkeypatch):
    fake(tmp_path, monkeypatch, "bpp-lint", FAKE_LINT)
    (proj / "old.ctl").write_text("outfile = o\n")
    (proj / "old.ctl.bak").write_text("precious")
    with pytest.raises(ToolError, match="already exists"):
        ctl.upgrade_control_file("old.ctl", apply=True)
    assert (proj / "old.ctl.bak").read_text() == "precious"
    assert (proj / "old.ctl").read_text() == "outfile = o\n"


def test_example_resources(tmp_path, monkeypatch):
    from mcp.server.mcpserver.exceptions import ResourceNotFoundError

    from bpp_mcp import prompts, resources
    monkeypatch.setenv("BPP_MCP_HOME", str(tmp_path))
    assert json.loads(resources.examples())["examples"] == []
    for rel in ("bpp-lint-0.3.5/examples/legacy.bpp.ctl", "bpp-4.8.7/examples/frogs/A00.bpp.ctl",
                "bpp-4.8.7/examples/frogs/frogs.txt"):
        f = tmp_path / "tools" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"* {rel}\n")
    listed = json.loads(resources.examples())["examples"]
    assert [(e["name"], e["from"]) for e in listed] == [
        ("frogs-A00.bpp.ctl", "bpp-4.8.7"), ("legacy.bpp.ctl", "bpp-lint-0.3.5")]
    assert resources.example("frogs-A00.bpp.ctl") == "* bpp-4.8.7/examples/frogs/A00.bpp.ctl\n"
    for bad in ("frogs-frogs.txt", "../../etc/passwd", "nope"):
        with pytest.raises(ResourceNotFoundError):
            resources.example(bad)
    assert "`my old.ctl`" in prompts.upgrade_old_file("my old.ctl")
    assert "My data: ten FASTA loci" in prompts.novice_setup("ten FASTA loci")
