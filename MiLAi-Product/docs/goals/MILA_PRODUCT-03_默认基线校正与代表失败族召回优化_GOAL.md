---
document_id: MILA-PRODUCT-03
version: "1.1"
status: PASS_OPENWORKER_MCP_USABLE_WIDE_BASELINE
created_at: "2026-09-02T11:08:30+08:00"
parent: MILA-PRODUCT-GOALS@1.4
predecessor: MILA-PRODUCT-02
supersedes: MILA-PRODUCT-03@1.0
execution_authorized: true
formal_holdout_authorized: false
schema_change_authorized: false
public_api_change_authorized: false
external_paid_provider_authorized: false
---

# MILA-PRODUCT-03：OpenWorker MCP 真实调用与宽预算可用 Memory 闭环

## 1. Goal

MiLAi Product 的成功对象不是直接调用 `milai-runtime` 的 benchmark harness，而是用户通过
OpenWorker 获得的真实 Memory 能力。本 Goal 先把当前已实现的 Memory 接到真实 OpenWorker
调用面，使用足够宽的本地预算验证它能否完成任务；成本压缩、精细路由和复杂 Memory 机制留到
可用性成立之后。

```text
先接通真实调用
→ 给足检索、Context 与回答预算
→ 完成用户任务
→ 失败时定位一个最早边界并修复
→ 重跑真实调用
→ 可用后再优化成本
```

本 Goal 替代 Product-03 v1.0 的后续 `24 context-only → 64 Qwen → opened-128` 执行条款。
v1.0 已完成的默认基线、trace 和 T1 代码工作保留为组件准备事实，但不能作为 OpenWorker 产品
可用性证据。

## 2. 当前真实产品路径

### 2.1 回答数据面

当前 shipped 主路径是 Host-controlled `query-first`，不是模型自由选择 Memory tool：

```text
OpenWorker / OpenCode native user operation
→ X-MiLAi-Host-Instance / Task-Session / Task-Operation
→ milai-openworker-adapter /v1/chat/completions
→ Host McpUnixClient 直连 reader-lite.sock
→ profile-scoped broker
→ one real milai-mcp child
→ milai_memory_resolve(query) exactly once
→ Python Client
→ loopback milai-runtime
→ Retrieval / Gate / Context Compiler
→ Host 注入 MILAI_CONTEXT
→ Host 从 provider payload 移除 MiLAi memory tools
→ local vLLM Qwen
→ OpenWorker receives final answer
```

同一 OpenWorker session 的后续 user operation 仍产生一次新的 MCP resolve；Host 最多附带上一轮
opaque `context_capsule_id`，Runtime 必须在线重新授权、验证并在同一次调用中 fallback。

### 2.2 MCP discovery 面

容器内 relay 位于另一条真实路径：

```text
OpenCode MCP stdio
→ milai-mcp-relay
→ read-only mounted reader-lite.sock
→ broker
→ milai-mcp
→ Runtime
```

relay 负责 OpenCode 的 MCP discovery/兼容 tool 路径；`query-first` 的逐轮回答调用由 Host 直接
连接同一个 broker socket，不经过容器内 relay。最终测试必须分别证明 discovery 面和回答数据面，
不得把两条路径错误画成一条串行链。

### 2.3 写入与撤销

普通 OpenWorker 只持有 `reader-lite`。场景数据通过可信 Host 的正式 MCP profiles 准备：

```text
submitter MCP → milai_evidence_capture
reader-detail MCP → projection readiness（仅测试编排）
operator MCP → milai_evidence_revoke
```

不为本 Goal 把 submitter/operator token 放进 OpenWorker，也不让回答模型写 Canonical State。

## 3. 已确认的评测偏差

Product-02/03 的 Lab effect harness 直接调用 Runtime HTTP：

```text
POST /v1/memory/resolve
max_results       = 50
max_candidates    = 120
max_latency_ms    = 2000
```

它是 Runtime public-interface diagnostic，不是 OpenWorker user operation。当前真实 OpenWorker
配置则更窄：

```text
reader-lite broker max_limit       = 3
Runtime default max_candidates     = 60
Runtime default max_context_tokens = 2500
Runtime default max_latency_ms     = 500
OpenWorker answer output limit     = 96
```

