import json
import os
import stat
import sys

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from bpp_mcp import runner

PY = sys.executable
SEQ = "ACGTACGTACGTACGTACGTACGTACGTACGTACGTAC"  # 38 bp


def py(code):
    return [PY, "-c", code]


def test_run_ok(tmp_path):
    r = runner.run(py("import sys; print('hi'); print('err', file=sys.stderr); sys.exit(3)"),
                   cwd=tmp_path)
    assert (r.exit_code, r.stdout.strip(), r.stderr.strip(), r.timed_out) == (3, "hi", "err", False)


def test_run_cwd(tmp_path):
    r = runner.run(py("import os; print(os.getcwd())"), cwd=tmp_path)
    assert os.path.samefile(r.stdout.strip(), tmp_path)


def test_run_timeout(tmp_path):
    r = runner.run(py("import time, sys; print('started', flush=True); time.sleep(30)"),
                   cwd=tmp_path, timeout=1)
    assert r.timed_out and r.exit_code is None
    assert r.seconds < 10
    assert "started" in r.stdout


def test_run_missing_binary(tmp_path):
    with pytest.raises(ToolError, match="could not run"):
        runner.run([str(tmp_path / "nope")], cwd=tmp_path)


def test_json_result_timeout_is_tool_error(tmp_path):
    r = runner.run(py("import time; time.sleep(30)"), cwd=tmp_path, timeout=1)
    with pytest.raises(ToolError, match="did not finish"):
        runner.json_result(r)


def test_json_result_passthrough(tmp_path):
    report = {"status": "valid", "diagnostics": [], "n": 2}
    r = runner.run(py(f"print({json.dumps(json.dumps(report))})"), cwd=tmp_path)
    assert runner.json_result(r) == {"exit_code": 0, "report": report}


def test_json_result_non_json(tmp_path):
    r = runner.run(py("import sys; print('plain'); print('oops', file=sys.stderr); sys.exit(2)"),
                   cwd=tmp_path)
    out = runner.json_result(r)
    assert out["exit_code"] == 2 and out["report"] is None
    assert out["stdout"].strip() == "plain" and out["stderr"].strip() == "oops"


def test_json_result_caps_lists_and_notes_it(tmp_path):
    report = {"sample_names": [f"s{i}" for i in range(500)]}
    r = runner.run(py(f"print({json.dumps(json.dumps(report))})"), cwd=tmp_path)
    out = runner.json_result(r)
    assert len(out["report"]["sample_names"]) == runner.MAX_LIST
    assert any("sample_names" in n and "500" in n for n in out["server"]["truncated"])


def test_json_result_caps_huge_stderr(tmp_path):
    r = runner.run(py("import sys; sys.stderr.write('x' * 100000)"), cwd=tmp_path)
    out = runner.json_result(r)
    assert len(out["stderr"]) == runner.MAX_TEXT
    assert out["server"]["truncated"]


def test_sanitize_capped_total_size():
    big = {f"k{i}": ["y" * 1000] * 50 for i in range(50)}
    notes = []
    out = runner.sanitize_capped(big, notes)
    assert len(json.dumps(out)) <= runner.MAX_RESULT
    assert notes


def test_redact_sequences():
    assert SEQ not in runner.redact(f"^a1 {SEQ}")
    assert "38 chars of sequence data redacted" in runner.redact(SEQ)
    assert runner.redact(SEQ.lower() + "-NN") != SEQ.lower() + "-NN"
    # short runs, separators, ordinary text and paths are kept
    for s in ["ACGTACGT", "-" * 60, "." * 60, "/data/loci/locus_ACGT.fa",
              "Expected 3 loci but found only 2", "speciesdelimitation = 1 0 2"]:
        assert runner.redact(s) == s


def test_sanitize_redacts_nested_and_cuts_strings():
    notes = []
    out = runner.sanitize({"a": [{"seq": SEQ}], "long": "z" * 5000}, notes)
    assert SEQ not in json.dumps(out)
    assert len(out["long"]) == runner.MAX_STR
    assert any(n.startswith("long:") for n in notes)


def test_cap_text_head_and_tail():
    assert runner.cap_text("abcdef", 3) == ("def", True)
    assert runner.cap_text("abcdef", 3, keep="head") == ("abc", True)
    assert runner.cap_text("abc", 3) == ("abc", False)


def _fake_bin(d, name):
    p = d / name
    p.write_text("#!/bin/sh\necho fake\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return p


def test_find_env_override(tmp_path, monkeypatch):
    p = _fake_bin(tmp_path, "my-lint")
    monkeypatch.setenv("BPP_MCP_BPP_LINT", str(p))
    assert runner.find("bpp-lint") == str(p)
    monkeypatch.setenv("BPP_MCP_BPP_LINT", str(tmp_path / "missing"))
    assert runner.find("bpp-lint") is None


def test_find_extra_dirs(tmp_path, monkeypatch):
    _fake_bin(tmp_path, "bpp-zzz")
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(runner, "EXTRA_DIRS", [str(tmp_path)])
    assert runner.find("bpp-zzz") == str(tmp_path / "bpp-zzz")


def test_require_missing(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(runner, "EXTRA_DIRS", [])
    with pytest.raises(ToolError, match="brew install bpp/tap/bpp-qqq"):
        runner.require("bpp-qqq")
