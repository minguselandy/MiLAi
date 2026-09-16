---
document_id: MILA-MD03
version: "0.1"
status: DESIGN_COMPLETE_EXECUTION_NOT_AUTHORIZED
document_type: DEVELOPMENT_EXPERIMENT_GOAL
architecture_baseline: MILA-ML-ARCH@1.0
execution_master: MILA-ML-MASTER@1.6
execution_authority: NONE
predecessor_terminal: var/md02/md02-boundary-product-shadow-20260830-001/terminal.json
predecessor_terminal_sha256: 8b25edec280f52bf6cea6d8824fb26bfab948cdd50ef1ec4601c3f14c3039cd7
predecessor_terminal_digest: bc19c30db84d46420e9a2a6e73bbc945a7e3718e9df47fcef250f57951984af7
formal_holdout_authorized: false
product_enablement_authorized: false
---

# MiLAi MD-03 — Identity / Event-Time / State-Change 泛化与 Governed Evolution 重放 Goal

> 本文是后续开发与实验合同，不是执行授权，也不是新的 Logical Architecture。任何数据创建、代码修改、模型调用、数据库重放或 effect 运行，都必须取得新的显式授权。

---

# 1. 当前问题与进入理由

已有机器事实不能被扩大解释：

| 既有 Goal | 已建立事实 | 尚未建立事实 |
| --- | --- | --- |
| MF-03 | 24/24 event、4/4 entity、2/2 occurrence time | 独立数据上的 identity/time 泛化；alias collision、same-event/different-event、relative/ambiguous time |
| MF-04 | 6/6 state assertion、3/3 transition | 多谓词、多措辞、否定、修正、撤回和短期约束的泛化 |
| EV-01 | 小型真实 PostgreSQL governed replay；6 个 hard gate 为 0 | 扩大后的 Formation artifact 是否仍能正确映射到既有 Evolution Core |
| MD-02 | default-OFF observation-only shadow 等价且 freshness-safe | V02 episode boundary policy 未通过 over-split 非劣门，不能采用 |

因此下一步不是重新运行 MF-03/04，也不是增加检索层，而是回答：

> **query-independent Formation 能否在全新、覆盖更广的文本记忆上稳定形成 entity、event identity、event occurrence time、state assertion 与 state transition，并继续安全地进入唯一 Governed Evolution 路径？**

MD-02 的 shadow contract 可以复用，但 V02 boundary policy 必须保持拒绝。MD-03 允许直接读取完整 Raw Evidence spans，不能把 episode 完美性作为前置条件。

---

# 2. 方法主张与研究假设

## 2.1 Method Thesis

```text
Raw Evidence
  → query-independent typed semantic candidates
  → reversible identity/time/state hypotheses
  → source-grounded validation
  → noncanonical MemoryFormationBundle
  → governed OperationProposal mapping
  → existing Validator / Steward / Canonical Procedure
```

模型或规则可以提出语义候选；Runtime 仍负责 span、source role、time basis、identity closure、scope 和 proposal 合法性。Formation 输出不能直接成为 Canonical State。

## 2.2 MD03-H1 — Semantic Formation Generalization

在全新 sealed non-holdout validation 上，当前 V01 baseline 或经过 repair-dev 开发的单一 V02 treatment 必须满足：

```text
SemanticFormationMacroF1                 ≥ 0.85
minimum component F1                     ≥ 0.75
RawSpanGroundingExactness                = 1.0
SourceEventTimeSeparationAccuracy        = 1.0
AmbiguousTimePreservationRate            = 1.0
AssistantToUserArtifactContamination     = 0
UnsupportedIdentityMerge                 = 0
DistinctEventCollapse                    = 0
QueryDependentFormationInput             = 0
```

其中：

```text
SemanticFormationMacroF1 = macro mean of
  EntityMentionF1
  IdentityPairwiseF1
  EventMentionF1
  EventIdentityPairwiseF1
  OccurrenceTimeF1
  StateAssertionF1
  TransitionRelationMacroF1
```

