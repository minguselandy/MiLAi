---
document_id: MILA-ML-CLOSURE
version: "0.1"
status: DESIGN_COMPLETE_AWAITING_ACTIVATION
document_type: PROGRAM_COMPLETION_GOAL
architecture_baseline: MILA-ML-ARCH@1.0
current_execution_master: MILA-ML-MASTER@1.6
normative_scope: remaining_phase1_memory_lifecycle_tasks
execution_authority: NONE
supersedes_before_activation: NONE
supersedes_on_activation:
  - MILA-MD03@0.1 execution navigation
formal_holdout_authorized: false
product_default_enable_authorized: false
---

# MiLAi Memory Lifecycle 全任务闭环 Goal

> 本文为 Phase 1 文本个人记忆生命周期的统一完成合同。它在激活前不替代 `MILA-ML-MASTER@1.6`，不授权代码、数据、模型、数据库、formal holdout 或产品开关操作。

---

# 1. 总目标

完成以下可重放闭环，并对每个候选能力作出明确采用或不采用决定：

```text
Raw Evidence
  → query-independent Memory Formation
  → governed Memory Evolution
  → rebuildable Raw / Formed / Canonical projections
  → requirement-aware Recollection
  → typed Binding / Sufficiency / Operator
  → minimal Context / Reader
  → correction / revocation / rollback / rebuild
```

完成不等于实现所有复杂功能。每项任务最终必须落入：

```text
PASS
NOT_NEEDED_BY_EVIDENCE
PARKED_WITH_CAUSAL_ROUTE
FAIL_SAFETY
```

不得保留无归因的 `TODO`，也不得为补齐路线而强制建设 consolidation、adaptive retrieval、graph memory 或 durable Formation store。

---

# 2. Phase 1 范围

## 2.1 In Scope

```text
user-assistant textual Evidence
personal facts and preferences
events and occurrence time
current / historical state
correction, update, temporary constraint and revocation
entity and event identity
Raw-preserving semantic representation
Governed Canonical evolution
simple and conditionally adaptive recollection
typed operator and Reader handoff
derived-artifact freshness and revocation
local single-user / single-tenant candidate integration
```

## 2.2 Out of Scope

```text
multimodal memory
procedural skill learning
agent trajectory gotcha learning
multi-agent or family governance
automatic Pattern/Profile promotion
LoRA personalization
Graphiti/Zep/Hindsight/OpenViking production backend
unbounded ReAct/refinding
training a new retrieval, planner or Reader model
```

这些范围可在后续 Program 中重新评估，但不属于本 Goal 的“全部任务”。

---

# 3. 规范与激活规则

规范优先级保持：

```text
architecture/v1.0 frozen bundle
→ MiLAi Logical Architecture v1
→ MiLAi Lean V1 实施合同
→ MILA-ML-ARCH@1.0
→ MILA-ML-MASTER@1.6
→ 本 Goal（激活后仅控制剩余执行顺序）
```

激活本 Goal 必须显式完成：

1. 用户明确授权执行 `MILA-ML-CLOSURE@0.1`。
2. 将 `MILA-ML-MASTER` 升级到新的 execution version，并只增加本 Goal 的入口和状态。
3. 创建唯一 Program run-lock，绑定代码、数据、模型、Reader、数据库 migration、feature flags 和 formal-holdout 状态。
4. MD-03 不再另建重复 run；其 H1/H2 合同直接并入 Block C1。

激活前：

```text
execution_authority = NONE
current active navigation = MILA-ML-MASTER@1.6
```

---

# 4. 当前机器事实与剩余缺口

