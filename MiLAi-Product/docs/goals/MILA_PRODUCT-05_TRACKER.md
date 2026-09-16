---
document_id: MILA-PRODUCT-05-TRACKER-LATEST
version: "1.1"
status: COMPLETE_PARTIAL
goal: MILA-PRODUCT-05@1.0
updated_at: "2026-09-03T03:55:00+08:00"
---

# Product-05 执行 Tracker

## 终态

```yaml
current_block: B4
current_activity: terminal_delivery
P05-H1: PASS
P05-H2: UNRESOLVED_AFTER_THREE_GENERAL_REPAIRS
selected_reader: direct
terminal: PARTIAL_PRODUCT05_MEMORY_LIFECYCLE_USABLE_READER_CONSUMPTION_UNRESOLVED
formal_holdout_consumed: false
```

Product-05 完成了真实 OpenWorker 写入、持久化、召回和 tenant 隔离闭环。固定 Context
证据消费实验没有建立预注册增益，因此 `direct` 继续作为默认 Reader；`inventory`、
`grounded` 和 `ledger` 均未被选中或默认开启。产品仍是 `0.1.0-candidate`，Schema 仍为
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。

## Block 结果

| Block | 状态 | 结果 |
| --- | --- | --- |
| B0 | `PASS` | Product-04 后真实 replay、Qwen/tokenizer、direct baseline 与 first-loss taxonomy 已对齐 |
| B1 | `PASS` | 同一 fresh PostgreSQL 上 2 tenant 的真实 write/read/restart/idempotency 门通过 |
| B2 | `UNRESOLVED` | A/B/C/D 均未达到固定 Context 的 P05-H2 门 |
| B3 | `NOT_ENTERED_BY_GATE` | 没有最小通过 treatment，因此未运行 24-case S2 confirmation |
| B4 | `PASS_PARTIAL_DELIVERY` | direct 保留；完整受影响门与 fresh PostgreSQL 纵向门通过 |

## P05-H1：可用 Memory 生命周期

最终纵向门：`MiLAi-Lab/var/runs/mila-p05-e1-final-20260903035224/summary.json`。

```text
shared PostgreSQL / tenants                         1 / 2
source identity integrity                          1.0
capture / projection                               10/10 / 10/10
restart recall                                     2/2
native OpenWorker operations / Qwen calls          5 / 5
assistant support lineage                          1.0
cross-tenant read / write / projection leaks       0 / 0 / 0
idempotent replay duplicate rows                   0
captured Context, system, or secret payloads        0
assistant self-amplification                       0
model-visible submitter/operator tools             0
unauthorized Canonical mutations                   0
automatic semantic retries                         0
```

Host 在 provider 终态后用独立 submitter socket 结算 exact user/assistant message identity。
assistant Evidence 保留 `memory_support_refs`，再次召回时不会被伪装为独立 user fact。
`tenant_id` 仍由可信 Runtime 部署身份决定；相同 `subject_id` 不会合并 tenant。

## P05-H2：固定 Context 证据消费

所有有效比较均使用同一病例内完全相同的 Reader Context bytes、别名集合和预算，
`temperature=0`、`top_p=1`，无投票或自动语义 retry。

| 方法 | 代表证据 | 结果 |
| --- | --- | --- |
| A direct | S1 corrected scorer | 8/12；保留为默认 |
| B inventory | S1 | 7/12；有正确 direct 回归，未通过 |
| C one-pass `GroundedEvidenceUseV01` | S1 r5 | 8/12 after scorer audit；仅 1 个 gain family，且存在回归、算术一致性 0.8 |
| D ledger → grounded final，r1 | S0 | direct 4/6，D 4/6；+1/-1，未通过 |
| D ledger → grounded final，r2 | S1 | 原始 summary 为 8/12 vs 8/12；abstention scorer audit 去除假回归，但增益仍不足且算术一致性 0.6 |
| D 独立 ledger → 结构化 final，r3 | B2 / 13 | 4 例被 Host 以 `EVIDENCE_USE_CALCULATION_INVALID` 拒绝；可执行 9 例中 7/9 vs 6/9，仅 +1、1 个 family |

r3 的 provider 两阶段调用本身均成功；Host 验证拒绝后 OpenCode 重发原 operation，形成
4 次可见 transport repeat。该 run 正确终结为 `FAIL_EXECUTION`，不能进入 effect 分母。
这证明 D 仍不稳定，而不是外部 Qwen/数据库故障。依 Goal 的三轮上限停止继续调 Prompt、
schema 或阈值；P05-H2 标为 `UNRESOLVED`。

无 treatment 达到以下联合门：别名 100%、显式算术 100%、普通 lookup 回归 0、至少新增
3 个正确 case 且横跨至少 2 个能力族、unsupported answer 0。因此没有冻结 treatment，
也没有运行只允许“最小通过方法”进入的 S2。

## 通用机制与边界

本轮交付的产品机制：

- `OpenWorkerMemoryFacade` 组合 reader 与独立 submitter lane；
- 流式和非流式 completion 均在完整 provider 终态后一次结算；
- 源 session/message/turn/time identity 原样进入 Evidence，replay key 不依赖采集时间；
- 只捕获原始 user/assistant 内容，不捕获注入的 Memory Context、system prompt 或 secret；
- Host 可验证结构化 schema、可见别名、显式 members 与算术自洽，但不认证事实真值、
  集合完备性、Raw typed operand、Requirement `COMPLETE` 或 Canonical state；
- 未改 public MCP/API、数据库 migration、权限模型或 Canonical authority。

## B4 验证

```text
OpenWorker MCP full tests             150 passed
MCP full tests                         54 passed
Lab full tests                         56 passed
OpenWorker / Lab Ruff                  PASS / PASS
OpenWorker strict mypy                 PASS (13 source files)
Lab strict mypy                        PASS (26 source files)
OpenWorker / Lab wheel + sdist         PASS / PASS
fresh PostgreSQL lifecycle             PASS
Product tree                           18e29cd9...a2982 (318 files)
Product-05 Lab lock                    af87d759...6f3ab
```

一次无数据库环境变量的额外 Runtime 全套诊断得到 736 passed / 43 skipped，其数据库用例
按设计因缺少 DSN 失败；它不计作 B4 门。随后由上述自建 fresh PostgreSQL 生命周期门完成
真实数据库验证。

## 回滚与保留项

- 不传 `--submitter-socket` 与 `--memory-subject-id` 即回到只读 Host；
- `--evidence-use-mode` 默认值保持 `direct`；
- `inventory`、`grounded`、`ledger` 只保留为 default-OFF 实验实现，不构成支持承诺；
- 回滚 Host 能力不删除已写 Evidence，也不修改 Canonical State；
- formal LongMemEval 500-case 未进入、未消费。

失败细节与唯一终态由 Lab 的 `var/product05/failure-ledger.jsonl` 和
`var/product05/terminal.json` 保存。
