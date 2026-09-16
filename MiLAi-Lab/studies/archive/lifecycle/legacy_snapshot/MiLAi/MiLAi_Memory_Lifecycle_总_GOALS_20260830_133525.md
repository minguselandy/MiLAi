---
document_id: MILA-ML-MASTER
version: "1.1"
status: ACTIVE_EXECUTION_MASTER
normative_scope: execution_order_and_program_gates
architecture_baseline: MILA-ML-ARCH@1.0
supersedes_execution_clauses:
  - DG-26-30-MASTER@1.0
---

# MiLAi Memory Lifecycle 总 Goal

> 日期：2026-08-30（Asia/Shanghai）  
> 冻结上位规范：`architecture/v1.0` / MiLAi Logical Architecture 1.0.0  
> 项目架构：[MILA-ML-ARCH@1.0](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)  
> ExperimentalFeatureFlagsDefault：`OFF`  
> Formal holdout：未授权、不得使用

---

# 1. 唯一规范链与总目标

本文件是当前唯一的执行顺序、Program gate 和 terminal decision 来源。

~~~text
architecture/v1.0 + frozen Logical Architecture
  ↓
MiLA Lean V1 implementation contracts
  ↓
MILA-ML-ARCH@1.0                  stable Program / Plane baseline
  ↓
MILA-ML-MASTER@1.1                execution order / gates / terminal
  ↓
Program and local Goal contracts
  ↓
historical DG method documents
~~~

旧 `DG-26-30-MASTER@1.0` 只保留历史事实与 Program C 局部设计来源，不再控制项目级顺序、DG-28 是否包含模型、DG-30 声明范围或 Formation/Evolution entry gate。

总目标是在保留 Raw Evidence 的前提下，验证一条可归因的文本个人记忆生命周期：

~~~text
Raw Evidence
  ├─ Raw projection ───────────────────┐
  ├─ Formation → Formed projection ────┼→ Recollection → Typed completion
  └─ governed proposal → Evolution → Canonical projection ─┘
~~~

核心原则：

> 不用复杂检索补偿尚未形成的记忆，也不用有损结构化替代原始 Evidence。

Phase 1 仅含 user-assistant 文本交互中的个人事实、偏好、事件、状态变化、修正和撤销。多模态、procedural skill、agent trajectory gotcha 与 workflow learning 不进入本轮研究假设；LongMemEval-V2 仅作后续扩展候选。

---

# 2. 当前机器事实

本节只引用 terminal / run-lock；`NOT_RECORDED_IN_TERMINAL` 不使用当前 HEAD 回填历史身份。

| Goal | Authority artifact | SHA-256 | Code identity | Data / snapshot identity | As-of |
| --- | --- | --- | --- | --- | --- |
| DG-24 | `var/dg24/s8/dg24-s8-terminal-20260829-003/receipt.json` | `fff0f5ce8ab7b230c49923308f37c080d1eab58776d298a075cda513790a6aa0` | `NOT_RECORDED_IN_TERMINAL` | scorer-registry snapshot `4a88cb030e67cce456b1dfe159fce177a5ace4b972f11af2a6674639c52dc876` | `NOT_RECORDED_IN_TERMINAL`（run-id date 2026-08-29） |
| DG-25 | `var/dg25/terminal/dg25-s10-terminal-20260830-001/receipt.json` | `d2b660499fee9e8a1db79603aaedc96c361099a9ab00a1b959069965d80bd2a0` | `NOT_RECORDED_IN_TERMINAL` | associated frozen input `7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412` | `NOT_RECORDED_IN_TERMINAL`（run-id date 2026-08-30） |
| DG-26 | `var/dg26/terminal.json` | `72a98dda4a7bf202fa12ac8c18c1322e33e6f47c05e914db00992fc0596c6282` | run-lock commit `651099ba8cffc2675961bb9250ba44c158efccb5` | frozen input `7c1c3a61cc81ddf523e8355a02ac2ba9ed4f517fc09cf9609cc7aeaa062fa412` | `2026-08-30T03:00:45.447408+00:00` |
| DG-27 | `var/dg27/run-lock.json` | `8a56395401a546b769a8a7463adb8682d53b965b92dc663c0ff9ddf1a29f0d77` | `651099ba8cffc2675961bb9250ba44c158efccb5` / dirty | same frozen input | `2026-08-30T11:09:36.950949+08:00` |

