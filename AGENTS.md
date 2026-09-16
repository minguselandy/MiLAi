# AGENTS.md

本文件指导在 `MiLAi/` 目录及其子目录中工作的编码代理。目标是把 MiLAi Lean V1 做成一个小而正确、可追溯、可测试的本地个人记忆系统，而不是提前扩建完整 memory platform。

## 当前仓库状态

当前目录已有 `0.1.x EXPERIMENTAL` Runtime。用户已明确 MiLAi Logical Architecture 不是待下载
的外部原件，而是本项目需要基于当前实现和已有项目自行设计、实现并验证的架构。精确
`1.0.0-candidate.5` 已由同一 independent reviewer 全量 `ACCEPT`，F01–F12 全部关闭；独立
`architecture/v1.0/` 是当前 `1.0.0 FROZEN` Logical Architecture。Runtime 仍为
`0.1.x CANDIDATE`，Schema 仍为 `0.1.x EXPERIMENTAL / NO-GO`。只有实际通过的命令和门禁才能被宣称完成，
不要因为文档或代码描述了目标能力就宣称它已通过测试。

Agent Integration `0.1 candidate.1` 的独立审查为 `REVISE`；candidate.2 已关闭泄露 sdist、完整
credential/KEK rotation、inventory/CI、不可变 host recall policy 与 ProposalDraft 边界，并通过独立
re-review。Agent Execution Optimization candidate.2 也已通过本地 synthetic 独立复审，本地开放
P0/P1/P2 为 0/0/0；真实 provider usage/billing/同模型质量证据 OE-F06 仍开放。candidate.3 provider
readiness 独立复审为 `REVISE`；candidate.4.4 已针对伪造 reconciliation、执行字节/approval 自指、文件与
网络隔离、pre-call 预算、真实 shipped tool schema、CI 和有界 partial receipt 缺口提交独立复审。工具结果永不自动
产生 PASS；candidate.4.3 因未强制执行 dependency closure 被独立判 `REVISE`，candidate.4.4 以
Landlock read/execute allowlist 整改；在其独立验收及真实 provider/model 报告完成前不得宣称 Beta。

当前文件：

- `MiLAi_Logical_Architecture_v1_设计文档.md`：当前 `1.0.0 FROZEN` Logical Architecture，
  定义 G1–G9、I-01～I-12、对象、边界、事务和 change control。
- `architecture/v1.0/`：不可原地修改的 frozen bundle、crosswalk、manifest、threat model 和
  validator；release verification 必须使用 bundle 外 digest。
- `architecture/v1.0-candidate/`：被接受的 candidate.5 历史；其 archive/receipt/review 不得
  改写，也不能替代 frozen release。
- `MiLAi_Lean_V1_实施合同.md`：Lean V1 当前实施合同；开始开发前必须完整阅读。
- `MiLAi_Lean_V1_设计规划与开发路线_v1.md`：从零开发的目标架构、资产复用边界、阶段路线和验收索引；它是执行导航，不覆盖实施合同语义。
- `MiLAi_Lean_V1_设计开发_GOALS.md`：开发目标、当前优先级、成功证据和 Goal 晋级规则；使用 `DG-*`，不与冻结架构 `G1–G9` 混用。
- `MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md`：`MILA-ML-ARCH@1.0 / ACTIVE_PROGRAM_BASELINE`，
  只定义 Memory Formation、Memory Evolution、Memory Recollection 的 Program/Plane、跨层边界、
  sidecar freshness/revocation 与 Evolution Bridge；不保存动态执行状态，也不修改 `architecture/v1.0`。
