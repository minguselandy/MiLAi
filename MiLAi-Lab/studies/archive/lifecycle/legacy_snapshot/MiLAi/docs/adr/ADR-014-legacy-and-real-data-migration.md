# ADR-014：Legacy 与真实数据迁移

> 状态：`ACCEPTED FOR 1.0.0-candidate.1`  
> 日期：`2026-08-16`  
> 当前发现：未识别可授权导入的 legacy/real dataset

## Decision

不进行数据库表级复制或 dual-write/dual-read。每个 legacy source 使用版本化 importer：

```text
read-only inventory
→ dry-run normalization and rejection report
→ immutable Evidence import with source lineage/idempotency
→ Proposal generation
→ explicit Steward review
→ reconciliation and signed cutover report
```

无法证明 tenant、source、permission、retention、observed time 或 content identity 的记录进入
quarantine，不进入 canonical Claim。legacy “memory/fact” 不能直接成为 ClaimVersion。

真实数据导入还必须通过 ADR-012 加密/key gate、隐私/threat review、backup/restore drill、删除演练
和用户授权。导入可中止并按 idempotency 安全重跑；回滚只撤销本批 Evidence/Proposal，不重写历史。

## Consequences

当前没有 legacy dataset，因此只冻结迁移协议而不编造 mapping。发现实际 source 后必须先生成
source-specific inventory/mapping ADR 与 dry-run report，才允许执行导入。

