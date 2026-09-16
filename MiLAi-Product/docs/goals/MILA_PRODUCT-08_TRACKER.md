---
document_id: MILA-PRODUCT-08-TRACKER
version: "1.1"
status: PASS_PRODUCT08_CODEX_HTTP_MCP_USABLE
goal: MILA-PRODUCT-08@1.1
updated_at: "2026-09-03T20:15:00+08:00"
---

# Product-08 轻量 Tracker

| 阶段 | 状态 | 当前证据 / 下一动作 |
| --- | --- | --- |
| P08-0 HTTP facade | `PASS` | MCP 62 tests；Bearer reject；health/readiness；fixed scope；stdio compatibility |
| P08-1 Codex HTTP | `PASS` | Codex 0.151.0 URL mode：required 1 call、no-memory 0 call、continuation 2 calls；3/3 exact |
| P08-2 Host scope | `PASS` | Codex 是唯一 P08 验收 Host；Claude 不再是前置 |
| Host capture | `SUCCESSOR` | 已有 Host-only adapter/unit；PG replay/restart 归入后续 write-path Goal |
| Coding usability | `SUCCESSOR` | 使用真实数据库评估检索效果，不回溯改变 P08 transport PASS |

```yaml
selected_mcp_profile: agent-memory
selected_wire_contract: memory-evidence-context-v1
product_transport: streamable-http
product_endpoint: http://127.0.0.1:7337/mcp
acceptance_host: codex
model_backend: none
bearer_auth_required: true
fixed_server_owned_scope: true
openworker_stdio_reader_lite_compatibility: preserved
old_product08_context_candidate: default_off_historical_input
database_migration: none
canonical_authority_change: none
formal_500_consumed: false
schema_freeze: false
product_tree_sha256: d866c5ff82f67bacc7594be4cddb159e1d0181bf8eb4f71a309185883ff0cc1a
product_tree_file_count: 329
lab_product_lock_digest: 5b15eb6c2c592f4ae0dc50bd0e639f3833ab164652da6fe9f998350a568fc386
product_pin_valid: true
```

失败只记录首次边界、通用修复和复测结果。不要为阶段性失败创建新的 Goal 编号或 receipt 树。
