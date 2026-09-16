---
document_id: MILA-PRODUCT-06-TRACKER
version: "1.0"
status: PLANNED_AWAITING_EXECUTION_AUTHORIZATION
goal: MILA-PRODUCT-06@1.0
created_at: "2026-09-03T07:48:12+08:00"
updated_at: "2026-09-03T07:48:12+08:00"
---

# Product-06 轻量执行 Tracker

## 当前状态

```yaml
current_stage: R0
execution_authorized: false
opened_development_lme_authorized: false
formal_holdout_consumed: false
selected_path: null
selected_reader: direct
P06-H1: NOT_RUN
P06-H2: NOT_RUN
terminal: null
```

Product-05 的 Memory lifecycle 已通过，Product-06 不重开持久化与用户隔离。当前只允许
评审 Goal；尚未授权 vLLM 调用、数据冻结、实验运行或产品行为修改。

## 阶段进度

| 阶段 | 状态 | 产物/决定 |
| --- | --- | --- |
| R0 固定 Context 瓶颈诊断 | `NOT_STARTED` | D0–D3 first-loss matrix |
| R1 一个最小机制 | `NOT_STARTED` | Path A/B/C 中至多一个首选实现 |
| R2 12-case 固定 Evidence 验证 | `NOT_STARTED` | P06-H1 |
| R3 24-case 真实 OpenWorker 确认 | `NOT_STARTED` | P06-H2 |
| R4 产品收口与简化 | `NOT_STARTED` | selected/default/fallback/terminal |

## R0 决策表

| Case hash | Family | D0 | D1 | D2 | D3 member recall | First loss | Selected implication |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pending | pending | pending | pending | pending | pending | pending | pending |

## 修复记录

每次失败只追加一行；禁止粘贴完整 transcript 或建立重复 receipt。

| Time | Family | First loss | Cross-case evidence | General repair | Targeted result | Slice result | Next |
| --- | --- | --- | --- | --- | --- | --- | --- |
| pending | pending | pending | pending | pending | pending | pending | pending |

## 当前不变量

```text
direct Reader remains default
TypeBinding remains rejected
public API/schema/migration change unauthorized
Canonical authority unchanged
formal 500-case holdout untouched
```

