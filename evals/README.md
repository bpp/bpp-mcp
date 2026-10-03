# Evaluation

The unit and end-to-end tests show that the code runs. This shows whether the
project works: can a model, given this server, take a novice from a vague
request to a correct, tested control file?

Each scenario in `tasks/` is one conversation between two models. The
**assistant** under test gets the server's instructions and tools. A
**simulated user** opens with the scenario's request and answers the
assistant's questions from the scenario's list of decisions, without
volunteering BPP expertise. The conversation ends when the user is told the
setup is finished, or at a limit of user turns or tool calls.

```
pip install -e '.[evals]'        # anthropic + pyyaml
bpp-mcp install-tools
python evals/run_evals.py run --model claude-code:opus --user-model claude-code:haiku -v
python evals/run_evals.py run --model claude-opus-5-5 --tasks 'anas_*' --trials 3
python evals/run_evals.py report evals/runs/* > evals/RESULTS.md
```

There are two ways to supply the models:

- `--model claude-code:opus --user-model claude-code:haiku` runs Claude Code
  in headless mode (`claude -p`) on your claude.ai login. It counts against
  your subscription's usage limits instead of being billed per token. The bpp
  server is attached with `--mcp-config`; your own settings, plugins, skills
  and other MCP servers are left out; and Claude Code's Read, Write, Edit,
  Glob and Grep are the assistant's file tools. This is the closest to what a
  user sees.
- A bare model name, e.g. `--model claude-opus-5-5`, uses the Anthropic API
  (credentials in the environment, billed per token). The harness runs the
  tool loop itself.

Either way a scenario is a multi-turn conversation between two models. `run`
writes one JSON file per conversation, with the full transcript, under
`evals/runs/` (not committed), and prints the report. The cost figure in the
report is what the tokens would cost at API prices.

## What a scenario holds

```yaml
request: >            # what the novice types first
fixtures: [anastrepha]   # tests/fixtures/<name>, copied into the project
examples: [...]       # files from the installed tool releases
files: {name: text}   # extra files to write;  remove: [names] to delete
decisions:            # what the user knows and would decide if asked
  - ...
expect:
  analysis: A10       # bpp-lint's analysis_type for the final file
  species: [...]      # species in species&tree
  newick: "(...);"    # topology, compared with children sorted
  keywords: {nloci: 10, phase: {regex: '1( +1){4}'}, migration: present}
  declines: true      # instead of the above: an out-of-scope request
```

Keyword expectations are an exact value (whitespace ignored), `present`,
`absent`, `{regex: ...}`, `{one_of: [...]}` or `{absent_or: ...}`.

## How a conversation is scored

Everything is computed from the tool trace and the files in the project
folder. Nothing the assistant says about its own work counts.

- **Lint valid** and **test run ok**: the harness finds the control file the
  assistant ended on and calls `lint_control_file` and `smoke_test` on it
  itself.
- **Choices**: the scenario's `expect` entries, checked against that file.
- **By hand**: the assistant also has file tools of its own, as in a real
  host: Claude Code's Read/Write/Edit, or three stand-ins (`host_list_files`,
  `host_read_file`, `host_write_file`) on the API route. Writing or editing a
  control file with them is recorded and fails the scenario, even if the
  file is correct.
- **Set, not looked up**: a keyword passed to `set_keyword` or to
  `make_control_file` (`extra`, `phase`, `thetaprior`, `tauprior`) before any
  `lookup_docs` / `search_docs` / `explain_diagnostic` result mentioned it.
- **Stated from memory**: `keyword = value` written in a reply before any
  tool result (a lookup, a control file, a lint report) had shown that
  keyword. This is a text match; read it as a hint, not a verdict.
- **Tool calls**, **user turns**, whether `check_environment` came first, and
  how the conversation ended.

**Pass** = a control file exists, lint valid, test run ok, every expected
choice right, and no control file written by hand. The two lookup measures
are reported but do not decide a pass.

## What this does not measure

- Whether the explanations given to the user were correct or clear.
- Whether the full analysis would converge or give sensible estimates; the
  test run only proves BPP accepts the file and data.
- Run-to-run variation, unless you use `--trials`. One trial per scenario is
  a rough number: a difference of one or two scenarios between two models is
  within noise.
- The simulated user is itself a model. It can leak a decision early or
  accept something a real novice would question. Read the transcripts of
  failures before blaming the assistant.

## Checking the harness itself

`reference.py` holds a known-good sequence of tool calls for every scenario.
`tests/test_evals.py` replays them through the harness with no model, and
also checks that a wrong analysis, a hand-written file, an empty result and
an out-of-scope control file all fail. A new scenario needs a reference
solution, or that test fails.

## Other models

`harness.py` talks to a model only through two small interfaces:
`Model.start(system, tools)` returns a `Chat` with `send_user(text)` and
`send_tool_results(results)`, each returning a `Turn` (text, tool calls,
usage). `AnthropicModel` is the first implementation. To use another
provider, add a class with those methods and a
branch in `make_model()`, then run with `--model yourprovider:name`. The
simulated user goes through the same interface (`--user-model`), and should be
kept the same across the models being compared.
