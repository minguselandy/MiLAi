# MiLAi Deletion, Projection, Backup, and Recovery

> Architecture `1.0.0 FROZEN`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

## 1. Principle

删除不是一条 boolean。逻辑 authority 必须同步失效；派生数据、Blob 和历史备份按可证明状态异步
传播。系统只声明已经完成的层级，不把“已请求”报告成“已物理擦除”。

## 2. State dimensions

```text
logical_revocation
canonical_block_applied
context_invalidated
derived_purge_pending | running | completed | dead_letter
primary_bytes_retained | erased | shared_reference | policy_blocked
backup_expiry_pending | completed | policy_blocked
retention_or_legal_hold_clear | blocked | unknown
```

`unknown` 在 permission/retention 路径上 fail closed。每个阶段记录 actor、database time、reason、
attempt、error code 和关联 event/outbox。

## 3. Synchronous TX-05 boundary

单个事务内：

```text
revoke Evidence
→ create typed REVOKE_EVIDENCE Proposal
→ create immutable GroundingBlock for affected use
→ invalidate active ContextCapsule/ContextPointer
→ create or advance DeletionRequest
→ write StewardDecision and OperationalEvent
→ emit high-priority purge and re-ground OutboxEvent
```

commit 后 ECS/Gate 立即拒绝受影响 authority；不等待 projection worker、Blob erase 或 backup expiry。
事务任一步失败则全部回滚。

## 4. Asynchronous purge

优先级：

```text
permission invalidation / purge
→ grounding-impacting repair
→ FTS update
→ embedding rebuild
```

Worker 使用 lease、bounded retry、dead-letter 和 idempotent downstream key。它可以删除或重建
`SearchDocument`、`SearchEmbedding`、外部 projection 和过期 Context；不能修改 ClaimHead 或
OpenIssue。

共享 Blob 处理：

- 若同 tenant 仍有 live/readable Evidence 引用，标记 `shared_reference` 并保留 bytes；
- 无 live 引用且 retention/legal hold 允许时 erase，并返回 identity-bound durable-absence proof；
- policy unknown 或 blocked 时保留 bytes、authority 仍被阻断，并记录原因；
- cross-tenant Blob dedup 不允许。

## 5. Projection correctness

- canonical transaction 与 OutboxEvent 原子；
- delivery key 为 tenant + projection + outbox；
- watermark 仅在 durable delivery 后连续推进；
- dead-letter gap 不得跳过；
- rebuild 只能清理可重建派生状态；
- model/dimension/adapter version 改变产生新 projection version；
- purge route unavailable 时状态可见且 authority 仍由 canonical block 保证。

## 6. Backup preconditions

一致性备份要求：

1. API、Steward 和 worker 进入 quiescent/read-only window；
2. PostgreSQL 使用 repeatable-read exported snapshot；
3. 生成 PostgreSQL custom dump；
4. 同一逻辑 cut 复制完整 Blob root；
5. 记录 migration revision、dump/blob hashes、runtime/config revision；
6. 从 catalog 枚举所有 tenant-owned durable table；
7. catalog 与 inventory 配置必须完全相等；
8. 逐表记录 count 与 deterministic hash；
9. 验证当前部署仅包含目标 tenant；
10. 为已撤销但仍位于历史备份的 Blob 建立 `BackupDeletionObligation`。

当前 candidate 期望：Alembic `0026_legacy_tx05_time_guard`，31 张 tenant-owned durable tables。
其中 `legacy_issue_transition_quarantine` 保存 candidate.1 非法 Issue effect，
`legacy_grounding_relation_quarantine` 保存 rejected pre-Decision resolution grounding；两者都保存精确
原始列、可重算 SHA-256 与 reconciliation link，必须出现在 inventory/count/hash 中，但不计入
canonical Issue revision replay/lineage。
这只是基线，不可硬编码替代 catalog audit。

## 7. Backup manifest

manifest 至少包含：

```text
backup ID, tenant, status, created/completed time
database engine and migration revision
snapshot identity
dump path/size/sha256
blob root inventory and per-file hash
table catalog and per-table count/hash
application/config revision
deletion obligations
tool versions and command result
```

部分文件、hash mismatch、catalog mismatch 或 unknown tenant 范围必须将 backup 标记 failed。

## 8. Restore protocol

只恢复到新建的空数据库和空 Blob root：

