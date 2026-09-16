# AF-09 Candidate.5 Remediation Record

> Candidate：`1.0.0-candidate.5`  
> Prior independent decisions：`REVISE`（candidate.1 through candidate.4）  
> Current independent decision：`PENDING`  
> Scope：candidate.4 open P1 `AF09-F12`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件是作者整改导航，不修改、覆盖或“关闭”独立 reviewer 的原始决定。Candidate.1–4 的
review/archive/receipt/remediation/report 均保持不可变。Candidate.4 精确 manifest
`13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb` 的同一 reviewer 复审
决定为 `REVISE`；review SHA-256 为
`ed7f4ff514f8b7c41eb345fe4c2d568b34f6df4260d74c1eaaa33341fe25ec21`。该复审关闭 F01，确认
F11 的 exact missing-DeletionRequest 反例已修复，并新增 F12 为 P1 OPEN。只有同一 reviewer 针对
candidate.5 外部回执标识的精确 bytes 重跑全量评审并签署 `ACCEPT`，AF-09 才能关闭。

## Finding closure matrix

| Finding | Candidate.4 rereview counterexample | Candidate.5 normative remediation | Primary executable evidence |
| --- | --- | --- | --- |
| F12 | Candidate.1 TX-05 的 DeletionRequest/Evidence 时间、actor、identity 与所有 state axes 已受证，但 idempotency、OperationalEvent、revoke Outbox 或 purge Outbox 的 `created_at` 任一偏移 1 秒，0024/0025 仍重建 `APPLIED` Proposal + `STEWARD APPROVE` Decision | 以 `DeletionRequest.requested_at` 为原事务时间锚；corrected 0024/0025 在锁内要求 Evidence revoke 与四个 `created_at` 全部精确相等；0024 重建查询重复同一谓词；新 proof-only 0026 重新认证已应用 candidate.4/0025 的开发库。任一冲突返回 `AF09_UNPROVABLE_LEGACY_TX05`，fresh/compat 分别停在 0023/0024/0025，不能获得新 head 或本次 authority residue | 四个具名 fresh public-procedure negative nodes；四例 0024→0025 compatibility；四例 0025→0026 compatibility；六时间腿合法控制 |

F01 与 exact F11 已由 candidate.4 独立复审关闭；F02–F10 的既有关闭结论不由作者重新裁决。
Candidate.5 必须在全套门禁中证明这些控制没有回归，不能用 F12 的局部 PASS 替代完整 AF-09。

## Governing ADRs

- `docs/adr/ADR-015-af09-governance-history-and-gate-remediation.md`：F01–F06；
- `docs/adr/ADR-016-af09-causality-erasure-role-and-lock-remediation.md`：F07–F10；
- `docs/adr/ADR-017-populated-governance-history-reconciliation.md`：candidate.2 F01/F02 的
  provenance-first populated-state repair；
- `docs/adr/ADR-018-rejected-grounding-and-tx05-provenance-guard.md`：candidate.3 F01/F11 的
  exact grounding quarantine 与 actual DeletionRequest proof；
- `docs/adr/ADR-019-legacy-tx05-transaction-time-certification.md`：candidate.4 F12 的完整事务
  时间证明及 0026 compatibility certification。

Candidate.4 从未被接受/冻结；其 0024/0025 bytes 保存在不可变 candidate.4 archive。Live 0024 与
0025 增加四条时间等式，让新的 fresh/candidate.3-compatible 输入在重建 authority 前 fail closed。
新 head `0026_legacy_tx05_time_guard` 不创建表或 authority，只允许完整证明的 candidate.4/0025
开发库前进。`0015+` 保存治理、擦除、隔离和认证事实，禁止 destructive downgrade。

两个 legacy quarantine ledger 继续不参与 canonical replay/lineage/Issue/Context，不提供 authority。
0026 不改变 32-table durable catalog、forced RLS、角色 grants 或 backup inventory。

## Reviewer reproduction boundary

Reviewer 必须从 bundle 外的 candidate.5 submission receipt 复制 digest，再运行：

```bash
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
```

还需复跑 runtime 真实五角色 PostgreSQL 全套、fresh base→head、populated 0014→head、candidate.3
0024→0025、candidate.4 0025→0026、四个独立时间反例、既有 F01/F11 反例、真实 Issue/Context、
backup/security/research/package 门禁，并重新裁决 F01–F12 closure。作者的 PASS、测试通过或本记录
本身都不构成 AF-09 接受。