- `MiLAi_Memory_Lifecycle_总_GOALS.md`：`MILA-ML-MASTER@2.1 / ACTIVE_EXECUTION_MASTER`，上述三 Program 的唯一执行顺序来源。MVP U0 24-case context-only 已由 `mvp01-u0-20260901-017` 以 24/24 PASS 封存；warm `001` 因 eval-only `session_ordinal` 越界进入 strict Runtime wire 而不可变 FAIL，旧 2-event + 0-event production-path probe 只关闭该根因。fresh warm `mvp01-u0-warm-20260901-002` 也已不可变 FAIL：100 个 request、100 个 logical attempt、1 个 Runtime attempt、90 个 archive、Reader/Answer/Judge 0；独立审计将其分为 50 个 evaluator 假失败、30 个 typed semantic-abstention 结果（其中 Bicycle 另有 receipt losslessness 缺陷）、10 个合法 safe-empty terminal 但不满足本 run-lock 正向锚点，以及 10 个真实 Atlas window-count contract 失败，故 `0/100 Context terminal` 不得当作产品成功率。`001`、旧 probe 与 `002` 均不得重放、覆盖或重封。当前只激活 `MILA-MVP-01@0.1 / U0 / MVP01_U0_WARM_002_FAILURE_REPAIR_PROBE / mvp01-u0-warm-repair-probe-20260901-002`：允许固定 synthetic fixture 的 10 个不同 query class 各执行 1 次 Context，benchmark 访问禁止，Reader/Answer/Judge 为 0；formal 100-request successor、formal holdout、公开 MCP/Schema、default-on 和 Canonical promotion 均未授权。
- `MiLAi_ML-R01_ProjectionWorker租约与Formation送达Binding闭环修复_GOALS.md`：predecessor。R4 user-limited checkpoint 已封存 32/32 successful contexts、8/8 exact Raw/Formed snapshots；一个 cleanup witness 和 projected resource window fail-closed，Formation applied 0，answers/judges 均未运行。不得覆盖或重跑这些历史 cells。
- `MiLAi_ML-R02_统一MemoryLifecycle架构收敛与LongMemEval验证_GOALS.md`：已终结为 `COMPLETE_USER_LIMIT_8X4`；32/32 Context、Answer、Judge、Score cells 已封存，不 resume、不覆盖。
- `MiLAi_GDPM-01_受治理双过程Memory分阶段开发与验证_GOALS.md`：前驱 Goal；B0 targeted fixtures 为 `71 passed`，24-case attempt-003 为 4/24 PASS，失败精确分为 14 个缺 ContextReceipt 与 6 个 MCP output-limit。其活动写权已关闭，未执行复杂分支保持 OFF，历史 terminal 不得覆盖。
- `MiLAi_MVP-01_高效可用Memory最小闭环_GOALS.md`：当前唯一活动 Goal。U0 golden、已知根因 fixtures 和 24/24 context-only 已通过；warm-002 已不可变 FAIL，当前仅修复并验证 10-class synthetic production path，Reader/Answer/Judge 仍禁止。repair probe 与独立复审 GO 前不得授权新的 100-request formal run；之后才按 U0→U3 连续刷新 exact scope，始终不授权 formal holdout、public MCP/Schema、default-on 或自动 Canonical promotion。
- `MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md`：DG-26～DG-30 的 Read Path / Recollection 子计划。DG-27 保留终态负结果；DG-28 deterministic union 与 formed consumption 已闭合 7/7；DG-29 因无 residual opportunity 不进入；DG-30 仅封存 read path，`release_ready=false`。
- `MiLAi_MF-01-MF-06_Memory_Formation_and_Representation_MASTER.md`：Memory Formation 主线；MF-01/MF-02/MF-03/MF-04/EV-01/MD-01/MD-02 已封存。MF-02 在 24-case sealed non-holdout 集上支持 H1/H2；MD-02 将 over-merge 降为 0，但 over-split 增量 `0.027778 > 0.02`，故 H1 MISS；official-path shadow 的 identity/freshness/fallback/zero-call gates 全通过，故 H2 PASS。保留 shadow contract、拒绝当前 V02；这不等于 formal holdout 或产品结论。MF-06 当前只支持开发集工程增益、不支持 ML-H1 泛化。FormationArtifactCandidate 必须
  raw-preserving、noncanonical、provenance-linked 和 rebuildable。
- `MiLAi_DG-26-DG-30_自适应检索与集中验证_总_GOALS.md`：
  `SUPERSEDED_AS_GLOBAL_EXECUTION_NAVIGATION / RETAINED_AS_PROGRAM_C_HISTORY`；不得再用于创建 run-lock。
- `MiLAi_DG-31_简单记忆形成与单次读取闭环_GOALS.md`：已由项目重分层替代；其中
  formed + simple 假设迁移到 MF-06，在 MF-01 前不得直接实施。
