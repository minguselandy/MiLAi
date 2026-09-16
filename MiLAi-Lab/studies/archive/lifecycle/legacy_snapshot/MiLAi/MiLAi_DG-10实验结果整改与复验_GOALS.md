# MiLAi 最新 Goals：DG-10 完成态与后续受控使用计划

> Goal ID：`DG-10`  
> 文档版本：`0.5.0 FINAL — CLOSED / ACCEPTED`  
> 完成日期：`2026-08-23`（Asia/Shanghai）  
> 最终声明：`MILAI_PREFETCH_AGENT_READY`  
> 当前 Goal 状态：`CLOSED`  
> 后继目标：`DG-11 MEMORY QUALITY / AGENT EFFICIENCY — PROPOSED / READY FOR EXECUTION`  
> 唯一已验证 Provider：`self-hosted vLLM 0.27.1 / Qwen3.6-35B-A3B-FP8`  
> 数据边界：`SYNTHETIC / DEIDENTIFIED ONLY`  
> Logical Architecture：`1.0.0 FROZEN`  
> Runtime：`0.1.x CANDIDATE`  
> Schema：`0.1.x EXPERIMENTAL / NO-GO FOR FREEZE`  
> Dynamic-tool profile：`NOT CLAIMED`  
> 外部 Provider：`OE-F06 OPEN / PARKED`

---

# 0. 最新结论

DG-10 已完成并关闭。当前允许声明：

```text
MILAI_MCP_MEMORY_FUNCTIONAL = PASS
MILAI_PREFETCH_AGENT_READY  = PASS
MILAI_DYNAMIC_TOOL_AGENT_READY = NOT CLAIMED
```

完成含义：

```text
可安装 MiLAi MCP packages
→ 真实 Runtime / PostgreSQL
→ governed submit
→ 跨会话 recall
→ OpenWorker host-owned memory_mode
→ compact canonical-safe context
→ self-hosted vLLM answer
→ trace / usage / terminal ledger
→ revoke / conflict / OpenIssue / Scope / restart / degrade / rollback
```

所有 blocking RM（`RM-00～RM-09`、`RM-12～RM-15`）均为 `PASS`。`RM-10/RM-11`
没有启动，因为最终候选不声明模型自主选择工具的 dynamic-tool profile；它们不影响
`MILAI_PREFETCH_AGENT_READY`。

DG-10 下没有剩余开发任务。后续若继续工作，应开启新的受控使用目标，不得在已关闭 Goal 下继续
追加 candidate、审计或 Benchmark 版本。

---

# 1. 事实源与优先级

最新状态按以下顺序解释：

```text
1. controlled-adjudication.json
   = 最终受控接受决定

2. final-report.json
   = 最终工程、功能、质量、性能与声明结果

3. current-state.json
   = RM 与 functional case 的运行状态

4. frozen candidate / review workspace
   = 被审阅的只读产品、合同、测试和证据闭集

5. 本文
   = 最新 Goal 状态摘要与后续工作边界
```

权威材料：

| 材料 | 路径 | SHA-256 |
| --- | --- | --- |
| 最终状态 | `var/dg10/current-state.json` | `aadc8ec5476eeab8981af2d007afb5756c0ca723dc908d23f9481f89cc3dda00` |
| 最终报告 | `var/dg10/final/final-report.json` | `6268d17aa9e3f944f09ed1b0c273fd742945aeec6b5fbc477f79efab6df02c07` |
| 受控裁决 | `var/dg10/final/controlled-adjudication.json` | `11915210213bf51dfe92b88b2763b2bf2983a64db693c090e762b982a29f65a3` |
| 候选 inventory | `var/dg10/final/candidate/inventory.json` | `e134807d745bf30e2e464d9a875edb3af571b3651bf3152f3ae43f72d26ecf6a` |
| Freeze manifest | `var/dg10/final/candidate/freeze-manifest.json` | `c64ed9a9b69ac36ba4ea5a91e0be5a9350bfefec8e30316b4be02e7aedb84562` |
| 已执行 Goal 合同 | `var/dg10/final/review-workspace/GOALS.md` | `0e42270e275b2ba3d08b7974e1f6b77d77a28b68d8c0bfbb88aec1c55907729f` |
| Review workspace inventory | `var/dg10/final/review-workspace/inventory.json` | `27b7f30300a7e88ef099401abe01933d4f46c7f98880500b4273a25a01bcf24c` |