决策合同预先固定：

```text
若 V01 baseline 在最终 sealed score 中通过全部绝对门：
  MD03-H1 = PASS_BASELINE_GENERALIZES
  只采纳 V01；即使 repair-dev 曾触发 V02，也不把 V02 作为必要贡献

若 V01 repair-dev 未通过 entry gate：
  只在 repair-dev 上开发一个通用 treatment

若最终 sealed V01 未通过且已有预注册 treatment：
  sealed treatment 必须：
    通过全部绝对门
    SemanticFormationMacroF1 - V01 ≥ 0.05
    paired conversation bootstrap 95% CI lower > 0
```

## 2.3 MD03-H2 — Governed Evolution Compatibility

对 H1 输出中所有适用的 state/change artifacts，扩大的 EV-01 replay 必须满足：

```text
EligibleArtifactMappingRecall            ≥ 0.95
ExpectedOperationAccuracy                = 1.0
ExpectedReviewDispositionAccuracy        = 1.0
QueryLocalArtifactFilterRate             = 1.0

UnsupportedCanonicalPromotion            = 0
WrongTransitionDisposition               = 0
MissingProvenanceClosure                 = 0
ValidTimeMisassignment                   = 0
RevocationSupportLeak                    = 0
RollbackReplayMismatch                   = 0
CrossScopeIdentityLink                    = 0
```

H2 只能在全新临时 PostgreSQL 数据库中重放。允许的 Canonical mutation 仅限该临时数据库，运行结束必须清理；不得写入产品数据库。

## 2.4 Anti-Hypotheses

必须排除：

```text
增益来自 query、case ID、gold 或最终答案
增益来自将 source time 冒充 event occurrence time
增益来自不可逆 entity/event merge
增益来自 assistant 内容被错误提升为 user memory
增益来自绕过 Validator / Steward 的直接 Canonical 写入
增益只是增加模型调用、检索轮次或 Reader 上下文
```

---

# 3. 作用域与硬边界

## 3.1 本 Goal 允许设计的对象

优先复用：

```text
FormationArtifactSidecarV01
FormationEntityCandidateV01
FormationEventCandidateV01
FormationStateChangeSidecarV01
FormationStateAssertionV01
FormationStateTransitionV01
MemoryFormationBundleV01
map_state_artifact_to_proposal
MD-02 observation-only shadow contract
```

只有 repair-dev first loss 证明 V01 无法表达必要状态时，才允许增加一个内部 V02 typed sidecar。V02 必须保持：

```text
query-independent
raw-preserving
noncanonical
provenance-linked
rebuildable
default OFF
```

## 3.2 明确禁止

```text
重开或改写 MF-03 / MF-04 / EV-01 历史 terminal
继续调整 MF-02 或 MD-02 sealed cases
采用 MD-02 V02 episode boundary policy
用 RequirementState、RequirementBinding、query 或 candidate pool 构造 Formation identity
新增检索 channel、第二轮 refinding、Reader treatment 或 answer scorer
把 formed-only 作为产品路径
自动 Canonical promotion
新增 public MCP、PostgreSQL schema、后台 worker 或 durable Episode/Identity Store
使用 formal holdout
默认开启任何 experimental feature flag
训练或微调模型
```

## 3.3 唯一必须保留的正确性不变量

为避免防御性编程继续膨胀，MD-03 只把以下四项视为 Formation 硬不变量：

1. 每个 semantic artifact 必须回到 exact Raw Evidence span。
2. Formation 输入不得含 query、gold、答案或 query-time Binding。
3. source time 与 event occurrence time 必须分离；不确定时间保持 unresolved。
4. Formation artifact 永远 noncanonical；Canonical 写入仍只经过既有 governed path。

其他 classifier、feature、规则和模型均是可替换的实验策略，不升级为架构不变量。

---

# 4. 新数据合同

