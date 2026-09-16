---
document_id: MILA-LAB-PRODUCT02-128-FAILURE-FAMILIES
version: "1.0"
status: DIAGNOSTIC_COMPLETE
created_at: "2026-09-02T08:31:07+08:00"
source_run: product02-longmemeval-128-20260901T235621Z
normative_scope: diagnostic_input_only
---

# Product-02 128-case 错误族分析

## 1. 结论

Product-02 的终态选择正确：保留 B0/B1，停放 B2。但后验病例分析进一步发现两个需要优先
修复的工程事实：

1. B2 的主要失败不是新检索算法无效，而是普通 `LOOKUP` 的 Reader boundary 被切换成
   `DECISION_ACCEPTED_ONLY`。114/128 个 case 的 EvidenceSet 为空，Raw Evidence 在 Context
   编译前被删除。
2. 当前 Product 配置默认值 `progressive_context_evidence_v0_1=False` 对应被否定的 B2
   行为；实验选中的 B0 使用相反配置。产品默认行为与终态选择尚未对齐。

对 B0/B1 本身，94 个错误的首损近似分布为：

```text
59  session-level discovery 未命中
10  session 已命中但 required role 未进入 Context
15  只覆盖部分 EvidenceSet
 9  required roles 全部可见后仍答错
 1  abstention / Judge 判定错误
```

因此后续顺序应是：先校正默认边界与真实 trace，再用正式 acquisition 做 channel opportunity
probe；只有 probe 证明机会后，才选择一个简单检索 treatment。

## 2. 证据身份与结论边界

| 项目 | 身份 |
| --- | --- |
| Run | `product02-longmemeval-128-20260901T235621Z` |
| Cases | `artifacts/product02-u3-longmemeval-128-007/cases.jsonl` |
| Metrics | `artifacts/product02-u3-longmemeval-128-007/metrics.json` |
| Product tree | `3c7cc1b1304263d1bb41d60952efe2feadfb0a9db86087e86fd017780e5df5ba` |
| Product lock | `6f2869254659bf1c5f7710785a65016cb21b36d06b5411da978e9ffe98c68d1b` |
| Label manifest | `6238c10cb7d6203715043a1437add55e3cd8114d20cec9e7ceded11c92831412` |

限制：exact-turn/role 标签为 Qwen 模型辅助标签，不是独立人工 ground truth；Answer 与 Judge
使用同一 Qwen 服务，不声称 leaderboard equivalence。当前 128 slice 在本报告后已成为 opened
development evidence，后续在同一 slice 上的结果只能支持工程回归，不能支持独立泛化。

## 3. 原始结果表

### 3.1 B0/B1 与 B2

| 指标 | B0/B1 | B2 | 解释 |
| --- | ---: | ---: | --- |
| Judge correct | 34/128 | 10/128 | B2 净损失 24 |
| Session Recall@5 | 0.447917 | 0.075781 | B2 trace 已经过 boundary filtering |
| Exact answer-turn coverage | 0.418129 | 0.052632 | 57 个 turn-labeled cases |
| Exact answer-span coverage | 0.407738 | 0.053571 | 56 个 span-labeled cases |
| Required-role coverage | 0.354270 | 0.051240 | 121 个 role-labeled cases |
| EvidenceSet 为空 | 114/128 | 114/128 | 两臂 DecisionSnapshot 相同 |
| Accepted refs 总数 | 15 | 15 | B2 没有生成更多 Binding |
| Visible sessions 平均值 | 3.156 | 0.117 | B2 删除 baseline Evidence |
| Reader prompt tokens 平均值 | 2898.7 | 216.2 | 不是 token cap 截断 |
| Judge paired win/loss | — | 1/25 | 唯一 win 不是 Memory 增益 |

B2 唯一 paired win 的 Answer 字节与 B0 完全相同，只是 Judge 从 false 翻转为 true；因此可归因
的 Memory 效果更接近 `0 wins / 25 losses`。

### 3.2 LOOKUP 与 STRICT 分层

