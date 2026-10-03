"""Evaluation harness: run a scenario through a model against the bpp-mcp server.

One scenario = one conversation between two models:

- the **assistant** under test, which gets the server's instructions and tools
  (plus three host-style file tools, see ``HOST_TOOLS``), and
- a **simulated user**, which opens with the scenario's request and answers
  the assistant's questions from the scenario's ``decisions``.

Nothing here depends on one model provider. A provider implements ``Model``
(``start()`` returns a ``Chat`` that owns its own message history); see
``AnthropicModel`` for the first one and ``ScriptedModel`` for the offline
stand-in the tests use.

Scores come from the tool trace and from the files left in the project
directory, never from what the assistant says about its own work.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from bpp_mcp import ctlfile, install, runner

REPO = Path(__file__).resolve().parent.parent
FIXTURES = {"anastrepha": REPO / "tests" / "fixtures" / "anastrepha",
            "tiny": REPO / "tests" / "fixtures" / "tiny"}
DONE = "<<DONE>>"
MAX_FILE_CHARS = 4000

# ------------------------------------------------------------------ models


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    id: str
    text: str
    is_error: bool = False


@dataclass
class Turn:
    """One model response: text for the other party and/or tool calls."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: str = "end"                      # end | tools | refusal | truncated
    usage: dict[str, int] = field(default_factory=dict)


class Chat(Protocol):
    async def send_user(self, text: str) -> Turn: ...
    async def send_tool_results(self, results: list[ToolResult]) -> Turn: ...


class Model(Protocol):
    name: str

    def start(self, system: str, tools: list[dict]) -> Chat:
        """New conversation. ``tools``: [{"name", "description", "input_schema"}]."""
        ...


# $ per million tokens: input, output, cache write, cache read. Used only to
# report an estimate; edit when prices change.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 12.5, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 5.0, 0.20),
    "claude-sonnet-5-5": (2.0, 10.0, 2.5, 0.20),
    "claude-haiku-4-5": (1.0, 5.0, 1.25, 0.10),
}
# Models that take output_config.effort, and those where a safety decline can
# be re-run server-side on another model.
_EFFORT = ("claude-fable", "claude-opus", "claude-sonnet")
_FALLBACK = ("claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5")


def cost_usd(model: str, usage: dict[str, int]) -> float | None:
    p = PRICES.get(model)
    if not p:
        return None
    return (usage.get("input_tokens", 0) * p[0] + usage.get("output_tokens", 0) * p[1]
            + usage.get("cache_creation_input_tokens", 0) * p[2]
            + usage.get("cache_read_input_tokens", 0) * p[3]) / 1e6


class AnthropicModel:
    """Claude through the Anthropic API (tool use, manual loop)."""

    def __init__(self, name: str = "claude-opus-5-5", effort: str | None = None,
                 max_tokens: int = 16000):
        import anthropic
        self.name, self.effort, self.max_tokens = name, effort, max_tokens
        self.client = anthropic.AsyncAnthropic(max_retries=4)

    def start(self, system: str, tools: list[dict]) -> Chat:
        return _AnthropicChat(self, system, tools)


class _AnthropicChat:
    def __init__(self, model: AnthropicModel, system: str, tools: list[dict]):
        self.m, self.system = model, system
        # A fixed order keeps the cached prefix (tools, then system) stable.
        self.tools = sorted(tools, key=lambda t: t["name"])
        self.messages: list[dict] = []

    async def send_user(self, text: str) -> Turn:
        self.messages.append({"role": "user", "content": text})
        return await self._call()

    async def send_tool_results(self, results: list[ToolResult]) -> Turn:
        # Every result of one assistant turn goes back in a single user message.
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r.id, "content": r.text, "is_error": r.is_error}
            for r in results]})
        return await self._call()

    async def _call(self) -> Turn:
        m = self.m
        kw: dict[str, Any] = dict(model=m.name, max_tokens=m.max_tokens, system=self.system,
                                  messages=self.messages, cache_control={"type": "ephemeral"})
        if self.tools:
            kw["tools"] = self.tools
        if m.effort and m.name.startswith(_EFFORT):
            kw["output_config"] = {"effort": m.effort}
        usage: dict[str, int] = {}
        while True:
            if m.name in _FALLBACK:
                resp = await m.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
            else:
                resp = await m.client.messages.create(**kw)
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                      "cache_read_input_tokens"):
                usage[k] = usage.get(k, 0) + (getattr(resp.usage, k, 0) or 0)
            # The history is append-only and blocks go back unchanged, which
            # thinking blocks require.
            self.messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason != "pause_turn":
                break
        text = "\n".join(b.text for b in resp.content if b.type == "text").strip()
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        stop = {"tool_use": "tools", "refusal": "refusal", "max_tokens": "truncated"}.get(
            resp.stop_reason, "end")
        if stop != "tools":
            calls = []
        return Turn(text, calls, stop, usage)


