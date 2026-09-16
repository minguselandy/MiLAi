---
document_id: MILA-PRODUCT-07-SUMMARY
version: "1.3"
status: PLANNED_S2_EVIDENCESET_SELECTION_REPAIR
updated_at: "2026-09-03T11:11:41+08:00"
canonical_goal: MILA-PRODUCT-07@1.3
further_execution_authorized: false
formal_holdout_authorized: false
---

# Product-07 v1.3 固定摘要

S1 已完成两次 12-case Context-only 诊断。R2 相对 Product-06 将完整 EvidenceSet 从
7/12 提高到 10/12，平均 Reader-visible group coverage 从 0.7778 提高到 0.8889，
恢复 3 个问题形状且无旧完整例丢失。原 P07-H1 仍因未达 0.90 而不成立。

剩余两例的 5/5 required source refs 都已在 acquired results 中，但只有 2/5 进入
Reader-visible Context。首损因此是 admission/EvidenceSet selection，不是 discovery。
S2 SHADOW 已产生 5 条合法 residual query，但因 eligibility 判断使用了 visible
incompleteness 而非 full-pool absence，这些 query 只保留为 transport 证据，不得执行。

下一个修复是在同一 candidate/window closure 上比较：

```text
B1  relevance + semantic novelty + relevant-session diversity
B2  only if B1 is insufficient: one Qwen candidate-ID prioritization
```

两者都保留 original-query fallback，不使用 TypeBinding/RequirementState 控制普通召回，
不新增 Ledger、case rule 或持久状态。当前 feature 仍 default OFF，没有 Reader/Judge
效果或产品可用性结论。详细规范以稳定 Goal 为准。
