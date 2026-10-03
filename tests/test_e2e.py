"""Drive the server over stdio, as a host would."""
import json
import os
import sys

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _session_call(env, calls):
    params = StdioServerParameters(command=sys.executable, args=["-m", "bpp_mcp.server"],
                                   env={**os.environ, **env})
    results = {}
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            results["instructions"] = init.instructions
            results["tools"] = sorted(t.name for t in (await s.list_tools()).tools)
            for key, name, args in calls:
                res = await s.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                try:
                    body = json.loads(text)
                except json.JSONDecodeError:
                    body = text
                results[key] = (res.is_error, body)
    return results


def run(env, calls=()):
    return anyio.run(_session_call, env, list(calls))


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("BPP_MCP_PROJECTS_DIR", raising=False)
    monkeypatch.delenv("BPP_MCP_ROOT", raising=False)


def test_check_environment_over_stdio(tmp_path, clean_env):
    out = run({"BPP_MCP_ROOT": str(tmp_path)},
              [("env", "check_environment", {})])
    assert "check_environment" in out["tools"] and "set_project" not in out["tools"]
    assert "Never write or edit a control file by hand" in out["instructions"]
    is_error, body = out["env"]
    assert not is_error
    assert body["project_root"] == str(tmp_path.resolve())
    assert set(body["tools"]) == {"bpp-seqs", "bpp-tree", "bpp-lint", "bpp-docs", "bpp"}
    assert isinstance(body["ready"], bool)


def test_set_project_over_stdio(tmp_path, clean_env):
    (tmp_path / "p1").mkdir()
    out = run({"BPP_MCP_PROJECTS_DIR": str(tmp_path)}, [
        ("before", "check_environment", {}),
        ("escape", "set_project", {"path": "../.."}),
        ("ok", "set_project", {"path": "p1"}),
        ("after", "check_environment", {}),
    ])
    assert "set_project" in out["tools"]
    assert out["before"][1]["project_root"] is None
    is_error, msg = out["escape"]
    assert is_error and "outside the projects directory" in msg  # the reason reaches the model
    assert out["ok"] == (False, {"project_root": str((tmp_path / "p1").resolve()), "files": []})
    assert out["after"][1]["project_root"] == str((tmp_path / "p1").resolve())


# ---------------------------------------------------------------- core path
import re
import shutil
from pathlib import Path

from bpp_mcp import install as _install
from bpp_mcp import runner as _runner

# Evaluated at import, before conftest points BPP_MCP_HOME at an empty folder,
# so these tests use the tools `bpp-mcp install-tools` really installed.
REAL_HOME = str(_install.home())
FIXTURES = Path(__file__).parent / "fixtures"
TOOLS = ["bpp-seqs", "bpp-tree", "bpp-lint", "bpp-docs", "bpp"]


def needs(*tools):
    """Skip a test, with the reason, unless these tools are installed."""
    missing = [t for t in tools if _runner.find(t) is None]
    return pytest.mark.skipif(
        bool(missing), reason=f"BPP tools not installed: {', '.join(missing)} "
                              "(run `bpp-mcp install-tools`)")


needs_tools = needs(*TOOLS)

ANAS_JOINS = ("fraterculus+obliqua, distincta+fraterculus_obliqua, "
              "suspensa+distincta_fraterculus_obliqua, "
              "turpiniae+distincta_fraterculus_obliqua_suspensa")
LONG_SEQ = re.compile(r"[ACGTN\-?]{31,}", re.I)


class Host:
    """Calls tools over a live stdio session and records every result text."""

    def __init__(self, session):
        self.s, self.texts, self.called = session, [], set()

    async def call(self, name, args, *, ok=True):
        res = await self.s.call_tool(name, args)
        text = res.content[0].text if res.content else ""
        self.texts.append(text)
        self.called.add(name)
        assert res.is_error is (not ok), f"{name}: {text[:2000]}"
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text


async def _with_host(env, body):
    params = StdioServerParameters(command=sys.executable, args=["-m", "bpp_mcp.server"],
                                   env={**os.environ, **env})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            host = Host(s)
            await body(host)
            return host


def drive(root, body):
    return anyio.run(_with_host, {"BPP_MCP_ROOT": str(root), "BPP_MCP_HOME": REAL_HOME}, body)