DG-27 artifact 是历史 pre-execution lock，不是 effect result；执行前必须 fresh S0。

| Goal | 机器结论 | 本 Master 处置 |
| --- | --- | --- |
| DG-24 | 6 个 channel 未调用、1 个 cutoff、3 个无现有通道发现；2 个 temporal proof gap | Program C diagnosis 基线 |
| DG-25 | 候选机会存在，但 Binding precision 与 Wrong COMPLETE 不允许采用 | 不采用候选策略 |
| DG-26 | fixed-pool StateView 无独立增益且有回归 | 保持 terminal，不重开 |
| DG-27 | 无 effect result | fresh S0 后执行 |
| DG-28 | 未执行 | deterministic official channel union only |
| DG-29 | 未执行 | 默认 `NOT_ENTERED_PENDING_REFINDING_OPPORTUNITY` |
| DG-30 | 未执行 | 仅 Read Path integration |
| MF-01 | design Goal | 当前仅 S0～S1 |

---

# 3. 不可变边界与统一术语

1. Raw Evidence 在 retention/revocation 允许范围内保留；合法删除不计为丢失。
2. Formation 输出是 noncanonical、versioned、provenance-linked、rebuildable 的 `FormationArtifactCandidate`。
3. Canonical 变化只经 `OperationProposal → Validator/StewardDecision → ClaimVersion/OpenIssue`。
4. 模型、EvidenceCandidate、Context 和 Reader 不能直接改写 Hard State 或宣布 canonical truth / COMPLETE。
5. access、revocation、tenant/scope 与 Evidence lineage 不得为 recall 放宽。
6. Formed projection 过期或未覆盖最新 Evidence 时必须标记 `PARTIAL/STALE`，保留 Raw fallback，且不得承担 completeness proof。
7. 新 durable logical object 必须走 architecture-vNext ADR；本轮不修改 `architecture/v1.0`。

统一术语：

~~~text
ExperimentalFeatureFlagsDefault = OFF
EvidenceCandidate               query-time retrieval object
FormationArtifactCandidate      noncanonical derived object
OperationProposal               sole canonical write proposal

ImplementationRollback          restore executable feature baseline
ProjectionRebuildRollback       invalidate/rebuild derived projections
CanonicalStateRollback          governed semantic rollback/replay

Formation-time Semantic Derivation
Query-time Grounded Evidence Interpretation
~~~

`Candidate 默认 OFF`、无命名空间的 `C1/C2` 和研究 `Claim` 不再是规范术语。

---

# 4. 研究假设与效应合同

## ML-H1 — Formation Utility

问题：保留 Raw fallback 的 Formation 是否改善 Simple Recollection 下的有效绑定？

主指标固定为 `ValidBindingRecall`，分析单位固定为 `query × requirement × evidence-role/equivalence-group obligation`。

最小效应固定为：

~~~text
delta_F_min = 0.05 absolute ValidBindingRecall
AND at least 2 net additional valid obligations
~~~

MF-06 run-lock 必须在 effect label 揭示前固定：

~~~text
paired bootstrap procedure
confidence interval rule
correct-case set
~~~

未冻结这些参数，MF-06 不得运行。ML-H1 只在以下全部成立时通过：

1. 直接 Formation fidelity gate 通过。
2. `ΔF` 达到预注册 `delta_F_min`，且 paired 95% CI lower bound > 0。
3. AcceptedBindingPrecision、CurrentStateAccuracy 和适用安全指标不回归。
4. Wrong COMPLETE、scope/authority violation、correct-case regression = 0。
5. 增益不是由更多 hydration、evidence tokens、model calls 或 official actions 造成。

