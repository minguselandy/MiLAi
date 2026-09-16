# OE-07 Agent execution optimization implementation evidence

Decision: `LOCAL OPTIMIZATION CANDIDATE PASS — PROVIDER/BETA NO-GO`  
Date: `2026-08-18` (Asia/Shanghai)  
Boundary: local/synthetic only; Runtime `0.1.x CANDIDATE`; Schema `0.1.x EXPERIMENTAL / NO-GO`

## Outcome

The executable optimization path described by
`MiLAi_Agent执行效率与Token优化设计开发文档_v1.md` is implemented for Generic Python,
MCP stdio, LangGraph, AutoGen and coding hooks. It preserves the frozen Canonical Gate and does not
add an external memory backend or grant an adapter canonical mutation authority.

This record does **not** promote the result to Beta or Production. Candidate.2 passed independent
local re-review and closed OE-F01–F05/F07 with no new finding. One non-local release proof remains
open: no approved real LLM provider/model was called, so provider-native usage/billing, actual model
rounds/wall time and same-model quality remain unverified. Candidate.3's first provider protocol was
independently rejected. Candidate.4.4 closed the adapter-side executable fallback but independent
review retained one P0 because privileged sandbox/runtime/helper transitive bytes were not bound.
Candidate.4.5 added a deterministic host-execution closure, but independent review found that its
post flag preceded persistent network-helper shutdown. Candidate.4.6 stops and bounded-waits every
executing helper before FD+path revalidation; it is ready for independent re-review, not provider
evidence.

## Implemented design

| Area | Current implementation | Safety property |
| --- | --- | --- |
| Token truth | `TokenCounter`, `CallableTokenCounter`, `TokenBudget`, tool/context split, `ProviderTokenUsage` and `ModelCallResult` | absent tokenizer/usage remains `unverified`/null; no estimated billing is labelled actual |
| Hard budgets | STANDARD 512, HIGH 1,024, hard memory/total ceiling 1,600 and tool-schema ceiling 250 | infeasible protected context raises or abstains; protected fields are not silently dropped |
| Router | deterministic `NONE/CACHE/L0/L1` with reason codes and limit at most three | action-safe/current-state rules retain governed recall; no generative routing call |
| Slot/Delta | one `MemorySlot` per session, `REPLACE/REMOVE/UNCHANGED`, complete policy/budget/compiler/tokenizer/TTL cache key and serializable hook checkpoint | only server-validated, unexpired Slots under the current host policy can be reused; there is no public cache-valid boolean |
| Compiler | ABSTRACT/OVERVIEW/FULL tiers, protected Goal/Constraint/ECS/OpenIssue/branch/discharge/authority/trace material, pointer/omission metadata | incomplete, non-live, invalid-revision/target/branch/discharge Issue details fail closed |
| Tools | `reader-lite` default exposes only `milai_recall`; detail/submitter/operator remain explicit host profiles | dynamic catalog removes MiLAi tools on NONE/CACHE and never elevates token authority |
| HTTP | one bounded `httpx.AsyncClient`, keep-alive pool and explicit close; sync facade owns one event loop | loopback/remote policy, authentication and typed errors unchanged |
| Retrieval | deterministic weighted RRF; optional lexical MMR is disabled by default | candidates still pass the live Canonical Gate; OpenIssue candidates receive no novelty suppression |
| Embedding | bounded concurrency, prewarm, `COLD/READY/DEGRADED` state and readiness metadata | failure is observable and recoverable; no external provider added |
| Frameworks | Generic manager, MCP reader-lite, LangGraph replaceable slot, AutoGen single data message, cross-process hook slot | host policy is immutable from model/state/tool/event arguments; writes remain explicit |
| Provider evidence | frozen 100/500-turn same-model A/B; exact shipped reader catalogs; target pre-count; every native call/receipt; strict quality labels; full capture and two-object billing recomputation | out-of-band approval/plan/report anchors; pinned adapter bytes plus independently rebuilt sandbox Python/import/helper/recursive-ELF closure; pre/post FD+path revalidation; mount/PID/network sandbox; pre-call reservation; secret reflection rejection; capture/reconciliation remain REVIEW_REQUIRED and exit 3 |

During candidate.2 E2E, strict validation exposed that Runtime ContextCapsule omitted OpenIssue
`revision`. Runtime now carries revision, issue type, scope and authority at every compression tier;
the SDK gate was not weakened. Adapters fetch each required Issue by ID, normalize away transport
`request_id`, and preserve branch/discharge semantics.

## Measured results

### Deterministic Agent workload

Frozen workload: 20/100/500 turns, exactly every fifth turn requires memory. Tokenizer is
`ospc.regex.v1`, provider exact is false, and no model call occurs.

| Turns | Static reader-detail + recall every turn | Optimized | Reduction | Route accuracy |
| ---: | ---: | ---: | ---: | ---: |
| 20 | 14,160 | 2,056 | 85.480% | 100% |
| 100 | 70,800 | 10,280 | 85.480% | 100% |
| 500 | 354,000 | 51,400 | 85.480% | 100% |

