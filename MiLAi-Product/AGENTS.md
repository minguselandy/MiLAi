# AGENTS.md — MiLAi Product

This file applies to the complete `MiLAi-Product/` repository.

## Mission

Deliver a small, usable, local personal-memory product. Prefer the shortest correct vertical path
over speculative platform work. Experimental algorithms, benchmark harnesses, paper assets, Goal
history, and run artifacts belong in `MiLAi-Lab`, not here.

The current product status is always:

```text
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```

Do not claim production readiness from code presence, historical receipts, or partial tests.

## Normative order

When sources conflict, use:

1. `architecture/v1.0/` frozen logical architecture;
2. `MiLAi_Logical_Architecture_v1_设计文档.md`;
3. `docs/reference/MiLAi_Lean_V1_实施合同.md`;
4. current product contracts and ADRs;
5. implementation and comments.

Changing identity, canonical authority, permission, revocation, deletion, or transaction semantics
requires an ADR, migration where applicable, and direct tests. Do not edit `architecture/v1.0/` in
place.

## Product boundary

Allowed top-level product areas:

```text
architecture
contracts
docs
examples
integrations
runtime
```

Product code and tests must not import `evals`, `research`, legacy root `scripts`, benchmark
packages, or artifacts under `var`. Product CI must remain runnable without the Lab repository.

All six adapters are supported packaging surfaces:

```text
python-client
mcp
openworker-mcp
hooks
langgraph
autogen
```

## Hard invariants

- PostgreSQL Canonical Core is the only formal state source.
- `EvidenceRecord` records an observation, not accepted truth.
- `ClaimVersion`, transition, decision, and issue history are append-only.
- `ClaimHead` moves only by exact-head CAS.
- Only a governed canonical procedure may commit Claim/OpenIssue changes.
- Search, Context, models, adapters, and derived projections cannot raise authority.
- Permission, scope, tenant, retention, and revocation fail closed.
- Evidence revocation blocks authority synchronously; derived cleanup may follow asynchronously.
- A secondary-index failure may reduce recall, never increase authority.
- Canonical unavailable or evidence insufficient means explicit abstention.

## Efficient development discipline

Use the minimum proof needed for the risk:

1. inspect the adjacent domain, application, repository, migration, and tests;
2. make one narrow vertical change;
3. run the smallest relevant test first;
4. expand to static, package, and database gates before handoff;
5. if a test fails, diagnose and repair the general cause, then continue—do not create a new
   experiment bureaucracy or a case-ID special rule.

Avoid defensive-programming layers that duplicate an existing typed boundary. Add validation only
at trust, authority, persistence, or external-I/O boundaries. Internal pure functions may rely on
already-validated domain objects.

Do not add synonyms, query-case branches, benchmark IDs, arbitrary retries, enlarged Top-k, or seed
changes to make a fixture pass. Prefer orthogonal contracts, per-requirement evidence coverage, and
simple multi-channel retrieval.

## File and migration rules

- Preserve user changes and unrelated work.
- Use `apply_patch` for authored edits.
- Never commit `.env`, databases, blobs, model weights, logs, caches, wheelhouses, or run artifacts.
- Migrations 0001–0049 are an ordered compatibility chain. Never renumber, squash, or rewrite an
  applied migration.
- A new schema change needs upgrade behavior, an honest downgrade or irreversibility statement,
  compatibility notes, and real PostgreSQL tests.
- Runtime roles stay separated: migration owner, API, Steward executor, projection worker, Audit.

## Testing

During development run the narrow test. Before product handoff run, as applicable:

```bash
cd runtime
uv run ruff check src tests migrations
uv run mypy
uv run pytest -q
uv build
```

For integration changes, run that package's locked `ruff`, `mypy` where configured, `pytest`, and
`uv build`. Canonical, RLS, concurrency, worker, revocation, and migration changes require real
PostgreSQL rather than mocks.

Architecture validation uses bundle scope in this split repository. The frozen manifest's broader
project/workspace locks describe the legacy freeze environment and are retained as historical
evidence; they are not a promise that the new product repository has identical Git/workspace state.

## Handoff

Report:

- changed behavior and affected invariant;
- API/schema/permission/canonical impact;
- exact commands and results;
- unrun checks and why;
- migration/rollback implications;
- remaining risks;
- confirmation that Schema remains `NO-GO FOR SCHEMA FREEZE`.
