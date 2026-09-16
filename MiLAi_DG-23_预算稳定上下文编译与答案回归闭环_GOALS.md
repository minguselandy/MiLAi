# MiLAi DG-23：预算稳定上下文编译与答案回归闭环 Goal

> Goal ID：`DG-23`  
> 方法名：`Budget-Invariant Decision / Saturating Evidence Context`  
> 文档版本：`0.1.0 DRAFT FOR OWNER EXECUTION AUTHORIZATION`  
> 起草日期：`2026-08-29`（Asia/Shanghai）  
> 当前状态：`DOCUMENT READY / IMPLEMENTATION NOT STARTED`  
> 本次 Owner 授权：`生成 Goal 修复文档；不等于授权执行代码、调用 Reader、打开 formal holdout 或发布 Candidate`  
> 前置终态：`DG-22 = FAIL_SAFETY_OR_REGRESSION`  
> DG-22 已通过：`Reader conformance / Recall+Binding / Quality+PostgreSQL+Security`  
> DG-22 未通过：`Correct-case regression / Temporal COUNT completeness / Overall`  
> 本 Goal 主 lane：`CONTEXT COMPILATION + ANSWER REGRESSION CLOSURE`  
> Temporal COUNT：`CARRIED PARTIAL / OUT OF PRIMARY SCOPE / MUST NOT REGRESS`  
> 冻结基线：`architecture/v1.0/`，禁止原地修改  
> Candidate 默认：`OFF`  
> Formal holdout：`UNTOUCHED / NOT AUTHORIZED`  
> 默认禁止：`CASE-ID RUNTIME RULE / GOLD-AWARE PACKING / TOP-K INFLATION / BUDGET-DEPENDENT ACQUISITION / PER-BUDGET REBINDING / BUDGET-DEPENDENT READER SEED / ARBITRARY EVIDENCE PREFIX TRUNCATION / RETRY-TO-PASS`

---

# 0. Goal 决定

DG-23 是 DG-22 的窄 successor。它接受并保持 DG-22 的终态，不覆盖、重算或改判 DG-22 的历史收据。

DG-22 已经建立：

```text
Reader conformance                              PASS
Requirement-complete recall / Binding           PASS
Safe-oracle normalized recall                   0.80
Required evidence coverage @2048                19/23
Required evidence coverage @512                 18/23
Accepted Binding precision                      1.0
UsefulCandidateRate                             0.346153846
Additional acquisition calls @2048              6
Candidates hydrated @2048                       26
Wrong COMPLETE                                  0
Quality/PostgreSQL/Security                     PASS
```

但 DG-22 没有完成答案正确性闭环：

```text
Candidate EM @2048                              4/10
Candidate F1 @2048                              0.435504653
Candidate EM @512                               6/10
Candidate F1 @512                               0.633715799
Baseline-correct answer regression              1
Regression case                                 gpt4_88806d6e @2048
DG22 answer disposition                         FAIL_CORRECT_CASE_REGRESSION
DG22 overall disposition                        FAIL_SAFETY_OR_REGRESSION
```

该失败不能继续解释为“召回不足”，也不能通过扩大 Top-k、调 Prompt、换 seed 或增加 Reader retry 修复。现有证据定位到预算与执行链耦合：

```text
token budget
→ budget-specific selected source set
→ budget-specific body allocation/truncation
→ budget-specific Reader seed
→ different Reader-visible semantic input
→ 512 correct / 2048 regressed
```

DG-23 的唯一主目标是：

> **让 Context presentation budget 只约束“已经完成的证据决策如何呈现”，不得改变 acquisition、Binding、RequirementState、Sufficiency 或 operator；当较小预算已经容纳全部必要语义单元时，更大预算不得自动填入无 requirement gain 的噪声，并必须产生相同的 Reader 语义输入。**

形式化链路：

```text
one governed candidate snapshot
→ one Evidence Gate result
→ one Binding / RequirementState / Sufficiency result
→ one immutable ReaderEvidencePlan
→ zero or more budget renders
→ one matched Reader contract
```

禁止继续执行：

```text
budget B1 → retrieval/binding/context path B1
budget B2 → retrieval/binding/context path B2
```

## 0.1 本 Goal 中“预算稳定”的定义

预算稳定不等于声称 LLM 在任意更长上下文上天然单调。DG-23 只建立 Runtime 可以控制的合同：

```text
Decision invariance
  acquisition、Gate、Binding、RequirementState、Sufficiency、operator
  不随 Reader presentation budget 改变

Atomic evidence integrity
  required binding span、derived result、conflict side、status 与 provenance
  不允许任意 prefix token 截断

Nested selection
  对同一 ReaderEvidencePlan，B_small < B_large 时：
  selected_units(B_small) 是 selected_units(B_large) 的稳定有序子集，
  或 B_small 返回 typed BUDGET_INFEASIBLE

Semantic saturation
  一旦全部必要语义单元已经装入，增加 budget 不得继续填充
  对当前 requirement 无增益的 topic-similar Evidence

Reader identity stability
  相同 Reader-visible context + contract + case + replicate
  只能对应一个 provider identity；sampling seed 不包含 budget 或 arm
```

## 0.2 Primary claims、supporting claims 与 anti-claims

| ID | Claim | Minimum convincing evidence |
| --- | --- | --- |
| C1 Primary | Presentation budget 可以从 acquisition 和 deterministic decision 中完全解耦 | 同一 case 的所有 diagnostic budgets 具有相同 candidate snapshot、Gate、Binding、RequirementState、Sufficiency 与 operator digest；BudgetDecisionLeakage=`0/N` |
| C2 Primary | Requirement-protected、atomic、saturation-aware Context 可以关闭 DG-22 的 2048 correct-case regression，而不牺牲 recall/Binding/safety | `gpt4_88806d6e@2048` 修复；全部历史正确病例 regression=`0`；coverage/precision/calls/hydration 不回归；Wrong COMPLETE=`0` |
| C3 Supporting | 产品预算应由可用模型窗口和最小安全呈现成本计算，而不是把 512/2048 固化成产品分支 | label-free `MinimumSafePresentationBudget` 分布；`B_ref` 可复算；adaptive 与 reference lane 非劣；512/2048 仅作为 legacy diagnostics |
| C4 Measurement | 相同语义计划的多预算评测必须共享同一 sampling seed，且 retrieval/Binding 只执行一次 | seed identity 不含 budget/arm；每 case acquisition execution=`1`；budget ladder 只执行本地 render |
| AC1 Anti-claim | 改善不能来自扩大 Top-k、增加 acquisition calls、改变 Reader/prompt/model/scorer、换 seed、重复调用或删除 gold-conflicting distractor | frozen controls；zero retry；same seed；call/hydration ceilings；runtime input 不含 case ID/gold |
| AC2 Anti-claim | DG-23 不证明 LLM 对任意更长上下文普遍单调，也不证明 temporal COUNT、formal LongMemEval、Production 或 Schema freeze 已完成 | explicit claim boundary；temporal carried partial；holdout untouched；candidate off |

## 0.3 Successor 边界

DG-22 以下 lane 作为 floor 继承，不在 DG-23 中重新“争取通过”：

```text
Reader conformance                 PASS_READER_CONFORMANCE
Recall / Binding                   PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION
Quality / PostgreSQL / Security    PASS_DG22_QUALITY_POSTGRESQL_SECURITY
Candidate default                  false
Formal holdout consumed            false
Architecture v1 changed            false
Public MCP schema changed          false
Database schema changed            false
```

