---
document_id: MILA-PRODUCT-07-TRACKER
version: "1.1"
status: PLANNED
goal: MILA-PRODUCT-07@1.1
created_at: "2026-09-03T09:23:18+08:00"
updated_at: "2026-09-03T09:37:34+08:00"
---

# Product-07 v1.1 初始 Tracker 快照

```yaml
current_stage: S0_NOT_STARTED
execution_authorized: false
P07-H1_EvidenceCoverage: NOT_RUN
P07-H2_ConsumptionAndEndToEnd: NOT_RUN
selected_current_reader: direct
native_reasoning_reader: default_off
residual_recall: default_off
formal_holdout_consumed: false
```

执行顺序：S0 归因与锁定 → S1 simple union → 必要时 S2 residual recall → S3 完整 Evidence
消费修复 → S4 真实 OpenWorker 验证与简化。普通失败按共享机制修复后继续；不创建 case 规则。
