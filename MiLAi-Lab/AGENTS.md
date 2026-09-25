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
