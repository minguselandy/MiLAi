# ADR-006：OpenIssue Revision 与 Transition

> 状态：`ACCEPTED FOR 0.1.x EXPERIMENTAL`  
> 日期：`2026-08-15`  
> 候选架构结论：revision + append-only transition 是 v1 逻辑版本模型

## Decision

Lean `0.1.x` 使用 `open_issue.revision` 作为 CAS 字段，并以 append-only
`open_issue_transition` 保存每次状态变化、proposal、decision、actor、policy 和 commit
sequence。正反 branches 使用结构化 `grounding_relation`，不复制进自然语言描述。

Resolution Evidence 被撤销时更新同一 issue ID 的 revision/status 并追加 transition；不创建
替代 issue。未来若数据量或查询证明需要独立 OpenIssueVersion，必须将 transition 作为迁移来源、
保留兼容读取并走架构版本变更；当前不再将其视为未决语义。