`current-state.json` 的 `goal` 字段记录第一里程碑 `MILAI_MCP_MEMORY_FUNCTIONAL`；最终发布声明以
`final-report.json.release_claim` 和受控裁决 disposition 为准，两者均支持
`MILAI_PREFETCH_AGENT_READY`。

---

# 2. DG-10 完成矩阵

| ID | 最终状态 | 最后运行 | 完成能力 |
| --- | --- | --- | --- |
| `RM-00` | `PASS` | `rm00-workflow-20260823-002` | 开发期 AI 审计为 0，移除审计驱动执行依赖 |
| `RM-01` | `PASS` | `t2-openworker-20260823-009` | Provider gateway、预算、native usage 与终态稳定 |
| `RM-02` | `PASS` | `f0-package-20260823-012` | MCP/Client/OpenWorker/Runtime packages 可 fresh install |
| `RM-03` | `PASS` | `f0-native-20260823-011` | governed submit、query/context、跨会话 recall、revoke、restart |
| `RM-04` | `PASS` | `freeze-preflight-20260823-003` | Context、召回和 Memory 预算达到候选门 |
| `RM-05` | `PASS` | `lme-confirmation-20260823-003` | 公平三臂 LongMemEval confirmation 通过 |
| `RM-06` | `PASS` | `freeze-preflight-20260823-003` | T2 `24/24` 稳定终态 |
| `RM-07` | `PASS` | `serving-minimal-20260823-006` | T3a prefetch Agent 路径可用且无额外模型轮 |
| `RM-08` | `PASS` | `lme-confirmation-20260823-003` | 质量、Token 与非劣门通过 |
| `RM-09` | `PASS` | `hardened-openworker-20260823-010` | Scope/OpenIssue/revoke/cache/重启/降级安全通过 |
| `RM-10` | `NOT_STARTED / NON_BLOCKING` | — | BFCL single-turn/no-call；未声明 dynamic-tool |
| `RM-11` | `NOT_STARTED / NON_BLOCKING` | — | BFCL multi-turn；未声明 dynamic-tool |
| `RM-12` | `PASS` | `freeze-preflight-20260823-003` | Serving 与 Memory-control 性能门通过 |
| `RM-13` | `PASS` | `rm13-finalization-20260823-001` | Hardened OpenWorker、S1–S10、package、rollback |
| `RM-14` | `PASS` | `finalize-candidate-20260823-002` | Confirmation、最终报告与只读候选冻结 |
| `RM-15` | `PASS` | `controlled-adjudication-20260823-001` | 一次终审、批量修复、确定性受控接受 |

Blocking completion：

```text
RM-00..RM-09 ∧ RM-12..RM-15 = PASS
```

---

# 3. 功能性验证结果

## 3.1 F0 MCP 原生功能

```text
F0-01..F0-10 = 10/10 PASS
```

已证明：

- fresh wheel 安装与非仓库目录启动；
- MCP stdio initialize、list_tools、call_tool；
- 真实 Runtime/PostgreSQL 路径；
- submitter 只创建 Evidence/Proposal，由受控 steward 路径决定 canonical state；
- 新 session 可召回已接受记忆与 provenance；
- update、conflict、OpenIssue、revoke、Scope 和 tenant/profile 负例正确；
- Runtime/MCP 重启后记忆语义保持；
- timeout/disconnect 有明确终态；
- synthetic cleanup 无残留和 secret artifact。

