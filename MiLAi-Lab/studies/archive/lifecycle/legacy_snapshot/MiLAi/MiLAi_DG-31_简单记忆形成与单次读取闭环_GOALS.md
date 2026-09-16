# MiLAi DG-31：简单记忆形成与单次读取闭环 Goal

> Goal ID：DG-31
> 版本：1.2 / SUPERSEDED_BY_PROJECT_REBASE
> 日期：2026-08-30（Asia/Shanghai）
> 前置事实：DG-24 已定位首损；DG-25、DG-26 未证明复杂检索控制流能稳定提高正确性
> 当前状态：DO NOT EXECUTE
> 处置：原子记忆 + 简单读取假设迁移到 MF-06 的 formed + simple arm；MF-01 之前不得直接实施 projection treatment
> 替代导航：[MiLAi Memory Lifecycle Master](./MiLAi_Memory_Lifecycle_项目级架构与主程序_MASTER.md)
> Candidate 默认：OFF
> Formal holdout：不使用

---

# 1. 为什么重置路线

当前系统把简单个人记忆读取逐步扩展成：

~~~text
RequirementState
→ 多通道动作
→ StateView
→ reranker
→ Binding
→ action ranking
→ residual cue
→ refinding
→ 多层完成证明
~~~

这些机制适用于复杂、多跳或高风险任务，却使简单问题经过过多转换和拒绝点。DG-24 已证明主要损失首先发生在通道未调用、cutoff 和未发现；DG-25 又证明扩大候选后，分散在各层的完成判断会产生错误接受。

本 Goal 将问题重新定义为：

> 先把原始对话形成可直接匹配的简单记忆，再用一次读取找到它，最后只在一个边界判断答案是否成立。

---

# 2. 目标与非目标

## 目标

1. 建立 query-independent 的简单记忆投影。
2. 用 Exact/FTS 完成基础读取，Dense 只作为待验证的附加来源。
3. 取消检索阶段的 subject、predicate、lexical 等硬过滤，改为软排序。
4. 必要时只调用一次模型做候选与问题的语义配对。
5. 将证据接受和 COMPLETE 判断集中到最终边界。
6. 在 opened-development cases 上选择最简单、净正确性最高的方案。

## 本轮不做

~~~text
多轮 ReFind
模型动作选择
StateView action controller
Residual cue loop
Graph traversal
动态 channel planner
Prompt、seed 或 Top-k sweep
模型训练
自动 Canonical 写入
Formal holdout
~~~

DG-27～DG-30 的自适应检索路线由本 Goal 替代，不继续执行其旧 run-lock。

---

# 3. 最终读取路径

~~~text
Raw Evidence
  ↓  query-independent formation
SimpleMemoryRecord
  ↓
Exact / FTS / optional Dense，均只执行一次
  ↓
union + identity dedup + soft score
  ↓
optional one-shot semantic pairing
  ↓
single final decision boundary
  ↓
typed answer or abstention
~~~

只保留三个硬边界：

~~~text
访问权限与撤销
来源可追溯且 grounded span 存在
候选结果不能自动写入 Canonical State
~~~

其他匹配条件默认是排序特征，不是早期删除规则。

---

# 4. 最小数据对象

## SimpleMemoryRecordV01

每条记录表达一个事实、事件、偏好、决定或状态。字段允许为空，原始 memory text 是主要检索面。

~~~yaml
record_id:
source_evidence_id:
kind: FACT | EVENT | PREFERENCE | DECISION | STATE
memory_text:
subject:
relation:
object:
event_occurrence_time:
source_observed_time:
~~~

形成规则：

- 一个记录只表达一个可独立回答的内容。
- 所有内容必须能定位到原始 Evidence span。
- event time 与 source time 分开；无法确定时留空。
- projection 可重建、无 authority，不替代原始 Evidence。
- 本轮使用 sidecar artifact，不创建数据库 migration。

## SimpleMemoryQueryV01

~~~yaml
query_text:
answer_mode: LOOKUP | LIST | COMPARE | COUNT
expected_kind:
time_range:
items:
~~~

LOOKUP/LIST 直接读取；COMPARE 最多拆为两个 item；COUNT 只统计能确定 occurrence time 和 identity 的事件。范围是否完整若无法证明，返回部分结果或 abstain，不在本 Goal 新建复杂证明框架。

---

# 5. 检索与配对

## 5.1 候选生成

只比较三种递增方案：

| Arm | 候选来源 | 模型 |
| --- | --- | --- |
| M0 | 当前 raw-turn safe baseline | 无 |
| M1 | SimpleMemoryRecord Exact + FTS | 无 |
| M2 | M1 + Dense union | 无 |
| M3 | M2 | 一次语义配对 |

每个通道最多调用一次。M2 的 Dense 不削减 M1 的既有预算。候选按 evidence identity 去重，并保留来源。

## 5.2 软排序

只使用少量直观信号：

~~~text
文本相关性
subject / relation / object 兼容性
时间兼容性
source role
重复惩罚
~~~

除权限、撤销、损坏 evidence 和明确超出硬时间范围外，不在最终配对前删除候选。

## 5.3 可选语义配对

M3 最多一次模型调用：

~~~text
query item + small candidate set
→ MATCH | POSSIBLE | NO_MATCH
→ grounded evidence span
~~~

模型不选通道、不继续搜索、不宣布 COMPLETE、不提交 Canonical State。

## 5.4 单一最终边界

Runtime 在一个位置检查：

