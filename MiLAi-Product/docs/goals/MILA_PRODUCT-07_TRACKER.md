---
document_id: MILA-PRODUCT-07-TRACKER
version: "1.4"
status: COMPLETE_PARKED_NO_GENERAL_EVIDENCE_GAIN
goal: MILA-PRODUCT-07@1.4
created_at: "2026-09-03T09:23:18+08:00"
updated_at: "2026-09-03T12:22:12+08:00"
---

# Product-07 轻量 Tracker

```yaml
current_stage: TERMINAL_PARKED
further_execution_authorized: false
product06_terminal: PARTIAL_PRODUCT06_LEDGER_REMOVED_READER_GAIN_UNRESOLVED
selected_current_reader: direct
model_native_reader: default_off
formal_holdout_consumed: false
opened_development_v0_consumed: true
R3_context_consumed: true
R3_answers_consumed: false
P07-H1: FAILED
P07-H2: NOT_ENTERED_BY_GATE
terminal: PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN
```

| 阶段 | 状态 | 目标 |
| --- | --- | --- |
| S0 attribution + lock | `COMPLETE_DIAGNOSTIC` | Product/V0 identities 和 Context-only 边界已固定 |
| S1 simple recall | `PARTIAL_COMPLETE` | R2=10/12、0.8889、3 shapes recovered、0 losses；Dense 未调用 |
| S2 EvidenceSet completion | `V0_PASS_R3_H1_FAIL` | B1 V0=11/12、0.9167；R3 相对 A 完整集 -2、coverage -0.0944 |
| S2 residual SHADOW | `COMPLETE_NOT_EXECUTABLE` | 2 calls / 5 queries / 0 reads；证据已在 pool，不得执行 |
| S3 consumption repair | `NOT_ENTERED_BY_H1_GATE` | 未运行 D0/D1、Answer 或 Judge |
| S4 real effect + simplify | `CONTEXT_ONLY_PARKED` | R3 Context 已消费；OpenWorker Answer effect 未进入，direct 保持 |

## 已知起点

```text
R2 direct / model-native correct             7/12 / 7/12
Product-06 all-required groups                 7/12
S1-R1 complete / coverage / regression         8/12 / 0.7222 / 2
S1-R2 complete / coverage / regression        10/12 / 0.8889 / 0
S1-R2 recovered incomplete / shapes            3 / 3
remaining required refs present in acquired    5/5
remaining required refs Reader-visible         2/5
baseline-wrong missing Evidence groups        4/5
fully covered but semantically wrong          1/5
Ledger protocol rejection in Product-06       0
query-preserving union feature flag            default OFF
Dense / reranker defaults                      OFF / none
RecallWorkspace                                implemented / default OFF / not selected
native reasoning Reader                        not implemented
S1 requested/effective Context tokens           32768 / 16384
S2 formal Product tree pin                      01ad1775...94612 / run-time valid
final delivery Product tree pin                 17df2c8f...face3 / valid
```

## S2-B1 与 R3 结果

```text
V0 B1 complete / coverage / old loss           11/12 / 0.9167 / 0
V0 same-pool gain over B0                       +1 complete / +0.0278
R3 A complete / mean group coverage             10/24 / 0.5667
R3 B1 complete / mean group coverage             8/24 / 0.4722
R3 B1 gain over A                                -2 / -0.0944
R3 recovered shapes / old-complete losses         2 / 4
R3 any-gold-session A / B1                      22/24 / 17/24
candidate/order/hydration/budget match          24/24
window closure match                            22/24
R3 Answer/Judge/Provider calls                   0 / 0 / 0
tenant leak / Canonical mutation                 0 / 0
```

B1 在 V0 恢复了至少一个 EvidenceSet，因此 B2 按计划跳过。R3-R1 至 R3-R3 是回执观测合同的
基础设施重放；`mila-p07-r3-context-b1-r4` 是权威结果。H1 失败后未运行 H2、D0/D1、
residual official reads 或 formal 500。三轮跨 case 通用修复已经用完，当前 Goal 不授权后续
执行；B1 只保留为 default-OFF 诊断代码，direct 继续作为当前路径。