`RequiredEvidenceCoverage`、`ReconstructedCurrentStateAccuracy`、`OperatorReadyRate` 是预指定 secondary outcomes，不能在结果出现后替代主指标。

## ML-H2 — Adaptive Residual Utility

问题：Formation + Simple 后仍存在的预注册 residual，是否需要 observation-conditioned extra action？

ML-H2 只在以下全部成立时通过：

1. Formed + Simple 仍有预注册 unresolved requirements。
2. 在该 residual subset 上，`delta_A_min = 0.05` absolute ValidBindingRecall 且至少净增加 1 个 valid obligation；paired 95% CI lower bound > 0。
3. `IncrementalCostPerAdditionalValidBinding` 不高于 run-lock 预注册上限。
4. Wrong COMPLETE、correct-case regression、authority violation = 0。
5. 增益不来自超出 matched processing ceilings。

`PASS_RETRIEVAL_DOMINANT_RAW_PRESERVED` 使用独立预注册门：`delta_A_raw_min = 0.05` absolute ValidBindingRecall、至少净增加 1 个 valid obligation，且 paired 95% CI lower bound > 0。它不能用 `ΔA|Formed` 的结果替代。

数据量不支持预注册置信程序时，结果只能是 descriptive diagnosis，不能通过 ML-H1/ML-H2。

---

# 5. 执行 Block 与条件 DAG

## MLB-1 — Read-path Decision Boundary

对应 DG-27 与 `DG27-H1`：

~~~text
ProvisionalBinding preserves ambiguity
one final boundary emits AcceptedBinding
Sufficiency / COMPLETE computed on fresh state
known DG-25 Wrong COMPLETE closed
existing correct completion non-regressed
~~~

DG27-H1 未通过，DG-28 effect 不得进入。

## MLB-2 — Minimal Recollection Repair

DG-28 只比较：

~~~text
current product route
vs
each existing eligible official channel called once
+ identity-level union
+ one common downstream DecisionBoundary
~~~

只针对 DG-24 的 6 个 `CHANNEL_ELIGIBLE_NOT_INVOKED` 和 1 个 `CHANNEL_CUTOFF_DROP`。不含模型 planner、second round 或 eval-owned retrieval。

DG-29 只在以下全部有机器证据时进入：

~~~text
one-pass 后仍有 unresolved requirement
fresh observation 提供新 cue
存在未执行的合法 action
second-round official oracle 存在 mediator opportunity
~~~

否则为 `NOT_ENTERED_PENDING_REFINDING_OPPORTUNITY`。

## MLB-3 — Formation First-Loss 与条件 Treatment

MF-01 是观察性 Goal。其 effect 不依赖 DG-28：

~~~text
MF-01 S0–S1 schema / label / trace design
  ↓ label adequacy + Evidence snapshot seal
passive MF-01 S2–S4 effect
~~~

MF-01 terminal 后按 first-loss 条件分支：

~~~text
MF-01
  ├─ MF-02  only if episode first-loss exists
  ├─ MF-03  if identity/event/time first-loss exists
  └─ MF-04  if state/change first-loss exists
~~~

MF-03 可读取 Raw Evidence spans 或已验证 SemanticEpisode artifacts；MF-04 可读取 raw spans、verified identity/time artifacts 或两者。编号不构成依赖。无对应 first loss 时标记 `NOT_NEEDED_BY_FIRST_LOSS`。

## MLB-4 — Evolution Bridge

最小 `EV-01` 不新建 Store，重放：

~~~text
FormationArtifactCandidate
→ OperationProposal mapping
→ deterministic validation
→ StewardDecision replay
→ ClaimVersion / OpenIssue expected disposition
→ as-of current / historical read
→ correction / revocation / CanonicalStateRollback replay
~~~

