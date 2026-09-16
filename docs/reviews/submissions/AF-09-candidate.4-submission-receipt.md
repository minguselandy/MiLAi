# AF-09 Candidate.4 Submission Receipt

> Submission：`MiLAi Logical Architecture 1.0.0-candidate.4`  
> Independent decision：`PENDING REREVIEW`  
> Reviewer：`/root/af09_reviewer_retry`（same independent reviewer）  
> Submission date：`2026-08-17`（Asia/Shanghai）

本 receipt 位于 candidate bundle 之外，是 AF-09 review-mode 的 manifest trust anchor。它只标识精确
提交 bytes，不宣称作者整改已被接受。Candidate.1/2/3 的 review、archive、receipt、remediation 与
report 均为不可变历史。

## Identity

```text
Candidate manifest SHA-256:
13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb

Deterministic submission archive SHA-256:
03ca6b686f21afacccb0a31ca9892ca2854a8a395d402adc26fb6374e36ec341

Archive bytes: 4767531
Archive entries: 168
Bundle required files: 19 (manifest + 18 locked siblings)
Source locks: 149

Candidate.3 independent rereview SHA-256:
321883a7b9b695f4727aee99375fbeb3daf9919314c7562f6854d2a826012e9c

ADR-018 SHA-256:
b3f3804d3dcae04aa27f5d452b622d7cc2e18e66158f288b3accb4ee0b3308a1

Candidate.4 remediation record SHA-256:
34a8212556ee696b6d70c1d67f62b6b68958c3d2326230343d27541d7436cd16

Candidate.4 DG-00 author report SHA-256:
ea06d3bf7143b1ce027e5eec400aba5275a47ed09465dfedd0a905e8bbcdc23a
```

Archive：`AF-09-candidate.4-13d0a948-submission.tar.gz`

归档由 manifest 的 19 个 `required_files` 与全部 149 个 `source_locks` 精确生成，无重复。Project
文件使用 `MiLAi/` 前缀，workspace locks 保持 workspace 相对路径；Git-locked repositories 不复制
未声明正文。两次独立构建 byte-for-byte 相同。168 个成员全部是排序后的安全相对 regular-file
path，mtime 固定为 `2026-08-17T00:00:00+08:00`，numeric owner/group 固定为 0，gzip header 不含
时间；每个 archive member 已与 live locked file 逐字节和 SHA-256 比较。

## Trusted review command

Reviewer 必须从本 receipt 独立复制 digest，不能从 candidate bundle 的自我声明推导：

```bash
TRUSTED_MANIFEST_SHA256="13d0a948daa0b9907fd8fc6d7142c6565f8afd3672471c1da2ed5814a5af57eb"
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
fresh empty database base → 0025
candidate.1 public procedures at 0014 → head
pending resolution exact relation/hash quarantine
already-decided REJECT quarantine and APPROVE retention/link
missing/conflicting resolution support-set whole rollback to 0023
real Issue API and L0-derived Context absence of rejected grounding
valid legacy TX-05 backed by the actual DeletionRequest
nine independently corrupted TX-05 proof legs → AF09_UNPROVABLE_LEGACY_TX05 / no 0024 residue
candidate.3-compatible 0024 → 0025 positive repair
candidate.3-compatible missing DeletionRequest → remain 0024 / no 0025 residue
both quarantine ledgers: forced RLS, grants, owner U/D denial, backup inventory/restore
```

Reviewer 必须重新裁决 AF09-F01/F11，并确认 F02–F10 没有回归。作者 PASS、ADR、本 receipt 与绿色
测试都不是 closure evidence 的替代品。

## Pre-submission evidence

```text
architecture validate / all-scope development lock     PASS (18 bundle / 149 source locks)
architecture review-mode external trust anchor         PASS
architecture positive/negative tests                   PASS (19)
runtime Ruff format/check                               PASS (104 files)
runtime strict mypy                                     PASS (55 source files)
runtime real exact-role PostgreSQL suite                PASS (108 tests on a clean database)
fresh/populated/compat migration adversarial gates      PASS
catalog                                                 PASS (32 durable / 31 tenant-owned / head 0025)
runtime wheel/sdist double build                        BYTE-STABLE (63 / 119 entries)
research isolation Ruff/mypy/tests/benchmark            PASS (7 source / 9 tests / 40 fixtures)
locked install / Compose interpolation                  PASS
Markdown links/fences                                   PASS (74 files)
archive deterministic/safe/live-exact verification      PASS (168 entries)
```

既有 `milai` 开发库保留为 candidate.3 负向取证样本：它在 0024，有 134 个 legacy revoke event，其中
四个因历史对抗测试缺失 actual DeletionRequest；candidate.4 0025 正确拒绝它。作者没有伪造或删除行来
抬头。正式门禁使用全新 `milai_candidate4_gate_20260817b`。

## Immutability and decision boundary

本 receipt 生成后，candidate.4 bundle、manifest、149 个 source locks 与 archive 视为提交冻结对象。
若发现任何需要修改的内容，必须创建 candidate.5、新 archive 和新外部 receipt，不能刷新本摘要。

当前结论仍为：

```text
Architecture CANDIDATE — NOT FROZEN
AF-09 PENDING_INDEPENDENT_REREVIEW
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```
