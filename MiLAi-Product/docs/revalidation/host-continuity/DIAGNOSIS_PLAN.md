# Host continuity diagnosis — Phase 3A-2D

Status: DIAGNOSED, 2026-09-22; remote closure pending. The
[execution report](REVALIDATION.md) classifies native continuity OPEN and cache-miss
continuation FIXED for the tested scope. This page preserves the original plan;
no Product behavior fix is included.

Baseline: main `9474c63e56e5029c33e2dca5c19e772e4868b18d`, Git tree
`1c070d6d9c62ea3ce71a68b22ca3ec4e87c2584e`, main fast `35683815988` PASS.
Product tree `22c011d0d9dc267c2a82a71cd9a4c2b2fdbb199f65aa0084eaf25d6583487f8a`.
The [governing Goal](../../cleanup/MILA_POST_CLEANUP_DEVELOPMENT_GOAL_v1.0_20260922.md)
section 5.3 defines the required cases and separate diagnosis/remediation boundary.

## Required distinction

Native execution identity is process-local: a restart ends the old graph and
creates TASK_START. Persistent Runtime memory may be reacquired only through current
authorization and exact Context validation. A receipt locator is not offline authority.
An old native token must not become a new-process execution capability.

The existing query-first path always calls Runtime through MCP and delegates receipt
validation to Runtime. Compatibility prefetch retains a Host slot and must reject
UNCHANGED when that slot is absent or its digest differs. Diagnose these distinct
paths rather than equating a local cache miss with lost persistent memory.

## Minimal evidence matrix

| Required case | Existing entry point / remaining proof |
| --- | --- |
| Same-process CONTINUE; duplicate reject | `tests/test_task_binding.py` native registry tests; real Adapter dispatch binding |
| SWITCH; delayed result; ABA generation | Existing registry graph, suspended-task result and old-token tests |
| Scope/profile change | `tests/test_adapter.py` rebind/invalidation and registry ambiguity tests |
| Restart, same session | New-process native graph/cache absence plus actual Runtime reacquisition |
| Old locator; persisted memory; cache miss | Real MCP/Runtime/PG, current authorization, explicit fresh or validated reuse |
| Canonical change | Actual governed supersession; stale Context never authorized as current |
| Runtime unavailable | Fail-closed Host terminal; no Provider dispatch or offline cached Context |
| Old native token | Cross-process/instance rejection without rebinding delayed result to new task |

Existing PR #34 integration fast CI already exercised the package. Do not rerun the
whole package merely to count its tests again. Add only missing diagnostic cases;
run the affected matrix once with a compact JUnit and explicit node IDs. Use the
existing isolated role-separated PostgreSQL instance if real persistence is needed,
synthetic data and bounded controlled Provider fixtures, never an actual model.
State exact source/Product identities, preserve failed evidence and keep raw outputs
outside Git. No Lab private Product imports or direct Lab Canonical writes.

## Exit and limits

Produce REVALIDATION.md and receipt.json only after actual diagnosis. PASS can mark
the specific covered debt FIXED; reproducible behavior failure marks it OPEN with
owner, risk and next step. A fix requires a separate `fix/host-continuity-<gap>` branch
and remediation receipt. Code inspection alone supplies neither classification.

No model allocation, historical experiment resume, shared-service modification,
schema/API/permission/Canonical change, full composition or old replay is planned.
Schema remains EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE.
