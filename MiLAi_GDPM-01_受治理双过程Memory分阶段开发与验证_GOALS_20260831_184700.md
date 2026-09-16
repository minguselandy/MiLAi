---
document_id: MILA-GDPM-01
version: "0.1"
status: DESIGN_COMPLETE_AWAITING_MASTER_ACTIVATION
document_type: DEVELOPMENT_AND_VALIDATION_GOAL
created_at: "2026-08-31T18:47:00+08:00"
architecture_baseline: MILA-ML-ARCH@1.0
architecture_design_source: MILA-GDPM-ARCH@0.1
diagnostic_source: MILA-LME-AUDIT-20260831@1.1
execution_order_authority: MILA-ML-MASTER
authority_snapshot: MILA-ML-MASTER@1.9
execution_authorized: false
execution_scope: NONE
activation_condition: MILA-ML-MASTER_EXPLICITLY_RECORDS_MILA-GDPM-01_AS_ACTIVE_UMBRELLA_WITH_EXACT_BLOCK_AND_RUN_SCOPE
predecessor_goal: MILA-ML-R02@0.2
predecessor_terminal_artifact: var/ml_r02/ml-r02-20260831-004/terminal.json
predecessor_terminal_status: COMPLETE_USER_LIMIT_8X4
first_executable_child: MILA-ML-EVAL-00
development_control: LEAN_REPAIR_CONTINUE
audit_policy: MINIMUM_SUFFICIENT_EVIDENCE
formal_holdout_authorized: false
product_default_enable_authorized: false
canonical_schema_change_authorized: false
public_mcp_change_authorized: false
benchmark_judge_backend: LOCAL_VLLM_QWEN
leaderboard_equivalence_claimed: false
requested_supersession_on_master_activation:
  - MILA-ML-R02@0.2::unexecuted_future_navigation_only
supersession_authority: MILA-ML-MASTER_ONLY
does_not_supersede:
  - architecture/v1.0
  - MiLAi-Logical-Architecture-1.0.0-FROZEN
  - MILA-ML-ARCH@1.0
  - MILA-ML-MASTER@1.9
  - sealed_ML-CLOSURE_ML-R01_ML-R02_artifacts
does_not_authorize:
  - execution_before_master_activation
  - reuse_or_overwrite_of_legacy_R4_contexts_or_terminals
  - formal_holdout
  - product_default_enablement
  - frozen_architecture_or_canonical_schema_change
  - public_MCP_contract_change
  - automatic_canonical_promotion
  - free_search_agent_or_unbounded_refinding
  - model_owned_binding_complete_or_commit_authority
  - 24_128_or_500_case_execution_without_explicit_scope_in_MILA-ML-MASTER
---

# MiLAi GDPM-01：受治理双过程 Memory 分阶段开发与验证 Goal

_本文件把受治理双过程 Memory 架构转换为可执行、可修复、低审计负担的开发计划。它在被 MILA-ML-MASTER 激活前只是一份下位设计合同，不启动代码修改、实验、产品开关或 formal holdout。_

---

## 📋 Goal 定位、范围与授权

本 Goal 的目标是在不重写 Evidence 与 Canonical Core 的前提下，完成 Phase 1 文本个人记忆生命周期候选：

~~~text
Raw Evidence
→ Raw-preserving Formation
→ existing governed Canonical Evolution
→ fast familiarity recollection
→ bounded associative recollection when needed
→ grounded EvidenceSet convergence
→ Context / Reader / Agent
→ outcome and accessibility feedback
~~~

本 Goal 对应的设计来源是 [受治理双过程 Memory 架构设计](./MiLAi_受治理双过程Memory架构设计_20260831.md)，失败模型来源是 [LongMemEval 全切片审计与 Memory 架构重构设计](./MiLAi_LongMemEval全切片审计与Memory架构重构设计_20260831.md)。

### 权威边界

当前唯一执行顺序来源仍是 [MILA-ML-MASTER@1.9](./MiLAi_Memory_Lifecycle_总_GOALS.md)。本 Goal 不自行获得执行权。激活前必须由 Master：

1. 登记 ML-R02 的真实终态 COMPLETE_USER_LIMIT_8X4；
2. 明确结束或 supersede 其未执行的未来导航；
3. 若只激活 MILA-ML-EVAL-00，则授权范围仅为 B0，不自动激活 B1～B4；
4. 若激活 umbrella Goal MILA-GDPM-01，必须同时写明 exact active block、case scope 与 run scope；
5. 单独授权每个 24、128、500-case block，并刷新本文件记录的 Master authority snapshot。

激活后，本 Goal 也只规范自己的实现、实验和 terminal。稳定 Program/Plane 边界仍由 MILA-ML-ARCH 定义；对象身份、单写者、权限、删除和事务仍受 architecture/v1.0 与 Lean 实施合同约束。

### 本轮完成范围

必须完成或形成明确的 NOT_NEEDED / PARKED 结论：