DG-23 不负责新建 event projection，不把 source observed time 冒充 event time，不把两个 unresolved COUNT case 强判 COMPLETE。Temporal lane 只做非回归：

```text
opened COUNT OperatorReady         0（可保持 partial）
opened COUNT Wrong COMPLETE        0（不可回归）
time-axis substitution             0
```

## 0.4 授权矩阵

只有 owner 明确要求“执行 DG-23 Goal”后，才进入 S0。

| 变更 | 本文预定义 | 执行 DG-23 后是否还需额外授权 |
| --- | --- | --- |
| 内部 `ReaderEvidencePlan` / budget renderer / audit receipt | 是 | 否；不得扩大 public schema |
| `MemoryContextCompiler` 内部 plan/render 分离 | 是 | 否；public method contract 保持兼容 |
| 将 `max_context_tokens` 明确为 presentation ceiling | 是 | 否；请求字段保持不变 |
| acquisition candidate cap 与 context budget 解耦 | 是 | 否；不得增加冻结 call/hydration ceiling |
| eval seed identity 去除 budget/arm | 是 | 否；Reader contract 其他部分冻结 |
| DG23 label-free diagnostic budget ladder | 是 | 否；不进入产品配置 |
| Reader 调用 | 条件允许 | 仅在 S0–S6 全部通过后进入 S7；无 retry |
| Reader prompt/model/temperature/top-p/output schema/scorer change | 否 | 本 Goal 禁止 |
| public MCP request/response schema change | 否 | 必须退出本 Goal并取得单独授权 |
| PostgreSQL migration | 否 | 本 Goal禁止；若证明必需则终止并请求授权 |
| temporal event projection | 否 | 本 Goal禁止 |
| formal holdout | 否 | 必须单独授权；默认 0 case |
| Candidate default-on / Production release | 否 | 本 Goal禁止 |

---

# 1. 权威事实基线

## 1.1 规范优先级

发生冲突时按以下顺序解释：

1. `architecture/v1.0/` frozen bundle；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. executable Runtime 与真实 PostgreSQL tests；
5. DG-22 S10/S9/S8/S7 sealed receipts、products、scores 与 manifests；
6. DG-22 Goal；
7. 本 Goal；
8. runbook、README、注释与命名。

必须继续保持：

```text
EvidenceRecord != ClaimVersion
projection/search/context/model cannot raise truth or authority
permission/retention/revoke unknown fail closed
Candidate cannot directly obtain completion authority
Sufficiency and operator remain deterministic
Reader consumes governed data; Reader does not decide authority
all authority-bearing answers remain traceable
```

## 1.2 绑定输入与 SHA-256

| Artifact | SHA-256 | 用途 |
| --- | --- | --- |
| `architecture/v1.0/architecture_manifest.json` | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` | frozen architecture identity |
| `MiLAi_Lean_V1_实施合同.md` | `395a443da282f69a56ae5ea29f0dac07a65da12a697534e5c650c9893f8ae3ba` | implementation contract |
| `MiLAi_DG-22_证据召回准确性与答案正确性闭环_GOALS.md` | `7ee8b2c74cfaa1d40cd24c5f38bd0fd2c105c3888109ad3a4f7992305cdf9d69` | predecessor Goal |
| DG22 S10 terminal receipt | `2671583f8a11c97cbc462a48b15faaf9b41df4bf083dddcb422ec548677fae6e` | authoritative predecessor terminal |
| DG22 S8 answer score run 002 | `8358486fba6e7d38281b6509bc30d659e70cdb3709c48ddb6e5f246f38bf2452` | regression identity and answer metrics |
| DG22 S8 sealed contexts run 002 | `bb5231b51ddfcdab4f363db1ecc5cd1ad64cb0141076cdd851c19198b2ebeb12` | frozen Reader inputs |
| DG22 S8 sealed Reader product run 002 | `fd6a73e49fedfa58a61c0fc164daad4ec58aef576769ccc5c89297ffafbf2aca` | exact affected outputs |

以上制品只读。DG-23 必须使用新的 `run_id`、`var/dg23/`、failure index、source manifest、artifact manifest 和 terminal receipt。

## 1.3 DG-22 终态机器事实

```text
full_success                                      false
reader_disposition                               PASS_READER_CONFORMANCE
recall_binding_disposition                       PASS_REQUIREMENT_COMPLETE_RECALL_PRECISION
temporal_disposition                             PARTIAL_EVENT_POINT_ONLY_COUNT_UNRESOLVED
answer_disposition                               FAIL_CORRECT_CASE_REGRESSION
overall_disposition                              FAIL_SAFETY_OR_REGRESSION

safe_oracle_normalized_recall                    0.80
required_evidence_coverage_2048                  19/23
required_evidence_coverage_512                   18/23
accepted_binding_precision                       1.0
useful_candidate_rate                            0.34615384615384615
additional_acquisition_calls_2048                6
candidates_hydrated_2048                         26

