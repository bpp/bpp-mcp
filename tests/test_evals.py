"""The evaluation harness, with no model: grading helpers, and every scenario's
reference solution replayed against the real server."""
import sys
from pathlib import Path

import anyio
import pytest

pytest.importorskip("yaml", reason="evaluation extras not installed (pip install -e '.[evals]')")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "evals"))

import harness  # noqa: E402
import reference  # noqa: E402
from bpp_mcp import install as _install  # noqa: E402
from bpp_mcp import runner as _runner  # noqa: E402

REAL_HOME = str(_install.home())       # before conftest points BPP_MCP_HOME elsewhere
TASKS = sorted((Path(harness.__file__).parent / "tasks").glob("*.yaml"))
_missing = [t for t in ("bpp-seqs", "bpp-tree", "bpp-lint", "bpp-docs", "bpp") if _runner.find(t) is None]
needs_tools = pytest.mark.skipif(bool(_missing), reason=f"BPP tools not installed: {', '.join(_missing)}")


def tool(name, args, result="{}", is_error=False, said=""):
    return {"role": "tool", "name": name, "args": args, "result": result, "is_error": is_error,
            "said": said}


def test_every_scenario_loads_and_has_a_reference_solution():
    ids = [harness.load_scenario(p)["id"] for p in TASKS]
    assert len(ids) >= 10 and sorted(ids) == sorted(reference.SOLUTIONS)


def test_canonical_newick():
    c = harness.canonical_newick
    assert c("(((K, C), L), H);") == c("(H,(L,(C,K)))") == "(((C,K),L),H)"
    assert c("((A:0.1,B:0.2)AB:0.3,C);") == "((A,B),C)"
    assert c("((A,B),C);") != c("((A,C),B);")
    assert c("((A,B),C") is None and c("") is None


def test_tree_line():
    text = "species&tree = 3  A  B  C\n   2  2  2\n  ((A,B),C);\nnloci = 2\n"
    assert harness.tree_line(text) == "((A,B),C);"
    assert harness.tree_line("nloci = 2\n") is None


def test_match():
    m = harness._match
    assert m(10, "10") and m("invgamma 3 0.01", "invgamma  3 0.01") and not m(10, "3")
    assert m("absent", None) and not m("absent", "1") and m("present", "x") and not m("present", None)
    assert m({"regex": "1( +1){4}"}, "1 1 1 1 1") and not m({"regex": "1( +1){4}"}, "1 1 1")
    assert m({"absent_or": {"regex": "0( +0)*"}}, None) and m({"absent_or": {"regex": "0( +0)*"}}, "0 0 0")
    assert not m({"absent_or": {"regex": "0( +0)*"}}, "1 1")
    assert m({"one_of": [1, 2]}, "2") and not m({"regex": "x"}, None)


def test_docs_discipline():
    kws = ["nsample", "wprior", "phase", "thetaprior"]
    ok = [tool("lookup_docs", {"keyword": "wprior"}),
          tool("make_control_file", {"extra": {"wprior": "2 10"}}),
          tool("search_docs", {"query": "unphased"}, result="... the phase keyword ..."),
          tool("set_keyword", {"keyword": "Phase", "value": "1 1"}),
          {"role": "assistant", "text": "I set:\n  phase = 1 1\nas the manual says."}]
    assert harness.docs_discipline(ok, kws) == ([], [])
    bad = [tool("set_keyword", {"keyword": "nsample", "value": "5"}),
           tool("lookup_docs", {"keyword": "nsample"}),               # too late
           {"role": "assistant", "text": "Use `thetaprior = invgamma 3 0.002` for this."},
           tool("make_control_file", {"extra": {"wprior": "2 10", "notakeyword": "1"}})]
    assert harness.docs_discipline(bad, kws) == (["nsample", "wprior"], ["thetaprior"])
    typed = [tool("make_control_file", {"phase": "1 1", "thetaprior": None, "nsample": 9})]
    assert harness.docs_discipline(typed, kws) == (["phase"], [])
    # Prose that mentions a keyword without stating a value is not flagged.
    prose = [{"role": "assistant", "text": "nsample controls length; xnsample = 3."}]
    assert harness.docs_discipline(prose, kws) == ([], [])


def test_hand_edits():
    events = [tool("host_write_file", {"path": "notes.md", "content": "hello"}),
              tool("host_write_file", {"path": "a.ctl", "content": "seed = 1"}),
              tool("host_write_file", {"path": "run.txt", "content": "seqfile = x.txt\n"}),
              tool("host_write_file", {"path": "b.ctl", "content": ""}, is_error=True)]
    assert harness.hand_edits(events) == ["a.ctl", "run.txt"]


def test_host_tools_are_confined(tmp_path):
    (tmp_path / "a.txt").write_text("ACGT" * 20 + "\nname\n")
    assert harness.host_tool(tmp_path, "host_list_files", {}).text == "a.txt"
    read = harness.host_tool(tmp_path, "host_read_file", {"path": "a.txt"})
    assert "sequence data redacted" in read.text and "ACGTACGT" not in read.text
    assert harness.host_tool(tmp_path, "host_write_file", {"path": "../x", "content": ""}).is_error
    assert harness.host_tool(tmp_path, "host_read_file", {"path": "/etc/passwd"}).is_error


