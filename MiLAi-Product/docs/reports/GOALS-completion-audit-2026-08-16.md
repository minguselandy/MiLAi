# MiLAi Lean V1 Goals 完成审计

> **ARCHITECTURE UPDATE 2026-08-16：** 本报告的 runtime/research 验收事实继续有效；其中
> “DG-00 等待外部权威 bundle”的结论已被用户更正。DG-00 现为自研 Logical Architecture
> 设计与实现目标；LA-0～LA-4 candidate 已完成，当前结论见
> [DG-00 candidate report](DG-00-architecture-candidate-2026-08-16.md)。

> Audit date：`2026-08-16`（Asia/Shanghai）  
> Audit scope：`DG-00～DG-09、DG-R01、North Star vertical slice`  
> Product result：`DG-01～DG-09 ACHIEVED within local synthetic boundary`  
> Research result：`DG-R01 ACHIEVED; OSPC novelty ABANDONED by hard falsifier`  
> Master result：`IN PROGRESS — DG-00 CANDIDATE READY; AF-09 REVIEW PENDING`  
> Schema：`0.1.x EXPERIMENTAL`  
> Implementation：`CANDIDATE`  
> 冻结结论：`NO-GO FOR SCHEMA FREEZE`

## 审计方法

本审计从 `MiLAi_Lean_V1_设计开发_GOALS.md` 的每条关键结果反向检查源码、migration、API
contract、真实 PostgreSQL login role/RLS、并发路径、故障路径、恢复 drill、构建产物和研究
benchmark。完成判定不接受“代码存在”或单个 happy-path 测试，必须同时满足：

1. 正向结果可回放；
2. hard failure/fail-closed 路径受测；
3. durable 行为有数据库约束或 procedure 复验；
4. artifact 可定位并有 hash；
5. 报告明确适用边界和未关闭风险。

所有 fixture 和 drill 数据均为 synthetic；没有引入真实个人数据或真实生产 secret。

## 总结矩阵

| Goal | 逐项结果 | 关键机器证据 | 结论 |
| --- | --- | --- | --- |
| DG-00 | 自研设计、bundle、source/Git lock、crosswalk、ADR、threat review 完整 | validators + 14 bundle tests；AF-00～AF-08 pass | `IN_PROGRESS`；AF-09 pending |
| DG-01 | package/lock/API/worker/settings/Compose/migration/fixtures/health/CI/runbook/boundary 全部存在 | frozen sync、fresh migration、CI YAML、build、74 tests | `ACHIEVED` |
| DG-02 | 五角色、tenant context、forced RLS、pool reset、cross-tenant/direct-DML denial | 真实 login role security tests | `ACHIEVED` |
| DG-03 | content-addressed Blob、observation identity、TX-01、idempotency/race/rollback、permission-safe GET | contract/integration/concurrency tests | `ACHIEVED` |
| DG-04 | typed DeriveAndDiagnose/CommitPolicy、Proposal/User Review、immutable version、CAS、TX-02/03/04/06 | unit + canonical API + two-connection race | `ACHIEVED` |
| DG-05 | conflict preserves Head、structured OpenIssue branches、CAS/discharge/reopen、E1→E2→E3 | OpenIssue and canonical E2E tests | `ACHIEVED` |
| DG-06 | synchronous revoke/block/context invalidation、stale Gate denial、purge/retry/shared Blob/deletion/backup obligation | revoke/purge/recovery drill | `ACHIEVED` |
| DG-07 | outbox/watermark、L0/L1、typed persisted QueryPlan、Canonical Gate、trace/fallback/abstain、L2 disabled | projection/retrieval tests and four-stage trace | `ACHIEVED` |
| DG-08 | protected ContextCapsule、pointer recovery、live confirmation Evidence、traceable Chat/UI、Episode/Settlement | context/chat/episode tests and DB procedure checks | `ACHIEVED` |
| DG-09 | startup/build、fault behavior、exhaustive inventory、backup/revoke/expire/restore、privacy/runbooks | real pg_dump/pg_restore drill, wheel inspection | `ACHIEVED` |
| DG-R01 | 40 fixtures、equal-budget baselines/ablations、separate FC/unsupported/cost/failure metrics、isolation | strict checks, 9 tests, reproduced benchmark | `ACHIEVED`; novelty `ABANDONED` |