| Mode | n | B0 correct | B2 correct | B0/B2 Context | 平均 tokens B0→B2 |
| --- | ---: | ---: | ---: | --- | ---: |
| LOOKUP | 69 | 30 | 6 | 69/69 被改变 | 5170.9 → 194.7 |
| STRICT | 59 | 4 | 4 | 59/59 byte-identical | 241.3 → 241.3 |

说明 B2 增量回退完全来自 LOOKUP。STRICT 本来就使用 accepted-only proof boundary；其低正确率
主要是 acquisition/Binding 没有形成可用 operand，而不是 B2 新增回退。

### 3.3 B0/B1 错误首损

| 错误族 | 数量 | 可观察条件 | 主要含义 |
| --- | ---: | --- | --- |
| F1 Discovery | 59 | gold session Recall@5 = 0 | 当前 FTS/query/channel 没把正确区域带入候选 |
| F2 Turn admission | 10 | session hit，但 required-role coverage = 0 | 命中主题 session，未命中或未装入 answer turn |
| F3 Partial EvidenceSet | 15 | `0 < role coverage < 1` | 多 session/operand 只找到部分成员 |
| F4/F5 Visible but wrong | 9 | role coverage = 1，Judge wrong | temporal/operator/Reader consumption |
| F5 Abstention | 1 | negative case，Judge wrong | semantic abstention 或 Judge 稳定性 |

F1 分布在所有 query 类型，不是一个孤立 benchmark 词面：temporal 23、multi-session 17、
knowledge-update 7、preference 5、single-session-user 5、single-session-assistant 2。

### 3.4 Coverage 与 Answer 的关系

对 121 个正向 role-labeled cases：

| Reader-visible role coverage | cases | correct | accuracy |
| --- | ---: | ---: | ---: |
| FULL | 35 | 26 | 0.742857 |
| PARTIAL | 17 | 1 | 0.058824 |
| NONE | 69 | 1 | 0.014493 |

对 57 个 exact-turn-labeled cases：全部 answer turns 可见时正确 16/23；未全部可见时正确 0/34。
这证明当前最强的可操作 mediator 是 required-role / answer-turn coverage，而不是继续调整 Reader
Prompt 或增加 Judge 调用。

### 3.5 按 LongMemEval 类型

| 类型 | n | B0 correct | B2 correct | B2 win/loss |
| --- | ---: | ---: | ---: | ---: |
| knowledge-update | 15 | 4 | 2 | 0/2 |
| multi-session | 34 | 7 | 3 | 0/4 |
| single-session-assistant | 16 | 12 | 0 | 0/12 |
| single-session-preference | 8 | 1 | 0 | 0/1 |
| single-session-user | 15 | 7 | 2 | 0/5 |
| temporal-reasoning | 40 | 3 | 3 | 1/1 |

assistant-authored recall 的 12 个回退说明 EvidenceSet 当前只形成极少 USER `MATCH` spans，不能
作为普通 lookup 的排他准入层。

## 4. 代表病例

以下 ID 只存在于 Lab 诊断文档，不得复制进 Product 代码、fixture 或 Goal。

| Lab case | 类型 | 观察 | 首损 |
| --- | --- | --- | --- |
| `95bcc1c8` | 单 session 数量 lookup | 两臂 session/turn/role coverage 均为 0 | F1 discovery |
| `58bf7951` | 单 session 用户事实 | session Recall=1；turn/role=0；B0 仍装入 7 sessions | F2 answer-turn admission |
| `1b9b7252` | assistant-authored answer | B0 正确且 role=1；B2 Context 归零并答错 | B2 source-role/boundary 删除 |
| `f35224e0` | multi-session 双 operand | B0 role=1 且正确；B2 删除全部 operand | B2 multi-operand admission |
| `gpt4_f49edff3` | 三事件时间排序 | B0 role=1 且正确；B2 不向 Reader 提供事件 | B2 temporal admission |
| `gpt4_68e94288` | relative-time strict query | 两臂 Context 相同、role=1、operator OK，但 Reader 仍答错 | F4/F5 Reader consumption |
| `gpt4_93159ced_abs` | temporal negative | 两臂 Answer hash 相同，Judge false→true | Judge instability |

