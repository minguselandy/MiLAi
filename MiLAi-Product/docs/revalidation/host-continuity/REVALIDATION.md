# Host continuity diagnosis — Phase 3A-2D

2026-09-22. Diagnosis complete locally; exact-head CI/merge/main closure pending.
No Product executable behavior changed. Schema remains EXPERIMENTAL / NO-GO.

## Decisions

- **process-local task continuity/state: OPEN.** A retired Host instance can reactivate
  after another instance has replaced it, repeating an already seen native operation.
- **cache-miss Host continuation: FIXED for the tested scope.** Fresh Host processes
  reacquire persistent memory through actual MCP/HTTP/PG. Neither missing local cache
  nor an offline Runtime silently authorizes cached Context.

The two findings are independent. Correct Runtime reauthorization does not make a
duplicate native operation acceptable; a native replay defect does not demonstrate
unauthorized Canonical state or stale memory exposure.

## Reproduced defect and next action

`SameProcessTaskRegistry.bind` treats every different `host_instance` as a new process,
clears sessions and seen operations, and increments generation. Sequence A/op-1 →
B/op-2 → retired A/op-1 therefore passes. The actual Adapter repeats the MCP and
controlled Provider calls: observed `(rejected=False, mcp_calls=3, fixture_calls=3)`
instead of `(True, 2, 2)`. Ordinary same-instance duplicate rejection still passes.

Owner: Product OpenWorker task binding. Risk: an authenticated delayed/replayed old
native request replaces the graph and causes duplicate work/provider spend. This is
not an ingress-capability, tenant, scope or Canonical authority bypass claim.
Next: separate `fix/host-continuity-retired-instance`, reject retired instance before
state mutation or MCP/Provider, retain legitimate new-instance and same-instance
continuation, and produce a separate remediation receipt. No fix is in this branch.

## Required-case evidence

| Required case | Evidence / result |
| --- | --- |
| Same-process CONTINUE, ordinary duplicate | Existing native registry plus actual Adapter duplicate gate: PASS |
| SWITCH, delayed result, ABA generation | Existing task-binding graph, suspended-task result and generation controls: PASS |
| Restart, same session | Four separate spawned Host interpreters; TASK_START then CONTINUE in each pair: PASS |
| Old native token | Fresh graph returns ORPHAN_TASK_MISSING; rotated HTTP capability rejects old bearer: PASS |
| Retired native instance/operation | Registry and actual Adapter A → B → A replay: FAIL, preserved |
| Persistent Runtime memory/cache miss | Fresh Host has no previous locator, obtains same exact Claim version by new Runtime retrieval: PASS |
| Receipt reuse | Same-process narrow-query continuation reuses Runtime-validated origin: PASS |
| No reusable receipt | Broad-query control performs a fresh read on all four attempts and retains the Claim: PASS |
| Runtime unavailable | Stop actual HTTP Runtime while Host/MCP/locator remain; Host blocks Provider: PASS |
| Canonical change / old scoped locator | Reuse unchanged-Product-tree 3B-1 PG evidence: old receipt invalidates after supersession/scope change |
| Scope/profile change | Existing Host rebind/invalidation test: PASS; no union of authority |
| Compatibility prefetch cache miss | UNCHANGED without a retained slot, or with wrong digest, fails closed: PASS |

Host PG proof totals 2 cases, 4 distinct Host processes, 10 Host attempts, 8 controlled
Provider fixture invocations, 8 actual authorized Runtime resolves. In the receipt
case, fresh/cache/fresh/cache is observed; in the no-receipt control all are fresh.
After Runtime stops, both retained Host processes produce
HOST_MEMORY_REQUIRED_BUT_UNAVAILABLE with zero further fixture invocation.
Provider is an in-process fixture, not an inference service. Model requests/tokens
and research allocations remain zero. No claim of observed model use or efficacy.

## Identity and execution

All executions share unchanged Product tree
`22c011d0d9dc267c2a82a71cd9a4c2b2fdbb199f65aa0084eaf25d6583487f8a`, manifest SHA
`0a3f2b1ada1e00d98133acc287c24fe8837e9775aef1d9f5c73def90e2da17ae` (425 files).
Only diagnostic tests and documentation changed after main `9474c63`.

- Native matrix source `c70ceacb5bc2aeb19ad332b2ec04c8c700bf3145`: **18 PASS / 2 FAIL**,
  zero skips, 1.50 s. The two assertion failures are the original behavior diagnosis.
- Final real-chain source `6712e800ef28189f191eb313108a6b8d86b3d795`, Git tree
  `8ca2419f9d3dcd4a8baf08edb0106d285e300a0a`: **2 PASS**, zero skips, 10.59 s.
- Later CI annotations preserve both assertions as strict expected failures:
  **3 PASS / 2 XFAIL**, 0.43 s. XFAIL is not a behavior PASS; `--runxfail` reproduces
  the original failure. A repair must remove these annotations in its own PR.
- Changed-test Ruff passes. Existing source mypy/package behavior is unchanged;
  affected OpenWorker package checks are delegated to classified fast CI once.

Authoritative commands, test node IDs and JUnit hashes are in
[native receipt](receipt.json) and [cache-miss receipt](cache-miss.receipt.json).
Raw artifacts are private and external:
`/cra/memory/mx_memory/evidence/post-cleanup-3a2d-20260922-mlGmSz`.
`native-diagnosis.xml` SHA
`6920cc370a86837a909518c7b65fe6833bade75d33e7f7c88fdc6023d99cc9e3`;
`pg-r5.xml` SHA
`364c802e51f5ccf0481027eadcbe85d9260587e31c86a5c2f18ce0c5d38b3ec8`.
Each PG case also retains its `diagnostic.json`, per-process Host/Provider records
and broker log under `pg-r5`. No old artifact or source identity was rewritten.

Dedicated PostgreSQL 16.14, database `milai_worker_once`, migration `0056_host_notes`,
loopback `127.0.0.1:32796`, isolated synthetic tenant per case and API/Steward/worker
roles. Real public Proposal/Review creates Claims; the actual worker CLI projects
them. No direct test SQL writes or Lab Product imports. The Lab project supplies
an already-cached Python 3.11 environment only; no Lab source/test runs in this proof.
Owned Host/MCP/broker/Runtime processes and DB are stopped; data remains. Only the
new per-case synthetic reader capability files were removed, not user credentials.

## Preserved development failures and limits

Initial unit collection used the wrong transport module name and was corrected.
The Python 3.12 offline overlay lacked cached psycopg; the cached 3.11 environment
was used instead. Its first `pytest` executable bypassed overlay imports; invoking
`python -m pytest` corrected that harness issue. `pg-r1` retains that collection error.
`pg-r2` failed the broker's required profile socket name. `pg-r3` exposed the invalid
test assumption that every query must issue a cache receipt; the legitimate fresh
path was retained as a separate control. `pg-r4` read native binding from the wrong
owner export; it was corrected to read the actual Host event. These are harness
failures, not concealed successful first attempts or Product continuity defects.

The receipts provide SCOPED G9/G7 evidence, not broad architecture conformance or
production readiness. Serial query-first and compatibility retained-slot negatives
are covered; streaming/concurrent continuation, long-lived Host replacement pressure
and real model effects are not. No full composition, historical replay or unrelated
Runtime/PG suite was repeated. Prior exact-tree scope/canonical tests are reused.

Rollback: remove the new tests/docs to `9474c63`; no migration, behavior or DB rollback.