## 3.2 F1 Agent 功能

```text
F1-01..F1-05 = 5/5 PASS
OpenWorker F1 = PASS
```

已证明：

- generic Agent/OpenWorker 使用安装后的 MCP 产品路径；
- no-memory control 与 MiLAi arm 可配对比较；
- local vLLM 答案实际消费了跨会话 MiLAi context；
- context digest、retrieval trace 和 native ledger 可追踪；
- MiLAi 没有增加隐藏模型轮；
- OpenIssue、revoke 和 Runtime unavailable 不产生错误确定性答案。

## 3.3 OpenWorker 路由修复

最终实现已移除从用户文本识别 DG-10/synthetic marker 的路由。Memory 是否启用由 Host 所有的
`memory_mode` 决定：

```text
memory_mode = none | prefetch | auto
```

用户文本不能提升 Memory authority、选择测试路径或扩大 socket/profile 权限。最终裁决的
`ADJ-04-MARKER-REMOVAL` 已通过。

## 3.4 Hardened 集成

```text
T2                  = 24/24 PASS
S1–S10              = PASS
S8a / S8b / S8c     = PASS
fresh package       = PASS
stdio / UDS profiles = PASS
capability isolation = PASS
task settlement      = PASS
restart/degrade/rollback = PASS
```

---

# 4. Benchmark、质量与效率结果

## 4.1 LongMemEval DEV

| 指标 | 结果 |
| --- | ---: |
| Provider requests | `150` |
| F1 delta vs `NAIVE_RAG` | `+0.083127` |
| EM delta | `+0.12` |
| Recall@k | `0.90` |
| Prompt-token ratio vs strongest baseline | `1.292523x` |
| Hidden model calls | `0` |
| Quality gate | `PASS` |

## 4.2 Confirmation-003

| 指标 | 结果 |
| --- | ---: |
| Provider requests | `150` |
| Strongest baseline | `NAIVE_RAG` |
| F1 delta | `+0.121108` |
| EM delta | `+0.14` |
| Recall@k | `0.86` |
| Prompt-token ratio | `1.293692x` |
| Memory payload | `<=512 target tokens` |
| One answer call per arm/case | `PASS` |
| Knowledge-update non-inferiority | `PASS` |
| Temporal-reasoning non-inferiority | `PASS` |
| Overall quality gate | `PASS` |

## 4.3 Serving 与 Cache

| 指标 | 结果 | 门槛/解释 |
| --- | ---: | --- |
| Serving requests | `124/124 PASS` | terminal failures `0` |
| Memory-control warm p95 | `52.102 ms` | 门槛 `<=250 ms` |
| 优化前 Memory-control p95 | `322.389 ms` | 对照 |
| Memory-control p95 delta | `-270.287 ms` | `KEEP_EFFICIENCY` |
| T3a warm E2E mean | `637.166 ms` | 不隐藏模型时间 |
| T3a warm E2E p95 | `774.561 ms` | 优化前 `1002.444 ms` |
| Validated-cache hit rate | `1.0` | 冻结功能 workload |
| Validated-cache warm p95 | `7.932692 ms` | 本地候选结果 |

这些结果只支持冻结的本地 Qwen/vLLM、synthetic/deidentified workload 和候选环境；不是生产 SLA。

---

# 5. 最终审查与受控裁决

## 5.1 实际审查预算

```text
development AI audits = 0
final xhigh reviews    = 1
second AI review       = false
```

Goal 跟踪器累计使用 `4,928,716 tokens`，耗时约 `7 小时 43 分钟`。这是用户报告的过程成本，
不是 Provider billing 或产品 Token 指标。后续 Goal 必须继续以功能和实验结果为主，禁止恢复高频审计链。

## 5.2 Primary review 的五个 P1

唯一一次 xhigh 终审返回 `REVISE`，发现：

