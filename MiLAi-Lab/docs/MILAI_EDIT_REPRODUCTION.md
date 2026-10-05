# MiLAi-Edit reproduction instructions

Prepared during execution; this file does not claim completion of unrun stages.
See [progress](MILAI_EDIT_PROGRESS.md), [analysis](MILAI_EDIT_ANALYSIS_SPEC.md) and
the [original plan](MILAI_EDIT_LITERATURE_AND_EXPERIMENT_PLAN.md). The baseline is
PR82 `fc1c6c93f6e75f8775e2d5195bb35e6e8ce0e0b1`. Preserve all older worktrees,
historical cohorts and their original results. New experiments use separate roots.

## Local environment and source material

The active checkout is `MiLAi-worktrees/development-milai-edit/MiLAi-Lab`.
The installed interpreter is
`/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python`; it is an older editable
environment, so `PYTHONPATH=src` is required from the active Lab directory.
Python is 3.11.13. Recorded relevant packages are langmem 0.0.30, langgraph 1.1.10,
langchain-core 1.6.5, httpx 0.28.1, openai 3.19.2, transformers 4.57.6,
tokenizers 0.22.2, NumPy 2.4.6, pytest 8.4.2, Ruff 0.16.5 and mypy 1.20.2.
Use the repository lock/dependency groups for a separate environment; these actual
installed versions describe this execution, not a guarantee for other environments.

Original data and author sources are outside Git at
`/cra/memory/mx_memory/reference-sources/milai-edit/`:

| Resource | Actual location/version |
| --- | --- |
| HaluMem-Medium | `data/HaluMem-Medium.jsonl`; 20 users, 14948 reference memory points, 3467 questions |
| HaluMem scorer | `HaluMem/`, author commit `718f16ff0c83413b1c86fa83fc13cc1a639871f9` |
| LongMemEval-S-cleaned | `data/longmemeval_s_cleaned.json`; 500 questions |
| LongMemEval scorer | `LongMemEval/`, author commit `9e0b455f4ef0e2ab8f2e582289761153549043fc` |
| A-MEM original implementation | author commit `0c8039f28fdcc08189a23c07a3437d9d2482f9c2`, `memory_layer.py` |
| Method papers | `papers/`, nine local readable papers and their retrieval manifest |

The tracked manifests contain selection metadata and evaluator annotations, not
copies of the corpora. HaluMem's CC-BY-NC-ND-4.0 resource and other upstream
licenses remain attached to their originals; do not bundle raw corpora into this
repository. This execution adapts actual author scorer functions, not rewritten
local scoring approximations. A-MEM retains the original author class bodies;
local provider/embedding callbacks and the NumPy cosine substitution are declared
in the analysis specification.

Generation uses the existing `http://127.0.0.1:7862/v1` Qwen3.6-35B-A3B-FP8
service and local tokenizer `/cra/qwen36-35B`; its context is 65536 tokens.
External embedding uses `http://127.0.0.1:7861/v1` bge-m3 and tokenizer
`/data/models/embed/tokenizer.json`, with 8192-token input capacity. No second
generation family is connected. Generation, source review and final judgments
are therefore not independent-family evidence.

The continuous ledger is
`/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`.
One root-owned serial HTTP lease protects cooperating generation/embedding calls.
Do not start a second suite while the first is running. Requests persist before
dispatch and responses before parsing. A request without a confirmed response is
UNKNOWN; restarting a process does not authorize repeating it. Known first format,
truncation or structural failures remain in their original denominators.

## Checks before actual runs

From the active Lab directory:

```bash
MILAI_EDIT_PY=/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python
export PYTHONPATH=src
"$MILAI_EDIT_PY" -m ruff check src tests tools
"$MILAI_EDIT_PY" -m mypy
"$MILAI_EDIT_PY" -m milai_lab.boundary
"$MILAI_EDIT_PY" -m milai_lab.tools_boundary
"$MILAI_EDIT_PY" tools/check_verification_matrix.py
"$MILAI_EDIT_PY" -m pytest -q tests/unit/test_edit_benchmark_wiring.py tests/unit/test_edit_results.py tests/unit/test_edit_external.py tests/unit/test_edit_mechanism.py
```

Engineering Store/Host checks and the wider current-memory audit are recorded
separately in progress. The four archived correction-protocol modules use their
exact pre-Edit source via `tools/prepare_sealed_regression.py`; their historical
digest assertions are not imported into the current normal-path contract. Missing
optional SDK environments and unavailable local artifacts are skips, not passes.

## Experiment order and commands

