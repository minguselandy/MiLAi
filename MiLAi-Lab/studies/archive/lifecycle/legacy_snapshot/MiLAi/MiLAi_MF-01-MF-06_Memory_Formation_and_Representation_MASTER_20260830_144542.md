---
document_id: MILA-MF-MASTER
version: "0.3"
status: ACTIVE_PROGRAM_A_SUBPLAN
execution_order_authority: MILA-ML-MASTER
architecture_baseline: MILA-ML-ARCH@1.0
---

# MiLAi Program A：MF-01～MF-06 Memory Formation and Representation Master

> 文档版本：0.3 / ACTIVE PROGRAM-A SUBPLAN
> 日期：2026-08-30（Asia/Shanghai）
> 总执行导航：[MiLAi Memory Lifecycle 总 Goal](./MiLAi_Memory_Lifecycle_总_GOALS.md)
> 所属项目：[MiLAi Memory Lifecycle 项目级 Master](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)
> 当前入口：[MF-01 Formation First-Loss Audit](./MiLAi_MF-01_Formation_First-Loss_Audit_GOALS.md) 的 S2～S4 passive audit
> Schema：0.1.x EXPERIMENTAL / 本 Program 暂不迁移
> Formal holdout：不使用

---

# 1. Program 目标

Program A 回答：

> Raw Evidence 中哪些可复用的 episode、identity、event time、state 和 change 没有被正确形成，以及形成这些表示是否使简单读取足够有效？

采用：

~~~text
Raw Evidence
+
rebuildable semantic representations
+
governed promotion into existing Canonical Core
~~~

禁止：

~~~text
formed summary 替代 Raw Evidence
extractor output 自动成为 Claim
不可逆 entity/event merge
用最终 QA 分数替代 Formation 直接评价
~~~

---

# 2. Formation artifact 类型

这些对象只是 `FormationArtifactCandidate` 类型，统一包装在项目级 Master 定义的 `FormationArtifactEnvelope` 中。它们可持久化用于实验审计和重建，但不是 frozen durable logical object、Canonical memory 或 authority-bearing Claim。

## SemanticEpisodeVersion

~~~yaml
episode_id:
version:
evidence_span_ids: []
participants: []
topic_hypotheses: []
event_mentions: []
source_time_range:
boundary_reason:
formation_identity:
~~~

允许 overlap、split、merge；必须回到 Raw Evidence span。

## IdentityClusterVersion

~~~yaml
identity_id:
version:
mention_ids: []
label_candidate:
aliases: []
scope:
merge_history: []
split_history: []
unresolved_competitors: []
~~~

支持 merge、split 和 rollback；同名不同人不得被永久折叠。

## EventOccurrenceCandidate

~~~yaml
event_candidate_id:
event_type:
participant_candidates: []
object_candidates: []
location_candidate:
occurrence_interval:
source_time:
reference_time:
evidence_span_ids: []
identity_hypotheses: []
~~~

occurrence time 与 dialogue/source time 必须分开。

## StateAssertionCandidate

~~~yaml
subject_identity:
predicate:
value:
valid_time:
evidence_span_ids: []
modality:
scope:
confidence:
~~~

## StateTransitionCandidate

~~~yaml
previous_state_candidates: []
new_state_candidate:
transition_relation:
trigger_event_candidates: []
valid_time:
evidence_span_ids: []
~~~

transition_relation 最少区分：

~~~text
ESTABLISHES
UPDATES
CORRECTS
REVOKES
TEMPORARILY_CONSTRAINS
CONTRADICTS
REFINES
~~~

## ConsolidatedMemoryView

~~~yaml
view_id:
view_version:
subject:
view_kind:
supporting_claim_ids: []
supporting_evidence_ids: []
contested_elements: []
valid_time:
invalidation_conditions: []
~~~

它是 read model，不是 Claim。

## Sidecar runtime contract