## North Star 纵向回放

```text
Evidence Ingest (TX-01)
→ DeriveAndDiagnose against current ECS
→ typed ValidatedProposal + persisted CommitPolicy trace
→ explicit Steward review
→ immutable ClaimVersion / exact-head CAS 或 structured OpenIssue
→ typed QueryPlan + L0/L1 candidates
→ Canonical Gate
→ protected ContextCapsule
→ traceable ChatTurn / Answer lineage
→ action-sensitive live USER_CONFIRMATION Evidence check
→ Episode capture / governed Settlement
→ Evidence revoke (TX-05)
→ synchronous GroundingBlock + Context invalidation
→ stale projection rejected; async purge and backup obligation reconciled
```

E1 accepted、E2 conflict/OpenIssue rejected、E3 governed resolution accepted、resolution Evidence
revoke 后 `GROUNDING_BLOCKED` 的四个阶段均有独立 RetrievalTrace。这个回放证明 projection 只
影响召回，不改变 truth/authority；canonical 不可用时返回 abstention/503。

## Requirement-by-requirement 结论

### DG-01 — Runtime 与 CI

- Flask app factory、API/worker/operations CLI、typed settings、PostgreSQL/pgvector 和本地 Blob
  root 均由 locked project 定义；
- Compose 缺 secret 时 fail fast，成功配置只监听 loopback；
- liveness 与 dependency-sensitive readiness 分离；
- integration fixture 只允许专用测试目标，fresh migration 执行完整 downgrade/upgrade；
- `.github/workflows/ci.yml` 启动 pgvector、建立分离 login roles，并运行 frozen sync、runtime
  format/lint/type/full tests 和隔离 research gate；
- runtime boundary tests 阻止外部 memory framework 进入在线依赖。

证据：[DG-01 report](DG-01-LG-01-evidence-2026-08-15.md)、
[local runtime runbook](../runbooks/local-runtime.md)。

### DG-02 — Tenant / Roles / RLS

- Migration Owner、API Runtime、Steward Executor、Projection Worker、Audit Runner 分权；
- transaction-scoped tenant/actor context 与 pool reset 防止借还泄漏；
- tenant-owned durable 表 forced RLS，两个 tenant/真实连接负向测试通过；
- Steward 只能执行 allowlisted procedure；API/worker/audit 不能 direct canonical DML；
- security-definer functions 固定 search path 并重复校验 tenant。

证据：[DG-02 report](DG-02-LC-003-security-2026-08-15.md)。

### DG-03 — Evidence Plane

- Blob content-addressed、tenant-local dedupe，Evidence observation identity 独立；
- source、observed time、capture identity、content hash 不可覆盖；
- TX-01 将 Evidence/idempotency/outbox 原子提交，同 key replay、fingerprint conflict 和 race
  受测；
- Evidence GET 对不可读 permission snapshot 不返回正文，跨 tenant 与 revoked content fail
  closed。

证据：[DG-03 report](DG-03-LC-004-evidence-2026-08-15.md)。

### DG-04 — Canonical Claim Core

- `DeriveAndDiagnose` 生成 typed `ValidatedProposal`，记录观察到的 ECS 与 relation/diagnostics；
- `CommitPolicy lean-commit-policy-v1` 结果持久化；candidate 阶段固定 `USER_REVIEW`，legacy
  proposal 同样保守；
- ClaimVersion/transition/decision append-only，ClaimHead 只通过 absence/exact-head CAS；
- TX-04 no-change/conflict 不创建版本或移动 Head，TX-06 只以新 Evidence/版本恢复；
- canonical procedure 内没有模型、embedding、向量或网络调用，decision/result/outbox 原子。

证据：[DG-04 report](DG-04-LC-005-008-canonical-2026-08-15.md)。

### DG-05 — OpenIssue 治理

- `CONTRADICT` 保留当前 Head，创建稳定 issue identity 与结构化 support/contradict/resolution
  branches；
- issue revision CAS、append-only transition、discharge rule/authority/Evidence 条件在 procedure
  中执行；
- summary、遗漏、时间经过或模型判断不能关闭 issue；resolution Evidence revoke 会重开同一
  identity 并阻断已解决版本。

证据：[DG-05 report](DG-05-LC-009-open-issue-2026-08-15.md)。