- 评测语义身份、Context admission 与 Reader-visible trace；
- QueryTaskContract、CognitiveWorkspace 与 grounded read boundary；
- Raw、Canonical、Dense、FTS、adjacency、eligible Formed lane 的简单 EvidenceSet；
- query-independent、增量、Raw-preserving Formation sidecar；
- Formation 到既有 OperationProposal / Steward 写链的最小桥；
- Familiarity fast path 与有机会才进入的 bounded associative slow path；
- non-authoritative accessibility、AttentionThread 和 BranchLedger projection；
- OpenWorker / MCP / Runtime 产品同构路径；
- LongMemEval 与真实使用场景的分层验证；
- model outage、撤销、跨 scope 与 false association 负控。

明确不进入：

~~~text
multimodal memory
procedural skill or workflow learning
multi-agent shared memory
automatic Canonical promotion
automatic profile promotion
free-search Agent
default multi-round ReFind
global graph as truth store
clinical or ADHD inference
formal holdout
Schema freeze or Production-ready claim
~~~

新增 CognitiveWorkspace、AssociativeBranchLedger、AttentionThread 和 Accessibility 先保持 query-local 或 sidecar、noncanonical、rebuildable。任何 durable object、Schema 或公开 API 变化必须另走 architecture-vNext ADR。

## 🧭 历史证据与开发原则

历史实验不再被当作需要重新补考的障碍，而是本 Goal 的设计输入：

| 历史事实 | 已证明的边界 | 本 Goal 的处理 |
| --- | --- | --- |
| DG-19 residual cue 交付成功但 mediator 增益不足 | 模型调用成功不等于检索有效 | 不从 cue 或多轮 Agent 开始 |
| DG-20 fresh state + official deterministic acquisition 已足够 | 简单路径可能不需要模型 | Fast path 永远先于 slow path |
| DG-21～23 出现 Reader 回归和人工 512/2048 切片 | retrieval、Context、Reader 必须分开归因 | 使用 exact visible trace 与实用 token 轨 |
| DG-24：23 组中 6 个 channel 未调用、1 个 cutoff、3 个现有 channel 未发现 | first loss 主要不在单一模型 | 先做 official multi-channel 与 EvidenceSet |
| DG-25：119 条 failure 后仍有 Binding precision 与 Wrong COMPLETE | 审计数量不能制造正确性 | 只保留少量硬不变量与一个决定边界 |
| DG-26 fixed-pool StateView 无独立增益并挤掉正确 evidence | 更复杂 state prompt 和更大 K 不是默认答案 | 不重开同类 reranking 调参 |
| DG-27 协议错误可修复，但有效 effect 仍有 Wrong COMPLETE | protocol failure 与 method failure 不同 | 前者修复继续，后者保留负结果并换机制 |
| DG-28 official union 使候选 4/7→7/7、Binding 3/7→6/7，Formation 到 7/7 | 简单 union 和 formed lane 已有工程机会 | 先产品同构复用，不建自由 planner |
| MF/MD 直接表示指标较好，但 MF-06 净增益仅 1 个 obligation 且 CI 含 0 | Formation 有 substrate 信号，尚无泛化主张 | 先 direct funnel，再谈 QA effect |
| ML-CLOSURE 500-case 被 477/500 Candidate context failures 主导 | 旧分数主要测到运行失败 | 不作为语义 baseline |
| ML-R02 8×4 送达完成但 session identity、visible subset 和 formed exposure 仍不成立 | 旧 R4 只可诊断 pipeline | B0 后重建 untreated baseline |
| LongMemEval 470 个可回答 case 中 300 个需要多 session | 单条 Top-1 不是主要目标 | 优化 requirement-role EvidenceSet |

### 开发方法

本 Goal 使用以下简化原则：

~~~text
一个 Raw source of record
一个 Canonical writer
一个 query-local workspace
一个 Evidence acceptance boundary
一个 strict COMPLETE owner
一份 exact Reader-visible trace
~~~

只有下列六项是跨组件硬不变量：

1. subject、session、source、turn、Evidence 和 candidate identity 真实；
2. scope、permission、retention 与 revocation 不泄漏；
3. Reader-visible trace 与真实序列化内容、顺序和 token 计费一致；
4. ordinary recall 具有 grounded subject / relation / source-role Binding；
5. strict COMPLETE 只由唯一 DecisionEngine profile 产生，且 proof 闭合；
6. Formation、retrieval、模型、Reader 和 evaluation 都不能直接修改 Canonical State。

通道排序、episode 边界、cue、rerank、fusion、Context 排版、accessibility score 和 branch preference 都是可替换策略。不得在每一层重复建立 parser、digest、validator、receipt 或 fail-closed 状态机。

## 🎯 研究假设与反主张

本 Goal 最多保留两个主假设。

### GDPM-H1 — Fast Memory Convergence

在真实 identity、exact Reader-visible Context 和相同预算下，MiLA-Fast：

~~~text
Raw + Canonical + eligible Formed lanes
+ requirement-level EvidenceSet
+ grounded Binding
+ ordinary / strict readiness separation
~~~

