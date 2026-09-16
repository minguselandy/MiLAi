# AF-09 Author Preflight

> Architecture：`1.0.0-candidate.5`  
> Review type：`AUTHOR_PREFLIGHT_NOT_INDEPENDENT`  
> Result：`CANDIDATE.5_REMEDIATED_READY_FOR_REREVIEW`  
> AF-09：`PENDING_INDEPENDENT_REVIEW`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件记录实现作者在移交 AF-09 前完成的证据预检。它不具备独立性，不能签署 AF-09、不能
批准 Schema freeze，也不能替代 `FREEZE_REVIEW.md` 中 reviewer 对证据的重新执行与判断。

## 1. Scope and method

预检逐项反查：

```text
G/I normative statement
→ object/role/transaction/retrieval/delete specification
→ ADR and migration
→ runtime procedure/application boundary
→ positive and hard-failure test node
→ report and manifest/source/Git lock
```

结论只适用于当前 manifest 标识的 local synthetic candidate。任何文件、外部仓库状态或测试环境
变化都要求刷新 manifest 并重跑本预检；Reviewer 必须在开始评审时另行记录实际 manifest
SHA-256。

## 2. Semantic preflight matrix

| ID | Independent-review check | Author preflight | Evidence and adversarial question |
| --- | --- | --- | --- |
| PF-01 | G1–G9 相互一致且没有循环授权 | PASS_AUTHOR_PREFLIGHT | `INVARIANTS.md`、根设计 §4；canonical state 只由 Steward procedure 改变，Evidence/Context/projection 均不能自授权。Reviewer 应寻找任何“由检索结果证明其自身 authority”的环。 |
| PF-02 | I-01～I-12 各有正/负向可执行证据 | PASS_AUTHOR_PREFLIGHT | `crosswalk.json` exact-ID mapping；validator 要求每项 design/implementation/test/report 和独立 positive/negative nodes。删除 I-12 或负向集合的测试会失败。 |
| PF-03 | Evidence/Claim/OpenIssue/Context identity 边界 | PASS_AUTHOR_PREFLIGHT | `OBJECTS.md`、ADR-003/004/006；Evidence 是观察，ClaimVersion 是治理结果，OpenIssue 有稳定 identity/revision，Context 只保存受保护引用。Reviewer 应尝试通过 summary/Context 制造 Evidence 或移动 Head。 |
| PF-04 | Steward single-writer、CAS、append-only、rollback | PASS_AUTHOR_PREFLIGHT | `PERMISSIONS.md`、`TRANSACTIONS.md`、migrations 0004/0005/0015/0016/0024–0026；fresh writes 与三代 populated/compat upgrade 均要求 V1/Issue creation history、noncanonical proposal、approved-only grounding、governed resolution/revoke 和连续 immutable replay；无法证明时回到 prior head。 |
| PF-05 | authority/Scope/time/freshness/epistemic 正交 | PASS_AUTHOR_PREFLIGHT | ADR-008/015、migrations 0017/0021；ECS 是全部 Gate decision facts 唯一来源，Gate/Context 覆盖 lifecycle、epistemic、freshness、confidence、Scope、valid/system time。 |
| PF-06 | projection/external/model 不提升 truth/authority | PASS_AUTHOR_PREFLIGHT | `RETRIEVAL_CONTEXT.md`、ADR-010；L0/L1 candidate 都进入 canonical Gate，L2/external disabled，runtime import-boundary test 阻止外部 framework 成为在线依赖。 |
| PF-07 | revoke/invalidation/purge/Blob/backup fail closed | PASS_AUTHOR_PREFLIGHT | `DELETION_RECOVERY.md`、migrations 0016/0019/0021–0026；同步 governed TX-05 先于异步 purge，ERASED 需要 SQL 可重算的 identity-bound absence proof；legacy TX-05 migration 必须 join actual DeletionRequest，并证明六个 durable timestamps 精确一致。13 个新时间/compat nodes、33 个 foundation tests、121 项 exact-role full suite 与独立 backup/security 6 项均已通过。 |
| PF-08 | tenant/RLS/roles/network/secrets/log 最小权限 | PASS_AUTHOR_PREFLIGHT | `PERMISSIONS.md`、Threat Model TM-01～TM-27；每个连接精确 attestation `milai_api/steward/worker`，owner/role swap/unsafe role 被拒；两个 quarantine ledger forced-RLS/append-only，causal secret 与 API secret 强制分离。远程访问未批准。 |
| PF-09 | dual sequence/watermark/RYW/recovery 无歧义 | PASS_AUTHOR_PREFLIGHT | ADR-009/016、migrations 0018/0020；服务器由真实 Outbox ID 签发 tenant-bound token，bounded wait 的 REACHED/TIMEOUT/DEAD_LETTER 与耗时持久化，fallback 和 snapshot advance 均有因果测试。 |
| PF-10 | external assets 可关闭且 identity/license 可验证 | PASS_AUTHOR_PREFLIGHT | `BASELINE.md` 与 manifest Git/source locks；ReMe/Hindsight/Graphiti/Mem0/benchmarks 仅为只读参考或离线评估，没有 Steward credential，核心启动/恢复不依赖它们。 |
| PF-11 | threat residual risk 与 synthetic-only 边界 | PASS_WITH_DECLARED_BOUNDARY | Threat Model 对 synthetic local candidate 为 PASS；TM-10 plaintext Blob、remote、host root、performance abuse 和独立隐私评审仍开放。Reviewer 必须显式接受该边界，否则 REVISE。 |
| PF-12 | migration/rollback/legacy/real-data change policy | PASS_AUTHOR_PREFLIGHT | 真实 public procedures 的四个 fresh 时间反例、四个 candidate.3 0024→0025 反例、四个 candidate.4 0025→0026 反例及合法控制均直接通过；全新数据库 base→0026 与 121 项 full suite 通过。0015+ 因治理/擦除/隔离/认证审计不可逆而拒绝 downgrade。ADR-014/017/018/019 定义 legacy path；真实数据仍由 ADR-012 阻断。 |

