# MiLAi Canonical Transaction Protocol

> Architecture `1.0.0 FROZEN`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

## 1. 总合同

canonical write path 固定为：

```text
typed command
→ immutable Evidence capture
→ DeriveAndDiagnose candidate
→ proposal validation
→ CommitPolicy / explicit review
→ Steward procedure live revalidation
→ atomic canonical mutation + Decision + OperationalEvent + Outbox
```

LLM、embedding、外部 memory、网络调用和长耗时计算必须在 canonical database transaction 外。
事务使用数据库时间、适用的 canonical/outbox sequence 和 transaction-scoped tenant/actor。

## 2. TX-01 Evidence Ingest

**Preconditions**

- authenticated tenant/actor；
- typed source、observed time、content、retention/permission inputs；
- idempotency key 与 deterministic request fingerprint。

**Atomic writes**

- content hash 与 tenant-scoped `ContentBlob` identity；
- 新 `EvidenceRecord`；
- `IdempotencyRecord`、`OperationalEvent`、`OutboxEvent`。

同 key+同 fingerprint 返回原结果；同 key+不同 fingerprint 返回 `IDEMPOTENCY_CONFLICT`。
重试不得覆盖 source、observed time、capture identity 或 content hash。

## 3. TX-02 Claim Create

**Preconditions**

- normalized claim identity 不存在（absence-CAS）；
- supporting Evidence live/readable 且 tenant/scope/time 匹配；
- validated CREATE proposal 与 APPROVE decision；
- requested authority 被 policy 明确允许。

**Atomic writes**

- `Claim`、V1 `ClaimVersion`、`ClaimHead`；
- support `GroundingRelation`；
- proposal result、`StewardDecision`、`VersionTransition(CREATE, old_version_id=NULL)`；
- `OperationalEvent` 与 `OutboxEvent`。

identity 或 version race 失败时全部回滚，不得残留孤立 history/outbox。

## 4. TX-03 Claim Revision

**Preconditions**

- proposal observed Head 等于 caller 的 expected Head；
- 当前 Head 与 live ECS 在 procedure 内再次读取；
- UPDATE proposal 与 APPROVE decision；
- Evidence、Scope、time、authority 和 block 检查通过。

**Atomic writes**

- 新 immutable `ClaimVersion`；
- `VersionTransition` 与新 grounding；
- `ClaimHead` exact compare-and-swap；
- decision/result/event/outbox。

CAS loser 返回 `VERSION_CONFLICT`，整个事务回滚。不得先 insert 新版本后单独移动 Head。

## 5. TX-04 No Change / Conflict

NO_CHANGE：

- 不创建 ClaimVersion、不移动 Head；
- 可记录 proposal/decision/result/event；
- 同一 idempotency replay 返回同结果。

CONFLICT：

- 默认不移动 Head；
- 创建或 revision-CAS 更新稳定 `OpenIssue`；
- 保存 supporting/contradicting branch grounding 和 discharge rule；
- append `OpenIssueTransition`、decision、event、outbox。

首次创建 Issue 必须写 `ISSUE_CREATED` transition（`from_status=NULL`、revision `0→1`）。Resolution
proposal submission 是非 canonical 事实，不得把 Issue 推到 `READY_FOR_REVIEW`，也不得创建
ClaimVersion/grounding。只有 resolution review 的 `APPROVE` 分支可在同一事务中写新版本、Head CAS、
grounding、`DISCHARGE_APPROVED` transition、Issue `RESOLVED`、Decision、event 和 outbox；`REJECT`
保持 Issue 状态与 revision 不变。并发 review 通过 expected revision CAS 只允许一个 winner。

summary、相似度、时间经过或某 branch 未召回都不是 issue resolution。

## 6. TX-05 Evidence Revoke

**Preconditions**

- Steward authorization；
- target Evidence 在当前 tenant 可见且尚未撤销；
- retention/legal-hold policy 已知；unknown fail closed；
- typed reason、idempotency 和 deletion intent。