| Plane / Program | 已完成 | 剩余必须解决 |
| --- | --- | --- |
| Evidence | Raw ingest、scope、retention、revocation、lineage 基础存在 | 若采用持久 Formed projection，验证 derived revocation/freshness 传播 |
| Formation / Episode | MD-01、MF-02 PASS；MD-02 shadow H2 PASS | V02 boundary 被拒绝；identity/time/state-change 仍缺大样本泛化 |
| Formation / Identity-Time | MF-03 小样本 PASS：24 events、2 occurrence times | 新独立数据上的 alias、same/distinct event、relative/ambiguous time |
| Formation / State-Change | MF-04 小样本 PASS：6 assertions、3 transitions | 多谓词、修正、撤回、短期约束泛化 |
| Evolution | EV-01 小型真实 PostgreSQL replay PASS | 扩大后的 operation/disposition、conflict/revoke/re-ground/rollback |
| Recollection | DG-28 + Formed 已在 7 个义务上 7/7；Wrong COMPLETE 0 | 更大 matched set 上的有效绑定和完整性 |
| Adaptive | DG-29 未进入 | 只有新数据出现 residual opportunity 才决定是否进入 |
| Consolidation | 未执行 | 先做 opportunity audit；无机会则 `NOT_NEEDED` |
| Reader | 历史存在 semantic non-monotonicity / correct-case regression | operator-ready 后单独修复 consumption，不回调 retrieval |
| Product integration | MD-02 observation-only shadow 安全；DG-30 `release_ready=false` | selected method 的 product-faithful canary、rollback 和最终 release decision |
| Formal validation | 未使用 | 仅在所有 non-holdout 门通过且另获授权后运行一次 |

---

# 5. 最终方法候选

所有产品候选保留 Canonical Core 和 Raw fallback，只从下列三种最小路径中选择一条：

## Candidate R — Raw + Canonical Simple

```text
Canonical exact/current
+ Raw official acquisition
+ deterministic Binding/Sufficiency
```

当 Formation 没有独立泛化收益时采用。它仍是完整、安全的 memory lifecycle，不因为不使用 Formed projection 而失败。

## Candidate F — Formed + Raw + Canonical Simple

```text
Candidate R
+ query-independent Formed projection
+ one-pass deterministic formed consumption
```

只有 `MLC-H1` 通过时采用。

## Candidate A — Formed + Raw + Canonical Adaptive

```text
Candidate F
+ fresh observation 后最多一个 admissible extra action
```

只有 Formed+Simple 后仍有机器证明的 residual opportunity，且 `MLC-H2` 通过时采用。

以下永不成为产品候选：

```text
Formed-only
free model action generation
model-declared COMPLETE
eval-owned retrieval
unbounded search
```

---

# 6. 两项 Program Hypotheses

## MLC-H1 — Raw-Preserving Formation Utility

问题：经过直接 fidelity 验证的 Formed representation，是否在相同 Simple Recollection 预算下改善有效绑定？

必须同时满足：

```text
MD03 direct Formation gates pass
ΔF = ValidBindingRecall(F) - ValidBindingRecall(R) ≥ 0.05
net additional valid obligations ≥ 2
paired conversation bootstrap 95% CI lower > 0
AcceptedBindingPrecision = 1.0
Wrong COMPLETE = 0
CorrectCaseRegression = 0
Authority/Scope violation = 0
same official actions, hydration and Reader evidence ceilings
```

如果直接 Formation fidelity 通过、但下游 `ΔF` 不通过，则 Formation 可保留为研究 sidecar，不进入产品候选。

## MLC-H2 — Adaptive Residual Utility

问题：在 Candidate F 后仍存在的预注册 residual 是否需要一次 observation-conditioned action？

进入条件：

```text
Candidate F has unresolved requirements
fresh observation provides a new cue or anchor
an unexecuted feasible official action exists
official oracle shows recoverable valid Evidence
```

效果门：

```text
ΔA|Formed ≥ 0.05 ValidBindingRecall
net additional valid obligations ≥ 1
paired 95% CI lower > 0
IncrementalCostPerAdditionalValidBinding within run-lock ceiling
Wrong COMPLETE / regression / authority violation = 0
```

无 opportunity 时：