automatic_retries                                0
canonical_mutations                              0
case_id_or_gold_runtime_inputs                   0
provider_controller_calls                       0
time_axis_substitutions                          0
wrong_complete                                   0
```

## 1.4 预算混杂的代码级事实

DG-22 evaluation packer 当前执行：

```text
unique refs cap                                  8
body allocation                                  remaining // remaining refs
body handling                                    tokenizer prefix truncation
baseline refs                                    inherited per budget
new refs order                                   before baseline refs
sampling seed identity                           includes token_budget
```

涉及位置：

```text
evals/dg22/mediator.py::_pack_context
evals/dg22/mediator.py::_candidate_record
evals/dg14/provider.py::matched_seed
scripts/run_dg22_s8_answer_correctness.py
```

因此 512/2048 比较同时改变：

```text
source membership
source order
per-source visible span
total context
sampling seed
```

它不是单因素 Context budget 消融。

## 1.5 唯一回归病例

`gpt4_88806d6e` 的 sealed Reader product 显示：

| Cell | Selected refs | Context tokens | Answer | Correct |
| --- | ---: | ---: | --- | --- |
| DG22 candidate @512 | 3 | 394 | `Tom` | yes |
| DG22 candidate @2048 | 8 | 1682 | `Mark and Sarah` | no |

这支持以下窄结论：

> 当前 2048 lane 引入或放大了与目标 requirement 无增益的上下文，并改变了 Reader-visible evidence distribution；它不支持“更多 evidence 天然更准确”或“512 天然优于 2048”。

## 1.6 参考实现审计边界

本 Goal 使用以下本地代码事实作为设计参考，但不复制其产品合同：

| Project | Control mechanism | 与 DG23 的关系 |
| --- | --- | --- |
| ReFind | internal search Top-5、neighbor window ±2、最多 4 iterations、API top-k | action/result budget 与 Reader token budget 分离；没有固定 512/2048 双档 |
| Graphiti | `SearchConfig.limit=10`，按 graph object type 检索和 rerank | result-count control；没有 core Reader token packer |
| Mem0 | `top_k=20`，内部 `max(limit*4,60)` over-fetch，再 final top-k | candidate pool 与最终结果数分离；`maxLength=512` 仅是 reranker pair input |
| Hindsight | recall `max_tokens=4096`，search depth 使用独立 budget，并可 adaptive | 最接近 presentation ceiling，但不是固定双档 |
| LongMemEval V1 | `topk_context`；可用检索长度由 model window 减 generation/reserve 动态计算 | 支持 model-aware available budget |
| LongMemEval V2 | 高 memory-context ceiling；按完整 item prefix 截断 | 支持 whole-item integrity，不支持任意证据 prefix 截断 |
| OpenViking | query `limit=10`；Markdown parser 使用 512 min / 2048 max section | 512/2048 属 ingestion chunking，不是 query-time Reader 双档 |

结论：

```text
512/2048 = MiLAi historical evaluation arms
512/2048 != external architecture prior
512/2048 != product-optimal budget proof
```

## 1.7 产品代码冲突

| ID | Observed code | Conflict |
| --- | --- | --- |
| O23-01 | `MemoryResolveBudget.max_context_tokens` 同时影响 retrieval budget handling 与 final Context | presentation cap 泄漏到 decision path |
| O23-02 | `_context_candidate_budget()` 对 Evidence DTO 使用 `context_budget * 4` | 改变 Context budget 会改变 acquisition candidate allowance |
| O23-03 | `_apply_context_budget()` 可以在最终 `MemoryContextCompiler` 前过滤 accepted/results | budget 可能改变后续可见 decision input |
| O23-04 | `MemoryContextCompiler.compile()` 在一个方法内完成 view、排序、required reserve、fit、render | 无法封存 budget-independent semantic plan |
| O23-05 | optional window 使用 `_fit_window()` | 同一 evidence unit 可能因 budget 看到不同 prefix |
| O23-06 | integration `prepare_turn_window_prefetch()` 使用 `_item_token_budgets()` 按相对相关性切分正文 | 增大预算可能改变每项文本而不仅是增加完整 unit |
| O23-07 | DG22 使用 eval-only `_pack_context()` 而非正式 `MemoryContextCompiler` | matched answer 没有完整测到产品 Context path |
| O23-08 | `matched_seed(run_id, case_id, token_budget)` | 跨预算不是 same-seed matched comparison |
| O23-09 | 512/2048 在 DG14–DG22 被固定为评测合同 | 历史可比性被误当成产品配置理由 |

---

# 2. 问题与冲突登记

| Conflict ID | 当前冲突 | 必须采取的决定 |
| --- | --- | --- |
| C23-01 | Context budget 同时约束 acquisition 与 Reader presentation | 拆为 `AcquisitionBudget` 与 `PresentationBudget`；后者不得进入 acquisition plan/digest |
| C23-02 | 不同预算重新执行 Binding/Sufficiency | 每个 source snapshot 只生成一个 `DecisionSnapshot`；所有预算共享 |
| C23-03 | packer 以“填满预算”为目标 | budget 是 ceiling，不是 quota；达到 semantic saturation 后停止 |
| C23-04 | required span 可能被 token-prefix 截断 | required/derived/conflict/status unit 必须 atomic；装不下则 typed infeasible |
| C23-05 | optional evidence 没有 requirement gain 约束 | 只允许 `incremental_requirement_gain > 0`、conflict disambiguation 或 unresolved diagnosis unit 进入 optional queue |
| C23-06 | 预算增大可能替换或重排已有 evidence | 单一 stable order；small selection 必须是 large selection 的有序子集 |
| C23-07 | seed 包含 budget | sampling seed 只绑定 frozen seed namespace、case snapshot 与 replicate；不含 arm/budget |
| C23-08 | eval 自己实现 Context packing | DG23 eval 只能调用正式 plan/render service；实验层不得重写 packing |
| C23-09 | 2048 是主 Gate，但无最优依据 | 2048 降为 legacy diagnostic；主预算由 label-free minimum-safe distribution 推导 |
| C23-10 | “更多 Context 导致错答”可能诱发 case-specific 删除 | Runtime 禁止 case ID/gold/answer routing；只允许 requirement-local、type-safe 通用规则 |
| C23-11 | DG22 temporal partial 与 answer regression 混在 Overall | DG23 分 lane 封存；temporal 只做 safety non-regression，不阻止窄 Context lane PASS |
| C23-12 | exact tokenizer 与 Runtime estimator 可能不一致 | Runtime estimator 用于 preflight；Reader boundary exact tokenizer 为最终 ceiling authority；不一致 typed fail |

## 2.1 保持为正确行为

以下行为不得因“答案准确性修复”而削弱：

```text
Wrong COMPLETE = 0
accepted Binding precision = 1.0
governance Gate before Reader
canonical state and Evidence separation
permission/revoke/retention fail closed
query-time event time does not become canonical truth
COUNT unresolved remains PARTIAL
one-pass official acquisition
zero Provider controller calls
zero automatic retry
candidate default false
formal holdout untouched
```

## 2.2 禁止的修复

```text
按 gpt4_88806d6e 或任何 case ID 分支
按 gold answer、gold source refs 或 scorer label packing
删除包含 “Mark and Sarah” 等具体词的证据
为 2048 单独改 prompt、temperature、top-p 或 answer schema
让 512/2048 使用不同 acquisition policy
增加 Top-k、candidate cap、acquisition calls 或 hydration ceiling
多轮 search / retry / majority vote / best-of-N
损坏 JSON 修补后计为成功
放宽 Binding、Sufficiency、scope、authority 或 temporal Gate
把 source observed time 当 event occurrence time
把 eval-only packer 包装成“product faithful”
用更大 budget 掩盖 required evidence packing loss
为了单调性把全部较大 budget 强行截成固定 512
```

---

# 3. 目标架构合同

## 3.1 唯一执行链

```text
MemoryResolveRequest
→ QueryPlan / MemoryQueryIR
→ AcquisitionPlan                    [AcquisitionBudget only]
→ official channel execution
→ governed CandidateSnapshot
→ Evidence Gate
→ Span / Interpretation / Binding
→ RequirementState
→ SufficiencyDecision
→ OperatorResult
→ DecisionSnapshot                   [immutable, budget-independent]
→ ReaderEvidencePlan                 [immutable semantic units, budget-independent]
→ ContextBudgetEnvelope              [Reader boundary]
→ ContextRenderer                    [presentation only]
→ ReaderReadiness
→ fixed Reader
```

禁止：

```text
PresentationBudget
→ AcquisitionPlan
→ CandidateSnapshot
→ Binding
→ Sufficiency
```

## 3.2 三类预算

### A. `AcquisitionBudget`

```yaml
AcquisitionBudget:
  channel_calls:
  max_candidates_scanned:
  max_candidates_hydrated:
  max_extra_passes:
  latency_ceiling_ms:
```

来源：capability policy、requirement 类型与 frozen development ceiling。

不得来源于：

```text
Reader max_context_tokens
Reader model window
512/2048 legacy arm
answer label
```

### B. `DecisionBudget`

DG-23 不引入可调 DecisionBudget。Gate、Binding、RequirementState、Sufficiency 与 operator 必须消费同一 governed candidate snapshot；如果 deterministic computation 本身资源不可用，返回 typed failure，不能用 Reader budget 隐式减少输入。

### C. `PresentationBudget`

```yaml
ContextBudgetEnvelope:
  requested_cap:
  model_context_limit:
  fixed_system_prompt_tokens:
  query_tokens:
  answer_reserve_tokens:
  safety_margin_tokens:
  available_memory_tokens:
  reader_tokenizer_identity:
```

计算：

```text
available_memory_tokens
= min(
    requested_cap,
    model_context_limit
    - fixed_system_prompt_tokens
    - query_tokens
    - answer_reserve_tokens
    - safety_margin_tokens
  )
```

若调用边界无法提供 model/tokenizer identity，则保持当前 public cap，但必须在 receipt 中标为：

```text
BUDGET_SOURCE = CALLER_CAP_ONLY
```

不得静默猜测更大的窗口。

## 3.3 `DecisionSnapshot`

内部不可变对象：

```yaml
DecisionSnapshot:
  schema_version: decision-snapshot-v0.1
  source_snapshot_digest:
  query_ir_digest:
  acquisition_plan_digest:
  candidate_snapshot_digest:
  gate_digest:
  binding_digest:
  requirement_state_digest:
  sufficiency_digest:
  operator_result_digest:
  accepted_evidence_ids: []
  rejected_evidence_summary: {}
  required_requirement_ids: []
  unresolved_requirement_ids: []