**Synchronous atomic writes**

- typed `REVOKE_EVIDENCE` `OperationProposal`；
- Evidence logical revoke；
- 每个受影响版本/grounding 的 `GroundingBlock`；
- active `ContextCapsule`/pointer invalidation；
- `DeletionRequest` 初始/推进状态；
- `StewardDecision`、operational event、high-priority purge/re-ground outbox；
- proposal、decision、transition、event 与 outbox 共享本次 governance 的 canonical sequence。

提交后 authority 立即失效，不等待 worker。物理派生数据、eligible Blob 和备份 obligation 由异步流程
完成并可审计。

## 7. TX-06 Grounding Restore

**Preconditions**

- 新的 live/readable Evidence，而非删除旧 block；
- affected claim/current Head 和 block 在 procedure 内重验；
- APPROVE decision、expected Head；
- 相关 OpenIssue effect 明确。

**Atomic writes**

- 新 ClaimVersion、transition 和 grounding；
- Head CAS；
- governed OpenIssue transition（若 discharge 条件满足）；
- decision/event/outbox。

旧 ClaimVersion 和 GroundingBlock 保留；禁止“解除 block”使旧版原地复活。

## 8. EP-01 Episode Capture

- typed Evidence/ChatTurn/ContextCapsule refs 全部 tenant/readability 校验；
- 冻结边界快照，写 `Episode`、capture transition、event/outbox；
- idempotency replay 稳定；
- 不修改 Claim/OpenIssue。

## 9. EP-02 Episode Settlement

- Steward-only，expected episode revision CAS；
- 校验 referenced Episode 和 live issue；
- append `EpisodeSettlement` 与 transition；
- residual proposal refs 最多三个，Context 过期；
- settlement 本身不自动提交任何 ClaimVersion。

## 10. Populated forward reconciliation protocol

Corrected migration 0024 是 fresh populated input 的离线、单事务、forward-only 兼容协议；0025 是
已经执行 candidate.3/0024 开发库的前向 compatibility guard；proof-only 0026 认证已经执行
candidate.4/0025 的开发库。三者都不是常驻 canonical 写入口：

```text
stop serving + acquire ACCESS EXCLUSIVE governance/provenance locks
→ prove all V1/Issue/pre-Decision/TX-05 source shapes from durable facts
→ prove Proposal distinct support set equals the exact Issue-owned resolution relation set
→ join the actual tenant-scoped DeletionRequest for every legacy TX-05
→ choose DeletionRequest.requested_at as the original transaction-time anchor
→ require Evidence.revoked_at and idempotency/OperationalEvent/revoke Outbox/purge Outbox created_at exact equality
→ fail whole migration on any unknown/conflicting provenance
→ backfill source-linked V1 CREATE and ISSUE_CREATED sentinels
→ atomically move exact invalid transition/rejected relation rows + SQL SHA-256 to separate immutable ledgers
→ write governed classification/replacement and, for pending legacy resolution, POLICY REJECT + CAS reversal
→ validate constraints, continuous replay and approved-only canonical grounding postconditions
→ commit or roll back every migration effect
```

Proof requires the relevant Proposal/Decision/actor/canonical sequence/original Outbox. Legacy TX-05 additionally
requires a mutually consistent actual DeletionRequest, Evidence/Blob/revocation, requester/creator/reason and
state axes, idempotency result, OperationalEvent, original revoke Outbox and paired purge Outbox. The request,
Evidence revoke, idempotency, OperationalEvent and both Outbox legs must expose one exact PostgreSQL transaction
timestamp; proximity or agreement among a subset is insufficient. Agreement among
JSON UUID references to a missing request is not proof and raises `AF09_UNPROVABLE_LEGACY_TX05`. A fixed
reconciliation policy actor may only `REJECT` an unauthorized pending effect—it cannot fabricate historical
approval or elevate authority. Rejected relations are exact-hash preserved outside canonical lineage; approved
relations remain only with an actual `APPLIED` Proposal/`APPROVE` Decision linked to the same Issue/support set.
Neither quarantine ledger can be queried by ECS/Gate/Issue/Context as history or authority.