- `MiLAi_DG-12高效Benchmark与论文实验_GOALS.md`：2026-08-24 起接管 DG11 冻结功能候选之后的
  既有代码本体化整理、结构规范化、通用效率优化、薄 evaluation harness、正式 baseline/benchmark/消融、
  统计和反思。当前 Goal 为 `v0.9.1 PRE_LABEL_PARALLEL_EXECUTION`：goal-specific `BHE01 RuntimeSlot`
  方向已停止，`CORE00～02`、`PD00～02`、`EH00～04` 与 `ND00～05` 均已有 terminal。`DG12-PD02` 的
  功能实现被 EH04 确认为等价，但 online、deep 与 cold 性能目标均为 terminal miss；FP6 untouched
  confirmation 已消费且禁止重跑，产品 speed claim 不成立。当前唯一产品/评测身份为 product manifest
  `cdf3d942aadeaa8e57743bf2691758303852c5f5047244a0acfe638f811bd16a` 与 harness content identity
  `577541aba3df4c2a8fc5427ff011afcfc5ed04fc0877085d0908e18f236163ad`。
  `DG12-ND02=PASS_DEV_SIGNAL`、`DG12-ND03=PASS_MECHANISM_DISTINGUISHED`；一次有边界的 ND04 查新已结束，
  方法主张为 `OVERLAPS_PRIOR_WORK`，只有八个 synthetic block 的 numeric-distractor 结果保留为
  `EMPIRICAL_FINDING_MAY_BE_DISTINCT` 的负面/边界候选。用户已明确授权按 `codex_sol_xhigh.md` 由一次
  `gpt-5.6-sol` xhigh owner-decision delegate 代选；`DG12-ND05=PASS_SELECTED_BOUNDARY_PACKAGE`，
  `C-BOUNDARY-001` 与 `C-EMPIRICAL-001` 均只作为待正式验证的选定假设，方法新颖性、SOTA、性能提升、
  广义质量与安全性主张仍禁止。`DG12-PE00=PASS_DOCUMENT_FREEZE_EXECUTION_GAPS_DISCOVERED_PE02`：claim matrix、thresholds、method
  inclusion/config、两个确认性 public strata、五个实验 block 与完整 seeded Latin matrices 已在 0 条正式
  label、0 个 aggregate score、0 次 model call 下完成文档 freeze。`DG12-PE01=PASS`：冻结
  harness 58/58、5 个 opened-development case 的 20 条 controlled context、四个 legacy native 静态身份与
  OpenViking `URI/FIND/CONTEXT` 技术门禁均已通过；legacy probe source drift、OpenViking 首次 14 个 embedding
  401、接口诊断失败与 context 零条目的合同边界均已保留，不能当作正式质量证据。`DG12-PE02` 的零调用
  pre-label audit 已 terminal 为 `BLOCKED_PRE_LABEL_PROTOCOL_AND_HARNESS_GAPS`：正式 runner 要求的 one-way
  paper manifest 不存在，runner 仍使用 DG11 Latin namespace 且拒绝 `DG12-BATCH` 与三个 OpenViking arm，
  两份独立盲法 operand annotation 缺失，LongMemEval checkout 还有两个未绑定的 tracked source drift。用户随后已
  授权唯一 `DG12-PE00V3` pre-label successor；两份独立盲法 annotation、consensus 与 claim disposition 已完成，
  v3 runner、producer、clean source identity 与绑定 56 个文件的 one-way manifest 已完成；无标签
  PE01/PE02 gate 均 PASS，且已生成绑定两个 terminal 的独立正式执行授权。正式 paper labels、contexts、
  answers 与 aggregate scores 仍均为 0。当前只允许先建立并验证唯一 PE02 正式 resource plan；资源预检
  PASS 后才得一次性打开 labels 并运行 100×11 method output。
  当前机器容量为 16 物理核、约 215 GiB available RAM、4×A100；vLLM 使用 GPU0/1，GPU2/3 可供隔离 baseline。
  旧 `context/answer <=2` 限制已废止，v3 使用 8-way stateless/answer lane、4 个独立 stateful process（每进程
  1 worker）与 2 个确定性分片的 dense GPU process（分别绑定 GPU2/3）；harness hard ceiling 16。并发只改变物理调度，不增加 logical attempt、
  retry、hidden Provider call 或 failure denominator，answer/judge service window 必须分离。
  当前 DG-12 candidate 继续禁止训练或微调 answer/router/retriever/
  reranker/compiler/control model，Task Resolver 的 LLM、embedding、retrieval、training 与 hidden Provider
  calls 必须为 0；只有 PE08 E2E 与至少一个 core memory benchmark 完整通过且 deterministic residual 被证明
  materially limiting 后，PE11 才能考虑 successor Goal。OpenViking production backend 继续 PARK；官方
  `v0.4.16` source/wheel/config 已预冻结，`URI/FIND/CONTEXT` 三档只在隔离 Evaluation Plane 作为 native
  baseline，PE01 无标签技术 gate 已通过但尚无任何正式结果，Governed State Behavior 固定写
  `NOT_SAME_CONTRACT`。旧
  `MiLAi_DG-11记忆质量与Agent效率优化_GOALS.md` 保留为历史证据，不再作为后续状态板。MiLAi 的主产品接口是
  MCP，首要宿主是 OpenWorker；权威纵向路径是
  `OpenWorker → relay/UDS → broker → milai-mcp → milai-runtime`。Python Client 是 MCP 内部 SDK，
  LangGraph/AutoGen/Generic direct-client 仅为次级 portability smoke。`evals/` 可保留 dataset mapping、协议、
  scorer 和特殊适配，但正式 MiLAi arm 必须走 OpenWorker/MCP，且 `evals/` 不得拥有 MiLAi 业务行为。
