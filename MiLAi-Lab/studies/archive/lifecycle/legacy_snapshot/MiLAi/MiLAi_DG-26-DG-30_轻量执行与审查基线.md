# MiLAi Program C：DG-26～DG-30 轻量开发共享基线

> 文档版本：2.2 / ACTIVE SUBPLAN SUPPORT
> 日期：2026-08-30（Asia/Shanghai）
> 适用范围：DG-26、DG-27、DG-28、DG-29、DG-30
> 历史导航：[DG-26～DG-30 自适应检索与集中验证总 Goal](./MiLAi_DG-26-DG-30_自适应检索与集中验证_总_GOALS.md)
> 当前执行导航：[Program C Read Path / Recollection Master](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
> 项目级导航：[MiLAi Memory Lifecycle Master](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)
> 核心原则：**宽检索、软解释、严提交**
> 处置：只提供机器事实和轻量开发规则；具体范围以 Program C Master 为准。

---

# 1. 当前机器事实

| Goal | 当前状态 | 已证明的事实 | 后续处置 |
| --- | --- | --- | --- |
| DG-24 | `PASS_RETRIEVAL_FIRST_LOSS_LOCALIZED` | 23 个 evidence groups 中，6 个因 channel eligible 但未调用丢失，1 个被 cutoff 丢失，3 个未被现有通道发现 | 作为 DG-28 的 discovery 基线 |
| DG-25 | `FAIL_SAFETY_OR_REGRESSION` | 扩大候选池未提高 evidence coverage；最低 Binding precision 为 `2/3`；E1 replay 出现 16 次 Wrong COMPLETE | 不发布策略；拆分搜索问题与最终决策问题 |
| DG-26 | `FAIL / CORRECT_CASE_REGRESSION` | correct StateView 固定池重排恢复 2 个 residual groups，但丢失 1 个 baseline group，且与 shuffled StateView 聚合结果相同 | 保留为负结果，不调 K、Prompt、seed 重开 |
| DG-27 | 旧 `run-lock.json` 已冻结，未执行 | 只有旧版严格单解释合同；尚无实现、模型调用、results 或 terminal | 旧 lock 标记为 pre-execution superseded；按 V02 新合同重新进入 |
| DG-28～DG-30 | 未开始 | 无运行制品 | 使用本基线实施 |

DG-25 的两个问题必须分开：

```text
检索/选择问题：
  更多候选没有转化为更多有效 coverage

最终决策问题：
  replay completion proxy 曾在没有 MATCH Binding 时宣布 COMPLETE
```

不能用增加检索规则修复第二个问题，也不能用更严格的早期过滤修复第一个问题。

---

# 2. 架构修正

旧路径把最终状态要求复制到了每个中间层：

```text
单一 query 分类
→ 固定 channel
→ lexical/entity/time hard filter
→ channel cutoff
→ global priority
→ 单一 interpretation
→ Binding hard decision
→ COMPLETE
```

任一层误判都会让证据不可恢复；增加层数还会重复消耗排序、hydration、Binding 和审计成本。

新路径改为：

```text
Query
  ↓
SemanticSearchWorkspace                 # query-local、可变、无 authority
  ↓
Capability Sandbox                     # Runtime 给出合法动作和全局预算
  ↓
Broad / Adaptive Official Acquisition  # 多通道、可组合、允许噪声
  ↓
Provisional Interpretation / Binding   # N-best、可歧义、可修正
  ↓
集中 Decision Boundary                 # 一次最终验证
  ↓
AcceptedBinding + typed Sufficiency
  ↓
OperatorResult / Abstention
```

原则不是减少正确性，而是让严格性只出现在真正产生 authority 的边界。

---

# 3. 两种状态

## 3.1 `SemanticSearchWorkspaceV01`

这是模型可理解和参与更新的 query-local 工作状态：

```yaml
query_hypotheses: []
requirement_hypotheses: []
missing_support_hypotheses: []
entity_aliases: []
temporal_hypotheses: []
anchors: []
provisional_bindings: []
conflicts: []
attempts: []
seen_regions: []
remaining_global_budget: {}
```

允许：

```text
多个解释并存
模型修正 failure hypothesis
模型选择或组合合法动作
模型产生 cue、alias、local expansion
候选暂时保持 AMBIGUOUS/POSSIBLE
```

禁止：

```text
直接写 Canonical State
直接产生 AcceptedBinding
直接宣布 COMPLETE
扩大 Runtime 未授权的 scope、time range 或 budget
```

## 3.2 `DecisionState`

这是 Runtime 最终派生的权威查询状态：

```text
admitted evidence identities
AcceptedBinding
unresolved conflicts
proof obligations
RequirementState
Sufficiency
Operator readiness
```

只有实际 evidence、最终验证和 proof 才能改变它。模型的 Soft State 不能直接提交为 DecisionState。

---

# 4. 硬边界应放在哪里

## 4.1 检索前硬边界

只保留：

```text
tenant/access/revocation/retention
capability 是否真实存在
动作 scope 与时间范围上界
全局 query budget
最大外部调用和总候选资源
```

Runtime 提供 `FeasibleActionSet`；模型只能引用其中的动作模板，不能生成任意 SQL、tool 或跨域参数。

## 4.2 检索和解释中使用软信号

以下默认改为 score、feature 或 provisional status，不再作为不可恢复 hard drop：

```text
lexical anchor match
entity alias match
predicate similarity
source-role preference
event-time hypothesis
session/episode prior
candidate relevance
模型 relation/confidence
```

例外只有真实 access denial、明确超出动作范围或数据损坏。

## 4.3 最终决策硬边界

最终 `AcceptedBinding` 必须验证：

```text
evidence 仍可访问且 provenance 可解析
grounded span 或等价的可验证结构化来源存在
requirement role/type/source/time/unit 合法
冲突、重复和歧义未被静默吞掉
```

最终 `COMPLETE` 必须同时满足：

```text
每个 required evidence role 均有 AcceptedBinding
每个 required proof obligation 均已满足
不存在阻断性 conflict / ambiguity
typed operator 已可执行
```

禁止再次使用：

```python
bool(selected_rows) and all(proofs_satisfied)
```

代替合法 Binding coverage。

---

# 5. 预算与效率

不再为每层和每通道叠加固定 quota。每个 query 只冻结一个全局资源预算：

```yaml
max_model_calls:
max_official_actions:
max_hydrated_candidates:
max_total_latency_ms:
max_rounds:
```

Planner 可以在合法 actions 之间分配预算。Runtime 只检查总量和单次动作上界。

默认开发顺序：

```text
DG-28：一轮、宽候选、同预算比较
DG-29：只有一轮仍 unresolved 且 observation 有新增信息时，才进入第 2/3 轮
```

达到以下任一条件停止搜索：

```text
DecisionState 已 COMPLETE
没有可行动作
连续一轮没有新 region、candidate 或 provisional binding
边际 gain 低于预注册阈值
全局预算耗尽
```

模型可以表达停止偏好，但 Runtime 决定是否停止。

---

# 6. 指标分层

不同层不能共用同一个精度硬门。

## Discovery / search workspace

```text
TargetRequirementCandidateRecall
RequiredEvidenceRoleDiscovery
NewRegionRate
RepeatedRegionRate
candidate/action cost
```

允许噪声；`CandidatePrecision = 1.0` 不是要求。

## Provisional interpretation

```text
GoldSpanOrSemanticCoverage
AmbiguityPreservationRate
FalseDefinitiveInterpretationRate
ProvisionalBindingCoverage
```

允许 `POSSIBLE`、`AMBIGUOUS` 和多个假设；ProvisionalBinding 不计作 AcceptedBinding。

## Final decision

```text
RequiredEvidenceCoverage
AcceptedBindingPrecision
KnownFalseAcceptedBinding
ProofObligationSatisfaction
OperatorReady
Wrong COMPLETE
CorrectCaseRegression
```

硬门只作用于最终层：

```text
KnownFalseAcceptedBinding = 0
Wrong COMPLETE = 0
Authority violation = 0
Canonical mutation = 0
```

中间候选发生变化不再自动算 correct-case regression；只有最终 AcceptedBinding、OperatorResult 或 answer 退化才算。

---

# 7. 执行顺序

```text
DG-26  已完成：固定池重排负结果，作为 anti-claim

DG-27  先修复语义解释与最终完成边界
       ProvisionalBinding → 集中 AcceptedBinding/COMPLETE

DG-28  在 capability sandbox 中执行一轮宽检索
       deterministic multi-channel 与 model-guided action composition 同预算比较

DG-29  仅对 DG-28 剩余且可恢复的病例运行 observation-conditioned refinding
       最多 2～3 轮，总预算不增加

DG-30  集成已证明有效的路径，统一执行最终验证、质量门和 holdout-ready 判断
```

DG-27 是安全语义前置；DG-28 是主要召回开发；DG-29 是条件式扩展，不是默认必跑；DG-30 不消费 formal holdout。

---

# 8. 轻量实验与制品

每个未完成 Goal 默认只保留：

```text
run-lock.json
results.json
terminal.json
failure-index.jsonl        # 仅 material failure
```

不再默认生成阶段 receipt、deliverable index、transitive manifest 或独立 runbook。

每个 Goal 最多：

```text
2 个 claims
4 个决定性 arms
3 个 core blocks
1 次权威运行；随机模型路径按预注册 seeds
```

开发循环只运行 touched tests、targeted mypy/Ruff 和一个 smoke。PostgreSQL/security/architecture/full suite 按实际变更触发；完整质量门只在 DG-30 统一运行一次。

Material failure 仅包括：

```text
改变实验结论
label leakage
错误 AcceptedBinding/COMPLETE
权限或预算违规
最终正确病例回归
sealed run 无法重放
```

语法、fixture 路径、格式和同一开发循环内修复的问题不进入正式 failure ledger。

---

# 9. 共同安全与发布边界

```text
Candidate 默认 OFF
Formal holdout 不使用
Public MCP schema 不修改
PostgreSQL schema 默认不修改
architecture/v1.0 不修改
Canonical mutation = 0
Automatic retry = 0
Reader 不参与 retrieval mediator 归因
```

这些边界限制外部副作用，不限制 query-local semantic search 的假设数量、候选噪声或合法动作组合。

---

# 10. Rollback

```text
所有 candidate flags OFF
恢复 DG-25 deterministic baseline
保留历史 run-lock/results/terminal
不覆盖失败证据
不删除用户已有改动
```

> 新基线不追求“每层都正确”。它追求中间状态可修正、搜索空间可适应，并在唯一的最终决策边界上保持严格正确。
