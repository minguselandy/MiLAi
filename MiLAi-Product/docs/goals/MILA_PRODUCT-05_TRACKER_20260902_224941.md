---
document_id: MILA-PRODUCT-05-TRACKER
version: "1.0-initial"
status: ACTIVE
goal: MILA-PRODUCT-05@1.0
created_at: "2026-09-02T22:49:41+08:00"
---

# Product-05 执行 Tracker（初始快照）

## 当前位置

```yaml
current_block: B0
current_activity: reconcile_product04_post_terminal_replay_and_freeze_baseline
P05-H1: NOT_TESTED
P05-H2: NOT_TESTED
formal_holdout_consumed: false
```

## Block 进度

| Block | 状态 | 完成条件 |
| --- | --- | --- |
| B0 | `IN_PROGRESS` | 真实 replay、模型身份、baseline 与 first-loss taxonomy 已对齐 |
| B1 | `PENDING` | 真实 write/read/restart 与同库双 tenant 零泄漏 |
| B2 | `PENDING` | 固定 Context 上选出最小通过消费协议 |
| B3 | `PENDING` | 6 → 12 → 24 多类型真实 OpenWorker LME |
| B4 | `PENDING` | 产品决策、全量受影响验证、文档与回滚 |

## 已知基线

| 事实 | 值 |
| --- | --- |
| Product-04 terminal | `PASS_PRODUCT04_READER_AVAILABILITY_WITHOUT_TYPEBINDING` |
| Product tree before Product-05 | `04b356531db615de7dcd68af036669ef8d88371013af513b89cd1228aeb13f20` |
| real replay | 2 cases, 923/923 captures, 2 MCP resolve, 2 Qwen calls |
| ordinary lookup | 1/1 pass |
| multi-session count | 0/1 pass; all gold groups Reader-visible |
| formal 500 | not consumed |

## 最小失败记录

实施后只在此表和 Lab `failure-ledger.jsonl` 记录有意义失败：

| occurrence | first loss | family evidence | general root cause | repair | counterexamples | status |
| --- | --- | --- | --- | --- | --- | --- |
| P05-F000 | READER_CONSUMPTION | multi-session count; evidence visible | prompt-only reading does not force explicit member accounting | pending B2 | lookup + paraphrase + false-member negative | OPEN |

## 自动续跑规则

```text
PASS block
→ mark completed
→ immediately enter next block

recoverable failure
→ first-loss localization
→ compare another same-family case
→ smallest general repair
→ narrow test
→ family rerun
→ current-slice rerun
→ continue
```

只在跨 tenant 泄漏、Canonical 越权、Evidence 损坏、破坏性操作不确定或外部服务持续不可用时停止。

## 当前禁止

```text
case/gold 进 Product
TypeBinding 复活
subject_id 作安全用户边界
没有 first-loss 证据就扩 Top-k
模型宣告 COMPLETE/Canonical commit
formal 500-case
```
