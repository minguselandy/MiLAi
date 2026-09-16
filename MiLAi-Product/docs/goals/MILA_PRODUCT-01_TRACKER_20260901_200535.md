---
document_id: MILA-PRODUCT-01-TRACKER
version: "1.0"
status: PLAN_ONLY
created_at: "2026-09-01T20:05:35+08:00"
goal: MILA-PRODUCT-01
execution_authorized: false
---

# MiLA Product-01 轻量执行 Tracker

本表只跟踪可交付结果，不创建逐步骤 receipt。执行必须由用户另行明确授权。

## 阶段状态

| 阶段 | 目标 | 最小验证 | 当前状态 | 下一动作 |
| --- | --- | --- | --- | --- |
| S0 | fresh PostgreSQL 与本地纵向链路 | migration、真实角色、operations、worker、restart | `TODO` | 建立 Product baseline identity 与隔离数据库 |
| S1 | 真实 identity 与 Reader-visible trace | 24-case context-only preflight | `TODO` | 传播 typed `speaker/source_context` |
| S2 | grounded simple recollection | known-false replay、B0/B1 paired mediator | `TODO` | 接通 quota union、Binding 与 EvidenceSet |
| S3 | local-ready 使用体验 | golden flow、24 scenarios、100 warm | `TODO` | 完成 capture/recall/correct/revoke/restart |
| S4 | Lab 黑盒泛化确认 | 128 gate；通过后 500-case vLLM Qwen | `TODO` | Product 交付 manifest/wheel，Lab 执行 |

## 首批运行队列

| Run | 内容 | 产物 | 状态 |
| --- | --- | --- | --- |
| P01-R001 | 冻结 Product baseline identity，更新 Lab pin | manifest + concise status | `TODO` |
| P01-R002 | isolated PostgreSQL 0048/0049、真实角色与 worker 门 | S0 summary | `TODO` |
| P01-R003 | `init → doctor → start → smoke → stop` 与 MCP/OpenWorker vertical | S0 summary | `TODO` |
| P01-R004 | typed identity 传播及 unknown-identity adjacency 负控 | targeted tests | `TODO` |
| P01-R005 | 三层 trace、whole-unit admission、24-case preflight | S1 summary | `TODO` |
| P01-R006 | repaired untreated baseline B0 | Lab run reference | `TODO` |
| P01-R007 | simple B1 与 known-false Binding replay | S2 summary | `TODO` |
| P01-R008 | golden flow、24 scenarios、100 warm soak | S3 summary | `TODO` |
| P01-R009 | Lab 128-case B0/B1 matched gate | Lab metrics | `TODO` |
| P01-R010 | 条件满足时运行 500-case vLLM Qwen | Lab terminal | `CONDITIONAL` |

## 失败处理

```text
失败
→ 定位一个通用根因
→ 窄修复
→ 正反例测试
→ 只重跑受影响门
→ 通过后自动继续
```

Optional treatment 无稳定增益时，状态记为 `DROP_TREATMENT_KEEP_BASELINE`，不阻断本地产品
交付。只有权限、破坏性操作、公共 API/Schema 变更或不可替代外部依赖才暂停请求用户。

## 状态更新规则

- 同一时刻只更新一行阶段状态：`TODO → ACTIVE → PASS`。
- 可恢复失败保持 `ACTIVE`，在“下一动作”中记录根因与修复，不创建 terminal 文档。
- 每个阶段完成时更新一次 `PRODUCT_CURRENT_STATUS.md`。
- Product 开发制品留在 Product；LongMemEval cases、答案、Judge 和指标只留在 Lab。
