---
document_id: MILA-DG27
version: "0.7.0"
status: TERMINAL_NEGATIVE_WRONG_COMPLETE_REMAINS
execution_order_authority: MILA-ML-MASTER
---

# MiLAi DG-27：Read-path Decision Boundary Repair Goal

> 文档版本：0.7.0 / TERMINAL LOCAL GOAL
> 日期：2026-08-30（Asia/Shanghai）
> 状态：V02 协议错误已修复；V03 有效 effect 仍 `FAIL / WRONG_COMPLETE_REMAINS`
> Program：[Program C Read Path / Recollection](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
> 共享基线：[DG-26～DG-30 自适应检索轻量开发基线](./MiLAi_DG-26-DG-30_轻量执行与审查基线.md)
> 必须结果：`PASS / DECISION_BOUNDARY_REPAIRED`
> 可选增益：`PASS / PROVISIONAL_INTERPRETATION_GAIN`
> 范围：只修 grounded interpretation、ProvisionalBinding、AcceptedBinding 与集中 COMPLETE 边界

---

# 1. 当前机器事实与 V03 处置

V03 权威终态为 `var/dg27/v03/attempt-004/terminal.json`（terminal digest `94273ada7ecacdf293aa7e1f27966e7f363ecce01a86b475b09d97591942a948`）。D1 仍有 1 个 Wrong COMPLETE，D2/D3 丢失 11 个基线正确组，因此 DG27-H1/H2 均未建立。本文后续 repair 步骤仅作历史方法记录，不再授权新 effect。

V02 已执行且不得改写：

```text
terminal: var/dg27/v02/terminal.json
sha256:  cc010fa788d5671179cb7f076b85468f9803cfd42ad3d17287c95839546cd477
status:  FAIL / SAFETY_OR_PROTOCOL
detail:  MODEL_OUTPUT_RUNTIME_VALIDATION_FAILED

violations:
  GROUNDED_SPAN_WIDTH_MISMATCH
  EVENT_TIME_TIMEZONE_MISSING
```

V02 在第一个模型输出后 fail-closed，没有重试，也没有 acquisition、Reader、Canonical mutation、authority violation 或 holdout 消耗。因此：

```text
V02 run disposition: ATTEMPT_FAILED_PROTOCOL
DG27-H1: NOT_ESTABLISHED_BY_MATCHED_EFFECT
DG27-H2: NOT_ESTABLISHED
Goal disposition: ACTIVE_REPAIR_ITERATION
```

这不是 treatment 负结果。模型被要求同时完成精确 Unicode/Python offset 算术和 timezone-aware datetime 合同，任一 hypothesis 不合法又会终止整批。V03 必须修这个通用边界，不能重放相同请求碰运气。

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

模型可以为一个 candidate 返回 0～3 个假设，但 V03 不再要求模型计算 source offsets：

```yaml
candidate_id:
hypotheses:
  - relation: SUPPORT | CONTRADICT | UPDATE | CONTEXT_ONLY | IRRELEVANT
    grounded_quotes: []
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

## 4.2 V03 trusted materialization

Runtime adapter 拥有 source text，由它完成可验证的机械处理：

```text
exact quote occurs once
  → adapter derives Python [start, end) offsets

quote absent or occurs more than once
  → reject this hypothesis as REJECTED_PROTOCOL
  → do not abort unrelated candidates/hypotheses

timezone supplied and valid
  → materialize EventTimeHypothesis

timezone absent and runtime has an explicit deterministic timezone context
  → runtime resolves it and records resolution provenance

timezone absent/ambiguous without deterministic context
  → event time = UNRESOLVED
  → preserve non-temporal semantic content
  → prohibit temporal AcceptedBinding
```

每个 hypothesis 的 disposition 仅能是：

```text
VALID
REJECTED_PROTOCOL
DOWNGRADED_UNRESOLVED
```

只有 top-level JSON 无法解析、request/candidate identity drift 或 source mapping 损坏才是 batch-fatal。结构化输出通过不代表 semantic materialization 必须全成功。

## 4.3 `ProvisionalBindingV01`

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

## 4.4 集中 `DecisionBoundaryV02`

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

# 7. V03 高效修复与实验阶段

## S0 — Offline reproduction and repair

1. 将 V02 的两类 violation 变成无 Provider 的固定 fixtures。
2. 实现 quote-to-offset trusted materialization、timezone unresolved downgrade 和 hypothesis-local disposition。
3. 受限地保存一份 raw response 与 digest，用于重现协议故障；不进入公开 artifact 或业务 state。
4. 只运行 touched unit/contract tests、DG27 direct regression、edited-file Ruff/mypy。

## S1 — One real canary

使用与 effect 相同的 model/tokenizer/template/schema，只运行 1 个预注册 canary：

```text
top-level schema parse succeeds
request/candidate identity unchanged
at least one hypothesis reaches a legal local disposition
no state escape or canonical mutation
```

transport 故障可进行 1 次 identical retry。schema/semantic invalidity 不得盲目重试；必须返回 S0 修通用合同。

## S2 — Superseding lock and matched effect

canary 合法后写 `var/dg27/v03/run-lock.json`，绑定 V02 terminal、D0 replay、admitted candidate pool、model identity、schema digest、global interpretation budget 和主指标。然后一次完成 D0–D3，写 `var/dg27/v03/results.json`。

并发策略：

```text
initial concurrency = 4
raise to 8 only when waiting = 0, KV cache < 0.5,
and rolling P95 <= 2 * canary latency
halve concurrency when any threshold fails
```

不调 Prompt、candidate pool、seed 或 validator 挽救结果。

## S3 — Score / reflect / terminal

未评分输出封存后再打开 scorer。运行 DG27 targeted tests、直接 Binding/Sufficiency regressions、targeted mypy/Ruff，写 `var/dg27/v03/terminal.json`。只有有效 D0–D3 treatment 才可判定 DG27-H1/H2。

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

迭代处置（不是 Goal terminal）：

| disposition | 条件 | 处置 |
| --- | --- | --- |
| REPAIR_ITERATION | fail-closed protocol/implementation invalidity，无 state escape | 保留当次证据，修通用根因后新建 superseding iteration |
| INFRASTRUCTURE_RETRY_EXHAUSTED | identical transport retry 仍失败 | 修服务/超时边界，不评分假设 |

V02 已封存为第一个 `REPAIR_ITERATION`，不再作为阻塞后续开发的项目 terminal。

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
旧 run-lock、V02 terminal 与所有 V03 结果均保留
不把 provisional state 持久化为 canonical state
```

> DG-27 的修复目标不是让模型绕过 Binding，而是让模型在最终接受之前保留语义可能性，并让 Runtime 只在一个集中边界上作严格决定。