这些病例共同排除了“所有问题都应靠扩大 Top-k、修改 Prompt 或上多轮 Agent”这一解释。

## 5. 代码根因

### 5.1 B2 将 EvidenceSet 误作 LOOKUP 白名单

`DecisionSnapshot` 总会携带 `EvidenceSet`，即便集合为空。`memory_resolve._access_outcome`
当前使用：

```text
STRICT
or (EvidenceSet exists and progressive_context_evidence == false)
→ DECISION_ACCEPTED_ONLY
→ 删除所有不在 accepted Evidence IDs 中的 EvidenceObservation
```

对应代码边界：

- `runtime/src/milai/application/retrieval.py::_requirement_evidence_set`
- `runtime/src/milai/application/memory_resolve.py::_access_outcome`
- `runtime/src/milai/application/memory_context.py` 的 Context compiler

EvidenceSet 只收 accepted MATCH Binding span。它适合 strict proof，不适合作为开放式 LOOKUP 的
唯一 Reader Evidence。

### 5.2 配置语义与终态选择相反

Product 默认：

```text
progressive_context_evidence_v0_1 = false
```

Lab 终态中的 treatment：

```text
B0/B1 = true  → GOVERNANCE_ADMITTED_SOFT_RANKED
B2    = false → DECISION_ACCEPTED_ONLY
```

因此“B2 default OFF”目前只是实验处置文本，不等于默认 Runtime 已执行 B0。下一 Goal 必须先让
真实默认 capability/context trace 与选中基线一致。

### 5.3 当前 raw trace 不是严格 pre-filter trace

现有 `raw_retrieval_trace` 从 `_access_outcome` 已过滤的 items 继续构造，因此 B2 指标把 selection
删除误表现为 retrieval recall 下降。后续至少需要：

```text
acquired_candidate_trace
bound_evidence_trace
reader_visible_trace
```

否则无法可靠区分 discovery、Binding 和 presentation 首损。

## 6. 优化建议

1. **先修默认行为，不先修 B2。** LOOKUP 默认保留 governance-admitted soft-ranked Evidence；
   STRICT COMPLETE 与 operator 继续只接受 Binding-authorized inputs。
2. **EvidenceSet 改为 additive signal。** 它可以提升 accepted spans 的优先级，但不得在普通
   lookup 中删除所有 baseline Raw Evidence。
3. **先跑 official channel opportunity probe。** F1 占 59/94，先比较当前 FTS、Dense、小 quota
   union 与 same-session expansion 的 pre-filter exact-turn/role recall；不调用 Reader/Judge。
4. **一次只选一个 treatment。** 若 Dense/FTS union 能恢复跨 query 类型的 F1，先做该项；若
   机会主要在 session-hit/turn-miss，才做 bounded local expansion。
5. **Strict proof 与 Reader context 分权。** 放宽 Reader 可见候选不能放宽 COMPLETE；Reader
   可以看到标记为 non-proof 的 governed Evidence，但 deterministic operator 仍只消费 accepted
   Binding。
6. **Reader 问题后置。** 只有 role coverage=1 的 9 个错误进入 Reader/temporal/operator 专项；
   不用 Reader Prompt 修复前 84 个证据不完整错误。

## 7. 不应采取的修复

- 重新启用或逐 case 修补 B2 hard filter；
- 将 EvidenceSet 是否存在当作是否有 accepted Binding 的判断；
- 为 sealed case 添加 synonym、entity 或 query-type 映射；
- 同时修改 retrieval、packing、Reader Prompt 与 token budget；
- 用更短 Prompt 的延迟下降抵消 correctness 回退；
- 在 acquisition opportunity 尚未证明前引入 Formation、Graph、Reflect 或多轮 ReFind；
- 将同答案的 Judge 翻转记作 Memory win。

## 8. 后续执行入口

本报告只拥有诊断权。后续执行由 Product 的 `MILA-PRODUCT-03` Goal 控制；B0/B1 保持基线，
B2 保持 parked，500-case formal holdout 继续不授权。
