# AF-09 Candidate.3 整改记录

> 日期：2026-08-17（Asia/Shanghai）  
> 作者证据性质：`REMEDIATION_RECORD_NOT_INDEPENDENT_ACCEPTANCE`  
> Candidate：`1.0.0-candidate.3`  
> 当前 AF-09：`PENDING_INDEPENDENT_REREVIEW`

## 1. 不可变审查链

- Candidate.1 独立审查决定：`REVISE`，finding `AF09-F01`～`AF09-F10`。
- Candidate.2 精确 manifest：
  `17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae`；archive：
  `03bf746775beb60a0910f0bbec2539a62a4aa656e3d3de7cb82d667eca0c9544`。
- 同一独立 reviewer 的 candidate.2 复审记录：
  `docs/reviews/AF-09-independent-rereview-candidate.2-2026-08-17.md`；SHA-256
  `50f341f2d460fbca59e12b3a1841894a49dbbeb13405804e007bbb1d53557515`；决定 `REVISE`。
- Candidate.2 中 F03～F10 已被 reviewer 判定关闭；F01/F02 仍为 P1 OPEN。Candidate.1/2 的 review、
  archive、receipt、remediation 和 report 都保持原字节，不由本记录改写。

本记录只陈述 candidate.3 的作者整改主张。它无权关闭 finding 或签署 AF-09。

## 2. F01/F02 整改矩阵

| Finding | Candidate.2 反例 | Candidate.3 实现 | 直接可执行证据 |
| --- | --- | --- | --- |
| AF09-F01 | 0014 resolution submission 已把 Issue 变为 `READY_FOR_REVIEW`，留下 NULL Decision transition；升级后 Proposal 因 revision conflict 不可审核 | migration 0024 在写入前证明精确 Proposal/Issue/Outbox shape；原行哈希后原子移入 append-only quarantine；pending Proposal 只能由固定 POLICY actor `REJECT`，并以 governed classification + CAS reversal 恢复旧状态；已有合法 Decision 则链接真实 Decision | `test_candidate1_populated_governance_state_is_reconciled_forward`；`test_candidate1_unprovable_creation_history_fails_upgrade_closed` |
| AF09-F02 | 0014 V1/Issue 升级后仍无创建 sentinel，`ck_issue_transition_governed` 未验证 | migration 0024 仅从真实 Proposal/APPROVE Decision/actor/sequence/Outbox 回填 `CREATE old=NULL` 与 `ISSUE_CREATED NULL 0→1`；无法证明即整体失败；验证历史约束并建立 incoming/revision 唯一索引 | 同上；fresh base→head migration test |

独立排查还发现 candidate.1 TX-05 会产生同类 NULL Proposal/Decision Issue transitions。0024 只在
idempotency result、revoked Evidence、OperationalEvent 与 Outbox 四方一致时重建
`REVOKE_EVIDENCE` Proposal 和真实 `STEWARD APPROVE` Decision；精确旧行仍进入 quarantine。证据为
`test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof`。

## 3. 安全与恢复边界

- `legacy_issue_transition_quarantine` 是不参与 canonical replay 的审计隔离账本，启用 forced RLS；
  API/Worker 无权限，Steward/Audit 只读，Migration Owner 也被 UPDATE/DELETE trigger 拒绝。
- 旧行的 SHA-256 从全部原始治理列在 PostgreSQL 内重算；迁移、隔离、替代/反转、事件和 Outbox
  同一事务提交。
- 0024 完成后，每个 ClaimVersion 有且只有一个 incoming transition，每个 Issue 从 revision 0 连续
  回放到当前 revision，canonical Issue history 不允许治理字段为 NULL。
- quarantine 已加入 backup inventory；catalog 增/缺仍 fail closed。
- 0024 为 forward-only，downgrade 会删除治理/隔离证据，因此显式拒绝。

规范决策见 `docs/adr/ADR-017-populated-governance-history-reconciliation.md`。

## 4. 作者验证状态

封装前的精确门禁结果记录在
`docs/reports/DG-00-architecture-candidate.3-2026-08-17.md`。在最终 candidate.3 manifest、archive
与外部 receipt 生成前，任何局部 PASS 都不构成稳定提交身份。

## 5. 独立接受条件

同一 independent reviewer 必须从 bundle 外 candidate.3 receipt 取得 manifest SHA-256，验证 archive
与 live/source locks，重新执行 populated 0014→head、fresh migration、真实五角色 PostgreSQL 全套和
全部架构门禁，并逐条裁决 AF09-F01/F02。只有新记录明确 `ACCEPT` 才可进入 frozen 发布；此前始终：

```text
Schema: 0.1.x EXPERIMENTAL
Implementation: CANDIDATE
AF-09: PENDING_INDEPENDENT_REVIEW
Freeze: NO-GO FOR SCHEMA FREEZE
```