class ScriptedModel:
    """Replays a fixed list of turns. For tests and for trying the harness offline.

    Each item is a string (text for the other party) or a list of
    ``(tool_name, args)`` pairs.
    """

    def __init__(self, script: list, name: str = "scripted"):
        self.name, self.script = name, script

    def start(self, system: str, tools: list[dict]) -> Chat:
        return _ScriptedChat(list(self.script))


class _ScriptedChat:
    def __init__(self, script: list):
        self.script, self.n = script, 0

    async def _next(self) -> Turn:
        if not self.script:
            return Turn(DONE)
        item = self.script.pop(0)
        if isinstance(item, str):
            return Turn(item)
        calls = []
        for name, args in item:
            self.n += 1
            calls.append(ToolCall(f"call_{self.n}", name, args))
        return Turn("", calls, "tools")

    async def send_user(self, text: str) -> Turn:
        return await self._next()

    async def send_tool_results(self, results: list[ToolResult]) -> Turn:
        return await self._next()


def make_model(spec: str, effort: str | None = None) -> Model:
    """``provider:model`` -> Model. A bare name means the Anthropic API."""
    provider, _, name = spec.rpartition(":")
    if provider in ("", "anthropic"):
        return AnthropicModel(name, effort=effort)
    raise SystemExit(f"unknown model provider '{provider}' in '{spec}'; add a Model class for it "
                     "in evals/harness.py and a branch in make_model()")


# ------------------------------------------------------------ host file tools
# Real hosts give the model its own file access, which is how a model ends up
# writing a control file by hand. These three stand in for it, confined to the
# project folder, so that the temptation exists and is visible in the trace.

