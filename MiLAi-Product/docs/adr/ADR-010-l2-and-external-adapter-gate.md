# ADR-010：L2 与 External Adapter 启用门

> 状态：`ACCEPTED FOR 1.0.0-candidate.1`  
> 日期：`2026-08-16`

## Decision

L0/L1 PostgreSQL route 是 v1 默认。L2、ReMe、Hindsight、Mem0、Graphiti 和任何远程模型默认关闭，
并且：

- 只接收只读 export 或最小化 Outbox payload；
- 使用独立 namespace、目录、凭据、projection version 和 watermark；
- 输出带 canonical source refs 的 typed candidate；
- 统一解析 canonical ID 并经过 ECS/Gate；
- 无 Migration Owner/Steward credential；
- 可完全卸载，核心 startup、L0、revoke、backup/restore 仍通过。

启用任一路由前必须有固定数据/模型/seed/budget/scorer 的可复现 benchmark，证明相对 PostgreSQL
baseline 的目标指标增益，并通过隐私、删除传播、故障降级、成本与 license 门禁。没有显著增益或
出现 hard falsifier 时保持关闭。

## Consequences

已下载项目是研究资产而非 runtime 依赖。外部自动 fact invalidation、reflect、dream 或 summary
只能成为 Proposal/Retrieval candidate。