应比简单 Hybrid baseline 提高 ValidSemanticBindingRecall 与 ReaderVisibleRequirementRoleCoverage，并在本地 Qwen Judge 上形成端到端改善。

500-case 确认性支持门：

~~~text
QwenJudgeAccuracy absolute delta >= 0.02
AND paired bootstrap 95% CI lower bound > 0
AND ValidSemanticBindingRecall and visible role coverage move in same direction
AND SessionIdentityIntegrity = 1.0
AND ReaderVisibleTraceExactness = 1.0
AND AcceptedReferenceIntegrity = 1.0
AND SemanticBindingPrecision = 1.0 on accepted labeled bindings
AND KnownFalseBinding = 0
AND WrongComplete = 0
AND CorrectCaseRegression = 0
AND CrossScopeLeak = 0
AND RevokedEvidenceLeak = 0
AND CanonicalMutationFromReadPath = 0
~~~

若 500-case 未获单独授权，只能报告 24/128-case development evidence，不能宣称 H1 通过。

### GDPM-H2 — Bounded Associative Utility

仅在 MiLA-Fast 后仍有合法 residual opportunity 的 case 上，MiLA-Dual 允许：

~~~text
one state diagnosis or action-ranking call
+ at most one additional official acquisition action
+ full fresh Binding / readiness recomputation
~~~

它应相对 MiLA-Fast 提高 intention-to-treat QwenJudgeAccuracy 与 requirement-role coverage，并保持 false association、成本和延迟受控。

500-case 确认性支持门：

~~~text
ITT QwenJudgeAccuracy absolute delta >= 0.02
AND paired bootstrap 95% CI lower bound > 0
AND P95 query latency <= 1.5 × MiLA-Fast
AND FalseAssociationRate does not worsen on the negative-control suite
AND additional model calls <= 1 per eligible case
AND additional official actions <= 1 per eligible case
AND every absolute H1 identity / binding / safety gate remains satisfied
~~~

若不存在足够 residual opportunity，H2 的正确处置是 NOT_NEEDED_NO_ASSOCIATIVE_OPPORTUNITY，不是失败，也不为了进入实验而制造第二轮。

### 明确排除的解释

任何增益都不得来自：

- 更大的 Reader evidence token budget；
- 更多 hydrated candidates 或 retrieval calls；
- case ID、gold answer、literal quote、专用 synonym 或 magic boost；
- sealed 结果后的 Prompt、seed、Top-k 或 trigger 调整；
- eval-owned simplified retrieval；
- system failure 被计为 semantic abstention；
- Qwen self-judge 被包装成官方 GPT-4o leaderboard 等价结果。

Formation、Evolution、Accessibility 的直接合同是架构交付指标，不在结果后被提升为第三个主假设。

## 🏗️ 目标交付与依赖图

~~~mermaid
flowchart TB
    accTitle: GDPM staged development
    accDescr: Evaluation truth is repaired first, then the fast memory path and raw-preserving lifecycle are completed before an optional associative slow path and final validation.

    master_gate{Master activates goal?}
    b0[Repair evaluation truth]
    b1[Build fast memory convergence]
    b2[Integrate formation and evolution]
    opportunity{Residual opportunity exists?}
    b3[Build bounded associative path]
    no_slow[Keep slow path off]
    b4[Integrate and validate]

    master_gate -->|Yes| b0
    b0 --> b1
    b1 --> b2
    b2 --> opportunity
    opportunity -->|Yes| b3
    opportunity -->|No| no_slow
    b3 --> b4
    no_slow --> b4

    classDef gate_style fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#713f12
    classDef build_style fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    classDef hold_style fill:#f3f4f6,stroke:#6b7280,stroke-width:2px,color:#1f2937
    classDef final_style fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d

    class master_gate,opportunity gate_style
    class b0,b1,b2,b3 build_style
    class no_slow hold_style
    class b4 final_style
~~~

### 复用而非重建

| 已有资产 | 本 Goal 的用法 |
| --- | --- |
| EvidenceRecord、ContentBlob、source identity | Raw source of record |
| ClaimVersion、ClaimHead、OpenIssue | 唯一 Canonical State |
| OperationProposal、StewardDecision、Canonical Procedure | 唯一受治理写链 |
| SQL live governance、Canonical Gate | 权限与撤销判定 |
| official FTS / Dense / adjacency / Canonical acquisition | 候选生成，不在 eval 重写 |
| RequirementState、DecisionEngine scaffold | 收敛为 ordinary / strict 两个 profile |
| MD/MF Formation bundle 与 sidecar | 改为真实增量、可观测 funnel |
| vLLM Qwen endpoints | 可替换的 Reader、Judge 和语义策略后端 |

### 最小新增对象

只新增或收敛以下 query-local / sidecar 合同：

