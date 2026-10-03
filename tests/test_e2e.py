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
_missing = [t for t in TOOLS if _runner.find(t) is None]
needs_tools = pytest.mark.skipif(
    bool(_missing), reason=f"BPP tools not installed: {', '.join(_missing)} "
                           "(run `bpp-mcp install-tools`)")

ANAS_JOINS = ("fraterculus+obliqua, distincta+fraterculus_obliqua, "
              "suspensa+distincta_fraterculus_obliqua, "
              "turpiniae+distincta_fraterculus_obliqua_suspensa")
LONG_SEQ = re.compile(r"[ACGTN\-?]{31,}", re.I)


class Host:
    """Calls tools over a live stdio session and records every result text."""

    def __init__(self, session):
        self.s, self.texts = session, []

    async def call(self, name, args, *, ok=True):
        res = await self.s.call_tool(name, args)
        text = res.content[0].text if res.content else ""
        self.texts.append(text)
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
        doc = await h.call("lookup_docs", {"keyword": "speciesdelimitation"})
        assert doc["report"]["found"] and "speciesdelimitation" in doc["report"]["syntax"]
        hits = await h.call("search_docs", {"query": "migration prior"})
        assert isinstance(hits["report"], list) and hits["report"]
        exp = await h.call("explain_diagnostic", {"code": "BPP101"})
        assert "required" in exp["text"].lower()
        await h.call("lint_control_file", {"ctl": "../outside.ctl"}, ok=False)

    host = drive(anas, body)
    assert "speciesdelimitation = 1 0 2" in results["A10"]["text"]
    assert any(w["id"] == "speciesdelimitation-bare"
               for w in results["A11"]["server"].get("workarounds_applied", []))
    assert "workarounds_applied" not in results["A00"]["server"]
    assert not list(anas.rglob(".bpp-smoke-*"))
    assert_private(host, FIXTURES / "anastrepha")


@needs_tools
def test_tiny_defects_caught(tmp_path, clean_env):
    proj = tmp_path / "tiny"
    shutil.copytree(FIXTURES / "tiny", proj)
    base = (proj / "ok.ctl").read_text()
    (proj / "nloci.ctl").write_text(base.replace("nloci = 2", "nloci = 3"))
    (proj / "sd_bare.ctl").write_text(base.replace("speciesdelimitation = 0",
                                                   "speciesdelimitation = 1\nspeciesmodelprior = 1"))

    async def body(h):
        ok = await h.call("lint_control_file", {"ctl": "ok.ctl"})
        assert ok["server"]["status"] == "valid"
        assert (await h.call("smoke_test", {"ctl": "ok.ctl"}))["ok"] is True

        bad = await h.call("lint_control_file", {"ctl": "nloci.ctl"})
        assert bad["report"]["status"] == "valid"            # bpp-lint 0.3.5 misses it...
        assert bad["server"]["status"] == "invalid"          # ...the data checks do not
        assert [i["check"] for i in bad["server"]["data_checks"]["issues"]] == ["nloci"]
        smoke = await h.call("smoke_test", {"ctl": "nloci.ctl"})
        assert smoke["ok"] is False and "Expected 3 loci" in smoke["error_line"]

        smoke = await h.call("smoke_test", {"ctl": "sd_bare.ctl"})
        assert smoke["ok"] is False and smoke["error_line"].startswith("Erroneous format")

    host = drive(proj, body)
    assert_private(host, FIXTURES / "tiny")