Every ClaimVersion must end with exactly one incoming VersionTransition. Every Issue must have one transition
for each revision from 0 to its current revision, exactly one `ISSUE_CREATED`, and no canonical transition with
NULL Proposal/Decision/policy/sequence. Constraint validation is part of the same transaction; failure leaves
the database at the prior Alembic revision. A bad fresh 0014 chain therefore remains at 0023 with no 0024 residue;
a bad already-applied candidate.3 database remains at 0024 with no 0025 residue; a bad already-applied candidate.4
database remains at 0025 and receives no 0026 certification or new authority.

## 11. Sequence and ordering model

1. TX-02～TX-06 的正式 Claim/OpenIssue governance 获得单调 `canonical_commit_seq`；
2. 每个 OutboxEvent 获得独立、全局单调 `outbox_sequence`；
3. governance Outbox 同时携带 canonical sequence；TX-01/Episode 的 canonical sequence 可为空；
4. worker delivery 以 `(tenant, projection, outbox_id)` 幂等；
5. watermark 只推进到连续、durably delivered 的最高 outbox sequence；
6. dead-letter gap 未修复前不能越过；
7. 写事务提交后，客户端用真实 Outbox ID 向窄 API 换取 tenant-bound causal token；
8. read-your-writes 验证 token 后等待其 `minimum_outbox_sequence`，超时或 dead-letter 转 canonical
   fallback，并把 wait outcome/耗时写入 RetrievalTrace；
9. sequence 表示各自域的记录顺序，不替代 valid time、authority 或 causality。

## 12. Abort and error contract

| Condition | Stable result |
| --- | --- |
| idempotency fingerprint mismatch | `IDEMPOTENCY_CONFLICT` |
| expected Head changed | `VERSION_CONFLICT` |
| expected issue revision changed | `ISSUE_REVISION_CONFLICT` |
| revoked supporting Evidence | `EVIDENCE_REVOKED` |
| active block | `GROUNDING_BLOCKED` |
| scope/time mismatch | `SCOPE_MISMATCH` / `SCOPE_TIME_CONFLICT` |
| authority not explicitly matched | `AUTHORITY_INSUFFICIENT` |
| permission/retention/canonical unknown | deny / `CANONICAL_UNAVAILABLE` |
| legacy provenance unknown/conflicting | abort migration with stable `AF09_*` error; no partial repair |

所有失败必须无部分 canonical writes；错误响应不得泄露正文、凭据或 cross-tenant existence。

## 13. Required concurrency and migration evidence

至少验证：duplicate ingest、absence-CAS create race、exact-head revision race、issue revision race、
revoke vs read、revoke vs restore、outbox duplicate lease、dead-letter watermark gap、episode settlement
race。还必须验证 proposal submission 不改变 Issue、reject 保持 Issue、TX-05 governance chain、
强制故障无 proposal/decision/event/outbox 残留。每个 race 必须证明唯一 winner、loser rollback 与
可重放 trace。还必须用真实 candidate.1 public procedures 在 0014 创建 V1、conflict、pending/
decided resolution 与 TX-05，再升级到 head 验证 exact support/hash quarantine、真实 Issue/Context 不
返回 rejected branch、批准 relation 与实际 Decision 链接、连续 replay、quarantine immutability 和
后续正常 review。DeletionRequest、actor、reason/status、idempotency、Evidence、OperationalEvent、
revoke/purge Outbox 必须逐腿破坏并证明 whole rollback；idempotency、OperationalEvent、revoke Outbox、
purge Outbox 四条时间腿还必须各自偏移一秒并分别 fail closed；同时重放有效/无效 candidate.3
0024→0025 与 candidate.4 0025→0026。
手工构造空数据库不能替代这些证据。