1. OpenWorker 产品路径含用户文本 marker 路由；
2. confirmation-001 的 zero-call consumed attempt 未披露；
3. Review workspace 未材料化 F0 `10/10` 动态证据；
4. package 010→011 等价性不可独立复算；
5. Serving-005 重分类缺少原失败输入。

这些问题被一次性退回开发并批量修复，没有逐项启动新的 AI review。

## 5.3 最终裁决

`controlled-adjudication-20260823-001` 的 `ADJ-01..ADJ-10` 全部通过，最终状态：

```text
status      = ACCEPT
disposition = RM15_PASS_RELEASE_CLAIM_MILAI_PREFETCH_AGENT_READY
open blocking findings = 0
```

`final-report.json.primary_review.verdict = REVISE` 是历史 primary 结果；最终 disposition 必须与
`controlled-adjudication.json` 一起解释，不能把历史 REVISE 误读为当前开放 finding。

---

# 6. 冻结候选与交付物

## 6.1 最终 packages

| Package | SHA-256 |
| --- | --- |
| `milai_client-0.1.0-py3-none-any.whl` | `a2ea195369b70d96d4cb62378e9f02d51a8d67ec238dc1c90ef0bc9638a93635` |
| `milai_mcp-0.1.0-py3-none-any.whl` | `08a08d13be792fc34cd9eb2e1b99b8b9f0a7ed00c5b5c51c30c4b85d0494ee66` |
| `milai_openworker_mcp-0.1.0-py3-none-any.whl` | `d10c80cb045fac3870dae8219b6ad16c1d774589090e654d0b35b6a44ea619ed` |
| `milai_runtime-0.1.0-py3-none-any.whl` | `2a22e5d1dadc7dc8716a017845be9adc059962eb6ea653a766db048d8c499f8e` |

## 6.2 只读边界

```text
var/dg10/final/candidate         mode 0555
var/dg10/final/review-workspace mode 0555
files                            mode 0444
```

最终候选和 review workspace 不得原位修改。需要修复时必须从冻结候选派生新的开发工作区，重跑受影响
功能门、Benchmark 和 package equivalence 后再决定是否产生后继候选。

原 `0.4.0` 执行合同已逐字节保留在：

```text
var/dg10/final/review-workspace/GOALS.md
SHA-256 0e42270e275b2ba3d08b7974e1f6b77d77a28b68d8c0bfbb88aec1c55907729f
```

---

# 7. 允许与禁止的声明

## 7.1 允许

```text
MiLAi Logical Architecture 1.0.0 = FROZEN
MiLAi Runtime 0.1.x              = CANDIDATE
MiLAi MCP Memory                 = FUNCTIONAL
Local vLLM prefetch Agent        = READY
OpenWorker hardened integration  = PASS
Synthetic/deidentified quality   = PASS
```

准确表述：

> MiLAi 已能作为受限本地 MCP Memory 工具被 OpenWorker/Agent 使用；冻结的 prefetch profile 在一次
> 本地 vLLM 回答调用前读取 canonical、conflict-aware memory，并满足功能、质量、Token、延迟、
> revoke/OpenIssue 和集成门槛。

## 7.2 仍然禁止

```text
MILAI_DYNAMIC_TOOL_AGENT_READY
EXTERNAL_PROVIDER_VERIFIED
EXTERNAL_PROVIDER_BETA
PRODUCTION_READY
SCHEMA_FROZEN
REAL_PRIVATE_DATA_APPROVED
PUBLIC_REMOTE_DEPLOYMENT_APPROVED
GENERAL_MULTI_AGENT_MEMORY_PLATFORM
PRODUCTION_SLA_PROVEN
```

本次 PASS 不重开 OSPC novelty，也不改变外部 Provider `OE-F06` 的 PARKED 状态。

---

# 8. 历史提案：`DG-10-OPS CONTROLLED_AGENT_USAGE`

## 8.1 状态

```text
SUPERSEDED BY DG-11 / NOT STARTED
```

