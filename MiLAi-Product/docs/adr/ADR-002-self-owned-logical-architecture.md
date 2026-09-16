# ADR-002：MiLAi 自主 Logical Architecture

> 状态：`ACCEPTED FOR 1.0.0-candidate.1`  
> 日期：`2026-08-16`  
> 冻结影响：`NO-GO`，等待 AF-09 独立评审

## Context

历史计划曾假设外部存在一个可下载的 frozen architecture bundle。项目审计未找到该制品，且用户
明确确认 MiLAi Logical Architecture 从未实现，必须根据当前项目和已下载的研究项目自行设计。

## Decision

- `MiLAi_Logical_Architecture_v1_设计文档.md` 是自主架构设计源；
- `architecture/v1.0-candidate/` 是规范候选包；
- PostgreSQL canonical truth、Evidence/Claim 分离、Steward procedure、ECS/Gate、OpenIssue、
  revoke propagation 和 tenant/RLS 是核心边界；
- ReMe、Hindsight、Graphiti、Mem0 与 benchmark 仓库只提供可隔离的设计/评测输入，不定义
  MiLAi canonical schema；
- 旧 DG-00 acquisition 报告仅保留为历史证据，不再作为外部下载阻塞；
- candidate 经 manifest、crosswalk、自动门禁和独立评审后才可成为 `1.0.0 FROZEN`。

## Consequences

不再等待或下载不存在的架构项目。任何外部项目都必须走 adapter boundary 和增益/安全门禁；
任何核心语义变更都更新本架构版本、ADR、migration、tests 和 manifest。

