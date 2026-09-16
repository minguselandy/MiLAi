---
document_id: MILA-DG29
version: "0.5.0"
status: NOT_ENTERED_PENDING_REFINDING_OPPORTUNITY
execution_order_authority: MILA-ML-MASTER
---

# MiLAi DG-29：Observation 驱动的有界主动 Refinding Goal

> 文档版本：0.5.0 / CONDITIONAL
> 日期：2026-08-30（Asia/Shanghai）
> 状态：NOT_ENTERED_PENDING_REFINDING_OPPORTUNITY
> Program：[Program C Read Path / Recollection](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
> 共享基线：[DG-26～DG-30 自适应检索轻量开发基线](./MiLAi_DG-26-DG-30_轻量执行与审查基线.md)
> 执行授权：只有 DG-28 封存真实 second-round oracle opportunity 后才可更新版本并进入；当前不得运行 effect

---

# 1. 目标

测试 ReFind 类机制中真正有价值的部分：

```text
执行一次搜索
→ 阅读当前 observation
→ 更新 SemanticSearchWorkspace
→ 改变下一次合法 action/cue
→ 再搜索
```

研究问题：

> 在相同 max official actions、hydrated Evidence、evidence tokens、model calls、rounds 和 timeout policy 下，observation-conditioned sequential search 是否获得更多 target Binding、新 region 或更低重复率？

模型拥有 query-local 的语义策略权，但 Runtime 保留 capability、access、总预算、执行和最终 DecisionBoundary。

---

# 2. Entry

只有以下全部成立才进入：

```text
DG-28 已完成一轮 official acquisition
至少一个 requirement 最终仍 unresolved
第一轮产生了新的 anchor、region、rejection pattern 或 semantic hypothesis
仍存在至少一个未执行且合法的 FeasibleAction
official oracle/trace 表明第二步可能触达新 evidence
```

以下情况直接 `NOT_ENTERED`：

```text
DG-28 已 COMPLETE
所有现有 channel 均不可达
剩余问题只是 range proof、dedup proof、access 或 Reader
第一轮没有任何新 observation
只有重复同一 action/cue
```

---

# 3. Research Hypotheses

| Hypothesis | 最小证据 |
| --- | --- |
| DG29-H1 observation-conditioned refinding 有独立 mediator gain | 在相同处理上限下，adaptive arm 至少新增 1 个 AcceptedBinding/required role，或在相同 coverage 下显著降低 repeated regions / hydrated Evidence units |
| DG29-H2 有界闭环不会获得 Runtime authority | 每轮 action 均来自 fresh FeasibleActionSet；scope/budget 违规、stale action、KnownFalseAcceptedBinding、Wrong COMPLETE 和 Canonical mutation 均为 0 |

不声称模型能够证明 temporal completeness，也不让模型返回 `finish_search` 作为终态。

---

# 4. Search loop

```text
Round 0 DecisionState + SemanticSearchWorkspace
  ↓
Runtime enumerates fresh FeasibleActionSet
  ↓
Model diagnoses current gap and ranks/composes legal actions
  ↓
Runtime validates action bounds and executes official acquisition
  ↓
Governance admission
  ↓
Provisional interpretation / Binding
  ↓
Workspace observation update
  ↓
central DecisionBoundary at round boundary
  ├─ COMPLETE → stop
  └─ unresolved + budget → next round
```

DecisionBoundary 是同一个集中组件；不会把其 validator 复制进每个 channel/filter/reranker。

## 模型可更新

```text
failure hypotheses
missing-support description
entity/predicate aliases
temporal interpretation hypotheses
anchor priority
action preference
query/cue expression
region exploration priority
```

## Runtime 每轮控制

```text
fresh capability/action set
access/scope/time bound
remaining global budget
official execution
seen-action/region identity
AcceptedBinding/Sufficiency
```

---

# 5. Observation

模型读取有界语义 observation，而不是只有 digest：

```yaml
accepted_anchors: []
provisional_bindings: []
rejected_candidate_summary: []
new_region_summaries: []
attempted_actions: []
attempted_cues: []
repeat_rate:
new_candidate_count:
new_provisional_binding_count:
remaining_global_budget: {}
```

digest/epoch 由 adapter 附加用于 stale 检查，不要求模型复制。

seen state 以 requirement-specific region 为单位，不因访问一个 session 的局部窗口就排除整个 session。

---

# 6. 预算与停止

Must-run 比较只使用两轮；第三轮是条件扩展。所有 arms 共用同一总预算，区别只是预算何时分配。

Runtime 停止条件：

```text
DecisionBoundary = COMPLETE
没有 FeasibleAction
全局预算耗尽
本轮 new region = 0 且 new candidate = 0
本轮只有 equivalent cue / repeated action
预注册边际 gain 阈值未达到
```

第三轮只有在：

```text
第二轮产生新的 anchor/region
requirement 仍 unresolved
全局预算仍有剩余
第二轮边际 mediator 为正
```

时进入。不得在结果后追加预算。

---

# 7. Matched experiment

| Arm | 内容 | 作用 |
| --- | --- | --- |
| F0 | DG-28 best one-shot policy，在 round 0 一次性分配全部预算 | 强 one-shot baseline |
| F1 | deterministic two-round observation policy，同一总预算 | 简单 sequential baseline |
| F2 | correct observation + model active refinding，同一总预算 | 主 treatment |
| F3 | stale round-0 observation 驱动第二轮，同一总预算 | 证明 gain 来自 fresh observation |

固定处理上限：

```text
snapshot、requirements、policy/access
max official actions
max hydrated Evidence units
max Reader evidence tokens
max model calls and rounds
same timeout policy
available official channels
DecisionBoundaryV02
model/config
scorer
```

F3 只复用当前请求自己的旧 observation，不使用其他用户状态。

不做 free-form ReAct、四轮默认搜索、Prompt sweep 或 case-ID policy。

---

# 8. Core blocks

## DG29-B1 — Observation update

验证 round 1 结果能够产生：

```text
new anchors
new/repeated region identities
new provisional Binding
typed rejection summary
fresh remaining action set
```

## DG29-B2 — Budget-matched refinding

运行 F0–F3，比较最终 evidence/Binding，而不是只比较模型生成的 cue 是否“看起来合理”。

## DG29-B3 — Marginal efficiency

逐轮报告：

```text
delta candidate discovery
delta required role coverage
delta AcceptedBinding
delta OperatorReady
new/repeated region
model/action calls
hydration and latency
```

---

# 9. 执行阶段

## S0 — Entry / Freeze

写 `var/dg29/run-lock.json`，冻结 DG-28 residual cases、F0 policy、全局总预算、actions、model 和 metrics。

## S1 — Implement / Smoke

实现：

```text
workspace observation reducer
round-aware FeasibleActionSet
model state diagnosis/action composition
seen-region/equivalent-action suppression
bounded search controller
```

运行 touched tests、stale observation、repeat suppression、budget exhaustion 和一个 two-round official smoke。

## S2 — Matched effect

一次运行 F0–F3，写 `var/dg29/results.json`。第三轮若未满足预注册 entry，明确记录 `NOT_ENTERED`，不影响两轮结论。

## S3 — Targeted terminal

运行 DG29 targeted tests、direct active-retrieval regressions、targeted mypy/Ruff，写 `var/dg29/terminal.json`。

---

# 10. Metrics 与终态

Effect：

```text
RequiredEvidenceCoverage
TargetRequirementBindingGain
OperatorReadyDelta
DG28ResidualGroupsRecovered
```

Efficiency：

```text
MarginalGainPerRound
NewRegionRate
RepeatedRegionRate
HydratedCandidatesPerUsefulBinding
ModelAndActionCalls
Latency
```

Safety：

```text
StaleActionAccepted
ActionScopeOrBudgetMutation
KnownFalseAcceptedBinding
Wrong COMPLETE
FinalCorrectCaseRegression
```

终态：

| status | reason_code |
| --- | --- |
| NOT_ENTERED | NO_REFINDING_OPPORTUNITY |
| PASS | OBSERVATION_CONDITIONED_REFINDING_GAIN |
| PASS | SEQUENTIAL_DETERMINISTIC_GAIN_MODEL_NOT_NEEDED |
| PARKED | NO_ADAPTIVE_GAIN_AT_MATCHED_BUDGET |
| PARKED | EXISTING_CHANNELS_EXHAUSTED |
| FAIL | ACTION_SANDBOX_VIOLATION |
| FAIL | WRONG_COMPLETE_OR_FINAL_REGRESSION |

如果 F1 与 F2 相同且更简单，采用 F1。若 F0 与 F2 相同，保持 one-shot，不上线循环。

---

# 11. Rollback

```text
active-refinding flag OFF
max_rounds 恢复为 1
恢复 DG-28 admitted one-shot policy
保留 round traces/results/terminal
```

> DG-29 只在 fresh observation 真能改变下一步并带来边际证据时保留循环；轮数本身不是能力，也不是成功指标。
