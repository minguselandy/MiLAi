# ADR-004：GroundingRelation 实验性物理模型

> 状态：`ACCEPTED FOR 0.1.x EXPERIMENTAL`  
> 日期：`2026-08-15`  
> 候选架构结论：逻辑关系统一；`0.1.x` 物理表保持统一

## Decision

Lean `0.1.x` 使用一个 `grounding_relation` 表，并以两个 nullable owner foreign key 表示：

```text
claim_version_id XOR open_issue_id
→ evidence_id
→ relation_type
```

ClaimVersion 允许 `SUPPORTS / CONTRADICTS / DERIVED_FROM`，OpenIssue 允许
`SUPPORT_BRANCH / CONTRADICT_BRANCH / RESOLUTION_CANDIDATE`。Check constraint 保证 owner 与
relation type 相容，partial unique index 防止重复边。

## Consequences

- API、评测和 lineage 只有一个规范 relation 语义；
- `DEPENDS_ON` 只有出现经验证的业务语义和 cycle/删除规则后才新增；
- 若未来因性能或约束需要物理拆表，通过 compatibility view 和 expand/migrate/contract 迁移；
- 外部 graph/memory ID 不进入该表。
