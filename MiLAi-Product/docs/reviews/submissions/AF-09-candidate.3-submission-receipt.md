# AF-09 Candidate.3 Submission Receipt

> Submission：`MiLAi Logical Architecture 1.0.0-candidate.3`  
> Independent decision：`PENDING REREVIEW`  
> Reviewer：`/root/af09_reviewer_retry`（same independent reviewer）  
> Submission date：`2026-08-17`（Asia/Shanghai）

本 receipt 位于可变 bundle 之外，是 AF-09 review-mode 的 manifest trust anchor。它只标识本次提交
bytes，不宣称作者整改已被接受。Candidate.1/2 review、archive 与 receipt 均为不可变历史。

## Identity

```text
Candidate manifest SHA-256:
6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620

Deterministic submission archive SHA-256:
1c57041803db46ff90e74e9fcb305c72fe72aa85ac1f3946a747a65f2fb8a8bd

Archive bytes: 2367005
Archive entries: 161

Candidate.1 independent review SHA-256:
b12c64be6aea41cfb62ba9d8501a4cfc31f73dda0a50146de7d2367ae98f4707

Candidate.2 independent rereview SHA-256:
50f341f2d460fbca59e12b3a1841894a49dbbeb13405804e007bbb1d53557515

ADR-017 SHA-256:
2646160e9cd8084efd61906098dfb0fb54db6d044c00f8292f09ed962dcf17d5

Candidate.3 remediation record SHA-256:
f660bd7ed2f102d8b13c68d53359c106aa2504c413dd906171282614e62fc386

Candidate.3 DG-00 evidence report SHA-256:
30de75fffb33e4cb94b0cebc4b473be3b38971f4a7dfc33639a04ca7dc951118
```

Archive：`AF-09-candidate.3-6a2f1574-submission.tar.gz`

归档由 manifest 的 19 个 `required_files` 与全部 142 个 `source_locks` 精确生成，无重复。Project
文件以 `MiLAi/` 为前缀，workspace source locks 保持 workspace 相对路径；Git-locked external
repositories 不复制未声明正文。归档成员均为排序后的安全相对 regular-file path，时间固定为
`2026-08-17T00:00:00+08:00`，numeric owner 固定为 0，gzip header 不含时间。两次独立构建
byte-for-byte 相同，archive 内 161 个文件均已与 live locked bytes 做 SHA-256 比较。

## Trusted review command

Reviewer 必须从本 receipt 独立复制摘要，不能从候选 bundle 的自我声明推导：

```bash
TRUSTED_MANIFEST_SHA256="6a2f1574511f53614d558d663b0792c79b26c1b43a62ab746bfe10f367f15620"
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
```

缺 receipt、摘要格式错误、摘要不匹配、archive/live bytes 不同，或协同替换 bundle+manifest，必须使
review 失败。Reviewer 还必须从 `runtime/` 使用真实五角色 PostgreSQL DSN 重跑完整 suite，尤其：

```text
test_candidate1_populated_governance_state_is_reconciled_forward
test_candidate1_legacy_tx05_history_is_reconciled_from_four_way_proof
test_candidate1_unprovable_creation_history_fails_upgrade_closed
```

并独立裁决 AF09-F01/F02；作者报告和本 receipt 都不是 closure evidence 的替代品。

## Pre-submission evidence

```text
architecture validate / all-scope development lock   PASS (18 bundle / 142 source locks)
architecture review-mode external trust anchor       PASS
architecture positive/negative tests                 PASS (19)
runtime Ruff format/check                             PASS (103 files)
runtime strict mypy                                   PASS (57 source files)
runtime real exact-role PostgreSQL suite              PASS (95 tests)
fresh empty database forward migration to 0024       PASS
populated candidate.1 0014 → 0024 regressions        PASS (3 direct tests)
runtime wheel/sdist double build                      BYTE-STABLE (63 / 118 entries)
research isolation Ruff/mypy/tests/benchmark          PASS (7 source / 9 tests / 40 fixtures)
locked install / Compose interpolation               PASS
critical Markdown links/fences                       PASS (24 files)
```

## Immutability and decision boundary

从本 receipt 生成后，candidate.3 bundle、manifest、source locks 与 archive 视为提交冻结对象。若发现
任何需要修改的内容，必须创建 candidate.4、新 archive 和新外部 receipt，不能刷新本摘要。

当前结论仍为：

```text
Architecture CANDIDATE — NOT FROZEN
AF-09 PENDING_INDEPENDENT_REREVIEW
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```
