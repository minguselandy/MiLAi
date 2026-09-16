# AF-09 Candidate.2 Submission Receipt

> Submission：`MiLAi Logical Architecture 1.0.0-candidate.2`  
> Independent decision：`PENDING REREVIEW`  
> Reviewer：`/root/af09_reviewer_retry`（same independent reviewer）  
> Submission date：`2026-08-17`（Asia/Shanghai）

本 receipt 位于可变 bundle 之外，是 AF-09 review-mode 的 manifest trust anchor。它只标识提交
bytes，不宣称整改已被接受。Candidate.1 review/archive/receipt 仍是不变的首轮 `REVISE` 历史。

## Identity

```text
Candidate manifest SHA-256:
17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae

Deterministic submission archive SHA-256:
03bf746775beb60a0910f0bbec2539a62a4aa656e3d3de7cb82d667eca0c9544

Archive bytes: 1165262
Archive entries: 154

Prior independent review record SHA-256:
b12c64be6aea41cfb62ba9d8501a4cfc31f73dda0a50146de7d2367ae98f4707

Candidate.2 remediation record SHA-256:
096bdc1ad4de4ca8a320583f307d138e2072ce2922b8b283c46a19a4fbcaf6a9

Candidate.2 DG-00 evidence report SHA-256:
fd82f571b4005c780b195377fcef76116ced4a172a6b74c6586cb3243bf61175
```

Archive：`AF-09-candidate.2-17561675-submission.tar.gz`

归档由 manifest 的 `required_files` 与全部 `source_locks` 精确生成；project 文件以 `MiLAi/`
为前缀，workspace source locks 保持 workspace 相对路径。Git-locked 外部仓库不复制正文，其
commit/status/diff identity 保留在 manifest 中。归档使用排序路径、固定时间、numeric owner 和
`gzip -n`；第二次构建 byte-for-byte 相同。

## Trusted review command

Reviewer 必须从本 receipt 独立取得摘要，而不是从 candidate bundle 内推导：

```bash
TRUSTED_MANIFEST_SHA256="17561675750fa1add9f32f4dbe20f9a7ba6668861e0af2beb41e391dc55329ae"
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
```

缺 receipt、摘要格式错误、摘要不匹配，或内容与 bundle 内 manifest 协同替换，均必须使 review
失败。Reviewer 还需重跑真实角色 PostgreSQL runtime suite，并逐项审查 AF09-F01～F10，而不能只
依赖作者证据。

## Pre-submission evidence

```text
architecture validate / all-scope development lock   PASS
architecture review-mode external trust anchor       PASS
architecture positive/negative tests                 PASS (19)
runtime Ruff format/check                             PASS
runtime mypy                                          PASS (55 source files)
runtime real-role PostgreSQL suite                    PASS (92 tests)
fresh empty database forward migration to 0023       PASS
runtime wheel/sdist double build                      BYTE-STABLE
research isolation Ruff/mypy/tests/benchmark          PASS (8 source / 9 tests / 40 fixtures)
critical Markdown links/fences                       PASS (19 files)
```

## Immutability and decision boundary

从本 receipt 生成后，candidate.2 bundle、manifest、source locks 与 archive 视为提交冻结对象。
若发现任何需要修改的内容，必须创建 candidate.3、新 archive 和新外部 receipt，不能刷新本摘要。

当前结论仍为：

```text
Architecture CANDIDATE — NOT FROZEN
AF-09 PENDING_INDEPENDENT_REREVIEW
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```
