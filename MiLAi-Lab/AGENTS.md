# MiLAi Lab agent instructions

## Scope

This repository owns experiments, evaluation contracts, benchmark adapters, scoring,
analysis, and historical research source. It does not own MiLAi product behavior or
canonical memory state.

## Hard boundaries

1. `src/milai_lab` must never import `milai`, `milai_client`, `evals`, `scripts`, or any
   legacy source module.
2. A `PRODUCT_BLACK_BOX` arm uses only interfaces pinned by `product.lock.json`.
3. A `PRODUCT_TESTKIT` arm may use only a separately published public testkit or
   read-only trace contract. Private product helpers remain forbidden.
4. `RESEARCH_PROTOTYPE` and `SIMULATION` results must not be described as product
   behavior.
5. Benchmark corpora, model weights, venvs, caches, raw Provider transcripts, and run
   artifacts stay outside Git. Git stores manifests and compact terminal results.
6. Archived code is historical evidence, not an active dependency. Do not add archive
   paths to `sys.path`.
7. The Lab never writes canonical product tables directly. Stateful product experiments
   use isolated instances through published interfaces.
8. Preserve failed experimental evidence, but prefer one compact failure record over
   duplicating environments or source trees per attempt.

## Efficient development

- Start with the smallest falsifiable slice, then scale only after execution validity.
- Fail a case, not the whole development program, when a local repair is safe and
  generalizable.
- Diagnose infrastructure failures separately from semantic misses.
- Do not add case IDs, gold terms, benchmark-specific synonyms, or post-outcome routing.
- Use parallel execution only within declared service and database capacity.
- Keep product and research claims tied to the declared `ExperimentArmKind`.

## Required checks

The user-authorized [Goal v12.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v12.0_20260925.md)
is `COMPLETE_WITH_SCOPED_ENGINEERING_VALIDATION`; preserve the
[results](docs/CONTEXTUAL_USER_MEMORY_V12_RESULTS_20260925.md). Final R4 mapping is
`f39d8170f168a56d21057a3079fdaed21a5cb6d32e852687544dd740df8955d0`.
Implementation covers exact resident visibility, actionable revisions, failed-write repair or
reasoned abandonment, unchanged-format snapshot recovery and compact shared tools.
R1 corrected both original amounts and consumed the current amount, then maintenance
truncated; R2 zero-model preparation failed on tuple/list binding spans. R3 repaired the
snapshot representation and completed natural/controlled maintenance without repeating
business actions. R3 also preserved a zero-write semantic miss; R4's single generic finish
purpose clarification passed that same isolated native message and updated the original card.
Do not relabel mixed v11 prefixes and R1/R3/R4 suffixes as a final-source full arc, unseen
validation or general reliability. Preserve all 38 generations / 323992 generation tokens /
2383 embedding tokens, unknown=0, Judge=0, including earlier failures. Final same-schema
shared tool text is 4080 -> 1915 tokens; this does not prove total task savings. Ordinary and
thinking=false remain the delivered default; no Attention comparison or sidecar change.
No new compatibility format, Product API/schema/permission/Canonical change or package move.
Do not restart completed diagnostics or broaden tests merely for publication. Existing user
authorization for Luna high publication persists. New development, if authorized, retains
one Sol xhigh core owner, one real model controller/concurrency 1, narrow checks and
continuous accounting; no standing reviewer. Raw transcripts, databases and models stay ignored.

The user explicitly authorized execution of [Goal v11.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v11.0_20260925.md)
and its [sparse-basis design](docs/MILA_CONTEXTUAL_USER_MEMORY_V11_SPARSE_BASIS_DESIGN_20260925.md).
The scoped Goal is `COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`; preserve the
[results](docs/CONTEXTUAL_USER_MEMORY_V11_RESULTS_20260925.md). All six R2 trajectories use
mapping `2a95dcd0fde0e90a4eff053b5875d0f6d07a3ec61961fd158201c312102d1cf4`: A2 scored 5/5 on
both instances; arc1 A0/A1 interrupted; arc2 Notes 5/5 and A1 4/5. No automatic gap query or
version notice occurred; ordinary stays default. R3 fixes Host read-cache invalidation,
search outcome metrics and error-code projection under mapping
`666344907d0ef59f171431ebc7e572b92bf68fae2378f82fc32dc8df4fff7c12`, with 59 related tests and
static checks passing, no new model calls. Do not represent R2 as R3 unseen validation.
Keep exposed-arc failures, all F interruptions and continuous v11 charges of 238 generations /
2453097 generation tokens / 14274 embedding tokens, unknown=0, Judge=0. Do not restart
completed arms, substitute seeds, expand the benchmark or promote an unobserved mechanism.
Keep ordinary default, v10 evidence sealed and native scoring unchanged.

