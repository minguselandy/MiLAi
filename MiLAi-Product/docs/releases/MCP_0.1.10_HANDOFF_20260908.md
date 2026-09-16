# MCP 0.1.10 local repair handoff

Candidate combination: MCP 0.1.10 / Python client 0.1.3 / Runtime 0.1.4,
ordinary-memory-v1 (23 registered tools), legacy (13), migration 0056 unchanged.
Public service, grants, OAuth state and user memory have not been changed.

This increment fixes scope-specific checkpoint hints, exposes actual Proposal
constraints, preserves safe field/CAS diagnostics, and stops automatic State write
retries that hid UNKNOWN when SDK retries were enabled. Guidance remains optional;
governance hints explicitly require authorization. Note deletion consistently
reports physical_deletion_supported=false without changing tombstones/history.
Runtime's only validation change is field-local error locations. Identity, scope,
TTL, permissions, canonical commit procedures and persistence semantics remain.

Contracts: [ordinary catalog](../../contracts/mcp/ordinary-memory-v1.md),
[repair runbook](../runbooks/mcp-contract-repair-v08.md), and
[execution audit](../goals/MILA_V02_08_EXECUTION_20260908.md).
The delivery archive includes wheels, sdists, locks, current and historical
snapshots, nine Proposal examples and installation instructions. Archive hashes
are external sidecars so they do not create a self-referential package checksum.

Verification: MCP 333 passed / 6 conditional PG skips in the full default suite;
the changed signed-private HTTP/PG slice separately passed, including three-scope
CAS races, exact-object version disclosure, invalid combinations, source/deletion
visibility, before/after-commit cuts, identical replay, fresh clients and restart.
Client 190 passed. Runtime unit/contract 1016 passed and adjacent real PG 4 passed;
the unmodified large-reference capacity/migration test was deselected. Locked
Ruff/mypy passed for these three packages; build and installation receipts are
recorded in the execution audit. Default-suite PG skips are not counted as passes.

Failures retained: stricter UUIDs exposed non-UUID synthetic fixtures; CREATE field
errors were initially hidden by evidence-list validation and were repaired. The
first real State wire-cut test exposed SDK automatic retry; client 0.1.3 disables
it and the real HTTP test then passed. One Runtime PG attempt lacked Audit-role
configuration; a fresh owned database with that role completed the slice. Minor
lint failures and the installed-package inspection's missing pytest are recorded
as development/inspection failures, not runtime regressions or discarded evidence.

Current Codex metadata still exposes 13 tools and proposal: unknown. Installed
0.1.6 wire schemas have a Proposal object reference and short tool descriptions;
all 13 observed Host descriptions prepend its exact 1541-character instructions.
Twelve complete descriptions match after that prefix; review has a further
difference. This establishes a materialization/version mismatch, not the unique
live process or cache cause. Ordinary candidate tools/list now expands the Proposal
object at serialization; no second business schema or validator was created.
Candidate Host rendering is still unverified. No actual Host cleanup rejection
was available; admin scope enforcement is verified locally without public cleanup.

Rollback: install previous compatible packages/configuration while retaining all
database rows, identities, grants and audit. No new migration, database restore or
destructive cleanup is needed. Rolling the SDK back also restores its older State
retry behavior. Public deployment requires separate authorization and endpoint,
package combination, scope and rollback checks. No model requests, paid requests
or token allocation were added; v0.2-07 U5 and experiments remain pending/paused.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.