```

约束：

```text
presentation budget 不进入任何 digest material
同一 source/query/capability/policy → 一个 DecisionSnapshot
预算 ladder 不得重新获取、重新 Gate、重新 Binding 或重新执行 operator
```

## 3.4 `ReaderEvidencePlan`

内部对象，不扩大 public MCP schema：

```yaml
ReaderEvidencePlan:
  schema_version: reader-evidence-plan-v0.1
  plan_digest:
  decision_snapshot_digest:
  compiler_version:
  stable_order_version:

  protected_units:
    - unit_id:
      kind:
        STATUS
        DERIVED_RESULT
        REQUIRED_BINDING
        CONFLICT_SIDE
        OPEN_ISSUE
        PROVENANCE
      requirement_ids: []
      evidence_ids: []
      source_turn_refs: []
      text:
      exact_span: true
      atomic: true
      estimated_tokens:

  conditional_units:
    - unit_id:
      requirement_ids: []
      incremental_requirement_gain:
      rejection_diagnostic_gain:
      evidence_ids: []
      source_turn_refs: []
      text:
      atomic: true
      estimated_tokens:

  omitted_units:
    - unit_id:
      reason:
```

`plan_digest` 不包含 presentation budget。

## 3.5 Protected unit 合同

必须优先且 atomic 呈现：

1. `Sufficiency status` 与 unresolved reason；
2. 合法 `derived_result` 的 operator/value/unit；
3. 每个 required requirement 的 accepted binding span；
4. contested requirement 的两侧或多侧；
5. OpenIssue 对 Reader 必需的安全提示；
6. Reader 可理解的 speaker、observed/event time 与 provenance alias；
7. authority/scope 所需的最小安全说明。

禁止：

```text
required span 任意 token prefix
只保留冲突一侧
derived value 没有 operand/provenance
把 opaque UUID/hash 放进 Reader 正文
为装入 budget 删除 PARTIAL/CONTESTED/UNRESOLVED 状态
```

如果 protected closure 装不下：

```text
ReaderReadiness = BUDGET_INFEASIBLE
SufficiencyDecision 保持原值
Reader 不得被调用
```

## 3.6 Conditional unit 与 semantic saturation

conditional unit 只有满足至少一项时才可进入计划：

```text
新增未覆盖 requirement 的合法 candidate evidence
补齐一个 accepted binding 的必要局部上下文
提供 conflict disambiguation 的另一侧
提供 unresolved / rejection 原因的可解释诊断
满足 query 明示要求的 provenance/source role
```

以下不是 gain：

```text
topic overlap
同一事实重复表述
仅 source/session 不同但没有新 requirement coverage
更长的 assistant explanation
包含答案实体但角色或时态不适用
```

一旦：

```text
all protected units selected
AND no conditional unit has positive admissible gain
```

则：

```text
semantic_saturated = true
larger budget does not add Reader-visible text
reader_context_digest remains identical
```

预算是 ceiling，不是必须填满的 quota。

## 3.7 Nested render 合同

对同一 `ReaderEvidencePlan P`，若 `B1 < B2`：

```text
U(P,B1) ⊆ U(P,B2)
relative_order(U(P,B1), U(P,B2)) unchanged
protected unit text byte-identical
no selected unit is replaced by another unit
```

允许：

- B1 跳过一个装不下的 optional atomic unit，继续考虑更短的后续 optional unit；
- B2 包含该 unit；
- B1 因 protected closure 装不下而 typed infeasible。

不允许：

- 为 B1/B2 重新计算 relevance；
- 按剩余预算重新均分所有 evidence 正文；
- B2 改写 B1 已选 unit 的 span；
- B2 因加入新 evidence 而改变已选 unit 顺序。

## 3.8 最小安全预算与 reference budget

定义：

```text
B_safe(case)
= exact Reader-token cost of fixed boundary + protected closure
```

对于 operator-ready case：

```text
B_ready(case)
= minimum budget rendering all required bindings + valid operator result
```

对于 PARTIAL/CONTESTED case：

```text
B_safe(case)
= minimum budget rendering status + accepted evidence + unresolved/conflict reason
```

label-free opened-dev reference：

```text
B_present(case)
= B_ready(case), when the case is operator-ready
= B_safe(case), otherwise

