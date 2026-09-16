---
document_id: MILA-PRODUCT-10-READ-ONLY-AUDIT-AMENDMENT
version: "1.1"
status: READ_ONLY_PREPARATION_COMPLETE
goal: MILA-PRODUCT-10@1.1
amended_at: "2026-09-03T21:13:00+08:00"
execution_authorized: false
formal_holdout_authorized: false
---

# Product-10 只读审计修订快照

独立同族 provisional 审计判词为
`FAIL / CLAIM_EVIDENCE_MISMATCH_AND_UNSEALED_EVALUATION`。该 FAIL 针对 Product-09 historical
evaluation provenance，不是 Product-10 方法结果。

Product-09 的 normalized EM/F1 `3/4 / 0.75` 只保留为 documentary observation。历史制品未绑定
Product tree/lock、Lab/input hashes、exact Codex identity 或完整 tool trace；restart 只重启
API/worker/MCP，turn visibility 是 Qwen model-assisted proxy，formal 500 文件被读取后取子集但
没有执行 formal 500-case scoring，tool choice 由 prompt 规定。

因此 Product-10 必须在 X0 合同下重跑 sealed A0；当前 `execution_authorized=false`，X0--X4 均
未启动。静态 identity/continuation 证据仍以 `MILA_PRODUCT-10_READ_ONLY_AUDIT_20260903_210412.md`
为准，完整独立审计位于 `../../../MiLAi-Lab/EXPERIMENT_AUDIT.md`。