```text
MLC-H2 = NOT_APPLICABLE
selected method remains Candidate F or R
```

---

# 7. 统一数据与评测合同

只创建一套新的 Phase 1 lifecycle 数据，避免每个 Goal 重复标注。

## 7.1 数据分区

```text
Lifecycle repair-dev:
  ≥ 16 conversations
  允许读取 labels，用于通用修复

Lifecycle sealed-validation:
  ≥ 48 new conversations
  ≥ 192 turns
  ≥ 60 query-requirement groups
  scorer 与 treatment 前一次封存

Formal holdout:
  separate
  untouched until C4 explicit authorization
```

旧 MF-01、MD-01、MF-02、MD-02 和 7-case read-path 数据只作历史 regression，不进入主效应分母。

## 7.2 最小 query strata

| Stratum | 最小 query 数 |
| --- | ---: |
| current state / exact lookup | 10 |
| update / correction / conflict / revoke | 10 |
| entity identity / multi-session composition | 10 |
| event-time / temporal order / count | 10 |
| preference / intent / temporary constraint | 10 |
| abstention / missing / hard negative | 10 |

## 7.3 Formation 与 Evolution labels

至少覆盖：

```text
Entity mentions ≥ 40
identity positive pairs ≥ 20
identity hard negatives ≥ 20
Event mentions ≥ 40
same-event pairs ≥ 16
distinct-event pairs ≥ 16
Occurrence-time labels ≥ 30
  explicit ≥ 8
  relative/cross-Evidence ≥ 8
  interval/durative ≥ 6
  ambiguous/unresolved ≥ 6
State assertions ≥ 30
State transitions ≥ 24
each current transition enum ≥ 3
lifecycle replay sequences ≥ 16
```

标注单位同时包括：

```text
Evidence role/equivalence group
proof obligation
expected Binding
expected operator readiness
expected current/historical state
expected OperationProposal operation
expected review/OpenIssue disposition
```

## 7.4 Label isolation

```text
Raw inputs and split frozen before treatment
sealed labels unavailable to builder/model/Reader developers
baseline and treatment outputs generated before label opening
one final sealed score
no sealed retuning
```

---

# 8. 五个执行 Block

## C0 — Common Baseline and Run Lock

目标：一次冻结所有后续 Block 共用的身份、数据、预算和 scorer。

任务：

```text
CL-001 freeze lifecycle repair-dev and sealed-validation
CL-002 validate label coverage and hand-score fixtures
CL-003 freeze Raw/Canonical snapshot and access/revocation state
CL-004 freeze Reader/model/tokenizer/template identities
CL-005 freeze action/hydration/token/model-call/timeout ceilings
CL-006 reproduce current Candidate R baseline
```

完成门：

```text
all label strata adequate
formal holdout untouched
baseline reproducible
product and eval acquisition implementations identical
```

## C1 — Formation and Evolution Generalization

此 Block 吸收 MD-03，不另跑重复实验。

### C1.1 Formation baseline and repair

```text
CL-101 run V01 label-blind outputs
CL-102 score repair-dev first loss
CL-103 if needed, implement one general V02 treatment
CL-104 allow at most 3 repair-dev iterations per root cause
CL-105 run one sealed matched Formation effect
```

直接门沿用 MD-03：

```text
SemanticFormationMacroF1 ≥ 0.85
minimum component F1 ≥ 0.75
RawSpanGroundingExactness = 1.0
SourceEventTimeSeparationAccuracy = 1.0
AmbiguousTimePreservation = 1.0
AssistantContamination = 0
UnsupportedIdentityMerge = 0
DistinctEventCollapse = 0
QueryDependentFormationInput = 0
```

MD-02 V02 boundary 继续禁止。Identity/time/state-change 可直接消费 Raw spans；新的 boundary treatment 只有在新 repair-dev 明确定位 episode first loss 时才允许另立 V03。

### C1.2 Governed Evolution replay