全生命周期 PASS 要求：

~~~text
UnsupportedCanonicalPromotion = 0
WrongTransitionDisposition = 0
MissingProvenanceClosure = 0
ValidTimeMisassignment = 0
RevocationSupportLeak = 0
RollbackReplayMismatch = 0
~~~

若 label set 没有可验证的 state/change 与 evolution disposition，不可静默标记 EV-01 PASS；项目最多为明确限定范围的 PARTIAL。

## MLB-5 — Conditional Consolidation

MF-05 的 opportunity 与 effect 分开。

Entry / Opportunity Gate：

~~~text
failure requires cross-episode aggregation
raw/member evidence exists
simple formed units cannot form target view
oracle consolidation view can discharge requirement
~~~

无 opportunity 才是 `NOT_ENTERED_NO_CONSOLIDATION_OPPORTUNITY`；有 opportunity 但 treatment 无 mediator gain 是 `PARKED_NO_CONSOLIDATION_GAIN`。

Phase 1 view 仅含 `USER_PROFILE`、`ACTIVE_GOAL`、`DURATIVE_STATE`、`EPISODE_SCENE`。`PROCEDURAL_PATTERN` 留给后续扩展。

## MLB-6 — Factorial Evaluation 与 Integration

MF-06 归因 representation/recollection；DG-30 只集成获证据支持的最小 Read Path 组件，不宣称完整 Memory Architecture ready。

---

# 6. Simple / Adaptive 与 MF-06

`Simple Recollection`：

~~~text
one query-time acquisition phase
deterministic official lanes only
no model planner
no observation-conditioned second action
bounded EvidenceSet selection
typed Binding / Sufficiency
~~~

DG-28 deterministic multi-channel union 仍属于 Simple。

`Adaptive Recollection`：

~~~text
same DecisionBoundary
same total action/hydration/token ceilings
fresh RequirementState after observation
at most one additional admissible action
optional constrained model preference
full Gate / Binding / State / Sufficiency recomputation
~~~

DG-29 这种 observation-conditioned second action 才属于 Adaptive。

| Arm | Representation | Recollection | 用途 |
| --- | --- | --- | --- |
| A | Raw | Simple | 原始基线 |
| B | Raw | Adaptive | Raw 上 adaptive 增益 |
| C | Formed + Raw fallback | Simple | Formation 主效应 |
| D | Formed + Raw fallback | Adaptive | Formation 后 residual 与交互 |
| E | Formed only | Simple | 信息损失负控，永不作为产品候选 |

预注册计算：

~~~text
ΔF           = M(C) - M(A)
ΔA|Raw       = M(B) - M(A)
ΔA|Formed    = M(D) - M(C)
ΔInteraction = [M(D) - M(C)] - [M(B) - M(A)]
~~~

所有 arm 固定：

~~~text
same Raw Evidence and query cases
same access/revocation snapshot
same DecisionBoundary and Binding/Sufficiency
same Operator/Reader identity
same max official actions
same max hydrated Evidence units
same max Reader evidence tokens
same max model calls and rounds
same timeout policy
~~~

Latency 是结果变量，不强制各方法等 latency。

---

# 7. 指标与成本

## Formation fidelity

~~~text
EpisodeBoundaryPrecision / Recall / F1
EpisodeSelfContainedness
CrossBoundaryDependencyRate
RawSpanPreservation
DerivedSupportClosureCoverage
SpanGroundingExactness

EntityMentionRecall
IdentityPairwisePrecision / Recall / F1
FalseCrossScopeMerge = 0
AliasResolutionAccuracy

EventMentionRecall
EventIdentityPairwiseF1
EventDedupPrecision / Recall
DistinctEventPreservation

OccurrenceIntervalAccuracy
TimezoneResolutionAccuracy
AmbiguousTimePreservation
SourceEventTimeSeparationAccuracy