def assert_private(host, fixture_dir):
    """No tool output may contain a run of sequence data from the fixtures."""
    seqs = set()
    for f in fixture_dir.rglob("*"):
        if f.is_file():
            seqs.update(m.group().upper() for m in LONG_SEQ.finditer(f.read_text(errors="replace")))
    for text in host.texts:
        for m in LONG_SEQ.finditer(text):
            assert m.group().upper() not in seqs, f"sequence data leaked: {m.group()[:40]}..."


@pytest.fixture
def anas(tmp_path, clean_env):
    proj = tmp_path / "anastrepha project"      # a space, as real folders have
    shutil.copytree(FIXTURES / "anastrepha", proj)
    return proj


@needs_tools
def test_anastrepha_core_path(anas):
    results = {}

    async def body(h):
        env_ = await h.call("check_environment", {})
        assert env_["ready"], env_["problems"]
        insp = await h.call("inspect_data", {"files": ["loci/*.fasta"], "imap": "imap.txt"})
        assert insp["report"]["ready_to_run"] and not insp["report"]["missing"]
        conv = await h.call("convert_data", {"files": ["loci/*.fasta"], "imap": "imap.txt",
                                             "out_prefix": "data/anas"})
        assert conv["server"]["nloci"] == 10
        tr = await h.call("build_species_tree", {"joins": ANAS_JOINS, "imap": "data/anas.imap",
                                                 "out_prefix": "data/sp"})
        assert tr["report"]["newick"] == "(turpiniae,(suspensa,(distincta,(fraterculus,obliqua))));"
        assert "fraterculus_obliqua" in tr["server"]["diagram"]
        for analysis in ["A10", "A00", "A11"]:
            ctl_path = f"runs/{analysis.lower()}.ctl"
            made = await h.call("make_control_file", {
                "analysis": analysis, "seqfile": "data/anas.txt", "imapfile": "data/anas.imap",
                "stree_file": tr["server"]["stree_file"], "out": ctl_path,
                "nloci": conv["server"]["nloci"], "jobname": analysis.lower()})
            assert "seqfile = ../data/anas.txt" in made["text"]   # relative to the ctl folder
            lint = await h.call("lint_control_file", {"ctl": ctl_path})
            assert lint["server"]["status"] == "valid", lint
            assert lint["server"]["data_checks"]["issues"] == []
            smoke = await h.call("smoke_test", {"ctl": ctl_path})
            assert smoke["ok"] is True, smoke
            results[analysis] = made
        edit = await h.call("set_keyword", {"ctl": "runs/a00.ctl", "keyword": "nsample",
                                            "value": "20000"})
        assert edit["server"]["status"] == "valid", edit
        assert edit["server"]["changed"]["new"] == "20000"
        assert edit["server"]["changed"]["old"] not in (None, "20000")
        err = await h.call("set_keyword", {"ctl": "runs/a00.ctl", "keyword": "nsamples",
                                           "value": "1"}, ok=False)
        assert "not a BPP control-file keyword" in err
        err = await h.call("set_keyword", {"ctl": "runs/a00.ctl", "keyword": "species&tree",
                                           "value": "1 A"}, ok=False)
        assert "make_control_file" in err
        bad = await h.call("set_keyword", {"ctl": "runs/a00.ctl", "keyword": "nsample",
                                           "value": "many"})
        assert bad["server"]["status"] == "invalid"            # the re-lint catches a bad value
        await h.call("set_keyword", {"ctl": "runs/a00.ctl", "keyword": "nsample", "value": "20000"})
        sub = await h.call("subset_loci", {"seqfile": "data/anas.txt", "out_prefix": "data/small",
                                           "first": 3})
        assert sub["server"]["nloci"] == 3 and (anas / "data" / "small.txt").is_file()
        (anas / "old.nwk").write_text(tr["report"]["newick"] + "\n")
        rd = await h.call("read_species_tree", {"path": "old.nwk", "imap": "data/anas.imap",
                                                "out_prefix": "data/read"})
        assert rd["report"]["newick"] == tr["report"]["newick"]
        assert rd["report"]["individual_counts_filled"]
        assert rd["server"]["diagram"] == tr["server"]["diagram"]
        assert (anas / rd["server"]["stree_file"]).read_text() == \
            (anas / tr["server"]["stree_file"]).read_text()
        up = await h.call("upgrade_control_file", {"ctl": "runs/a00.ctl"})
        assert up["server"]["upgrade"] == {"fixes_available": False, "diff": "", "applied": False}
        bed = await h.call("make_loci_bed", {"input": "loci/sco_9239at7203.fasta",
                                             "window_size": 200, "out": "data/loci.bed"})
        assert bed["report"]["n_windows_emitted"] > 0 and (anas / "data" / "loci.bed").is_file()
        how = await h.call("run_command", {"ctl": "runs/a00.ctl"})
        assert how["directory"] == str((anas / "runs").resolve())
        assert how["command"].endswith("bpp --cfile a00.ctl") and how["jobname"] == "a00"
        assert how["shell"].startswith("cd '") and not list((anas / "runs").glob("a00.*txt"))
        results["edited"] = (anas / "runs" / "a00.ctl").read_text()
        doc = await h.call("lookup_docs", {"keyword": "speciesdelimitation"})
        assert doc["report"]["found"] and "speciesdelimitation" in doc["report"]["syntax"]
        hits = await h.call("search_docs", {"query": "migration prior"})
        assert isinstance(hits["report"], list) and hits["report"]
        exp = await h.call("explain_diagnostic", {"code": "BPP101"})
        assert "required" in exp["text"].lower()
        await h.call("lint_control_file", {"ctl": "../outside.ctl"}, ok=False)

        results["tools"] = {t.name for t in (await h.s.list_tools()).tools}

    host = drive(anas, body)
    assert host.called == results["tools"]          # so the privacy check covers every tool
    assert "speciesdelimitation = 1 0 2" in results["A10"]["text"]
    assert any(w["id"] == "speciesdelimitation-bare"
               for w in results["A11"]["server"].get("workarounds_applied", []))
    assert "workarounds_applied" not in results["A00"]["server"]
    assert not list(anas.rglob(".bpp-smoke-*"))
    assert results["edited"] == re.sub(r"(nsample\s*=\s*)\d+", r"\g<1>20000", results["A00"]["text"])
    assert_private(host, FIXTURES / "anastrepha")