因此此前结果既没有证明真实 OpenWorker 可用，也不能据此选择真实产品预算。Lab 中的
`PRODUCT_BLACK_BOX` 必须进一步区分：

```text
PRODUCT_RUNTIME_HTTP_BLACK_BOX
PRODUCT_MCP_BLACK_BOX
OPENWORKER_HOST_BLACK_BOX
```

只有最后一种、并同时通过真实 MCP/broker/Runtime 与 provider，才能支撑本 Goal 的 Product
可用性结论。直接 Runtime、fake MCP、mock provider 和测试内 Context 注入只用于故障定位。

## 4. Research hypotheses

### P03-H1 — Real-call availability

每个 native OpenWorker user operation 都能通过真实 Host → UDS broker → `milai-mcp` → Runtime
完成一次 fresh Memory resolve，并由本地 Qwen 消费实际注入的 Context 返回答案；调用身份、
MCP trace、Runtime trace 和 provider request 可关联，且不存在 direct-Runtime evaluator bypass。

### P03-H2 — Useful local memory

在代表性的本地任务流中，Memory-enabled OpenWorker 相对同请求的 Memory-disabled 对照能恢复
正确的个人事实、assistant 历史回答、跨轮线索和多证据结果；scope isolation、revocation 和
read-only Canonical 边界不回归。

Anti-claim：本 Goal 不证明 production readiness、LongMemEval 泛化、Schema 稳定、外部 Provider
等价或最优成本。

## 5. 使用优先的宽预算基线

第一轮不再用紧预算筛掉证据。使用一个 Host-owned、模型不可修改的本地
`OPENWORKER_USABILITY_WIDE_V01`：

```yaml
Memory resolve:
  max_results: 50
  max_candidates: 120
  max_context_tokens: 8192
  max_latency_ms: 2000

OpenWorker / Qwen:
  model_context_limit: 65536
  answer_output_tokens: 2048
  mcp_timeout_ms: 10000
  provider_timeout_seconds: 60

Execution:
  semantic_retry: 0
  vote: 0
  model_selected_scope_or_budget: false
```

这些值使用当前 Runtime contract 的上限，不是无限资源。它们只扩大 work/presentation capacity，
不放宽 tenant、scope、permission、revocation、identity 或 Canonical authority。

实现时只允许一个 budget owner。优先把上述字段作为 Host/MCP deployment profile 注入 Runtime
request；不要在 OpenWorker、MCP、Runtime 和 Context 四层分别增加同义 budget flags。

本 Goal 不以 token、candidate 或 P95 成本非劣作为初始 PASS 门。记录实际用量、OOM、timeout、
queue saturation 和 latency；只要本机资源稳定且任务正确，先保留宽预算。后续单独 Goal 再做
budget sweep，并要求任务正确性不回归。

## 6. 继承的组件准备事实

Product-03 v1.0 已完成但仅作为准备工作的内容：

| 旧阶段 | 事实 | 新定位 |
| --- | --- | --- |
| P0 | 默认 LOOKUP policy 与三层 trace 校正 | Product component preparation |
| P1 | official acquisition opportunity 显示 Dense 有 residual opportunity | Lab diagnostic |
| P2 | 既有 FTS + Dense independent quota/RRF T1 可运行 | optional implementation, default OFF |
| P3 partial | micro/context-only direct Runtime runs 已产生 | diagnostic only; not Product acceptance |

不得删除这些失败或准备证据，也不得把它们并入新的 OpenWorker task success 分母。

## 7. 五阶段执行安排

| 阶段 | 目标 | 状态 |
| --- | --- | --- |
| OW0 | 当前源码身份下接通真实 OpenWorker/MCP/Qwen 纵向路径与宽预算 profile | `PASS` |
| OW1 | 代表性真实使用场景与 Memory-disabled 对照 | `PASS` |
| OW2 | 失败单点诊断、通用修复并自动续跑 | `PASS` |
| OW3 | 32-operation 真实调用稳定性与 restart | `PASS` |
| OW4 | 简单基线/T1 产品决定、一次受影响全量验证与文档交付 | `PASS_KEEP_T1_OFF` |