所有上述对象必须使用 `MILA-ML-ARCH@1.0` 的 `FormationArtifactEnvelope`，至少绑定 producer/model/config、source Evidence/span、snapshot、access policy、idempotent build key、build epoch、source watermark、status、supersedes lineage 与 derivation graph。

~~~text
at-least-once safe processing
dead-letter visibility
per-projection watermark and stale detection
rebuild from Raw Evidence
source revocation → immediate read block and projection invalidation
FormationCoverageWatermark < EvidenceWatermark → PARTIAL/STALE + Raw fallback
~~~

Sidecar 可以持久保存用于实验与重建，但不因此成为 durable logical object 或 Canonical memory。

---

# 3. Goal 路线

| Goal | 核心问题 | 进入条件 | 主要输出 |
| --- | --- | --- | --- |
| MF-01 | Formation 首损在哪里 | 立即进入 | label contract、trace、first-loss map |
| MF-02 | semantic episode 是否优于固定 chunk | MF-01 证明 episode loss 是主要因素 | versioned episode sidecar |
| MF-03 | identity、event identity、occurrence time 是否稳定 | MF-01 证明 identity/event/time loss；可直接读取 raw spans | identity/event/temporal sidecar |
| MF-04 | state/update/correction/revocation 是否正确形成 | MF-01 证明 state/change loss；所需 identity/time 输入已验证或直接来自 raw spans | assertion/transition candidates |
| EV-01 | Formation candidate 能否正确进入现有 Evolution Core | 存在预注册 state/change 与 canonical disposition labels | Proposal/Steward/ClaimVersion/OpenIssue replay |
| MF-05 | scene/profile/durative state 是否有独立价值 | consolidation opportunity gate 通过 | support-closed read views |
| MF-06 | Formation 与 adaptive recollection 各自贡献多少 | 所有适用 treatment、DecisionBoundary 和 EV-01 disposition 已封存 | representation × recollection factorial |

MF-02～MF-06 与 EV-01 在满足进入条件时才生成独立 Goal 文档；编号不构成串行依赖，本 Master 不预先冻结实现细节。

条件 DAG：

~~~text
MF-01
  ├─ MF-02  only for episode first loss
  ├─ MF-03  for identity/event/time first loss
  └─ MF-04  for state/change first loss
       ├─ EV-01 when evolution labels apply
       └─ MF-05 opportunity gate
~~~

MF-03 可消费 Raw Evidence spans 或已验证的 MF-02 artifact；MF-04 可消费 raw spans、已验证 identity/time artifact 或两者。任何 Goal 不为补齐编号而进入。

---

# 4. MF-01 — Formation First-Loss Audit

观察当前实际路径：

~~~text
Raw Evidence
→ Episode
→ Mention
→ Identity
→ Event Time
→ State / Change
→ OperationProposal
→ Canonical disposition
→ Retrieval Projection
~~~

当前源码没有执行的 stage 必须记录 NOT_IMPLEMENTED，不得在评估层伪造实现。

MF-01 不替换 extractor、不调 Prompt、不新增模型、不创建 Migration。

---

# 5. MF-02 — Semantic Episode Formation

比较：

~~~text
turn
fixed window
session
semantic episode
~~~

直接指标：

~~~text
boundary precision / recall
self-containedness
cross-boundary dependency
raw-span preservation
split / merge reversibility
~~~

只有 semantic episode 在直接指标和简单 retrieval 上均有净增益，才保留。

---

# 6. MF-03 — Identity / Event / Temporal

目标：

~~~text
entity mention and alias resolution
entity merge / split / rollback
event identity and distinct-event preservation
occurrence-time interval
source/event-time separation
ambiguous-time preservation
~~~

该 Goal 是 temporal COUNT、multi-session aggregation 和 state evolution 的共同 substrate，不以关键词召回替代。

---

# 7. MF-04 — State and Change Formation

形成 StateAssertionCandidate 与 StateTransitionCandidate；只有通过 EV-01 的 typed mapping 才进入现有写路径：

~~~text
OperationProposal
→ Validator / Steward
→ ClaimVersion / OpenIssue
~~~