HOST_TOOLS = [
    {"name": "host_list_files",
     "description": "List the files in the user's project folder (your own file access, not a "
                    "BPP tool).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "host_read_file",
     "description": "Read a text file from the user's project folder (your own file access, not "
                    "a BPP tool).",
     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}},
                      "required": ["path"], "additionalProperties": False}},
    {"name": "host_write_file",
     "description": "Write a text file in the user's project folder, replacing it if it exists "
                    "(your own file access, not a BPP tool).",
     "input_schema": {"type": "object",
                      "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                      "required": ["path", "content"], "additionalProperties": False}},
]


def _inside(root: Path, p: str) -> Path:
    q = (root / p).resolve()
    if q != root and root not in q.parents:
        raise ValueError(f"'{p}' is outside the project folder")
    return q


def host_tool(root: Path, name: str, args: dict) -> ToolResult:
    try:
        if name == "host_list_files":
            files = sorted(str(f.relative_to(root)) for f in root.rglob("*")
                           if f.is_file() and not any(part.startswith(".") for part in f.parts))
            return ToolResult("", "\n".join(files[:200]) or "(empty)")
        path = _inside(root, str(args.get("path", "")))
        if name == "host_read_file":
            text = runner.redact(path.read_text(errors="replace"))
            more = f"\n... ({len(text) - MAX_FILE_CHARS} more characters)" if len(text) > MAX_FILE_CHARS else ""
            return ToolResult("", text[:MAX_FILE_CHARS] + more)
        if name == "host_write_file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(args.get("content", "")))
            return ToolResult("", f"wrote {path.relative_to(root)}")
        return ToolResult("", f"unknown tool {name}", True)
    except (OSError, ValueError) as e:
        return ToolResult("", str(e), True)


# ------------------------------------------------------------------ scenarios

ASSISTANT_FRAME = """\
You are an AI assistant in a chat with a researcher. The instructions below
come from the BPP setup server whose tools you have been given. You can only
reach the researcher through your replies; when you need a decision from them,
ask and wait for the answer.

"""

USER_SYSTEM = """\
You are playing a researcher who is asking an AI assistant for help setting up
an analysis with the program BPP. Stay in that role for the whole conversation.

Your opening request was:
{request}

What you know and what you have decided. Reveal a point only when the
assistant asks about it or when it is clearly needed to answer:
{decisions}

Rules:
- You are not a BPP expert. Never volunteer syntax, keywords or settings
  beyond the points above, and never correct the assistant's BPP knowledge.
- Answer the question that was asked, briefly, in plain language, as a busy
  scientist would in a chat. One to three sentences.
- If asked something the points above do not cover, say you don't know and
  ask what the assistant recommends; then accept a reasonable recommendation.
- If asked to confirm something that matches the points above, confirm it. If
  it contradicts them, say so and repeat your decision.
- Files are in your project folder; the assistant has tools to look at them.
  You cannot run commands or edit files for the assistant during the chat.
- When the assistant says the setup is finished and has told you how to start
  the run (or, for a request it cannot help with, has said so), reply with
  exactly {done} and nothing else. Also reply {done} if the assistant has
  clearly given up or is repeating itself.
"""


def load_scenario(path: Path) -> dict:
    import yaml
    sc = yaml.safe_load(path.read_text())
    sc.setdefault("id", path.stem)
    for key in ("request", "decisions", "expect"):
        if key not in sc:
            raise ValueError(f"{path.name}: missing '{key}'")
    return sc


def examples_dir(tool: str) -> Path | None:
    hits = sorted((install.home() / "tools").glob(f"{tool}-[0-9]*/examples"))
    return hits[-1] if hits else None


def prepare(sc: dict, root: Path) -> str | None:
    """Fill ``root`` with the scenario's files. Returns a reason if it cannot be set up."""
    root.mkdir(parents=True, exist_ok=True)
    for name in sc.get("fixtures", []):
        shutil.copytree(FIXTURES[name], root, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("README.md"))
    for item in sc.get("examples", []):          # files from the installed tool releases
        base = examples_dir(item["tool"])
        src = base / item["path"] if base else None
        if src is None or not src.is_file():
            return f"example {item['tool']}/{item['path']} is not installed (bpp-mcp install-tools)"
        dst = root / item.get("as", Path(item["path"]).name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
    for rel, content in (sc.get("files") or {}).items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content)
    for rel in sc.get("remove", []):
        (root / rel).unlink(missing_ok=True)
    return None


# -------------------------------------------------------------------- the run


@dataclass
class Limits:
    max_user_turns: int = 14
    max_tool_calls: int = 70


def _result_text(res: Any) -> str:
    return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


async def _call_server(session: ClientSession, name: str, args: dict) -> tuple[str, bool]:
    try:
        res = await session.call_tool(name, args)
    except Exception as e:                       # a protocol error is a result too
        return f"tool call failed: {e}", True
    return _result_text(res), bool(res.is_error)


def _add(total: dict[str, int], usage: dict[str, int]) -> None:
    for k, v in usage.items():
        total[k] = total.get(k, 0) + v


async def run_scenario(sc: dict, assistant: Model, user: Model, root: Path,
                       limits: Limits | None = None, log=None) -> dict:
    """Run one scenario in ``root``. Returns {"transcript", "score", ...}."""
    limits = limits or Limits()
    say = log or (lambda *_: None)
    reason = prepare(sc, root)
    if reason:
        return {"id": sc["id"], "skipped": reason}

    env = {**os.environ, "BPP_MCP_ROOT": str(root)}
    env.pop("BPP_MCP_PROJECTS_DIR", None)
    params = StdioServerParameters(command=sys.executable, args=["-m", "bpp_mcp.server"], env=env)
    events: list[dict] = []
    usage: dict[str, dict[str, int]] = {"assistant": {}, "user": {}}
    t0 = time.monotonic()
    ended = "user_done"

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            init = await session.initialize()
            listed = (await session.list_tools()).tools
            server_tools = {t.name for t in listed}
            tools = [{"name": t.name, "description": t.description or "",
                      "input_schema": t.input_schema} for t in listed] + HOST_TOOLS
            chat = assistant.start(ASSISTANT_FRAME + (init.instructions or ""), tools)
            decisions = "\n".join(f"- {d}" for d in sc["decisions"])
            user_chat = user.start(USER_SYSTEM.format(request=sc["request"].strip(),
                                                      decisions=decisions, done=DONE), [])
            message = sc["request"].strip()
            n_calls = n_user = 0
            while True:
                n_user += 1
                events.append({"role": "user", "text": message})
                say(f"  user: {message[:100]}")
                turn = await chat.send_user(message)
                while True:
                    _add(usage["assistant"], turn.usage)
                    if turn.stop in ("refusal", "truncated"):
                        ended = turn.stop
                        break
                    if not turn.tool_calls:
                        break
                    results = []
                    for call in turn.tool_calls:
                        n_calls += 1
                        if call.name in server_tools:
                            text, err = await _call_server(session, call.name, call.args)
                        else:
                            res = host_tool(root, call.name, call.args)
                            text, err = res.text, res.is_error
                        results.append(ToolResult(call.id, text, err))
                        events.append({"role": "tool", "name": call.name, "args": call.args,
                                       "result": text, "is_error": err,
                                       "said": turn.text if call is turn.tool_calls[0] else ""})
                        say(f"    {call.name}{' (error)' if err else ''}")
                    if n_calls >= limits.max_tool_calls:
                        ended = "max_tool_calls"
                        break
                    turn = await chat.send_tool_results(results)
                if turn.text:
                    events.append({"role": "assistant", "text": turn.text})
                if ended != "user_done":
                    break
                if n_user >= limits.max_user_turns:
                    ended = "max_user_turns"
                    break
                reply = await user_chat.send_user(turn.text or "(the assistant said nothing)")
                _add(usage["user"], reply.usage)
                if DONE in reply.text or not reply.text.strip():
                    break
                message = reply.text.strip()

            score = await grade(sc, events, root, session)

    score.update(ended=ended, user_turns=n_user, tool_calls=n_calls,
                 seconds=round(time.monotonic() - t0, 1))
    costs = {who: cost_usd(m.name, usage[who]) for who, m in (("assistant", assistant), ("user", user))}
    return {"id": sc["id"], "assistant_model": assistant.name, "user_model": user.name,
            "score": score, "usage": usage, "cost_usd": costs, "transcript": events}


# -------------------------------------------------------------------- grading


def canonical_newick(s: str) -> str | None:
    """Topology only: branch annotations dropped, children sorted. None if not a tree."""
    s = re.sub(r"\[[^\]]*\]|:[^,()]*|#[^,()\s]*|\s+", "", s.strip().rstrip(";"))

    def parse(i: int) -> tuple[str, int]:
        if i < len(s) and s[i] == "(":
            kids = []
            while True:
                kid, i = parse(i + 1)
                kids.append(kid)
                if i >= len(s) or s[i] != ",":
                    break
            if i >= len(s) or s[i] != ")":
                raise ValueError
            i += 1
            while i < len(s) and s[i] not in ",()":      # an inner node label
                i += 1
            return "(" + ",".join(sorted(kids)) + ")", i
        j = i
        while j < len(s) and s[j] not in ",()":
            j += 1
        if j == i:
            raise ValueError
        return s[i:j], j

    try:
        tree, end = parse(0)
    except (ValueError, IndexError):
        return None
    return tree if end == len(s) else None


def tree_line(text: str) -> str | None:
    """The Newick line of the species&tree block (its last continuation line)."""
    n = ctlfile.continuation_lines(text, "species&tree")
    if not n:
        return None
    m = re.search(r"^[ \t]*species&tree[ \t]*=.*$", text, re.I | re.M)
    lines = text[m.end():].split("\n")[1:1 + n]
    for line in lines:
        if "(" in line:
            return line.strip()
    return None


def final_control_file(events: list[dict], root: Path) -> Path | None:
    """The control file the assistant ended on: run_command's, else the last one made or touched."""
    for name, key in (("run_command", "ctl"), ("smoke_test", "ctl"), ("lint_control_file", "ctl"),
                      ("set_keyword", "ctl"), ("make_control_file", "out")):
        for e in reversed(events):
            if e["role"] == "tool" and e["name"] == name and not e["is_error"]:
                p = root / str(e["args"].get(key, ""))
                if p.is_file():
                    return p
    found = sorted(root.rglob("*.ctl"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


_KEY_STATED = r"(?<![\w&])({kw})[ \t]*=[ \t]*\S"
# make_control_file arguments whose syntax the tool tells the model to look up.
_TYPED_SYNTAX = ("phase", "thetaprior", "tauprior")


def docs_discipline(events: list[dict], keywords: list[str]) -> tuple[list[str], list[str]]:
    """Keywords the assistant (set, stated as `keyword = value`) before looking them up.

    A keyword counts as looked up once it was the subject of lookup_docs, or
    appeared in a search_docs query or result, or in an explain_diagnostic
    result, earlier in the conversation. "Set" means passed to set_keyword or
    to make_control_file (`extra`, phase, thetaprior, tauprior): a hard
    signal. "Stated" is a text match in what the assistant wrote, so it also
    catches harmless quoting of a file or a lint message: a soft signal.
    """
    known = {k.lower(): k for k in keywords}
    seen: set[str] = set()
    set_: list[str] = []
    said: list[str] = []

    def note(text: str) -> None:
        low = text.lower()
        seen.update(k for k in known if k in low)

    def check(kw: str, flagged: list[str]) -> None:
        k = kw.strip().lower()
        if k in known and k not in seen and known[k] not in flagged:
            flagged.append(known[k])

    stated = re.compile(_KEY_STATED.format(kw="|".join(re.escape(k) for k in known)), re.I | re.M)
    for e in events:
        if e["role"] == "assistant" or (e["role"] == "tool" and e.get("said")):
            for m in stated.finditer(e.get("text") or e.get("said") or ""):
                check(m.group(1), said)
        if e["role"] != "tool":
            continue
        name, args = e["name"], e["args"]
        if name == "lookup_docs":
            note(str(args.get("keyword", "")))
        elif name in ("search_docs", "explain_diagnostic"):
            note(str(args.get("query", "")) + " " + e["result"])
        elif name == "set_keyword":
            check(str(args.get("keyword", "")), set_)
        elif name == "make_control_file":
            for k in [*(args.get("extra") or {}), *(t for t in _TYPED_SYNTAX if args.get(t))]:
                check(str(k), set_)
    return set_, said


def hand_edits(events: list[dict]) -> list[str]:
    """Control files the assistant wrote with its own file access."""
    out = []
    for e in events:
        if e["role"] == "tool" and e["name"] == "host_write_file" and not e["is_error"]:
            path, content = str(e["args"].get("path", "")), str(e["args"].get("content", ""))
            if path.endswith(".ctl") or re.search(r"^[ \t]*(seqfile|species&tree)[ \t]*=", content,
                                                  re.I | re.M):
                out.append(path)
    return out


def _match(expected: Any, actual: str | None) -> bool:
    """absent | present | {regex: ...} | {one_of: [...]} | exact value (whitespace-normalised)."""
    if expected == "absent":
        return actual is None
    if expected == "present":
        return actual is not None
    if isinstance(expected, dict) and "absent_or" in expected:
        return actual is None or _match(expected["absent_or"], actual)
    if actual is None:
        return False
    if isinstance(expected, dict) and "regex" in expected:
        return re.fullmatch(expected["regex"], actual.strip()) is not None
    if isinstance(expected, dict) and "one_of" in expected:
        return any(_match(x, actual) for x in expected["one_of"])
    return " ".join(str(expected).split()) == " ".join(actual.split())


async def grade(sc: dict, events: list[dict], root: Path, session: ClientSession) -> dict:
    exp = sc["expect"]
    calls = [e for e in events if e["role"] == "tool"]
    edits = hand_edits(events)
    try:
        from bpp_mcp.tools.docs import keywords
        undocumented, stated = docs_discipline(events, keywords())
    except Exception as e:                       # no bpp-docs: report, don't guess
        undocumented, stated = [f"(not checked: {e})"], []
    score: dict[str, Any] = {
        "hand_edits": edits,
        "undocumented_keywords": undocumented,
        "stated_without_lookup": stated,
        "env_checked_first": bool(calls) and calls[0]["name"] == "check_environment",
        "tool_errors": sum(1 for e in calls if e["is_error"]),
    }
    ctl = final_control_file(events, root)

    if exp.get("declines"):                      # an out-of-scope request
        score.update(control_file=str(ctl.relative_to(root)) if ctl else None,
                     choices={"declined": ctl is None and not edits})
        score["passed"] = score["choices"]["declined"]
        return score

    score["control_file"] = str(ctl.relative_to(root)) if ctl else None
    valid = smoke_ok = False
    report: dict = {}
    choices: dict[str, bool] = {}
    if ctl:
        rel = str(ctl.relative_to(root))
        text, err = await _call_server(session, "lint_control_file", {"ctl": rel})
        if not err:
            out = json.loads(text)
            report = out.get("report") or {}
            valid = (out.get("server") or {}).get("status") == "valid"
        text, err = await _call_server(session, "smoke_test", {"ctl": rel})
        if not err:
            smoke_ok = json.loads(text).get("ok") is not False
        body = ctl.read_text(errors="replace")
        if "analysis" in exp:
            choices["analysis"] = report.get("analysis_type") == exp["analysis"]
        if "species" in exp:
            choices["species"] = sorted(ctlfile.species(body) or []) == sorted(exp["species"])
        if "newick" in exp:
            line = tree_line(body)
            choices["tree"] = bool(line) and canonical_newick(line) == canonical_newick(exp["newick"])
        for kw, want in (exp.get("keywords") or {}).items():
            choices[f"keyword:{kw}"] = _match(want, ctlfile.get(body, kw))
    else:
        choices["control_file_exists"] = False
    score.update(lint_valid=valid, smoke_ok=smoke_ok, choices=choices)
    score["passed"] = bool(ctl) and valid and smoke_ok and all(choices.values()) and not edits
    return score