### OW0 — 真实路径接通

使用 fresh isolated PostgreSQL 和当前 Product source identity 启动：

```text
Runtime API
projection worker
reader-lite broker + real milai-mcp
Host adapter in explicit query-first mode
local vLLM Qwen
actual local OpenWorker/OpenCode image
```

另启 submitter/operator profile 仅用于 synthetic fixture capture/revoke。不得使用 Product-02/03
的 RuntimeHttpClient 代替 OpenWorker 请求。

最小场景：写入一个唯一 synthetic fact，在真实 OpenCode session 提问两轮。第一轮必须召回并
回答；第二轮必须形成新的 native operation 和新的 MCP call，同时只传 opaque locator。启动时还要
通过容器内 relay 完成一次真实 MCP discovery。

OW0 最小门：

```text
OpenCode native operation → Host headers            1.0
Host memory mode                                    query-first
Relay discovery catalog                             {milai_recall, milai_memory_resolve}
Native user operations → MCP resolve calls          1:1
MCP calls → Runtime traces                           1:1
Reader-visible Context present for the fact          PASS
Qwen answer uses the correct fact                    PASS
Provider calls per answerable operation              1
Provider payload contains MiLA memory tools          0
Cross-session identity mix                           0
Direct Runtime evaluator call                        0
```

还需做一次 broker-stop 负控：Memory required 时返回 typed unavailable，provider 不得被调用。

### OW1 — 可用性场景

用 10–12 个 synthetic/deidentified OpenWorker task flows 覆盖：

```text
1. exact personal fact
2. paraphrased fact
3. assistant-answer recall
4. same-session continuation
5. new-session recollection
6. two-evidence comparison
7. multi-session evidence composition
8. current correction / obsolete fact suppression
9. scope isolation
10. revoked evidence
11. no-memory / abstention
12. optional temporal query
```

至少 6 个 answerable flows 使用同请求 Memory-disabled matched control。评价对象是 OpenWorker
最终 answer、真实 Reader-visible Evidence 和 task completion，不是 Runtime 内部 score。

最低门：

```text
Critical usable flows                            all PASS
Memory-enabled matched wins                      > losses
Correct evidence visible but answer wrong        separately reported
MCP/Runtime/provider system success              1.0 after repair rerun
Scope/revocation leak                            0
Read-path canonical mutation                     0
```

optional temporal 或复杂 composition 失败可以记录为 limitation；不能用其阻塞 exact、paraphrase、
continuation、correction 和 multi-evidence 这些核心流程。

### OW2 — 失败反思、修复与继续

OW2 不是一次性 stage，而是 OW0–OW3 的共同内循环：

```text
失败
→ 保存最小 operation/MCP/Runtime/provider identity chain
→ 定位最早失败边界
→ 只改一个通用边界
→ 失败例 + 正确对照 + scope/revocation 负控
→ 重跑当前 OpenWorker stage
→ PASS 后自动进入下一 stage
```

有限 failure classes：

```text
OPENWORKER_REQUEST_OR_IDENTITY
MCP_DISCOVERY_OR_TRANSPORT
RUNTIME_NO_USEFUL_EVIDENCE
EVIDENCE_NOT_READER_VISIBLE
READER_VISIBLE_BUT_WRONG_ANSWER
EXPECTED_POLICY_DENIAL
INFRASTRUCTURE_CAPACITY
```

修复路由：

- `RUNTIME_NO_USEFUL_EVIDENCE`：先确认宽预算已生效；仍缺失时才比较已有 B0 与 T1。
- `EVIDENCE_NOT_READER_VISIBLE`：修 atomic admission/serialization，不增加 retrieval 规则。
- `READER_VISIBLE_BUT_WRONG_ANSWER`：修 Qwen prompt/answer contract，不扩大 Top-k。
- `MCP_DISCOVERY_OR_TRANSPORT`：修真实 composition；fake MCP PASS 不能替代。
- `INFRASTRUCTURE_CAPACITY`：修 worker/lease/concurrency，不能计作 semantic abstention。

