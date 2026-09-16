---
document_id: MILA-PRODUCT-02-TRACKER
version: "1.0"
status: PLANNED_AWAITING_EXECUTION_AUTHORIZATION
created_at: "2026-09-02T00:01:11+08:00"
goal: MILA-PRODUCT-02
execution_authorized: false
---

# MiLAi Product-02 轻量执行 Tracker

本 Tracker 是唯一日常执行记录。单点开发失败不创建 terminal/receipt；只更新一行 issue，修复后继续。

## 阶段状态

| 阶段 | 目标 | 最小验证 | 状态 | 下一动作 |
| --- | --- | --- | --- | --- |
| U0 | 当前 S4 repair 与真实指标基线 | Wrong COMPLETE 正反例、turn/span metric、单 case trace | `PLANNED` | 激活后只读审阅 dirty diff |
| U1 | answer-turn-first 一次 acquisition | A0/A1/A2 targeted + 24-case | `WAITING_U0` | direct-turn quota 与 local atomic expansion |
| U2 | Requirement EvidenceSet 与 operator | failure-family 单点修复、known-false、24/128 | `WAITING_U1` | AcceptedBinding-only 与 role-first packing |
| U3 | 本地可用性交付与 128/500 决策 | golden flow、24、100 warm、fresh 128 | `WAITING_U2` | 128 entry PASS 后才考虑 500 |
| U4 | 条件式复杂能力 | 每种能力独立 Entry/Effect | `NOT_ENTERED_NO_MEASURED_OPPORTUNITY` | 不影响 Core 完成 |

## 首批运行队列

| Run ID | 阶段 | 目的 | 范围 | 状态 |
| --- | --- | --- | --- | --- |
| P02-R001 | U0 | 审阅当前未提交 repair | 3 dirty files，只读 diff | `PLANNED` |
| P02-R002 | U0 | Wrong COMPLETE 单点正反例 | 1 known-false + 1 legal operator | `WAITING` |
| P02-R003 | U0 | 修正 session/span 指标 | Lab metric unit + 2 trace fixtures | `WAITING` |
| P02-R004 | U1 | direct-turn quota | 1 failed + 1 correct + 1 cross-session negative | `WAITING` |
| P02-R005 | U1 | bounded local expansion | 8-case micro-slice | `WAITING` |
| P02-R006 | U1 | acquisition 24-case gate | A0/A1/A2 context-only | `WAITING` |
| P02-R007 | U2 | multi-operand EvidenceSet | one failure family at a time | `WAITING` |
| P02-R008 | U2 | temporal/current operator | AcceptedBinding-only fixtures | `WAITING` |
| P02-R009 | U2 | role-first atomic Context | 24-case answer/context | `WAITING` |
| P02-R010 | U3 | local Product handoff | golden flow + 24 + 100 warm | `WAITING` |
| P02-R011 | U3 | matched decision | fresh 128 B0/B1/B2 | `WAITING` |
| P02-R012 | U3 | conditional confirmation | 500-case Qwen | `CONDITIONAL_128_PASS` |

## 单点 Issue / Reflection

| ID | 阶段 | 最早首损 | 代表 case/fixture | 根因假设 | 单一改动 | 正反例结果 | 状态 | 反思/下一步 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P02-I001 | U0 | OPERATOR | Product-01 S4 strict false COMPLETE | Raw lookup/operator result 仍可间接提升 COMPLETE | 待审阅当前 dirty repair | 未运行 | `PLANNED` | 不扩大检索，先闭合 authority |
| P02-I002 | U0 | HARNESS | `reader_visible_gold_span_coverage` | session proxy 被命名为 span coverage | 重命名并新增 exact turn/span 指标 | 未运行 | `PLANNED` | 后续效果只用真实可见证据归因 |
| P02-I003 | U1 | ADMISSION | session hit / answer-turn miss family | session/global score 未定位 answer turn | direct-turn + bounded local atomic admission | 未运行 | `PLANNED` | 不先上 Formation/Graph |

新增 issue 时只增加一行；同一根因的后续尝试更新原行，不复制新文档。

## 自动执行规则

```text
PASS
→ 更新当前阶段
→ 自动激活下一 WAITING 阶段

RECOVERABLE FAILURE
→ 当前阶段保持 ACTIVE_REPAIR
→ 单 case 重放
→ 一个通用修复
→ 正例 + 对照 + 负控
→ 8/24/128 逐级恢复

OPTIONAL NO EFFECT
→ PARKED_NO_EFFECT
→ 回退简单 profile
→ 继续 Core
```

只有以下条件暂停请求用户：

```text
需要 public API 或 PostgreSQL schema 变更
需要默认启用复杂 feature
需要破坏性数据操作
权限或目标范围不明确
不可替代的外部依赖阻塞
```

## 状态写入规则

- 同一时刻最多一个 Core 阶段为 `ACTIVE` 或 `ACTIVE_REPAIR`；
- 可并行的是该阶段内部互不依赖的 unit/static/adapter 或不同 Lab model pools；
- 可恢复失败不写 `FAIL` terminal；
- treatment 无增益只关闭 treatment，不把 Product 标为失败；
- 阶段完成时更新一次 `PRODUCT_CURRENT_STATUS.md`；
- 只有 128/500 sealed run 在 Lab 保存正式四件套；
- Product 代码和文档不得包含 LongMemEval case ID、gold text 或 Judge prompt。

## Core 完成检查

- [ ] U0 PASS
- [ ] U1 选择最简单有效 acquisition
- [ ] U2 strict Wrong COMPLETE = 0
- [ ] U2 EvidenceSet/atomic Context 完成
- [ ] U3 local Product gate PASS
- [ ] U3 fresh 128 decision 完成
- [ ] 500 仅在 entry PASS 时运行
- [ ] U4 可以全部 NOT_ENTERED/PARKED，而不影响 Core PASS
- [ ] Schema 仍为 `NO-GO FOR FREEZE`