~~~text
QueryTaskContract
CognitiveWorkspaceV01
GroundedAnswerSpanBinding
EvidenceSetSelection
AssociativeBranchLedger
AccessibilityProjection
AttentionThreadProjection
Raw / admitted / reader-visible traces
~~~

新类型只有在跨进程、持久化或 authority 边界时才需要独立 envelope。普通应用函数之间不为“以后可能使用”增加多层 DTO。

## ⚙️ 五个工作块

### B0 — ML-EVAL-00：恢复评测真实性

目标：先让每个 context、trace 和 token 都代表真实输入，再进行任何语义 effect。

必须实现：

- 在 LongMemEval adapter、CandidateEnvelope、EvidenceReferenceNote 和 Context 分组中贯通原始 subject / session / turn identity；
- 禁止不同真实 session 的 adjacency 拼接；
- Context 使用 whole-unit、rank-first admission，不切断 atomic turn/window；
- 使用真实 Qwen tokenizer 与 chat template 计算 evidence ceiling；
- 保存 raw retrieval、admitted evidence、reader-visible 三层 trace；
- 将 timeout、lease、serialization、model unavailable、hydration failure 与 semantic abstention 分开；
- 旧 R4 context 只保留为 diagnostic artifact，不 resume、不覆盖。

最小验证：

~~~text
SessionIdentityIntegrity                 = 1.0
CrossSourceSessionAdjacencyExpansion     = 0
ReaderVisibleTraceExactness              = 1.0
ContextSerializationReplayEquivalence    = 1.0
SystemFailureAsSemanticAbstention         = 0
ReaderCallsDuringContextPreflight         = 0
~~~

执行楼梯：

1. known failure fixtures；
2. 24-case outcome-blind、metadata-stratified context-only canary；
3. 单独授权后重建 128-case untreated baseline 与 first-loss map。

协议或实现失败进入 repair iteration，不终止 GDPM。B0 未通过时，不进入 Answer/Judge 或 treatment。

### B1 — Fast Memory 与 EvidenceSet 收敛

目标：用最简单的产品同构路径解决普通回忆和多 evidence role 组合。

必须实现：

- 在现有 MemoryQueryIR 上补齐正交的 answer intent、operator、source role、evidence topology、temporal contract、output type 与 proof obligation；
- 允许 N-best semantic proposals，但 Runtime 负责 type-check 与可执行性；
- 创建 query-local CognitiveWorkspace，不创建第二套持久 Memory State；
- ordinary lane 使用 GroundedAnswerSpanBinding 与 LookupReadiness；
- strict lane 使用 TypedRequirementBinding、StrictSufficiency 和唯一 COMPLETE owner；
- strict operator 只读取 AcceptedBinding，不再直接读取 raw candidates；
- 用 official Raw FTS、Dense、Canonical 与真实 adjacency 做小 quota union、identity dedup、RRF；
- EvidenceSet selector 优化 requirement-role coverage，而不是单条 Top-k；
- 保留 deterministic exact / Canonical fast path，模型不可用时仍可运行。

必须重放：

~~~text
dad/sister vs uncle/niece relation hard negatives
DG-25 Wrong COMPLETE cases
DG-26 correct-case displacement
DG-28 seven opportunity groups
ordinary assistant-source lookup
multi-operand and multi-session cases
COUNT proof-gap cases
~~~

进入 128-case effect 前，24-case canary 必须证明：

- known relation hard negatives 不再 READY / COMPLETE；
- correct baseline evidence 不因新 selector 被挤出；
- system、Context 与 Reader errors 为独立分母；
- candidate、hydration、token 与 call ceilings matched。

B1 的主要对比是 Hybrid vs MiLA-Fast-Raw；B2 完成后才形成含 eligible Formed lane 的 MiLA-Fast，并进入 GDPM-H1 的最终对比。不得添加 case-shaped query enum、synonym 表或扩大 K 来补单例。

### B2 — Raw-preserving Formation 与 Evolution Bridge

目标：让 Formation 真正成为 query 前形成、可增量消费的 memory substrate，而不是运行时几乎总走 Raw fallback 的标签。

必须实现：

- FormationArtifactEnvelope 具有 producer、source spans、snapshot、watermark、policy、version、status 与 supersession lineage；
- ingest 继续同步保存 Raw Evidence，Formation 失败不阻塞 Evidence；
- Episode、mention、entity/event identity、occurrence time、state assertion 和 state transition 按模块增量构建；
- assistant 内容可以提供 episode context，但不能静默形成 user state；
- formed projection 过期时标记 PARTIAL / STALE 并自动保留 Raw fallback；
- source Evidence revoke 后立即阻断 derived artifact 读取，并触发 projection rebuild；
- Formation candidate 只有经既有 OperationProposal → StewardDecision → Canonical Procedure 才能影响 Canonical State；
- 不自动 promotion profile、preference、AttentionThread 或 accessibility。

Formation funnel 统一记录：

~~~text
EvidenceEligible
→ ArtifactEmitted
→ SpanGrounded
→ IdentityOrTimeResolved
→ QueryMatched
→ Selected
→ BindingContributed
~~~

