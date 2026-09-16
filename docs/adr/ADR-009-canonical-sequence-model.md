# ADR-009：Canonical Commit 与 Projection Sequence

> 状态：`ACCEPTED FOR 1.0.0-candidate.2`  
> 日期：`2026-08-16`  
> 兼容项：`RENAMED BY 0014; CAUSAL CONTRACT CLOSED BY 0018/0020`

## Decision

- 正式 Claim/OpenIssue/grounding governance mutation 在数据库内取得单调
  `canonical_commit_seq`，用于治理历史和 ClaimVersion 排序；
- 每个产生 Outbox 的 mutation（包括 TX-01、Episode）取得独立单调 `outbox_sequence`，
  用于 delivery、projection snapshot 和 read-your-writes；
- governance mutation 的 Outbox 同时携带其 canonical sequence；非 belief mutation 可以为空，
  不能伪造 canonical position；
- projection delivery 以 outbox ID 幂等，watermark 只推进连续且 durable 的 outbox sequence；
- dead-letter gap 不得越过；
- `READ_YOUR_WRITES` 等待 `minimum_outbox_sequence`，超时转 canonical fallback；
- 两条 sequence 都表示各自域的 system recording order，不替代 valid time、authority、causality
  或事务 ID。

TX-01 Evidence 是 observation capture，不是 canonical belief commit，因此其
`canonical_commit_seq = NULL` 是明确语义，不是缺失。migration
`0014_query_plan_outbox_sequence` 将 QueryPlan 的旧歧义字段迁移为
`minimum_outbox_sequence`；无需篡改或重排历史 sequence。

Candidate.2 不接受 caller 自报序号。客户端把本次写入返回的 Outbox ID 交给
`POST /v1/causal-tokens`；API 经 tenant-scoped 安全函数解析真实最大 Outbox sequence，再用独立、
仅服务端持有的 HMAC secret 签发 tenant-bound opaque token。RYW 请求必须携带该 token；伪造、
错误密钥、跨 tenant、未知或未来位置拒绝。L1 对 FTS/vector 连续水位执行有界等待；达到、超时、
dead-letter 和等待毫秒数写入 QueryPlan/RetrievalTrace。超时或 dead-letter 走 canonical fallback，
并发 snapshot 前进则合并 canonical candidate，但仍由请求固定的 system time Gate。

## Consequences

worker 并行不改变对外顺序承诺；重建 projection 复用原 outbox sequence。任何跨
region/global ordering 需求属于未来架构版本。
