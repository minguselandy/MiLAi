# ADR-003：标识、幂等与时间基线

> 状态：`ACCEPTED FOR 0.1.x EXPERIMENTAL`  
> 日期：`2026-08-15`  
> 冻结影响：不构成 Schema freeze

## Decision

- tenant-owned identity 使用 UUID，并以 `(tenant_id, object_id)` 作为数据库身份；
- 时间使用 PostgreSQL `timestamptz`，应用输出 ISO 8601；
- 可重试写入由 `(tenant_id, operation_family, idempotency_key)` 唯一定位；
- fingerprint 是规范化 typed payload 加认证 tenant 的 SHA-256；
- 同 key 同 fingerprint 返回存储的首次 response，同 key 不同 fingerprint fail closed；
- idempotency response 与 canonical/outbox side effects 在同一事务写入；
- Evidence ingest 的 Outbox 当前允许 `canonical_commit_seq` 为空；Claim/OpenIssue 正式提交
  分配 canonical sequence。ADR-009 将其定义为 `0.1.x` 兼容差异，后续以 expand/backfill/
  contract 迁移到所有 canonical event 可排序。

## Consequences

客户端 ID 不能替代 tenant/RLS 检查；时间、Scope 和 system time 分字段保存；重试不会创建
第二份 canonical state。sequence 覆盖扩大时必须回填 Evidence commit position 并更新 ADR-009。