重点区分：

~~~text
永久更新
短期约束
上下文例外
显式修正
撤回
冲突
~~~

不创建第二套 canonical store。

---

# 8. EV-01 — Evolution Bridge

对预注册 state/change labels 重放：

~~~text
FormationArtifactCandidate
→ OperationProposal mapping
→ deterministic validation
→ StewardDecision
→ ClaimVersion / OpenIssue expected disposition
→ as-of current/historical read
→ correction/revocation/CanonicalStateRollback replay
~~~

硬门为 UnsupportedCanonicalPromotion、WrongTransitionDisposition、MissingProvenanceClosure、ValidTimeMisassignment、RevocationSupportLeak 与 RollbackReplayMismatch 全部为 0。该 Gate 复用现有 Canonical Core，不新建 Store。

---

# 9. MF-05 — Consolidation and User Model

Entry / Opportunity Gate：

~~~text
failure requires cross-episode aggregation
raw/member evidence exists
simple formed units cannot discharge requirement
oracle consolidation view can discharge it
~~~

只有 opportunity 存在才实现下列 Phase 1 view：

~~~text
episode → scene
repeated evidence → preference hypothesis
events → durative state
~~~

每个 view 必须保存 support set、valid time、contested alternatives 和 invalidation rule。

无 opportunity 为 `NOT_ENTERED_NO_CONSOLIDATION_OPPORTUNITY`；有 opportunity 但 treatment 无 gain 为 `PARKED_NO_CONSOLIDATION_GAIN`。

---

# 10. MF-06 — Representation × Recollection

`Simple Recollection` 是一次 query-time acquisition、deterministic official lanes、无 planner、无 observation-conditioned second action，并使用 typed Binding/Sufficiency。

`Adaptive Recollection` 使用同一 DecisionBoundary 与处理上限，在 fresh observation 后最多追加一个 admissible action，并完整重算 Gate/Binding/State/Sufficiency。

正式 2×2 与负控：

| Arm | Representation | Retrieval |
| --- | --- | --- |
| A | Raw | Simple |
| B | Raw | Adaptive |
| C | Formed + Raw fallback | Simple |
| D | Formed + Raw fallback | Adaptive |
| E | Formed only | Simple |

预注册关键差值：

~~~text
ΔF           = M(C) - M(A)
ΔA|Raw       = M(B) - M(A)
ΔA|Formed    = M(D) - M(C)
ΔInteraction = [M(D) - M(C)] - [M(B) - M(A)]
formation loss risk = M(E) - M(C)
~~~

所有 arm 固定 max official actions、hydrated Evidence units、Reader evidence tokens、model calls、rounds 和 timeout policy；latency 是测量结果，不是强制相同的预算变量。

解释：

| 结果 | 工程结论 |
| --- | --- |
| `ML-H1 PASS`，`ML-H2` 不通过或无 residual opportunity | representation 是主因，不建设复杂 refinding |
| `ML-H1` 不通过，`ΔA|Raw` 达到 MILA-ML-MASTER 的预注册门 | recollection 仍是主因 |
| `ML-H1 PASS` 且 `ML-H2 PASS` | Formation 与 adaptive recollection 互补 |
| `M(E)-M(C) ≤ -0.05` 且 paired 95% CI upper bound < 0 | raw fallback 必须永久保留 |
| `ΔInteraction` 达到 run-lock 预注册门 | 存在 representation × active recollection 交互 |

---

# 11. 评价层

## Formation 直接指标

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
Alias resolution accuracy

EventMentionRecall
EventIdentityPairwiseF1
EventDedupPrecision / Recall
Distinct-event preservation

OccurrenceIntervalAccuracy
TimezoneResolutionAccuracy
AmbiguousTimePreservation
SourceEventTimeSeparationAccuracy

StateAssertionPrecision / Recall
StateTransitionExtractionRecall
Transition relation accuracy
TemporaryConstraintClassificationAccuracy
Correction/revocation recall
Conflict preservation
~~~