The user explicitly authorized execution of [Goal v10.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v10.0_20260925.md)
and its detailed design. Planning-only wording is historical. Follow A → B–D implementation
and narrow checks → E frozen original small selection → F staged real comparisons. Keep one
Sol xhigh owner for the core/Host/session integration; Luna high handles official downloads
and user-authorized publication. No standing review agent. One model controller, concurrency 1.
StateMemBench availability is a separate evidence question; do not invent or rename data.
Keep ordinary default, old State/H1–H6 frozen, Lab-only scope, existing identity/permission/
lifecycle/recovery guarantees, and continuous new v10 accounting that cites sealed v9 costs.
No full suite or benchmark, no Product migration. No fresh model run before development freeze.
Preserve [R1](docs/CONTEXTUAL_USER_MEMORY_V10_RESULTS_20260925.md) as a historical failed
comparison: notes 5/5, basis 3/5, basis all null, 51 generations / 452656 generation
tokens / 3955 embedding tokens. [R2](docs/CONTEXTUAL_USER_MEMORY_V10_R2_RESULTS_20260925.md)
on the same exposed original arc scored notes 5/5, basis 4/5, both 7/7 Host complete;
basis established one exact-adoption → new-observation → recheck → committed-revision chain,
but no automatic version notice. Basis cost more. The scoped Goal is
`COMPLETE_WITH_NEGATIVE_OR_UNCERTAIN_EFFECT`; ordinary remains default. Continuous v10
charges are 122 generations / 1216124 generation tokens / 8148 embedding tokens,
unknown=0, Judge=0. E2/E3/E4 and StateMemBench remain NOT_RUN. Do not force a State ritual,
alter tasks or rerun to replace negative evidence. Keep all raw artifacts ignored.

[Goal v9.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v9.0_20260925.md)
completed A–E and scoped final continuous validation. Preserve its
[results](docs/CONTEXTUAL_USER_MEMORY_V9_RESULTS_20260925.md), first failed attempt,
final source identity and all charges: 119 generations / 966332 generation tokens /
4358 embedding tokens, unknown=0, Judge=0. Final original MERIT 5/5 (dependent 2/2,
7/7 Host turns) and document 4/4 use the same frozen implementation from initial states;
local full/delta branches both completed with no new business action. Delta was cheaper
locally, but the full continuous trajectory was more expensive than v8. Do not claim
general reliability, State benefit or overall efficiency. Do not expand the benchmark or
rerun merely to clear truncation counts. Keep raw model/runtime artifacts ignored.
The user explicitly authorized Luna high to commit and push all development to GitHub;
this supersedes old no-commit/push and Luna-download-only restrictions for publication.
Ordinary development remains Sol xhigh; Astra xhigh only for concrete difficult issues.
One model controller, concurrency 1, continuous accounting with null cumulative caps,
Lab-only scope and narrow problem-driven checks remain. No Product migration or full suite.
Documentation-only changes need no pytest, build or model calls.

The user-authorized [Goal v8.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v8.0_20260925.md)
completed A–E development and scoped, staged validation. Durable runtime/recovery, first
writes, same-record updates, post-action maintenance, explicit source-body delivery and
incomplete-run preservation are implemented. The final isolated original MERIT episode
passed 1/1 with current original-card completion, after two full native 5/5 runs whose
maintenance failures remain preserved. Do not describe this as final-source continuous
five-episode success, general reliability, State benefit or Product readiness.
Preserve [results](docs/CONTEXTUAL_USER_MEMORY_V8_RESULTS_20260925.md), all source snapshots
and continuous v8 charges: 137 generations / 948575 generation tokens / 5432 embedding
tokens, unknown=0, Judge=0. Cumulative and verification caps stay null; closed historical
stages do not block new user-authorized repairs. Luna high only downloads, Sol xhigh
ordinary development, Astra xhigh concrete difficult issues. Keep verification narrow;
do not automatically expand the benchmark or run full suites. Documentation checks need
no pytest, build or model calls. No commit/tag/push or Product migration was performed.

