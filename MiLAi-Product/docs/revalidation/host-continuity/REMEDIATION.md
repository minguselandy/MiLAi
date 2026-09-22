# Retired Host instance remediation — Phase 3A-2R

2026-09-22. Local scoped proof PASS; final composition and remote closure pending.
The original [FAIL diagnosis](REVALIDATION.md) and its receipt remain unchanged.

## Behavior and boundary

[ADR-057](../../adr/ADR-057-retired-native-host-instance-rejection.md) records the
decision: retain retired native Host IDs for the Adapter registry lifetime and reject
them under the existing lock before graph/generation/session/operation mutation.
The check precedes synchronous tool-continuation handling. It rejects both old and
new operations/sessions from a retired instance; it is not a case-specific op-1 rule.

The active instance still continues, and a genuinely new instance starts a new
generation. Actual Adapter rejection preserves native/task registry and Context
locator snapshots and causes no extra MCP/Provider call. Existing conflict mapping,
HTTP capability rotation, Runtime reauthorization and persistent Memory are unchanged.
The retirement set is process-local and grows with replaced instances; it cannot
evict old IDs during that registry lifetime without reopening the defect.

No API/schema, permission, Canonical, migration, retrieval, cache-validation policy,
Provider budget or Lab behavior change. Schema remains EXPERIMENTAL / NO-GO.

## Exact source and executed proof

- Source `faf3922c2b1d037f0c3a019dd1bbaf6dc059be15`, Git tree
  `778b9ef41f1e06ef1671d77b15b17d03b542668f`.
- Product 425 files, tree
  `08cd98fea12383fd26cf3f10b39bc04ffea23da2271f45ebe55c772a57ecafe2`, manifest SHA
  `44be5e2e93837dcc75b996140f06b10e6142dc34e6a5718a894f79574ddfd352`.
- Final native matrix: **24 PASS / 0 FAIL / 0 SKIP / 0 XFAIL**, 1.41 s.
  Includes original failed assertions, four new retired-instance/tool-continuation
  combinations, legitimate later replacement, duplicate, delayed result, ABA,
  scope/profile, missing/wrong slot and rotated ingress capability controls.
- Real recovery matrix: **2 PASS / 0 skips**, 11.07 s; four fresh Host processes,
  ten Host attempts, eight controlled Provider fixture calls through actual broker,
  MCP subprocess, authenticated HTTP Runtime and PostgreSQL. Identical persisted
  Claim reacquisition, receipt hit, fresh fallback and stopped Runtime fail-closed pass.
- Initial development check: 21 narrow tests passed. Changed-file Ruff and mypy pass.
  Original XFAIL annotations were removed; this is an actual behavioral repair.

The [new machine receipt](remediation.receipt.json) records exact commands/node IDs,
JUnit paths and hashes. Evidence root:
`/cra/memory/mx_memory/evidence/post-cleanup-3a2r-20260922-jwlwRm`.
Native JUnit SHA `c3207d894bd81f6fb9076e7043a27faa995d7ff6ab97f9bc9b03aaaa83c68d05`;
PG JUnit SHA `ad90dfd31f154bf35b4a9333b9ac173d12de821b03b2625ecfefe8de4dbd4e0d`.
Private per-process traces and compact diagnostic JSON are retained under `pg`.

Dedicated PostgreSQL 16.14, `milai_worker_once`, migration `0056_host_notes`, loopback
`127.0.0.1:32797`, isolated synthetic tenants and separated API/Steward/worker roles.
Actual Proposal/Review and worker CLI create/project Claims; no Lab source or model
is executed. Model requests/tokens and research allocations remain zero. Owned child
processes and database are stopped; data retained. Per-case synthetic reader capability
files were removed after execution; no user credential or historical evidence changed.

## Remaining gates and rollback

This material Host repair requires one final-candidate full composition under the
governing Goal. Package-wide/static/build and composition checks are delegated to CI;
no local full suite or historical replay is duplicated. The work package stays
IN_PROGRESS until exact tested-head gates, expected-head merge and main identity pass.
This receipt is SCOPED G9/G7, not broad conformance or a model benefit claim. Previous
receipts retain their original Product identity; they are not rebound to this tree.

Rollback to `e7604346471593127f09dbae321e95f018d2fa13` reopens the known native replay
defect; no database migration rollback or rewriting persisted memory is involved.