可恢复的代码、模型或环境失败不产生 terminal，不创建新 Goal。只有 authority/secret 泄漏、
破坏性不确定性、未授权外部费用或不可替代外部依赖才暂停。

### OW3 — 真实调用稳定性

运行 32 个 native OpenWorker operations，混合 fresh session、same-session continuation、
multi-evidence 和 no-match；并发从 4 起步，本机 vLLM/DB/worker 无 saturation 后可提高到 8。

执行一次 broker restart 和一次 OpenWorker recreate。旧 socket inode 不得被现有 Worker 静默
跟随；recreate 后恢复。记录：

```text
task success
MCP/Runtime/provider call coverage
retrieved/admitted/Reader-visible item counts
prompt/completion tokens
memory-control and end-to-end P50/P95
timeouts/OOM/queue saturation
```

OW3 不设置人为的 20% latency ratio 或小 token ceiling。现有 10 秒 MCP timeout 内无失败是最低
可用门；端到端时延先作为优化基线。

### OW4 — 产品决定

判断对象只有：

```text
B0/B1 simple baseline with WIDE profile
vs
B0/B1 + existing T1 with the same WIDE profile
```

若 B0/B1 已完成 OW1/OW3，T1 不必运行；若仍有明确
`RUNTIME_NO_USEFUL_EVIDENCE`，才做 matched T1。T1 只有在真实 OpenWorker task wins 增加且 losses
不增加时才能进入 local canary；否则保持 default OFF。

最后只跑一次受影响 Product checks：Runtime retrieval/Context、MCP、OpenWorker、build、Ruff 和
mypy。更新 local runbook 与 current status。Schema、public API、real personal data、remote MCP、
image redistribution 和 production release 均不因本 Goal 自动授权。

## 8. 高效开发与最小审计

- 内循环使用 OpenWorker wire-faithful simulator；OW0/OW1/OW3 终门使用 actual local OpenWorker。
- simulator 必须发送真实三项 native headers 并经过 Host/MCP；不得 import Runtime services。
- direct Runtime 请求只在 E2E 首损定位后使用，且结果标记为 `COMPONENT_DIAGNOSTIC`。
- 一个 compact JSONL 记录 operation → MCP → Runtime → provider linkage；一个 final summary。
- 不为每个 stage 创建 receipt hierarchy、witness、source mirror 或重复 manifest。
- 一次行为修改先跑 narrow triad；OW4 前再跑一次全量，不在每个小修复后重跑 600+ tests。
- validation 只保留真实信任边界：Worker/Host identity、scope/revocation、read-only Canonical。
- 内部纯函数信任 typed inputs；程序错误直接暴露，不用多层 `except Exception` 静默 fallback。
- 不添加 case ID、gold quote、synonym、seed switch、semantic retry、vote 或 post-outcome route。

## 9. LongMemEval 与 Lab 的位置

现有 LongMemEval direct-Runtime 结果继续用于检索诊断，但不是本 Goal 的 PASS 条件。只有 OW4
完成后，Lab 才可以新增 `OPENWORKER_HOST_BLACK_BOX` benchmark adapter；它必须复用同一
query-first composition 和宽预算 profile。500-case formal holdout 仍未授权。

## 10. Terminal logic

允许终态：

```text
PASS_OPENWORKER_MCP_USABLE_WIDE_BASELINE
PASS_OPENWORKER_MCP_USABLE_T1_CANARY
FAIL_AUTHORITY_OR_SECRET_BOUNDARY
PARKED_IRREPLACEABLE_EXTERNAL_DEPENDENCY
```

普通 task failure、model answer miss、MCP composition bug、worker capacity bug 或测试错误都不允许
直接 terminal；按 OW2 修复并继续。

## 11. 当前授权与限制

用户于 2026-09-02 明确要求 Product 以 OpenWorker MCP 真实使用为目标，并要求先完成可用性、
放开开发预算限制。本 Goal 因此授权：

```text
actual local OpenWorker / OpenCode execution
local vLLM Qwen
fresh isolated synthetic/deidentified Product stack
Host-owned WIDE budget profile
recoverable failure repair and automatic stage continuation
```

仍未授权：

