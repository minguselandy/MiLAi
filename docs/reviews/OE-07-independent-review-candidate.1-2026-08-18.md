# MiLAi Agent Execution Optimization 0.1 独立审查总结（candidate.1 record）

Decision: **REVISE**

Reviewer identity: /root/af09_independent_review  
Independence: separate no-history sub-agent; did not author candidate  
Review window: 2026-08-18T06:28:13Z–2026-08-18T06:57:10Z  
Environment: Linux 5.15.0-86-generic x86_64; CPython 3.11.13; Ruff 0.16.3; mypy 1.20.2; pytest 8.4.2; local PostgreSQL/pgvector exact-role environment.

本文件是在指定基础路径已经存在后，按要求使用 candidate.1 后缀新增的审查总结；未覆盖既有 review，未修改候选源码、配置、证据、包、manifest 或 inventory。

## 1. Candidate identity

| Artifact | SHA-256 / identity |
| --- | --- |
| docs/reports/OE-current-byte-inventory-2026-08-18.json | 32c15cd82f364728682f6b4fe64333c670e43a3715afffb9212b683347f01294 |
| Inventory entries root | 31bbc18a6d819e1a00792e26bc87b2d84db32cfd0abfb599b71634de588e1606 |
| Inventory entries | 342 |
| OE design | 8c1f9fcd1cae31fe78029fced998c4587d712db18cc6e8a54e3483200b5de014 |
| OE implementation evidence | fbc1e87529c91dae64a461930083d7aa11d326e590102f7e192745b9c58b2f39 |
| OE requirements matrix | 1c97fa99d21317a496a498c801c9715309c89a7ada1e00af2f89c09d2fe20750 |
| Package release manifest | d88b17ca65c0fd29b7ac445929222067acb4370a530a8b006388f6ebe0ec8146 |
| Frozen architecture manifest | ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e |

独立重算确认 inventory 路径安全、排序唯一，342 个 entry 的 size/SHA 与 JSON 完全相等，canonical entries root 与文件 SHA 均匹配。docs/reviews 不在 candidate inventory scope，因此本 review 不应改变候选身份。

## 2. Confirmed findings

| ID | Severity | Confirmed observation | Required change / acceptance evidence |
| --- | --- | --- | --- |
| OE-F01 | **P0** | Cache validity is not bound to the complete current host policy or token/compiler budget. DeterministicRecallRouter.cache_key() includes scope/authority/consistency, but the runtime reuse path does not consume that key and MemorySlot does not retain an equivalent binding. AgentMemory.prepare_context() and AsyncAgentContext.prepare() also accept a public cache_validated override that can bypass their server-side validation path. Current behavior can retain an old slot after a policy or budget change. Evidence: MiLAi_Agent执行效率与Token优化设计开发文档_v1.md:550-577,1411-1416; integrations/python-client/src/milai_client/optimization.py:325-354,388-424,1061-1079; lifecycle.py:155-208,273-283; async_context.py:60-112,176-188. | Bind every reusable slot to query/goal, scope, authority, consistency, canonical and Issue position, router/compiler version, tokenizer and applicable budget/TTL. Validation facts must be internally produced and current-input-bound rather than accepted as a caller boolean. Add sync/async/hook/framework regressions for every invalidation dimension and show valid unchanged reuse still works. |
| OE-F02 | **P1** | OpenIssue cache/delta identity hashes the complete raw response. Runtime GET /v1/open-issues/{id} adds a per-request request_id, so semantically unchanged Issue state produces a different digest/snapshot and the next identical query performs L1/REPLACE rather than stable CACHE/UNCHANGED. Evidence: runtime/src/milai/api/app.py:51-53,147-153; runtime/src/milai/api/canonical_routes.py:183-191; integrations/python-client/src/milai_client/optimization.py:1030-1047,1061-1079. | Define and use one semantic OpenIssue projection for snapshot/digest/rendering, excluding transport metadata while retaining all governed fields. A repeated real endpoint response with unchanged Issue revision/branches/discharge must reuse the slot; any governed change must still invalidate it. |
| OE-F03 | **P1** | The retained workload is explicitly offline-synthetic with model_id=no-llm-called, provider_usage_verified=false and null pricing. No target-provider usage/billing reconciliation, target-tokenizer reader-lite/context proof, post-ready first normal query record, or same-task/same-model current-versus-optimized quality comparison exists. The author evidence itself acknowledges this boundary at lines 14-18 and 42-55. | Retain a frozen target model/provider A/B run with provider-native input/cached-input/output usage and request identity, MiLAi memory/tool split, actual model turns, wall time, pricing snapshot and quality/safety results; separately retain the post-ready first-query measurement. Until then the status must remain Optimization Candidate. |

Open findings: **P0=1, P1=2, P2=0**.

## 3. OE / OG / DoD disposition

### OE-00～OE-07

| Work package | Independent disposition |
| --- | --- |
| OE-00 | PARTIAL — frozen offline workload, input hashes and scale generator are reproducible; same real model/provider baseline is absent (OE-F03). |
| OE-01 | PARTIAL — accounting API and explicit unverified fallback exist; provider reconciliation is absent. |
| OE-02 | REVISE — slot/delta implementation exists, but reuse binding and stable Issue identity are not correct (OE-F01/F02). |
| OE-03 | REVISE — deterministic Router and reader-lite exist; the implemented cache key is not enforced by the reuse path (OE-F01). |
| OE-04 | PARTIAL — injected-counter budget tests pass; target-provider tokenizer proof remains open. |
| OE-05 | PASS for local synthetic candidate — persistent transport, bounded embedding, RRF/MMR and independent 10k/100k thresholds passed. |
| OE-06 | PASS for the exercised local synthetic E2E boundary — Generic/MCP/LangGraph/AutoGen and governed conflict/revoke flows passed. |
| OE-07 | FAIL — open P0/P1 and provider release evidence prevent acceptance. |