直接门只检查真正的表示质量：

~~~text
RawSpanCoverage
EpisodeBoundaryF1
IdentityPairwiseF1
EventIdentityF1
OccurrenceTimeAccuracy
StateAssertionPrecisionAndRecall
TransitionRelationAccuracy
RevocationPropagation
DeterministicReplay
~~~

下游比较固定为 MiLA-Fast-Raw vs MiLA-Fast。若 direct gate 通过但 downstream 没有增益，保留可重建 sidecar、保持产品 OFF，并继续 B4 的 read-path 结论；不得通过增加抽取对象或自动 promotion 挽救效果。

### B3 — 受控联想、Accessibility 与 Thread Resume

进入条件必须同时成立：

~~~text
MiLA-Fast 后仍有 unresolved requirement
fresh observation 提供了新 semantic cue
存在未执行的 admissible official action
official oracle 显示该 action 可恢复缺失 role
~~~

若条件不成立，本块以 NOT_NEEDED_NO_ASSOCIATIVE_OPPORTUNITY 完成。

#### B3-A：Bounded associative effect

进入后必须实现：

- Familiarity probe 只使用可校准的 exact match、channel agreement、role coverage、rank margin、ambiguity、conflict 与 repeat signals；
- Runtime 枚举合法动作，模型只诊断 state、排序 action 或生成 action 内 cue；
- 每个 eligible case 最多一个模型策略调用、一个额外 official action；
- AssociativeBranchLedger 记录 parent、trigger、target role、action、observation 与 disposition；
- 新 Evidence 后完整重算 Binding、Workspace 和 readiness；

一个 action 没有产生 role coverage gain 时，不进入第二轮。只有独立 successor 重新证明 second-round opportunity 才可扩展。

主要指标：

~~~text
UsefulAssociativeJumpRate
FalseAssociationRate
JumpLoopRate
RoleCoverageGainPerJump
NewRegionRate
IncrementalCostPerUsefulBinding
~~~

#### B3-B：Observation-only lifecycle shadows

Accessibility 与 Thread Resume 不由 GDPM-H2 获得产品资格。第一版只交付 default-OFF、observation-only shadow：

- Accessibility 只观察 ranking、prefetch 与 hot/cold projection 的潜在变化，不能改变 truth、permission、retention 或实际 Context；
- AttentionThread 只保存可回到 Raw Evidence 的 noncanonical resume projection；
- Focus / Explore / Resume 只作为显式产品模式合同，不根据用户行为推断临床状态；
- 直接报告 ThreadResumeAccuracy、AccessibilityReactivationRate 与错误 thread 激活，不进入 H2 主效应。

B3-B 的 shadow 交付不阻塞 B3-A terminal，也不能因 H2 PASS 自动启用。

### B4 — 产品同构集成、LongMemEval 与发布决策

目标：在同一 OpenWorker → MCP → Runtime 路径中确认开发交付，不建立 eval-owned MiLA 行为。

必须完成：

- Experimental feature flags 默认 OFF；
- exact / Canonical / simple hybrid deterministic fallback 在 vLLM outage 时可用；
- model、retrieval、Context 和 Formation 没有 Canonical DML 权限；
- revocation、cross-scope、stale projection、model outage 与 deletion cascade 负控；
- Context / answer / judge 使用同一可重放 identity；
- Runtime / Schema 继续标记 0.1.x CANDIDATE / EXPERIMENTAL。

验证顺序：

~~~text
targeted fixtures
→ cross-scope / revocation / malicious-memory / model-outage safety core
→ 24-case canary
→ 128-case development effect
→ 24-case real-use negative-control suite
→ 500-case LongMemEval confirmation when separately authorized
→ repeat the safety core before release decision
~~~

真实使用 suite 固定覆盖 Topic Jump、Interrupted Work、Remote Cue、False Association、Temporary Constraint、Evolving State、Deletion Cascade、Model Outage、Cross-scope Identity、No-memory-needed、Jumpy Multi-thread 与 Malicious Memory。

最终只形成 CANARY_ELIGIBLE 或 KEEP_FLAGS_OFF 建议；不自动修改产品默认开关。

## 🔄 失败、修复与继续开发

本 Goal 不把第一次失败当作终态。失败首先按“是否有状态或输出逃逸”分类：

| 失败类型 | 处置 | 是否停止整个 Goal |
| --- | --- | --- |
| Infrastructure | 修复 lease、timeout、服务或资源；仅在代码、配置、模型和 snapshot byte-identical 时恢复失败 cells | 否 |
| Protocol / implementation | 修复 identity、schema、offset、timezone、token accounting；当前 attempt 受影响 cells 失效，以新 identity 重跑 | 否 |
| Semantic correctness in repair-dev | 找到 requirement 与 first-loss owner，只在 targeted fixtures / repair-dev 做通用机制修复 | 否 |
| Semantic miss in sealed 24/128/500 effect | 形成该 branch 的真实负结果；不得在原 sealed set 调修 | 否 |
| Method no gain | 保留真实负结果，关闭该可选 treatment，继续更简单路径 | 否 |
| No opportunity | 标记 NOT_NEEDED，不人为制造 treatment | 否 |
| 任一六项硬不变量逃逸 | 当前 attempt 全部无效、禁止评分和 checkpoint 复用；修复后以新 attempt 重放安全负控 | 冻结当前 attempt |
| Evidence 损坏、权限/撤销泄漏、跨 scope 泄漏或未授权 Canonical mutation | 冻结整个活动 run，人工确认恢复边界 | 是 |

