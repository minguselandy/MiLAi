---
document_id: MILA-PRODUCT-05-LATEST
status: ACTIVE_POINTER
current_version: "1.0"
current_version_created_at: "2026-09-02T22:49:41+08:00"
---

# MILA-PRODUCT-05 稳定入口

当前权威开发计划：

- [Product-05 v1.0 完整 Goal](MILA_PRODUCT-05_OpenWorker记忆闭环用户隔离与集合证据消费_GOAL_20260902_224941.md)
- [Product-05 执行 Tracker](MILA_PRODUCT-05_TRACKER.md)

目标路径：

```text
OpenWorker 真实对话
→ Host-owned capture/recall facade
→ submitter + reader MCP
→ tenant/RLS 隔离的 PostgreSQL-backed Memory
→ restart 后可召回
→ Qwen 对集合证据做 grounded 消费
```

五个 Block：

```text
B0 基线对齐
B1 OpenWorker write/read/restart/two-user 闭环
B2 固定 Context 证据消费实验
B3 多类型真实 LME 修复循环
B4 最小通过产品交付
```

本文件只是不随版本变化的导航入口。执行规范、硬门、失败续跑、参考项目映射和
终态决策以上述时间版本为准。