DG-10 已关闭。该提案没有启动；其 Agent 受控使用目标已被
`MiLAi_DG-11记忆质量与Agent效率优化_GOALS.md` 的 `DG11-07` 收纳，并与 Context、检索、
Temporal、Token 和持久 OpenWorker 优化形成一条统一开发链。不得再单独启动 DG-10-OPS。

## 8.2 目标

```text
accepted frozen candidate
→ controlled synthetic/deidentified Agent workflows
→ actual task outcomes
→ memory usage / abstention / stale / failure telemetry
→ compare no-memory and MiLAi behavior
→ only measured regressions trigger code changes
```

## 8.3 建议工作包

| ID | 工作包 | 首要产出 | 完成条件 |
| --- | --- | --- | --- |
| `OPS-00` | 冻结运行基线 | final candidate/package/config identity | 与 §6 完全一致 |
| `OPS-01` | Controlled adoption | 先运行 10 个代表性 Agent tasks | 10/10 explicit terminal，无数据越界 |
| `OPS-02` | Memory usefulness | paired no-memory/MiLAi task outcome | task success 不劣；错误确定性为 0 |
| `OPS-03` | Efficiency observation | Token、recall、cache、Memory p95、E2E | 不突破冻结门；无隐藏模型轮 |
| `OPS-04` | Availability observation | timeout、restart、degrade、rollback | action-safe fail closed；无 hang |
| `OPS-05` | Feedback loop | 按第一个真实失败提出单一假设 | 先重现、再修复、KEEP/REVERT |
| `OPS-06` | 扩展决定 | 10-task 结果决定是否扩到 50 tasks | 不自动扩大 workload 或权限 |

## 8.4 OPS 验收门

```text
functional regressions                         = 0
cross-tenant/Scope/profile leakage             = 0
revoked/stale memory used for action           = 0
hidden MiLAi-added model calls                 = 0
explicit terminal rate                         = 100%
warm memory-control p95                        <= 250 ms
memory payload                                 <= 512 target tokens
paired task success vs strongest fixed control >= 0 delta
development AI review calls                    = 0
```

如果 10-task 阶段未通过，只修复第一个可复现根因，不扩大到 50 tasks，不启动 AI review，不生成多层
candidate/receipt。

---

# 9. 后续开发与实验纪律

## 9.1 默认不改代码

冻结候选首先用于受控使用。只有以下情况才允许创建开发分支/工作区：

- F0/F1 功能回归；
- 实际 task 出现可重复错误记忆或错误确定性；
- Token、Memory-control 或 E2E 明确突破门槛；
- OpenIssue、revoke、Scope、cache 或 restart 失败；
- 新 Agent framework 存在可复现接入阻断。

“想进一步优化”但没有可复现指标，不构成修改冻结候选的理由。

## 9.2 修复循环

```text
真实失败
→ 最小重现
→ 一个主要假设
→ 修改开发副本
→ 重跑受影响 F0/F1/S1-S10
→ 重跑相同 paired workload
→ KEEP 或 REVERT
```

每个假设族最多连续尝试三次。第三次仍无稳定收益时停止局部调参并请求设计决定，但不自动重开
Frozen Logical Architecture。

## 9.3 审计预算

```text
日常 OPS / bugfix AI review = 0
性能或质量调参 AI review   = 0
只有新 release candidate 冻结后，才允许一次有限终审
```

确定性测试、真实 Agent task、Benchmark delta 和故障重现是默认反馈来源。

---

# 10. 独立后续目标边界

以下方向不得混入 `DG-10-OPS`：