```text
CL-111 map accepted state/change artifacts to OperationProposal
CL-112 replay CREATE/SUPPORT/SUPERSEDE/CONTEXTUALIZE/WEAKEN/REGROUND
CL-113 replay conflict/OpenIssue preservation
CL-114 verify valid-time and current/historical reads
CL-115 revoke support → block/reopen → fresh re-ground
CL-116 verify rollback/replay equivalence
```

硬门：

```text
ExpectedOperationAccuracy = 1.0
ExpectedReviewDispositionAccuracy = 1.0
UnsupportedCanonicalPromotion = 0
WrongTransitionDisposition = 0
MissingProvenanceClosure = 0
ValidTimeMisassignment = 0
RevocationSupportLeak = 0
RollbackReplayMismatch = 0
CrossScopeIdentityLink = 0
```

真实 Canonical mutation 只允许发生在新建临时 PostgreSQL 数据库，并在 Block 结束后清理。

## C2 — Consolidation Opportunity and Representation × Recollection

### C2.1 MF-05 opportunity

```text
CL-201 identify requirements needing cross-episode aggregation
CL-202 verify raw/member Evidence already exists
CL-203 verify simple formed units cannot discharge them
CL-204 run oracle support-closed view
```

若无 oracle opportunity：

```text
MF-05 = NOT_NEEDED_BY_EVIDENCE
no consolidation code
```

若有机会，只实现 repair-dev 上覆盖最大的一个 view family：

```text
USER_PROFILE
ACTIVE_GOAL
DURATIVE_STATE
EPISODE_SCENE
```

view 必须保存 support set、valid time、contested alternatives 和 invalidation rule；不能自动成为 Claim。

### C2.2 MF-06 method selection

必须运行：

| Arm | Representation | Recollection | 产品资格 |
| --- | --- | --- | --- |
| R | Raw + Canonical | Simple | 是 |
| F | Formed + Raw + Canonical | Simple | H1 通过才有 |
| E | Formed only | Simple | 否，仅测信息损失 |

条件式运行：

| Arm | Entry |
| --- | --- |
| AR | Candidate R 存在 residual oracle opportunity |
| AF | Candidate F 存在 residual oracle opportunity |

```text
CL-211 run R/F/E with identical ceilings
CL-212 calculate ΔF and information-loss risk
CL-213 run adaptive oracle opportunity audit
CL-214 only if applicable, run AR/AF once
CL-215 select exactly one minimal product candidate
```

选择规则：

```text
H1 miss → select R
H1 pass, H2 not applicable/miss → select F
H1 pass, H2 pass → select A
```

不允许因算法更复杂而优先选择 A。

## C3 — Product-Faithful Lifecycle Integration

### C3.1 Projection topology decision

如果选择 R：

```text
CL-301 durable Formed projection = NOT_NEEDED_BY_EVIDENCE
```

如果选择 F/A：

```text
CL-302 submit architecture-vNext ADR for formed projection identity
CL-303 implement experimental projection only after ADR approval
CL-304 bind source watermark, build epoch and access snapshot
CL-305 implement idempotent rebuild and dead-letter visibility
CL-306 propagate revoke/retention/scope change to read block and purge
```

不得原地修改 `architecture/v1.0`。ADR 未批准时，Formed 只能保持 internal default-OFF sidecar，不能默认产品启用。

### C3.2 Official product path

```text
CL-311 integrate selected method behind one internal feature flag
CL-312 preserve flag-OFF byte/behavior identity
CL-313 observation-only shadow replay
CL-314 candidate canary with Raw fallback
CL-315 full Gate → Binding → State → Sufficiency recomputation
CL-316 exact rollback to Candidate R
```

正式路径必须经过：

```text
OpenWorker → MCP → milai-runtime
```

`evals/` 只能构造 case、触发 flag 和评分，不能实现 retrieval、Binding、Evolution 或 Reader 业务行为。

### C3.3 Reader and Context closure

