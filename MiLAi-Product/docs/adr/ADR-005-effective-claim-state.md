# ADR-005：EffectiveClaimState 唯一入口

> 状态：`ACCEPTED FOR 0.1.x EXPERIMENTAL`  
> 日期：`2026-08-15`

## Decision

`effective_claim_state` 先实现为 PostgreSQL `security_invoker` view，集中暴露 Head、版本、
live grounding、GroundingBlock、有效时间和 live OpenIssue 状态。带查询 Scope、历史版本、
required authority 的最终判定由同 schema 的受测 SQL function 在 DG-07 完成，API/Context 不
复制判断逻辑。

Scope `0.1.x` 使用保守 JSON containment 候选；authority 使用 ADR-008 的显式匹配 matrix，
不实现总序。任何替换必须有 ADR、migration、crosswalk 与 Gate 回归。

## Candidate.2 closure

Migration `0017_authoritative_ecs` 将 ECS 扩展为所有 ClaimVersion 的权威状态投影，并使唯一公开
Gate 只从该视图读取 current、lifecycle、epistemic、freshness、Scope、valid/system time、
authority、confidence、lineage、permission/retention、Blob、block 与 live issue 事实。旧六参数
Gate 被改名并撤销；Context 由 `0021_gate_consumers` 通过同一十一参数 Gate 重验 RetrievalTrace，
不再复制或遗漏状态轴。
