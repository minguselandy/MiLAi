# MiLAi-Edit E0 wiring

Executed 2026-10-04 from PR82 `fc1c6c9` in the isolated MiLAi-Edit worktree.
This is a wiring result, not a comparison of editing methods or Product acceptance.

The complete HaluMem-Medium and LongMemEval-S-cleaned files were downloaded into
`/cra/memory/mx_memory/reference-sources/milai-edit/data`. Author scoring versions
are MemTensor/HaluMem `718f16f` and xiaowu0162/LongMemEval `9e0b455`.
The adapter executes selected author function bodies and prompt literals unchanged,
with serial accounted HTTP replacing their client/process-pool transport.
The actual Writer, Reader and Judge model is Qwen3.6-35B-A3B-FP8 at port7862,
temperature0, thinking disabled, max output8192, loaded local tokenizer and
65536 context. This Judge overlaps the Writer model; it is not independent.

Writer receives only chronological observed dialogue and its own retrieved state.
It never receives persona metadata, reference memories, update labels, original
gold memories, answers or future questions. LongMemEval `has_answer` is stripped.
Each user/question has an isolated existing MemoryService/SQLite bank. The E0
method rewrites affected ordinary text records once; no semantic reviewer is added.
Reference-guided HaluMem update retrieval is a separate read-only diagnostic.

| Dataset | Actual scope | Result |
| --- | --- | --- |
| HaluMem-Medium | first complete session of each of two preselected development users | 30 integrity, 2 accuracy and 6 QA records scored; zero Judge failures |
| LongMemEval-S-cleaned | temporal-reasoning `6613b389`, all41 history sessions | official label false |
| LongMemEval-S-cleaned | knowledge-update `852ce960`, all39 history sessions | official label true |

HaluMem integrity was29/30 at the author's full-score threshold. Both extracted
records received accuracy1/2, and QA was4 Correct /2 Hallucination. There were
zero native update opportunities and zero interference reference points in this
prefix. The unchanged author aggregate encounters `ZeroDivisionError` at an absent
prefix denominator. Partial author metrics and the error are both preserved;
missing aggregate metrics are not replaced by invented official values. Per-item
formation, accuracy and QA scores remain available. No update effect is claimed.

All80 LongMemEval sessions were ingested, with no history truncation or gold
initialization. The exported official-format JSONL has `question_id` and
`hypothesis`. The author's exact `yes`-substring label rule is retained, including
its limitations. Full-answer auditing belongs to later supplementary evaluation.

Continuous accounting increased by130 generation requests and496149 known
generation tokens, with zero newly unknown usage. The original ledger remains
`MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`; it was not reset. Ignored local
evidence is `artifacts/milai-edit/e0-wiring-v1`: actual configuration, per-request
inputs/responses/failures, immutable proposals/receipts, per-session evaluation
checkpoints, hypotheses, author results and start/end accounting. Dataset contents,
SQLite banks and raw outputs are not redistributed in Git.

Before HTTP, six synthetic engineering tests verified reference exclusion,
complete chronological history, transitive source grouping, author-function
loading, real Store formation/revision/reopen and charged incomplete response
replay. Ruff, strict type checking of the new modules and both package boundaries
passed. This satisfies P0's minimum wiring deliverable. P1-P5/E1-E5 remain required.
