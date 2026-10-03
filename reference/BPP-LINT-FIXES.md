# bpp-lint: fixes for data-consistency gaps and the A10/A11 template

Instructions for Claude Code. Put this file in the root of the `bpp-lint`
repository and read all of it before you change any code.

## Why this work matters

bpp-lint is going to be the validation layer behind an MCP server. Frontier
models will use that server to guide novice users through BPP setup, and the
agent treats `bpp-lint --json` reporting `status == "valid"` as its signal to
stop. Every defect below breaks that contract in the same way: **bpp-lint
reports the file as valid, and then BPP 4.8.7 refuses to run it.**

All of these cases were reproduced against bpp-lint 0.3.5 and BPP v4.8.7. The
fixtures and the exact BPP messages are given below.

## Ground truth

**BPP's own parser is the authority.** When BPP and this document disagree,
BPP wins.

- Read `src/cfile.c` in the BPP repo to see what BPP accepts. Cite the line
  numbers in code comments, following the existing convention (for example
  `Source: bpp-4.8.7 cfile.c:2878-2879`).
- If a `bpp` binary is on `PATH`, use it as an oracle: `bpp --cfile FILE` on
  each fixture must give the outcome listed in the table below.
- Don't add any check that BPP itself doesn't enforce at **error** severity.
  Report behaviour that is harmless in BPP as a warning or info.

## Repository conventions

These come from the existing code. Keep to them.

- Value grammars are **generated**, never hand-edited.
  - The source of truth is `spec/bpp-syntax.json`.
  - `spec/gen_keywords_c.py` produces `src/keywords_gen.c`.
  - Run `make gen` to regenerate. `make check-gen` (part of `make test`) fails
    if the two drift apart.
- Cross-keyword rules live in `src/lint.c`, in the rule table near line 1012
  (`{ "BPP120", rule_... }`).
- Every new code needs an entry in `src/codes.c`, with a short summary and a
  long `--explain` text.
- The `--json` contract is locked by `tests/run.sh`, which the bpp-agent loop
  depends on. You may add fields to the JSON. Don't rename or remove existing
  ones.
- Exit codes stay as they are:
  - `0`: no errors.
  - `1`: at least one error.
  - `2`: invocation error.
- C11, no new dependencies. `make debug` must stay clean under ASan/UBSan.

## Test fixtures

Create `tests/fixtures/data/` containing these two files.

`tiny.txt`:
```
6 20
^a1 ACGTACGTACGTACGTACGT
^a2 ACGTACGTACGTACGTACGA
^b1 ACGTACGAACGTACGTACGT
^b2 ACGTACGAACGTACGTACCT
^c1 ACGAACGAACGTTCGTACGT
^c2 ACGAACGAACGTTCGTACGG

6 20
^a1 TTGCATGCATGCATGCATGC
^a2 TTGCATGCATGCATGCATGA
^b1 TTGCATGGATGCATGCATGC
^b2 TTGCATGGATGCATGCATCC
^c1 TTGGATGGATGCAAGCATGC
^c2 TTGGATGGATGCAAGCATGG
```

`tiny.imap`:
```
a1 A
a2 A
b1 B
b2 B
c1 C
c2 C
```

Baseline control file `ok.ctl`. It lints clean, and BPP runs it.

```
seed = 1
seqfile = tiny.txt
Imapfile = tiny.imap
jobname = out
speciesdelimitation = 0
speciestree = 0
species&tree = 3  A  B  C
                  2  2  2
                  ((A,B),C);
usedata = 1
nloci = 2
cleandata = 0
thetaprior = invgamma 3 0.01
tauprior = invgamma 3 0.02
finetune = 1
burnin = 10
sampfreq = 1
nsample = 20
```

Each case below is `ok.ctl` with one change. All paths are relative to the
fixture directory, and BPP is run from that directory.

