---
document_id: MILA-PRODUCT-10-TRACKER
version: "2.0"
status: PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
goal: MILA-PRODUCT-10@1.3
updated_at: "2026-09-04T02:05:50+08:00"
---

# Product-10 终态 Tracker

```yaml
current_stage: TERMINAL
terminal: PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED
execution_authorized: true
formal_holdout_authorized: true
formal_holdout_consumed: false
formal_files_accessed: true
formal_cases_scored: 0
x0: COMPLETE_24_CASES_36_GROUPS
labels: MODEL_ASSISTED_PROXY_HUMAN_PENDING_NON_GOLD
x1: COMPLETE_BEHAVIOR_NEUTRAL_FIRST_LOSS
x2_round_1: FAIL_PRODUCT10_H1
x2_round_2: FAIL_PRODUCT10_H1
x3: NOT_ENTERED_INSUFFICIENT_OPPORTUNITY
x4: NOT_ENTERED_TERMINAL_PRECEDENCE
continuation_frontier: NOT_IMPLEMENTED
public_mcp_schema_change: NONE
b1_default: OFF
mcp_product_wrapper: milai-agent-memory-mcp_0.1.1
final_product_tree: 0b170d3fdeaf962c26492578293d29a7fcc1c9036555f8adb01b121f41cba7b5
final_product_lock_digest: 4bf9ee438c92a5c4545bbcd05e940136d6f0e477f89a10cf5366663640b6d68b
```

## 核心指标

| 指标 | A0 | B1 round 2 | H1 门 |
| --- | ---: | ---: | --- |
| micro instance coverage | 29/36 | 29/36 | report |
| mean coverage | 0.84375 | 0.8854167 | gain `>=0.05` |
| mean gain | — | +0.0416667 | **FAIL** |
| newly covered groups | — | 3 | PASS `>=2` |
| gain shapes | — | 7 | PASS `>=2` |
| previously full-coverage cases lost | — | 2 | **FAIL =0** |
| corrected lost groups | — | 3 | diagnostic |
| hard collapse | — | 0 | PASS =0 |
| continuation opportunities | 1 | 2 | **INSUFFICIENT <6** |

## Block 处置

| Block | 状态 | 出口 |
| --- | --- | --- |
| X0 | `COMPLETE` | sealed labels/membership/identity/budget |
| X1 | `COMPLETE` | admission first-loss proved; no label leakage |
| X2 | `FAILED_AFTER_TWO_GENERAL_ROUNDS` | default-off; no third round |
| X3 | `NOT_ENTERED` | opportunity gate failed; continuation remains null unless Runtime-proven |
| X4 | `NOT_ENTERED` | terminal precedence stopped real Codex confirmation |

权威 run：`MiLAi-Lab/artifacts/product10/p10-x2-matched-20260904b`。summary SHA256
`6d4b1a8a…feeba`，redacted trace SHA256 `a9408eb8…a8bb1`，same-pool digest
`57527559…d8b8`。sealed summary 的 2-loss 列表由 correction receipt `167ee995…18a9d`
修正为 3 groups；其中 2 个原完整 case 退化，触发预注册 guard。其余指标与终态不变。完整逐项
审计见 `MILA_PRODUCT-10_COMPLETION_AUDIT.md`。
v3 correction `065812c5…b5659` 已将未来 runner threshold 从 group-level loss 对齐到该
case-level guard；sealed run 未改写。

## 最终实现处置

X1 tracing、内部 exact-ID candidate handoff 和安全回归保留。B1 只在软治理边界且明确开关开启时
激活，硬决策边界不改变，内部候选字段不会进入 public response。由于 effect 未通过，默认值保持
false。MCP 最终封装固定 HTTP transport/profile/zero-retry，模型参数面不扩张。

最终交付由 Lab 的 `data/locks/product10-final-product.lock.json` 独立绑定；它不覆盖 effect run 使用的
`product10-a0-product.lock.json`，因此效果身份与交付身份均可复核。