1. 在写入前验证 archive、dump 和每个 Blob hash；
2. 创建隔离数据库/roles，不复用 production connection；
3. restore dump，验证 migration revision；
4. restore Blob 到空 root，再验证 hash；
5. 重新枚举 catalog；
6. 比较每表 count/hash 与全部 canonical ID/relation；
7. 特别核对 GroundingBlock、OpenIssue、Episode/Settlement、deletion obligations，以及两个
   quarantine ledger 的原始行 SHA-256、reconciliation links 和 append-only trigger；
8. 核对 projection delivery/watermark，必要时从 Outbox rebuild；
9. 以真实最小角色运行 RLS/security smoke；
10. 生成新的 restore report，不自动切换 production。

任何 archive tamper 必须在 database restore 前失败。

## 9. Recovery and forward repair

| Failure | Recovery |
| --- | --- |
| worker lease abandoned | lease timeout 后同 outbox ID 重试 |
| dead-letter gap | 修复原因并重放 gap；然后推进 contiguous watermark |
| derived index corruption | 清空指定 projection version，从 Outbox/canonical rebuild |
| Context stale after revoke | canonical block 保证拒绝；重放 invalidation/purge |
| Blob missing | metadata/identity 可保留；正文访问显式失败，不回退旧 cache |
| Blob erase 在 SQL completion 前 crash | 重试返回 `VERIFIED_ALREADY_ABSENT` proof；验证通过后才推进 ERASED |
| Blob proof forged/mismatched | completion 整体拒绝并 dead-letter；不改变删除完成状态 |
| backup obligation pending | 保留并报告 backup ID，直到 expiry/reconciliation |
| fresh migration partially deployed | corrected 0024 单事务回滚并保持 0023；修复 provenance 或从验证过的 pre-migration backup 恢复后再 forward upgrade，不伪造 head |
| already-applied candidate.3 compatibility fails | 0025 整体回滚并保持 0024；隔离该开发库，恢复/证明 durable source 后再升级，不能伪造 DeletionRequest |
| already-applied candidate.4 certification fails | proof-only 0026 整体回滚并保持 0025；既有 reconstructed governance 只作 forensic prior state，不得服务 candidate.5 或强推 head |
| legacy provenance unknown/conflicting | fail closed，不创建 sentinel/Decision/quarantine；人工审计而非猜测 authority |
| canonical DB unavailable | readiness fail；authority queries abstain/503 |

## 10. Deletion proof

对一个 deletion request，可交付证明必须区分：

- canonical revoke/block commit sequence；
- invalidated Capsule/pointer 数量；
- 每个 projection 的 purge delivery 与 watermark；
- Blob erased/shared/policy-blocked 状态；`ERASED` 必须附
  `ERASED_AND_VERIFIED_ABSENT` 或 `VERIFIED_ALREADY_ABSENT` proof；
- 每个未过期 backup 的 obligation；
- dead-letter 或 reconciliation failures。

只有所有适用层完成才能声明 physical completion；法律保留或共享引用必须明确写为未擦除原因。

Erasure proof 至少绑定 disposition、tenant、lease、storage URI、expected content SHA-256 与
proof SHA-256。Adapter 必须在删除前以 `lstat` 拒绝 symlink/non-regular target，校验 bytes hash，
unlink 后 fsync parent directory 并再次确认路径不存在。Worker 必须把完整 proof 传到数据库；SQL
使用 PostgreSQL 内建 `sha256(bytea)` 独立重算，旧的无 proof completion entry point 必须撤权。

## 11. Required drills

- revoke 后同步 ECS/Gate denial；
- active Capsule 和 pointer 立即不可用；
- worker outage/dead-letter 不恢复 authority；
- duplicate purge 幂等；
- shared Blob 不误删，最后 live reference 删除后可清理；
- tampered/symlink/non-regular Blob 不得删除或标记 ERASED；
- forged proof 被 SQL 拒绝，crash-after-unlink retry 以 verified-already-absent 完成；
- backup inventory 增/缺表均 fail closed；
- 两个 quarantine ledger 的原始列/hash/reconciliation link 在 backup/restore 后完全一致，且 Owner
  UPDATE/DELETE 仍被拒绝；
- 删除/破坏 actual DeletionRequest、requester/reason/status、idempotency、Evidence、OperationalEvent、
  revoke Outbox 或 purge Outbox 时 migration 返回 `AF09_UNPROVABLE_LEGACY_TX05` 且无新 residue；
- dump 或 Blob tamper 在 restore 前失败；
- restore 后 ID、lineage、block、issue、episode、watermark 一致；
- external adapters 完全缺席仍能恢复核心系统。