有效 sealed effect 中出现 Wrong COMPLETE、false Binding 或 correct-case regression 是 method failure，不能改标为 protocol repair。若它来自可选 branch，拒绝该 branch 后可以继续更简单的安全路径；若它存在于最终候选路径，则不得 PASS。

合法 repair loop：

~~~text
failure
→ classify one root cause
→ identify one owner and affected invariant
→ make the smallest generalized repair
→ run targeted positive + negative fixtures
→ run one context-only canary
→ create a fresh attempt identity
→ resume byte-identical infrastructure cells or rerun every behavior-affected cell
~~~

规则：

- transport failure 最多一次 identical retry；语义或 schema invalidity 不自动重试；
- 成功 cells 只有在代码、配置、模型、tokenizer、template、snapshot 和行为 byte-identical 的纯基础设施恢复中才复用；
- identity、schema、token accounting、语义代码或配置变化时，所有受影响 cells 必须重跑，不能混合新旧实现形成一个 effect；
- 同一通用根因连续三次有实质 repair 仍无改善时，park 该 branch、执行简化设计 review，其他 blocks 继续；
- sealed effect miss 后不修改同一数据重跑；修复只能在 repair-dev 完成，再用新 sealed set；
- 每个实质根因只写一条 repair-log，后续验证更新同一条 disposition。

### 防止单例特判

任何修复必须同时满足：

1. 不读取 case ID、gold answer、gold span 或 treatment outcome；
2. 可表述为 identity、schema、type、role、time、decision boundary 或通用 ranking 特征；
3. 至少通过两个结构不同的正例和一个反例或变异 fixture；
4. 对 entity rename、paraphrase、session permutation 或 role-swap hard negative 至少有一项不变性证明；
5. 不通过扩大 K、token、模型调用或候选数掩盖错误；
6. 不在 evaluation 层重写产品 retrieval、Binding 或 Context。

单个 case 可以定位根因，不能批准一条产品规则。

## 🧪 精简实验策略与计算资源

### 三个 baseline family

| Family | 定义 | 作用 |
| --- | --- | --- |
| Lexical | turn / local-window BM25 | 最小 sparse reference |
| Hybrid | BM25 + Dense，小 quota、dedup、RRF | GDPM-H1 的确认性对照 |
| MiLA-Fast | Hybrid + Raw/Canonical/eligible Formed + EvidenceSet + grounded readiness | 主 fast treatment 与 GDPM-H2 对照 |

MiLA-Dual 是 MiLA-Fast 加一次 bounded associative action 的 treatment，不是第四个 baseline family。Dense-only、adjacency-only、Formation-off 只作为 24/128-case mechanism ablation，不进入全量 baseline 笛卡尔积。

### 评估楼梯

| 层级 | 用途 | 允许调整 |
| --- | --- | --- |
| Targeted fixtures | 修 implementation 和通用语义合同 | 可以修代码，不能加 case rule |
| 24-case canary | 验证 delivery、Context、资源与负控 | 只修 protocol / infra |
| 128-case development effect | 估计机制与 first-loss 分布 | 不按中期 accuracy 调参 |
| 500-case confirmation | 检验 H1/H2 | 不修改方法、预算、Prompt、K 或 trigger |

24-case 按 metadata outcome-blind 分层，覆盖 1、2、3–6 gold sessions、answerable/abstention、query capability、长短 context 与 relation hard negatives。它不是 label-free；可以用结构 metadata，不能用系统成败或 treatment opportunity 选样。

24-case manifest 嵌套于 128，128 再嵌套于 500。只有代码、配置、模型、tokenizer、template、预算和 snapshot identity 完全相同且无行为变化时，已完成 cells 才能直接晋级复用；任何行为变化都使受影响 arm 的旧 cells 失效，无关且 byte-identical 的 baseline 才可保留。

### Matched ceilings

所有 arms 固定：

~~~text
same Evidence snapshot
same access policy
same exact Qwen tokenizer and chat template
same max raw candidates per channel
same fused / hydrated / admitted unit ceilings
same Reader evidence-token ceiling
same answer reserve
same timeout and retry policy
same Reader and Judge identities
~~~

主轨使用 4096 evidence tokens；1024 只作为 MiLA-Fast / MiLA-Dual 的效率压力轨，不建立 512/2048 人工二分。Official-style capacity 可作为单独外部参照，不与主轨混合。

每层报告：