### OG-00～OG-12

| Gate | Result |
| --- | --- |
| OG-00 | PARTIAL — offline baseline reproducible; real model/provider baseline incomplete. |
| OG-01 | NOT MET — no provider reconciliation. |
| OG-02 | PASS for the tested one-slot/500-turn cases; OE-F02 remains a live-Issue stability defect. |
| OG-03 | NOT MET — target-provider tool count absent. |
| OG-04 | NOT MET — target-provider budget proof absent and OE-F01 permits stale budget reuse. |
| OG-05 | PASS only under ospc.regex.v1 (100-turn 10,280); not provider billing proof. |
| OG-06 | PASS — independent 10k L0 C1 p95 27.402 ms. |
| OG-07 | PASS — independent 10k L1 C1 p95 35.951 ms. |
| OG-08 | NOT MET — post-ready first normal query record absent. |
| OG-09 | NOT MET — same-model quality comparison absent. |
| OG-10 | PASS for exercised local synthetic adapters, subject to OE-F01 repair across reuse paths. |
| OG-11 | FAIL — stale cache does not fail closed in the confirmed policy/override cases. |
| OG-12 | FAIL — this independent decision is REVISE with open P0/P1. |

### Definition of Done 1～15

| DoD | Result |
| --- | --- |
| 1 | PARTIAL — unverified state is honestly reported; no target-provider proof. |
| 2 | PASS for one-slot replace/remove/unchanged and 500-turn non-append behavior. |
| 3 | FAIL because OE-F01 can bypass the current policy-bound canonical recall decision. |
| 4 | PASS — reader-lite exposes one recall tool and tested catalog escalation is rejected. |
| 5 | PASS for the exercised complete Issue fixtures and protected rendering; provider-tokenizer evidence remains separate. |
| 6 | FAIL because a changed lower budget is not part of cache reuse validity (OE-F01). |
| 7 | FAIL because cache policy binding is incomplete. |
| 8 | FAIL because current policy/canonical validation can be bypassed by the public override (OE-F01). |
| 9 | PASS for the exercised Generic/MCP/LangGraph/AutoGen host-policy contracts, subject to OE-F01 cross-path regression. |
| 10 | FAIL — actual provider tokens/model turns/billing and full wall-time comparison are absent. |
| 11 | PASS — independent 1/1k/10k/100k, concurrency and cold/warm scale run completed. |
| 12 | NOT MET — no same-model quality comparison; OE-F01/OE-F02 remain correctness regressions. |
| 13 | FAIL — package/install/examples/CI/security portions pass, but independent acceptance does not. |
| 14 | PASS — no external memory engine dependency was found in Runtime. |
| 15 | PASS — Schema remains 0.1.x EXPERIMENTAL / NO-GO and Runtime remains CANDIDATE. |

## 4. Completed independent gates

| Gate | Result |
| --- | --- |
| Inventory recomputation | 342/342 exact; root and file SHA exact; safe sorted unique paths |
| Package static/test gates | SDK 57, MCP 9, LangGraph 4, AutoGen 4, Hooks 4; Ruff/format/mypy PASS |
| Runtime static gate | Ruff/format/mypy PASS |
| Fresh exact-role PostgreSQL Runtime | 152 passed in 77.63 s; cleanup PASS |
| Fresh three-session Agent E2E | Generic SDK, official MCP 2026-07-28, independent wire 2025-11-25, LangGraph, AutoGen; conflict/head/revoke/purge and cleanup PASS |
| Fresh PostgreSQL scale | 1/1k/10k/100k PASS; 10k L0/L1 C1 p95 27.402/35.951 ms; cleanup PASS |
| Offline workload | 3 tests PASS; 20/100/500 totals 2,056/10,280/51,400; explicitly non-provider |
| Retained packages | 12 wheel/sdist artifact size/SHA entries match manifest; six fresh isolated wheel installs and PEP 561 PASS |
| Archive/security | 344 files and 295 archive members scanned; zero secret match, forbidden member or unsafe archive; release-safety 8/8 |
| Examples | Generic/MCP/LangGraph/AutoGen smoke 4/4 PASS |
| Live status | doctor 17/17; API live/ready; ONNX READY; synthetic-only; remote disabled |
| Frozen architecture | bundle validation and release lock PASS; 19 tests OK with bundle scope and one expected skip |
| Research isolation | Ruff/mypy and 9 tests PASS |

## 5. Final boundary

The current bytes may remain a **local synthetic/de-identified Optimization Candidate**. They are not accepted for the §20 final release statement, Beta, Production, remote use, real-personal-data use or Schema freeze. Logical Architecture 1.0.0 remains frozen; Runtime remains CANDIDATE; Schema remains 0.1.x EXPERIMENTAL / NO-GO.

Inventory before review record:

- file SHA-256: 32c15cd82f364728682f6b4fe64333c670e43a3715afffb9212b683347f01294
- entries root: 31bbc18a6d819e1a00792e26bc87b2d84db32cfd0abfb599b71634de588e1606
- entries: 342

Inventory after review record was independently recomputed and remained identical:

- file SHA-256: 32c15cd82f364728682f6b4fe64333c670e43a3715afffb9212b683347f01294
- entries root: 31bbc18a6d819e1a00792e26bc87b2d84db32cfd0abfb599b71634de588e1606
- entries: 342
- all 342 entry size/SHA records still matched

This is expected because docs/reviews is outside scope. Any mismatch would invalidate this record and require a new candidate identity.

Final decision: **REVISE**.