## 4.1 数据分区

获得执行授权后，必须在 treatment 开发前一次性冻结：

```text
repair-dev:
  ≥ 12 conversations
  只用于错误分析和通用修复

sealed-validation:
  ≥ 32 new conversations
  ≥ 128 turns
  scorer 前封存 Raw、labels、split 和 snapshot identity
  treatment 开发期间不可读取 labels

formal holdout:
  untouched
```

MF-01、MD-01、MF-02 和 MD-02 的旧数据只能作历史 replay，不能进入主效应分母，也不能用于生成 V02 规则。

## 4.2 sealed-validation 最小覆盖

| 标签族 | 最小覆盖 |
| --- | ---: |
| Entity mention | 32 |
| Alias/coreference positive pairs | 16 |
| Same-label/different-entity hard negatives | 16 |
| Event mention | 32 |
| Same-event observation pairs | 12 |
| Distinct-event hard-negative pairs | 12 |
| Event occurrence time | 24 |
| 其中 explicit event time | 8 |
| 其中 relative/cross-Evidence time | 8 |
| 其中 interval/durative time | 4 |
| 其中 ambiguous/unresolved time | 4 |
| State assertion | 24 |
| State transition | 18 |
| 每个 transition enum | 至少 2 |
| Source-time-as-event-time negative controls | 8 |
| Assistant contamination negative controls | 8 |

Transition enum 只使用当前真实合同：

```text
ESTABLISHES
UPDATES
CORRECTS
REVOKES
TEMPORARILY_CONSTRAINS
```

不为实验方便新增未实现 enum。

## 4.3 标注单位

```text
Evidence span
Entity mention
Entity identity pair
Event mention
Event identity pair
Occurrence-time interval + time basis
State assertion tuple
State transition relation
Expected proposal operation / review disposition
```

Identity 使用 pairwise label，避免强制一次性生成不可逆全局 cluster。Ambiguous identity/time 必须允许 `UNRESOLVED`，不能强迫单值答案。

---

# 5. Matched 实验设计

## 5.1 固定输入

所有 arm 共享：

```text
同一 Raw Evidence snapshot
同一 source order / role / observed_at
同一 accepted MF-02 V01 episode context（若使用）
同一 Raw fallback
同一 scorer 与 label mapping
同一 maximum model-call / token / timeout policy
同一 Evolution validator、policy 和 PostgreSQL migration identity
```

MD-02 V02 episode 不能进入任一 arm。

## 5.2 Arms

| Arm | 含义 | 必须运行 |
| --- | --- | --- |
| A0 | 当前 V01 deterministic + 已有 residual behavior | 是 |
| A1 | 单一通用 V02 treatment；仅当 A0 repair-dev 未通过 entry gate | 条件式 |
| A2 | A1 去掉模型 residual；仅当 A1 实际使用模型 | 条件式消融 |
| N0 | source/event-time、assistant/user、same/distinct-event 负控 | 是 |

不建设更多 treatment arms，不做 Prompt、seed、Top-k 或模型规模 sweep。

## 5.3 模型的条件式位置

模型不是默认依赖。只有 repair-dev 证明存在下列 residual 时才允许启用：

```text
PARAPHRASE_ENTITY_GAP
CROSS_EVIDENCE_EVENT_IDENTITY_GAP
RELATIVE_TIME_INTERPRETATION_GAP
STATE_CHANGE_EXPRESSION_GAP
```

模型只能产生 source-quote-grounded proposal；Runtime 计算或验证 offset、time basis、identity membership 和 digest。模型不能输出 Canonical operation、Steward decision 或 completion 状态。

若启用模型：

```text
固定 local model/revision/tokenizer/template
批量推理
temperature = 0 或等价确定性配置
每个 eligible conversation 最多一次 logical extraction
schema/semantic invalidity 不自动重试
不调用外部 Provider
```

---

# 6. 开发与实验流程

## D0 — Contract and Label Sanity