~~~text
scanned
→ retrieval occurrences
→ unique evidence candidates
→ hydrated
→ governance admitted
→ EvidenceSet selected
→ Reader visible
→ valid Binding
→ ready / complete
→ answer
~~~

### 并发计划

执行前做一次只读 capability probe，然后冻结物理并发：

- stateless retrieval、packing、scoring 使用至多 16-way；
- PostgreSQL / worker lane 使用 4 个隔离进程，每进程 1 个 worker，避免共享 lease 争抢；
- vLLM Answer 与 Judge 分时运行，各从 8 个 in-flight 开始；
- 发生 429、OOM 或持续超时只允许 8→4→2 的资源下调，不因 accuracy 调整并发；
- answer 全部封存后才打开 Judge window；
- 每个 case × arm 是一个 exactly-once logical cell，并在完成时 checkpoint；
- 并发和 resume 不增加 logical attempt、Provider call 或 failure denominator。

本地 Qwen Judge 输出指标命名为 QwenJudgeAccuracy。它遵循 LongMemEval answer/judge 分离思路，但不声称与官方 GPT-4o leaderboard 等价。

### 核心指标

主指标：

~~~text
ValidSemanticBindingRecall
ReaderVisibleRequirementRoleCoverage
QwenJudgeAccuracy
~~~

安全与正确性：

~~~text
AcceptedReferenceIntegrity
SemanticBindingPrecision
Wrong COMPLETE
CorrectCaseRegression
CrossScopeLeak
RevokedEvidenceLeak
CanonicalMutationFromReadPath
~~~

效率：

~~~text
ContextSuccessRate
P50 / P95 query latency
tokens per case
retrieval / model calls
hydrated and visible units
CostPerCorrectAnswer
CostPerUsefulBinding
FormationCostPerEvidence
ProjectionBuildLagP95
~~~

LongMemEval 结果必须同时报告全体 intention-to-treat、answerable、abstention、multi-session、temporal、knowledge-update 和 no-memory-needed slices。Subgroup 只能解释主结果，不能救活失败的总体假设。

## 🪶 减少防御性编程与审计负担

### 编码规则

1. 只在 trust boundary、authority boundary、持久化和外部模型边界验证；纯内部函数不重复验证同一对象。
2. 一项状态或决定只有一个 owner；不得再建平行 QueryIR、Binding、Sufficiency 或 Canonical writer。
3. 没有两个真实实现前，不为假设中的未来 backend 创建接口层级。
4. 新配置只有在存在两个合理值且会被实验比较时才加入；否则使用清晰常量。
5. 新 reason code 只有在会改变 Runtime 行为或修复路由时才创建。
6. 优先直接、短小、typed 的纵向实现；不为一次实验建立通用 workflow engine。
7. 产品和 evaluation 复用同一个 Acquisition、Binding、Context 编译器；eval 只负责 case mapping、调度和 scoring。
8. 删除重复路径应在行为等价证明后单独进行，不与 effect treatment 混在同一变更中。

### 分层测试

| 时点 | 必跑 | 不必跑 |
| --- | --- | --- |
| 每次编辑 | touched unit / contract、edited-file Ruff / mypy | 全仓库、PostgreSQL、安全 suite |
| repair canary 前 | 相关 component suite、已知 regression | 无关历史 DG 全套 |
| block terminal 前 | 本 block targeted + 直接上下游 integration | 未触及的 public/API/schema 门 |
| B4 / release review | Runtime 全量、相关 PostgreSQL/security/E2E | formal holdout，除非单独授权 |

只有变更 PostgreSQL、security、public MCP、删除、Canonical transaction 或 frozen architecture 边界时，才运行对应的重型门禁和独立审查。

### 最小制品

每个 claim-bearing 有效 effect 最多保留：

~~~text
run-lock.json
results.json
terminal.json
trace-bundle/        only for exact B0/B4 replay; partitioned or content-addressed
repair-log.jsonl    only when a material repair occurred
~~~

run-lock 绑定 Goal、Master authority snapshot、代码/配置、dataset/case manifest、budget、model/tokenizer/template。results 保存聚合指标与有界 per-case machine rows。trace-bundle 只在 B0/B4 保存每 cell 的 raw/admitted/reader-visible trace、精确序列化 Context、answer/judge identity 与 typed failure，不拆成逐阶段 receipt。terminal 只保存结论、边界和输入输出 digest。

禁止默认生成：

~~~text
per-stage receipts
transitive source manifests
deliverable indexes
duplicate runbooks
repeated reviewer or witness loops
one failure file per cell
status document rewrite after every attempt
~~~

独立 reviewer 只在 authority/Schema/frozen architecture 变化、formal holdout 或 release decision 时需要。MANIFEST 只登记制品，不承担执行授权。

### 文档与状态更新

- repair iteration 只写 repair-log，不同步改写所有 Master、Goal、AGENTS 和 runbook；
- block terminal 时一次性同步相关局部 Goal；
- 整个 GDPM terminal 或正式激活/接管时才更新 MILA-ML-MASTER 与 AGENTS；
- 已封存的历史 failure、terminal 和 contexts 永不覆盖。