~~~text
Evidence 仍可访问
grounded span 真实存在
候选能回答目标 item
必要的值、时间和单位可用
冲突或歧义没有被静默合并
所有答案 operand 已覆盖
~~~

候选池可以有噪声；中间 POSSIBLE 不等于错误。只有经过这一边界的证据才进入最终答案。

---

# 6. 实验问题

## H1 — 记忆形成

SimpleMemoryRecord 是否比直接反复检索原始对话提高目标证据覆盖和最终答案正确性？

## H2 — Dense 必要性

在相同简单记录上，Dense union 是否提供 Exact/FTS 没有的有效证据？

## H3 — 模型必要性

在固定候选集合中，一次语义配对是否产生超出 M2 的净答案增益？

若较简单 arm 已达到同等最终效果，就删除更复杂组件。

---

# 7. 执行阶段

## S0 — 冻结可比基线

- 复用 DG-24 的 evidence equivalence groups 和 opened-development cases。
- 记录 DG-25 safe baseline 的候选、最终答案和成本。
- 写入 var/dg31/run-lock.json。
- 不执行旧 DG-27 run-lock。

## S1 — 形成简单记忆

- 从同一 Raw Evidence 生成 SimpleMemoryRecord sidecar。
- 人工抽查与自动检查只关注 atomicity、source grounding 和 event-time 明显错误。
- 修复通用 projection 逻辑；禁止 case-ID、答案和 gold 驱动规则。

## S2 — 实现单次读取

- 实现 M1 与 M2。
- 复用正式 repository/index，不在评估脚本中重写 BM25 或 Dense。
- 删除或旁路非权限类的早期 hard filter。

## S3 — 集中最终判断

- 将检索层的 COMPLETE/accepted shortcut 移到单一最终边界。
- 重放 DG-25 的错误 COMPLETE 病例。
- 仅当 M2 存在“候选已到达但无法正确配对”时实现 M3。

## S4 — 一次 matched evaluation

- 固定 snapshot、cases、Evidence、权限和最终 answer scorer。
- 一次运行 M0–M3；未实现的 M3 标记 NOT_NEEDED。
- 结果出现后不换 seed、不扩大 K、不追加搜索轮数。
- 选择净正确性最高且组件最少的 arm。

---

# 8. 指标与判定

核心指标：

~~~text
TargetEvidenceRecall
RequiredEvidenceCoverage
FinalAnswerCorrect
FinalAnswerF1
ImprovedCases
RegressedCases
NetCorrectGain = ImprovedCases - RegressedCases
OfficialRetrievalCalls
HydratedCandidates
ModelCalls
Latency
~~~

诊断指标：

~~~text
KnownFalseFinalBinding
Wrong COMPLETE
PermissionViolation
CanonicalMutation
TemporalUnknownCount
~~~

中间 candidate precision 不设硬门，也不因一个错误 case 提前终止全部实验。

## 开发结论

满足以下条件即可判定实验路线有效：

~~~text
NetCorrectGain > 0
RequiredEvidenceCoverage 不下降
至少恢复一个 DG-24 预注册首损 group
PermissionViolation = 0
CanonicalMutation = 0
~~~

已知错误和回归必须逐例列出，但用于修复和选 arm，不触发重型审计或中途停机。

## 发布资格

发布是独立、更严格的后续决定：

~~~text
KnownFalseFinalBinding = 0
Wrong COMPLETE = 0
RegressedCases = 0
Candidate flag 经过明确授权
~~~

DG-31 结束时 Candidate 仍保持 OFF，因此“实验有效”和“可默认发布”不得混为一个门。

终态只使用：

| 状态 | 含义 |
| --- | --- |
| PASS_SIMPLE_MEMORY_GAIN | 简单记忆读取获得净正确性增益 |
| PASS_NO_DENSE_NEEDED | M1 已足够 |
| PASS_NO_MODEL_NEEDED | M1/M2 已足够 |
| PARKED_NO_GAIN | 简化路径未提高最终效果 |
| PARKED_SOURCE_INSUFFICIENT | 原始 Evidence 本身不足 |
| PARTIAL_TEMPORAL_UNRESOLVED | 普通读取改善，但 temporal COUNT 未闭合 |

---

# 9. 轻量开发与制品

只保留四个运行文件：

~~~text
var/dg31/run-lock.json
var/dg31/results.json
var/dg31/terminal.json
var/dg31/failure-index.jsonl
~~~

只记录会改变设计判断的 material failure。开发时运行 touched tests、targeted mypy/Ruff 和两个 smoke；终态运行 DG-31 targeted tests 与直接相关回归。数据库、安全或架构测试仅在实际改到对应边界时触发。

不创建逐阶段 receipt、transitive source manifest、deliverable index、独立 runbook 或多轮 reviewer。

---

# 10. 回滚与立即行动

回滚只需关闭 simple-memory candidate flag，并恢复 M0；sidecar projection 和实验结果可保留，Canonical State 不受影响。

立即执行顺序：

1. 将 DG-27～DG-30 标记为 superseded。
2. 冻结 M0 与 SimpleMemoryRecord 样例。
3. 先完成 S1，确认简单记忆本身可正确配对。
4. 依次运行 M1、M2；只有候选到达后的语义歧义仍是主要损失时才实现 M3。
5. 以最终净正确性选最简单 arm，不再继续扩建检索 Agent。

> 对简单记忆，正确默认应是“形成一次、读取一次、最终判断一次”。