- `MiLAi_Lean_V1_产品底座与研究核心.md`：近期产品范围与唯一研究方向。
- `MiLAi技术升级需求说明_v2.md`：长期架构与能力地图。
- `MiLAi开发实施与使用流程_v1.md`：完整工程路线，其中部分阶段已暂停。
- `MiLAi_Lean_V1_产品底座与研究核心.zip`：2026-08-11 的文档快照，不是编辑源。
- `runtime/`：实验性 Flask/PostgreSQL/worker 实现；以其中 `pyproject.toml`、锁文件、Migration 和真实测试为准。
- `docs/adr/`、`docs/runbooks/`：实验性实现决策与本地运行手册。

若后续新增新的 architecture/runtime 版本，及时更新本节，但不要凭计划虚构目录和命令。

## 开始工作前

按顺序执行：

1. 阅读本文件和 `MiLAi_Lean_V1_实施合同.md`。
2. 确认用户请求属于 Lean 在线产品、离线研究还是暂停路线。
3. 查找当前代码、Schema、Migration、测试和相邻文档；不要只根据概念图实现。
4. 找出受影响的 invariant、事务、权限、删除和回滚路径。
5. 先做最小、可验证的纵向改动，再考虑抽象或扩展。

Logical Architecture 已通过 AF-09；实验性 Runtime 与 Schema 仍必须保持：

```text
Schema 0.1.x EXPERIMENTAL
Implementation CANDIDATE
NO-GO FOR SCHEMA FREEZE
```

## 规范优先级

文档或实现发生冲突时使用以下顺序：

