# MiLAi Lab active operating constraints

## Current authorization

The active user Goal authorizes full execution of
[code organization and boundary plan v12.0](docs/MILAI_CODE_ORGANIZATION_BOUNDARY_PLAN_20260929_v12.0.md).
Its PLAN_ONLY metadata is the original planning snapshot, not a refusal of current execution.
Work in `/cra/memory/mx_memory/MiLAi-worktrees/code-architecture-v12-20260929/MiLAi-Lab`,
based on main `cca2fd9d1cb4614c44a40ddc0458325d959e6740`.
The code-organization Goal is active; all semantic experiments remain paused.
No real Host, embedding, Judge, PostgreSQL experiment, model download, deployment or service
configuration change is authorized by v12. Product remains NO_GO.

## Owners and scope

Root owns plans, baseline inventories, synthetic fixture specifications, documentation,
acceptance and integration decisions. One reused gpt-6-sol / xhigh owns source, tests,
configuration and necessary CI. Reused gpt-6-luna / high owns Git publication and merges.
Use gpt-6-astra / xhigh only for a concrete difficult issue with evidence and a clear question.
Keep one writer per file; do not silently change model or reasoning level.
Work in Lab and necessary root navigation/CI; do not alter Product or Archive implementation.

## Required end state

Follow S0–S7 and all fifteen completion criteria without replacing them with a smaller cleanup.
Canonical contracts, memory, external integrations, benchmark lifecycle and generic provider
hooks must own the reusable behavior. Old moved paths are pure re-exports of the same objects.
Enforce the real dependency DAG and facade purity automatically; do not hide violations in
TYPE_CHECKING, dynamic imports, new generic-looking wrappers or broad allowlists.
Keep method-specific logic in methods/recipe composition, never generic provider code.

## Behavior, evidence and validation

Freeze baseline schemas, receipts, requests/wire, Store calls, identities and on-disk contracts
before moving their implementation. Preserve ordering, errors, namespace, UUID, tool call IDs,
accounting, defaults, upstream SDK identity and real historical failures.
No rubric/gold in runtime inputs; no sample-specific rules; no R2 semantic repair or method
promotion in this task. Keep legacy labels and all algorithm/budget settings unchanged.
Every canonical move must enter current source identity and the verification matrix.
Historical locks and experiment reports are immutable; replay old results at original commits.
Use the existing Core/Foundation/External/Local-artifact groups with real dependency coverage.
Run affected Ruff/mypy/behavior/boundary/matrix checks and package/install checks for module
moves. Do not repeat passed checks unless code changes or evidence justifies them. Do not run
broad benchmarks, download new dependencies or use skips to manufacture a pass.
Preserve initial check failures and fixes. Local mechanical tests are not semantic evidence.

## Publication and preservation

Use reviewable S1–S6 commit groups (A–F in the plan); one integration PR is allowed.
Luna publishes after concrete changes and checks, then merges only after affected Fast CI passes.
Do not force-push, squash away frozen history, bypass required checks, delete original worktrees,
remove drafts or publish credentials, private traces, databases, caches, weights or build output.
The continuous experimental ledger remains the original checkout's
`artifacts/ser-v20/budget.json`; do not reset or rewrite it.

## Historical instructions

The previous AGENTS bytes are preserved unchanged in
[the pre-v12 snapshot](docs/agent-history/AGENTS_PRE_V12_20260929.md).
Historical ACTIVE, pause and no-merge paragraphs describe their dated scopes and cannot override
this Goal or later explicit user instructions. Root cross-bundle AGENTS and Source of Truth
continue to govern ownership; the original research objective is not complete.