| # | Fixture | Change to `ok.ctl` | lint 0.3.5 | BPP 4.8.7 |
|---|---|---|---|---|
| 1 | `sd_bare.ctl` | `speciesdelimitation = 1` + `speciesmodelprior = 1` | exit 0 | **fatal**: `Erroneous format of option speciesdelimitation = 1` |
| 2 | `sd_short.ctl` | `speciesdelimitation = 1 0` (+ smp) | exit 0 | **fatal**: `Erroneous format …` |
| 3 | `sd_alg1_short.ctl` | `speciesdelimitation = 1 1 2` (+ smp) | exit 0 | **fatal**: `Erroneous format …` |
| 4 | `sd_ok.ctl` | `speciesdelimitation = 1 0 2` (+ smp) | exit 0 | runs (control) |
| 5 | `nofile.ctl` | `seqfile = missing.txt` | exit 0 | **fatal**: `Unable to open file (missing.txt)` |
| 6 | `nloci.ctl` | `nloci = 3` | exit 0 | **fatal**: `Expected 3 loci but found only 2` |
| 7 | `imap_missing_tag.ctl` | Imap without the `a1` line | exit 0 | **fatal**: `Cannot find a mapping to species for tag a1 inside file …` |
| 8 | `imap_extra_sp.ctl` | Imap maps `c2` to `D` | exit 0 | **fatal**: `Cannot find node with population label D` |
| 9 | `tree_sp_noimap.ctl` | tree species `C` renamed to `Cx` in both the header and the Newick | exit 0 | **fatal**: `Cannot find node with population label C` |
| 10 | `phase_ones.ctl` | `phase = 1 1` (3 species) | exit 0 | **fatal**: `Number of digits in 'phase' does not match number of species` |
| 11 | `phase_zeros.ctl` | `phase = 0 0` (3 species) | exit 0 | runs: BPP discards an all-zero `phase` before counting |
| 12 | `counts.ctl` | counts line `2  2  9` | exit 0 | runs: inference ignores these counts; only `--simulate` uses them |
| 13 | `sub/rel.ctl` | in `sub/`, `seqfile = ../tiny.txt`, `Imapfile = ../tiny.imap`; run from the fixture dir as `bpp --cfile sub/rel.ctl` | exit 0, and `--check-priors` also exit 0 | **fatal**: `Unable to open file (../tiny.txt)` |

## Fix 1: `speciesdelimitation` grammar (cases 1–4)

**Cause.** In `spec/bpp-syntax.json`, `speciesdelimitation` has grammar
`b [d f f]`. The generator turns that into four independently optional slots
(`src/keywords_gen.c`, `slots_speciesdelimitation`). As a result, `1`, `1 0`
and `1 1 2` all pass.

BPP's rules (`cfile.c`, `parse_speciesdelimitation`, around line 668):

- **`0`**: nothing may follow.
- **`1 0 ε`**: exactly one float after the algorithm number.
- **`1 1 α m`**: exactly two floats after the algorithm number.
- **Algorithm number**: must be 0 or 1.

**What to do:**

1. Give `speciesdelimitation` a value check that depends on the first token.
   The generic slot grammar can't express that the number of arguments
   depends on an earlier value. You have two options:
   - Preferred: extend the spec grammar and `gen_keywords_c.py` so that later
     slots can depend on an earlier value. This also fixes any other keyword
     with the same shape, so search the spec for similar `[...]` groups first.
   - Fallback: add a dedicated rule in `lint.c` and note in the spec entry's
     `notes` that the arity is checked there.
2. Report wrong argument counts with the existing **BPP017** code, and a bad
   algorithm number with **BPP019**.
   - Suggest `1 0 2` as the fix, since the manual says reasonable values of ε
     are 1, 2 or 5.
   - Mark it as auto-fixable only when the value is exactly `1`.
3. **The template bug.** In `src/main.c`, `emit_template()` (around line 567)
   writes a bare `speciesdelimitation = 1` for A10 and A11. Write `1 0 2`
   instead, and allow an override with `--speciesdelimitation`.

**Acceptance:**
- Cases 1–3 fail lint with BPP017 or BPP019. Case 4 passes.
- `bpp-lint --template A10` and `--template A11` produce files that pass lint
  and that BPP accepts.

## Fix 2: check the control file against the data files (cases 5–10, 13)

**Cause.** Normal linting never opens `seqfile` or `imapfile`. The data
loaders already exist:

- `bpp_alignment_load` in `src/seqfile.h`.
- `bpp_imap_load` and `bpp_imap_species_list` in `src/imap.h`.
- `resolve_data_paths` in `src/main.c`. It is used today only by
  `--check-priors` and `--suggest-priors`.

**What to do.** Add a data-consistency pass that runs by default whenever
`seqfile` and/or `imapfile` are set. Add `--no-data-checks` to turn it off.
Use the free **15x** block for its codes:

| Code | Severity | Condition | Matches BPP |
|---|---|---|---|
| BPP150 | error | `seqfile` or `imapfile` can't be opened | case 5 |
| BPP151 | warning | a relative data path resolves differently from the control file's directory than from the current working directory (see below) | case 13 |
| BPP152 | error | `nloci` is greater than the number of loci in `seqfile`. If it is smaller, report info: BPP uses only the first `nloci` loci. Confirm that in cfile.c / msa loading before choosing the severity | case 6 |
| BPP153 | error | a sequence label in `seqfile` (the `^name` tag) has no Imap entry. List the first few missing tags and the total count | case 7 |
| BPP154 | error | the Imap species set doesn't match the `species&tree` names. Report both directions: Imap species not in the tree, and tree species with no Imap individuals | cases 8, 9 |
| BPP155 | error if `phase` contains any `1`; warning if all `0` | the number of `phase` digits ≠ number of species. In the all-zero case BPP ignores the line, so the warning should say so | cases 10, 11 |
| BPP156 | info (inference) / error (`--simulate`) | the per-species counts in `species&tree` don't match the number of Imap individuals per species. Inference ignores these counts; simulation uses them | case 12 |

**Path resolution (BPP151).** BPP opens `seqfile` and `Imapfile` relative to
the **current working directory**. bpp-lint's `resolve_data_paths` resolves
them relative to the **control file's directory**.

Keep the control-file-directory behaviour, because it is the friendlier
default for editors. But when the two resolutions point to different places,
warn which one BPP will actually use. If the file exists in only one of those
locations, say which.

With `--json`, include the resolved absolute paths in a new top-level `data`
object, for example:

```json
"data": {
  "seqfile": "/abs/tiny.txt",
  "imapfile": "/abs/tiny.imap",
  "n_loci": 2,
  "n_sequences": 6,
  "species": ["A", "B", "C"]
}
```

The MCP server needs these values.

**Implementation notes:**

- Load the data once and pass it to both the new checks and `--check-priors`.
- Don't load the alignment twice.
- Large seqfiles exist, so read loci once and stream them if you can.
- Imap matching in BPP is case-sensitive. Mirror whatever BPP actually does,
  and check how BPP compares `^tag` labels to Imap individuals.
- Respect `usedata = 0`: BPP may not read the seqfile at all in that case.
  Check cfile.c and skip the seqfile checks if it doesn't.

**Acceptance:**
- Cases 5–10 and 13 produce the code, severity and exit status shown above.
- `ok.ctl` stays clean.
- The existing examples (`examples/*.ctl`) give the same results as before,
  apart from expected new BPP150 errors where their data files aren't in the
  repo. If that happens, have the existing tests pass `--no-data-checks`, and
  don't weaken the new check.

## Fix 3: tests and documentation

- **Tests.** Add the fixtures and one test per case to `tests/run.sh`. Each
  test should assert:
  - the exit code,
  - `status`,
  - the specific diagnostic code in `--json`.
- **Optional oracle check.** If `bpp` is on `PATH`, add a check that runs
  `bpp --cfile` on every fixture lint calls valid and asserts that BPP gets
  past parsing. Look for its usual startup output, and treat a non-zero exit
  with an `Erroneous format` / `Unable to open` / `Cannot find` message as a
  failure. Skip the check quietly when `bpp` isn't available.
- **README.** Add the 15x codes to the code table and document
  `--no-data-checks`.
- **`--explain`.** Each new code's explanation should quote the BPP error
  message it prevents, so users can search for it.

## Done when

- `make`, `make debug` and `make test` all pass with no warnings.
- `make check-gen` is clean.
- Every fixture in the table lints with the expected outcome. Where `bpp` is
  available, no file that lint calls valid is rejected by BPP's parser.
- `bpp-lint --template A10|A11 ... --suggest-priors --nloci N` produces a file
  that lints valid and that BPP runs.
- The `--json` schema has only additions, and `tests/run.sh` covers them.

## Out of scope

- Changes to BPP itself.
- Polishing priors heuristics.
- Changes to bpp-seqs and bpp-tree. Separate note: the bpp-seqs README
  documents a `recommended_phase` JSON field that isn't emitted for FASTA
  input. Handle that in that repo.