B_ref = max(B_present(case) for all frozen opened-dev cases)
```

约束：

```text
B_ref <= public max_context_tokens ceiling (8000)
B_ref 在 labels 打开前计算并封存
B_ref 保留 exact integer，不为了好看向 512/1024/2048 对齐
```

若任一 case 的 `B_safe > 8000`：

```text
PARKED_CONTEXT_CONTRACT_INFEASIBLE
```

不得扩大 public ceiling 或静默截断。

## 3.9 Diagnostic budget ladder

仅在 label-free、zero-Reader Context audit 中运行：

```text
128 / 256 / 512 / 1024 / 2048 / 4096 / 8000
```

用途：

```text
验证 nestedness
定位 B_safe / saturation point
绘制 coverage-token curve
验证 acquisition/decision digest invariance
```

不得：

```text
从 ladder 选择 opened-dev 最佳 answer budget
将这些值写成 Runtime case policy
在每个 budget 重新执行 acquisition/Binding
```

512/2048 只保留为 legacy comparison cells。

## 3.10 Reader seed 与调用 identity

sampling seed：

```text
seed = H(
  frozen_seed_namespace,
  case_source_snapshot_digest,
  replicate_index
)
```

明确排除：

```text
arm
presentation budget
context length
answer label
attempt number
```

logical request ID 可以包含 arm/budget/replicate 用于账本，但不能影响 sampling seed。

如果以下 identity 全部相同：

```text
reader_context_digest
reader_contract_digest
sampling_seed
generation_settings_digest
```

必须复用同一个 sealed Reader output，不得重复调用 Provider。此复用是 identity checkpoint，不是 retry。

## 3.11 Token accounting

```text
Runtime estimator              planning / safe preflight
Reader exact tokenizer         final presentation ceiling authority
```

receipt 必须同时保存：

```yaml
estimated_tokens:
exact_reader_tokens:
reader_tokenizer_path_or_id:
reader_tokenizer_sha256:
budget_ceiling:
accounting_delta:
```

如果 exact count 超出 ceiling：

```text
TOKEN_ACCOUNTING_MISMATCH
Reader not called
```

禁止 send-time 临时裁剪。

## 3.12 Product-faithful execution

DG23 evaluation 只能调用正式：

```text
RetrievalRepository / official acquisition
→ Runtime Evidence Gate
→ semantic Binding / Sufficiency / operator
→ MemoryContextCompiler plan
→ MemoryContextCompiler render
```

实验层只允许：

```text
构造 case
选择 diagnostic budget
触发 candidate flag
封存 trace/product
在 seal 后打开 scorer labels
```

实验层禁止实现：

```text
ranking
fusion
Binding
required-source selection
per-item token allocation
body truncation
Context ordering
semantic saturation
```

DG22 `_pack_context()` 只能作为 frozen baseline replay，不得成为 DG23 candidate path。

## 3.13 Typed failure

至少支持以下 reason code：

```text
BUDGET_DEPENDENT_ACQUISITION
DECISION_SNAPSHOT_DRIFT
READER_PLAN_DRIFT
CONTEXT_BUDGET_INFEASIBLE_REQUIRED_UNITS
CONTEXT_NESTEDNESS_VIOLATION
CONTEXT_ORDER_VIOLATION
ATOMIC_UNIT_TRUNCATED
SEMANTIC_SATURATION_VIOLATION
TOKEN_ACCOUNTING_MISMATCH
READER_SEED_BUDGET_DEPENDENT
EVAL_PRODUCT_PATH_DIVERGENCE
READER_INVALID_JSON
CORRECT_CASE_REGRESSION
```

---

# 4. Work Packages

## DG23-WP00 — Baseline、identity 与 denominator freeze

交付：

- 绑定 §1.2 全部 SHA-256；
- 冻结 10-case opened-dev order、source snapshot、Reader/provider/prompt/generation/scorer；
- 冻结 DG22 recall/Binding/quality floors；
- 冻结 regression case 与历史正确病例列表，仅供 scorer/evaluation；
- 明确 temporal COUNT 不进入 DG23 primary success denominator；
- 建立 `var/dg23/failure-index.jsonl` append-only ledger。

硬门：

```text
artifact identity mismatch                       0
formal holdout consumed                          false
labels loaded during baseline freeze             false
architecture manifest mismatch                   0
```

## DG23-WP01 — Budget causality audit

零 Provider、零 Reader。

对 DG22 10 cases × 512/2048，输出：

```text
candidate snapshot digest
Gate digest
Binding digest
RequirementState digest
Sufficiency digest
operator digest
selected source refs and order
per-source visible span digest
Reader context digest
sampling seed
```

必须复现：

```text
gpt4_88806d6e @512 selected refs = 3
gpt4_88806d6e @2048 selected refs = 8
answers = Tom / Mark and Sarah
```

本阶段只建立 first divergence，不修复。

## DG23-WP02 — DecisionSnapshot 与 budget separation

主要代码范围：

```text
runtime/src/milai/application/retrieval.py
runtime/src/milai/application/memory_resolve.py
runtime/src/milai/application/memory_context.py
runtime/src/milai/domain/memory_context.py
runtime/src/milai/domain/memory_resolve.py
```

允许新增内部模块，例如：

```text
runtime/src/milai/domain/reader_evidence_plan.py
runtime/src/milai/application/reader_evidence_plan.py
```

实现：

- acquisition budget 不再由 `max_context_tokens` 派生；
- `_context_candidate_budget()` 不得使用 presentation budget 扩大/缩小 candidate allowance；
- `_apply_context_budget()` 不得改变 Gate/Binding/Sufficiency/operator 输入；
- 生成 budget-independent `DecisionSnapshot`；
- public MCP request/response schema 不变；
- 无 PostgreSQL migration。

## DG23-WP03 — ReaderEvidencePlan 与 atomic renderer

实现：

- `MemoryContextCompiler` 内部拆分 `plan()` 与 `render()`；
- 保持现有 `compile()` 兼容入口，内部调用 plan/render；
- protected/conditional unit 分类；
- stable ordering；
- whole-unit selection；
- typed infeasible；
- exact required span；
- semantic saturation；
- plan/render audit receipt。

禁止把 DG22 eval packer 复制进 Runtime。

## DG23-WP04 — Seed、tokenizer 与 Reader boundary

实现：

- 新 matched seed 不含 arm/budget；
- exact input identity checkpoint；
- exact Reader tokenizer preflight；
- budget envelope receipt；
- invalid JSON fail-closed；
- no retry；
- Reader prompt/model/generation/output schema 不变。

## DG23-WP05 — Synthetic contract matrix

零 Provider、零 Reader、无 opened-dev labels。

至少覆盖：

```text
single required value
multi-requirement evidence set
derived operator with two operands
preference current-state update
contested/conflict both sides
speaker/role mismatch
temporal unresolved PARTIAL
one oversized required unit
one oversized optional unit followed by short useful unit
duplicate topic-similar distractors
same evidence in permuted repository order
budget just below / equal / above B_safe
```

每个 synthetic case 运行完整 diagnostic ladder，但 acquisition/decision 只执行一次。

## DG23-WP06 — Product-faithful opened-dev Context ladder

零 Provider、零 Reader；先封存 product，再打开 labels。

执行：

```text
10 cases
× one official acquisition/decision execution
× 7 local renders
```

不得执行：

```text
10 × 7 acquisitions
10 × 7 bindings
```

输出：

```text
B_safe(case)
B_ready(case) when applicable
B_ref
saturation budget
selected unit ladder
required-source survival
context digest ladder
exact token count
nestedness/order violations
```

## DG23-WP07 — Matched Reader answer closure

只有 WP00–WP06 全部通过后进入。

Reader arms：

```text
A_DG22_FROZEN_FINAL_CONTEXT
B_DG23_BUDGET_INVARIANT_CONTEXT
```

预算 modes：

```text
LEGACY_512          characterization
LEGACY_2048         required regression closure
REFERENCE_B_REF     primary correctness
ADAPTIVE_RUNTIME    primary efficiency/correctness
```

如果不同 mode 的 DG23 `reader_context_digest` 相同，按 §3.10 复用同一个 sealed Reader identity。

预注册 replicates：

```text
3 fixed sampling seeds per unique Reader input identity
seed formula excludes arm and budget
0 retry
```

labels 只在所有 Reader products seal 后打开。

DG22 历史 answer 只用于冻结 scoring floor 和回归病例，不得当作新 matched baseline 的 Reader output 复用。只有
下列四项 identity 完全一致时才能按 §3.10 复用：

```text
reader_context_digest
reader_contract_digest
sampling_seed
generation_settings_digest
```

DG23 使用新的 frozen seed namespace，因此历史 DG22 answer 通常不满足 exact identity；在这种情况下，
`A_DG22_FROZEN_FINAL_CONTEXT` 也必须在新 matched seed 下执行一次 fresh Reader call，不得用历史文本充当新输出。

## DG23-WP08 — Quality、PostgreSQL、Security 与 rollback

运行：

```text
targeted DG23 unit
context/retrieval regression
DG20/DG21/DG22 evaluation regression
contract
strict mypy
Ruff
real PostgreSQL integration
real PostgreSQL security
architecture validate/lock
temporary database cleanup
```

未修改数据库 schema 仍必须跑真实 PostgreSQL 回归，验证 budget refactor 没有改变 scope/permission/tenant boundary。

## DG23-WP09 — Terminal seal

生成唯一 terminal receipt，引用 S0–S8 receipt、failure index、source manifest、artifact manifest 和 runbook。

terminal builder 不得重新运行实验或重新解释失败；只允许验证并汇总已封存制品。

---

# 5. Stage 执行顺序

```text
S0 Baseline and Denominator Freeze
→ S1 Budget Causality Audit
→ S2 Decision/Presentation Separation
→ S3 Atomic Saturating Context Compiler
→ S4 Seed and Token Boundary Conformance
→ S5 Synthetic Budget Invariance Matrix
→ S6 Product-faithful Opened-dev Context Ladder
→ S7 Matched Reader Answer Closure
→ S8 Quality/PostgreSQL/Security
→ S9 Terminal Seal
```

## S0 — Freeze

Entry：Goal 获 owner 执行授权。

Exit：所有 predecessor identity、denominator、Reader contract、seed namespace 和禁止项冻结。

## S1 — Causality audit

Entry：S0 PASS。

Exit：first divergence 被机器化定位；不得仅写自然语言结论。

若无法复现 DG22 regression identity：

```text
PARKED_BASELINE_IDENTITY_NOT_REPRODUCIBLE
```

## S2 — Decision separation

Entry：S1 PASS。

Exit：相同 case/source/policy 在全部 diagnostic budgets 下产生同一 `DecisionSnapshot`。

S2 失败不得进入 Context tuning。

## S3 — Context compiler

Entry：S2 PASS。

Exit：plan/render、atomic unit、nestedness、saturation、typed infeasible 全部有 unit/contract tests。

## S4 — Reader boundary

Entry：S3 PASS。

Exit：seed budget independence、exact tokenizer preflight 和 exact identity reuse 通过；仍不调用 opened-dev Reader。

## S5 — Synthetic matrix

Entry：S4 PASS。

Exit：所有 synthetic mutation 和 property gates 通过；Runtime 无 case-specific branch。

## S6 — Opened-dev Context ladder

Entry：S5 PASS。

Exit：label-free product sealed；B_ref 冻结；之后才允许 scorer 加载 required source labels。

若 acquisition/decision digest 随 budget 变化，立即停止，不允许进入 Reader。

## S7 — Matched Reader

Entry：S6 全部 structural、safety、mediator gates PASS。

Exit：所有 unique Reader identities 完成一次调用或合法 exact-identity reuse；products seal 后评分。

无 latency repeats，直到 correctness seal。

## S8 — Quality

Entry：S7 terminal answer score 已封存，无论 PASS/FAIL 都运行质量回归。

Exit：代码质量、真实 PostgreSQL、security、cleanup、architecture lock 全部有 receipt。

## S9 — Terminal

Entry：S0–S8 receipt 齐全。

Exit：按 §13 唯一终态封存；不得以 tests PASS 覆盖 answer failure。

---

# 6. Claim-driven experiment blocks

| Block | Claim | Runs | Priority | Stop/Go |
| --- | --- | --- | --- | --- |
| B1 Budget leakage audit | C1 | DG22 20 frozen cells，zero Reader | MUST | first divergence 可复算才 GO |
| B2 Decision invariance | C1/C4 | 10 opened-dev + synthetic × diagnostic ladder，one decision each | MUST | digest mismatch 任一即 STOP |
| B3 Atomic/saturation compiler | C2 | synthetic mutation/property matrix | MUST | truncation/nestedness/saturation violation 任一即 STOP |
| B4 Product Context mediator | C2/C3 | 10 cases × 7 renders，one acquisition each | MUST | coverage/safety/call floor 不回归才 GO |
| B5 Matched answer closure | C2 | two arms × budget modes × 3 seeds per unique identity | MUST | correct-case regression 任一即 FAIL |
| B6 Adaptive budget efficiency | C3 | B_ref vs adaptive, exact context/token identities | MUST | accuracy 非劣且 typed infeasible 正确 |
| B7 Broad budget curve | measurement only | label-free context curve | APPENDIX | 不用于选 opened-dev answer 最佳点 |
| B8 Temporal COUNT closure | none in DG23 | no new event projection | CUT | carried partial only |

## 6.1 最重要的 anti-confound

```text
same source snapshot
same QueryIR
same acquisition plan/capability/policy
same candidate snapshot
same Binding/Sufficiency/operator
same Reader contract
same sampling seed per replicate
only presentation renderer/mode differs
```

若上述任一项不同，对应 cell 不得进入“budget effect”比较。

---

# 7. Metrics

## 7.1 Decision invariance

```text
AcquisitionBudgetLeakageRate
= budget-varying cells with different acquisition_plan_digest / eligible cells