E0 is completed wiring evidence. E1 is currently the admitted four-arm development
run, not a completed comparison. Its selected users are fixed by
`data/manifests/milai-edit-source-split-v1.json`; all 277 sessions are processed,
with timestamp ordering and preserved original ordinals. The main Writer sees only
observed dialogue and its own prior state, never persona, gold, update flags or
future QA. The four arms share 4096 source tokens, retrieval limit 10 and a common
Reader. Their first failures are retained without an extra semantic repair.

```bash
"$MILAI_EDIT_PY" tools/run_edit_suite.py configs/milai-edit-e1-dev-v1.json artifacts/milai-edit/e1-dev-v1 --benchmark halumem
"$MILAI_EDIT_PY" tools/summarize_edit_benchmarks.py --root artifacts/milai-edit/e1-dev-v1 --output artifacts/milai-edit/e1-dev-v1/paired-results.json --benchmark halumem
```

While this actual run is still live, the first command above is a documented
entry point, not an instruction to dispatch another process. Summary refuses to
infer paired effects from incomplete arms. It can also save an explicitly partial
operational report while the suite is live, using a separate output such as
`artifacts/milai-edit/e1-dev-v1/operational-progress.json`. This report distinguishes
prepared source characters, recorded Writer requests, confirmed responses, first
failures, structural rejections, commits, pure no-change and confirmation by replay.
Its live counts do not select a candidate or substitute for the final paired table.
The source-review manifest was fixed
before native mechanism judgments. The lexical selection's raw source file is
ignored; it can be recreated with `tools/select_edit_updates.py`, but keep the
original selected IDs and reviewed annotations rather than choosing a new slice
after inspecting outcomes.

After all E1 arms finish, run evaluator-only E2 and native continuous drift:

```bash
"$MILAI_EDIT_PY" tools/run_edit_mechanism.py --config configs/milai-edit-e2-native-v1.json --suite artifacts/milai-edit/e1-dev-v1 --selection artifacts/milai-edit/selection/native-updates-v1.json --review data/manifests/milai-edit-native-source-review-v1.json --output artifacts/milai-edit/e2-native-v1
"$MILAI_EDIT_PY" tools/run_edit_drift.py --config configs/milai-edit-e4-native-drift-v1.json --suite artifacts/milai-edit/e1-dev-v1 --output artifacts/milai-edit/e4-native-drift-v1
```

Fix the final candidate, method/common configuration and source version after
development. Record that selection as ordinary `candidate-freeze.json` metadata
with `status=FROZEN_CANDIDATE`, `method_version`, `config_version` and the selected
arm. This is the plan's candidate freeze, not a new semantic approval platform.
If generic development repairs require another version, make a separate complete
paired cohort and preserve v1; do not change a running arm or tune on reserved users.

E3 reserved-user configuration contains all sixteen reserved HaluMem users and
B1/B2/M. Root must admit it only after candidate freeze and before inspecting their
semantic contents. The external descriptive configuration selects 28 LongMemEval
questions, all six categories and four available abstention categories, consuming
1354 complete case histories. The overlap graph is one component, so it is not
450 independent unseen sources. Prepared configuration files are not run evidence.

The selected LongMemEval history has two repeated original session IDs at different
dates. All external arms capture every occurrence with `history-occurrence-v1`
source-session keys, recording the original ID/date in `source-occurrence.json`.
They retain every original role, body and date. Source grouping still uses original
session IDs, so the overlap component remains one. The metadata-only chronology
report is `artifacts/milai-edit/selection/longmem-chronology-preflight-v1.json`.
An actual-SDK, scripted-empty-Writer preflight verifies the four repeated observations
without HTTP or semantic formation; it is not external model evidence.

```bash
"$MILAI_EDIT_PY" tools/run_edit_suite.py configs/milai-edit-e3-reserved-v1.json artifacts/milai-edit/e3-reserved-v1 --benchmark halumem
"$MILAI_EDIT_PY" tools/run_edit_external.py --config configs/milai-edit-e3-external-v1.json --output artifacts/milai-edit/e3-external-v1
"$MILAI_EDIT_PY" tools/run_edit_answer_audit.py --config configs/milai-edit-e3-answer-audit-v1.json --suite artifacts/milai-edit/e3-external-v1 --manifest data/manifests/milai-edit-external-subset-v1.json --output artifacts/milai-edit/e3-answer-audit-v1
```

The ten-question answer audit uses unchanged original hypotheses and complete raw
history, preserving context-unavailable judgments. It does not regenerate answers
or replace official accuracy. E4's controlled supplement has three authored story
clusters and ten histories, including equivalent wording/language and one explicitly
independent order swap. It is separate from official and natural-user evidence:

