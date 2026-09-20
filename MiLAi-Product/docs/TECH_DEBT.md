# Product Technical Debt Revalidation

历史报告中的问题不自动等于当前缺陷。下表是重组阶段的复核登记；状态只能使用
`OPEN`、`FIXED`、`OBSOLETE`、`NEEDS_REVALIDATION`。状态改变必须附命令、测试和日期。

Phase 2A baseline: Product tree `77b13141c2aed57802c4d89adbe9e4597defc430b77e5f9bc0d373c3a199a443`,
baseline commit `2ce622b86ec4aa9b6df7dc79243159eca3ceb8a0`, verified on 2026-09-20.

| Item | State | 当前证据/下一步 |
| --- | --- | --- |
| process-local task continuity/state | NEEDS_REVALIDATION | 复核 OpenWorker restart、task identity 与持久化边界 |
| cache-miss Host continuation | NEEDS_REVALIDATION | 复核 Host/MCP continuation contract；不得隐式扩大 retrieval |
| validation-token TTL vs capsule lifecycle | NEEDS_REVALIDATION | 复核 token、ContextCapsule、revocation 的生命周期交集 |
| projection purge/rebuild | FIXED | [`docs/revalidation/projection-purge-rebuild/REVALIDATION.md`](revalidation/projection-purge-rebuild/REVALIDATION.md); targeted PostgreSQL execution passed, including rebuild-after-revoke non-resurrection |
| confirmation binding to query/action | NEEDS_REVALIDATION | 复核 confirmation Evidence 的 query/action fingerprint |
| OpenWorker HTTP auth/exposure | NEEDS_REVALIDATION | 复核 bearer、loopback/TLS、scope、日志和 revocation |
| resolver lexical-language assumptions | NEEDS_REVALIDATION | 只做诊断，不在重组 PR 调 lexical/ranking |
| Runtime vs Host/provider trace ownership | NEEDS_REVALIDATION | 固定 trace owner、span 关联和 payload 脱敏边界 |
| worker --once docs/behavior | NEEDS_REVALIDATION | 对照真实 CLI、lease、退出码与 runbook |
| CAS blob-first orphan possibility | FIXED | [`docs/revalidation/cas-blob-orphan/REVALIDATION.md`](revalidation/cas-blob-orphan/REVALIDATION.md); forced DB failure, real worker startup cleanup, recovery ingest, and replay passed |

重组完成报告必须逐项列出最终状态。任何需要行为修复的条目另开独立 Goal/PR，不能在
结构性整理中顺手改变检索、排序、阈值、预算、Prompt、Schema 或迁移。
