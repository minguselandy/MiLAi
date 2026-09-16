# ADR-020：Agent Integration Plane

> 状态：`ACCEPTED FOR EXPERIMENTAL IMPLEMENTATION`  
> 日期：2026-08-17

## Decision

MiLAi 在既有 REST Runtime 前增加独立、可替换的 Integration Plane：versioned contract、Python
client、lifecycle facade、MCP stdio server 及框架薄适配器。所有适配器只能调用公开 REST，禁止
导入 `milai.persistence`、`milai.application` 或持有数据库 DSN。

Recall 可以自动执行；Observation 只记录真实用户/工具观察；Governance 只允许 Agent 创建
Proposal，审批仍由独立 Steward 主体和过程完成。框架 checkpoint、消息历史与 MiLAi canonical
memory 是三个不同对象，不进行隐式互写。

## Compatibility

`contracts/agent/v1` 是接入契约。v1 只做向后兼容字段增加；删除、改名、收紧枚举或改变失败语义
必须发布新 major。SDK 必须保留 abstention、degraded、OpenIssue、trace 和 canonical position。

## Transport

本地 beta 只批准 loopback REST 和 MCP stdio。HTTP MCP、远程 Runtime、多 Agent delegation 均
继续 `NOT APPROVED`。