### DG-06 — Revoke / Delete

- TX-05 同事务写 revoke、GroundingBlock、Context invalidation、purge outbox 和 deletion 状态；
- canonical Gate 不信任 stale FTS/vector/cache 标志，提交后立即拒绝；
- purge 支持 idempotent retry/dead-letter/shared Blob live-ref 保护；
- backup deletion obligation 与物理擦除独立对账，retention/legal hold 不被绕过；
- 正式 deletion 查询 alias 为 `/v1/deletions/{id}`。

证据：[DG-06 report](DG-06-LC-010-progress-2026-08-15.md)、
[backup runbook](../runbooks/backup-restore.md)。

### DG-07 — QueryPlan / Retrieval / Gate

- 每个 projection 独立 delivery/lease/retry/dead-letter 与 contiguous watermark，gap 不可跨越；
- L0 canonical exact read；L1 metadata/time/scope prefilter + FTS/pgvector fusion/dedupe；
- versioned QueryPlanner 生成 typed QueryPlan：intent、散列 entity、time、Scope、authority、
  confirmation、complexity、consistency、budget 和 routes；不保存 query 明文；
- `0012_query_plan_trace` 将 plan 与 RetrievalTrace 持久化，并在 DB procedure 校验实际
  route/consistency/authority/scope；
- Gate 检查 tenant/permission/retention/revocation/head/block/scope/time/OpenIssue/authority/
  lineage；projection lag 回退 canonical，DB outage abstain，L2 禁用；
- 正式接口 `/v1/memory/query`、`/v1/system/watermarks`、
  `/v1/system/degraded-routes` 已受 contract tests 覆盖。

证据：[DG-07 report](DG-07-LC-011-014-retrieval-2026-08-15.md)。

### DG-08 — Context / Chat / Episode

- ContextCapsule 六分区；Goal/constraints/ECS/live OpenIssue 受保护，最小表示超预算显式
  `CONTEXT_BUDGET_INFEASIBLE`；
- pointer recovery 重验 ID/hash/permission/retention/revocation/blob/capsule TTL；
- ChatTurn append-only，不存 query 明文，DB procedure 重验全部 lineage 引用；
- action-sensitive Chat 需要 5 分钟内、可读、未撤销、source/ref/subject/content 匹配的
  `USER_CONFIRMATION` Evidence；该 Evidence 进入 answer/ChatTurn lineage；
- Episode capture 引用验证、idempotency、forced RLS；Settlement steward-only/CAS/append-only，
  最多三个 residual Proposal，使 Context 过期但不自动创建 ClaimVersion；
- UI 覆盖 review/correct/confirm/trace/revoke/capture/settle。

证据：[DG-08 report](DG-08-LC-015-017-context-chat-2026-08-15.md)。

### DG-09 — Local Beta / Recovery

- backup catalog 枚举所有含 `tenant_id` 的 base table，并要求与 inventory 配置完全相等；新
  durable table 漏配会使 backup/restore fail closed；
- 当前 29 表 inventory 覆盖 canonical、安全、Chat/Context、Episode/Settlement、projection、
  trace、operational/deletion/backup obligation；单 tenant 校验也逐表执行；
- 真实 drill 完成 backup A→revoke/purge→backup B→expire obligation→empty target restore，
  逐表 count/hash、Blob、revision、canonical ID、Episode/Settlement、block/watermark 对账；
- tampered dump 被 hash 拒绝；DB/vector/blob/worker 故障与 projection rebuild 有明确行为；
- frozen install/build、wheel resource inspection、隐私日志/trace 回归和 runbook 完整。

证据：[DG-09 report](DG-09-LC-018-local-beta-2026-08-15.md)。

### DG-R01 — OSPC 可证伪研究

- 40 个 synthetic fixtures 覆盖全局 Bmin 以下、恰好 Bmin、Bmin+12 和 full-raw feasible；
- 同一总预算比较 full raw、naive recursive、extractive top-k、hierarchical summary、structured
  eviction、typed state、static OpenIssue、OSPC、四项 ablation 与 oracle；
- 输出包含 Goal、constraints、stable state、open issues、evidence pointers、evicted recoverable
  和 compression trace；