StateAssertionPrecision / Recall
StateTransitionExtractionRecall
TransitionRelationAccuracy
TemporaryConstraintClassificationAccuracy
CorrectionRevocationRecall
ConflictPreservation
~~~

## Evolution

~~~text
CanonicalCurrentStateAccuracy
ValidTimeAccuracy
VersionTransitionAccuracy
UnsupportedCanonicalPromotion
MissingProvenanceClosure
RevocationSupportLeak
RollbackReplayEquivalence
~~~

`ReconstructedCurrentStateAccuracy` 与 `CanonicalCurrentStateAccuracy` 分开；未经 Steward promotion 的 sidecar 只能改善前者。

## Recollection / answer

~~~text
ValidBindingRecall                         ML-H1 primary
RequiredEvidenceCoverage                  secondary
AcceptedBindingPrecision
OperatorReadyRate
TemporalCompletenessRate
FinalAnswerCorrect / F1                   attribution-safe secondary
Wrong COMPLETE
CorrectCaseRegression
~~~

## Revocation / freshness

~~~text
UnauthorizedRawEvidenceLoss = 0
DerivedArtifactRevocationLeak = 0
RevokedEvidenceRetrievalLeak = 0
StaleProjectionRead = 0
CanonicalSupportReevaluationCoverage
RevocationPropagationLagP95
FormationCoverageWatermark
FormationPendingEvidenceCount
RawFallbackActivated
~~~

## 成本与效率

写时与读时分开：

~~~text
FormationCostPerEvidence
FormationStorageAmplification
ProjectionBuildLagP95
RebuildCost

OfficialRetrievalCalls
HydratedEvidenceUnits
BindingComputations
ModelCalls
QueryLatencyP50 / P95
QueryCostPerUsefulBinding
IncrementalCostPerAdditionalValidBinding
~~~

MF-06 run-lock 必须在 effect label 揭示前固定 primary amortization horizon `H_primary`，并额外报告 `H = 1, 10, 100` 次读取的敏感性分析。未标明 H 时不得报告 `RepresentationCostPerUsefulBinding`。

---

# 8. 执行顺序与当前授权

两条支线使用独立冻结 snapshot，不互相阻塞：

~~~text
T0
  ├─ DG-27 fresh S0 → DG27-H1 effect
  └─ MF-01 S0–S1 schema / labels / trace design

MF-01 S1 label and snapshot seal
  └─ passive MF-01 S2–S4 effect

DG27-H1 PASS
  └─ DG-28 deterministic union
       └─ DG-29 opportunity decision

MF-01 terminal
  ├─ conditional MF-02
  ├─ conditional MF-03
  └─ conditional MF-04
       ├─ EV-01 when state/change labels apply
       └─ MF-05 opportunity gate

prerequisites sealed
  └─ MF-06 factorial
       └─ DG-30 minimal Read Path integration
~~~

当前只授权：

~~~text
DG-27 fresh S0 and effect
MF-01 S0–S1 schema / labels / trace design
~~~

本次文档修订不自动冻结 DG-28 run-lock，也不自动启动 MF-01 effect；局部 Goal 必须先完成各自 entry gate。

---

# 9. Terminal 分类与可达性

| 类别 | 必要条件 | 不要求 |
| --- | --- | --- |
| PASS | MF-06、DG-30、所有适用 Program 完成；EV-01 适用时通过；安全门通过 | 不要求 Adaptive 有增益 |
| PARTIAL | Read Path 完成；Formation/Evolution 因标签或范围不可充分验证；未验证范围明示 | 不要求 MF-06/EV-01 完成 |
| PARKED | entry/effect gate 已证明无法或不值得继续；根因已封存 | 不要求对应后续 Goal 执行 |
| FAIL | authority/scope/Evidence preservation/Wrong COMPLETE/canonical safety 失败 | 不因其他指标改善而降级 |

确定性决策顺序：

~~~text
if observed_safety_or_authority_failure:
    FAIL_<reason>
