# Product Technical Debt Revalidation

历史报告中的问题不自动等于当前缺陷。下表是重组阶段的复核登记；状态只能使用
`OPEN`、`FIXED`、`OBSOLETE`、`NEEDS_REVALIDATION`。状态改变必须附命令、测试和日期。

The explicit Host trace testkit addition changes the whole-Product identity. Existing FIXED
decisions remain tied to their recorded behavior baselines; they are not new-tree revalidation
claims. See the [current evidence map](conformance/CURRENT_ARCHITECTURE_CONFORMANCE.md).

Phase 2 diagnosis baseline: Product tree
`77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443`, baseline commit
`2ce622b86ec4aa9b6df7dc79243159eca3ceb8a0`, with Phase 2B diagnostics anchored by
`dc3267142fdc9c5bcd7061c55c1a0242e62663af`. B1 remediation baseline: Product tree
`f9d6f6ebf90712160441c3d57835131851ece12c945670cc607c225e22566344`, source commit
`c1895e37defe5effbb5ce489613d0528dc8f3fd5`. B2 remediation baseline: Product tree
`a93268d94a73e5aee53150ca4be9bbc5f37f76d0173c5be72633cc54cf2ea382`, source commit
`28fa9211d54032243eac3aac6a3819aca41bff2b`. Phase 2C-1 diagnosis uses the same
Product tree with source commit `fa16bb7c1b28b16b15c1800df86999804e729d3b`. Phase 2C-1 remediation
baseline is Product tree `2dddd26130943834468e7944f3b422c2aa81e64611256cb7f497e7f96e32b0a1`,
source commit `6fbb717ba2e9c77fd8be071725b2f25a0d771cb4`. Results were verified on 2026-09-20.

| Item | State | 当前证据/下一步 |
| --- | --- | --- |
| process-local task continuity/state | FIXED | [3A-2R scoped repair](revalidation/host-continuity/REMEDIATION.md), 2026-09-22: retired instances reject under the existing lock before native graph mutation/MCP/Provider, including fresh operation/session and tool continuation. 24 native tests and 2 real recovery cases PASS; original FAIL receipt retained. PR #36/full #63/main fast `35688151840` close the scoped repair; not a production or full G9 claim. |
| cache-miss Host continuation | FIXED | [3A-2D scoped diagnosis](revalidation/host-continuity/REVALIDATION.md), 2026-09-22: 2 real MCP/HTTP/PG cases, 4 fresh Host processes, 10 attempts / 8 fixture calls; exact Claim reacquired after restart, receipt hit and fresh fallback work, stopped Runtime blocks Provider. Compatibility missing/mismatched slot fails closed. Separate native defect was repaired in PR #36. |
| validation-token TTL vs capsule lifecycle | FIXED | [`docs/revalidation/context-validation-lifecycle/REVALIDATION.md`](revalidation/context-validation-lifecycle/REVALIDATION.md); diagnosis FAIL is preserved, while current-tree validation reads authoritative capsule lifecycle, clamps lease expiry, and exact-refreshes lifecycle misses |
| projection purge/rebuild | FIXED | [`docs/revalidation/projection-purge-rebuild/REVALIDATION.md`](revalidation/projection-purge-rebuild/REVALIDATION.md); targeted PostgreSQL execution passed, including rebuild-after-revoke non-resurrection |
| confirmation binding to query/action | FIXED | [`docs/revalidation/confirmation-binding/REVALIDATION.md`](revalidation/confirmation-binding/REVALIDATION.md); diagnosis FAIL is preserved, while current-tree remediation binds tenant/query/goal/scope/authority/action digest and passes replay, expiry, revoke, and readability regressions |
| OpenWorker HTTP auth/exposure | FIXED | [`docs/revalidation/openworker-http-exposure/REVALIDATION.md`](revalidation/openworker-http-exposure/REVALIDATION.md); executable 仅接受显式 loopback/private literal，拒绝 wildcard/hostname/multicast/public bind；Bearer 为进程生命周期 capability，stop/replace/restart 完成 rotation |
| resolver lexical-language assumptions | OPEN | [Original diagnosis](revalidation/resolver-language/REVALIDATION.md) retains 17 PASS/13 FAIL. [Separate partial remediation](revalidation/resolver-language/REMEDIATION.md), 2026-09-22: same corpus 28 PASS/2 FAIL; client 20/2, Runtime 8/0. Typed Unicode/ambiguity/retry/no-memory boundaries improve; C06 undeclared synonym and C21 cross-language exact predicate remain unsatisfied. Owner: Product client/Runtime. No actual retrieval/use measured, frozen aliases preserved. Debt remains OPEN; no fixture dictionary/model authority. Final composition/remote candidate closure pending. |
| Runtime vs Host/provider trace ownership | FIXED | [3B-1 scoped revalidation](revalidation/trace-ownership/REVALIDATION.md), 2026-09-22: serial query-first public testkit binds actual fresh Evidence and Claim/cache origins across Runtime/MCP/Host/controlled Provider/Lab; 47 Product targeted tests (8 PG cases), 76 Lab tests and 18 real-chain attempts. Exposure/use UNKNOWN and unknown usage remain explicit. Streaming/concurrent tracing, cross-process continuity and model benefit are not claimed. PR #34 / main fast `35683815988` closes the scoped work package. |
| worker --once docs/behavior | FIXED | [`worker-once/REVALIDATION.md`](revalidation/worker-once/REVALIDATION.md), 2026-09-22: real CLI/PostgreSQL bounded-cycle, failure, check, orphan and watermark evidence; 20 targeted tests PASS. Runbook clarifies exit 0 is not queue-success proof; no executable change. |
| CAS blob-first orphan possibility | FIXED | [`docs/revalidation/cas-blob-orphan/REVALIDATION.md`](revalidation/cas-blob-orphan/REVALIDATION.md); forced DB failure, real worker startup cleanup, recovery ingest, and replay passed |

重组完成报告必须逐项列出最终状态。任何需要行为修复的条目另开独立 Goal/PR，不能在
结构性整理中顺手改变检索、排序、阈值、预算、Prompt、Schema 或迁移。