CandidateSnapshotDriftRate
= budget-varying cells with different candidate_snapshot_digest / eligible cells

BindingDriftRate
= budget-varying cells with different binding_digest / eligible cells

RequirementStateDriftRate
= budget-varying cells with different requirement_state_digest / eligible cells

SufficiencyDriftRate
= budget-varying cells with different sufficiency_digest / eligible cells

OperatorDriftRate
= budget-varying cells with different operator_result_digest / eligible cells
```

全部必须为 `0/N`。

## 7.2 Context structural correctness

```text
AtomicUnitTruncationRate
ContextNestednessViolationRate
ContextOrderViolationRate
ProtectedUnitLossRate
ConflictSideLossRate
RequiredEvidencePackingLossRate
SemanticSaturationViolationRate
TokenAccountingMismatchRate
ProductPathDivergenceRate
```

全部必须为 `0/N`。

## 7.3 Budget characterization

逐 case 报告：

```text
B_safe
B_ready if applicable
saturation_budget
requested_budget
available_budget
exact_reader_tokens
estimated_tokens
selected/omitted unit count
omission reasons
```

汇总：

```text
B_safe min / p50 / p95 / max
B_ref
mean and total exact Reader memory tokens
adaptive token delta vs legacy 2048
adaptive token delta vs B_ref
```

不报告“最佳 budget”而不带 development-only 限定。

## 7.4 Recall、Binding 与 safety floors

```text
SafeOracleNormalizedRecall
RequiredEvidenceCoverage
AcceptedBindingPrecision
UsefulCandidateRate
AdditionalAcquisitionCalls
CandidatesHydrated
WrongCOMPLETE
WrongScope
AuthorityViolation
Permission/Retention/RevokeViolation
TimeAxisSubstitution
CanonicalMutation
```

## 7.5 Reader correctness

```text
ValidJSONRate
ExactMatch
NormalizedF1
CorrectCaseRegressionCount
HistoricalRegressionCaseAccuracy
SaturatedContextAnswerMismatchCount
ReaderSeedBudgetDependenceRate
ExactIdentityDuplicateCallCount
```

`SaturatedContextAnswerMismatchCount` 只在 context digest、contract 和 seed 完全相同时定义；正常情况下这些 cells 应 exact-reuse，因此 mismatch 必须为 0。

## 7.6 效率

```text
official acquisition executions per case
additional acquisition calls
candidates scanned/hydrated
Binding evaluations
Context plan compilations
local budget renders
unique Reader input identities
Reader provider calls
exact-identity reuses
prompt/context/completion tokens
retrieval/context/Reader latency
```

预算 ladder 的本地 render 不得被计成 acquisition call 或 Reader call。

---

# 8. Hard Gates

## 8.1 不可降低的安全门

```text
Wrong COMPLETE                                 = 0/N
Wrong scope                                    = 0/N
Authority violation                            = 0/N
Permission/retention/revoke violation          = 0/N
Time-axis substitution                         = 0/N
Canonical mutation                             = 0/N
Runtime case-ID/gold routing                   = 0/N
Automatic retry                                = 0/N
Provider controller calls                      = 0/N
Formal holdout consumption                     = false
Candidate default                              = false
```

任一失败，DG23 不得 PASS。

## 8.2 Decision invariance 门

```text
AcquisitionBudgetLeakageRate                   = 0/N
CandidateSnapshotDriftRate                     = 0/N
BindingDriftRate                               = 0/N
RequirementStateDriftRate                      = 0/N
SufficiencyDriftRate                           = 0/N
OperatorDriftRate                              = 0/N
one acquisition/decision execution per case    = 100%
budget ladder local-render only                = 100%
```

## 8.3 Context compiler 门

```text
AtomicUnitTruncationRate                       = 0/N
ContextNestednessViolationRate                 = 0/N
ContextOrderViolationRate                      = 0/N
ProtectedUnitLossRate                          = 0/N
ConflictSideLossRate                           = 0/N
TokenAccountingMismatchRate                    = 0/N
ProductPathDivergenceRate                      = 0/N
Reader call on BUDGET_INFEASIBLE               = 0/N
B_ref                                           <= 8000
```

对于所有 saturated budgets：

```text
reader_context_digest identical                = 100%
selected unit sequence identical               = 100%
```

## 8.4 Recall/Binding 非回归门

在 `REFERENCE_B_REF`：

```text
SafeOracleNormalizedRecall                     >= 0.80
RequiredEvidenceCoverage                       >= 19/23
AcceptedBindingPrecision                       = 1.0
UsefulCandidateRate                            >= 0.34615384615384615
AdditionalAcquisitionCalls                     <= 6
CandidatesHydrated                             <= 26
Correct-case required source retention         = 100%
```

在 `LEGACY_512` 只做 stress characterization，但：

```text
RequiredEvidenceCoverage                       >= 18/23
Wrong COMPLETE                                 = 0/N
```

如果 512 低于某 case 的 `B_safe`，该 case 必须 typed infeasible，不得伪造 context-ready；coverage 分母和 infeasible count 分开报告。

## 8.5 Reader 门

```text
Reader contract drift                          = 0/N
Reader seed includes budget/arm                 = 0/N
Invalid JSON                                   = 0/N
Automatic retry                                = 0/N
ExactIdentityDuplicateCallCount                = 0/N
```

## 8.6 Answer 门

主门以 `REFERENCE_B_REF` 和 `ADAPTIVE_RUNTIME` 为准：

```text
CorrectCaseRegressionCount                     = 0 across every preregistered replicate
Historical regression case @2048               correct across every preregistered replicate
Candidate EM @B_ref                            >= 6/10
Candidate normalized F1 @B_ref                 >= 0.633715799
Adaptive EM                                    >= B_ref EM
Adaptive normalized F1                         >= B_ref F1 - 0.01
SaturatedContextAnswerMismatchCount            = 0/N
Wrong COMPLETE                                 = 0/N
```

`LEGACY_2048` 是必须关闭的历史回归 cell：

```text
gpt4_88806d6e answer                             = correct
baseline-correct regression                     = 0/N
```

`LEGACY_512` 保留报告，不用它选择产品预算；不得低于 DG22 candidate 的历史正确病例集合。

任何 aggregate EM/F1 提升都不能抵消一个 correct-case regression。

主指标固定使用全部 10 个 frozen opened-dev cases 作为分母。`BUDGET_INFEASIBLE` 在 answer 准确性中按
abstention / not-correct 计入，不得从 EM/F1 分母移除；可另报 readiness-stratified 结果，但只作次级诊断。

## 8.7 效率门

```text
AdditionalAcquisitionCalls                     <= 6
CandidatesHydrated                             <= 26
budget ladder acquisition multiplier            = 1.0x
hidden model calls                              = 0
Reader calls                                    = unique input identities only
adaptive exact context tokens                   <= B_ref exact context tokens per ready case
```

latency 只有在 correctness seal 后运行固定 repeats。没有 correctness 时不得用更低 latency 宣称成功。

## 8.8 质量门

```text
targeted DG23 unit                              PASS
context/retrieval regression                    PASS
DG20/DG21/DG22 evaluation regression            PASS
contract                                        PASS
strict mypy                                     PASS
Ruff                                            PASS
real PostgreSQL integration/security            PASS
temporary PostgreSQL cleanup                     PASS
architecture validate/lock                       PASS
```

---

# 9. Test Plan

## 9.1 Unit tests

至少新增：

```text
test_presentation_budget_does_not_change_acquisition_plan
test_presentation_budget_does_not_change_candidate_snapshot
test_presentation_budget_does_not_change_binding_or_sufficiency
test_required_units_are_atomic
test_conflict_sides_are_kept_together
test_budget_below_protected_closure_is_typed_infeasible
test_small_context_units_are_ordered_subset_of_large_context_units
test_saturated_context_is_byte_identical_across_larger_budgets
test_optional_oversized_unit_does_not_block_later_short_useful_unit
test_topic_similar_zero_gain_evidence_is_not_used_to_fill_budget
test_repository_permutation_does_not_change_plan_digest
test_reader_seed_excludes_arm_and_budget
test_exact_identity_is_called_once
test_exact_tokenizer_overflow_fails_before_reader
```

## 9.2 Property tests

随机生成：

```text
unit token costs
protected/conditional classifications
requirement gain vectors
budget monotone sequences
repository permutations
duplicate evidence
```

验证：

```text
nestedness
stable order
atomicity
digest determinism
saturation identity
typed infeasible boundary
```

Property test 不使用 opened-dev case ID 或 answers。

## 9.3 Contract tests

```text
public MCP schema unchanged
MemoryResolveBudget request compatibility
MemoryContext existing response compatibility
compile() compatibility wrapper
opaque Reader identity protection
Reader data/instruction boundary
receipt digest completeness
```

## 9.4 Evaluation tests

```text
DG23 denominator exactly 10 cases
diagnostic ladder exactly 7 budgets
one DecisionSnapshot per case/arm
labels absent before Context product seal
same seed across arms/budgets for one case/replicate
all Reader products sealed before scorer
historical regression cell present
formal holdout absent
```

## 9.5 Real PostgreSQL integration/security

覆盖：

```text
tenant isolation
scope narrowing
permission denial
retention/revoke filtering
same source snapshot across budget renders
no extra repository query per render
transaction cleanup
temporary database removal
```

## 9.6 Failure injection

```text
tokenizer unavailable
exact count exceeds estimated count
required atomic unit larger than cap
plan digest drift
candidate snapshot drift
Reader invalid JSON
Provider timeout
same identity accidental reissue
```

全部必须 typed、fail-closed、zero retry。

---

# 10. Failure Discipline

## 10.1 First-loss taxonomy

每个失败只标第一个权威 loss：

```text
SOURCE_SNAPSHOT
ACQUISITION
GATE
BINDING
REQUIREMENT_STATE
SUFFICIENCY
OPERATOR
READER_PLAN
PRESENTATION_BUDGET
TOKEN_ACCOUNTING
READER_CONTRACT
READER_SEMANTIC_ERROR
SCORING
```

## 10.2 Fresh run 与失败保留

- 每次修复使用新 run ID；
- 失败 receipt、trace、Reader raw response 与 ledger append-only 保留；
- 不覆盖 DG22 artifacts；
- 不删除失败以制造 clean manifest；
- 不把 retry 结果替换第一次结果；
- 相同 input identity 不允许第二次 Provider 调用。

## 10.3 立即停止条件

```text
architecture lock mismatch
public MCP schema drift
database migration required
formal holdout accessed
runtime case-ID/gold branch
budget-dependent acquisition/decision
Wrong COMPLETE > 0
scope/authority/permission violation > 0
atomic required unit silently truncated
Reader called after typed budget infeasible
Reader seed depends on budget/arm
```

## 10.4 Diagnosis budget

每个 stage 最多：

```text
one primary implementation hypothesis
one narrow repair after a reproducible failure
one fresh rerun
```

若同一 blocking condition 在连续三次 Goal turns 仍存在且不能安全推进，按持久 Goal 规则标记 blocked；不得无限换参数。

---

# 11. Rollback 与兼容

## 11.1 Feature boundary

DG23 candidate 默认关闭。建议内部 feature identity：

```text
budget_invariant_context_v0_1 = false
```

关闭后恢复 DG22/current product behavior，但不得删除 DG23 traces 或 failure receipts。

## 11.2 Schema

```text
public MCP migration           none
PostgreSQL migration           none
architecture/v1.0 mutation    none
```

内部对象通过 application/domain code 存在；如发现必须改变 public schema，终态为：

```text
NOT_ENTERED_SCHEMA_AUTH_REQUIRED
```

## 11.3 Reader

不修改：

```text
model
prompt
temperature/top-p
output schema
answer scorer
completion ceiling
```

只修正 matched seed identity 与输入 Context 编译。

## 11.4 Rollback trigger

任一情况立即关闭 candidate：

```text
correct-case regression
required evidence loss
accepted Binding precision < 1.0
Wrong COMPLETE
governance violation
context digest nondeterminism
budget-dependent decision
quality/security regression
```

---

# 12. Deliverables

最低交付清单：

1. DG23 S0 baseline freeze receipt；
2. budget causality audit；
3. affected-case first-divergence trace；
4. `DecisionSnapshot` internal contract；
5. `ReaderEvidencePlan` internal contract；
6. Context budget envelope contract；
7. atomic/saturation/nested renderer；
8. seed identity contract；
9. exact tokenizer accounting report；
10. synthetic mutation matrix；
11. property-test report；
12. opened-dev label-free Context ladder product；
13. B_safe/B_ref report；
14. product-path fidelity report；
15. mediator score；
16. sealed matched Reader product；
17. answer score；
18. correct-case regression report；
19. efficiency/token report；
20. quality receipt；
21. real PostgreSQL integration/security receipt；
22. append-only failure index；
23. source manifest；
24. artifact manifest；
25. rollback/runbook：`docs/runbooks/dg23-budget-invariant-context.md`；
26. S9 terminal receipt。

建议目录：

```text
evals/dg23/
scripts/run_dg23_*.py
tests/test_dg23_*.py
var/dg23/s0 ... var/dg23/s9
docs/runbooks/dg23-budget-invariant-context.md
```

---

# 13. Terminal Dispositions

## 13.1 Context/decision lane

### PASS

```text
PASS_BUDGET_INVARIANT_DECISION_AND_CONTEXT
```

仅当 §8.2–§8.3 全部通过。

### FAIL

```text
FAIL_BUDGET_DEPENDENT_DECISION
FAIL_CONTEXT_NESTEDNESS_OR_ATOMICITY
PARKED_CONTEXT_CONTRACT_INFEASIBLE
```

## 13.2 Recall/Binding lane

### PASS

```text
PASS_DG22_RECALL_BINDING_NON_REGRESSION
```

### FAIL

```text
FAIL_RECALL_BINDING_REGRESSION
```

DG23 不重新声明新的 recall 创新，只验证 refactor 没有破坏 DG22 PASS。

## 13.3 Answer lane

### PASS

```text
PASS_CORRECT_CASE_REGRESSION_CLOSURE
```

仅当 §8.5–§8.6 全部通过。

### FAIL/PARKED

```text
FAIL_CORRECT_CASE_REGRESSION
PARKED_READER_SEMANTIC_NON_MONOTONICITY
PARKED_READER_CONTRACT_UNAVAILABLE
```

Reader invalid JSON、timeout 或 Provider failure 不允许通过 retry 变成 PASS。

## 13.4 Temporal lane

固定允许：

```text
CARRIED_PARTIAL_EVENT_POINT_ONLY_COUNT_UNRESOLVED
```

只要 Wrong COMPLETE、time-axis substitution 与 temporal regression 为 0，它不阻止 DG23 窄 Goal PASS；但 terminal 必须明确 MiLA 总体仍有 temporal COUNT 未完成。

## 13.5 Overall terminal

### Full narrow success

```text
DG23 = PASS_BUDGET_STABLE_CONTEXT_ACCURACY
```

要求：

```text
Context/decision lane PASS
Recall/Binding non-regression PASS
Answer regression closure PASS
Safety PASS
Quality/PostgreSQL/Security PASS
Candidate default false
Formal holdout untouched
Architecture unchanged
```

这不是 Production PASS，也不是 MiLA 全系统 Full PASS。

### Structural success but answer failure

```text
DG23 = PARKED_READER_SEMANTIC_NON_MONOTONICITY
```

适用：decision/context structural gates 全部通过，但固定 Reader 仍产生正确病例回归。此时不得继续改 packing 以追单 case；必须单独研究 Reader evidence consumption。

### Decision/context failure

```text
DG23 = FAIL_BUDGET_DEPENDENT_DECISION
```

或：

```text
DG23 = PARKED_CONTEXT_CONTRACT_INFEASIBLE
```

### Safety/regression failure

```text
DG23 = FAIL_SAFETY_OR_REGRESSION
```

## 13.6 Claim boundary

允许表述：

> 在冻结的 synthetic 与 deidentified opened-development 协议上，DG23 将 presentation budget 从 acquisition、Binding、RequirementState、Sufficiency 与 operator 中解耦，并通过 requirement-protected atomic Context 与 semantic saturation 关闭了/未关闭 DG22 的已知 correct-case regression；结果仅适用于封存的 Runtime、Reader、数据和预算合同。

禁止表述：

```text
larger contexts are universally monotonic
512 or 2048 is the optimal product budget
MiLA memory accuracy is solved
temporal COUNT is solved
formal LongMemEval improvement
production ready
schema ready
architecture freeze update ready
```

---

# 14. 执行检查表

进入 S0 前：

- [ ] Owner 明确授权执行 DG23；
- [ ] DG22 artifacts 保持只读；
- [ ] formal holdout 未使用；
- [ ] candidate 默认关闭；
- [ ] 工作树用户修改已记录并保留。

进入 S2 前：

- [ ] regression first divergence 已机器复现；
- [ ] budget 改变的所有变量已列全；
- [ ] 不存在“只比较 context length”的虚假因果表述。

进入 S5 前：

- [ ] DecisionSnapshot budget-independent；
- [ ] protected units atomic；
- [ ] nestedness 与 saturation property tests 通过；
- [ ] seed 不含 budget/arm；
- [ ] product/eval path 相同。

进入 S6 前：

- [ ] synthetic matrix 全通过；
- [ ] no case-ID/gold runtime logic；
- [ ] no schema/migration；
- [ ] no Reader calls。

进入 S7 前：

- [ ] label-free Context product sealed；
- [ ] B_ref sealed；
- [ ] acquisition/decision drift 0/N；
- [ ] safety 0 violations；
- [ ] recall/Binding floors preserved；
- [ ] exact tokenizer preflight PASS。

进入 S9 前：

- [ ] Reader products sealed before labels；
- [ ] correct-case regression independently scored；
- [ ] failure receipts retained；
- [ ] quality/PostgreSQL/security complete；
- [ ] temporary databases removed；
- [ ] architecture manifest verified。

终态前：

- [ ] terminal status 与每个 lane 一致；
- [ ] temporal partial 未被隐藏；
- [ ] candidate default false；
- [ ] formal holdout untouched；
- [ ] source/artifact manifests 全部匹配；
- [ ] claim boundary 无扩大。

---

# 15. 最终原则

DG-23 的核心不是寻找新的固定 token 数，而是纠正预算在架构中的位置：

```text
Acquisition decides what evidence is reachable.
Binding decides what evidence is applicable.
Sufficiency decides whether requirements are complete.
Operator decides the deterministic result.
ReaderEvidencePlan decides what semantics must be shown.
PresentationBudget only decides whether that immutable plan can fit.
```

最关键的实现规则：

> **预算是上限，不是填充目标；必要语义已经完整时，更多预算不得自动带来更多噪声。**

最关键的实验规则：

> **跨预算比较必须共享同一 acquisition、同一 decision、同一 evidence plan 和同一 seed；否则测到的不是 budget effect。**

最关键的安全规则：

> **装不下必要证据时返回 typed infeasible，不截断事实、不删除冲突、不让 Reader 猜。**