只有 EvidenceSet、Binding、OperatorResult 已正确时才修 Reader：

```text
CL-321 freeze correct semantic result and minimal proof context
CL-322 compare baseline Reader with selected candidate
CL-323 localize context packing vs semantic consumption
CL-324 repair general Reader boundary, max 3 repair-dev iterations
CL-325 one sealed Reader effect
```

Reader 不能修改：

```text
RequirementState
AcceptedBinding
COMPLETE
OperatorResult
Canonical State
```

对 typed lookup/count/compare/operator query，优先使用 deterministic structured rendering；Reader 只负责表达，不重新推理已经完成的操作。

C3 完成门：

```text
AcceptedBindingPrecision = 1.0
Wrong COMPLETE = 0
CorrectCaseRegression = 0
OperatorResultAccuracy = 1.0
ReaderGroundingViolation = 0
DerivedArtifactRevocationLeak = 0
RevokedEvidenceRetrievalLeak = 0
StaleProjectionRead = 0
RawFallbackSuccessRate = 1.0
flag-OFF identity = 1.0
ImplementationRollback = PASS
```

## C4 — Final Validation and Release Decision

### C4.1 Non-holdout lifecycle validation

```text
CL-401 run one full non-holdout lifecycle E2E validation
CL-402 close write-time, build-time and query-time cost/latency accounting
```

对选择出的唯一方法运行：

```text
Evidence ingest
→ async/synchronous Formation as selected
→ governed create/update/conflict/revoke/re-ground
→ projection freshness and rebuild
→ current/historical/multi-session/temporal query
→ Binding/Sufficiency/Operator
→ Context/Reader
→ correction and deletion replay
```

必须报告：

```text
direct Formation fidelity
CanonicalCurrentStateAccuracy
ValidBindingRecall / Precision
OperatorReadyRate
TemporalCompletenessRate
FinalAnswerCorrectness
Wrong COMPLETE / regression / authority violations
write-time and query-time cost separately
```

### C4.2 Formal holdout

```text
CL-410 only after separate authorization, run the frozen formal holdout once
```

只有下列条件全部成立并获得新的显式授权才进入：

```text
C0–C3 terminal
selected method frozen
all non-holdout safety gates pass
no open correctness repair
model/Reader/config identities frozen
one-way result protocol ready
```

Formal holdout：

```text
one execution
no retuning
no replacement seed/model/prompt
no hidden retry
```

若未获授权，C4 可以终结为 non-holdout candidate，必须明确 `formal_validation = NOT_RUN`。

### C4.3 Release decision

```text
CL-420 classify every lifecycle task and emit the deterministic Program terminal
CL-421 emit exactly one release decision for the selected method
```

最终只产生一个选择：

```text
KEEP_FLAG_OFF
SHADOW_ONLY
CANDIDATE_ENABLEMENT_READY
REJECT_CANDIDATE
```

本 Goal 不自动执行 `DEFAULT_ON`，也不使用 `PRODUCTION_READY` 表述。

---

# 9. 依赖、并行和恢复

## 9.1 Critical Path

```text
C0
→ C1 Formation/Evolution
→ C2 method selection
→ C3 product integration/Reader
→ C4 final validation
```

## 9.2 可并行工作

C0 完成后可以并行：

```text
C1 data-independent code/harness preparation
C3 flag-OFF integration harness
Reader baseline replay
PostgreSQL lifecycle fixture preparation
```

但 effect 与产品 candidate admission 仍按 Critical Path。

## 9.3 Checkpoint Resume

每个 Block 保存成功调用和数据身份。恢复时：

```text
reuse completed deterministic outputs
reuse successful model outputs bound to exact input identity
do not repeat Provider/Reader calls merely because aggregation failed
rerun only corrupted or not-yet-produced unit
```

并发和恢复不能增加逻辑尝试、样本权重或 hidden retry。

---

# 10. 开发失败与修复规则

## 10.1 Repair Iteration

