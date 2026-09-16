---
document_id: MILA-DG28
version: "0.7.0"
status: PASS_DG28_LITE_RETRIEVAL_GAIN
execution_order_authority: MILA-ML-MASTER
---

# MiLAi DG-28：最小多通道 Evidence Recovery Goal

> 文档版本：0.7.0 / TERMINAL LOCAL GOAL
> 日期：2026-08-30（Asia/Shanghai）
> 状态：`PASS_DG28_LITE_RETRIEVAL_GAIN`；后续 formed-consumption 已封存
> Program：[Program C Read Path / Recollection](./MiLAi_Program-C_DG26-DG30_Read_Path_Recollection_MASTER.md)
> ExperimentalFeatureFlagsDefault：OFF
> Formal holdout：不使用

---

# 1. 唯一问题

权威回执：`var/dg28/lite/dg28-lite-lexical-union-20260830-001/receipt.json`。结果为 target candidates 4/7 → 7/7、bindings 3/7 → 6/7、AcceptedBindingPrecision 1.0、Wrong COMPLETE 0。MF-03 sidecar 在同一 44-candidate pool 上进一步将 Binding 闭合为 7/7，回执为 `var/dg28/formation/dg28-formation-consumption-20260830-002/receipt.json`。

DG-24 已定位：

~~~text
CHANNEL_ELIGIBLE_NOT_INVOKED = 6
CHANNEL_CUTOFF_DROP = 1
~~~

DG-28 只回答：

> 对这 7 个预注册 evidence group，一次调用现有正式通道并做简单 union，是否比当前固定 route 恢复更多可 Binding evidence？

不处理 NO_CHANNEL_RETRIEVED_GOLD；那不是现有通道组合问题。

---

# 2. 分层 Entry

Preparation entry（已授权）：

~~~text
DG-24 gold-equivalence registry 可读取
official AcquisitionService/repository/index 可用
experimental feature flags OFF
formal holdout 未使用
shadow candidates 不进入 Binding/Sufficiency/Reader
~~~

Final effect entry（尚未满足）：

~~~text
DG27-H1 = PASS_DECISION_BOUNDARY_REPAIRED
acquisition-only preparation identity 已冻结
~~~

DG-27 未通过时不得运行 final effect，但不得因此空等：可以冻结通道、跑 official acquisition-only shadow、恢复 channel lineage 并预先发现索引/服务问题。

---

# 3. Treatment

只比较：

| Arm | 行为 |
| --- | --- |
| D0 | 当前 product-faithful route |
| D1 | 同一 query 下，所有已实现且合法的 official channels 各调用一次，union 后 identity dedup |

D1 只能复用当前 AcquisitionService、repository 和 index。评估层不得实现 BM25、Dense、fusion 或过滤器。

规则：

~~~text
每个 channel 最多一次
不生成新 cue
不让模型选 action
不进行第二轮搜索
不增加新检索器
不更改 Reader
不改变 DG-27 Decision Boundary
~~~

候选可以有噪声；除权限、撤销、损坏数据和明确硬时间范围外，不做新的早期 hard drop。

---

# 4. Research Hypotheses

| Hypothesis | 最小证据 |
| --- | --- |
| DG28-H1 official channel union 恢复已知机会损失 | 至少一个预注册 group 从未到达变为 governed candidate，并形成新的合法 Binding 或 Operator readiness |
| DG28-H2 复杂 planner 当前没有 entry evidence | D1 已达到 oracle-available recovery，或未获得增益但错误明确不属于 action selection |

不声称：

~~~text
完整 retrieval recall 已解决
adaptive action ranking 有效
第二轮 refinding 必要
Formation substrate 已正确
~~~

---

# 5. 并行准备与一次 effect

## S0 — Freeze

- 复用 DG-24 的 7 个目标 group。
- 冻结 D0、channel availability、snapshot 和总候选预算。
- 写 acquisition preparation identity；final effect run-lock 在 DG27-H1 通过后才封存。

## S1 — Official union

- 在 acquisition-only shadow 中使用正式 AcquisitionService 实现 D1 候选池。
- 保留每个 evidence 的 channel/rank lineage。
- union 后只做 identity dedup。
- 这些 shadow candidates 不进入 Gate 之后的任何决策，不改变产品输出。

## S2 — Full final decision

- Entry：DG27-H1 通过，并且封存新 final effect run-lock。
- D0、D1 均经过相同 DG-27 interpretation、AcceptedBinding 和 Sufficiency。
- 不使用 retrieval proxy 宣布 COMPLETE。

## S3 — Matched result

- 一次运行 D0/D1。
- 不换 K、Prompt、seed 或 channel 配置补考。
- 写 results.json 与 terminal.json。

---

# 6. 指标

~~~text
TargetGroupCandidateRecall
RequiredEvidenceCoverage
NewAcceptedBinding
OperatorReady
KnownFalseFinalBinding
Wrong COMPLETE
CorrectCaseRegression
OfficialCalls
HydratedCandidates
Latency
~~~

Candidate precision 是诊断指标，不是中途停机门。

---

# 7. 判定

| 状态 | 条件 |
| --- | --- |
| PASS_MINIMAL_MULTICHANNEL_GAIN | D1 获得至少一个最终 mediator gain，且净答案正确性不下降 |
| PASS_NO_ADAPTIVE_PLANNER_NEEDED | D1 已覆盖所有 official oracle opportunity |
| PARKED_CHANNEL_UNION_NO_GAIN | union 没有转化为 Binding/Operator gain |
| PARKED_REPRESENTATION_GAP | official channels 都没有目标 evidence |
| FAIL_DECISION_REGRESSION | 新增候选导致最终错误增加 |

实验完成不等于发布。Experimental feature flags 最终保持 OFF。

acquisition-only preparation 中发现的服务、索引或 lineage 失败按通用开发循环修复；只有完整 D0/D1 final treatment 才能形成上表的 PASS/PARKED/FAIL。

---

# 8. DG-29 Entry Check

DG-28 terminal 必须额外输出：

~~~text
unresolved_requirements_after_D1
new_observation_cues
unexecuted_feasible_actions
second_round_oracle_opportunity
~~~

只有四项均非空/为真时，DG-29 才可从 NOT_ENTERED 更新为 ACTIVE。否则 DG-29 直接保持 NOT_ENTERED。

---

# 9. 轻量制品

~~~text
var/dg28/run-lock.json
var/dg28/results.json
var/dg28/terminal.json
var/dg28/failure-index.jsonl
~~~

只运行 targeted retrieval、DG-27 boundary 和直接行为回归；不创建逐阶段 receipt、transitive manifest 或独立 runbook。

资源调度：acquisition-only channel probes 可按 `query × channel` 并行，但每个 query/channel 仅一次 official call；默认最多 8 个 concurrent probes，并在 repository/service latency P95 超过基线 2 倍时减半。
