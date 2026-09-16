# MiLAi Logical Objects

> Architecture `1.0.0 FROZEN`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文是逻辑对象、身份、所有权和可变性的规范定义。数据库表是当前物理实现，不反向定义
对象语义。

## 1. 通用规则

1. 除 `runtime_metadata` 外，每个 durable row 都属于一个 `tenant_id`。
2. 对象 ID 在 tenant 内稳定；可枚举 ID 不授予访问权。
3. append-only 对象只允许 insert；勘误以新记录表达。
4. canonical 对象只可由 Steward procedure 改变，API、worker、模型和 adapter 无 direct DML。
5. 派生对象可以重建或清除，但不能提升 truth、authority 或 freshness。
6. `MemoryIntention` 在 v1 保持 `PARKED`，不得以未治理快捷表形式进入 schema。

## 2. 对象目录

| Logical object | Current durable form | Identity | Mutability | Writer | Authority |
| --- | --- | --- | --- | --- | --- |
| RuntimeMetadata | `milai.runtime_metadata` | key | migration/operations controlled | migration owner | operational |
| OperationalEvent | `milai.operational_event` | tenant + event ID | append-only | approved application/procedure | audit fact |
| ContentBlob | `milai.content_blob` + blob root | tenant + blob ID; content hash dedup key | physical state only | Evidence service / purge worker | content carrier, not observation |
| EvidenceRecord | `milai.evidence_record` | tenant + evidence ID | immutable capture; governed lifecycle fields | Evidence/Revoke procedure | source observation |
| IdempotencyRecord | `milai.idempotency_record` | tenant + family + key | immutable fingerprint/result | transactional command path | replay control |
| OutboxEvent | `milai.outbox_event` | tenant + outbox ID / outbox sequence | append-only payload; leased delivery status | same mutation transaction | delivery fact |
| Claim | `milai.claim` | tenant + claim ID | identity immutable | Steward procedure | stable belief identity |
| ClaimVersion | `milai.claim_version` | tenant + version ID | append-only | Steward procedure | governed belief version |
| ClaimHead | `milai.claim_head` | tenant + claim ID | exact-head CAS only | Steward procedure | current pointer, not validity |
| VersionTransition | `milai.version_transition` | tenant + transition ID | append-only | Steward procedure | evolution history |
| GroundingRelation | `milai.grounding_relation` | tenant + relation ID | append-only | Steward procedure | lineage edge |
| GroundingBlock | `milai.grounding_block` | tenant + block ID | append-only; never removed to revive history | Revoke/Steward procedure | use prohibition |
| EffectiveClaimState | SQL view/function result | tenant + version + evaluation instant | computed only | none | sole current/readability decision |
| OperationProposal | `milai.operation_proposal` | tenant + proposal ID | submission is append-only input; review result changes only in Steward procedure | application then Steward procedure | non-canonical proposal |
| StewardDecision | `milai.steward_decision` | tenant + decision ID | append-only | Steward procedure | governance fact |
| OpenIssue | `milai.open_issue` | tenant + issue ID | revision CAS | Steward procedure | canonical unresolved state |
| OpenIssueTransition | `milai.open_issue_transition` | tenant + transition ID | append-only | Steward procedure | issue history |
| LegacyIssueTransitionQuarantine | `milai.legacy_issue_transition_quarantine` | tenant + original transition ID | insert during offline forward migration; UPDATE/DELETE rejected | Migration Owner only | exact evidence of an invalid legacy effect; **not canonical history or authority** |
| LegacyGroundingRelationQuarantine | `milai.legacy_grounding_relation_quarantine` | tenant + original relation ID | insert during offline forward migration; UPDATE/DELETE rejected | Migration Owner only | exact evidence of rejected pre-Decision grounding; **not canonical lineage or authority** |
| ContextCapsule | `milai.context_capsule` | tenant + capsule ID | immutable payload; status/TTL invalidation | context assembler / revoke | bounded non-canonical view |
| ContextPointer | `milai.context_pointer` | tenant + pointer ID | invalidation only | context assembler / revoke | recoverable content reference |
| DeletionRequest | `milai.deletion_request` | tenant + request ID | monotonic phase progress | Revoke procedure / purge worker | deletion workflow fact |
| ProjectionDelivery | `milai.projection_delivery` | tenant + projection + outbox | lease/retry state machine | projection worker | delivery state |
| IndexWatermark | `milai.index_watermark` | tenant + projection | contiguous monotonic sequence | projection worker | lag indicator |
| SearchDocument | `milai.search_document` | tenant + document ID + projection version | replaceable projection | projection worker | candidate only |
| SearchEmbedding | `milai.search_embedding` | tenant + document/model/version | replaceable projection | projection worker | candidate only |
| RetrievalTrace | `milai.retrieval_trace` | tenant + trace ID | append-only plan/result/causal-wait envelope | retrieval application | replay/audit trace |
| ChatTurn | `milai.chat_turn` | tenant + turn ID | append-only | chat application | answer record, not truth |
| BackupManifest | `milai.backup_manifest` | tenant + backup ID | append-only completion/failure state | audit runner | recovery evidence |
| BackupDeletionObligation | `milai.backup_deletion_obligation` | tenant + backup + evidence/blob | reconciliation lifecycle | backup/reconciliation path | deferred deletion duty |
| Episode | `milai.episode` | tenant + episode ID | immutable boundary snapshot | episode service | governed boundary |
| EpisodeSettlement | `milai.episode_settlement` | tenant + settlement ID | append-only | Steward procedure | governed conclusion |
| EpisodeTransition | `milai.episode_transition` | tenant + transition ID | append-only | episode/Steward procedure | episode history |