1. 已发布的 `architecture/v1.0/` MiLAi Logical Architecture frozen 版本；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` 中的 frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. `MiLAi_Lean_V1_产品底座与研究核心.md`；
5. 其他现有需求、路线和流程文档中未暂停的部分；
6. 实验性代码、Schema 和注释。

设计候选中的 G1–G9/I-01～I-12 不得由实现变更静默重定义。涉及对象身份、单写者、权限、
删除或 invariant 的变化必须提交 ADR，并同步设计、bundle、crosswalk 和测试。

## Lean V1 活跃范围

在线产品只围绕以下闭环开发：

```text
Evidence Ingest
→ DeriveAndDiagnose
→ Validated OperationProposal
→ CommitPolicy / User Review
→ Versioned Claim 或 OpenIssue
→ Exact / FTS / pgvector Retrieval
→ Canonical Gate
→ Minimal ContextCapsule
→ Answer with Trace
→ Evidence Revocation and Fail-Closed Cleanup
```

默认运行组件：

```text
Flask API
PostgreSQL
one background worker
LLM/embedding client
local content-addressed blob store
```

优先完成的纵向切片：

```text
Evidence
→ ClaimVersion/OpenIssue
→ L0 exact retrieval
→ revoke Evidence
→ GroundingBlock
→ stale candidate rejected
```

## 暂停范围

除非用户明确要求重新开启且任务包含相应评测与治理工作，否则不要实现或接入：

```text
MemoryIntention scheduler
ReMe/OpenViking production backend  # DG-12 隔离 Evaluation baseline 不等于 production backend
Hindsight production route
Graphiti/Zep production route
automatic Scope Evolution
automatic Pattern/Profile Promotion
LoRA personalization
multimodal/family sharing
multi-agent memory governance
```

暂停功能不得成为启动依赖、在线数据必填项、UI 承诺或 Lean V1 Definition of Done。外部项目可以用于隔离 baseline，但不能获得 canonical 写凭据。

## 不可破坏的产品原则

- PostgreSQL Canonical Core 是唯一正式状态来源。
- `EvidenceRecord` 表示观察，不表示系统接受该事实。
- `ClaimVersion` append-only；变化创建新版本，禁止原地覆盖。
- `ClaimHead` 只能通过 exact-head CAS 移动。
- `OperationProposal` 是建议，不是 canonical state。
- 只有受控 Canonical Procedure 可以提交 Claim/OpenIssue 正式变化。
- `ContextCapsule`、Summary、模型输出和搜索结果都不能制造 Evidence 或 canonical truth。
- 冲突默认创建或更新 `OpenIssue`，不能自动覆盖当前 Claim。
- OpenIssue 不能因摘要、压缩、检索遗漏或时间经过而关闭。
- confidence、authority、freshness 和 epistemic status 必须分别判断。
- 删除先同步 fail closed，再异步清理派生副本。
- 二级索引故障只能降低 recall，不能提高 authority。
- Production 与 Audit 的角色、写入和发布决策必须隔离。
- Canonical store 不可用或证据不足时，系统必须 abstain，不得伪装确定。

## 规范命名

新代码、表、API 和测试统一使用：

| 使用 | 不再新建 | 说明 |
| --- | --- | --- |
| `grounding_relation` | `claim_evidence_edge` | 后者仅是旧文档别名 |
| `steward_decision` | `commit_decision` | 唯一持久化决策名称 |
| `EffectiveClaimState` | 自定义 current 判断 | 统一执行 revocation、block、scope、time、authority gate |
| `CONTRADICT` | 数据库中的 `CONFLICT` operation | `CONFLICT` 是产品级诊断结果 |
| 明确内部 operation | 数据库中的笼统 `UPDATE` | UPDATE 必须映射到具体语义 |

产品级 `CREATE/UPDATE/CONFLICT/NO_CHANGE` 映射到内部操作：

```text
CREATE    → CREATE
UPDATE    → SUPPORT | WEAKEN | REVALIDATE | REGROUND |
            SUPERSEDE | CONTEXTUALIZE