The 100-turn candidate is below the 30,000 evaluation-token gate. It has 20 optimized logical recall
operations versus 100 baseline operations. The offline process performed zero provider calls, so
extra model rounds and end-to-end model wall time are explicitly null. AutoGen's 500-identical-update
test retains one model-visible MiLAi message and performs one recall after validated cache reuse.

### Provider gate readiness

The provider A/B path has a closed local protocol/adversarial suite. It alternates baseline and optimized
order across a frozen 500-turn run and derives the 100-turn prefix from the same calls, for exactly
1,000 provider requests. Before execution it requires an out-of-band approval and plan digest bound
to pricing/workload/execution/sandbox/egress/tool/budget identity. Each charge-bearing request is
target-counted and cost-reserved first. The adapter runs as a distinct uid in private mount/PID/network
namespaces with no workspace, home, host data/socket, general DNS or non-approved egress. The report
retains every native ID/receipt and is fully recomputed at reconciliation; normalized billing and the
actual upstream artifact are separately opened and hashed. A v3 host lock independently enumerates
the launcher, sandbox Python static imports, namespace/network helpers and recursive ELF closure;
approval/plan/report bind its digest/root/count/policy, and execution revalidates all entries before
and after the run. Final hashes occur only after the adapter and persistent network helper have
stopped; an unconfirmed helper exit yields FAIL_PARTIAL with a false post flag. No path returns
automatic PASS.

No provider approval, adapter, pricing snapshot, native request receipt or billing export currently
exists in the candidate. Therefore all real-provider measurements remain absent rather than zero.

### PostgreSQL scale

An isolated synthetic database was incrementally measured at 1/1k/10k/100k Claims using the exact
`milai_api` role, RLS, repository and Canonical Gate from `/tmp`. The retained first attempt coincided
with host CPU contention and failed the latency threshold; it is not hidden. A separate retry passed:
at 10k, warm concurrency-1 p95 was `20.819 ms` for L0 and `33.596 ms` for L1; 100k was measured and
cleanup passed. This variability reinforces that these are candidate observations, not an SLO.

### Runtime and integration gates

| Gate | Result | Retained evidence |
| --- | --- | --- |
| Fresh exact-role PostgreSQL Runtime | 152 passed in 139.04 s; cleanup 0 connections; database dropped | `OE-07-runtime-full-gate-2026-08-18.json` |
| Three-session Agent E2E | Generic, official/independent MCP wire, LangGraph, AutoGen; conflict branches/head preserved; revoke, stale projection, purge/erase and cleanup PASS | `OE-06-agent-e2e-2026-08-18.json` |
| Package tests | Runtime exact-role 152; SDK 76; MCP 9; LangGraph 4; AutoGen 6; Hooks 6; benchmark 4 | package-local Ruff/format/mypy/pytest |
| Provider evidence protocol | provider plus benchmark/release-safety combined 45/45 PASS in 133.56 s; Ruff/mypy PASS; non-repo-cwd full capture PASS | `evals/agent_efficiency/test_provider_ab.py`, candidate.4.6 remediation report |
| Clean install | six wheels, six fresh virtualenvs, Python `-I` import and PEP 561 PASS | `OE-07-package-clean-install-2026-08-18.json` |
| Examples | Generic, MCP, LangGraph and AutoGen offline smoke PASS | `examples/*/smoke.py` |
| Archive safety | pre-inventory scan: 364 current files and 296 archive members; zero exact-secret match, forbidden member or unsafe archive | archive-aware scanner v2 |
| Live local readiness | doctor 17/17 and status PASS; ONNX prewarm READY in 486.844 ms | local `milai-ops doctor/status` run |

Current package manifest SHA-256 is
`d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`.
The archive-aware scan is intentionally summarized by its counts rather than self-hashing a report
that is itself inside the scanned documentation tree.

## External-project absorption

The implementation absorbs only bounded patterns already documented from Mem0, ReMe, Hindsight,
OpenViking and Graphiti: selective recall, context budgets, pointer/detail recovery, phase separation,
hybrid fusion and MMR. None is imported by Runtime or used as canonical state. Scope evolution,
automatic promotion, generative memory reflection and graph arbitration remain disabled.

## Rollback and residual risk

The optimized adapter path has no destructive schema dependency. The compatibility
`AgentMemory.before_model` path remains available, MCP can be pinned to the legacy `reader` catalog,
embedding prewarm can be disabled, and MMR is off by default. Rollback may reduce efficiency but may
not restore a revoked item or reuse a stale Slot. Full operator steps are in
`docs/runbooks/agent-integration.md`.

The result remains an `Optimization Candidate`. Candidate.2 has independent local acceptance;
candidate.4.6 provider tooling now requires independent re-review. An approved provider/model run and
billing reconciliation are required to close OG-01/03/04/08/09 and provider portions of DoD
1/10/12.