## 3. 聚合边界

### Evidence Aggregate

`EvidenceRecord` 表示一次观察，`ContentBlob` 表示正文载体。相同 tenant 内相同正文可共享 Blob，
但每次独立观察必须拥有独立 Evidence ID、source、observed time 和 capture identity。
`DeletionRequest` 编排逻辑撤销到派生数据、正文与备份的传播。

### Claim Aggregate

`Claim` 是稳定身份；`ClaimVersion` 保存各版 belief；`ClaimHead` 仅指出最新治理版本。
`GroundingRelation` 连接 Evidence、Issue 和版本；`GroundingBlock` 禁止已失效 grounding 被再次使用。
是否可用于某次读取只能由 `EffectiveClaimState` 判定。

### Governance and OpenIssue Aggregate

`OperationProposal` 记录建议及 observed snapshot，`StewardDecision` 记录批准或拒绝。提交 proposal
本身绝不改变 Claim、Head、OpenIssue、grounding 或 canonical history；只有 Steward `APPROVE`
事务才能把 resolution proposal 原子兑现为新 ClaimVersion、grounding、Issue revision/transition、
Decision、event 与 outbox。`REJECT` 只形成治理事实并保持 Issue 原状态。

`OpenIssue` 用稳定 ID 保留冲突、缺证或 scope/authority 未决状态；首次创建必须写
`OpenIssueTransition(ISSUE_CREATED, from_status=NULL, revision 0→1)`，resolution 和 reopen 继续增加
transition，不换 issue ID。CONTRADICT branches 使用 `GroundingRelation` 保存。

Candidate.1 的非法 pre-Decision/null-governance transition 与 rejected resolution grounding 都不能留在
canonical replay/lineage，也不能静默删除或补造 authority。Corrected migration 0024 只有在真实
Proposal/Decision/actor/sequence/Outbox provenance 以及 Proposal distinct support set 可证明时才修复；
原 transition 与 relation 的所有原始字段及可重算 SHA-256 分别原子移入两个 legacy quarantine
ledger。Canonical Issue 只保留 governed classification/reversal，canonical resolution grounding
仅在真实 `APPLIED` Proposal + `APPROVE` Decision + matching Issue/support 链完整时保留。两个隔离
账本都不参与 revision replay、ECS、Gate、Issue/Context 或任何 authority decision；无法证明的 fresh
输入使 0024 整体回滚到 0023，已经执行 candidate.3 0024 的开发库由 0025 重复证明后兼容；
已经执行 candidate.4 0025 的开发库还必须由 proof-only 0026 重新认证完整 TX-05 事务时间。