- 分别报告 representation FC、decision FC、unsupported claim、goal/constraint/pointer recall、
  legal/later resolution、charged budget、wall/CPU/GPU/calls/failure distribution；
- OSPC 与 typed/static 强 baseline 在冻结主指标等价，且 validator 增加成本，按预注册 hard
  falsifier 放弃 novelty；研究代码、数据和凭据不进入 runtime。

证据：[DG-R01 report](DG-R01-RC-001-008-ospc-2026-08-15.md)。

## 最终机器验证

```text
Architecture gates
  validate_bundle.py                         PASS
  verify_lock.py                             PASS
  bundle unittest                            PASS (14 tests)

Runtime environment
  Python 3.11.13
  PostgreSQL 16.14
  pgvector 0.8.2
  Alembic 0014_query_plan_outbox_sequence

Runtime gates
  uv sync --frozen --dev --python 3.11       PASS (36 packages audited)
  ruff format --check .                      PASS (90 files)
  ruff check .                               PASS
  mypy src                                   PASS (53 source files)
  pytest                                     PASS (74 tests, 21.45 s)
  fresh DB base → head → base → head         PASS
  real backup/restore full inventory drill   PASS
  uv build + wheel content/source hash       PASS
  CI YAML parse / Compose config negative    PASS

Research gates
  ruff format --check research/ospc          PASS
  ruff check research/ospc                   PASS
  mypy --strict research/ospc                 PASS (7 source files)
  unittest discover                           PASS (9 tests)
  40-fixture equal-budget benchmark          PASS / decision ABANDON
```

## 关键 Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| CI workflow | `84d708b21c7e071e6604ae6f4ac3e439c0c5e9689be1ab272e1c61b96b3a1918` |
| `uv.lock` | `4f12bca74846302e734cc2d03f3f3f0573ad2f209c4332fa1d850eeae85d3f4b` |
| migration `0011_episode_settlement` | `8c7e68f9de4b9f28229c93d5deb8d50cf7118ae7d4f3c75b8fa5407a8a454114` |
| migration `0012_query_plan_trace` | `4b02d9c25cdceaa8310faf38abed84c64f187b4f84eb907ef225469921b9a6b6` |
| migration `0013_live_confirmation_gate` | `5f1c827d99825ef5889e0c6a6254d196da7154c99dd4214ebcf941c2c16bf452` |
| migration `0014_query_plan_outbox_sequence` | `a5ed271f01f0f1b82beb410b0b884141767aff0a7535eba278aaea4b6d19c190` |
| DeriveAndDiagnose / CommitPolicy | `d7e63e8b7cdbd6d50cd4f671cf2bc89ece8d849e088cc35800ebc61a35beadf9` |
| QueryPlanner | `a6d441290f7f0ee8921a81565f2f3b0197142e6d12a3b2075d27f387cf24bac9` |
| Chat live-confirmation service | `6fa5895a5cc9044c2c35fa8ea504debbb9ae58294526803150b95e9e1fececf1` |
| backup implementation | `49b59968702bc9ca5ff83aee7a0f9ebf141907596b238e76cecfbb180cb4784c` |
| full runtime test foundation | `fda41e135e27b1b1a9c7d59319e085ee5d1e0a72e9072e752077605a8fb7748d` |
| built wheel | `1632908d11d63b2f6db57a8bfd6f9f32eacf01de95f548d22077d4beab5fbb4a` |
| OSPC pilot metrics rerun snapshot | `1ee73817c4c1bd071f19aea452617183cf777ba654dbb858d7eb0fc2f8e93c8b` |

## 未关闭项与最终决定

DG-00 的 LA-0～LA-4 已达到 candidate 成功证据；历史 acquisition audit 已被 ADR-002 supersede。
当前唯一架构阶段缺口是 LA-5/AF-09 独立评审与评审后 release lock。ADR-009 双 sequence
语义已由 migration 0014 关闭；ADR-012 encryption/key implementation 是真实数据前硬门。详见
[DG-00 candidate report](DG-00-architecture-candidate-2026-08-16.md)。

因此本轮判定为：DG-01～DG-09 与 DG-R01 已在声明边界内完成；North Star experimental vertical
slice 已回放；DG-00 已进入独立评审但仍是 `IN_PROGRESS`。在 AF-09 正式接受前始终保持：

```text
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```
