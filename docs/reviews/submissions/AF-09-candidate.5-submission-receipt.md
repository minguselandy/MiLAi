# AF-09 Candidate.5 Submission Receipt

> Submission：`MiLAi Logical Architecture 1.0.0-candidate.5`  
> Independent decision：`PENDING REREVIEW`  
> Reviewer：`/root/af09_reviewer_retry`（same independent reviewer）  
> Submission date：`2026-08-17`（Asia/Shanghai）

本 receipt 位于 candidate bundle 之外，是 AF-09 review-mode 的 manifest trust anchor。它只标识
精确提交 bytes，不宣称作者整改已被接受。Candidate.1–4 的 review、archive、receipt、remediation
与 report 均为不可变历史。

## Identity

```text
Candidate manifest SHA-256:
ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64

Deterministic submission archive SHA-256:
aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668

Archive bytes: 9558914
Archive entries: 175
Bundle required files: 19 (manifest + 18 locked siblings)
Source locks: 156
Git locks: 9

Candidate.4 independent rereview SHA-256:
ed7f4ff514f8b7c41eb345fe4c2d568b34f6df4260d74c1eaaa33341fe25ec21

ADR-019 SHA-256:
3adcea9420abbbc0402fcda5dc39da9c5d307149a1dd06d077383ff3100a25f7

Candidate.5 remediation record SHA-256:
892564557708cc4170294319af85c25ce9b6a828078076bd5fe57e118bdb8e96

Candidate.5 DG-00 author report SHA-256:
5f46395e952eaf1c4ab5f653188763359361fb63d315370a18d7a8474ba47cf1

Migration 0026 SHA-256:
5a501f6dfb093059b2054c8fc7c5663c9604fdf11be467cd89763e7caa8c16cb
```

Archive：`AF-09-candidate.5-ece90366-submission.tar.gz`

归档由 manifest 的 19 个 `required_files` 与全部 156 个 `source_locks` 精确生成，无重复。Project
文件使用 `MiLAi/` 前缀，workspace locks 保持 workspace 相对路径；Git-locked repositories 不复制
未声明正文。两次独立构建 byte-for-byte 相同。175 个成员全部是排序后的安全相对 regular-file
path，mtime 固定为 `2026-08-17T00:00:00+08:00`，numeric owner/group 固定为 0，gzip header 不含
时间；每个 archive member 已与 live locked file 逐字节比较，差异为零。

## Trusted review command

Reviewer 必须从本 receipt 独立复制 digest，不能从 candidate bundle 的自我声明推导：

```bash
TRUSTED_MANIFEST_SHA256="ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64"
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
```

缺 receipt、摘要不匹配、archive/live bytes 不同、source/Git drift，或 coordinated bundle+manifest
substitution，必须使 review 失败。

## Required independent adversarial replay

除完整 G1–G9、I-01–I-12、AF-00–AF-09、runtime/research/package/backup/security 门禁外，同一 reviewer
至少必须独立执行并裁决：

```text
fresh empty database base -> 0026
candidate.1 public procedures at 0014 -> head
pending resolution exact relation/hash quarantine and real Issue/Context absence
actual DeletionRequest plus creator, time, Evidence/Blob identity and all TX-05 state axes
four fresh timestamp conflicts: idempotency, OperationalEvent, revoke Outbox, purge Outbox
four candidate.3-compatible 0024 -> 0025 timestamp conflicts
four candidate.4-compatible 0025 -> 0026 timestamp conflicts
one valid six-timestamp 0025 -> 0026 control
every invalid path: AF09_UNPROVABLE_LEGACY_TX05, prior head, no migration residue
F01/F11 exact counterexamples and F02–F10 regression audit
both quarantine ledgers: forced RLS, grants, owner U/D denial, backup inventory/restore
```

四个 timestamp legs 必须分别独立偏移，不能用作者测试名、共享 UUID、时间接近或合法控制替代负向
证明。0026 是 proof-only compatibility certification，不得新增或替换 Proposal、Decision、transition、
event、Outbox 或 canonical authority。

## Pre-submission evidence

```text
architecture validate / all-scope development lock     PASS (18 bundle / 156 source locks)
architecture review-mode external trust anchor         PASS
architecture positive/negative tests                   PASS (19)
runtime Ruff format/check                               PASS (105 files)
runtime strict mypy                                     PASS (57 source files)
fresh base -> 0026 exact-role PostgreSQL suite          PASS (121 tests)
F12 timestamp/compat + migration foundation             PASS (13 / 33 tests)
catalog/head/RLS                                        PASS (32 durable / 31 tenant / head 0026)
backup/restore + security                               PASS (6 tests)
runtime wheel/sdist double build                        BYTE-STABLE (63 / 120 entries)
wheel SHA-256                                           149eb1ec203cb3c9751e351a2a4c18be1609c9e53598bdc55c05e25965d9a8ff
sdist SHA-256                                           d454cdd6ee4d65aec58566debec6a0023524bde5ef8ee96172021d91eae8a59b
locked wheel install                                    PASS (milai-runtime 0.1.0)
research isolation Ruff/mypy/tests/benchmark            PASS (7 source / 9 tests / 40 fixtures)
research fixture SHA-256                                8fd9482aacf58d8802a16dbc86a9e8043ffc28123d904f72b7b87a052eaa718a
research decision                                       ABANDON; novelty_claim=false
locked dependency sync / CI YAML / Compose              PASS
Markdown links/fences                                   PASS (79 files; 0 errors)
archive deterministic/safe/live-exact verification      PASS (175 entries)
```

全量数据库门禁使用全新 `milai_candidate5_gate_20260817a`。既有 `/milai` 开发库继续作为历史对抗状态的
取证样本，没有为获得绿色结果而重置、删行、伪造 DeletionRequest 或强制移动 Alembic head。

## Immutability and decision boundary

从本 receipt 生成后，candidate.5 bundle、manifest、156 个 source locks 与 archive 视为提交冻结对象。
若发现任何需要修改的内容，必须创建 candidate.6、新 archive 和新外部 receipt，不能刷新本摘要。

当前结论仍为：

```text
Architecture CANDIDATE — NOT FROZEN
AF-09 PENDING_INDEPENDENT_REREVIEW
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```
