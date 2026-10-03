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
python evals/run_evals.py run --model claude-opus-5-5 -v
python evals/run_evals.py run --model claude-haiku-4-5 --tasks 'anas_*' --trials 3
python evals/run_evals.py report evals/runs/* > evals/RESULTS.md
```

`run` spends real money (about 20 model requests per scenario for the
assistant, plus the simulated user). It writes one JSON file per conversation,
with the full transcript, under `evals/runs/` (not committed), and prints the
report. Claude models need Anthropic API credentials in the environment.

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
- **By hand**: the assistant also gets three host-style tools
  (`host_list_files`, `host_read_file`, `host_write_file`), as real hosts
  give models their own file access. Writing a control file with
  `host_write_file` is recorded and fails the scenario, even if the file is
  correct.
- **Set, not looked up**: a keyword passed to `set_keyword` or to
  `make_control_file` (`extra`, `phase`, `thetaprior`, `tauprior`) before any
  `lookup_docs` / `search_docs` / `explain_diagnostic` result mentioned it.
- **Stated, not looked up**: `keyword = value` written in a reply before such
  a lookup. This is a text match, so it also fires when the assistant quotes
  the user's file or a lint message; read it as a hint, not a verdict.
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
usage). `AnthropicModel` is the first implementation. To compare another
provider, or a local model's agent loop, add a class with those methods and a
branch in `make_model()`, then run with `--model yourprovider:name`. The
simulated user goes through the same interface (`--user-model`), and should be
kept the same across the models being compared.