## 3. Hard-reject preflight

| Hard-reject condition | Author observation | Evidence that reviewer must reproduce |
| --- | --- | --- |
| unmapped G/I/MUST 或仅有间接 evidence | NOT OBSERVED | exact ID/coverage validator、13+ negative bundle tests、machine crosswalk |
| API/worker/model/adapter direct canonical DML | NOT OBSERVED | real-role grant/RLS tests、external dependency boundary |
| tenant/permission/retention/revoke/outage fail open | NOT OBSERVED | security/retrieval/revoke/Context failure tests |
| issue 因摘要、遗漏、时间或模型自动关闭 | NOT OBSERVED | conflict/discharge/reopen tests and OpenIssue CAS |
| projection/Context/graph/external memory 成为 authority | NOT OBSERVED | canonical Gate and external-off tests |
| CAS loser/rollback/outbox/history 部分写 | NOT OBSERVED | concurrency and atomicity tests |
| populated migration 保留 rejected grounding、信任无实体 UUID/冲突时间或在 proof 失败后留下 residue | NOT OBSERVED IN COMPLETE AUTHOR GATE | exact support/hash quarantine、actual DeletionRequest multi-leg/six-time proof、real Issue/Context、fresh/candidate.3/candidate.4 prior-head rollback tests；全新 exact-role full suite 与 catalog/backup/security gate |
| manifest/source/Git drift 或 coordinated bundle+manifest 替换未拒绝 | NOT OBSERVED | full-scope verifier、外部 manifest trust anchor 与 drift/path/omission/coordinated-tamper tests |
| 隐瞒真实数据、远程或 residual-risk gate | NOT OBSERVED | candidate banners、Threat Model、ADR-012/014、DG-00 report |
| AF-09 前移除 candidate/no-go banner | NOT OBSERVED | validator banner and forged-acceptance tests |

`NOT OBSERVED` 不是独立证明。Reviewer 应把任一反例登记到 `FREEZE_REVIEW.md` findings；P0/P1
未关闭时必须 REVISE/REJECT。

## 4. Reproduction snapshot

作者在全新 `milai_candidate5_gate_20260817a` 上完成的 candidate.5 preflight：

```text
runtime Ruff format/check                          PASS (105 files)
runtime strict mypy                                PASS (57 source files)
fresh base -> 0026 + exact-role full suite         PASS (121 tests)
new F12 timestamp/compatibility nodes              PASS (13 tests)
migration foundation regression                    PASS (33 tests)
backup/security + catalog/RLS                      PASS (6 tests; 32/31 tables)
research isolation                                 PASS (7 source; 9 tests; 40 fixtures)
double package build / locked install              PASS (63 wheel / 120 sdist entries)
CI YAML / Compose / Markdown links and fences      PASS (79 Markdown files)
architecture scripts / validator / lock / tests    PASS (19 tests after final relock)
```

本文件纳入最终重锁；以上运行事实仍不得用于跳过独立 reviewer 的
`validate_bundle.py`、`verify_lock.py --scope all` 和完整证据重跑。

## 5. Declared gates

独立 reviewer 接收的明确边界：

- candidate.1–4 独立 review 均为 REVISE；candidate.4 关闭 F01、修复 exact F11，但 F12 为 P1
  OPEN；candidate.5 尚无 ACCEPT/signature；
- Blob 仍是 plaintext，真实个人数据为 DENIED；
- remote/public deployment 为 DENIED；
- L2/external adapters 默认关闭；
- target-device performance SLO 未冻结；
- local root/host compromise 不由 RLS 防护；
- OSPC novelty 已按 hard falsifier 放弃，不是产品依赖。

## 6. Handoff result

```text
Author preflight: CANDIDATE.5_REMEDIATED_READY_FOR_REREVIEW
Independent reviewer: SAME REVIEWER ASSIGNED FOR REREVIEW
Independent decision: PENDING
AF-09: PENDING_INDEPENDENT_REVIEW
Freeze: NO-GO
```
