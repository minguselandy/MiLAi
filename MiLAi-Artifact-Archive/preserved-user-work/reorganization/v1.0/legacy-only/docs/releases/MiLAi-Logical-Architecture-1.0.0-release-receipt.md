# MiLAi Logical Architecture 1.0.0 Release Receipt

> Release：`MiLAi Logical Architecture 1.0.0`  
> Release state：`FROZEN LOGICAL ARCHITECTURE`  
> Independent release verification：`PENDING`  
> Release date：`2026-08-17`（Asia/Shanghai）

本 receipt 位于 `architecture/v1.0/` bundle 之外，是 release-mode 的外部 manifest trust
anchor。它标识精确的冻结逻辑架构、归档和已接受 candidate 证据链；它不是 schema freeze、
production readiness 或真实个人数据准入声明。

## 1. Frozen identity

```text
Release manifest SHA-256:
ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e

Deterministic release archive SHA-256:
dc43e4a5facb6037e14a98ca4f50e26a8bb599c3bd38440e8bcbd3869a3e4ff1

Archive bytes: 19138126
Archive entries: 180
Bundle required files: 19 (manifest + 18 locked siblings)
Source locks: 161 (150 project + 11 workspace)
Git locks: 9
```

Archive：`MiLAi-Logical-Architecture-1.0.0-ac16f3b7-release.tar.gz`

归档由 manifest 的 19 个 `required_files` 和全部 161 个 `source_locks` 精确生成且无重复。
Project 文件使用 `MiLAi/` 前缀，workspace locks 保持 workspace 相对路径；Git-locked
repositories 只由 commit/status/diff 锁定，不复制未声明正文。两次构建 byte-for-byte 相同。
所有成员均为排序后的安全相对 regular-file path，mtime 固定为
`2026-08-17T00:00:00+08:00`，numeric owner/group 固定为 0，gzip header 时间为 0；180 个
archive members 与 live locked files 逐字节相等。

## 2. Accepted candidate lineage

```text
Accepted candidate: 1.0.0-candidate.5
Candidate manifest SHA-256:
ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64

Candidate archive SHA-256:
aa56033be8380eee9289baec11c7839cbaa9bde4d66f69c6757fd9fb651ff668

Candidate receipt SHA-256:
2f8189339b6ee5b45107cee93c67005c1051171810913014631b1bd8c9aed680

Independent ACCEPT review SHA-256:
8ddf9e8a302b46404319ef2b27d99403f73b4d71127b4483c3b333d27230d1f3

Independent reviewer: /root/af09_reviewer_retry
Decision: ACCEPT
Open P0/P1/P2 findings: 0 / 0 / 0
AF09-F01 through AF09-F12: CLOSED
```

冻结 manifest 逐字段绑定上述四个 candidate acceptance objects。缺少任一对象、摘要不匹配、
把 candidate 状态伪装为接受状态，或 coordinated bundle + manifest substitution，均必须失败。

## 3. Promotion delta proof

Candidate.5 到 release 的核心规范归一化审计结果：

```text
OBJECTS / PERMISSIONS / INVARIANTS / TRANSACTIONS       NORMATIVE_BYTES_IDENTICAL
RETRIEVAL_CONTEXT / DELETION_RECOVERY / THREAT_MODEL   NORMATIVE_BYTES_IDENTICAL
common source locks                                     156
unchanged source locks                                   152
promotion-state documents changed                         4
accepted-evidence source locks added                       5
removed source locks                                       0
Git locks                                             BYTE_IDENTICAL
```

4 个变更对象仅为 `AGENTS.md`、实施合同、GOALS 和 Logical Architecture 设计文档的当前发布
状态；5 个新增锁仅为 candidate manifest、candidate archive、candidate receipt、独立 ACCEPT
review 和 release promotion report。没有 runtime、migration、research、ADR、runbook、CI、Compose
或外部项目身份漂移。

## 4. Release gate evidence

```text
manifest refresh check                              PASS (18 bundle / 161 source locks)
validator                                            PASS (1.0.0 frozen)
release-mode all-scope external anchor               PASS
bundle adversarial tests                             PASS (19)
runtime Ruff format/check                            PASS (105 files)
runtime strict mypy                                  PASS (57 source files)
fresh base -> 0026 exact-role PostgreSQL suite       PASS (121 tests)
research Ruff/mypy/tests/benchmark                   PASS (7 source / 9 tests / 40 fixtures)
CI YAML / Compose                                    PASS
runtime wheel/sdist double build                     BYTE-STABLE (63 / 120 entries)
wheel SHA-256                                        149eb1ec203cb3c9751e351a2a4c18be1609c9e53598bdc55c05e25965d9a8ff
sdist SHA-256                                        d454cdd6ee4d65aec58566debec6a0023524bde5ef8ee96172021d91eae8a59b
locked wheel install                                 PASS (milai-runtime 0.1.0)
release archive double build                         BYTE-STABLE
release archive safe/sorted/unique/live-exact        PASS (180 entries; 0 byte differences)
```

数据库门禁使用全新专用数据库 `milai_release100_gate_20260817a`。既有 `/milai` 数据库没有被
重置、修复或用来替代 fresh migration 证明。

## 5. Trusted release verification

Verifier 必须从本 receipt 独立复制 manifest digest，不能从 bundle 的自我声明推导：

```bash
TRUSTED_RELEASE_MANIFEST_SHA256="ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e"
runtime/.venv/bin/python architecture/v1.0/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0/scripts/verify_lock.py \
  --scope all --mode release \
  --expected-manifest-sha256 "$TRUSTED_RELEASE_MANIFEST_SHA256"
MILAI_ARCHITECTURE_LOCK_SCOPE=all runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0/tests -v
```

还必须独立验证 receipt、archive、manifest 三者摘要，archive/live 全成员身份，accepted candidate
四对象链，candidate-to-release 无规范语义漂移，以及冻结/实验边界声明。正式发布物复核记录只能
作为 bundle 外部新文件写入，不得修改本 receipt 或任一冻结对象。

## 6. Immutability and boundary

本 receipt 生成后，`architecture/v1.0/`、manifest 的 161 个 source locks、9 个 Git locks、release
archive 与本 receipt 均视为不可变发布对象。任何内容变更必须使用新版本、新 manifest、新 archive
和新 receipt；不得原地刷新摘要。

当前边界为：

```text
Logical Architecture 1.0.0 FROZEN
AF-09 ACCEPTED_INDEPENDENT_REVIEW
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
Synthetic data only
NO-GO FOR SCHEMA FREEZE
```
