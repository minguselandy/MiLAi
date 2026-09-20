# Product Technical Debt Revalidation

历史报告中的问题不自动等于当前缺陷。下表是重组阶段的复核登记；状态只能使用
`OPEN`、`FIXED`、`OBSOLETE`、`NEEDS_REVALIDATION`。状态改变必须附命令、测试和日期。

Phase 2 diagnosis baseline: Product tree
`77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443`, baseline commit
`2ce622b86ec4aa9b6df7dc79243159eca3ceb8a0`, with Phase 2B diagnostics anchored by
`dc3267142fdc9c5bcd7061c55c1a0242e62663af`. B1 remediation baseline: Product tree
`f9d6f6ebf90712160441c3d57835131851ece12c945670cc607c225e22566344`, source commit
`c1895e37defe5effbb5ce489613d0528dc8f3fd5`. B2 remediation baseline: Product tree
`a93268d94a73e5aee53150ca4be9bbc5f37f76d0173c5be72633cc54cf2ea382`, source commit
`28fa9211d54032243eac3aac6a3819aca41bff2b`. Phase 2C-1 diagnosis uses the same
Product tree with source commit `fa16bb7c1b28b16b15c1800df86999804e729d3b`. Results were verified on
2026-09-20.

| Item | State | 当前证据/下一步 |
| --- | --- | --- |
| process-local task continuity/state | NEEDS_REVALIDATION | 复核 OpenWorker restart、task identity 与持久化边界 |
| cache-miss Host continuation | NEEDS_REVALIDATION | 复核 Host/MCP continuation contract；不得隐式扩大 retrieval |
| validation-token TTL vs capsule lifecycle | FIXED | [`docs/revalidation/context-validation-lifecycle/REVALIDATION.md`](revalidation/context-validation-lifecycle/REVALIDATION.md); diagnosis FAIL is preserved, while current-tree validation reads authoritative capsule lifecycle, clamps lease expiry, and exact-refreshes lifecycle misses |
| projection purge/rebuild | FIXED | [`docs/revalidation/projection-purge-rebuild/REVALIDATION.md`](revalidation/projection-purge-rebuild/REVALIDATION.md); targeted PostgreSQL execution passed, including rebuild-after-revoke non-resurrection |
| confirmation binding to query/action | FIXED | [`docs/revalidation/confirmation-binding/REVALIDATION.md`](revalidation/confirmation-binding/REVALIDATION.md); diagnosis FAIL is preserved, while current-tree remediation binds tenant/query/goal/scope/authority/action digest and passes replay, expiry, revoke, and readability regressions |
| OpenWorker HTTP auth/exposure | OPEN | [`docs/revalidation/openworker-http-exposure/REVALIDATION.md`](revalidation/openworker-http-exposure/REVALIDATION.md); bearer 与 auth-before-parse 已闭合，但 executable 接受 wildcard bind，且 plain HTTP 可经非 loopback interface 到达；token 文件替换的在线 revocation 语义仍待 owner contract 明确 |
| resolver lexical-language assumptions | NEEDS_REVALIDATION | 只做诊断，不在重组 PR 调 lexical/ranking |
| Runtime vs Host/provider trace ownership | NEEDS_REVALIDATION | 固定 trace owner、span 关联和 payload 脱敏边界 |
| worker --once docs/behavior | NEEDS_REVALIDATION | 对照真实 CLI、lease、退出码与 runbook |
| CAS blob-first orphan possibility | FIXED | [`docs/revalidation/cas-blob-orphan/REVALIDATION.md`](revalidation/cas-blob-orphan/REVALIDATION.md); forced DB failure, real worker startup cleanup, recovery ingest, and replay passed |

重组完成报告必须逐项列出最终状态。任何需要行为修复的条目另开独立 Goal/PR，不能在
结构性整理中顺手改变检索、排序、阈值、预算、Prompt、Schema 或迁移。
