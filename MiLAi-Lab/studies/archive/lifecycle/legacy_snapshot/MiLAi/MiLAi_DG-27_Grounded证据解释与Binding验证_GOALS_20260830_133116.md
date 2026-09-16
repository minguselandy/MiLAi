---
document_id: MILA-DG27
version: "0.5.0"
status: READY_FOR_FRESH_S0
execution_order_authority: MILA-ML-MASTER
---

# MiLAi DG-27：Read-path Decision Boundary Repair Goal

> 文档版本：0.5.0 / ACTIVE LOCAL GOAL
> 日期：2026-08-30（Asia/Shanghai）
> 状态：READY FOR FRESH S0；既有 pre-execution run-lock 不得直接执行
> Program：[Program C Read Path / Recollection](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
> 共享基线：[DG-26～DG-30 自适应检索轻量开发基线](./MiLAi_DG-26-DG-30_轻量执行与审查基线.md)
> 必须结果：`PASS / DECISION_BOUNDARY_REPAIRED`
> 可选增益：`PASS / PROVISIONAL_INTERPRETATION_GAIN`
> 范围：只修 grounded interpretation、ProvisionalBinding、AcceptedBinding 与集中 COMPLETE 边界

---

# 1. 当前进度与迁移

当前已有：

```text
var/dg27/run-lock.json
scripts/run_dg27.py
```

但机器事实是：

```text
只有旧版 run-lock
没有 DG27 interpretation implementation
没有 model calls
没有 results.json
没有 terminal.json
```

旧 lock 强制“每 candidate 一个单一 proposal + 逐字段严格 validator”，并只消费 DG-26 R0 selected candidates。该合同仍把最终 Binding 约束提前压到解释层，不再执行。

处置：

```text
保留 var/dg27/run-lock.json 作为历史身份
不得覆盖或继续运行旧 lock
scripts/run_dg27.py 在适配 V02 前不得用于 effect run
V02 使用 var/dg27/v02/{run-lock,results,terminal}.json
```

这不是失败重跑，因为旧合同尚未产生模型输出或实验结果。

---

# 2. 目标

DG-27 同时解决两个已经分离的问题：

1. 建立允许多个语义假设、歧义和暂定关系的 `ProvisionalBinding`；
2. 把 AcceptedBinding 与 COMPLETE 的硬验证集中到唯一 Decision Boundary。

它不扩大 acquisition、不调用 Reader、不做 Canonical mutation。

---

# 3. Research Hypotheses

| Hypothesis | 最小证据 |
| --- | --- |
| DG27-H1 集中完成边界修复 DG-25 的错误 COMPLETE | 重放 DG-25 全部 16 个 Wrong COMPLETE occurrence 后，缺少 AcceptedBinding 的 requirement 均不得 COMPLETE；其他正确完成不回归 |
| DG27-H2 Provisional semantic interpretation 改善 Binding 决策 | 在 candidate 已存在的 interpretation-loss 病例中，减少已知 false accepted Binding，或恢复至少 1 个合法 Binding，且不把歧义候选直接提升为 AcceptedBinding |

DG27-H1 是必须通过的安全修复。DG27-H2 可以为负；DG27-H2 负结果不撤销已通过的 DG27-H1。

---

# 4. 新的解释合同

## 4.1 `SemanticInterpretationSetV02`

模型可以为一个 candidate 返回 0～3 个假设：

```yaml
candidate_id:
hypotheses:
  - relation: SUPPORT | CONTRADICT | UPDATE | CONTEXT_ONLY | IRRELEVANT
    grounded_spans: []
    normalized_subjects: []
    normalized_predicate:
    normalized_value:
    normalized_unit:
    event_time_hypothesis:
    confidence_feature:
ambiguity_reasons: []
```

允许：

```text
多个 entity/time/predicate 解释并存
无法确定时返回 AMBIGUOUS 或空 hypotheses
local context 支持代词和事件解释
模型修正 deterministic parser 的单一解释
```

模型 confidence 只是 feature，不是 authority。

## 4.2 `ProvisionalBindingV01`

```yaml
candidate_id:
requirement_id:
status: POSSIBLE | AMBIGUOUS | CONTRADICTORY | IRRELEVANT
supporting_interpretation_ids: []
unresolved_checks: []
```

ProvisionalBinding：

```text
可以进入 SemanticSearchWorkspace
可以成为下一轮检索 anchor
不计算 AcceptedBindingPrecision
不满足 Sufficiency
不产生 COMPLETE
```

## 4.3 集中 `DecisionBoundaryV02`

搜索停止后只执行一次最终验证：

```text
Gate 仍有效
grounded span/structured projection 可验证
requirement role/type/source/time/unit 合法
歧义和冲突已经解除
dedup identity 合法
```

然后才产生：

```text
AcceptedBinding
RequirementState
Sufficiency
Operator readiness
```

COMPLETE 必须要求每个 required role 有 AcceptedBinding。Proof satisfied 但 Binding 为空时必须保持：

```text
UNSATISFIED 或 COMPLETENESS_PROOF_MISSING
```

---

# 5. 实验设计

只运行四个决定性 arms：

| Arm | 内容 | 作用 |
| --- | --- | --- |
| D0 | DG-25 replay semantics | 复现已知错误，仅作历史对照 |
| D1 | deterministic interpretation + DecisionBoundaryV02 | 隔离完成边界修复 |
| D2 | model N-best interpretation + ProvisionalBinding + DecisionBoundaryV02 | 主 treatment |
| D3 | D2 但只保留 single-best hypothesis | 判断多假设是否必要 |

所有 arms 固定同一 admitted candidate pool、权限快照、requirements 和 scorer labels。D0 不进入产品 wiring。

不再强制 correct StateView 必须优于 shuffled-state 才允许语义解释；DG-26 已证明该测试不能代表当前主要瓶颈。若 D2 有增益但需要确认 observation 贡献，可把 query-only control 作为一次附加诊断，不阻塞 DG27-H1。

---

# 6. Core blocks

## DG27-B1 — Completion boundary repair

直接重放 DG-25：

```text
2 个无 MATCH 但 proof satisfied 的 requirements
8 个相关 arms
16 个 Wrong COMPLETE occurrences
```

验证 D1/D2/D3 均为 0 Wrong COMPLETE。

## DG27-B2 — Provisional interpretation

覆盖：

```text
DG-25 已知 false MATCH
DG-26 candidate-present but binding-missed group
event-time/source-time ambiguity
entity/predicate paraphrase
```

比较最终 AcceptedBinding，而不是要求 provisional candidates 全部精确。

## DG27-B3 — Efficiency and regression

记录：

```text
model calls
candidates interpreted
hypotheses per candidate
final validation calls
final correct-case regression
```

不为每个 candidate 生成 receipt。

---

# 7. 执行阶段

## S0 — Supersede / Freeze

写新的 `var/dg27/v02/run-lock.json`，显式引用旧 lock：

```yaml
supersedes:
  path: var/dg27/run-lock.json
  reason: PRE_EXECUTION_ARCHITECTURE_CORRECTION
```

冻结 D0 replay、admitted candidate pool、model、全局解释预算和主指标。

## S1 — Implement / Smoke

实现：

```text
SemanticInterpretationSetV02
ProvisionalBindingV01
DecisionBoundaryV02
trusted model adapter
```

只运行 touched tests、Unicode/offset smoke、known false-MATCH fixtures 和 Wrong-COMPLETE replay smoke。

## S2 — Matched effect

一次运行 D0–D3，写 `var/dg27/v02/results.json`。不调 Prompt、candidate pool、seed 或 validator 挽救结果。

## S3 — Targeted terminal

运行 DG27 targeted tests、直接 Binding/Sufficiency regressions、targeted mypy/Ruff，写 `var/dg27/v02/terminal.json`。

---

# 8. Metrics 与终态

主要：

```text
KnownFalseAcceptedBinding
AcceptedBindingPrecision
RequiredEvidenceCoverage
RecoveredValidBinding
AmbiguityPreservationRate
Wrong COMPLETE
OperatorReady
```

成本：

```text
model calls
interpreted candidates
provisional hypotheses
latency
```

终态：

| status | reason_code | 含义 |
| --- | --- | --- |
| PASS | DECISION_BOUNDARY_REPAIRED | DG27-H1 通过，DG27-H2 无独立增益 |
| PASS | PROVISIONAL_INTERPRETATION_GAIN | DG27-H1 通过且 D2 改善最终 Binding |
| FAIL | WRONG_COMPLETE_REMAINS | 集中完成边界仍错误 |
| FAIL | KNOWN_FALSE_BINDING_ACCEPTED | 已知 false candidate 被最终接受 |
| FAIL | FINAL_CORRECT_CASE_REGRESSION | 最终 Binding/Operator 退化 |
| PARKED | INTERPRETATION_MEDIATOR_ABSENT | DG27-H1 已修复，但没有可测试的 DG27-H2 病例 |

PASS 硬门：

```text
Wrong COMPLETE = 0
KnownFalseAcceptedBinding = 0
authority/canonical mutation = 0
final correct-case regression = 0
```

不对 CandidatePrecision 或 ProvisionalBindingPrecision 设置 1.0 硬门。

---

# 9. Rollback

```text
model interpretation flag OFF
DecisionBoundaryV02 可独立保留
旧 run-lock 与所有 V02 结果均保留
不把 provisional state 持久化为 canonical state
```

> DG-27 的修复目标不是让模型绕过 Binding，而是让模型在最终接受之前保留语义可能性，并让 Runtime 只在一个集中边界上作严格决定。