## ✅ 完成条件与终态路由

### Block 完成

- [ ] B0 建立真实 identity、Context 与 untreated baseline；
- [ ] B1 建立 MiLA-Fast、grounded Binding、EvidenceSet 与唯一 readiness/COMPLETE owner；
- [ ] B2 建立增量 Raw-preserving Formation、freshness/revocation 与 Evolution bridge；
- [ ] B3-A 完成 MiLA-Dual，或形成合法 NOT_NEEDED / PARKED 分支结论；B3-B observation-only shadow 独立处置；
- [ ] B4 完成产品同构集成、授权范围内的 LongMemEval 和真实使用负控；
- [ ] 所有未进入功能保持 default OFF；
- [ ] Runtime / Schema 继续保持 CANDIDATE / EXPERIMENTAL；
- [ ] formal holdout 保持未使用，除非另有显式授权。

### Branch 结果不是 Program 失败

| 分支结果 | 处置 |
| --- | --- |
| Formation direct 失败 | 保持 Raw path，repair 或 park Formation；继续 Fast read |
| Formation direct 通过但无 downstream gain | sidecar 可保留，产品 OFF；不增加抽取复杂度 |
| associative opportunity 不存在 | B3 = NOT_NEEDED；simple architecture 成立 |
| associative effect 无 gain | B3 = PARKED_NO_GENERALIZED_GAIN；Fast path 继续 |
| Reader 不消费更完整 Evidence | 路由 Reader boundary，不回退 retrieval |
| temporal proof 未闭合 | 路由 deterministic proof lane，不生成更多 cue |

### Program terminal

终态按实现事实决定：

| 条件 | Terminal |
| --- | --- |
| B0、B1、B2、B4 完成；GDPM-H1 获支持；B3 无机会或无增益 | PASS_GDPM_LIFECYCLE_SIMPLE |
| B0～B4 完成；GDPM-H1 与 GDPM-H2 均获支持 | PASS_GDPM_DUAL_PROCESS_MEMORY |
| B0～B4 在 128-case development scope 完成，但 500 未获授权 | PARTIAL_GDPM_128_SUPPORTED_AWAITING_CONFIRMATION |
| Read path 完成，Formation 因标签或 exposure 不可估计 | PARTIAL_GDPM_READ_PATH_FORMATION_UNPROVEN |
| 500-case 中 Fast 与 optional lifecycle treatments 均无通用增益，但安全边界成立 | PARKED_GDPM_NO_GENERALIZED_EFFECT |
| 仅在 24/128 development scope 无效，尚未进入 500 | PARKED_GDPM_NO_DEVELOPMENT_EFFECT |
| 最终候选仍有 Wrong COMPLETE、correct-case regression、permission/revocation leak、Evidence 损坏、跨 scope 泄漏或未授权 Canonical mutation | FAIL_GDPM_AUTHORITY_OR_DATA_SAFETY |

若 500-case 未获授权，两个 PASS terminal 均不可达；最多产生 PARTIAL_GDPM_128_SUPPORTED_AWAITING_CONFIRMATION、其他 scope-limited PARTIAL/PARKED 或 development-complete 局部结论。

### Release decision

Goal terminal 与产品发布分离：

~~~text
method terminal:
  pass / partial / parked / fail

product decision:
  KEEP_FLAGS_OFF
  CANARY_ELIGIBLE
  REJECT_CANDIDATE
~~~

CANARY_ELIGIBLE 只表示可进入独立产品 canary，不等于 default-on、Schema freeze、Production-ready 或 formal holdout pass。

## 📎 关联文档与权威事实

- [受治理双过程 Memory 架构设计](./MiLAi_受治理双过程Memory架构设计_20260831.md)
- [LongMemEval 全切片审计与架构 rebase](./MiLAi_LongMemEval全切片审计与Memory架构重构设计_20260831.md)
- [Memory Lifecycle 项目级架构](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)
- [Memory Lifecycle 执行 Master](./MiLAi_Memory_Lifecycle_总_GOALS.md)
- [ML-R02 predecessor Goal](./MiLAi_ML-R02_统一MemoryLifecycle架构收敛与LongMemEval验证_GOALS.md)
- [ML-R02 8×4 terminal](./var/ml_r02/ml-r02-20260831-004/terminal.json)
- [全代码结构与 Memory Lifecycle 对齐报告](./MiLAi_全代码结构与MemoryLifecycle实现对齐报告_20260831.md)
- [MiLAi Lean V1 实施合同](./MiLAi_Lean_V1_实施合同.md)

---

最终执行原则：

> 先修复观测真实性，再做简单而正确的 Memory；只有简单路径留下可证明缺口，才启用 Formation 或联想慢路径。失败先定位 owner、做最小通用修复并继续，只有权限、Evidence 或 Canonical State 真正受损时才停止整个运行。
