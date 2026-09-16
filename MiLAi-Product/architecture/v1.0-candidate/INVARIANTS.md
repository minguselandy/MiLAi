# MiLAi Goals and Invariants

> Architecture `1.0.0-candidate.5`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件中的 ID 和语句是 candidate bundle 的规范锚点；机器映射见 `crosswalk.json`。

## 1. Architecture goals

| ID | Normative goal | Release consequence |
| --- | --- | --- |
| G1 | **Source Fidelity**：每个 belief 可回到 admissible Evidence；Evidence 身份与来源不被重写。 | 无 lineage 的 authority answer 阻断 |
| G2 | **Governed Canonical Evolution**：所有 Claim/OpenIssue 变化经 Proposal、Decision、procedure、CAS 和 immutable history。 | 绕过治理的 mutation 阻断 |
| G3 | **Open-State Preservation**：冲突、缺证、Scope/authority 未决保持为有身份、有 branches、有 discharge rule 的 OpenIssue。 | 静默覆盖/关闭阻断 |
| G4 | **Applicability Separation**：lifecycle、epistemic、freshness、authority、confidence、Scope、valid/system time 正交。 | 非法推导阻断 |
| G5 | **Candidate-Safe Retrieval**：所有非 canonical 结果只是 candidate，必须经统一 ECS/Gate，故障只能降 recall。 | projection 自封 authority 阻断 |
| G6 | **Revocation Propagation**：Evidence revoke 同步阻断 authority，异步清理 projection/blob/backup 可证明。 | stale authority/bytes 无证明阻断 |
| G7 | **Bounded Traceable Context**：Context 保护 Goal/Constraint/ECS/OpenIssue；回答带 lineage 或 abstain。 | 丢 protected item 或无 trace 阻断 |
| G8 | **Least-Privilege Local Security**：tenant、RLS、角色、loopback、secret/log privacy 和 remote gate 明确。 | cross-tenant/secret exposure 为 P0 |
| G9 | **Replaceable and Recoverable System**：外部组件可移除；Migration、Outbox、projection、backup 和 audit 可重放。 | 无法恢复或外部依赖绑死阻断 |

## 2. Hard invariants

| ID | Normative invariant | Mandatory failure behavior |
| --- | --- | --- |
| I-01 | `EvidenceRecord != ClaimVersion`；观察不等于系统 belief。 | 阻止 canonical commit/release |
| I-02 | Evidence capture identity、source、observed time、content hash 不可覆盖；重试 key+fingerprint 幂等。 | 整个事务回滚并报 conflict |
| I-03 | Claim/OpenIssue 正式变化只有 Steward procedure 可写；模型、adapter、API、worker 无 direct DML。 | 权限测试必须拒绝 |
| I-04 | ClaimVersion、VersionTransition、StewardDecision、IssueTransition append-only；创建也必须留下 source-linked transition sentinel；canonical Issue history 的 Proposal/Decision/policy/sequence 不得为 NULL。精确 legacy invalid row 只能进入不参与 replay/authority 的 immutable quarantine。 | 原地修改、缺失/伪造创建历史、NULL governance 或可变 quarantine 阻断升级/发布 |
| I-05 | ClaimHead exact-head CAS，OpenIssue expected-revision CAS；并发只能一个胜者。 | loser 全事务回滚 |
| I-06 | CONTRADICT 默认不移动 Head；保留 issue identity、两侧 branch 和 discharge rule。 | 禁止覆盖或静默关闭 |
| I-07 | EffectiveClaimState 是 lifecycle/epistemic/freshness/confidence/Scope/valid-system time/current/authority decision facts 的唯一入口。 | 返回 abstention 或错误 |
| I-08 | FTS、vector、graph、cache、Context、Summary、LLM、外部 memory 不提升 truth/authority。 | candidate 必须 Gate |
| I-09 | authority、confidence、freshness、epistemic、Scope、valid/system time 不能互相推导。 | 边界校验拒绝 |
| I-10 | revoke 提交即同步 governed Proposal/Decision、GroundingBlock/Context invalidation；permission/retention unknown fail closed；物理 ERASED 需要可重算 absence proof。 | stale bytes 不可使用、无 proof 不得完成 |
| I-11 | tenant-owned row 带 tenant_id；精确 runtime login、真实角色、RLS、session reset 和最小凭据不可绕过。 | cross-tenant/role mismatch 为 P0 |
| I-12 | mutation、Decision、OperationalEvent、Outbox 原子；authority answer 可回放到 Claim/Evidence/Issue/Trace；RYW position 来自真实 Outbox 并留 wait trace。 | 无 trace/伪造因果位置则 abstain 或拒绝 |

## 3. Enforcement hierarchy

从最接近数据到最外层依次执行：

```text
database constraints / RLS / grants
→ SECURITY DEFINER procedure revalidation and CAS
→ typed repository and application contract
→ canonical retrieval Gate
→ API validation and stable error mapping
→ integration, concurrency, security and recovery tests
→ architecture crosswalk and bundle lock
```

应用层检查不能代替数据库约束；单元测试不能代替真实角色、并发和恢复测试。

## 4. Hard-failure rules

以下任一结果使 candidate 不能发布或冻结：

- I-01～I-12 任一缺少 schema/code/test/report 映射；
- 权限、tenant、retention、GroundingBlock 或 canonical 可用性为 unknown 但仍返回 authority answer；
- stale projection、外部 memory 或 Context 绕过 canonical Gate；
- CAS loser 产生部分 history、decision、outbox 或 Head 更新；
- revoke 后旧 Capsule/pointer/confirmation 仍可用于 action；
- proposal submission 在 Decision 前改变 OpenIssue/Claim，或创建对象缺 transition history；
- populated forward migration 无法证明真实 Proposal/Decision/actor/sequence/Outbox provenance，却继续
  服务、伪造 approval、丢弃 legacy row，或留下不连续 revision replay；
- Gate/Context 从 ECS 以外重建状态判定，或漏判任一正交轴；
- SQL 在缺少、伪造或身份不匹配的 durable-absence proof 下把 Blob 标记 ERASED；
- runtime DSN 使用 owner/错误角色，或 RYW 接受客户端自报 sequence/复用 Bearer secret；
- backup catalog、blob manifest 或 migration revision 不一致仍报告成功；
- manifest hash 漂移未被验证器检出；
- 实现声称 `FROZEN`，但 AF-09 未经独立审查通过。

## 5. Change rule

更改 G/I 的 ID 或语义必须新增 ADR、更新人类规范与 `crosswalk.json`、刷新 manifest hash，并重新运行
全部 architecture 和 runtime gates。Candidate review/release 还必须以 bundle 外回执提供 manifest
SHA-256 trust anchor；仅修改实现或协同替换 bundle+manifest 而不更新外部回执均视为 drift。
