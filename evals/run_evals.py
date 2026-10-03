"""Run the evaluation scenarios through a model, or write the report.

    python evals/run_evals.py run --model claude-code:opus --user-model claude-code:haiku
    python evals/run_evals.py run --model claude-opus-5-5
    python evals/run_evals.py run --model claude-haiku-4-5 --tasks 'anas_*' --trials 3
    python evals/run_evals.py report evals/runs/* > evals/RESULTS.md

`run` needs the BPP tools (bpp-mcp install-tools) and `pip install -e '.[evals]'`.
A `claude-code:` model runs Claude Code in headless mode on your claude.ai
login and counts against your subscription's usage limits. A bare model name
uses the Anthropic API and is billed per token. Either way every scenario is
a multi-turn conversation between two models.
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import fnmatch
import json
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import harness  # noqa: E402

TASKS = Path(__file__).resolve().parent / "tasks"
RUNS = Path(__file__).resolve().parent / "runs"


def select(patterns: list[str]) -> list[dict]:
    scenarios = [harness.load_scenario(p) for p in sorted(TASKS.glob("*.yaml"))]
    if patterns:
        scenarios = [s for s in scenarios if any(fnmatch.fnmatch(s["id"], p) for p in patterns)]
    if not scenarios:
        raise SystemExit("no scenarios match")
    return scenarios


async def run(args: argparse.Namespace) -> int:
    from bpp_mcp.tools.env import check_environment
    env = check_environment()
    missing = [n for n, t in env["tools"].items() if not t.get("ok")]
    if missing:
        raise SystemExit(f"BPP tools missing or too old: {', '.join(missing)} "
                         "(run `bpp-mcp install-tools`)")
    scenarios = select(args.tasks)
    assistant = harness.make_assistant(args.model, effort=args.effort)
    user = harness.make_model(args.user_model)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else RUNS / f"{stamp}-{assistant.name}"
    out.mkdir(parents=True, exist_ok=True)
    limits = harness.Limits(args.max_user_turns, args.max_tool_calls)
    sem = asyncio.Semaphore(args.jobs)
    results: list[dict] = []

    async def one(sc: dict, trial: int) -> None:
        async with sem:
            tag = f"{sc['id']}#{trial}"
            work = Path(tempfile.mkdtemp(prefix=f"bpp-eval-{sc['id']}-"))
            root = work / "project"
            log = (lambda msg: print(f"[{tag}] {msg}", file=sys.stderr)) if args.verbose else None
            try:
                res = await harness.run_scenario(sc, assistant, user, root, limits, log)
            except Exception as e:               # one broken scenario must not stop the run
                res = {"id": sc["id"], "error": f"{type(e).__name__}: {e}",
                       "traceback": traceback.format_exc()}
            res["trial"] = trial
            (out / f"{sc['id']}.{trial}.json").write_text(json.dumps(res, indent=2, default=str))
            if args.keep_projects and root.exists():
                shutil.copytree(root, out / "projects" / f"{sc['id']}.{trial}", dirs_exist_ok=True)
            shutil.rmtree(work, ignore_errors=True)
            results.append(res)
            s = res.get("score") or {}
            status = ("skipped: " + res["skipped"] if "skipped" in res else
                      "ERROR: " + res["error"] if "error" in res else
                      ("pass" if s.get("passed") else "FAIL")
                      + f"  tools={s.get('tool_calls')} turns={s.get('user_turns')}")
            print(f"{tag:<28} {status}", file=sys.stderr)

    await asyncio.gather(*(one(sc, t) for sc in scenarios for t in range(1, args.trials + 1)))
    meta = {"assistant_model": assistant.name, "user_model": user.name, "effort": args.effort,
            "trials": args.trials, "started": stamp, "bpp_mcp": env["server"]["bpp_mcp_version"],
            "tools": {n: t.get("version") for n, t in env["tools"].items()}}
    (out / "run.json").write_text(json.dumps(meta, indent=2))
    print(f"\nresults in {out}", file=sys.stderr)
    print(report([out]))
    return 0


# --------------------------------------------------------------------- report


def _load(run_dir: Path) -> tuple[dict, list[dict]]:
    meta = json.loads((run_dir / "run.json").read_text())
    results = [json.loads(p.read_text()) for p in sorted(run_dir.glob("*.json")) if p.name != "run.json"]
    return meta, results


def _mark(ok: bool | None) -> str:
    return "–" if ok is None else ("yes" if ok else "**no**")


def report(run_dirs: list[Path]) -> str:
    lines = ["# Evaluation results", "",
             "Written by `python evals/run_evals.py report`. What is measured, and what is not, "
             "is described in `evals/README.md`.", ""]
    for d in run_dirs:
        if not (d / "run.json").is_file():
            continue
        meta, results = _load(d)
        scored = [r for r in results if "score" in r]
        skipped = [r for r in results if "skipped" in r]
        errors = [r for r in results if "error" in r]
        n = len(scored)
        passed = sum(1 for r in scored if r["score"]["passed"])
        total = sum((r["cost_usd"].get("assistant") or 0) + (r["cost_usd"].get("user") or 0)
                    for r in scored)
        lines += [f"## {meta['assistant_model']}"
                  + (f", effort {meta['effort']}" if meta.get("effort") else ""), "",
                  f"- Run {meta['started']}; bpp-mcp {meta['bpp_mcp']}; simulated user: "
                  f"{meta['user_model']}; {meta['trials']} trial(s) per scenario.",
                  f"- **Passed {passed} of {n}** scored conversations"
                  + (f"; {len(skipped)} skipped" if skipped else "")
                  + (f"; {len(errors)} harness errors" if errors else "") + ".",
                  ]
        if n:
            def count(f) -> int:
                return sum(1 for r in scored if f(r["score"]))
            made = count(lambda s: "lint_valid" in s)
            lines += [
                f"- Of the {made} that should end with a control file: lint valid "
                f"{count(lambda s: s.get('lint_valid'))}/{made}, test run ok "
                f"{count(lambda s: s.get('smoke_ok'))}/{made}. All expected choices right: "
                f"{count(lambda s: all(s['choices'].values()))}/{n}.",
                f"- Wrote a control file by hand: {count(lambda s: s['hand_edits'])}/{n}. Set a "
                f"keyword before looking it up: {count(lambda s: s['undocumented_keywords'])}/{n}. "
                f"Wrote `keyword = value` in a reply before any tool had shown that keyword: "
                f"{count(lambda s: s.get('stated_without_lookup'))}/{n}.",
                f"- Mean tool calls {sum(r['score']['tool_calls'] for r in scored) / n:.1f}, mean "
                f"user turns {sum(r['score']['user_turns'] for r in scored) / n:.1f}. Cost at API "
                f"prices, estimated: ${total:.2f} (${total / n:.2f} per conversation).",
                "",
                "| Scenario | Trial | Pass | Lint | Test run | Choices wrong | By hand | Set, not looked up "
                "| Tool calls | User turns | Ended |",
                "|---|---|---|---|---|---|---|---|---|---|---|"]
            for r in sorted(scored, key=lambda r: (r["id"], r["trial"])):
                s = r["score"]
                wrong = ", ".join(k for k, ok in s["choices"].items() if not ok) or "–"
                lines.append(
                    f"| {r['id']} | {r['trial']} | {_mark(s['passed'])} | {_mark(s.get('lint_valid'))} "
                    f"| {_mark(s.get('smoke_ok'))} | {wrong} | {', '.join(s['hand_edits']) or '–'} "
                    f"| {', '.join(s['undocumented_keywords']) or '–'} | {s['tool_calls']} "
                    f"| {s['user_turns']} | {s['ended'].replace('_', ' ')} |")
        for r in skipped:
            lines.append(f"- Skipped {r['id']}: {r['skipped']}")
        for r in errors:
            lines.append(f"- Harness error in {r['id']}: {r['error']}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run scenarios (spends API money)")
    r.add_argument("--model", default="claude-opus-5-5",
                   help="assistant under test, as [provider:]model (default: %(default)s)")
    r.add_argument("--user-model", default="claude-haiku-4-5",
                   help="model that plays the user (default: %(default)s)")
    r.add_argument("--effort", default=None, help="output effort for the assistant, if it takes one")
    r.add_argument("--tasks", nargs="*", default=[], metavar="ID", help="scenario ids or globs (default: all)")
    r.add_argument("--trials", type=int, default=1)
    r.add_argument("--jobs", type=int, default=3, help="conversations run at once")
    r.add_argument("--max-user-turns", type=int, default=14)
    r.add_argument("--max-tool-calls", type=int, default=70)
    r.add_argument("--out", help="results folder (default: evals/runs/<time>-<model>)")
    r.add_argument("--keep-projects", action="store_true", help="keep each project folder with the results")
    r.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("report", help="print the Markdown report for finished runs")
    p.add_argument("runs", nargs="+", type=Path)
    args = ap.parse_args(argv)
    if args.cmd == "report":
        print(report(args.runs))
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