```text
formal 500 holdout
external paid Provider
real personal data
remote MCP
public API or database Schema change
production/default release claim
```

## 12. 执行结果（2026-09-02）

终态为 `PASS_OPENWORKER_MCP_USABLE_WIDE_BASELINE`。这是本地 synthetic/deidentified candidate
结论，不是 production readiness、Schema freeze、remote MCP 或镜像分发授权。

- OW0：真实 OpenCode session 两轮各产生一个新 operation、一个 fresh
  `milai_memory_resolve`、一个 Runtime trace 和一个本地 Qwen provider call；relay discovery
  catalog 精确为 `{milai_memory_resolve, milai_recall}`。provider payload 中 Memory tools 为 0。
  broker-stop 返回 typed `MEMORY_REQUIRED_BUT_UNAVAILABLE`，provider ledger 不增长。
- OW1：12 个代表 flow 全部获得正确语义结果；其中 final current-source 全套为 11/12，唯一
  literal miss 返回正确数值 `12`，随后独立真实复验返回 `$12 per coffee mug` 并通过语义断言。
  6 个 matched memory-disabled control 为 0/6，enabled 为 6/6，即 6 wins、0 losses；scope、
  revocation、no-memory 泄漏为 0，read path canonical mutation 为 0。
- OW2：修复的最早通用边界包括 compound subject 的错误 suffix 匹配、Host 对
  `NO_MEMORY/UNCERTAIN` 的 fail-closed provider prohibition、derived composition 的 Python
  Client 安全序列化，以及 strict composition 的 canonical/binding authority。失败例、正常对照和
  scope/revocation 负控均重跑。
- OW3：32 个 native operations、16 sessions、16 continuations、8 negatives，以并发 4→8
  运行；MCP attempt/context 为 32/32、MCP failure 为 0，24 个 answerable provider call 全部
  `SUCCEEDED/stop`。端到端 mean/P50/P95/max 为
  `7431.411/7211.627/14282.103/16160.277 ms`，无 timeout、OOM 或 queue saturation。旧 Worker
  固定在 inode `37783198`，broker restart 后未静默跟随 inode `37783268`；显式 recreate 后恢复。
  严格字符串分数 28/32，其中 3 条是正确中文 `$12/每个杯子` 被旧英文 literal scorer 漏判，
  1 条为本地 Qwen 不完整输出；系统路径覆盖仍为 32/32。
- OW4：宽 B0/B1 已通过 OW1/OW3，因此按预先规则没有运行 T1；T1 保持 default OFF。Runtime
  full gate 为 `774 passed, 1 skipped`，Python Client/MCP/OpenWorker 分别为
  `165/52/106 passed`；受影响 Ruff、配置的 mypy、四个 build 和 locked image build 均通过。

完整私有运行证据位于 Lab run
`var/runs/mila-product03-20260902T112900-cst/`；其中
`product03-final-summary.json` 是最终摘要，`product03-operation-linkage.jsonl` 是 compact
operation → MCP → Runtime → provider 关联记录。失败尝试均保留，未并入成功分母。

## 13. Post-terminal corrective addendum（2026-09-02）

在终态后，又使用 opened-development LongMemEval case `ad7109d1` 对 44 个真实 source sessions、
466 个 material turns 执行一次实际 OpenWorker 黑盒调用。初始失败暴露两个通用产品边界：

1. Host 声明 WIDE profile，但 Runtime 把显式读取降为 `POSSIBLE`，使 120 candidates / 8192
   Context tokens / 2000 ms 被 progressive acquisition 的 30 / 768 / 250 默认值覆盖；
2. 修复预算后，Runtime 已产生非空、受治理的 ordinary-recall MemoryContext，但 MCP 为控制 wire
   大小压缩 raw diagnostics，Host 又从压缩 items 重建 Context，导致 Runtime-owned Context 被丢弃。

通用修复保持最小：

```text
non-empty EXPLICIT_READ → REQUIRED
PREFETCH_AUTO           → POSSIBLE

authenticated Runtime soft-ranked MemoryContext
→ Host direct Context bridge
→ preserve Evidence refs and Runtime PARTIAL status
```

