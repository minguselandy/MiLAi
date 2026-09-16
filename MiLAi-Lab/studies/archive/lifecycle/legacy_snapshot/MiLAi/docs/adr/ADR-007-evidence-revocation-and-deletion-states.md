# ADR-007：Evidence 撤销与分层删除状态

> 状态：`ACCEPTED FOR 0.1.x EXPERIMENTAL`  
> 日期：`2026-08-15`  
> 候选架构结论：与 Logical Architecture `1.0.0-candidate.2` 一致

## Decision

TX-05 同步阶段只承诺立即失去合法可用性，不把异步传播包装为“已删除”。一个
`deletion_request` 分别保存：

```text
logical_revocation_status
canonical_block_status
derived_purge_status
primary_bytes_status
backup_expiry_status
retention_status
```

撤销原子写 Evidence revocation、GroundingBlock、Context invalidation、必要的 OpenIssue
reopen、OperationalEvent 和 purge/re-ground outbox。物理 Blob、FTS、vector、Context artifact
与 backup expiry 由 worker/运维阶段分别对账。

Blob 只在同 tenant 内共享。只要存在另一条未撤销 Evidence，或任何 reference 处于
`LEGAL_HOLD/UNREADABLE`，primary bytes 都不能进入可擦除状态。Evidence 正文读取和 Canonical
Gate 不等待物理清理；它们在逻辑撤销提交后立即 fail closed。

`0016_governed_revocation` 将 TX-05 表达为同一事务内的 `OperationProposal` +
`StewardDecision`，并把受影响 IssueTransition、OperationalEvent 与 Outbox 关联到 proposal/decision。
`0019_erasure_proof` 起，Blob adapter 返回身份绑定的
`ERASED_AND_VERIFIED_ABSENT | VERIFIED_ALREADY_ABSENT` 证明；数据库只有在重验 tenant、lease、
URI、content hash、引用与 proof hash 后才记录 `ERASED`。伪造证明、symlink、非普通文件、hash/URI
不匹配全部 fail closed；故障发生在 unlink 后可通过 verified-already-absent 明确恢复。

## Compatibility

Context persistence 采用可选 TTL `context_capsule` 与独立 `context_pointer`。后续 DG-08 可以
扩展 protected section validation，但不能弱化 TX-05 对 resident pointer 的同步失效。未来
架构版本若改变删除对象或状态名，必须迁移并保留本状态机的审计映射，不静默覆盖。