以下情况不是立即 terminal：

```text
schema/offset/timezone validation rejected fail-closed
adapter/transport failure without state escape
runner aggregation bug
temporary PostgreSQL setup failure
artifact writer/validator implementation bug
```

处理：

```text
record root cause
fix general implementation
run touched tests
resume same logical run
```

## 10.2 Semantic Repair

每个通用 first loss 最多 3 次 repair-dev 迭代：

```text
diagnose
→ one general mechanism change
→ repair-dev score
→ retain or revert treatment
```

三次仍无改善时：

```text
route to alternate architecture or select simpler candidate
do not terminate unrelated lifecycle blocks
```

## 10.3 Immediate Safety Failure

只有以下情况立即停止有风险的 lane：

```text
Raw Evidence unauthorized loss
cross-tenant/scope exposure
revoked Evidence remains authority-bearing
model/sidecar direct Canonical mutation
Wrong COMPLETE reaches product output
production database unintended mutation
formal holdout leakage
```

停止该 lane 后仍必须完成根因、回滚和替代路径判断；不能只写“失败后终止”。

---

# 11. 统一指标

## 11.1 Formation

```text
SemanticFormationMacroF1
EpisodeBoundaryF1
IdentityPairwiseF1
EventIdentityPairwiseF1
OccurrenceTimeF1
StateAssertionF1
TransitionRelationMacroF1
RawSpanGroundingExactness
AmbiguousTimePreservation
AssistantContamination
```

## 11.2 Evolution

```text
ExpectedOperationAccuracy
ExpectedReviewDispositionAccuracy
CanonicalCurrentStateAccuracy
ValidTimeAccuracy
VersionTransitionAccuracy
Conflict/OpenIssuePreservation
RevocationSupportLeak
RollbackReplayEquivalence
```

## 11.3 Recollection / Reader

```text
ValidBindingRecall                    primary
AcceptedBindingPrecision
RequiredEvidenceCoverage
OperatorReadyRate
TemporalCompletenessRate
FinalAnswerCorrectness
CorrectCaseRegression
Wrong COMPLETE
ReaderGroundingViolation
```

## 11.4 Lifecycle / Operations

```text
DerivedArtifactRevocationLeak
RevokedEvidenceRetrievalLeak
StaleProjectionRead
RawFallbackSuccessRate
ProjectionBuildLagP50/P95
RevocationPropagationLagP50/P95
RebuildSuccessRate
ImplementationRollback
```

## 11.5 Cost

写时和读时分开：

```text
FormationCostPerEvidence
StorageAmplification
RebuildCost
ModelCalls / Tokens
OfficialAcquisitionCalls
HydratedEvidenceUnits
ReaderTokens
QueryLatencyP50/P95
QueryCostPerUsefulBinding
```

MF-06 摊销同时报告 `H=1,10,100`，不能用单一任意读取次数隐藏 Formation 成本。

---

# 12. 资源与效率合同

```text
CPU-first for deterministic Formation, scoring and bootstrap
conversation/query-level parallelism
local vLLM only for repair-dev-proven semantic residual
no model training
no remote Provider by default
Reader and extraction service windows separated
one PostgreSQL ephemeral database per integration lane
```

run-lock 根据执行时资源 probe 冻结：

```text
worker ceiling
GPU assignment
batch size
model/token ceilings
timeouts
```

不为“利用 GPU”增加模型路径；GPU 只缩短已获准的必要推理。

---

# 13. 轻量质量门与制品

## 13.1 Quality Gates

```text
每次修改：touched unit/contract + edited-file Ruff/mypy
Block effect 前：相关 component regression
PostgreSQL/permission/schema 变更：对应 integration/security tests
最终 candidate：一次全量 Runtime + contract + PostgreSQL + E2E
```

不在每个 repair iteration 重跑全量系统。

## 13.2 Artifact Policy

Program 只保留：