只完成：

```text
新 repair-dev / sealed-validation seal
label coverage validation
scorer 手算 fixture
V01 source-only unscored output
run-lock identities
```

硬门：

```text
label coverage 满足第 4 节
query/gold/answer absent from Formation input
Raw Evidence preservation = 1.0
formal holdout used = false
```

## D1 — Current V01 Baseline

先运行当前 V01，不修改算法。sealed labels 仍关闭，分别生成 repair-dev 与 sealed unscored output。

只打开 repair-dev labels 进行 first-loss：

```text
MENTION_MISSED
IDENTITY_OVERMERGED
IDENTITY_OVERSPLIT
DISTINCT_EVENTS_COLLAPSED
SAME_EVENT_DUPLICATED
SOURCE_TIME_USED_AS_EVENT_TIME
RELATIVE_TIME_UNRESOLVED
AMBIGUOUS_TIME_FORCED
STATE_ASSERTION_MISSED
TRANSITION_RELATION_WRONG
ASSISTANT_CONTAMINATION
```

如果 V01 在最终 sealed scoring 中通过全部绝对门，直接采用 baseline；即使 repair-dev 曾触发 V02，也不得为了“有新代码”而采纳 V02。

## D2 — Repair-Dev-Only General Treatment

仅在 V01 repair-dev first loss 表明有可修复通用根因时进入。

允许最多 3 个 repair iterations：

```text
观察 repair-dev first loss
→ 修改一个通用机制
→ touched tests + repair-dev score
→ 保留简短 repair-log
```

同一根因连续 3 次没有改善时，停止该 treatment，转为架构备选分析；不终止整个 Memory Program。

禁止：

```text
case-ID / quote literal / answer-aware rules
查看 sealed labels
改变 sealed split
改变 scorer
扩大模型、token 或 context budget 来掩盖错误
```

## D3 — One Sealed Matched Effect

冻结代码后一次性运行：

```text
A0 baseline output
A1 treatment output（如适用）
A2 deletion ablation（如适用）
→ 一次打开 sealed labels
→ 同一 scorer 计算全部 metrics
→ conversation-level paired bootstrap
```

不得根据 sealed 结果修改并重跑 treatment。任何 protocol/transport 问题若 fail-closed 且没有输出逃逸，记录为 `REPAIR_ITERATION`；修复执行器后可以完成同一逻辑 run，但不得改变方法、数据或预算。

## D4 — Governed Evolution Replay

只有 H1 产生可接受 Formation output 后进入。

至少覆盖 12 条预注册 lifecycle sequences：

```text
CREATE
SUPPORT
SUPERSEDE / UPDATES
SUPERSEDE / CORRECTS
CONTEXTUALIZE / TEMPORARILY_CONSTRAINS
WEAKEN / REVOKES
REGROUND with fresh independent Evidence
QUERY_LOCAL_ONLY filtered
current read
historical as-of read
revoke → blocked/reopen behavior
rollback/replay equivalence
```

流程固定：

```text
Formation artifact
→ map_state_artifact_to_proposal
→ existing deterministic validation
→ existing CommitPolicy / Steward path
→ existing Canonical Procedure
→ current/historical/revocation replay
```

不新增第二套 Evolution store 或写入口。

## D5 — Compact Terminal

只汇总：

```text
H1/H2 disposition
component metrics
first-loss distribution
model/cost metrics
seven hard authority counters
successor route
```

不生成逐阶段 receipt、transitive manifest、重复 runbook 或 reviewer loop。

---

# 7. 效率与资源合同

默认执行策略：

```text
CPU batch for deterministic formation/scoring/bootstrap
并行单位 = conversation
worker ceiling 由 run-lock 根据机器物理核冻结
GPU = 0 unless repair-dev proves a semantic residual
如需模型，只复用已经独立 probe 的本地 vLLM endpoint
无训练、无远程 Provider、无 Reader、无 retrieval
```