def _tiny_variants(proj):
    """The 13 cases of reference/BPP-LINT-FIXES.md: name -> (data check or None, BPP's error)."""
    base = (proj / "ok.ctl").read_text()
    imap = (proj / "tiny.imap").read_text()

    def write(name, text):
        (proj / name).parent.mkdir(exist_ok=True)
        (proj / name).write_text(text)

    def sd(value):
        return base.replace("speciesdelimitation = 0", f"speciesdelimitation = {value}\n"
                                                         "speciesmodelprior = 1")

    (proj / "no_a1.imap").write_text(imap.replace("a1 A\n", ""))
    (proj / "extra_sp.imap").write_text(imap.replace("c2 C", "c2 D"))
    write("sd_bare.ctl", sd("1"))
    write("sd_short.ctl", sd("1 0"))
    write("sd_alg1_short.ctl", sd("1 1 2"))
    write("sd_ok.ctl", sd("1 0 2"))
    write("nofile.ctl", base.replace("seqfile = tiny.txt", "seqfile = missing.txt"))
    write("nloci.ctl", base.replace("nloci = 2", "nloci = 3"))
    write("imap_missing_tag.ctl", base.replace("tiny.imap", "no_a1.imap"))
    write("imap_extra_sp.ctl", base.replace("tiny.imap", "extra_sp.imap"))
    write("tree_sp_noimap.ctl", base.replace("A  B  C", "A  B  Cx").replace("((A,B),C)", "((A,B),Cx)"))
    write("phase_ones.ctl", base + "phase = 1 1\n")
    write("phase_zeros.ctl", base + "phase = 0 0\n")
    write("counts.ctl", base.replace("2  2  2", "2  2  9"))
    write("sub/rel.ctl", base.replace("tiny.txt", "../tiny.txt").replace("tiny.imap", "../tiny.imap"))
    return {
        "sd_bare.ctl": ("speciesdelimitation", "Erroneous format"),
        "sd_short.ctl": ("speciesdelimitation", "Erroneous format"),
        "sd_alg1_short.ctl": ("speciesdelimitation", "Erroneous format"),
        "sd_ok.ctl": None,
        "nofile.ctl": ("file_exists", "Unable to open file (missing.txt)"),
        "nloci.ctl": ("nloci", "Expected 3 loci but found only 2"),
        "imap_missing_tag.ctl": ("imap_tags", "Cannot find a mapping to species for tag a1"),
        "imap_extra_sp.ctl": ("species_match", "Cannot find node with population label D"),
        "tree_sp_noimap.ctl": ("species_match", "Cannot find node with population label C"),
        "phase_ones.ctl": ("phase", "Number of digits in 'phase'"),
        "phase_zeros.ctl": None,
        "counts.ctl": None,
        # Case 13 fails when BPP is started from the folder above. This server
        # always runs it from the control file's folder, where the paths hold.
        "sub/rel.ctl": None,
    }


