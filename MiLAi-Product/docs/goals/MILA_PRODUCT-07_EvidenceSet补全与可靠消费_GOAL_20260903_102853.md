---
document_id: MILA-PRODUCT-07
version: "1.2"
status: PLANNED_REBASE_FROM_UNSEALED_WIP
updated_at: "2026-09-03T10:28:53+08:00"
supersedes: MILA-PRODUCT-07@1.1
execution_authorized: false
formal_holdout_authorized: false
---

# Product-07 v1.2 固定摘要：EvidenceSet 补全与可靠消费

完整规范位于 `MILA_PRODUCT-07_模型引导证据补全与通用召回_GOAL.md`。

当前问题锚点：

```text
any gold session recalled                91.7%
all required Evidence groups recalled    58.3%
```

v1.2 将 Product-07 顺序冻结为：

```text
S0  审查 default-OFF、未封存的 query-preserving-union WIP
S1  original-query FTS + configured Dense + governed locality candidate pool
S2  lightweight RecallWorkspace + marginal EvidenceSet coverage
    仅在 pool 缺证据时执行一次 observation-driven residual recall
S3  仅在完整 Context 上测试 Qwen native reasoning 消费
S4  真实 OpenWorker 24-case 验证并删除无独立增益的组件
```

普通 recall 不由 TypeBinding 或 RequirementState 控制检索。RecallWorkspace 是请求内软状态，
不能 hard-drop 原始候选、授予 COMPLETE 或持久化为第二套 Memory State。当前只授权文档修订。
