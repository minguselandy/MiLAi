# MiLAi DG-26：固定候选池 StateView 重排终态与路线修正

> 文档版本：0.4.0 / EXECUTED / TERMINAL
> 日期：2026-08-30（Asia/Shanghai）
> 状态：`FAIL / CORRECT_CASE_REGRESSION`
> 共享基线：[DG-26～DG-30 自适应检索轻量开发基线](./MiLAi_DG-26-DG-30_轻量执行与审查基线.md)
> 处置：保留负结果；不重跑、不调参、不进入集成

---

# 1. 原始研究问题

DG-26 只测试：

> 在同一个 governance-gated candidate pool 和固定 `K=8` 下，加入正确的 Requirement State 语义是否比 query-only 和 shuffled-state 更好地选择 evidence？

它不增加 acquisition、不改变 pool、不执行 proof action，也不调用 Reader。

---

# 2. 已完成实现

已实现并保持 Candidate OFF：

```text
RankingStateViewV01
StateAwareCrossEncoderReranker
baseline-order fallback
fixed-pool evaluator
targeted tests
```

权威制品：

```text
var/dg26/run-lock.json
var/dg26/results.json
var/dg26/terminal.json
var/dg26/failure-index.jsonl
```

冻结规模：

```text
10 queries
15 requirement pools
327 candidate occurrences
K = 8
45 model batches / 981 pairs
1 authoritative run + 1 exact fresh-process replay
```

---

# 3. 实际结果

| Arm | Covered groups | Coverage@8 | Candidate recall@8 | AcceptedBindingPrecision | Residual recovered | R0 groups lost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| R0 baseline | 14 | 14/23 | 15/23 | 0.705882 | 0 | 0 |
| R1 query-only | 15 | 15/23 | 16/23 | 0.722222 | 1 | 0 |
| R2 correct StateView | 15 | 15/23 | 16/23 | 0.722222 | 2 | 1 |
| R3 shuffled StateView | 15 | 15/23 | 16/23 | 0.722222 | 2 | 1 |

安全与执行：

```text
Wrong COMPLETE = 0
acquisition call delta = 0
automatic retry = 0
canonical mutation = 0
authority violation = 0
formal holdout used = false
candidate feature flag = OFF
```

终态理由：

```text
R2 恢复两个 residual groups
但丢失一个 R0 baseline-correct group
且 R2 未优于 query-only R1
并与 shuffled-state R3 聚合结果相同
```

因此：

```text
C1 StateView independent ranking gain = NOT_SUPPORTED
C2 no acquisition/safety relaxation   = SUPPORTED
Final = FAIL / CORRECT_CASE_REGRESSION
```

---

# 4. 架构解释

该结果不支持继续把“固定候选池 + 固定 K + 更复杂 StateView”作为主要检索修复路线。

DG-26 暴露了三点：

1. pool 内确实存在可重新排序的信号，但正确 StateView 没有表现出独立因果增益；
2. 固定 K 让新 evidence 与 baseline evidence 竞争，导致“恢复一个、挤掉一个”；
3. DG-24 已证明更大的损失来自 channel 未调用、cutoff 和未发现，固定池重排无法恢复 pool 外证据。

所以后续不做：

```text
扩大 K 挽救 R2
Prompt sweep
更换 seed
增加 shuffled/digest controls
把 DG-26 reranker 接入默认产品
```

---

# 5. 保留与停止

保留：

```text
adapter 与 View 代码作为实验 plumbing
DG-26 结果作为 fixed-pool anti-claim
query-only R1 作为后续简单排序参考
全部失败制品
```

停止：

```text
state-aware reranker flag = OFF
不把 R1/R2 作为 DG-30 admitted component
不修改 DG-26 terminal
不覆盖 run-lock/results
```

只有未来新的、独立数据证明 first loss 主要位于固定池排序，才可以另立 successor；不能重开 DG-26。

---

# 6. 对后续 Goals 的约束

DG-27～DG-30 必须吸收本负结果：

```text
候选搜索不再固定在同一个 P/K
中间候选变化不直接算最终 correct-case regression
模型语义先进入 ProvisionalBinding
最终 AcceptedBinding/COMPLETE 集中验证
multi-channel discovery 必须先于复杂 reranking
```

DG-27 不应只消费 DG-26 R0 top-K 并强迫每个 candidate 产生唯一解释；DG-28 必须直接处理 DG-24 的 channel opportunity 和 cutoff loss。

---

# 7. 完成定义

本 Goal 已完成，不再有开发阶段。终态文件是唯一权威结论：

```text
var/dg26/terminal.json
status      = FAIL
reason_code = CORRECT_CASE_REGRESSION
```

> DG-26 的价值不是得到可发布组件，而是排除了“把更多 StateView 字段送入固定池 reranker 就能解决当前检索问题”这一假设。
