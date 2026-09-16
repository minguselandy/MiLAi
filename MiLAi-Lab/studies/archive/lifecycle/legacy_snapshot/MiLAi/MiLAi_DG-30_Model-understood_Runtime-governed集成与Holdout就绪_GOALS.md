---
document_id: MILA-DG30
version: "0.6.0"
status: PASS_READ_PATH_INTEGRATION_RELEASE_NOT_READY
execution_order_authority: MILA-ML-MASTER
---

# MiLAi DG-30：Read Path Integration Goal

> 文档版本：0.6.0 / TERMINAL READ-PATH GOAL
> 日期：2026-08-30（Asia/Shanghai）
> 状态：`PASS_READ_PATH_INTEGRATION`；`release_ready=false`
> Program：[Program C Read Path / Recollection](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
> Formal holdout：本 Goal 不执行
> ExperimentalFeatureFlagsFinalState：OFF
> 最高允许结论：PASS_READ_PATH_INTEGRATION

---

# 1. 目标

权威终态：`var/dg30/terminal-v002.json`（terminal digest `6fa2b04947b3a5c627f776f64b530b253fc863bbc56dcea920c7d746080a68c2`）。固定候选集上 target candidates/bindings 均为 7/7，AcceptedBindingPrecision 1.0，Wrong COMPLETE 0，query-time model calls 和 additional refinding rounds 均为 0。Formal holdout 未使用、feature flag 仍 OFF，所以不宣称 release ready。

DG-30 只集成 Program C 中有实验证据的最小读取路径：

~~~text
official acquisition
→ optional deterministic channel union
→ grounded interpretation
→ centralized AcceptedBinding / Sufficiency
→ Typed OperatorResult
→ Reader handoff
~~~

若 DG-29 未进入，集成路径不得包含 active refinding。若 DG-28 没有增益，集成路径不得包含 multi-channel treatment。

---

# 2. 组件 Admission

| 组件 | 默认处置 | Admission |
| --- | --- | --- |
| DG-26 StateView reranker | REJECTED | 已有终态负结果，不重开 |
| DG-27 Decision Boundary | REQUIRED | DG27-H1 通过 |
| DG-27 model interpretation | CONDITIONAL | 相对 deterministic interpretation 有最终 Binding 增益 |
| DG-28 channel union | CONDITIONAL | 有最终 mediator gain |
| DG-29 second round | DEFAULT EXCLUDED | DG-29 实际进入且有独立净增益 |

原则：

> 未证明有增益的组件从集成路径删除，而不是保留为“未来可用”的默认复杂度。

---

# 3. 非目标

~~~text
Memory Formation
Canonical Evolution redesign
full adaptive search agent
model action authority
Formation × Retrieval factorial
完整 Memory Architecture release
formal holdout
~~~

这些分别属于 Program A、Program B 或后续明确授权。

---

# 4. 执行阶段

## S0 — Admission freeze

- 读取 DG-27、DG-28 和可选 DG-29 terminal。
- 生成 admitted component list。
- 冻结 feature flags、fallback 和 rollback。

## S1 — Product-faithful integration

- 只连接 admitted components。
- 评估路径调用正式 Acquisition、Binding、Operator 和 Reader。
- Eval 不实现产品行为。

## S2 — Read-path regression

覆盖：

~~~text
simple lookup
two-operand compare
preference/current state
temporal point lookup
temporal COUNT abstention when proof absent
revoked or inaccessible Evidence
correct-case non-regression
~~~

## S3 — Efficiency and rollback

- 比较 baseline 与 admitted path 的 calls、candidates、latency 和 model usage。
- 验证关闭 experimental feature flag 即通过 ImplementationRollback 恢复原路径。

## S4 — Terminal

- 写 read-path terminal。
- Experimental feature flags 保持 OFF。
- 不消费 formal holdout。

---

# 5. 指标

~~~text
RequiredEvidenceCoverage
AcceptedBinding precision / recall
OperatorReady
FinalAnswerCorrect / F1
Wrong COMPLETE
CorrectCaseRegression
PermissionViolation
OfficialCalls
HydratedCandidates
ModelCalls
Latency
ImplementationRollbackEquivalence
~~~

---

# 6. PASS

PASS_READ_PATH_INTEGRATION：

~~~text
DG-27 centralized boundary 实际生效
只包含通过 admission 的组件
产品路径与 evaluation 路径同构
权限、撤销和 Canonical 边界未改变
rollback 恢复 baseline
ExperimentalFeatureFlagsDefault = OFF
formal holdout 未使用
~~~

实验结果和发布资格分开报告。若仍有 Wrong COMPLETE 或 correct-case regression，可以完成 read-path integration 诊断，但不能标记 RELEASE_READY。

允许终态：

| 状态 | 含义 |
| --- | --- |
| PASS_READ_PATH_INTEGRATION | 最小读取路径完成集成 |
| PASS_READ_PATH_NO_ADAPTIVE_COMPONENT | 无自适应组件仍完成 |
| PARKED_COMPONENT_CONFLICT | 已通过组件组合后相互回归 |
| PARKED_READER_REGRESSION | Operator 正确但 Reader 消费回归 |
| NOT_RELEASE_READY | 集成完成但严格发布门未通过 |

禁止使用 PASS_COMPLETE_MEMORY_ARCHITECTURE。

---

# 7. 轻量制品

~~~text
var/dg30/run-lock.json
var/dg30/results.json
var/dg30/terminal.json
var/dg30/failure-index.jsonl
~~~

测试只覆盖 admitted path 和直接回归；数据库、安全或架构测试仅在实际改到对应边界时触发。
