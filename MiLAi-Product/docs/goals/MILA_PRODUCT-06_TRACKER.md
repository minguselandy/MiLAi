---
document_id: MILA-PRODUCT-06-TRACKER
version: "1.2"
status: COMPLETE_PARTIAL
goal: MILA-PRODUCT-06@1.1
created_at: "2026-09-03T08:00:31+08:00"
updated_at: "2026-09-03T09:08:15+08:00"
---

# Product-06 轻量执行 Tracker

```yaml
current_stage: R4_COMPLETE
execution_authorized: true
selected_reader: direct
candidate_reader: model_native_vllm
strict_ledger_disposition: superseded_as_candidate_design
formal_holdout_consumed: false
P06-H1: NOT_MET
P06-H2: NOT_ENTERED_BY_GATE
terminal: PARTIAL_PRODUCT06_LEDGER_REMOVED_READER_GAIN_UNRESOLVED
```

Product-06 已完成 PARTIAL 收口。`EvidenceLedgerV01` 被定位为失败的模型草稿合同，而非
数据库或 Memory State；新 model-native Reader 通过了真实链路与安全边界，但没有建立
相对 direct 的预注册准确率增益。direct 继续默认，旧 structured modes 和 model-native 都
不构成可靠性承诺。

| 阶段 | 状态 | 目标 |
| --- | --- | --- |
| R0 Ledger replay + vLLM probe | `PASS` | strict Ledger 未成功 6 例：协议 4、语义 2；选择 `minimal_action_v1` |
| R1 model-native Reader | `PASS` | 一个 Reader session、一个 calculator、一个 final path |
| R2 12-case fixed Context | `H1_NOT_MET` | 更正评分后 direct 7/12、B2 7/12，新增 0；所有安全/执行门通过 |
| R3 24-case real OpenWorker | `NOT_ENTERED_BY_GATE` | H1 未通过，预冻结 case 未消费 |
| R4 simplify and deliver | `PASS_PARTIAL` | direct 保持默认，B2 保留 default-OFF 诊断路径 |

## Compact repair log

| Time | Failure family | Cross-case cause | General repair | Targeted | Slice | Next |
| --- | --- | --- | --- | --- | --- | --- |
| 08:57 | Harness contract | direct 的 evidence pass 0 被误当 provider request 0 | 分离两种 cardinality | 11 tests | R2 12/12 executed | complete |
| 09:02 | Harness scorer | 合法 abstention 中 `any records/information` 未被识别 | 扩展通用 abstention marker | 11 tests | corrected B2 7/12 | complete |
| 09:03 | Context ceiling | 4/5 baseline miss 缺必需 Evidence group | 未修改 retrieval；遵守禁止项 | exact trace audit | H1 unattainable | PARTIAL |

## R0 根因

```text
Product-05 unsuccessful strict-Ledger denominator     6
TOOL_PROTOCOL / Host rejection                       4 (66.7%)
model semantic miss                                  2 (33.3%)
storage / retrieval / tenant failure                 0
```

四个协议失败均为 `EVIDENCE_USE_CALCULATION_INVALID`，随后触发可见 operation repeat。vLLM
endpoint 的 native named/auto tool 均返回 HTTP 400，因此冻结 structured minimal action
transport；标准 assistant `tool_calls` 和 `tool` role 回注 live smoke 返回了正确 `10%`。

## R2 更正后结果

权威判定：`MiLAi-Lab/var/product06/r2-summary.json`。原始 answers、Context 和 trace 均未修改；
只更正两个明确拒答的 deterministic scorer 假阴性。

```text
paired completed / exact Context                 12/12 / 1.0
direct / model-native correct                     7/12 / 7/12
new correct / net / gain families                 0 / 0 / 0
ordinary lookup losses / all losses               0 / 0
unsupported / invalid citation                     0 / 0
Host rejection / Reader fallback                   0 / 0
transport repeat / semantic retry / votes          0 / 0 / 0
tenant leak / Canonical mutation                   0 / 0
```

Reader-visible required-Evidence-group recall 只有 0.5833。5 个 direct 错例中只有 1 个拥有全部
必需 Evidence groups，另外 4 个分别缺少 fish total、Hawaii price、grandparent ages 或一个
cocktail evidence group。Reader 不能在“不发明事实”的约束下补回这些信息，而扩大 retrieval
又是 Goal 明文禁止的修复。因此未消耗两次 Reader Prompt 修复预算，也不进入 R3。

## R4 验证

```text
OpenWorker MCP tests / Ruff / strict mypy       175 / PASS / PASS (14 files)
OpenWorker wheel + sdist                        PASS
Lab tests / active Ruff / strict mypy            59 / PASS / PASS (26 files)
Lab active import boundary / wheel + sdist       PASS / PASS
Product-06 R2 / final R4 pins                    PASS, same tree bd5240ab…e694
fresh PostgreSQL real chain                      PASS via R2, 12 tenants / 24 operations
formal 500                                       NOT ENTERED / NOT CONSUMED
```

## Frozen boundaries

```text
TypeBinding / typed operand / COMPLETE authority remain rejected
no new database schema, MCP tool, QueryIR enum, or Canonical writer
no case-specific rule, seed search, vote, or hidden semantic retry
direct remains current default until P06-H1 and P06-H2 pass
formal LongMemEval 500 remains untouched
```
