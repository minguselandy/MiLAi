# AF-09 Candidate.4 Remediation Record

> Candidate：`1.0.0-candidate.4`  
> Prior independent decisions：candidate.1/2/3 `REVISE`  
> Current independent decision：`PENDING`  
> Scope：candidate.3 open P1 findings `AF09-F01` / `AF09-F11`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件只记录作者整改与 reviewer 重放入口，不修改或替代任何既有独立决定。Candidate.3 精确
manifest `6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620` 的同一独立
reviewer 复审记录是
`docs/reviews/AF-09-independent-rereview-candidate.3-2026-08-17.md`，SHA-256 为
`321883a7b9b695f4727aee99375fbeb3daf9919314c7562f6854d2a826012e9c`，决定为
`REVISE`。该复审关闭 F02，保持 F03–F10 已关闭，并把 F01 与新发现 F11 列为 P1 OPEN。

只有同一 reviewer 对 candidate.4 外部 receipt 锚定的精确 archive/manifest/source bytes 完整
重放并签署 `ACCEPT`，AF-09 才能关闭。

## Finding remediation matrix

| Finding | Candidate.3 counterexample | Candidate.4 normative remediation | Direct executable evidence |
| --- | --- | --- | --- |
| AF09-F01 | Pending candidate.1 resolution 在 0024 后虽被 POLICY REJECT 且 Issue 恢复 OPEN，其 pre-Decision `RESOLUTION_CANDIDATE` 仍留在 canonical `grounding_relation`，真实 Issue/Context 继续返回该 rejected branch | Corrected 0024 在写入前证明 Proposal distinct support set 与 Issue-owned relation set 精确相等；REJECT 时把每条原 relation 全字段及 SQL 可重算 SHA-256 原子移入 forced-RLS/append-only `legacy_grounding_relation_quarantine`，再从 canonical 表删除；APPROVE 只在真实 Proposal/Decision/Issue/support 链完整时保留；最终 postcondition 拒绝任何无完整 APPROVE 链的 canonical resolution grounding | `test_candidate1_populated_governance_state_is_reconciled_forward`；`test_candidate1_unprovable_resolution_grounding_rolls_back_whole_migration`；`test_candidate1_decided_reject_quarantines_only_unauthorized_grounding`；`test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof` |
| AF09-F11 | 删除真实 `milai.deletion_request` 后，candidate.3 0024 仅凭 JSON/ID 一致仍重建 `APPLIED REVOKE_EVIDENCE` Proposal 与 `STEWARD APPROVE` Decision | Corrected 0024 与 compatibility 0025 都在任何治理重建前锁定并 join 真实 tenant-scoped DeletionRequest，同时验证 Evidence/Blob、requester/creator、reason/time、logical/canonical/purge/primary/backup/retention state、idempotency result、OperationalEvent、revoke Outbox 与 purge Outbox。任一腿缺失/冲突只返回 `AF09_UNPROVABLE_LEGACY_TX05`；fresh 0014 链整体停在 0023，无 quarantine/Proposal/Decision/replacement/event/outbox residue | `test_candidate1_legacy_tx05_corrupt_proof_leg_rolls_back_whole_migration`（九种独立破坏）；`test_candidate3_applied_0024_missing_deletion_request_is_blocked_by_0025`；合法正向 TX-05 regression |

## Migration identity and compatibility

Candidate.3 从未被 ACCEPT，也未成为 frozen/released migration line。Candidate.4 因而修正 live、
尚未接受的 0024 源文件，使 fresh candidate.1 数据库在同一个 0024 transaction 内 fail closed；
candidate.3 的原始 0024 bytes 仍完整保存在其不可变 submission archive 中，不能覆盖历史。

新增 forward-only head `0025_legacy_provenance_guard` 专门处理已经执行 candidate.3 0024 的开发
数据库：它重复真实 DeletionRequest proof，并把 candidate.3 遗留的 rejected grounding 收敛到同一
ledger/schema。有效兼容输入前向到 0025；无法证明的输入保持 0024，不能以伪造 DeletionRequest
强行抬头。0024/0025 downgrade 都不允许删除治理或隔离审计事实。详见 ADR-018。

## Audit, security, backup, and consumer boundary

`legacy_grounding_relation_quarantine`：

- 保存 tenant、原 relation ID、owner、Evidence、relation type、Proposal、原始时间/actor、关联原
  transition、实际 reconciliation Decision 与原行 SHA-256；
- forced RLS；API/Worker 无权限；Steward/Audit 仅 tenant-scoped SELECT；Migration Owner 也被
  append-only trigger 禁止 UPDATE/DELETE；
- 不进入 ECS、Gate、Issue、Context、retrieval 或任何 authority decision；
- 与 `legacy_issue_transition_quarantine` 一起进入 exhaustive backup catalog/count/hash/restore；
- 使 catalog 达到 32 张 durable tables，其中 31 张 tenant-owned。

真实 Issue API 与由 L0 trace 构造的真实 ContextCapsule 都直接验证 rejected Evidence 不再出现；后续
current proposal/review 仍能正常完成。测试还覆盖 exact hash 重算、批准 relation 保留、拒绝 relation
隔离、source-set 缺失/冲突整体回滚、Owner mutation denial、RLS/grants/trigger catalog。

## Governing artifacts

- `docs/adr/ADR-015-af09-governance-history-and-gate-remediation.md`；
- `docs/adr/ADR-016-af09-causality-erasure-role-and-lock-remediation.md`；
- `docs/adr/ADR-017-populated-governance-history-reconciliation.md`；
- `docs/adr/ADR-018-rejected-grounding-and-tx05-provenance-guard.md`；
- migrations `0024_legacy_history_reconcile` / `0025_legacy_provenance_guard`；
- `runtime/tests/integration/test_runtime_foundation.py` 与 backup/security suites。

## Reviewer reproduction boundary

Reviewer 必须从 bundle 外 candidate.4 receipt 复制 trusted manifest digest，再运行：

```bash
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
```

还必须重跑真实五角色 PostgreSQL 全套、fresh base→head、fresh populated 0014→head、already-applied
candidate.3 0024→0025、每条 provenance 破坏、真实 Issue/Context 与 backup/restore 门禁，并逐项重新
裁决 F01/F11 及所有已关闭 finding 是否回归。作者报告、绿色测试或本记录本身都不是 closure
evidence。
