# ADR-015：AF-09 Governance、History 与 Canonical Gate 整改

> 状态：`ACCEPTED FOR 1.0.0-candidate.2`  
> 日期：`2026-08-17`  
> 关闭：`AF09-F01`～`AF09-F06`

## Context

Candidate.1 独立评审发现：resolution proposal 在 Decision 前改变 OpenIssue、创建历史不完整、
ClaimVersion 状态枚举与规范不一致、Gate 缺状态轴且绕开 ECS、crosswalk 负向证据间接，以及 TX-05
没有 Proposal/Decision 治理事实。这些问题属于 P1，不能以文档解释延期。

## Decision

1. Proposal submission 永远非 canonical，只保存 proposal、候选 Evidence refs、操作事件与 Outbox；
   不改变 Claim、Head、OpenIssue、grounding 或 canonical history。
2. Resolution 只有在 Steward `APPROVE` 事务中才同时创建新 ClaimVersion、grounding、Head CAS、
   OpenIssue revision CAS、`DISCHARGE_APPROVED` transition、Decision、event 与 outbox；`REJECT` 保持
   Issue 原状态。并发 review 只有一个 winner，loser 无残留。
3. V1 创建写 `VersionTransition(CREATE, old=NULL)`；首次 Issue 创建写
   `OpenIssueTransition(ISSUE_CREATED, from_status=NULL, revision 0→1)`。后续 history 均链接非空
   Proposal、Decision、policy 和 canonical sequence。
4. Normative 状态域固定为 lifecycle `ACTIVE/SUPERSEDED/ARCHIVED/DELETED`、epistemic
   `PROVISIONAL/VERIFIED/CHALLENGED/UNPROVABLE`、freshness `CURRENT/STALE`。迁移显式把旧有限域
   `RETIRED/SUPPORTED/WEAKENED/UNCERTAIN/UNKNOWN` 映射到新域，并保留 insert compatibility；未知值
   整体回滚。
5. ECS 是所有 Gate decision facts 的唯一 SQL 来源。请求与 QueryPlan 显式携带 lifecycle、accepted
   epistemic set、freshness、minimum confidence、valid/system time；Gate 对每轴给出独立 reason。
   Context trace 重验也只能委托同一 Gate。
6. TX-05 在 revoke wrapper 内先写 Proposal，再执行同步 revoke/block/invalidation/Issue effect，最后
   写共享 canonical sequence 的 StewardDecision，并关联 transition/event/outbox；任一故障全部回滚。

## Implementation and evidence

- Migrations：`0015_governed_history`、`0016_governed_revocation`、
  `0017_authoritative_ecs`、`0021_gate_consumers`。
- Positive/negative evidence：creation replay、noncanonical submission、rejected resolution、review CAS、
  exhaustive state domains、invalid domain rollback、四类 history immutability、Evidence→Claim collapse
  denial、全部 Gate axes/bitemporal reasons、TX-05 governed success 与 forced rollback。
- Candidate.1 database 保持可前向升级；含新 governance history 后 downgrade 被明确拒绝，避免丢审计。

## Consequences

OpenIssue 可以保留 `READY_FOR_REVIEW` 状态，但进入该状态也必须是独立的 governed Decision；提交
resolution proposal 本身不再是状态边。当前最短批准路径允许 `OPEN/WAITING_* → RESOLVED`，前提是
同一 review transaction 完整满足 discharge rule 和 CAS。
