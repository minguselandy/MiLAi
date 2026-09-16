---
document_id: MILA-PRODUCT-10-AMENDMENT
version: "1.1"
status: PLANNED_NOT_STARTED
amended_at: "2026-09-03T21:13:00+08:00"
execution_authorized: false
formal_holdout_authorized: false
---

# Product-10 Goal v1.1 不可变修订摘要

稳定 Goal 在 `MILA_PRODUCT-10_InstancePreservingEvidence与Continuation_GOAL.md`。本次设计期修订由
Product-09 独立完整性审计触发，不授权任何 effect run：

- Product-09 历史 `3/4` 只保留为 documentary observation，不能作为 Product-10 审计级对照；
- X0 必须重跑 sealed A0，并绑定 Product/Lab/input hashes、命令、时间、Codex identity 与完整
  redacted tool trace；
- formal 文件访问与 formal case scoring 分开报告；历史 loader 访问过完整文件，但未运行
  formal 500-case score；
- model-assisted turn label 必须标为 proxy，并记录 annotation/adjudication provenance；
- X4 membership、model/config、一次 primary run、system-error replacement 和非官方 scorer 的
  规则在运行前固定；
- 终态加入明确优先级，消除 PASS/PARTIAL 及 ALREADY/INSUFFICIENT 重叠。

`execution_authorized=false`，当前阶段仍为 `X0_NOT_STARTED`。
