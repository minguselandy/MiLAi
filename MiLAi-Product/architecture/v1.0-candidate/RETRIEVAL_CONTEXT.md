# MiLAi Retrieval, Context, and Answer Protocol

> Architecture `1.0.0-candidate.5`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

## 1. Read-path authority

PostgreSQL canonical state plus `EffectiveClaimState` (ECS) is the only authority decision source.
FTS、pgvector、graph、cache、Context、summary、LLM 与外部 memory 仅产生 candidate。它们可以增加
recall，不能改变 truth、authority、freshness、Scope 或 issue status。

Canonical store 不可用时，authority query 返回 `CANONICAL_UNAVAILABLE` 或 abstain，不得回退到
旧 cache 冒充 current。

## 2. QueryPlan contract

每次 memory query 都生成并持久化或嵌入 `RetrievalTrace` 的版本化 typed plan：

```yaml
planner_version: lean-query-plan-v2
intent: EXACT_CURRENT | HYBRID_SEARCH
entities: [typed-or-hashed-entity]
time_constraint: null
scope_predicate:
  version: "1"
required_authority: INFORMATIONAL
required_lifecycle: ACTIVE
accepted_epistemic_statuses: [VERIFIED, PROVISIONAL]
required_freshness: CURRENT
minimum_confidence: 0.0
require_user_confirmation: false
complexity: L0
consistency_mode: EVENTUAL
minimum_outbox_sequence: null
context_budget: 8000
routes: [L0]
query_fingerprint: sha256
```

`time_constraint` 必须同时保存 `valid_as_of` 与 `system_as_of`。Query 明文不写 trace/log。可选模型
只能解释 query；确定性 validator 必须校验 enum、route、预算、scope schema、所有状态轴、confidence
与 authority 组合。模型失败或输出非法时安全回退 L0/L1，不自动扩大 scope 或 authority。

## 3. Routes

| Route | Source | Purpose | Candidate status |
| --- | --- | --- | --- |
| L0 Exact/Current | Claim identity、Head、ECS | 精确实体、当前状态 | enabled |
| L1 Hybrid | metadata/time/scope、FTS、pgvector | 关键词/语义召回 | enabled |
| L2 Reconstructive | lineage、Episode、optional graph/shadow | 复杂时间、多跳、冲突重建 | disabled by default |

L1 固定执行：

```text
metadata/time/scope prefilter
→ FTS and/or pgvector candidate recall
→ score normalization and deterministic deduplication
→ canonical claim/version ID resolution
→ Canonical Gate
→ Evidence Bundle and trace
```

任一 candidate 缺 canonical ID、tenant 或 source reference 即丢弃。route 故障只降低 recall，并在
trace 标记 `degraded_routes`。

L2 只有在 ADR、固定 benchmark、数据策略和 failure drill 全部通过后才能按 tenant/feature flag
开启；其输出仍进入同一 Gate。

## 4. Canonical Gate checklist

对每个 candidate 在同一 canonical read snapshot 中检查：

1. tenant、subject 与请求一致；
2. caller permission 和 retention readability；
3. Evidence 未撤销且 Blob 状态可用；
4. 指向当前 Head，或请求明确允许某历史版本；
5. 无 applicable `GroundingBlock`；
6. Scope predicate 匹配；
7. valid time 与 `valid_as_of` 匹配；
8. system time 与固定 `system_as_of` snapshot 匹配，不能冒充 valid time；
9. lifecycle 等于 `required_lifecycle`；
10. epistemic 位于 `accepted_epistemic_statuses`；
11. freshness 等于 `required_freshness`；
12. confidence 不低于 `minimum_confidence`，且不能提升任何其他轴；
13. live OpenIssue/conflict 对当前 use 不构成阻断；
14. required authority 明确匹配；
15. Evidence lineage 完整且可读；
16. action request 的 live confirmation Evidence 匹配。

未知 ID、cross-tenant、stale version、revoked lineage、unknown retention 或无法证明任一请求轴时拒绝。
Gate 输出逐轴 reason code。所有 decision facts 只能来自 ECS；SQL Gate、Context revalidation 与 Chat
不得复制或绕开状态判定。Confidence 只通过显式 minimum threshold，永远不补偿状态或 authority。

## 5. Consistency

| Mode | Contract |
| --- | --- |
| EVENTUAL | 允许落后 projection；trace 写 watermark、lag 与 degraded route |
| READ_YOUR_WRITES | 必须提供服务器针对真实 Outbox ID 签发的 tenant-bound token；等待其 position；超时/dead-letter 转 canonical search，不降低 Gate |
| CANONICAL_REQUIRED | current、权限、删除、ACTION_SAFE 只读 canonical snapshot |

Projection watermark 必须连续。dead-letter gap 后的较新 document 即使可见，也不能声称 projection
已追平。