@needs("bpp-lint", "bpp")
def test_tiny_defects_caught(tmp_path, clean_env):
    proj = tmp_path / "tiny"
    shutil.copytree(FIXTURES / "tiny", proj)
    cases = _tiny_variants(proj)
    assert len(cases) == 13

    async def body(h):
        ok = await h.call("lint_control_file", {"ctl": "ok.ctl"})
        assert ok["server"]["status"] == "valid"
        assert (await h.call("smoke_test", {"ctl": "ok.ctl"}))["ok"] is True

        for name, expect in cases.items():
            lint = await h.call("lint_control_file", {"ctl": name})
            smoke = await h.call("smoke_test", {"ctl": name})
            errors = [i["check"] for i in lint["server"]["data_checks"]["issues"]
                      if i["severity"] == "error"]
            if expect is None:
                assert lint["server"]["status"] == "valid" and not errors, (name, lint)
                assert smoke["ok"] is True, (name, smoke)
                continue
            check, bpp_error = expect
            caught = lint["report"]["counts"]["errors"] > 0 or check in errors
            assert lint["server"]["status"] == "invalid" and caught, (name, lint)
            assert smoke["ok"] is False and bpp_error in smoke["error_line"], (name, smoke)

    host = drive(proj, body)
    assert_private(host, FIXTURES / "tiny")


def _lint_example(name):
    hits = sorted(Path(REAL_HOME).glob(f"tools/bpp-lint-*/examples/{name}"))
    return hits[-1] if hits else None


@needs("bpp-lint", "bpp-docs")
def test_upgrade_path(tmp_path, clean_env):
    legacy = _lint_example("legacy-3x.bpp.ctl")
    if legacy is None:
        pytest.skip("bpp-lint's examples are not installed (run `bpp-mcp install-tools`)")
    out = {}

    async def body(h):
        listing = json.loads((await h.s.read_resource("bpp://examples")).contents[0].text)
        assert "legacy-3x.bpp.ctl" in [e["name"] for e in listing["examples"]]
        res = await h.s.read_resource("bpp://examples/legacy-3x.bpp.ctl")
        assert res.contents[0].text == legacy.read_text()
        (tmp_path / "old.ctl").write_text(res.contents[0].text)

        show = await h.call("upgrade_control_file", {"ctl": "old.ctl"})
        up = show["server"]["upgrade"]
        assert up["fixes_available"] and not up["applied"]
        assert "-      diploid = 0 0 0 0" in up["diff"] and "+      phase = 0 0 0 0" in up["diff"]
        assert show["server"]["status"] == "invalid"
        assert (tmp_path / "old.ctl").read_text() == legacy.read_text()   # nothing written yet
        assert not (tmp_path / "old.ctl.bak").exists()

        done = await h.call("upgrade_control_file", {"ctl": "old.ctl", "apply": True})
        assert done["server"]["upgrade"]["applied"]
        assert done["server"]["upgrade"]["backup"] == "old.ctl.bak"
        assert (tmp_path / "old.ctl.bak").read_text() == legacy.read_text()
        assert "phase = 0 0 0 0" in (tmp_path / "old.ctl").read_text()
        assert done["report"]["counts"]["errors"] < show["report"]["counts"]["errors"]
        # What is left needs the user: the model reads it in the lint report.
        assert done["server"]["status"] == "invalid" and done["report"]["diagnostics"]

        again = await h.call("upgrade_control_file", {"ctl": "old.ctl", "apply": True})
        assert again["server"]["upgrade"] == {"fixes_available": False, "diff": "", "applied": False}
        assert (tmp_path / "old.ctl.bak").read_text() == legacy.read_text()   # backup untouched

        man = await h.s.read_resource("bpp://manual/thetaprior")
        assert "thetaprior" in man.contents[0].text
        templates = (await h.s.list_resource_templates()).resource_templates
        out["templates"] = sorted(t.uri_template for t in templates)
        out["prompts"] = sorted(p.name for p in (await h.s.list_prompts()).prompts)
        got = await h.s.get_prompt("upgrade_old_file", {"ctl": "old.ctl"})
        assert "upgrade_control_file on `old.ctl`" in got.messages[0].content.text

    drive(tmp_path, body)
    assert out["templates"] == ["bpp://examples/{name}", "bpp://manual/{keyword}"]
    assert out["prompts"] == ["check_my_ctl", "novice_setup", "upgrade_old_file"]
