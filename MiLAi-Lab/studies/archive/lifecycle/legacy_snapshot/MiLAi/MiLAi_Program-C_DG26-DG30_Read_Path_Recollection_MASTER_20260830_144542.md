---
document_id: MILA-PC-MASTER
version: "1.2"
status: ACTIVE_PROGRAM_C_SUBPLAN
execution_order_authority: MILA-ML-MASTER
---

# MiLAi Program C：DG-26～DG-30 Read Path / Recollection 子计划

> 文档版本：1.2 / ACTIVE PROGRAM-C SUBPLAN
> 日期：2026-08-30（Asia/Shanghai）
> 总执行导航：[MiLAi Memory Lifecycle 总 Goal](./MiLAi_Memory_Lifecycle_总_GOALS.md)
> 所属项目：[MiLAi Memory Lifecycle 项目级 Master](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)
> 当前局部入口（由 MILA-ML-MASTER 授权）：DG-27 V03 repair + DG-28 acquisition-only preparation
> 范围：query-time evidence recollection，不代表完整 Memory Architecture
> Formal holdout：不使用
> ExperimentalFeatureFlagsDefault：OFF

---

# 1. 子计划边界

本子计划只负责：

~~~text
MemoryQueryIR
→ Candidate Acquisition
→ Interpretation
→ Binding
→ Sufficiency
→ Operator
→ Reader
~~~

不负责：

~~~text
Evidence ingest
episode formation
entity/event identity formation
state/change formation
Canonical evolution policy
user model consolidation
~~~

这些分别属于 Program A 和 Program B。

---

# 2. 当前机器事实

| Goal | 机器状态 | 保留结论 | 处置 |
| --- | --- | --- | --- |
| DG-24 | PASS | 6 个 channel 未调用、1 个 cutoff、3 个未发现 | DG-28 的固定诊断集 |
| DG-25 | FAIL | 候选可增加，但 Binding 与 COMPLETE 代理不安全 | 先修 DG-27 |
| DG-26 | TERMINAL FAIL | correct StateView fixed-pool rerank 无独立增益且有回归 | 不重开 |
| DG-27 V02 | FAIL-CLOSED PROTOCOL ATTEMPT | span offset / timezone 协议在 effect 前被 Runtime 拒绝；H1/H2 未评估 | V03 通用 repair 已授权 |
| DG-28 | 未执行 | 无效果证据 | S0/S1 acquisition-only 准备已授权；final effect 等待 DG27-H1 |
| DG-29～DG-30 | 未执行 | 无效果证据 | 按 MILA-ML-MASTER 与本地 Goal 条件进入 |
| DG-31 | 文档方案、未执行 | 形成后简单读取是假设 | 迁移至 MF-06 |

---

# 3. 两项 Program Hypotheses

| Research hypothesis | 最小可信证据 |
| --- | --- |
| PC-H1 集中的 Decision Boundary 能消除检索层 shortcut 造成的错误 COMPLETE | DG-25 的 16 个 Wrong COMPLETE 重放为 0，且已正确病例不因边界迁移丢失 |
| PC-H2 简单调用现有合法通道能恢复 DG-24 已知机会损失 | 只读 official channel union 恢复预注册 evidence group，并形成有效 Binding/Operator gain |

不再把以下内容设为 Program research hypothesis：

~~~text
StateView fixed-pool reranking
模型 action ranking
多轮 refinding
完整 adaptive retrieval workspace
~~~

它们只有在前一简单方案仍有可证明 residual opportunity 时才进入。

---

# 4. Goal 处置

## DG-26 — 保持终态

不换 K、Prompt、seed 或模型重跑。它只否定当前 fixed-pool StateView treatment 的独立增益。

## DG-27 — Read-path Decision Boundary Repair

只负责：

~~~text
grounded interpretation
ProvisionalBinding
single AcceptedBinding validation
single COMPLETE / Sufficiency decision
Wrong COMPLETE closure
~~~

允许候选与 ProvisionalBinding 有噪声；检索层不得提前宣布 Accepted 或 COMPLETE。

## DG-28 — 最小多通道读取修复

只测试 DG-24 的：

~~~text
CHANNEL_ELIGIBLE_NOT_INVOKED = 6
CHANNEL_CUTOFF_DROP = 1
~~~

比较：

~~~text
current route
vs
一次 deterministic official channel union
~~~

不加入 model planner、action composition、第二轮搜索或新检索器。只有 DG-24 已证明在某正式通道存在的 evidence 才进入 primary treatment。

## DG-29 — 默认不进入

默认状态：

~~~text
NOT_ENTERED_PENDING_REFINDING_OPPORTUNITY
~~~

只有以下条件全部存在才创建 effect run：

~~~text
DG-28 后仍有 unresolved requirement
新 observation 产生 query 初始时不存在的新 cue
至少一个未执行且合法的 action
第二轮 official acquisition 有 oracle opportunity
~~~

任一缺失即 terminal NOT_ENTERED，不把 ReFind 的外部有效性当作 MiLA 必要性证明。

## DG-30 — Read Path Integration and Release Readiness

只集成实际通过的最小组件，并封存：

~~~text
Decision Boundary
optional deterministic multi-channel
optional second round when DG-29 entered
Operator / Reader handoff
rollback and feature flags
~~~

允许的最高终态：

~~~text
PASS_READ_PATH_INTEGRATION
~~~

禁止：

~~~text
PASS_COMPLETE_MEMORY_ARCHITECTURE
PASS_MEMORY_LIFECYCLE
~~~

---

# 5. 执行顺序

~~~text
DG-27 V03 protocol repair → canary → matched effect
           │
           └─ in parallel: DG-28 acquisition-only preparation
  ↓ DG27-H1 repaired
DG-28 final deterministic union effect
  ↓ inspect real second-round opportunity
DG-29 entered or NOT_ENTERED
  ↓
DG-30 read-path integration
~~~

MF-01 可与 DG-27 并行开展标签和观察性 trace，但不得改变 DG-27 candidate pool 或回答。

---

# 6. 轻量实验规则

1. 一个 Goal 只保留一项主要机制问题。
2. 单次 protocol/implementation 失败进入 diagnose–repair–canary 循环，不等于 Goal terminal；只有实际权限泄漏、失控 Canonical mutation 或数据损坏立即停当次 effect。
3. Candidate noise 不作为提前终止条件，最终 AcceptedBinding/answer 才决定 correctness。
4. 不做 seed、Top-k、Prompt sweep。
5. 不生成逐阶段 receipts、transitive manifest 或多轮 reviewer。
6. 每个 Goal 只保留 run-lock、results、terminal 和 material failure ledger。
7. Formal holdout 继续未使用。

---

# 7. 统一指标

~~~text
TargetEvidenceRecall
RequiredEvidenceCoverage
AcceptedBinding precision / recall
OperatorReady
FinalAnswerCorrect / F1
Wrong COMPLETE
CorrectCaseRegression
Official calls
Hydrated candidates
Latency
~~~

检索候选可以宽；权限与最终 state commit 仍按冻结架构执行。

---

# 8. 文档优先级

1. architecture/v1.0
2. MiLAi Lean V1 实施合同
3. `MILA-ML-ARCH@1.0`（Program / Plane）
4. `MILA-ML-MASTER@1.2`（唯一执行顺序）
5. 本 Program C Master
6. DG-27～DG-30 局部 Goal
7. 旧自适应检索总 Goal与轻量基线的历史段落

本文件替代旧 DG-26～DG-30 总 Goal 的主路线地位，但不覆盖 DG-26 已封存的负结果。