修复没有扩大 scope/revocation/Canonical authority，也没有把 `PARTIAL` 伪装为 `COMPLETE`。最终
实际链路为：

```text
466 MCP captures/projections
→ 1 native OpenWorker operation
→ 1 logical MCP resolve
→ Runtime REQUIRED / 120 / 8192 / 2000
→ corrective summary: 20 governed Evidence units（gold Reader-visible）
→ Host Context 24,576 bytes / 5,858 tokens
→ 1 local Qwen call
→ exact expected answer
```

自动重试为 0，Canonical mutation 为 0，formal 500-case holdout 未消费。权威 Lab 目录是
`var/runs/mila-product03-lme-openworker-ad7109d1-final-20260902T133619-cst/`。

该增补建立的是单病例、大 haystack、真实 OpenWorker composition 的可用性，不改写原 Product-03
终态，也不声称 LongMemEval 泛化准确率。query scaffold 污染与 WIDE reranker 未被调用仍是后继
效率/泛化机会；只有 matched multi-case 证据成立后才应修改，不能在本次成功修复中叠加。

Post-corrective affected-surface checks：Runtime 30、Python Client 167、OpenWorker 106、Lab 46
均通过；相关 Ruff、strict Runtime/Python-Client mypy 和 Product pin verification 通过。

## 14. Expanded-budget V02 usability follow-up（2026-09-02）

为了先恢复大 haystack 下的实际可用性，新增显式、default-OFF 的
`OPENWORKER_USABILITY_WIDE_V02` deployment profile：

```yaml
Runtime:
  max_results: 50
  max_candidates: 120
  max_context_tokens: 16384
  max_latency_ms: 5000

Transport:
  mcp_wire_bytes: 262144
  host_context_chars: 262144

Unchanged:
  model_context_limit: 65536
  answer_output_tokens: 2048
  automatic_retry: 0
  model_selected_budget: false
```

V02 不覆盖 V01 历史合同；只有 Host 启动 broker 时显式选择 V02 才生效。省略
profile 仍走普通 Product 默认值，Worker 和模型不能提高预算。scope、permission、
revocation、identity、Binding、Sufficiency 和 Canonical authority 均未放宽。

三个 opened-development case 分别使用隔离数据库和实际
OpenWorker → Host → UDS broker → MCP → Runtime → Qwen 路径重放：

| Case | Sessions / turns | Runtime | Qwen | 结果 |
| --- | ---: | --- | ---: | --- |
| `71a3fd6b` | 44 / 439 | `PARTIAL`, 11,807 memory tokens | 1 call | lookup PASS |
| `ad7109d1` | 44 / 466 | `PARTIAL`, 11,658 memory tokens | 1 call | lookup PASS |
| `0a995998` | 44 / 484 | `PARTIAL / UNBOUNDED`, 11,604 memory tokens | 1 call | full-chain available, semantic COUNT MISS |

合计 1,389/1,389 turns 已 capture/project，3 个 native operations、3 次 logical MCP
resolve、3 次 Qwen call，自动重试和 Canonical mutation 均为 0。两个普通 lookup 正确；
集合计数 case 已从“Provider 不可达”改善为可读的 best-effort partial，但答案仍错。
其剩余缺口是通用的 object-instance / obligation / event-member identity、复合句原子化和
跨 session 去重，不再是 V02 容量不足。未添加 case ID、gold 数字、领域词表或同义词特判。

这一结果支持保留 V02 作为 opt-in 本地可用性 profile，不支持默认启用，也不支持
LongMemEval 泛化准确率、COUNT completeness 或 production readiness 主张。formal 500-case
holdout 仍未授权、未运行、未消费。紧凑机器摘要位于 Lab
`var/runs/mila-product03-lme-openworker-v02-replay-20260902T162500-cst/summary.json`。

最终受影响面验证：Runtime unit 642、MCP 54、OpenWorker 110、Python Client 168 和
Lab 48 全部通过；Runtime/MCP/Python Client strict mypy、相关 Ruff、四个 Product
package build、Lab build 与 Product pin/contract 均通过。Product tree 为 305 文件，SHA-256
`d1b3dc0c...9a50`；Lab lock logical digest 为 `7b954fa5...993e`。