```bash
"$MILAI_EDIT_PY" tools/run_edit_sensitivity.py --config configs/milai-edit-e4-controlled-v1.json --suite artifacts/milai-edit/e1-dev-v1 --candidate artifacts/milai-edit/candidate-freeze.json --manifest data/manifests/milai-edit-controlled-dialogues-v1.json --output artifacts/milai-edit/e4-controlled-v1
```

E5 uses the same final candidate through `tools/run_functional.py`, fresh banks and
the historical public L1/L2/L3/old-L4 inputs. New functional stories are authored
after candidate freeze. `configs/milai-edit-e5-functional-v1.json` is an unadmitted
M integration configuration; `configs/milai-edit-e5-functional-b1-v1.json` is the
matching B1 configuration. Both were validated with the actual local tokenizer and
zero HTTP. Neither predetermines the final candidate; if B0 or B2 is selected,
complete its matching functional adaptation before actual E5 admission. The
availability of an adapter is not a selection criterion. Before actual E5 admission,
copy the admitted source into its ignored run root, as done for E1; ordinary
configuration/version metadata does not itself preserve those source bodies.
The main functional configuration retains r52 sampling/material/call/queue bounds
and disables extra semantic support review. Any separate review ablation must
report original and final proposal errors and its additional generation usage.
Mechanical Host tests do not substitute for these actual model regressions.

The five sealed r52 input sets have been copied to
`artifacts/milai-edit/e5-inputs/historical-r52-v1/`: L1 24 cases/48 messages,
L2 12/26, L3 formation 57/57, L3 reading 30/30 and old L4 12/31. Their 145 raw
tool-source events and 1064 retrieval candidates are preserved in the original
order. Actual verification compared every message, owner, workflow, initial world,
source body/role/ordinary identity, retrieval range/score and offline control with
its sealed original. Only 3337 retired source/candidate digest metadata fields were
omitted. These are input copies, with no semantic memory initialization, candidate
admission or newly authored story. Recreate them in a new directory with:

```bash
"$MILAI_EDIT_PY" tools/prepare_edit_functional_inputs.py --legacy-root /cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v13-5/MiLAi-Lab/artifacts/v13-5 --output artifacts/milai-edit/e5-inputs/historical-r52-v1
```

The copier refuses an existing output directory. Keep its manifest and each original
sealed input; do not reinterpret these historical inputs as new unseen samples.

Use the existing `tools/v13_5_evaluate.py` for read-only mechanical review packs.

The offline public-input preflight report is
`artifacts/milai-edit/e5-inputs/preflight-current-v2.json`, with its runner retained
beside it. It checks these same 135 cases independently under M and B1: exact
fixture freeze, actual Source import and candidate-range binding, and first-message
ordinary material under the actual 8192-token bound. Later public messages remain
in the input freeze. Temporary banks were removed and HTTP was prohibited; there
are no semantic memory records or functional acceptance verdicts. The first v1
preflight/log retain a script namespace error; they are not model failure evidence.
Reproduction uses fresh output names because the scripts refuse existing reports.

The functional evaluator recognizes `functional_run_inputs_v2` and discovers persisted bank/message
IDs, source revisions and response IDs. It does not recompute their legacy opaque
identifiers or require old source/config/body digests. Source ranges and actual
recorded HTTP/output linkage are checked; semantic acceptance remains unreviewed
until the actual answer, scope and application effects are assessed. Its historical
digest mode remains available for old sealed queues. For example:

```bash
"$MILAI_EDIT_PY" tools/v13_5_evaluate.py --root artifacts/milai-edit/e5-l2-final --output artifacts/milai-edit/e5-l2-final-review --cohort L2
```

The example roots are not yet admitted. L1 also requires its original unchanged
public normal24 fixture. The default functional queue stops later messages in a
bank after an incomplete prior message. Inspect that actual failure and effect
before using `step` for the next planned message; an ordinary semantic failure is
not a reason to remove the remaining requested task from the denominator. Unknown
effects need their existing recovery/query path, and actual corruption stops the
affected operation. Do not silently repeat a lost mutation or present NOT_RUN as
completed evidence.

## Required final outputs

Retain requests, responses, delivered source ranges, proposals, actual receipts,
pre/post states, complete hypotheses, original official scores, first failures,
all/empty/unscored/valid denominators and usage in ignored experiment roots.
Deliver separate public-task, semantic-mechanism, external/sensitivity and functional
tables. Paired HaluMem uncertainty resamples original users with equal user weight;
variant histories and repeated sessions are dependent. Report the single-family
limit and every unscored interval. Finish the reproduction and contribution draft
with actual terminal identities and findings before marking the full plan complete.
Product readiness is a separate decision; r52 PARTIAL/NO_GO stays historical.