elif lifecycle_label_adequacy_failed:
    PARKED_INSUFFICIENT_LIFECYCLE_LABELS
elif read_path_complete and formation_or_evolution_not_evaluable:
    PARTIAL_READ_PATH_ONLY
elif MF06_complete and applicable_EV01_complete:
    classify_by_preregistered_factorial_effects()
else:
    PARKED_EXECUTION_PREREQUISITE_UNRESOLVED
~~~

| Factorial 条件 | Terminal |
| --- | --- |
| ML-H1 PASS；ML-H2 不通过或无 residual opportunity | `PASS_FORMATION_DOMINANT_SIMPLE_READ` |
| ML-H1 PASS；ML-H2 PASS | `PASS_FORMATION_AND_RECOLLECTION_COMPLEMENTARY` |
| ML-H1 不通过；`ΔA|Raw` 达到预注册增益且安全 | `PASS_RETRIEVAL_DOMINANT_RAW_PRESERVED` |
| Formation 无下游增益；Raw/formed 上 Adaptive 也无增益 | `PARKED_FORMATION_AND_RECOLLECTION_NO_GAIN` |
| `M(E)-M(C) ≤ -0.05` 且 paired 95% CI upper bound < 0 | 强制保留 Raw fallback，记录 information-loss finding；不单独覆盖上述 terminal |

`PARKED_FORMATION_NO_GAIN` 已废弃，因其不能区分 retrieval-dominant 与两者均无增益。

禁止使用：

~~~text
PASS_COMPLETE_MEMORY_ARCHITECTURE
PRODUCTION_READY
FORMAL_HOLDOUT_PASS
~~~

产品发布资格是后续独立决定。

---

# 10. 开发效率与不做事项

1. 每个局部 Goal 最多两个研究假设、五个 effect stage、四个主要运行文件。
2. 只保留一份 run-lock、一份 result、一份 terminal 和必要 failure log；不生成逐阶段 receipts。
3. 负结果完成整组预注册诊断；仅 Evidence 丢失、权限/范围违规、canonical mutation 失控或数据损坏立即停止。
4. 不生成 transitive source manifest、deliverable index、重复 runbook 或循环 reviewer package。
5. PostgreSQL/security/architecture 全量门只在修改相应边界时运行；纯 sidecar/eval 修改只跑相关测试。
6. 未证明有增益的 model、Dense、planner、graph 或 second round 不进入 DG-30。
7. 不做 case-ID/answer/gold-aware rules、Prompt/Top-k/seed sweep、eval-owned retrieval、formed-only product path、自动 Canonical promotion 或无界 refinding。

当前 development cases 不承担泛化证明；formal holdout 仍未授权。

---

# 11. 当前唯一执行导航

1. 执行 [DG-27 Read-path Decision Boundary Repair](./MiLAi_DG-27_Grounded证据解释与Binding验证_GOALS.md) 的 fresh S0 与 `DG27-H1` effect。
2. 同时完成 [MF-01 Formation First-Loss Audit](./MiLAi_MF-01_Formation_First-Loss_Audit_GOALS.md) 的 S0～S1 设计。
3. MF-01 在自身 label/snapshot gate 通过后可进入 passive effect，不等待 DG-28。
4. `DG27-H1` 通过后才可冻结 [DG-28 Minimal Multi-channel Recovery](./MiLAi_DG-28_可行动作排序与一次主动检索_GOALS.md) 的新 run-lock。
5. MF-01 terminal 决定 MF-02/MF-03/MF-04 的条件进入，不按编号串行。

局部合同：

- [Program C Read Path / Recollection Master](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
- [Program A Memory Formation Master](./MiLAi_MF-01-MF-06_Memory_Formation_and_Representation_MASTER.md)

本文件是唯一执行顺序来源；项目级 Master 只负责稳定架构边界，局部 Goal 只负责本 Goal 的实现与 effect contract。