固定处理上限，而不是强制相同 latency：

```text
max source turns
max model-eligible conversations
max logical model extractions
max input/output tokens
timeout policy
```

报告：

```text
FormationLatencyP50/P95
FormationCostPerConversation
ModelEligibleRate
ModelCalls
Prompt/CompletionTokens
ArtifactCountPerRawTurn
RepairIterations
```

不得为满足“充分利用 GPU”而增加模型路径；并行只缩短 wall time，不增加逻辑尝试或样本权重。

---

# 8. 质量门与制品上限

## 8.1 开发质量门

```text
每次编辑：touched unit tests + edited-file Ruff/mypy
D3 前：MF-02/MD-01/MD-02 compatibility regression
D4 前：formation_evolution_bridge targeted tests
terminal 前：相关 runtime unit + contract + one real PostgreSQL replay
```

只有修改 PostgreSQL、security、public MCP 或 frozen architecture 时才扩大到对应全量门。本 Goal 默认不修改这些边界。

## 8.2 正式输出上限

一个有效 MD-03 run 最多保留：

```text
run-lock.json
results.json
terminal.json
repair-log.jsonl        # 仅有 repair iteration 时
```

临时 PostgreSQL 数据库必须清理；凭据、原始私密正文和模型 Prompt 不进入公开 artifact。

---

# 9. Terminal 决策

```text
if actual Evidence loss, permission leak, cross-scope link,
   production Canonical mutation, or authority bypass:
  FAIL_MD03_AUTHORITY_OR_EVIDENCE_SAFETY

elif new label coverage is insufficient:
  PARKED_MD03_INSUFFICIENT_GENERALIZATION_LABELS

elif V01 passes H1 and H2 passes:
  PASS_MD03_BASELINE_GENERALIZES_EVOLUTION_SAFE

elif treatment passes H1 and H2 passes:
  PASS_MD03_FORMATION_GENERALIZES_EVOLUTION_SAFE

elif H1 passes and H2 misses without safety escape:
  PARTIAL_MD03_FORMATION_GENERALIZES_EVOLUTION_UNRESOLVED

elif H1 misses after the one sealed effect:
  PARKED_MD03_NO_SEMANTIC_GENERALIZATION_GAIN

else:
  PARTIAL_MD03_UNRESOLVED
```

单次 schema、offset、timezone、adapter 或 transport 错误在 fail-closed 条件下是 repair iteration，不是 Goal terminal。只有真实状态逃逸或最终有效 treatment 的预注册错误才进入 FAIL/PARK/PARTIAL。

---

# 10. 后续路由

只有 `PASS_MD03_*_EVOLUTION_SAFE` 才允许另行设计：

```text
MF-05 consolidation opportunity audit
或
扩大后的 MF-06 Raw+Simple vs Formed+Simple matched evaluation
```

若 H1 的主要 first loss 位于：

| First loss | 后续处理 |
| --- | --- |
| entity/event identity | 独立 identity-resolution successor，不改 retrieval |
| occurrence time | temporal formation successor，不把 source time 降级为 event time |
| state/change expression | typed semantic extractor successor |
| Evolution mapping | EV bridge successor，不重写 Formation extractor |
| episode boundary | 新数据上的独立 boundary V03；不使用 MD-02 sealed set |

任何 PASS 都不自动授权 durable schema、产品默认启用、Reader、adaptive retrieval 或 formal holdout。

---

# 11. 当前授权状态

```text
Goal design:                 COMPLETE
Data creation:               NOT AUTHORIZED
Code changes:                NOT AUTHORIZED
Model calls:                 NOT AUTHORIZED
PostgreSQL replay:            NOT AUTHORIZED
Sealed effect:               NOT AUTHORIZED
Formal holdout:              FORBIDDEN
Product feature enablement:  FORBIDDEN
```

执行者必须先取得新的显式授权并创建 superseding run-lock；本文件本身不能作为运行授权。