## 下游指标

~~~text
ValidBindingRecall
RequiredEvidenceCoverage
OperatorReady
ReconstructedCurrentStateAccuracy
CanonicalCurrentStateAccuracy
TemporalCompleteness
ObsoleteMemoryUsageRate
~~~

## 治理硬边界

~~~text
Unsupported Canonical Promotion = 0
Missing Provenance Closure = 0
Wrong-scope Identity Link = 0
Irreversible False Merge = 0
UnauthorizedRawEvidenceLoss = 0
DerivedArtifactRevocationLeak = 0
RevokedEvidenceRetrievalLeak = 0
StaleProjectionRead = 0
~~~

`ReconstructedCurrentStateAccuracy` 与 `CanonicalCurrentStateAccuracy` 必须分开。未经 Steward promotion 的 sidecar 只能改善前者。

成本分开报告 `FormationCostPerEvidence`、`FormationStorageAmplification`、`ProjectionBuildLagP95`、`RebuildCost`、`QueryLatencyP50/P95` 和 `QueryCostPerUsefulBinding`。`RepresentationCostPerUsefulBinding` 必须标注 MF-06 run-lock 预注册的摊销读取次数 H。

直接 Formation 指标不通过时，即使最终 QA 上升，也不得宣称形成机制正确。

---

# 12. 数据策略

继续使用：

~~~text
LongMemEval family：retrieval、temporal、update、abstention
Memora：consolidation、mutation、obsolete-memory misuse
HorizonBench：preference evolution 与旧偏好 hard negative
~~~

LongMemEval-V2 的 workflow、environment gotcha 与 procedural memory 属于后续扩展，不进入 Phase 1 的主假设或完成门。

外部 benchmark 只在本地已有、版本固定且授权的 snapshot 上运行。

另建小型 label-sealed Formation validation：

~~~text
raw evidence spans
episode boundaries
entity mention clusters
event identity clusters
occurrence-time intervals
state assertions
state transitions
expected canonical disposition
~~~

当前 10 个 diagnosis/dev cases 只做开发诊断，不承担泛化证明；Formal holdout 未授权前保持不使用。

---

# 13. 模型与 Runtime 分工

模型可以生成：

~~~text
episode boundary proposal
mention extraction
identity resolution proposal
event-time proposal
state/change classification
consolidation hypothesis
~~~

Runtime 保留：

~~~text
span / identity / time / type validation
permission and scope
version and rollback
Proposal admission
Steward decision
Canonical commit
~~~

优先拆成不同 typed task；可以共用 vLLM 后端，但不使用一个 Prompt 一次输出全部对象。

---

# 14. 开发效率规则

1. MF-01 S0/S1 已封存；当前执行 S2～S4，只剩 passive trace hook behavior-equivalence gate，不等待 DG-27 或 DG-28。
2. 每个后继 Goal 只在 MF-01 对应 first-loss 证据支持时创建；编号不形成串行前置。
3. 开发实验允许中间错误；protocol/implementation 失败先修通用根因再评估，不因单次尝试或单一 metric miss 停止整组诊断。
4. 只有 Evidence 丢失、权限违规、Canonical mutation 或数据损坏立即停止。
5. 每个 Goal 最多两项 Research Hypotheses、五个 effect stage 和四个主要运行文件。
6. 不生成逐阶段 receipts、transitive manifests、重复 runbooks 或多轮 reviewer。
7. 不用 case-ID、答案或 gold 构造 extractor 规则。

---

# 15. 当前顺序

~~~text
MF-01 audit
  ├─ MF-02 if episode loss
  ├─ MF-03 if identity/event/time loss
  └─ MF-04 if state/change loss
       ├─ EV-01 when evolution labels apply
       └─ MF-05 opportunity gate
→ MF-06 factorial after all applicable dispositions are sealed
~~~

MF-01 与 DG-27 可以同时推进，但两个实验保持各自 candidate、scorer 和 terminal，不相互借用结果宣称。