The [Goal v7.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v7.0_20260925.md)
completed P0–P7 development before E0 selection, followed by E1/E2 on one complete exposed
MERIT arc. The final ordinary/off run scored 5/5 (dependent 2/2) and exercised durable
CREATE → REVISE → later-session memory → native business action. Preserve both earlier
3/5 failures, the continuous v7 ledger, and the [limits in the results](docs/CONTEXTUAL_USER_MEMORY_V7_RESULTS_20260925.md).
Method v11 / write v10 / ingestion v27 / view v8 / operation v2 are the final runtime;
State benefit and reliable post-execution maintenance remain unproven. Do not describe
this single exposed unit as general quality or a comparative win. Do not automatically
expand the benchmark or reopen v6. Keep ordinary, H1–H6 frozen, vLLM Host/Judge,
continuous accounting without cumulative/verification hard stops, and Lab-only boundaries.
Documentation checks need no pytest/build/model calls; implementation checks stay narrow.

For the contextual user-memory
[Goal v6.0](docs/MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v6.0_20260924.md),
the user's current scope takes precedence over the general handoff commands below:

- Keep ordinary as the baseline, freeze H1–H6, and preserve the closed v3/v4/v5
  Goals and results. v5 completed its required execution wiring but retained semantic
  failures and no independent H2 benefit. Its 114 requests and budget stay closed.
- v6's scoped repairs are validated on the three exposed questions across five final
  paths, with general semantic quality unestablished. Method v10/write v9/ingestion v25/
  material view v5 are frozen in the final `v6-user-scope-*` runs. Preserve all previous
  failures, scores and costs: 243 generations, 969510 generation tokens and 93390
  embedding tokens, unknown=0. Final validation accounted for 43 of those generations.
- The user explicitly removed local-verification-count and cumulative request/token
  stopping restrictions. Caps may be null for accounting-only runs; never reset charges
  or block authorized repair because a previous verification was already used. Keep
  per-workflow capacity limits and problem-driven small verification.
- Keep the three exposed native cases and unchanged data/scoring. Ordinary and State
  histories have different identities; do not bypass ownership validation. Additional
  local verification is authorized and is not another independent sample. Do not
  reopen v5, rerun H2 effects, add candidates, expand benchmarks, consume untouched
  confirmation cases, run full STALE or run the full test suite. Keep real sources,
  creation/revision, independent dependencies and State consumption working.
- New schema branches must remain expressible in the deployed generation backend;
  JSON Schema validation alone is insufficient. Reuse the narrow grammar checks.
  Actual subject/source and dependency failures are semantic repair failures even when
  the calls settle; do not close v6 merely because its interfaces are implemented.
- For documentation/manifests, check paths, JSON, selection counts and source hashes;
  no pytest, model calls or package build is needed.
- For implementation, run affected static checks and the narrow existing tests
  relevant to the change. Add only necessary deterministic checks for semantics a
  benchmark cannot observe. Run the boundary check when moving package code and a
  build only when changing packaging.
- Host and any LLM Judge use vLLM. Gold annotations stay outside method inputs.
- Run the delivered default configuration's own smoke; distinguish source receipt,
  committed operations and unfinished maintenance. Verify real mechanism reachability
  before comparing scores, and keep failed or unscored attempts in the cost record.
- Keep refactoring incremental, separate structural moves from behavior changes,
  and avoid repeated validators, silent fallbacks and new review/approval stages.

For other work requiring the general package handoff, run:

```bash
uv run milai-lab-check-boundary
uv run pytest
uv run ruff check src tests tools
uv run mypy src/milai_lab
uv build
```

The product pin verifier is required before any product-backed effect run.