客户端不能自行声明 sequence。`POST /v1/causal-tokens` 只接受当前 tenant 的真实 Outbox ID，并通过
窄 SECURITY DEFINER summary function 解析 position；API 角色无 Outbox 原表读取权。Token 使用独立
server-only HMAC secret，不能复用 Bearer token。伪造、错 key、跨 tenant、未来或未知 position 均
拒绝。等待后若 canonical snapshot 前进，L1 必须合并 canonical search，同时固定原请求
`system_as_of`，防止投影结果遗漏并发提交。

## 6. RetrievalTrace

trace 至少保存：

- plan version、query fingerprint、tenant、actor/request fingerprint；
- route set、projection versions、watermarks、candidate counts；
- canonical snapshot/commit sequence；
- minimum outbox sequence、causal wait outcome 与实际 waited milliseconds；
- per-candidate accept/reject reason；
- ClaimVersion、Evidence、OpenIssue refs；
- degraded/abstained status、latency 与 bounded cost；
- adapter/model/version（若使用），不含原始 query/prompt/正文。

trace 是回放证据，不是 canonical truth。

## 7. ContextCapsule

Capsule 固定六分区：

```text
[1] ACTIVE GOAL
[2] ACTIVE STATE
[3] OPEN ISSUES
[4] CONSTRAINTS
[5] RETRIEVED EVIDENCE
[6] TRACE POINTERS
```

Protected items：

- active Goal 与 hard constraints；
- Gate-approved current ECS；
- 每个 live OpenIssue 的 ID、target、status、revision、branches、discharge rule；
- authority/permission/retention envelope；
- required lineage pointers。

上下文装配器可压缩 wording，不能删除、合并身份或改变 protected semantics。

## 8. Budget feasibility

```text
B_min =
  goal/constraints minimum
  + current ECS minimum
  + every live issue identity/branches/discharge minimum
  + authority envelope and required pointers
```

`context_budget < B_min` 时返回 `CONTEXT_BUDGET_INFEASIBLE` 或 abstain；不得通过丢弃冲突 branch、
live issue 或安全限制来“成功”。压缩策略和 token estimator version 写入 Capsule。

## 9. Pointer recovery

每次从 `ContextPointer` 恢复正文都重新验证：

```text
object ID and content hash
tenant and caller permission
retention and legal hold
Evidence revocation and GroundingBlock
Blob physical state
Capsule TTL/status and invalidation sequence
```

任何 unknown/mismatch 返回受控失败；不从旧 cache 或外部 memory 返回正文。

Context 中的 ClaimVersion revalidation 必须调用与检索相同、axis-complete 的 ECS/Gate；不得用
“仍是 Head”或旧的 accepted reason 替代本次 lifecycle/epistemic/freshness/confidence/bitemporal
判定。

## 10. Traceable Chat

Chat 只消费 Gate 后 Capsule。每个 `ChatTurn`/answer 保存：

- ClaimVersion、Evidence、OpenIssue refs；
- RetrievalTrace ID、ContextCapsule ID；
- query fingerprint；
- consistency、degraded、abstained 状态；
- answer composer/policy version。

没有充分 lineage 的陈述必须标记 provisional 或 abstain。

## 11. Live action confirmation

action-sensitive answer 需要：

- underlying Claim 明确 `ACTION_SAFE`；
- 无 live issue/block；
- 五分钟内的新鲜 `USER_CONFIRMATION` Evidence；
- confirmation 的 tenant、actor/source/ref、subject、content hash 和 requested action 全部匹配；
- 在最终 Gate snapshot 中仍 live/readable/unrevoked。

字符串 `CONFIRM_ACTION`、旧 ChatTurn、UI 状态或高 confidence 均不构成确认。

## 12. External candidate routes

ReMe 用于离线 Context baseline；Hindsight/Mem0 用于 shadow recall；Graphiti 用于 temporal graph
candidate；benchmark 项目只用于 EvaluationAdapter。所有外部 route 默认关闭，独立目录/namespace/
watermark，无 Steward credential，可完全移除且不影响 L0、revoke、backup 或 startup。

## 13. Required failure tests

- vector/FTS/adapter unavailable 只降低 recall；
- canonical unavailable 时不能返回 authority answer；
- stale projection、revoked Evidence、historical version、scope/time mismatch 被拒；
- 每个 lifecycle/epistemic/freshness/confidence/valid/system axis 的 mismatch 独立被拒；
- RYW missing/forged/wrong-key/cross-tenant/future/unknown token 被拒，timeout/dead-letter 可证明地
  canonical fallback，snapshot advance 合并并发 canonical candidate；
- low budget 不丢 live issue；
- invalidated pointer 不恢复 bytes；
- forged/expired/mismatched confirmation 被拒；
- trace 可重放到 Claim/Evidence/Issue 和 gate reasons。
