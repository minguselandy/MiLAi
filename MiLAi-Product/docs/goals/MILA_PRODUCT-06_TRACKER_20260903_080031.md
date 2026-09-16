---
document_id: MILA-PRODUCT-06-TRACKER
version: "1.1"
status: PLANNED_AWAITING_EXECUTION_AUTHORIZATION
goal: MILA-PRODUCT-06@1.1
created_at: "2026-09-03T08:00:31+08:00"
updated_at: "2026-09-03T08:00:31+08:00"
---

# Product-06 轻量执行 Tracker

```yaml
current_stage: R0
execution_authorized: false
selected_reader: direct
candidate_reader: model_native_vllm
strict_ledger_disposition: superseded_as_candidate_design
formal_holdout_consumed: false
P06-H1: NOT_RUN
P06-H2: NOT_RUN
terminal: null
```

Product-06 v1.1 已接受用户修正：`EvidenceLedgerV01` 是模型的结构化证据草稿，不是数据库
账本。下一步不是给 Ledger 增加规则，而是用 vLLM 承载 model-native Reader session，允许
Qwen 自主理解证据并按需调用一个通用 calculator；Host 只治理工具安全、可见引用、预算
和单次终态交付。

| 阶段 | 状态 | 目标 |
| --- | --- | --- |
| R0 Ledger replay + vLLM probe | `NOT_STARTED` | 选择 native tool 或 minimal action transport |
| R1 model-native Reader | `NOT_STARTED` | 一个 Reader session、一个 calculator、一个 final path |
| R2 12-case fixed Context | `NOT_STARTED` | P06-H1 |
| R3 24-case real OpenWorker | `NOT_STARTED` | P06-H2 |
| R4 simplify and deliver | `NOT_STARTED` | select new Reader or keep direct |

## Compact repair log

| Time | Failure family | Cross-case cause | General repair | Targeted | Slice | Next |
| --- | --- | --- | --- | --- | --- | --- |
| pending | pending | pending | pending | pending | pending | pending |

## Frozen boundaries

```text
TypeBinding / typed operand / COMPLETE authority remain rejected
no new database schema, MCP tool, QueryIR enum, or Canonical writer
no case-specific rule, seed search, vote, or hidden semantic retry
direct remains current default until P06-H1 and P06-H2 pass
formal LongMemEval 500 remains untouched
```