### Episode Aggregate

`Episode` 冻结 Evidence、ChatTurn 和 ContextCapsule 引用；`EpisodeSettlement` 保存经 Steward
批准的结论、live issue 与至多三个 residual proposal reference。settlement 不得自动创建
ClaimVersion。

### Non-authoritative support domains

检索、Context、Chat、projection、embedding、外部 memory 和模型输出都是支持域。支持域只能提供
candidate、视图或 trace；所有 candidate 必须解析回 canonical ID/version 并通过 Gate。

## 4. 关系与基数

```text
ContentBlob 1 <- 0..n EvidenceRecord
EvidenceRecord n <-> n ClaimVersion       through GroundingRelation
Claim 1 <- n ClaimVersion
Claim 1 -> 1 ClaimHead -> 1 ClaimVersion
ClaimVersion 1 <- n VersionTransition (V1 CREATE has old_version_id = NULL)
Claim/OpenIssue/Evidence 1 <- n GroundingBlock
OperationProposal 1 <- 0..n StewardDecision
OpenIssue 1 <- n OpenIssueTransition
OpenIssue 1 <- 0..n LegacyIssueTransitionQuarantine (audit-only, outside canonical replay)
OpenIssue 1 <- 0..n LegacyGroundingRelationQuarantine (audit-only, outside canonical lineage)
Canonical mutation 1 -> 1..n OutboxEvent
OutboxEvent 1 -> 0..n ProjectionDelivery
RetrievalTrace 1 -> 0..n ContextCapsule -> 0..n ChatTurn
EvidenceRecord 1 -> 0..n DeletionRequest -> 0..n BackupDeletionObligation
Episode 1 -> 0..n EpisodeSettlement and EpisodeTransition
```

所有跨对象关系都同时携带或验证 tenant；不得仅凭 UUID join。

## 5. 正交状态轴

ClaimVersion 的状态至少保持以下正交轴：

```text
lifecycle       ACTIVE | SUPERSEDED | ARCHIVED | DELETED
epistemic       PROVISIONAL | VERIFIED | CHALLENGED | UNPROVABLE
freshness       CURRENT | STALE
authority       INFORMATIONAL | ACTION_SAFE | USER_CONFIRMED
confidence      bounded support signal
scope           versioned predicate
valid_time      real-world applicability interval
system_time     database-recorded interval/instant
```

任一轴不得从另一轴推导。`ACTIVE + CHALLENGED + STALE + INFORMATIONAL` 是合法组合；
Head 指向某版本不表示它满足当前请求。

从 candidate.1 前向升级时，有限旧值只允许以下确定性映射：`RETIRED→ARCHIVED`、
`SUPPORTED→VERIFIED`、`WEAKENED→CHALLENGED`、`UNCERTAIN→PROVISIONAL`、`UNKNOWN→STALE`。
未知值必须使整个事务回滚，不能静默归一化。

## 6. Authority matching

Authority 是请求与 claim 属性的匹配关系，而非简单总序：

| Request | Required match |
| --- | --- |
| INFORMATIONAL | live、readable、scope/time 匹配的版本 |
| USER_CONFIRMED | 明确 `USER_CONFIRMED` 且 lineage live |
| ACTION_SAFE | 明确 `ACTION_SAFE` 且无 live block/conflict |
| ACTION_SAFE + confirmation | 上项以及新鲜、可读、未撤销、内容绑定的 confirmation Evidence |

`USER_CONFIRMED` 不自动高于 `ACTION_SAFE`，confidence 也不能提升 authority。

## 7. 物理覆盖审计

当前 migration head `0026_legacy_tx05_time_guard` 下有 32 张 durable 表，其中
`runtime_metadata` 是全局运行元数据，其余 31 张均为 tenant-owned。冻结评审必须从 catalog
重新枚举；本清单与 catalog 不完全相等即失败。