```text
program-run-lock.json
block-{c0..c4}-results.json
block-{c0..c4}-terminal.json
repair-log.jsonl
selected-method.json
lifecycle-terminal.json
release-decision.json
```

不生成逐阶段 receipts、transitive manifests、deliverable index、重复 runbook 或多轮 reviewer artifacts。

失败 Evidence append-only 保留，但不复制完整私密正文。

---

# 14. Definition of Done by Plane

## Evidence Plane

- Raw Evidence 可回放，合法 retention/revocation 正确传播。
- 无 unauthorized loss、permission leak 或 stale authority。

## Formation Plane

- 新 sealed set 上 direct fidelity 已评分。
- Formation 被明确选择为产品候选或明确拒绝。
- Raw fallback 永久保留。

## Canonical Evolution Plane

- create/update/correct/conflict/revoke/re-ground/current/historical/rollback 全部可重放。
- 仍只有一个 governed Canonical 写路径。

## Recollection Plane

- R/F/A 中恰好一个被选择。
- AcceptedBindingPrecision、Wrong COMPLETE 和 correct-case regression 满足门禁。
- 不需要的 adaptive/consolidation 明确记录为 `NOT_NEEDED_BY_EVIDENCE`。

## Context / Action Plane

- OperatorResult 正确后，Reader 不改变完成状态或 Canonical State。
- selected method 的最小 proof context、答案和 trace 可重放。

## Operations

- flag OFF 有行为等价基线。
- candidate 可一键回滚到 Candidate R。
- 所有临时数据库和资源清理完成。
- release decision 和 formal-validation 状态明确。

## Program Closure

所有 `CL-*` 任务必须有：

```text
PASS
NOT_NEEDED_BY_EVIDENCE
PARKED_WITH_CAUSAL_ROUTE
FAIL_SAFETY
```

不得存在未分类任务。

---

# 15. Program Terminal

```text
if authority, scope, Evidence preservation,
   production Canonical safety, or holdout integrity fails:
  FAIL_ML_CLOSURE_AUTHORITY_OR_DATA_SAFETY

elif all applicable Blocks complete and Candidate R selected:
  PASS_ML_CLOSURE_RAW_CANONICAL_CANDIDATE

elif all applicable Blocks complete and Candidate F selected:
  PASS_ML_CLOSURE_FORMED_SIMPLE_CANDIDATE

elif all applicable Blocks complete and Candidate A selected:
  PASS_ML_CLOSURE_FORMED_ADAPTIVE_CANDIDATE

elif lifecycle through Operator is correct but Reader remains unresolved:
  PARTIAL_ML_CLOSURE_READER_UNRESOLVED

elif labels or external authorization prevent required evaluation:
  PARKED_ML_CLOSURE_INSUFFICIENT_EVIDENCE_OR_AUTHORITY

elif no candidate clears correctness after valid treatments:
  PARKED_ML_CLOSURE_NO_SAFE_GENERALIZED_CANDIDATE
```

Terminal 必须另行记录：

```text
formal_validation = NOT_RUN | PASS | MISS
release_decision = KEEP_FLAG_OFF | SHADOW_ONLY |
                   CANDIDATE_ENABLEMENT_READY | REJECT_CANDIDATE
```

禁止写：

```text
PASS_COMPLETE_MEMORY_ARCHITECTURE
PRODUCTION_READY
FORMAL_HOLDOUT_PASS
```

---

# 16. 当前授权状态

```text
Goal design:                  COMPLETE
Program activation:           NOT AUTHORIZED
Data creation:                NOT AUTHORIZED
Code changes:                 NOT AUTHORIZED
Model/Reader calls:           NOT AUTHORIZED
PostgreSQL mutations:         NOT AUTHORIZED
Product feature enablement:   NOT AUTHORIZED
Formal holdout:               FORBIDDEN UNTIL SEPARATE AUTHORIZATION
```

本文件只完成“所有剩余任务如何被完成或关闭”的设计，不声称任何新任务已经执行。
