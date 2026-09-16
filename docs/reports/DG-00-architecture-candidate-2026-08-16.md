# DG-00 MiLAi Logical Architecture Candidate 验收报告

> Review date：`2026-08-16`（Asia/Shanghai）  
> Architecture：`1.0.0-candidate.1`  
> Goal result：`IN_PROGRESS — CANDIDATE READY FOR INDEPENDENT REVIEW`  
> Schema：`0.1.x EXPERIMENTAL`  
> Implementation：`CANDIDATE`  
> Freeze decision：`NO-GO FOR SCHEMA FREEZE`

## 1. Outcome

MiLAi 已不再等待外部 frozen bundle。本项目依据当前 runtime 与本地 ReMe、Hindsight、Graphiti、
Mem0、benchmark 资产，自主形成根设计文档和 `architecture/v1.0-candidate/` 自包含候选包。

已交付：

- G1–G9、I-01～I-12、对象/角色/状态/事务/检索/Context/删除恢复规范；
- machine-readable `crosswalk.json`；
- bundle/source/Git SHA-256 manifest；
- bundle 与 lock validator；
- 缺文件、缺 invariant、缺负向证据、hash drift、path escape、Git drift 负向测试；
- authority、grounding、OpenIssue、sequence、Blob encryption/key、model/device、legacy data、
  L2/external adapter 与 bundle lock ADR；
- threat model/privacy review；
- AF-09 作者预检矩阵与 hard-reject sweep（明确不具独立签署效力）；
- AF-09 independent review checklist、hard-reject criteria 和未签署模板。

自动证据完整，但 AF-09 独立评审尚未发生，因此 DG-00 不能标为 `ACHIEVED`，架构也不能标为
`FROZEN`。

## 2. G1–G9 gate review

| Goal | Candidate evidence | Negative/failure evidence | Decision |
| --- | --- | --- | --- |
| G1 Source Fidelity | Evidence/Claim 独立、lineage、TX-01/02 | ingest 后 lineage 无 Claim；identity update 拒绝 | PASS_CANDIDATE |
| G2 Governed Evolution | proposal/decision/procedure/CAS/history | direct DML、CAS loser、history update 拒绝 | PASS_CANDIDATE |
| G3 Open-State Preservation | stable issue、branches、discharge、reopen | conflict 不移动 Head；非法/racing resolution 拒绝 | PASS_CANDIDATE |
| G4 Applicability Separation | typed axes、ECS、scope/time/authority Gate | stale/scope/time/authority mismatch 拒绝 | PASS_CANDIDATE |
| G5 Candidate-Safe Retrieval | L0/L1、QueryPlan、Gate、trace | vector outage 降级；canonical outage abstain；L2 off | PASS_CANDIDATE |
| G6 Revocation Propagation | TX-05 block/invalidation/outbox、purge/backup | stale pointer/projection 拒绝；shared/hold 不误删 | PASS_CANDIDATE |
| G7 Bounded Traceable Context | six sections、Bmin、pointer、Chat lineage | budget infeasible、revoke/confirm/outage abstain | PASS_CANDIDATE |
| G8 Least Privilege | five roles、forced RLS、loopback、redaction | cross-tenant/direct-DML/pool leak/secret canary 拒绝 | PASS_CANDIDATE |
| G9 Replaceable/Recoverable | external import absence、outbox rebuild、full restore | dependency absent、gap/tamper/catalog mismatch fail closed | PASS_CANDIDATE |

详细 path/node/report 映射由 `crosswalk.json` 校验。每个 I-01～I-12 具有显式
`positive_tests` 和 `negative_tests`，validator 对空集合 fail closed。

## 3. Architecture freeze gates

| Gate | Current evidence | Result |
| --- | --- | --- |
| AF-00 Baseline | design/config/dependency version/license/hash captured | PASS_CANDIDATE |
| AF-01 Objects | 30 durable tables audited；29 tenant-owned；identity/mutability/writer defined | PASS_CANDIDATE |
| AF-02 Invariants | exact G/I ID sets、positive/negative test mappings、hard failures | PASS_CANDIDATE |
| AF-03 Permissions | role/grant/RLS/procedure/network/log boundary | PASS_CANDIDATE |
| AF-04 Transactions | TX-01～06、EP-01/02、CAS、rollback、outbox mapping | PASS_CANDIDATE |
| AF-05 Retrieval/Context | QueryPlan、L0/L1/L2、Gate、Bmin、pointer、confirmation | PASS_CANDIDATE |
| AF-06 Delete/Recovery | sync block、purge/watermark、backup obligation、restore | PASS_CANDIDATE |
| AF-07 Isolation | external/model credential boundary + threat/privacy review | PASS_CANDIDATE |
| AF-08 Operations | manifest、runbooks、forward repair、privacy and recovery evidence | PASS_CANDIDATE |
| AF-09 Lock Review | validators pass；independent reviewer/decision absent | **PENDING** |

`PASS_CANDIDATE` 只表示材料和当前 synthetic implementation 证据足够进入评审，不等于 production
certification 或 frozen architecture。

## 4. Machine verification snapshot

```text
Architecture
  validate_bundle.py                         PASS
  verify_lock.py                             PASS
  unittest bundle positive/negative suite    PASS (14 tests)
  ruff format/check architecture scripts     PASS

Runtime
  uv sync --frozen --dev --python 3.11       PASS (36 packages audited)
  ruff format --check .                      PASS (90 files)
  ruff check .                               PASS
  mypy src                                   PASS (53 source files)
  pytest with real PostgreSQL roles          PASS (74 tests, 18.51 s)
  migration base → 0014 → base → 0014       PASS
  0013 trace sequence-key up/down migration  PASS
  sdist + wheel build                        PASS

Research
  ruff format/check                          PASS
  mypy --strict                              PASS (7 source files)
  unittest                                   PASS (9 tests)
  deterministic benchmark                    PASS (40 fixtures)
  novelty decision                           ABANDON
```

首次 pytest 诊断调用未加载 `MILAI_*` 测试 DSN，因缺 migration URL 在 setup 前失败；按 runbook
从现有 loopback PostgreSQL 容器加载专用 role credentials 后，完整 74 项重新执行并全部通过。
未把未配置运行计入成功证据。

## 5. Security/privacy decision

Threat Model 对 TM-01～TM-18 完成边界审查。当前批准范围仅为 local synthetic candidate：

- Blob 当前明文，ADR-012 的 envelope encryption、key recovery/rotation 未实现；
- 未批准真实个人数据或 legacy import；
- 未批准公网/远程访问；
- 未冻结 target-device performance SLO；
- external adapters 和 L2 保持关闭。

这些边界不否定 candidate 设计，但任何绕过均为 P0。特别是，真实数据必须等 ADR-012 的实现、
加密备份/恢复和独立隐私评审。

## 6. Remaining work

1. 独立 reviewer 逐项审查 G/I/object/permission/TX 和 threat model；
2. 对所有 review comment 形成 ADR/修订并刷新 manifest；
3. 在进入真实数据前实现 ADR-012（不作为 synthetic candidate 的伪完成项）；
4. AF-09 签署后发布新的 hash-stable release manifest；
5. 仅在以上条件满足后，另行决定是否发布 `MiLAi Logical Architecture 1.0.0 FROZEN`。

## 7. Gate decision

```text
Candidate bundle: READY FOR INDEPENDENT REVIEW
DG-00: IN_PROGRESS
AF-09: PENDING_INDEPENDENT_REVIEW
Schema freeze: NO-GO
Real personal data: DENIED
```
