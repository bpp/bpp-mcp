# Evaluation results

Written by `python evals/run_evals.py report`. What is measured, and what is not, is described in `evals/README.md`.

## claude-code:opus

- Run 20261003-003623; bpp-mcp 0.1.0; simulated user: claude-code:haiku; 1 trial(s) per scenario.
- **Passed 13 of 13** scored conversations.
- Of the 12 that should end with a control file: lint valid 12/12, test run ok 12/12. All expected choices right: 13/13.
- Wrote a control file by hand: 0/13. Set a keyword before looking it up: 2/13. Wrote `keyword = value` in a reply before any tool had shown that keyword: 1/13.
- Mean tool calls 11.6, mean user turns 2.2. Cost at API prices, estimated: $7.35 ($0.57 per conversation).

| Scenario | Trial | Pass | Lint | Test run | Choices wrong | By hand | Set, not looked up | Tool calls | User turns | Ended |
|---|---|---|---|---|---|---|---|---|---|---|
| anas_chain_settings | 1 | yes | yes | yes | – | – | – | 10 | 3 | user done |
| anas_delimitation | 1 | yes | yes | yes | – | – | – | 13 | 2 | user done |
| anas_joint | 1 | yes | yes | yes | – | – | – | 15 | 2 | user done |
| anas_migration | 1 | yes | yes | yes | – | – | – | 15 | 3 | user done |
| anas_parameters | 1 | yes | yes | yes | – | – | – | 11 | 3 | user done |
| anas_species_tree | 1 | yes | yes | yes | – | – | – | 16 | 3 | user done |
| anas_subset_trial | 1 | yes | yes | yes | – | – | – | 12 | 2 | user done |
| anas_tree_file | 1 | yes | yes | yes | – | – | – | 13 | 2 | user done |
| frogs_unphased | 1 | yes | yes | yes | – | – | – | 12 | 2 | user done |
| frogs_upgrade | 1 | yes | yes | yes | – | – | cleandata, usedata, finetune | 14 | 2 | user done |
| off_topic | 1 | yes | – | – | – | – | – | 2 | 1 | user done |
| tiny_bpp_format | 1 | yes | yes | yes | – | – | – | 9 | 2 | user done |
| tiny_fix_broken | 1 | yes | yes | yes | – | – | nloci | 9 | 2 | user done |

## Reading this baseline

Written by hand on 2026-10-03; `report` does not produce this section.

**What ran.** Claude Code 2.1.288 in headless mode with its `opus` model alias
as the assistant and its `haiku` alias as the simulated user, on a claude.ai
subscription login, macOS arm64, one trial per scenario. The cost line is what
the tokens would have cost at API prices; nothing was billed per token.

**It is one trial per scenario.** 13 of 13 says the server and a frontier
model get a simulated novice to a correct, tested control file on these
scenarios. It does not say how often. Run `--trials 3` or more before
comparing two versions of the server or two models.

**Two scenarios were wrong, and were corrected before their final runs.** Both
first attempts are failures of the scenario, not of the assistant:

- `anas_unphased` (replaced by `frogs_unphased`). The scenario told the user
  to say the Anastrepha sequences were unphased diploid genotypes with
  ambiguity codes. They have none. The assistant searched the files, found
  that, quoted the manual on what `phase = 1` would then do, recommended
  `phase = 0`, and the user agreed. The expected `phase = 1 1 1 1 1` was the
  wrong answer for that data. The replacement uses BPP's frogs example, which
  really is unphased.
- `tiny_fix_broken`. After fixing the two real errors, the assistant pointed
  out that `burnin = 10` is below the manual's minimum for `finetune = 1` and
  offered to lengthen the chain; the simulated user accepted, against its
  instruction to keep the rest of the file. The scenario now tells the user to
  decline, and on the rerun the assistant made only the two fixes.

Both first attempts scored a fail under the scenario as then written. So the
honest summary of the first pass is 11 passes, 2 scenario defects found, and
(separately) 2 conversations lost to a bug in the harness's parsing of Claude
Code's output, which was fixed and those two rerun.

**What the transcripts show beyond the scores.**

- No control file was written or edited by hand in any conversation, although
  Write and Edit were available.
- `check_environment` was the first tool call in all 12 conversations that
  needed it.
- `frogs_upgrade`: the assistant noticed that `bpp-lint --fix` turns `outfile`
  and `mcmcfile` into two `jobname` lines, asked, and then rebuilt the file
  with `read_species_tree` and `make_control_file` rather than leave the
  duplicate. In doing so it carried `cleandata`, `usedata` and `finetune`
  over through `extra` without looking them up (the "set, not looked up"
  entry). There is no tool to remove a keyword, which is why it rebuilt.
- `tiny_fix_broken`: `nloci` was set from the data-check message without a
  manual lookup.
- `anas_chain_settings`: the one "stated before any tool showed it" case is
  the assistant repeating the user's own numbers back as `burnin = 20000`
  and so on.
- **Privacy.** In 5 of 13 conversations the assistant used Claude Code's own
  Read or Grep on the sequence files (for example to count ambiguity codes or
  look at the first lines of a locus). Those tools are outside this server,
  so its redaction does not apply to them. The README's privacy note says
  this; the evaluation confirms it happens in practice.
- The simulated user sometimes misbehaves: in the first `anas_unphased`
  attempt it invented a Newick string with a three-way split that
  contradicted its own description. The assistant caught the conflict and
  asked.
