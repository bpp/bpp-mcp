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