def test_cost_estimate():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000,
             "cache_creation_input_tokens": 0, "cache_read_input_tokens": 1_000_000}
    assert harness.cost_usd("claude-opus-5-5", usage) == pytest.approx(4 + 2 + 0.2)
    assert harness.cost_usd("some-local-model", usage) is None


def replay(sc, script, root, monkeypatch, limits=None):
    monkeypatch.setenv("BPP_MCP_HOME", REAL_HOME)
    user = harness.ScriptedModel(["Yes, go ahead."] * 3)        # then <<DONE>>
    return anyio.run(harness.run_scenario, sc, harness.ScriptedModel(script), user, root, limits)


@needs_tools
@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.stem)
def test_reference_solution_passes(path, tmp_path, monkeypatch):
    sc = harness.load_scenario(path)
    res = replay(sc, reference.SOLUTIONS[sc["id"]], tmp_path / "my project", monkeypatch)
    if "skipped" in res:
        pytest.skip(res["skipped"])
    score = res["score"]
    assert score["passed"], score
    assert score["hand_edits"] == [] and score["undocumented_keywords"] == []
    assert score["ended"] == "user_done" and score["tool_errors"] == 0
    if not sc["expect"].get("declines"):
        assert score["lint_valid"] and score["smoke_ok"] and score["env_checked_first"]
        assert all(len(e["result"]) < 70000 for e in res["transcript"] if e["role"] == "tool")


@needs_tools
def test_wrong_and_hand_written_solutions_fail(tmp_path, monkeypatch):
    by_id = {p.stem: harness.load_scenario(p) for p in TASKS}

    # The right tools, the wrong analysis: A00 where the user wanted A10.
    res = replay(by_id["anas_delimitation"], reference.SOLUTIONS["anas_parameters"],
                 tmp_path / "wrong", monkeypatch)
    s = res["score"]
    assert s["lint_valid"] and s["smoke_ok"] and not s["passed"]
    assert not s["choices"]["analysis"] and not s["choices"]["keyword:speciesdelimitation"]

    # A control file typed out by hand, even a correct one, does not pass.
    good = (harness.FIXTURES["tiny"] / "ok.ctl").read_text()
    script = [[("host_write_file", {"path": "run.ctl", "content": good})],
              [("set_keyword", {"ctl": "run.ctl", "keyword": "seed", "value": "7"})],
              "Done, run it with bpp --cfile run.ctl"]
    res = replay(by_id["tiny_bpp_format"], script, tmp_path / "byhand", monkeypatch)
    s = res["score"]
    assert s["lint_valid"] and s["smoke_ok"] and all(s["choices"].values())
    assert s["hand_edits"] == ["run.ctl"] and s["undocumented_keywords"] == ["seed"]
    assert not s["passed"] and not s["env_checked_first"]

    # Nothing produced at all.
    res = replay(by_id["anas_parameters"], ["I'm not sure how to do that."], tmp_path / "none",
                 monkeypatch)
    assert res["score"]["control_file"] is None and not res["score"]["passed"]

    # Asked for IQ-TREE, made a BPP control file anyway.
    res = replay(by_id["off_topic"], reference.SOLUTIONS["anas_parameters"], tmp_path / "scope",
                 monkeypatch)
    assert not res["score"]["passed"]


@needs_tools
def test_tool_call_limit_stops_a_runaway(tmp_path, monkeypatch):
    sc = harness.load_scenario(next(p for p in TASKS if p.stem == "tiny_bpp_format"))
    script = [[("check_environment", {})]] * 10
    res = replay(sc, script, tmp_path / "loop", monkeypatch, harness.Limits(max_tool_calls=4))
    assert res["score"]["ended"] == "max_tool_calls" and res["score"]["tool_calls"] == 4


def test_report(tmp_path):
    import json

    import run_evals
    (tmp_path / "run.json").write_text(json.dumps({
        "assistant_model": "m", "user_model": "u", "effort": None, "trials": 1,
        "started": "20261002-000000", "bpp_mcp": "0.1.0"}))
    score = {"passed": False, "lint_valid": True, "smoke_ok": True, "choices": {"analysis": False},
             "hand_edits": [], "undocumented_keywords": ["wprior"], "tool_calls": 9,
             "user_turns": 4, "ended": "user_done"}
    (tmp_path / "a.1.json").write_text(json.dumps({
        "id": "a", "trial": 1, "score": score, "cost_usd": {"assistant": 0.5, "user": None}}))
    (tmp_path / "b.1.json").write_text(json.dumps({"id": "b", "trial": 1, "skipped": "no data"}))
    text = run_evals.report([tmp_path])
    assert "**Passed 0 of 1**" in text and "1 skipped" in text
    assert "| a | 1 | **no** | yes | yes | analysis | – | wprior | 9 | 4 | user done |" in text