| 方向 | 状态 | 必须单独开启的原因 |
| --- | --- | --- |
| Dynamic model-selected MCP tools | `NOT STARTED` | 需要 RM-10/RM-11 与 BFCL 门 |
| 外部 Provider | `PARKED` | 需要真实 usage/billing/quality 证据，不能由本地 vLLM 替代 |
| 真实私密数据 | `NO-GO` | 需要独立隐私、删除、备份和运营批准 |
| 公网远程部署 | `NO-GO` | 需要新的网络、认证、速率和威胁模型 |
| Schema freeze | `NO-GO` | Runtime 仍为 0.1.x Candidate，Schema 仍 Experimental |
| General multi-agent shared memory | `NO-GO` | 需要新的 tenancy、authority 与并发合同 |
| OSPC novelty | `PARKED` | 当前 release 不构成 novelty 接受证据 |

---

# 11. 变更、回滚与重新开放规则

## 11.1 不需要重新开放 DG-10

- 只读取最终报告或运行现有示例；
- 使用冻结 wheels 做 synthetic/deidentified controlled tasks；
- 收集不含私密内容的运行指标；
- 更新本文的 OPS 观察状态但不改变产品字节或 release claim。

## 11.2 必须重新验收受影响能力

以下任一变化发生时：

```text
Runtime/MCP/OpenWorker/client product bytes
model/tokenizer/revision
prompt/context contract
retrieval ranking or Canonical Gate
Scope/authority/cache/revoke semantics
Provider endpoint or trust boundary
```

必须：

1. 从只读候选派生开发副本；
2. 明确受影响 RM 与 claim；
3. 重跑相应 F0/F1/S1-S10；
4. 重跑同一质量/性能对照；
5. 只在确需新发布时冻结一个后继 candidate；
6. 不为文档、hash、receipt 或审计文本变化单独 bump candidate。

## 11.3 立即停止条件

```text
canonical invariant violation
cross-tenant/Scope leakage
secret/private-data leakage
OpenIssue/revoke fail-open
stale context authorizes action
hidden model calls or denominator manipulation
test/confirmation labels contaminate development
```

发生后停止当前 run、保留一次故障记录、回滚最近变更并修复最小根因；不要先启动 AI 审计。

---

# 12. 当前行动清单

DG-10 本身没有未完成项：

```text
[x] F0 10/10
[x] F1 5/5
[x] T2 24/24
[x] S1–S10 hardened
[x] Serving 124/124
[x] LongMemEval DEV
[x] Confirmation-003
[x] Blocking RM PASS
[x] Final report
[x] Frozen candidate
[x] One xhigh primary review
[x] Five P1 batch-fixed
[x] Controlled adjudication ACCEPT
[x] MILAI_PREFETCH_AGENT_READY
```

后续执行以 `MiLAi_DG-11记忆质量与Agent效率优化_GOALS.md` 的启动清单为准：

```text
[ ] 1. 从只读候选安装四个 final wheels
[ ] 2. 固定 synthetic/deidentified Agent workload 与 no-memory control
[ ] 3. 运行 10 个 controlled Agent tasks
[ ] 4. 汇报 task success、Memory usage、Token、latency、failure 和 abstention
[ ] 5. 决定保持冻结、修复一个可复现问题，或扩展到 50 tasks
```

---

# 13. 最新状态摘要

```text
DG-10                         = CLOSED / ACCEPTED
MILAI_MCP_MEMORY_FUNCTIONAL   = PASS
MILAI_PREFETCH_AGENT_READY    = PASS
MILAI_DYNAMIC_TOOL_AGENT_READY = NOT CLAIMED
Local vLLM                    = VERIFIED
OpenWorker MCP                = HARDENED PASS
Runtime                       = 0.1.x CANDIDATE
Schema                        = EXPERIMENTAL / NO-GO FOR FREEZE
External Provider             = PARKED
Production Ready              = NO
Next Goal                     = DG-11 PROPOSED / READY FOR EXECUTION
```

本阶段真正的完成标准已经达成：MiLAi 能作为 Memory MCP 工具被真实 Agent 使用，效果优于冻结的
最强基线，Memory-control 成本在门槛内，安全语义没有退化，并以一次终审和一次确定性受控裁决完成
接受。后续重点应是受控实际使用与运行反馈，不再重复 DG-10 的审计和候选生产过程。