CONFLICT  → CONTRADICT，默认保持 ClaimHead 并维护 OpenIssue
NO_CHANGE → NO_CHANGE
```

`SPLIT` 在 Lean Runtime 中必须 fail closed。

## Authority 与 Scope

保留：

```text
INFORMATIONAL
ACTION_SAFE
USER_CONFIRMED
```

不要把它们当作简单总序：

- `USER_CONFIRMED` 不自动满足 `ACTION_SAFE`；
- action-safe 路径必须显式匹配 `ACTION_SAFE`；
- 同时要求用户确认时，还必须存在 live `USER_CONFIRMATION` Evidence；
- confidence 不能提升 authority。

Scope 和时间分开保存：

```text
scope_predicate = project/domain/mode/exclusions
valid_time       = ClaimVersion 的有效时间
system_time      = 数据库记录的版本时间
```

兼容 payload 中重复的 `valid_time` 必须规范化；两处不一致时返回 `SCOPE_TIME_CONFLICT`。

## 数据与 Schema 约束

Lean 在线正确性至少需要：

```text
content_blob
evidence_record
claim
claim_version
claim_head
version_transition
grounding_relation
grounding_block
effective_claim_state
open_issue
operation_proposal
steward_decision
outbox_event
index_watermark
search_document
search_embedding
retrieval_trace
operational_event
optional TTL context_capsule
```

不要为了“更 Lean”删除 `GroundingBlock`、`OutboxEvent` 或 `IndexWatermark`；删除正确性和异步投影依赖它们。

Schema 变更必须同时提供：

- Alembic Migration 或当前项目采用的等价迁移；
- upgrade、downgrade，或明确的不可逆理由；
- 数据回填和兼容策略；
- 真实 PostgreSQL 集成测试；
- 权限、并发、幂等和回滚测试；
- 对应实施合同或 ADR 更新。

所有 tenant-owned row 必须包含 `tenant_id`。幂等写必须保存 key 与 request fingerprint：同 key 同 payload 返回原结果，同 key 不同 payload 返回 `IDEMPOTENCY_CONFLICT`。

## 事务规则

保持六个事务族：

| 事务 | 约束 |
| --- | --- |
| TX-01 Evidence Ingest | 独立 Evidence、幂等、事件与 Outbox 原子提交 |
| TX-02 Claim Create | absence-CAS 创建 Claim、V1、Head |
| TX-03 Claim Revision | exact-head CAS 创建不可变 Vn+1 |
| TX-04 No Change | 不创建版本、不移动 Head；可以维护 OpenIssue |
| TX-05 Evidence Revoke | 同步 revoke、GroundingBlock、Context 失效和 purge Outbox |
| TX-06 Grounding Restore | 新 Evidence、新版本和治理决定后才解除阻断 |

Canonical transaction 中禁止调用 LLM、embedding、向量库或外部 memory engine。Canonical mutation 与 Outbox 必须原子提交。

关键事务应优先使用显式 SQL 或受控 procedure；不要依赖 ORM 隐式 flush 顺序表达 CAS、安全或 append-only 语义。

## OpenIssue 规则

至少支持：

```text
CONFLICT
MISSING_EVIDENCE
SCOPE_UNCERTAIN
AUTHORITY_UNCERTAIN
DEPENDENCY_INVALIDATED
```

状态：

```text
OPEN
WAITING_EVIDENCE
WAITING_USER
READY_FOR_REVIEW
RESOLVED
DISMISSED
```

每次状态变化必须：

- 使用 `expected_issue_revision` CAS；
- 保存 proposal、actor、policy、Evidence 和 decision；
- 与相关 Claim transaction 原子提交；
- 产生 append-only transition 或等价 canonical event；
- 重试不重复迁移。

Discharge 必须显式检查 issue ID、target、正反 branches、Evidence admissibility、Scope、authority 和 discharge rule。Resolution Evidence 被撤销时，原 issue ID 应重新进入开放状态，不得静默保留已解决结论。

## Retrieval 与 Context

L0 当前状态查询不得依赖向量索引。L1 必须按以下顺序：

```text
metadata/time/scope filter
→ FTS + pgvector
→ normalize and deduplicate
→ resolve canonical ID/version
→ Canonical Gate
→ Evidence Bundle
```

Canonical Gate 必须检查 tenant、subject、permission、retention、revocation、requested version、GroundingBlock、Scope、valid time、OpenIssue、authority 和 Evidence lineage。

ContextCapsule 固定分区：

```text
ACTIVE GOAL
ACTIVE STATE
OPEN ISSUES
CONSTRAINTS
RETRIEVED EVIDENCE
TRACE POINTERS
```

Goal、硬约束、当前 ECS 和 live OpenIssue 是 protected items。Pointer 必须校验 ID、hash、权限和 retention。预算不足时返回明确错误或 abstention，不能通过丢失 OpenIssue 获得表面成功。

## 删除、权限和本地安全

Lean V1 默认：

```text
single local user
single configured tenant
API binds to loopback
PostgreSQL not publicly exposed
Nginx/FRP public route disabled
```

即使单 tenant，也必须保留 `tenant_id`、基础 RLS、真实 login role 测试和连接池 tenant/actor context reset。复杂家庭权限推迟，不代表取消基础隔离。

至少分离：

```text
migration owner
API runtime
Steward procedure executor
projection worker
Audit runner
```

应用不能使用 migration owner。Steward 只能 execute procedure，不能直接 DML canonical tables。Worker 只能写自己的 projection、delivery metadata 和 watermark。

启用公网、FRP、家庭账号或远程设备即超出默认 Lean 范围；必须先完成 TLS、认证、session/device revocation、CSRF/CORS/cookie、rate limit、secret rotation 和安全日志门禁。

不要在代码、Prompt、日志、fixture 或提交中写入真实密码、token、用户私密正文或未脱敏生产数据。

## Outbox 与后台任务

Worker 必须保证：

- 使用 `outbox_id` 或确定性 downstream key 幂等；
- 同 aggregate 保序；
- durable projection 后才推进 watermark；
- dead-letter gap 未修复前不得越过；
- crash、lease timeout 和重复投递可恢复；
- 删除和权限失效任务优先于普通 embedding 补建；
- embedding 模型或维度变化创建新的 projection version。

V1 不引入 Kafka、通用 Projection Registry 或多个在线 memory database，除非实际负载和 ADR 证明必要。

## OSPC 研究边界

Open-State-Preserving Compression 仅在隔离 Audit 环境运行，状态始终是：

```text
RQ pending
novelty unvalidated
not a product dependency
```

实验必须：

- 使用 immutable Episode/Evidence snapshot；
- 使用相同 tokenizer、下游模型、固定 prompt、初始检索权限和总预算；
- 将 initial context、recovered tokens 和方法元数据都计入主 token budget；
- 记录 recovery calls、latency、fallback、模型调用和计算成本；
- 先计算 `B_min`；预算不足时报告 `INFEASIBLE_UNDER_BUDGET`，不得伪造零 false closure；
- 使用独立 scorer 或冻结 label，不允许被测方法自评；
- 实现强 typed-state/structured-eviction baseline 和完整消融；
- 固定外部 baseline 的 commit、依赖、许可证快照和配置。

如果简单保留 OpenIssue 字段或强 baseline 达到同样效果，应停止 novelty 主张。研究失败不得阻止 Lean Product Core 发布。

## 推荐代码布局

当创建 Runtime 时，默认放在 `runtime/`：

```text
runtime/
├─ pyproject.toml
├─ compose.yaml
├─ migrations/
├─ src/milai/
│  ├─ api/
│  ├─ domain/
│  ├─ application/
│  ├─ persistence/
│  ├─ adapters/
│  ├─ workers/
│  ├─ observability/
│  └─ config/
├─ tests/
│  ├─ unit/
│  ├─ contract/
│  ├─ integration/
│  ├─ concurrency/
│  ├─ failure/
│  ├─ security/
│  └─ e2e/
└─ evals/
```

保持模块化单体。只有出现独立扩缩容、隔离或故障域需求并有 ADR 时才拆微服务。

## 编码与变更纪律

- 保留用户已有修改；不要清理无关文件或做顺手重构。
- 先阅读相邻 domain model、Migration、procedure 和测试，再修改行为。
- 用 typed boundary model 校验 API、QueryPlan、OperationProposal 和压缩输出。
- 核心 domain 逻辑优先保持确定性；模型调用放在显式 adapter/application 边界。
- 新依赖必须有具体必要性、版本锁定、许可证检查和替代/移除方案。
- 不要把实验 adapter 直接耦合进 canonical transaction。
- 修改公开 API、Schema、operation enum 或错误码时，更新 Migration、测试、示例和合同。
- 不要把性能猜测写成 SLA；先在目标设备和 workload 上建立 baseline。
- 不要编辑 ZIP 作为源文件。只有用户明确要求发布新文档包时，才从当前 Markdown 重新生成 ZIP 并校验内容。

## 测试要求

开发期间运行最窄的相关测试，交付前按风险扩大范围。关键路径不能只用 mock：

```text
真实 PostgreSQL 两连接 CAS 竞争
真实 login role/RLS 负向测试
idempotency replay and fingerprint conflict
append-only/immutability
transaction rollback and Outbox atomicity
dead-letter watermark gap
revoke with stale index
Context recursive OpenIssue preservation
canonical unavailable abstention
end-to-end conflict → resolution → revoke → reopen
```

若 `runtime/` 尚不存在，不要运行或声称 Python、数据库或 API 测试通过。文档改动至少检查：

```bash
rg -n '^#{1,6} ' ./*.md
rg -n 'claim_evidence_edge|commit_decision' ./*.md
```

第二条命令用于发现旧术语，不代表旧历史文档必须被机械改写。检查上下文后再决定是否需要修订。

Runtime 创建后，以 `pyproject.toml`、锁文件和 CI 中的真实命令为准；不要继续复制尚未落地的“目标命令”。

## 完成与交付说明

每次交付应明确：

1. 修改了什么，以及对应哪个 Lean 合同条款；
2. 是否改变 Schema、API、权限、删除或 canonical 行为；
3. 运行了哪些测试及结果；
4. 哪些相关测试未运行及原因；
5. Migration、回滚和数据兼容方式；
6. 尚未解决的风险或 open decision；
7. 是否仍保持 `NO-GO FOR SCHEMA FREEZE`。

不要把“代码已写”“测试部分通过”“外部服务可启动”表述成 Production ready。只有架构
bundle/crosswalk/validator、AF-00～AF-09、Lean 发布门禁和真实失败测试全部通过后，才能升级
对应状态或发布 `1.0.0 FROZEN`。
