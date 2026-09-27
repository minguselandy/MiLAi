# MiLAi Lab agent instructions

## Current scope and authority

The user's latest instruction is to pause experiments and publish an overall summary.
The actual Goal is `paused` as of 2026-09-27 18:46:35 UTC. Stop implementation,
experiments, model downloads and deployment; only report closeout and authorized Git
publication are active. Resume requires a new explicit user instruction. Historical ACTIVE
text and the v2 plan are not current execution authorization. See the
[latest overall report](docs/MILAI_OVERALL_EXPERIMENT_REPORT_V2_PAUSE_20260928.md) and
[v2 execution record](docs/MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V2_20260928.md).

N0 selector extraction is published at ddd5ab71 (PR61); N1 audited one existing actual
failure trace. N2 has unfinished, uncommitted implementation and fixed input bytes;
no v2 real generation or embedding calls occurred. N3 remains a local draft; N4/N6
are conditional and untriggered, N5/WP7 remain unfinished. Product remains NO-GO.
Do not complete the full research Goal based on engineering checks or this report.

Preserve both WIP trees: original `next-improvement` at cf1588a (eight files) and
`next-development-v2` at ddd5ab71 (eleven N2 files, plus pause-status documentation).
Do not clean, reset, continue or publish unfinished WIP as an accepted method.
The docs-only closeout uses `next-development-v2-closeout` from ddd5ab71. Root owns
reports/status/manifests, Luna high owns Git publication, and Sol is stopped.
The v2 plan's original bytes and the disclosed NEXT_IMPROVEMENT/NEXT_DEVELOPMENT
filename discrepancy remain recorded. Prior pause reports and old failures are historical evidence.

The exact former AGENTS content is preserved at
[the historical instruction snapshot](AGENTS_HISTORY_PRE_WP1_20260927.md), in the same directory
so its relative links retain their original meaning. It is historical evidence, not a second
active instruction source. Its byte identity and recovery commit are recorded in the
[WP1 review](docs/MILAI_NEXT_IMPROVEMENT_WP1_REVIEW_20260927.md).
Do not restart completed historical repairs or turn every older phase restriction into a current blocker.

## Stable boundaries

- Work in MiLAi-Lab and the necessary root CI only. Product remains NO-GO. Old M1, persistent
  Decision State and structured ODR are historical paths, not automatic development targets.
- Active `src/milai_lab` must not import `milai`, `milai_client`, `evals`, `scripts`, legacy
  runtime or Archive source. Product access uses pinned public contracts/testkits only;
  Lab never writes canonical Product tables directly.
- Keep RESEARCH_PROTOTYPE, SIMULATION, native system comparisons and Product claims distinct.
  Current stored content is neither verified truth nor source authority.
- Preserve original plans, historical inputs/results/source locks, failed attempts and the
  untracked `docs/MILAI_MODEL_SENSITIVITY_V27_GOAL.md`. That stale draft is not a frozen protocol
  or authorization. No second model download/deployment from this task alone.
- Secrets, DSNs, raw private traces, databases, corpora, environments, model assets, caches and
  build outputs stay outside Git. Never print credentials or copy them into reports.
- Runtime cannot read gold/rubrics or route by sample IDs, expected answers or benchmark values.
  Owner/time/source/permission, real receipts, partial effects and pending recovery remain explicit.

## Responsibilities

- Root owns plans/docs, semantic fixtures/rubrics, freezes, every real Host/embedding call,
  scoring, the continuous ledger, analysis and acceptance. Real model HTTP concurrency is 1.
- One Sol xhigh owns source/config/CI/adapters/runners and necessary implementation checks.
  Ordinary development is not delegated to Luna to save cost.
- Luna high owns required public downloads and the user's explicitly authorized Git commit,
  push and GitHub publication. It does not judge semantic effectiveness.
- Astra xhigh is used for a concrete difficult problem with evidence, competing explanations
  and a precise question; no standing audit role. Sol converges the implementation afterward.
- Reuse matching available agents, give each file one writer, and declare paths/contracts/checks
  in assignments. Explicit model overrides use limited/no inherited history. If a requested
  model is unavailable, say so; do not silently downgrade. The root model is environment-defined.
- Development-agent models/costs are separate from experimental Host/Judge settings/costs.

## Work and experiment discipline

Locate the first actual broken link and at least two competing explanations. Implement the
smallest general repair before drawing effectiveness conclusions. Separate C0 verification,
C1 structural equivalence and later behavior changes. Preserve complete CRUD and NO_CHANGE;
do not require a fixed State/search ritual or silently convert unknown UPDATE into CREATE.

Use locked public LangGraph/LangMem APIs and existing runners. Keep shared vLLM deployment
unchanged. Freeze any permitted experiment-level setting/cadence/material change separately;
do not silently change parser, thinking, context, output limits or temperature for better scores.
Avoid speculative platforms, persistent indices, broad scans and repeated wording tweaks.

Before real evaluation freeze source/method, input bytes/selection, model parameters/tool
contract, scorer, group order and isolation. Root serially runs isolated namespace/store/
checkpoint/business state and verifies input → actual HTTP → tool/world → persistence → later
context → actual answer/action. Normal process exit is not semantic acceptance.

Keep every failure, retry, empty extraction and observation cost. Record Observed/Expected,
causal chain, first break, competing explanations, repair candidates, confounds, minimal next
experiment and Continue/Pivot/Kill. Do not replace failed samples, splice best trajectories,
relabel exposed data unseen, or combine incompatible denominators/source versions.

The authoritative continuous ledger is the original checkout's
`/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`.
Worktree runs must explicitly use it rather than create a fresh ledger. Historical cumulative
request/token hard caps remain removed; per-message/workflow capacity and all charges remain.
Unknown usage stays unknown. Private DSN is injected only when needed from the original
ignored `artifacts/langmem-foundation/private/postgres.json`.

## Verification and publication

Use [the dependency/check matrix](configs/lab-verification-matrix.json), its
[checker](tools/check_verification_matrix.py) and actual workflow commands. Core, foundation
and external checks must run with their true locked dependencies. Never global-ignore missing
imports, hide uncovered modules, or count skipped optional SDK paths as passes. Historical
local-asset contracts remain explicitly separate from public synthetic checks.

Run affected narrow checks first and expand only for a real failure, change or required gate.
For docs/manifest-only changes check links, JSON and hashes; no model calls, pytest or build.
Build when entrypoints, packaging or dependencies need it; do not repeat passed checks for
publication. Moving package code requires the relevant boundary checks. Mock HTTP tests are
engineering evidence and do not add real experimental samples or tokens.

Update compact results, costs, limits and reproduction before Luna publication. Check exact
remote SHA and intended worktree status. Keep C0 and later behavior identities separate;
no automatic PR merge, PR closure or main rewrite. Archived code/old results reproduce at their
own commits; current source need not match every old lock. Follow root Source of Truth for
any actual legacy retirement; this task does not authorize deleting sibling checkouts/assets.
