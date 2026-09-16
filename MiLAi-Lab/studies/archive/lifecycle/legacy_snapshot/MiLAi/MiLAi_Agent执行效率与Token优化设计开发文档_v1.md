# MiLAi Agent 执行效率与 Token 优化设计开发文档 v1

> 文档版本：`0.2.0 DESIGN CANDIDATE`  
> 编制日期：`2026-08-18`；最近更新：`2026-08-24`（Asia/Shanghai）  
> 目标版本：`MiLAi Agent Execution Optimization 0.1` + `DG11 Benchmark Harness Efficiency 0.1`  
> Logical Architecture：`1.0.0 FROZEN`  
> Runtime：`0.1.x CANDIDATE`  
> Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> Agent Integration：尚未宣布 Beta  
> 数据边界：`synthetic/de-identified only; real personal data denied`  
> 文档性质：性能与接入优化设计，不表示本文能力已经实现或达到 SLA
>
> 实施检查点（2026-08-24）：Agent Execution Optimization candidate.4.6 已通过本地独立复审；外部
> provider billing gate `OE-F06` 仍不在本地 vLLM 声明内。DG11 候选
> `712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51` 已冻结，
> `DG11-R00～R06` 与 `DG11-10` 为 `PASS`，当前正式状态是
> `DEVELOPMENT_CLOSED / FUNCTIONAL PASS / QUALITY_TARGET_NOT_MET / PAPER_EVALUATION NOT_STARTED`。
> PE08 已完成不读取正式标签、answer/judge 调用均为 0 的 CUPID/Horizon context smoke；其 `PASS`
> 只证明适配和真实治理链可运行，不代表 benchmark harness 已达到效率目标。本文此次更新只设计
> Evaluation Plane 的执行效率重构，不修改冻结候选字节，也不把快速 runner 的耗时冒充产品在线 SLA。

---

# 0. 执行结论

MiLAi 当前 Agent 接入的首要效率问题，不是 PostgreSQL、pgvector 或 embedding 本身太慢，而是
“送入模型之前”的上下文生命周期尚未收敛：

1. 高层 adapter 主要按字节限制 Context，没有使用宿主模型的真实 tokenizer；
2. AutoGen adapter 会把新的 MiLAi memory message 追加到上下文，存在跨轮重复和二次增长风险；
3. MCP reader 默认暴露六个工具，即使当前轮次只需要一次 recall；
4. 普通对话与确实需要长期记忆的轮次之间尚无确定性 Recall Router；
5. 同一 canonical snapshot 尚无跨轮 delta、去重和可替换 memory slot；
6. Python SDK 使用短连接式 `urlopen + asyncio.to_thread`，并发和连接复用仍有优化空间；
7. 当前小数据延迟良好，但 canonical FTS 查询会在查询时构造 search vector，尚无万级以上 Claim 的
   规模证据；
8. DG11 paper smoke 把数据库创建、28 次 Migration、Runtime/MCP/Worker 启停、历史治理写入、
   projection build 和首次查询放进每个 case，因而主要测到重复部署与 backfill 成本，而不是 Agent
   稳态调用 MiLAi 的在线延迟。

本设计不引入新的 canonical backend，而是在既有 Agent Integration Plane 中新增两个确定性组件：

```text
Recall Router
决定本轮 NONE / CACHE / L0 / L1，不把所有轮次都送入检索。

Governed Context Compiler
在真实模型 token budget 内保护 OpenIssue、authority、scope、abstention 和 trace，
生成可替换、可去重、可降级但不能伪造确定性的模型上下文。
```

目标数据流为：

```text
Agent turn
→ host policy + Recall Router
→ NONE | CACHE | governed L0/L1 recall
→ Canonical Gate
→ Context Compiler
→ replaceable milai_memory_slot
→ model invocation
```

写路径保持不变：

```text
真实用户/工具观察
→ EvidenceRecord
→ OperationProposal
→ independent Policy/User/Steward review
→ controlled canonical procedure
→ ClaimVersion 或 OpenIssue
```

任何 token、延迟或易用性优化都不得让外部 Agent、摘要、缓存、搜索结果或模型回答获得 canonical
写权限。

本文从 `0.2.0` 起同时区分两个效率平面：

```text
Agent Integration Plane
→ 优化真实在线 NONE/CACHE/L0/L1、上下文与工具成本

Evaluation Plane
→ 优化可复现实验的环境复用、历史摄取、投影构建和批量 query
```

Evaluation Plane 可以减少重复基础设施工作，但必须证明与 faithful 产品链路语义等价；它不能绕过
Evidence/Proposal/Decision，也不能把 evaluation-only cache 或 batch builder 的耗时写成产品性能。

---

# 1. 规范关系与状态边界

## 1.1 规范优先级

本文服从以下规范：

1. `architecture/v1.0/` frozen Logical Architecture；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` 中的 frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. `MiLAi_可用性与Agent接入设计开发文档_v1.md`；
5. 本文；
6. 实验性 adapter、示例和实现注释。

本文使用 `OE-*` 表示优化实施任务，使用 `OG-*` 表示优化证据门。它们不替代冻结架构 G1～G9、
I-01～I-12，也不与 Lean Runtime 的 `LC-*`、`LG-*` 混用。

## 1.2 不改变的事实

本文不改变：

- PostgreSQL Canonical Core 是唯一正式状态来源；
- ClaimVersion append-only，ClaimHead 只能通过 exact-head CAS 移动；
- Evidence 是观察，不等于 accepted belief；
- OpenIssue 不能因检索遗漏、摘要、压缩、缓存或时间经过而关闭；
- ContextCapsule、Memory Slot、Summary 和 Tool Result 不能制造 Evidence 或 Claim；
- 二级索引、reranker 和外部项目只产生 candidate，返回模型前仍需 Canonical Gate；
- canonical store 不可用且查询要求当前正式状态时必须 abstain；
- TX-01～TX-06、权限、删除、Outbox 和 fail-closed 语义不因性能优化改变。

## 1.3 允许的优化范围

- Python SDK、MCP、LangGraph、AutoGen、hook 和 generic adapter；
- QueryPlan 前的确定性 Recall Router；
- 模型侧上下文表示、token budget、去重、delta 和 memory slot；
- 派生 FTS/vector projection、candidate fusion 和 optional reranking；
- HTTP 连接复用、ONNX 预热、读路径缓存和并发控制；
- 不含敏感正文的 token、延迟、缓存和质量指标；
- synthetic/de-identified benchmark 与本地 Agent E2E。

## 1.4 暂停或禁止范围

- 把 ReMe、OpenViking、Hindsight、Graphiti、Mem0 作为生产 canonical backend；
- 自动 Scope Evolution、自动 Profile/Pattern Promotion；
- OSPC 作为产品依赖或 novelty 声明；
- 模型自动批准自己的 Proposal；
- 多 Agent canonical arbitration；
- 公网、远程、多 tenant 产品化；
- 未通过 crypto gate 的真实个人数据；
- 为降低 token 而删除 live OpenIssue、branch、discharge rule、authority 或 trace identity。

---

# 2. 当前实现与探索性基线

## 2.1 当前接入行为

当前代码中的主要默认值为：

| 项目 | 当前行为 | 位置 |
| --- | --- | --- |
| `AgentMemory.before_model` | 默认 `context_byte_budget=16_384`，只向 formatter 传 `max_bytes` | `integrations/python-client/src/milai_client/lifecycle.py` |
| prompt formatter | 支持 `max_tokens + token_counter`，但高层 adapter 尚未接入 | `integrations/python-client/src/milai_client/formatting.py` |
| AutoGen query | 使用 formatter 默认 `32_768` bytes | `integrations/autogen/src/milai_autogen/memory.py` |
| AutoGen context | 每次 `update_context` 追加一个 `UserMessage` | 同上 |
| Agent recall | `AgentRecallPolicy.max_limit=5` | `integrations/python-client/src/milai_client/models.py` |
| MCP recall | server 默认 `max_limit=10` | `integrations/mcp/src/milai_mcp/server.py` |
| MCP output | 单个结果只按 `65_536` bytes 限长 | 同上 |
| Python HTTP | `urlopen` 由 `asyncio.to_thread` 调用，无显式持久连接池 | `integrations/python-client/src/milai_client/client.py` |
| API worker | 默认四个 API threads | `runtime/src/milai/config/settings.py` |

这些实现已保护数据边界和 host policy，但“字节有界”不等于“模型 token 成本可证明有界”。

## 2.2 2026-08-18 探索性 token 测量

测量对象是当前 synthetic Claim 和当前 MCP schema。`ospc.regex.v1` 与本地 MiniLM WordPiece 仅用于
可重复比较，不是 OpenAI、Anthropic、Google 或其他 provider 的计费 tokenizer。

### Context block

| 当前模型输入 | UTF-8 bytes | `ospc.regex.v1` | MiniLM WordPiece |
| --- | ---: | ---: | ---: |
| 1 个当前 Claim | 1,385 | 408 | 622 |
| 5 个同形状 Claim | 4,217 | 1,304 | 2,050 |

### Tool catalog

| MCP profile/catalog | 工具数 | UTF-8 bytes | `ospc.regex.v1` |
| --- | ---: | ---: | ---: |
| 当前 reader | 6 | 2,530 | 约 791 |
| 当前 submitter | 8 | 5,726 | 约 1,893 |
| 当前 operator | 8 | 3,622 | 约 1,128 |
| 只暴露 `milai_recall` | 1 | 532 | 185 |
| `milai_status + milai_recall` | 2 | 861 | 280 |

只暴露 `milai_recall`，评估 tokenizer 下可相对当前 reader catalog 减少约 `76.6%`。该比例是 schema
形状比较，不是供应商账单承诺。

## 2.3 2026-08-18 探索性读路径延迟

现有 `retrieval_trace` 只有 12 个观测，数据库仅有 1 个 Claim、1 个 ClaimVersion、1 个 FTS document
和 1 个 embedding，因此只用于发现冷启动和路径差异，不能作为规模 SLA。

| 路径 | 样本 | 结果 |
| --- | ---: | --- |
| 全部 trace | 12 | avg `70.7 ms`，p50 `22 ms`，p95 `271.9 ms`，max `488 ms` |
| L0 canonical-required | 1 | `20 ms` |
| L1 canonical-required | 7 | avg `29.3 ms`，p50 `19 ms`，p95 `73.7 ms`，max `95 ms` |
| L1 eventual | 4 | `488/56/39/40 ms`；后三次 warm 为 `39–56 ms` |

`retrieval_trace` 时长覆盖 Runtime 内部搜索、gate 和 trace 写入，不覆盖 Agent 到 Runtime 的网络、认证、
JSON 序列化和宿主模型调用。

## 2.4 Embedding provider 基线

已有目标设备证据：

```text
ONNX cold first call       1050.172 ms
ONNX warm p50/p95/p99      14.529 / 15.069 / 15.548 ms
throughput                 28.967 calls/s
external provider cost     USD 0
```

证据文件：

- `docs/reports/UA-06-retrieval-quality-performance-evidence-2026-08-17.md`
- `evals/embedding/all-MiniLM-L6-v2-target-device-result.json`

结论是：warm embedding 不是当前首要瓶颈，首次加载和无效调用才是。应预热 provider，并让 Router 在
不需要 memory 的轮次完全绕过 embedding。

## 2.5 当前成本模型

定义单轮 MiLAi 额外输入：

```text
T_extra(turn)
= T_tool_schema
+ T_memory_context
+ T_tool_result_not_already_counted
+ T_repeated_history
```

MiLAi Runtime 当前不调用生成式 LLM 来完成 recall，因此直接外部费用主要来自宿主模型看到的 tool
schema 和 memory data，而不是 Runtime 内部的生成 token。

若长度为 `m` 的 memory block 每轮追加且宿主上下文不裁剪，100 轮累计输入近似：

```text
m × (1 + 2 + ... + 100)
= m × 5,050
```

按当前探索性 tokenizer：

```text
1-item block: 408 × 5,050 = 2,060,400
5-item block: 1,304 × 5,050 = 6,585,200
```

这是无界上下文的风险上界；宿主若使用滑动窗口或 token-limited context 会较早裁剪。但正确修复仍是
replace/delta，而不是依赖模型框架最终丢弃旧消息。

---

# 3. 相关项目调研与吸收决策

## 3.1 本地已下载资产

| 项目 | 本地身份 | 可吸收的效率机制 | 保持隔离的语义 |
| --- | --- | --- | --- |
| Mem0 | `2.0.18`；commit `001c235229be8795e3834520467bd0d661ed8f34` | filter、top-k、threshold、rerank；检索代替完整历史 | direct add/update/delete 不得等于 canonical mutation |
| Graphiti | `0.29.3`；commit `401c59a65bdeb22a44136901ff30231e6998a7fe` | temporal validity、keyword/vector/graph hybrid、RRF/MMR | graph fact 或 invalidation 不能移动 ClaimHead |
| ReMe | snapshot `0.4.1.6`；无 Git metadata | pre-reasoning hook、tool output offload、BM25、pointer recovery | auto-memory、dream、文件内容不能成为正式事实 |
| Hindsight | snapshot packages `0.9.0`；无 Git metadata | recall budget、token cap、threshold、candidate/reranker 分层、phase trace | reflect answer 和 extracted fact 不能提升 authority |
| Benchmarks | BEAM、CUPID、HorizonBench、LongMemEval/V2、Memora、PAHF | 长程检索、更新、冲突、偏好、abstention、Agent task success | benchmark 答案不能回写产品状态 |

ReMe 与 Hindsight 当前本地副本没有 Git metadata。若把它们用于正式性能 baseline，必须先生成包含
文件 SHA、依赖锁、许可证和运行配置的 snapshot manifest。

## 3.2 Mem0

Mem0 的核心启发是以筛选后的相关记忆替代完整历史。其论文在特定 LoCoMo workload 和比较基线下报告
显著 token 与 p95 延迟降低，证明“先检索、后注入”的方向值得评测，但不能把论文数字直接外推为
MiLAi 收益。

吸收：

- scope/filter 必须早于 expensive retrieval；
- 小 `top_k` 加分数阈值；
- reranker 只处理有限候选；
- 按用户、Agent、session/goal 建立明确 query scope。

拒绝：

- Agent 自主 `update/delete` 正式记忆；
- 让提取模型同时担任事实批准者；
- 用“更相似”替代 authority、OpenIssue 和 Evidence lineage 检查。

主参考：<https://arxiv.org/abs/2504.19413>

## 3.3 ReMe

ReMe 值得吸收的是 context management，而不是 canonical memory 模型：

- 长工具输出移出 prompt，只保留摘要、hash 和恢复 pointer；
- before-reasoning hook 在模型调用前管理上下文；
- BM25 作为无需 embedding/LLM 的廉价首级召回；
- 大内容按范围渐进读取，不一次展开全部正文；
- 摘要可异步生成，不阻塞当前推理。

MiLAi 中异步摘要只能是派生表示，必须可追溯到 canonical ID/version，且任何 pointer 恢复都重新检查
权限、retention 和 revocation。

主参考：<https://github.com/agentscope-ai/ReMe>

## 3.4 Hindsight

Hindsight 的 recall API 提供按请求控制的 budget、`max_tokens`、chunks、source facts 和阶段阈值，并在
trace 中记录每个阶段耗时。对 MiLAi 最有价值的是：

- 由服务端执行 token-aware selection，而不是把所有 items 返回后让 Agent 截断；
- keyword/semantic candidate floor 和 post-rerank floor 分离；
- source facts 去重并使用独立 budget；
- 提供低/中/高三种查询深度；
- 限制 CPU reranker candidate 和并发。

主参考：<https://hindsight.vectorize.io/developer/api/recall>

## 3.5 OpenViking

OpenViking 的 `context` retrieval 与本设计最接近：服务端统一组装上下文，执行 budget、层级降级、跨轮
去重，并在没有相关 memory 时不注入内容。MiLAi 吸收概念，不引入它作为 Runtime 依赖：

- 每个对象提供 `ABSTRACT / OVERVIEW / FULL` 层级；
- 大对象优先降低表示层级，而不是从中间截断；
- query expansion 有严格上限、超时和 fallback；
- Context 类型按 bucket 配额；
- 支持跨轮 digest/dedup；
- `NO_RELEVANT_MEMORY` 对应零注入。

主参考：<https://docs.openviking.ai/en/api/06-retrieval>

## 3.6 Graphiti

Graphiti 的 temporal fact、episode provenance、hybrid search 和 historical query 对 MiLAi 的 L1/L2 评测
有价值。近期只吸收：

- `as_of` 与有效时间在候选生成前过滤；
- FTS/vector 使用 Reciprocal Rank Fusion；
- MMR 降低同义重复项；
- compact fact 与 provenance pointer 分离；
- query path 不增加生成式 LLM 摘要调用。

Graph traversal 仍为 PARKED。Lean V1 不增加 Neo4j 或 Graphiti 在线依赖。

主参考：<https://github.com/getzep/graphiti>

## 3.7 LangGraph、AutoGen 与 OpenAI Agent 指南

LangGraph 明确区分 thread-scoped short-term state 与 cross-thread long-term memory，并允许把 memory write
放入后台。MiLAi 应保留为 long-term governed service；LangGraph state 只保存当前 MiLAi snapshot/slot ID。

主参考：<https://docs.langchain.com/oss/python/concepts/memory>

AutoGen 提供 token-limited model context，可调用具体 model client 的 token counter，并把 tool schema 纳入
计算。MiLAi AutoGen adapter 应要求或推荐该 context，且必须替换旧 memory slot，而不是无限追加。

主参考：<https://microsoft.github.io/autogen/stable/reference/python/autogen_core.model_context.html>

OpenAI 官方 Agent/Model 指南建议只暴露当前任务真正相关的工具、精简描述、利用 prompt caching，并在
代码侧执行过滤、排序、去重和聚合。该原则使“动态工具 profile + Context Compiler”优先于继续增加
模型可见工具。

主参考：<https://developers.openai.com/api/docs/guides/latest-model>

## 3.8 OSPC 吸收结论

本地 pilot 已因强 `typed_state` 和 `static_open_issue` baseline 等价而放弃 OSPC novelty。产品优化只吸收
已经被证据支持的简单机制：

```text
protected fields
minimum feasible budget B_min
structured eviction
explicit infeasible result
deterministic fallback
```

不创建新的 OSPC 在线组件，不增加模型调用，也不恢复 novelty 声明。

---

# 4. 优化目标、非目标与量化口径

## 4.1 产品目标

### O-01 Token 可证明

每次 Agent 模型调用都能区分并记录：

```text
provider input tokens
cached input tokens
MiLAi memory tokens
MiLAi tool schema tokens
MiLAi tool-result tokens
output/reasoning tokens when provider exposes them
```

没有真实 provider tokenizer 时，只能报告 bytes 和 evaluation-token proxy，不能声称计费 token。

### O-02 上下文不随轮次二次增长

同一会话只存在一个逻辑 `milai_memory_slot`。新 snapshot 替换旧 snapshot；相同 snapshot 不重复注入。

### O-03 按需召回

普通对话、格式转换、纯计算和无 memory 依赖的工具步骤不调用 MiLAi。Action-safe、删除、权限、当前状态
和明确记忆问题仍必须使用合适的 canonical consistency，不能为了延迟跳过 gate。

### O-04 小而安全的上下文

默认返回 1～3 个最相关 canonical item。超出预算时依次降低 payload 层级、使用 pointer、删除低优先级
item；永远不静默删除 protected OpenIssue 状态。

### O-05 不增加生成式召回成本

默认 L0/L1 recall、context selection、去重、fusion 和 budget allocation 均为确定性或本地模型路径。
Query expansion 或总结若未来启用，必须 opt-in、计入成本并有 deterministic fallback。

### O-06 可诊断

能够解释：为什么召回、为什么未召回、缓存是否复用、哪些对象被降级或省略、消耗多少 token、使用何种
tokenizer、花费在哪个阶段。

## 4.2 非目标

- 本文不承诺通用“记忆质量超过 Mem0/Hindsight/Graphiti”；
- 不把探索性测量写成 Production SLA；
- 不通过更大 context window 掩盖重复输入；
- 不依赖 prompt caching 获得正确性；
- 不为 token 节省牺牲 trace、authority 或冲突表示；
- 不在本阶段实现通用模型路由、Agent 编排器或多 Agent 共享记忆。

## 4.3 成本比较边界

必须至少分别报告：

```text
MiLAi service latency
Agent-to-MiLAi network latency
extra model round trips
provider input/cached/output tokens
local embedding/reranker CPU time
external API cost
task quality and safety regressions
```

“减少模型 token，但增加一次模型工具选择回合”不能只报告 token；必须同时报告 end-to-end wall time 和
额外模型调用次数。

---

# 5. 目标逻辑架构

## 5.1 组件图

```text
┌──────────────────── Agent Framework ────────────────────┐
│ current turn / active goal / framework state            │
│                                                         │
│  Host Policy ─→ Recall Router ─┬─ NONE                  │
│                                ├─ CACHE                 │
│                                ├─ L0 exact              │
│                                └─ L1 hybrid             │
└──────────────────────────────────────┬───────────────────┘
                                       │ typed request
┌──────────────────── MiLAi Agent Integration Plane ───────┐
│ Python SDK / hook / LangGraph / AutoGen / MCP            │
│ Dynamic Tool Profile                                     │
│ Context Compiler + TokenCounter + Session Slot Registry  │
└──────────────────────────────────────┬───────────────────┘
                                       │ REST
┌──────────────────── MiLAi Runtime ────────────────────────┐
│ QueryPlan → L0/L1 candidates → Canonical Gate            │
│ → governed result + OpenIssue + trace + watermark         │
│                                                         │
│ PostgreSQL Canonical Core + derived FTS/vector projection │
└───────────────────────────────────────────────────────────┘
```

## 5.2 新组件不拥有 canonical 权限

| 组件 | 允许 | 禁止 |
| --- | --- | --- |
| Recall Router | 选择不召回、缓存、L0、L1 | 决定 Claim 是否真实、关闭 Issue |
| TokenCounter | 计算模型输入成本 | 修改 payload 或权威状态 |
| Context Compiler | 选择表示层级、去重、生成 delta | 创建 Evidence/Claim、丢弃 protected state |
| Slot Registry | 保存会话当前 snapshot/hash | 充当长期事实源 |
| Reranker | 对已过滤 candidate 排序 | 绕过 Canonical Gate |
| Tool Profile | 减少当前模型可见工具 | 给模型提升权限 |

## 5.3 默认推荐接入模式

```text
host-side deterministic router
+ pre-model recall hook
+ replaceable memory slot
+ on-demand detail/recovery tools
```

原因：

- 预模型 hook 不需要先由 LLM 决定是否调用 recall，避免额外生成回合；
- Router 可在无记忆需求时完全跳过调用；
- detail/recovery 保留 MCP 的按需能力，但不让完整工具目录占用每轮 prompt；
- host policy 保持 authority、scope 和 consistency 不可被模型覆盖。

纯 MCP 宿主无法提供 hook 时，可以使用 `reader-lite` catalog；敏感 submitter/operator profile 仍需显式
人工配置，不能由模型请求动态升级。

---

# 6. Recall Router 设计

## 6.1 输入合同

建议新增 framework-neutral、非持久化 typed model：

```yaml
RecallRoutingInput:
  current_turn: string
  active_goal: string | null
  previous_goal_fingerprint: string | null
  known_object_ids: [string]
  requested_scope: object
  required_authority: INFORMATIONAL | ACTION_SAFE | USER_CONFIRMED
  consistency_floor: EVENTUAL | READ_YOUR_WRITES | CANONICAL_REQUIRED
  session_snapshot_id: string | null
  canonical_position_seen: integer | null
  issue_revision_digest_seen: string | null
  framework_event: USER_TURN | TOOL_RESULT | MODEL_RETRY | BACKGROUND
```

模型不能通过输入字段降低 host 配置的 scope、authority 或 consistency floor。

## 6.2 输出合同

```yaml
RecallRoutingDecision:
  route: NONE | CACHE | L0 | L1
  reason_code: string
  query: string | null
  limit: integer
  allow_vector: boolean
  budget_class: LOW | STANDARD | HIGH
  cache_validation_required: boolean
```

Router 输出只控制检索成本，不控制 canonical acceptance。

## 6.3 确定性规则优先级

规则从高到低：

1. 删除、撤销、权限、当前状态、action-safe 或明确 Claim/OpenIssue ID：强制 L0/canonical；
2. 用户明确询问“记得什么、以前决定、偏好、历史、冲突”：L0 或 L1；
3. active goal、核心实体或 scope fingerprint 改变：L1；
4. 工具结果包含已知 MiLAi object ID：L0；
5. canonical/issue watermark 已验证未变化且 query fingerprint 相同：CACHE；
6. 问候、改写、格式化、纯计算、模型 retry、重复 tool rendering：NONE；
7. 无法安全判定且任务可能依赖正式状态：使用 host 的安全默认 L0/L1，不用 NONE。

第一版不得用生成式模型作 Router。后续若比较 learned router，必须以 deterministic router 为 baseline，
并报告 false-negative recall 对任务和安全的影响。

## 6.4 缓存键与失效

建议缓存键：

```text
sha256(
  normalized_query
  + active_goal_fingerprint
  + scope_hash
  + required_authority
  + consistency_floor
  + canonical_position
  + live_issue_revision_digest
  + retrieval_policy_version
)
```

失效条件：

- canonical commit sequence 推进；
- relevant OpenIssue revision 变化；
- Evidence revoke、permission 或 retention 状态变化；
- scope/authority/consistency 变化；
- active goal 改变；
- policy/tokenizer/context-compiler version 改变；
- TTL 到期。

`CANONICAL_REQUIRED` 缓存必须先验证 watermark。无法验证时不得把旧缓存伪装为当前状态。

---

# 7. Provider-aware Token Budget

## 7.1 TokenCounter 协议

建议在 Python SDK 定义：

```python
class TokenCounter(Protocol):
    @property
    def tokenizer_id(self) -> str: ...

    def count_text(self, text: str) -> int: ...

    def count_tools(self, tools: Sequence[Mapping[str, object]]) -> int: ...
```

adapter 从实际 model client 注入 TokenCounter：

- OpenAI：使用与请求模型对应的 tokenizer/官方 token usage；
- AutoGen：优先使用 model client 的 `count_tokens` 与 `remaining_tokens`；
- LangGraph：由所选 chat model adapter 提供；
- generic/MCP：宿主若无法提供，使用 bytes hard limit 并标记 `token_budget_verified=false`。

不能用 MiniLM tokenizer估算生成模型账单。

## 7.2 TokenBudget 合同

建议非持久化合同：

```yaml
TokenBudget:
  tokenizer_id: string | null
  max_memory_tokens: integer | null
  max_tool_schema_tokens: integer | null
  max_total_milai_tokens: integer | null
  max_bytes: integer
  budget_class: LOW | STANDARD | HIGH
  verified: boolean
```

建议初始候选值：

| 类别 | memory token | 典型用途 |
| --- | ---: | --- |
| LOW | 256 | exact ID、单个当前状态、pointer |
| STANDARD | 512 | 普通 recall，1～3 个 compact Claim |
| HIGH | 1,024 | 多对象、时间/冲突问题 |
| hard ceiling | 1,600 | 只有 protected minimum 可行且 host context 允许时 |

这些是待 provider workload 验证的开发默认值，不是 frozen SLA。

## 7.3 最小可行预算

Context Compiler 先计算：

```text
B_min
= wrapper and trust boundary
+ active hard constraints
+ required current ECS identity
+ every relevant live OpenIssue minimum representation
+ branch references
+ discharge rule minimum
+ authority/scope/consistency state
+ trace identity
```

若 `budget < B_min`：

- 返回 `CONTEXT_BUDGET_INFEASIBLE`；
- 不通过隐藏 OpenIssue 获得表面成功；
- host 可以增加预算、缩小 query/scope 或让 Agent abstain；
- 记录 infeasible，而不是计为零 token 成功。

## 7.4 实际 token 回报

每个 model-facing block 应携带或在 side metadata 返回：

```yaml
budget:
  tokenizer_id: string | null
  verified: boolean
  max_tokens: integer | null
  actual_tokens: integer | null
  max_bytes: integer
  actual_bytes: integer
  protected_minimum_tokens: integer | null
```

模型正文中不必重复所有计费 metadata；能由 framework side channel 提供时，应避免再次消耗 prompt。

---

# 8. Governed Context Compiler

## 8.1 输入

```yaml
ContextCompileRequest:
  recall_envelope: RecallEnvelope
  active_goal: string | null
  constraints: [string]
  previous_snapshot_id: string | null
  previous_content_hash: string | null
  token_budget: TokenBudget
  representation_policy_version: string
```

## 8.2 对象表示层级

### ABSTRACT

用于最小安全表示：

```text
object ID/version
subject + predicate or issue type
authority/status
scope/time summary
canonical position/revision
content hash or trace pointer
```

### OVERVIEW

在 ABSTRACT 基础上增加：

```text
compact typed payload
epistemic/freshness
OpenIssue target and branches
evidence pointer summaries
fallback/degraded reason
```

### FULL

增加当前 API 允许返回的完整 Claim payload 和 bounded metadata。Evidence 正文不默认展开；大正文、
工具日志和历史 trace 使用授权 pointer recovery。

## 8.3 固定分区

保持实施合同规定的 ContextCapsule 分区：

```text
[1] ACTIVE GOAL
[2] ACTIVE STATE
[3] OPEN ISSUES
[4] CONSTRAINTS
[5] RETRIEVED EVIDENCE
[6] TRACE POINTERS
```

预算分配不是固定百分比，而是按以下顺序：

1. 完整放入 protected minimum；
2. 将最相关当前 state 从 ABSTRACT 提升到 OVERVIEW；
3. 放入 supporting/contradicting Evidence pointers；
4. 增加次相关 Claim；
5. 在仍有预算时把高价值 item 提升到 FULL；
6. 剩余 item 只记录 omitted ID，不从结构中间截断。

## 8.4 选择与降级

候选排序信号可以包括：

```text
exact identity
scope/time match
required authority match
OpenIssue relevance
recency/freshness policy
FTS/vector fused score
MMR diversity
active goal overlap
```

排序分数不能提高 authority，也不能让被 Canonical Gate 拒绝的对象重新出现。

降级顺序：

```text
FULL → OVERVIEW → ABSTRACT → pointer-only → omitted ID
```

live OpenIssue minimum representation没有 `omitted` 路径；预算不足时整体 infeasible。

## 8.5 零注入

满足以下条件时，不给模型加入 MiLAi data block：

- Router 决定 NONE；
- recall 明确 `NO_RELEVANT_MEMORY`，且不存在相关 protected issue/state；
- snapshot/content hash 与上一轮相同，旧 slot 仍有效；
- 当前框架可保留旧 slot 且无需再次发送正文。

ABSTAINED 不能一律零注入。如果 abstention 或 degraded 状态会影响回答安全，必须注入极小的状态块，
告诉模型“不得依赖该记忆作正式判断”。

---

# 9. Memory Slot、Delta 与跨轮去重

## 9.1 Slot 合同

建议 adapter 内部维护：

```yaml
MemorySlot:
  slot_id: milai-memory
  session_id: string
  snapshot_id: string
  content_hash: string
  canonical_position: integer | null
  live_issue_revision_digest: string
  tokenizer_id: string | null
  actual_tokens: integer | null
  created_at: timestamp
```

MemorySlot 是短期接入状态，不是 canonical object，不需要成为数据库正式事实。

## 9.2 Delta 合同

```yaml
ContextDelta:
  status: UNCHANGED | REPLACE | REMOVE | INFEASIBLE
  snapshot_id: string | null
  added_object_ids: [string]
  changed_object_ids: [string]
  removed_object_ids: [string]
  rendered_context: string | null
  reason_code: string
```

默认对模型执行 `REPLACE`，而不是在旧 block 后追加 `added/changed` 文本。Delta metadata 主要用于 host、
trace 和 UI；只有模型确实需要理解变化时，才在预算内提供 compact change summary。

## 9.3 Framework 责任

- 框架必须能定位并替换 `slot_id=milai-memory` 的旧消息；
- 无 replace API 的框架应使用 bounded context processor，在调用模型前重建消息列表；
- 不允许依赖 `source` 文本碰撞识别其他应用消息；
- session close 只删除临时 slot，不删除 MiLAi canonical 数据；
- revoke 或 permission change 事件应使 slot 立即无效。

---

# 10. Dynamic Tool Profile

## 10.1 Profile 设计

| Profile | 模型可见工具 | 使用场景 |
| --- | --- | --- |
| `reader-lite` | `milai_recall` | 默认 MCP-only Agent |
| `reader-detail` | claim、issue、trace、evidence metadata 按需工具 | 调试、解释、pointer recovery |
| `submitter` | Evidence capture、Proposal submit，加必要 reader | 明确用户/工具观察流程 |
| `operator` | revoke/deletion status | 人类运维或受控 HITL，不作为通用模型默认 |

`milai_status` 默认由 host 在 session start 调用并缓存，不需要每轮作为模型 tool 暴露。

## 10.2 权限不随 catalog 动态提升

- profile 在 server/host 启动时由配置选择；
- 模型不能通过 prompt 请求从 reader 切换为 submitter/operator；
- profile 缩减只影响工具发现，不改变 API token 的实际 capability；
- 每个敏感调用仍使用 typed confirmation、scope、idempotency 和服务端授权；
- 工具目录缓存必须绑定 profile、server version 和 capability digest。

## 10.3 Tool result 分层

默认 `milai_recall` 返回 compact model-facing 结果：

```text
status
compact items
open issue minimum
trace_id
canonical_position
degraded/fallback/abstention
omitted IDs
```

完整 trace、Evidence metadata 或 Claim 详情由独立工具按 ID 恢复。任何恢复都重新执行 tenant、permission、
retention 和 revocation 检查。

---

# 11. Retrieval 与 Runtime 优化

## 11.1 L0 快路径

L0 保持不依赖向量：

```text
known object ID or exact subject/predicate
→ EffectiveClaimState
→ Canonical Gate
→ compact result
```

优化项：

- 对 object ID、subject/predicate 和 current head 使用明确索引；
- 避免为 L0 初始化 ONNX；
- 不为只有 status/identity 的请求加载 Evidence 正文；
- 在同一 read transaction 中取得 canonical position 和 issue revision。

## 11.2 L1 pipeline

目标顺序继续服从实施合同：

```text
tenant/scope/time/permission pre-filter
→ exact/FTS/vector candidate generation
→ score normalization
→ RRF fusion
→ deduplicate by canonical ID/version
→ optional MMR
→ optional bounded local reranker
→ resolve current canonical identity
→ Canonical Gate
→ Context Compiler
```

建议第一版参数候选：

```text
final result limit          3
FTS candidate limit        20–50
vector candidate limit     20–50
reranker input             ≤ 30
reranker output            ≤ 5
```

参数必须通过 quality/latency sweep 冻结，不能仅因外部项目默认值而采用。

## 11.3 Canonical-current 搜索投影

当前 canonical search 在查询中对当前 Claim 行构造 `to_tsvector`。规模测试若证明扫描或 CPU 成本不可接受，
可以设计一个只读、可重建、带 canonical ID/version/commit sequence 的 current-search projection：

- projection 不是正式状态源；
- Outbox 和 watermark 保证可追踪更新；
- candidate 返回后仍执行 Canonical Gate；
- projection stale 只能降低 recall；
- migration、回填、索引大小、故障和重建必须有真实 PostgreSQL 测试；
- 涉及 Schema 时保持 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。

## 11.4 HTTP 与进程效率

Python SDK 应引入 transport abstraction：

```text
AsyncTransport
├─ persistent HTTP/1.1 connection pool
├─ bounded connect/read/write/pool timeouts
├─ retry only for safe GET or idempotent write
├─ explicit close lifecycle
└─ trace/request ID propagation
```

具体依赖必须经版本锁定、许可证和 clean-install gate。若选择 `httpx.AsyncClient` 或等价实现，不得在
模块 import 时创建全局跨 event-loop client。

## 11.5 ONNX 预热与并发

- Runtime/worker ready 前可以执行一次 bounded synthetic warmup；
- warmup 失败时 vector route 标记 degraded，FTS/canonical 继续；
- 不因 warmup 失败放宽 authority gate；
- provider、reranker、API threads 和 DB pool 分别设 semaphore；
- 默认并发必须通过目标设备 `1/4/16` workload 调优；
- 删除/purge 工作仍优先于普通 embedding 补建。

## 11.6 Projection 批处理与窗口成本

当前 `derive_projection_fragments()` 对每个 turn chunk 建立一个 `turn` fragment，并为每对相邻 turn
再建立一个 `window` fragment。对于没有长文本切块的 `n` 个 turn，向量数量近似：

```text
n turn fragments + (n - 1) adjacent windows = 2n - 1 embeddings
```

当前 Worker 又逐 fragment 调用一次 `EmbeddingProvider.embed()`，并逐 fragment 写 projection。PE08
Horizon smoke 的 24,383 个 turn 因而产生 48,358 次 embedding；正式 314,080 个 turn 的当前估算是
622,905 次。这个扩张来自投影构建，不来自 answer model。

优化分两步实施：

1. **保持表示不变，先批量执行。** 为下一 Runtime candidate 增加 `embed_many()`、有界 batch、文本
   去重和批量 projection write；每个 Outbox 的幂等、顺序、watermark 和错误归属仍逐事件保留。
2. **再做表示消融。** 比较 `turn + window vector`、`turn vector + window FTS`、由相邻 turn vector
   确定性组合 window 等方案。只有质量、更新、冲突和 revoke 回归通过后，才能减少 window 数量。

正式产品吞吐只能由包含上述 Runtime 能力的新候选声明。Evaluation-only 预计算可以加速论文质量实验，
但必须使用单独身份和等价性报告，且不得用于产品 latency/throughput claim。

---

# 12. Framework 接入优化

## 12.1 Generic Python Agent

推荐生命周期：

```python
decision = router.decide(turn, host_policy, session_state)
delta = memory.prepare_context(decision, token_counter=model.count_tokens)
messages = replace_slot(messages, "milai-memory", delta)
response = model.invoke(messages, tools=tool_profile.for_turn(decision))
```

`before_model` 应增加 token budget、previous snapshot 和 delta 输出，同时保留当前 byte-only 调用的兼容层。

## 12.2 LangGraph

Graph state 只保存：

```text
milai_snapshot_id
milai_slot_hash
canonical_position_seen
live_issue_revision_digest
```

推荐节点：

```text
route_memory
→ recall_if_needed
→ compile_context
→ replace_model_slot
→ model
```

LangGraph checkpointer 保存 thread execution state，MiLAi 保存 governed long-term memory。后台 observation
处理只能创建 Evidence/Proposal；不能在 background task 自动批准 canonical mutation。

## 12.3 AutoGen

当前 `update_context` 追加 `UserMessage` 的实现应改为：

1. 使用 `TokenLimitedChatCompletionContext` 或等价 token-aware context；
2. 从当前模型上下文移除旧 `source=milai-memory-data` 且 slot ID 匹配的消息；
3. snapshot unchanged 时不添加新消息；
4. REPLACE 时只添加一个新 memory message；
5. clear/close 不操作 canonical state。

若官方 context API 不提供安全 replace，adapter 在调用模型前创建受控的派生消息列表，不修改原始业务
消息。

## 12.4 MCP

MCP-only 模式存在一次额外 tool decision/round-trip 的可能，因此：

- 默认 catalog 使用 `reader-lite`；
- tool description 保持短而完整，不重复长安全说明；
- server instructions 保留一次 data-only trust boundary；
- recall result 默认 STANDARD budget 与 limit 3；
- detail 通过 ID 按需恢复；
- 支持宿主 tool-choice/prompt caching 时记录实际 cached tokens；
- catalog 变化不用于隐式权限升级。

## 12.5 Hook 模式

对于每轮高概率需要 memory 的 coding/personal assistant，pre-model hook 通常优于先让模型决定是否调用
工具；对于 memory 稀疏任务，host Router 先决定 NONE，再决定是否执行 hook。

最终选择必须由 workload A/B 决定：

```text
hook: fewer model round trips, host must route correctly
MCP: on-demand and portable, may add schema tokens and one model/tool turn
hybrid: host recall + minimal on-demand detail tools
```

本文推荐 `hybrid` 作为默认产品路径。

---

# 13. 可观察性与计费证据

## 13.1 每次 Agent 调用指标

建议记录以下不含正文的结构化字段：

```text
agent_framework
model_provider / model_id
tokenizer_id
recall_route and reason_code
consistency / required_authority
cache_hit / cache_validated
snapshot_id / context_hash
tool_profile and tool_count
tool_schema_tokens
memory_context_tokens
memory_context_bytes
provider_input_tokens / cached_input_tokens / output_tokens
retrieval_total_ms
router_ms / search_ms / gate_ms / compile_ms / network_ms
candidate_count / gated_count / returned_count / omitted_count
representation tiers
extra_model_round_trips
degraded / fallback / abstention / infeasible
```

不能记录：

```text
完整用户消息
完整 Evidence 正文
完整模型 prompt
token、password、KEK、cookie
未脱敏的个人数据
```

## 13.2 派生指标

```text
recall rate
useful recall rate
no-result rate
cache hit rate
unchanged snapshot rate
duplicate injection rate
tokens per successful task
MiLAi token share of provider input
tokens avoided by NONE/CACHE/delta
p50/p95/p99 by L0/L1 and cold/warm
extra LLM turns per task
OpenIssue preservation rate
unsupported answer / false closure rate
```

“useful recall”必须由任务结果、引用使用或独立 label 判断，不能让 Router 自评。

## 13.3 Trace 关系

Agent integration trace 应引用现有 `retrieval_trace_id`，但不把 provider token 明细塞入 canonical state。
推荐使用独立、短期、脱敏的 Agent execution report；若未来持久化，必须明确 retention 与访问权限。

## 13.4 Provider A/B 证据执行器

`evals/agent_efficiency/provider_ab.py` 的 v3 manifest/approval 协议实现 provider-agnostic JSONL
adapter 边界（adapter JSONL wire protocol 仍为 v2）。冻结
workload 对同一精确 model 交替执行 baseline/optimized，并记录每一个 native provider call identity、
原生 usage、目标 tokenizer 的 memory/tool 分项、terminal receipt、end-to-end wall time 与独立标签评分。
保留报告只含规范化五字段输出、哈希、ID、计数、耗时和评分，不含 prompt、Memory/Evidence、原始模型
输出或 stderr。工具不把 adapter 自报 usage 称为 verified，只有独立 provider 复核能够改变验收结论。

安全门包括：

- `plan` 不启动 adapter、不联网；approval SHA-256 必须从 manifest 外传入，并绑定 manifest、workload、
  pricing、runtime/source/dependency closure、host-execution closure、精确 shipped tool schema、预算和
  operator；`run` 还必须匹配带外 `plan_sha256`；
- 不接受 caller command/argv。runner 打开并验证 exact runtime/source FD、pin 每个 dependency byte，
  执行后复算；dependency lock 必须枚举 runtime 库、导入代码/数据和每个子程序的传递依赖；Landlock
  `READ_FILE/EXECUTE` 只放行这些批准字节，未声明宿主程序或代码读取 fail closed；
- `host-lock` 独立枚举 sandbox launcher/Python、全部 file-backed 静态 import、`unshare`、namespace/
  network helper 及递归 ELF 依赖。manifest、带外 approval、deterministic plan 和 report 绑定同一闭集
  hash/root/count/policy；运行器自行重建而不信任手写清单，缺项/多项/字节漂移均 fail closed；
- 所有 host closure 文件在启动 namespace 前以 `O_NOFOLLOW` 打开并哈希，运行后同时复核保留 FD 与原
  路径的 device/inode/size/SHA-256，防止 validation/run 或 path replacement 证据被接受；
- final rehash 前必须先停止并 bounded-wait adapter PID namespace 和持久 network helper；任何 helper
  仍存活或退出不可确认时跳过 post assertion、保持 false 并输出 `FAIL_PARTIAL`；
- adapter 在独立 mount/PID/network namespace 中以非 root uid/gid 和 `no_new_privs` 运行；workspace、
  `/root`、通用 DNS、proxy 和未审批环境均隐藏。真实 egress 仅允许 approval 绑定 IP 的 TCP/443；fixture
  使用 deny-all；凭据只使用 `MILAI_PROVIDER_CREDENTIAL_*` 别名，privileged Python 固定 `-I -S`；
- baseline/optimized 工具目录直接从 inventory-bound `create_milai_tools(reader/reader-lite)` 导出；
- 每个 model call 前用目标 tokenizer 对完整 request 计数并预留 input/output 最大费用；超限在 charge
  前停止。返回总 usage 必须等于全部 native call usage，ID 全局唯一，terminal/finish/output 为闭集；
- 每个 adapter 返回字符串先与内存中的全部 provider secret 比较，匹配即 fail closed 且不保留值；
- capture reconciliation 对精确 1000 个有序 record、全部 request/prompt/tool/output/native receipt、
  aggregate 和完整 gate set 从零重算；手写 status、空 gates、少量 ID 或任意 tolerance 均无效；
- billing reconciliation 同时打开并哈希仓库外 normalized export 与真实 upstream invoice/export，逐
  native request-ID 重算 coverage/总额；tolerance 只能来自 approval，actual 仍不能超过 cost ceiling；
- 非阻塞读取使用总 deadline 和 2 MiB 上限；超时终止整个进程组/PID namespace，已发生调用原子保留
  `FAIL_PARTIAL` cost/ID receipt。

完整 capture 只产生 `PROVIDER_CAPTURE_COMPLETE_REVIEW_REQUIRED`，账单匹配只产生
`PROVIDER_EVIDENCE_RECONCILED_REVIEW_REQUIRED`，二者都不是 PASS。离线 fixture 可走完整协议但不能
设置真实 provider 门。只有真实 capture、native receipt/账单对账与后续独立审查单独接受，OE-F06
才能关闭。

---

# 14. 预期收益模型

## 14.1 100 轮 token 情景

假设：

```text
100 turns
20% turns truly need recall
recall turn uses one tool schema
each result contains 1–5 current items
evaluation tokenizer = ospc.regex.v1
```

当前 MCP reader 若每轮均可见并召回：

```text
low  = 100 × (791 + 408)   = 119,900
high = 100 × (791 + 1,304) = 209,500
```

优化后只在 20 轮暴露 `milai_recall`：

```text
low  = 20 × (185 + 408)   = 11,860
high = 20 × (185 + 1,304) = 29,780
```

模型结果：

```text
estimated reduction = 85.8%–90.1%
```

这是在明确假设下的容量模型，不是实际 provider 账单。实现后必须以 provider usage 和 target workload
替换评估 tokenizer。

## 14.2 Direct hook 情景

若 hook 不向模型暴露 recall tool，且 Recall Router 将召回频率从 100% 降到 20%，memory block 本身由：

```text
40,800–130,400
```

下降到：

```text
8,160–26,080
```

即约 `80%`，并且 replace-not-append 消除跨轮三角累计。

## 14.3 延迟情景

在不计 Agent 网络的粗略模型中：

```text
amortized recall overhead ≈ recall_rate × warm_recall_latency
```

如果 20% 轮次 recall，warm service latency 在 `20–75 ms`，则平均每轮服务侧开销约 `4–15 ms`。
这只是当前小样本推导；万级 Claim、真实并发和实际网络必须重新测量。

主要延迟收益来源预计按顺序为：

1. NONE/CACHE 直接跳过请求；
2. 避免额外 LLM tool-choice 回合；
3. ONNX 预热消除首次约 1 秒尖峰；
4. 持久 HTTP 连接降低连接和线程切换开销；
5. 小 candidate set 与 bounded reranker；
6. 规模化 current-search projection。

---

# 15. 开发阶段与任务

## OE-00 冻结优化基线

交付：

- 固定 20/100/500-turn synthetic Agent workload；
- 固定 1/1k/10k/100k Claim 数据集生成器；
- 记录目标设备、模型、tokenizer、provider pricing snapshot；
- 建立 current hook/MCP/LangGraph/AutoGen baseline；
- 分别记录 cold/warm、concurrency 1/4/16；
- 输出不可修改的 baseline report 与输入 SHA。

退出条件：所有后续收益都有同 workload、同模型、同总任务和同质量口径的 current baseline。

## OE-01 Provider Token Accounting

交付：

- `TokenCounter` protocol；
- Python SDK formatter 接入；
- framework adapter 注入；
- tool schema 与 memory 分项计数；
- bytes fallback 和 `verified=false`；
- token metadata privacy tests。
- provider A/B JSONL adapter、真实 usage/request identity 校验与逐 request-ID billing reconciliation；

兼容：当前 `max_bytes` API 保留；未传 TokenCounter 的调用不报虚假 token。

## OE-02 Memory Slot 与 Delta

交付：

- `MemorySlot`、`ContextDelta` typed model；
- content/snapshot hash；
- replace/remove/unchanged 行为；
- revoke/permission/issue revision invalidation；
- AutoGen、LangGraph 和 generic adapter 实现；
- 500-turn no-quadratic-growth test。

## OE-03 Recall Router 与 Reader-lite

交付：

- deterministic Router；
- NONE/CACHE/L0/L1 reason codes；
- cache key/watermark validation；
- MCP `reader-lite` profile；
- session-start status cache；
- sensitive profile non-escalation tests。

## OE-04 Context Compiler v2

交付：

- ABSTRACT/OVERVIEW/FULL renderer；
- protected `B_min`；
- token-aware bucket allocator；
- structured downgrade、pointer 和 omitted IDs；
- zero injection、abstention minimal block；
- exact provider tokenizer regression tests。

## OE-05 Runtime 读路径优化

交付：

- persistent async transport；
- provider prewarm；
- candidate/final limits；
- RRF/MMR；
- optional bounded reranker；
- 10k/100k query plan evidence；
- 只有证据要求时才新增 current-search projection migration。

## OE-06 Framework E2E

交付：

- generic hook；
- MCP-only reader-lite；
- LangGraph slot replacement；
- AutoGen token-limited context；
- same workload cross-framework report；
- official pinned framework version and wire compatibility matrix。

## OE-07 优化候选验收

交付：

- token/latency/quality/security final report；
- external-project absorber comparison；
- package build、fresh install、example 和 CI；
- independent review；
- release/rollback runbook。

没有独立验收前只能称 `Optimization Candidate`。

---

# 16. 测试与评测设计

## 16.1 Unit

```text
token counter exactness for frozen strings/tools
B_min computation
protected field cannot be evicted
tier downgrade is structurally valid
unchanged snapshot emits no context
delta add/change/remove
router rule precedence
cache key includes scope/authority/consistency/watermark
profile cannot escalate
```

## 16.2 Contract

```text
current max_bytes client remains compatible
token-aware formatter reports actual token count
MCP reader-lite catalog is deterministic
tool output is bounded and typed
LangGraph/AutoGen host policy cannot be overridden by model input
context data remains data-only
```

## 16.3 PostgreSQL integration

```text
1 / 1k / 10k / 100k Claims
current and historical versions
open issues and revoked Evidence
scope/time selectivity
FTS/vector stale projection
canonical unavailable
concurrency 1 / 4 / 16
cold and warm runs
EXPLAIN plan and index bytes
connection pool saturation
```

## 16.4 Agent E2E

至少包含：

1. 100 轮中只有 20 轮需要记忆，验证 Router 和 token 节省；
2. 相同问题连续出现，验证 snapshot unchanged 零注入；
3. goal 改变，验证 cache invalidation 和新 recall；
4. conflict 两 branch 都存在，任何 budget 下不能错误闭合；
5. Evidence revoke 后旧 slot 失效，stale index 不能恢复 authority；
6. canonical unavailable，action-safe 问题 abstain；
7. MCP detail recovery 只按 ID 恢复授权内容；
8. submitter 只能创建 Evidence/Proposal，不能 self-review；
9. 500 轮 context 不出现二次 token 增长；
10. hook 与 MCP-only 比较额外模型回合和 end-to-end wall time。

## 16.5 Benchmark

使用本地已有：

```text
BEAM
CUPID
HorizonBench
LongMemEval / LongMemEval-V2
Memora
PAHF
MiLAi governed-conflict fixtures
actual synthetic coding/personal-agent tasks
```

比较组：

```text
A  full retained history
B  current MiLAi adapter
C  optimized MiLAi router + compiler
D  selected pinned external baseline where runnable
```

所有方法使用相同任务、模型、provider配置、初始权限、最大模型调用数和总计费口径。

MiLAi benchmark 必须同时提供三种互不混名的执行模式：

```text
reference-faithful  少量 case 完整冷启动产品链，验证真实性
evaluation-fast     常驻隔离 Runtime Slot，批量生成正式质量实验的 context
online-latency      数据与 projection 已就绪，只测 Agent/MCP 稳态查询
```

每种模式必须分别记录 bootstrap、governed ingest、projection、query、MCP、answer 和 judge；BM25、dense
及外部系统也应将 index build 与 query 分开。不得将 BM25 内存 warm query 与 MiLAi 每 case 冷部署总成本
放在同一 `query latency` 列中。详细生命周期、等价性与实施顺序见 §22。

## 16.6 质量与安全指标

```text
task success
answer correctness
claim/evidence citation accuracy
OpenIssue identity recall
branch and discharge recall
false epistemic closure
unsupported answer rate
authority escalation rate
abstention precision/recall
deletion/revocation stale-return rate
```

token 降低但任一 frozen invariant 或安全指标退化，判定失败。

---

# 17. 候选性能目标与优化门

以下是需要实测证明的 candidate target，不是当前 SLA。

| Gate | 候选条件 |
| --- | --- |
| `OG-00 Reproducible Baseline` | workload、模型、tokenizer、输入 SHA、current 结果完整 |
| `OG-01 Token Truth` | provider token 与 MiLAi 分项可核对；无 tokenizer 时不虚构 |
| `OG-02 No Quadratic Growth` | 500-turn 测试无重复 slot 累积；unchanged 再注入为 0 |
| `OG-03 Compact Tools` | target provider 下 reader-lite schema ≤ 250 tokens |
| `OG-04 Context Budget` | STANDARD ≤ 512、HIGH ≤ 1,024、hard ceiling ≤ 1,600；infeasible 明确 |
| `OG-05 Session Cost` | 冻结 100-turn workload 的 MiLAi extra input < 30,000 tokens |
| `OG-06 Warm L0` | 10k Claim 目标设备 p95 < 30 ms |
| `OG-07 Warm L1` | 10k Claim 目标设备 p95 < 100 ms |
| `OG-08 Cold Start` | prewarmed ready 后首个正常查询 < 250 ms；失败可解释降级 |
| `OG-09 Quality` | 相对 current MiLAi 无显著任务质量、安全或 trace 回归 |
| `OG-10 Frameworks` | generic/MCP/LangGraph/AutoGen 同合同与边界通过 |
| `OG-11 Failure Safety` | stale cache、revocation、DB/provider 故障均 fail closed |
| `OG-12 Independent Review` | 所有 P0/P1 关闭后才允许状态晋级 |

若目标设备或模型证明某个数值不合理，应以 baseline、ADR 和新证据修改 candidate target；不能把失败结果
反向解释成已达标。

---

# 18. 风险、回滚与安全分析

## 18.1 Router false negative

风险：本轮需要正式记忆但 Router 选择 NONE。

控制：action-safe/current-state/权限/删除/显式 memory 问题使用强制规则；不确定时使用安全 recall；记录
false-negative label 并独立评测。

## 18.2 Stale cache

风险：旧 snapshot 在 Claim、Issue、revocation 或权限变化后继续进入模型。

控制：缓存键绑定 canonical position 和 issue revision digest；revoke/permission 事件主动失效；
canonical-required 必须验证 watermark，无法验证则 abstain。

## 18.3 Token budget 导致语义丢失

风险：为了满足预算而丢失 conflict branch 或 discharge rule。

控制：protected `B_min`、结构化层级降级和明确 infeasible；禁止自然语言摘要替代结构化 Issue minimum。

## 18.4 Reranker 提高延迟或改变候选

风险：CPU saturation，或相似度排序隐藏不同 branch。

控制：候选上限、semaphore、超时 fallback、branch-aware diversity；reranker 只排序，不通过 gate。

## 18.5 Dynamic tools 造成权限混淆

风险：模型把 catalog 变化理解为权限升级。

控制：profile 由 host 配置，server 仍做实际授权；模型不能切 profile；敏感操作保留 confirmation/HITL。

## 18.6 Prompt caching 误用

风险：缓存降低账单但保留 stale memory，或把缓存命中当正确性证据。

控制：prompt caching 只作为 provider 成本优化；memory snapshot 仍按 canonical watermark/version 失效。

## 18.7 新 search projection

风险：派生 current index 被误认为 canonical state。

控制：命名、角色和权限隔离；只返回 candidate；Canonical Gate 必须重新读取/验证正式状态；可整库重建。

## 18.8 回滚策略

P0 adapter 优化不需要 Schema 变更，应保留 current formatter/client 兼容路径。建议通过版本化配置逐项启用：

```text
context compiler v1 | v2
recall router off | deterministic
reader profile current | lite
transport urllib | pooled-async
reranker off | local-bounded
```

上表是配置设计，不表示当前已有这些环境变量。回滚不得恢复已撤销 Evidence、绕过新权限状态或把旧 cache
重新视为 current。

若 OE-05 新增 projection migration：

- canonical tables 不做破坏性修改；
- projection 可停止写入并从 Outbox 重建；
- downgrade 若不安全则明确 forward-only，并提供 verified restore/forward repair；
- 旧 Runtime 与新 projection version 的兼容矩阵必须测试。

---

# 19. 依赖与下载决定

## 19.1 当前不需要新增生产 memory backend

已有本地 Mem0、Graphiti、ReMe、Hindsight 和 benchmark 足以支撑实现与对照。OpenViking、MemGPT/Letta
继续作为设计参考，不进入 Lean Runtime 启动依赖。

## 19.2 可能新增的实现依赖

只有在代码阶段证明确有必要时考虑：

| 能力 | 首选策略 | 新依赖条件 |
| --- | --- | --- |
| provider token count | 复用宿主 model client | SDK 无公开计数能力时才增加 pinned tokenizer |
| async HTTP pool | 小型 transport abstraction | 标准库无法满足目标并发证据时采用 pinned client |
| RRF/MMR | 本地确定性实现 | 不需要新服务 |
| reranker | 复用当前本地 ONNX 能力 | 新模型必须有 identity、license、quality/latency gate |
| metrics | 复用当前结构化日志/报告 | 不为早期本地 Runtime 引入独立 telemetry 服务 |

每个新依赖必须记录版本、hash、许可证、离线安装、移除方案和数据外发边界。

---

# 20. Definition of Done

MiLAi Agent Execution Optimization 0.1 只有在以下事实同时成立时才完成：

1. 每个受支持 provider 的 MiLAi memory/tool token 能真实计数或明确标记未验证；
2. 同一 session 的 memory 使用 replace/remove/unchanged，不随轮次二次增长；
3. Recall Router 能跳过无关轮次，且 action-safe/current-state 路径不会因优化绕过 canonical recall；
4. reader-lite 将默认模型工具面收敛到最小必要集合；
5. Context Compiler 在预算内保护 Goal、Constraint、ECS、OpenIssue、branch、discharge、authority 和 trace；
6. 预算不可行时显式失败或 abstain，不通过字段丢失获得成功；
7. cache、prompt caching、search projection 和 reranker 都不能成为 canonical authority；
8. revoke、permission、retention、Issue revision 和 canonical position 变化能及时失效 slot/cache；
9. generic、MCP、LangGraph、AutoGen 使用同一 host-policy 与治理边界；
10. 100/500-turn workload 证明无重复增长，并报告实际 provider token、额外模型回合和 wall time；
11. 10k/100k Claim、并发与冷暖路径有可复现证据；
12. 与 current MiLAi 相比，任务质量、OpenIssue preservation、authority 和删除安全无回归；
13. package、clean install、examples、CI、security scan 和独立审查通过；
14. Runtime 仍不依赖任何外部 memory engine；
15. Schema 仍明确保持 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`，除非未来独立流程正式晋级。

最终允许的发布叙事：

```text
MiLAi Agent Execution Optimization 0.1 provides measured,
provider-aware and bounded memory injection for supported local Agent integrations,
while preserving the frozen canonical governance and fail-closed safety model.
```

在 OG-00～OG-12 和独立审查完成前，只能称为设计或优化候选。

---

# 21. 参考材料

## 21.1 MiLAi 规范与证据

- `MiLAi_Logical_Architecture_v1_设计文档.md`
- `MiLAi_Lean_V1_实施合同.md`
- `MiLAi_可用性与Agent接入设计开发文档_v1.md`
- `architecture/v1.0/`
- `docs/reports/UA-06-retrieval-quality-performance-evidence-2026-08-17.md`
- `research/ospc/results/pilot_report.md`
- `integrations/python-client/src/milai_client/formatting.py`
- `integrations/python-client/src/milai_client/lifecycle.py`
- `integrations/mcp/src/milai_mcp/server.py`
- `integrations/langgraph/src/milai_langgraph/nodes.py`
- `integrations/autogen/src/milai_autogen/memory.py`
- `runtime/src/milai/persistence/retrieval_repository.py`
- `runtime/src/milai/domain/retrieval_projection.py`
- `runtime/src/milai/workers/main.py`
- `evals/paper/experiment-protocol.yaml`
- `evals/paper/runners/extended_milai_contexts.py`
- `evals/paper/runners/memora_milai_contexts.py`
- `var/dg11/current-state.json`
- `var/dg11/paper/runs/pe08-preference-smoke-20260824-001/result-001.json`
- `var/dg11/paper/runs/pe08-preference-smoke-20260824-001/resource-estimate-002.json`

## 21.2 外部一手资料

- Mem0 paper：<https://arxiv.org/abs/2504.19413>
- ReMe official repository：<https://github.com/agentscope-ai/ReMe>
- Hindsight Recall：<https://hindsight.vectorize.io/developer/api/recall>
- OpenViking Retrieval：<https://docs.openviking.ai/en/api/06-retrieval>
- Graphiti official repository：<https://github.com/getzep/graphiti>
- LangGraph Memory：<https://docs.langchain.com/oss/python/concepts/memory>
- AutoGen Model Context：<https://microsoft.github.io/autogen/stable/reference/python/autogen_core.model_context.html>
- MemGPT paper：<https://arxiv.org/abs/2310.08560>
- OpenAI Model/Agent Guidance：<https://developers.openai.com/api/docs/guides/latest-model>

外部项目行为、版本和许可证可能变化。正式 baseline 或代码复用必须使用固定 commit/package、lock、license
snapshot 和本地 manifest，不能只引用网页的 latest 状态。

---

# 22. DG11 Benchmark Harness 高效执行设计

本节是 2026-08-24 基于真实 paper smoke 与当前实现补充的 Evaluation Plane 设计。它解决
“每个 benchmark case 重建一次完整 MiLAi 部署”的执行问题，不改变冻结 Logical Architecture，默认也
不修改 DG11 frozen candidate。

## 22.1 当前实验状态与事实基线

权威状态来自 `var/dg11/current-state.json`，不能由本设计文档自动晋级：

```text
phase                    DEVELOPMENT_CLOSED
functional_status        PASS
quality_status           QUALITY_TARGET_NOT_MET
paper_evaluation_status  NOT_STARTED
frozen candidate         712577d17403951bdb6b7f6c7b6a2763b4b964427df33a857b02a316fbe74d51
```

“正式论文评测未开始”与“paper harness smoke 已运行”并不冲突。PE08 context smoke 的最新事实是：

| 数据 | case | session / turn | embedding | 当前记录的 query-path latency | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| CUPID smoke | 6 | 48 / 264 | 651 | 合计 `22.750 s`，均值 `3.792 s` | 6/6 success |
| Horizon smoke | 10 | 943 / 24,383 | 48,358 | 合计 `73.075 s`，均值 `7.308 s`，范围 `4.601–9.866 s` | 10/10 success |

以上运行的 answer/judge/provider generation 调用均为 0，正式标签未打开；成本来自 MiLAi 环境、治理写入、
projection 和 query。Horizon 正式 120-case 输入包含 11,822 个 session、314,080 个 turn，当前线性估计
为 622,905 次 embedding；CUPID 正式估计为 12,416 次，PE08 合计 635,321 次。资源 ceiling `PASS`
只表示没有超过预注册上限，不表示这种执行方式合理或高效。

PE08 曾披露并修复 query 超过 2,000 字符、单次 HTTP 500 以及 PostgreSQL 不接受 U+0000 三类 harness
问题；最终 smoke 成功且未修改 frozen candidate。它们证明 checkpoint/输入适配仍需保留，但不应继续
用版本化 failure report 替代执行架构改造。

PE07 BEAM 已实现按共享 history cohort 复用：正式计划为 20 个 history、每个 history 20 个问题。
这证明 history-level 生命周期是可行方向；但当前 `_CohortRuntime` 仍为每个 cohort 新建数据库、迁移、
启动和销毁 Runtime，因此只完成了“摄取一次、多次 query”，尚未完成 run-level 基础设施复用。

## 22.2 当前设计缺陷

### 22.2.1 生命周期混叠

`extended_milai_contexts.py` 当前逐 case 调用 `lme_product_smoke._runtime_context()`；后者在一次调用内完成：

```text
create database
→ Alembic base → head（当前 28 migrations）
→ start API
→ construct and warm embedding worker
→ for every session: Evidence → Proposal → Review
→ drain FTS/vector projections
→ start MCP host and recall
→ stop API
→ drop database
```

这条链适合作为少量真实冷启动 smoke，不适合规模化 context generation。当前一个 case 同时成为部署、
数据集、query 和清理单位，导致无法摊销任何稳定资源。

### 22.2.2 Projection 计算扩张

当前 projection 对每个 turn/chunk 建立向量，并为每对相邻 turn 再建立 window 向量，数量近似
`2n-1`。Worker 使用 Python list comprehension 逐 fragment 调用 ONNX；Repository 又逐 fragment
调用 projection procedure。Horizon 的 48,358 次 smoke embedding 与 622,905 次正式估计正是这一
实现的直接结果。

### 22.2.3 查询仍含冷成本

当前 `latency_ms` 包含 MCP 子进程启动、query embedding、PostgreSQL 检索、Canonical Gate、lazy
reranker 首次加载与推理、Context Compiler。API 每 case 重启使 reranker 无法跨 case 复用；因此字段名
虽然是 retrieval latency，却不是稳定运行后的 SQL latency，也不是纯 Agent 在线 p95。

### 22.2.4 并发合同没有落到 runner

`experiment-protocol.yaml` 允许最多两个独立 context process，并禁止进程内 case threading；这是因为
Migration target 和环境加载具有进程全局状态。当前 extended runner 没有 Slot/worker 参数，实际仍是
单进程顺序执行。直接加线程会造成环境、端口、数据库和 CPU oversubscription 风险。

### 22.2.5 观测维度不完整

底层 trace 已有 `ingest_ms`、`retrieval_ms` 和 `total_runtime_ms`，但 extended archive 主要只保留
`retrieval_ms`。数据库创建、Migration、API/MCP 启动、模型加载、治理写入、projection build 和 cleanup
没有统一 stage span，因而目前不能准确回答 10-case wall time 各阶段占比。

## 22.3 设计原则

1. **三种模式分离。** 冷启动真实性、快速质量评测和在线查询性能不得使用同一个模糊数字。
2. **只摊销真实可复用资源。** Migration、进程和模型按 run/slot 复用；history 只在内容精确相同时复用。
3. **治理语义不打折。** 快速路径仍产生 Evidence、Proposal、Decision、Claim/OpenIssue、Outbox 与 trace；
   禁止为 benchmark 直接 DML canonical 表。
4. **冻结候选与 harness 分离。** harness 优化可以改变 Evaluation Plane，但不得静默修改候选 wheel；
   Runtime 原生 batch 能力必须形成下一候选。
5. **冷、暖和摊销成本都报告。** cache/precompute 可以用于加速质量实验，但必须单列，不得冒充产品成本。
6. **并发有界且资源感知。** Slot 使用独立进程、数据库、端口和 blob root；并发数由实际吞吐而非线程数决定。
7. **先动态结果，后一次必要验收。** 开发阶段不为每个局部修改生成新 audit/receipt；以统一状态机、
   stage metrics 和等价性测试推进。

## 22.4 三种执行模式

| 模式 | 生命周期 | 主要用途 | 可以声明 | 禁止声明 |
| --- | --- | --- | --- | --- |
| `reference-faithful` | 每个选定 case 从空库执行完整 Migration、治理摄取、投影、MCP、清理 | 安装、迁移和完整链真实性 | cold E2E correctness/cost | 正式批量吞吐、warm SLA |
| `evaluation-fast` | 2 个常驻隔离 Slot；每个 history/cohort 摄取一次，执行多个问题 | paper context/quality 生成 | 等价性通过后的实验吞吐 | frozen product latency，除非使用原生候选路径 |
| `online-latency` | 数据和 projection 已就绪，API/MCP/模型已预热 | Agent 实际稳态调用 | warm MCP/query p50/p95/p99 | 建库、backfill 或恢复成本 |

`reference-faithful` 只需要固定少量代表案例；正式 paper denominator 使用 `evaluation-fast`。产品使用体验
主要看 `online-latency`，而系统部署与历史导入另行报告。

## 22.5 目标组件与状态机

```text
BenchmarkCoordinator
├─ RuntimeSlot-0
│  ├─ one migrated benchmark database
│  ├─ persistent API + Worker + MCP session
│  ├─ prewarmed embedding + reranker
│  └─ dedicated port / blob root / CPU budget
├─ RuntimeSlot-1
│  └─ same isolated ownership
├─ HistoryPlanner
│  └─ exact fingerprint → cohort → ordered questions
├─ StageRecorder
│  └─ bootstrap / ingest / projection / query / cleanup
└─ CheckpointWriter
   └─ write-once terminal records and bounded resume
```

每个 Slot 使用一个明确状态机：

```text
NEW
→ MIGRATED
→ READY_AND_WARM
→ EMPTY
→ LOADING_COHORT
→ INDEXED
→ QUERYING
→ DRAINING
→ RESETTING
→ EMPTY

任一未能验证的失败
→ QUARANTINED
→ recreate from trusted template
```

Coordinator 不能把 `QUARANTINED` Slot 重新分配给新 case，也不能把失败 case 从正式 denominator 删除。

## 22.6 四级生命周期

### Run 级：只做一次

```text
verify frozen wheel/install identity
→ create trusted pre-migrated template or migrate each Slot once
→ start at most two Slot processes
→ start API/Worker/MCP
→ warm embedding and reranker
→ record identities and resource limits
```

快速模式下 Migration/API/model/MCP 启动次数应与 Slot 数量成正比，而不是与 case 数量成正比。

### Cohort 级：每个唯一 history 一次

```text
validate empty isolated Slot
→ governed bulk/stream ingest
→ drain ordered Outbox
→ verify projection watermarks
→ freeze cohort snapshot
```

### Question 级：每个问题一次

```text
query embedding
→ FTS/vector
→ canonical resolution/gate
→ bounded reranker
→ Context Compiler
→ persistent MCP response
```

### Run 结束：一次

```text
flush checkpoints
→ stop MCP/API/Worker
→ verify no live connections
→ drop only explicitly marked benchmark databases
→ remove ephemeral blob roots
```

## 22.7 History fingerprint 与复用规则

历史复用不得只依赖 session ID。规范 fingerprint 至少绑定：

```text
ordered(session_id, observed_at, ordered(role, exact normalized content))
+ candidate_id
+ ingest/derivation policy identity
+ fragmenter/projection identity
+ embedding model/tokenizer/projection identity
+ scope/authority profile
```

只有 fingerprint 完全相同的 case 才共享一次 ingest/projection。BEAM 的 20-question shared history 应
直接使用该路径；Horizon/CUPID 必须先计算实际唯一 history 数，不能预设它们一定可复用。

对于“同一历史逐步增长”的 prefix case，可以在后续版本建立 prefix DAG，但只有同时满足以下条件才启用：

- session 前缀逐字节相同且时间单调；
- query 使用明确 `as_of`；
- 不存在同 ID 内容替换、分支或未来信息泄露；
- reference-faithful 对照证明结果一致。

否则回退到完整独立 cohort。

## 22.8 Slot 隔离与安全 reset

默认快速模式使用固定的临时 Slot database，在不同 cohort 之间执行 benchmark-only reset。reset 必须：

1. 验证数据库名使用专用随机前缀，并存在本 run 创建的 marker；
2. 停止新 query，等待在途请求归零，暂停 Worker；
3. drain 或明确丢弃当前 cohort 的已知 Outbox，不允许跨 cohort delivery；
4. 在受控事务中清理 tenant-owned canonical、projection、trace、idempotency 和 sequence 状态；
5. 清空对应 blob root，并验证表计数、watermark、连接与文件均回到 EMPTY 基线；
6. 任一步失败立即 quarantine，不尝试带病复用；从 trusted template 重建 Slot。

不得对 `.env` 中未验证的普通数据库执行 reset。将多个 cohort 永久放入同一数据库、仅依赖 project Scope
隔离属于备选方案，只有跨 Scope sentinel、MCP token/profile 和 Canonical Gate 负向测试全部通过后才能启用。

## 22.9 常驻 MCP、模型与连接

- 每个 Slot/profile 建立一个持久 MCP stdio session；`initialize/list_tools/status` 只在 session 启动时执行；
- 每个 question 只发送 `tools/call`，不得再次启动 Python 和 MCP server；
- MCP 断线最多执行一次身份一致的 reconnect；未确认请求结果时遵守原生 request ID/terminal 规则；
- API HTTP client 使用持久连接池和有界 timeout；
- embedding 与 reranker 在 Slot ready gate 中分别预热；
- 第一条真实 query 仍单独标为 `cold_after_ready`，随后才进入 warm 分布；
- warmup 失败不能放宽 FTS/canonical/authority gate，只能按既有规则 degraded 或 fail closed。

## 22.10 Embedding 批量、去重与缓存边界

### A. 当前 frozen candidate 可做的 harness 优化

- history/cohort 只摄取一次；
- API、Worker、ONNX session 和 MCP 常驻；
- 失败 resume 只导入身份完全相同的成功 terminal，不重复已完成 cohort。

### B. Evaluation-only 加速器

若正式质量实验不能承受 60 万次标量 ONNX 调用，可以在 paper freeze 前引入独立身份的批量预计算缓存；
相同 fragment 只在该 evaluation cache 内按 exact text hash 去重：

```text
cache_key = SHA256(
  candidate_id
  + fragmenter_source_sha256
  + embedding_model/tokenizer/projection identity
  + exact normalized fragment bytes
)
```

它只保存向量、维度、identity 和 hash，不保存未脱敏原文；公共/de-identified benchmark 与真实个人数据
使用不同 cache namespace。cache 的 cold build、warm hit 和节省调用数全部报告。该路径只用于质量/context
生成，不进入 frozen candidate 产品延迟结果。

### C. 下一 Runtime candidate 的正式能力

```text
EmbeddingProvider.embed_many(texts, batch_size)
→ Worker bounded lease batch
→ exact fragment dedupe
→ one/few ONNX batch inference calls
→ batch projection procedure
→ per-Outbox completion/watermark/error attribution
```

删除、purge 和权限失效事件继续高于普通 embedding 优先级。同 aggregate 保序、dead-letter gap、幂等、
revoke 和 projection version 语义不得因 batch 改变。

## 22.11 计时与成本口径

每个 run、Slot、cohort、question 都必须有不含正文的 stage record：

```text
db_create_or_clone_ms
migration_ms
api_start_ms / worker_start_ms / mcp_start_ms
embedding_load_ms / embedding_warm_ms
reranker_load_ms / reranker_warm_ms

evidence_ms / proposal_ms / review_ms
fts_projection_ms / vector_projection_ms
embedding_items / embedding_batches / embedding_cache_hits
projection_write_ms / outbox_drain_ms

mcp_transport_ms
query_embedding_ms
fts_ms / vector_ms / fusion_ms
canonical_gate_ms / reranker_ms / context_compile_ms
query_total_ms

reset_ms / cleanup_ms
answer_ms / judge_ms
```

统一公式：

```text
T_run_total
= T_run_setup
 + Σ T_unique_history_build
 + Σ T_question_query
 + Σ T_answer
 + Σ T_judge
 + T_cleanup

T_amortized_per_question = T_run_total / terminal_question_count
```

报告至少分为：

```text
Cold deployment cost
Cold history build cost
Warm online query p50/p95/p99
Amortized end-to-end cost per question
Throughput by Slot count
```

BM25、dense、Mem0/Hindsight/Graphiti/ReMe 同样分离 build/query；若某方法只报告 in-memory query，MiLAi
表中也应提供对应 warm query，而不是用 full deployment 与之直接比较。

## 22.12 并发与 CPU 调度

保持协议的安全边界：

```text
max Slot processes = 2
workers per process = 1
in-process case threading = prohibited
```

两个 Slot 各自拥有环境、数据库、端口和 blob root。由于 ONNX embedding 可能已经使用多个 CPU 线程，
必须冻结并记录每个 Slot 的 CPU affinity、OMP/ORT 线程数、DB pool 和 reranker semaphore；先比较 Slot=1
与 Slot=2 的吞吐、p95 和 CPU 使用率。若双 Slot 因 oversubscription 变慢，正式计划回退为 1，而不是为了
满足配置强行并发。

Coordinator 可把一个 Slot 用于 cohort build、另一个用于 query，但必须通过全局 embedding/reranker
资源 semaphore 防止两个重任务同时压满 CPU。

## 22.13 快速路径等价性门

在正式 paper inputs 打开前，对固定、无标签的 smoke cases 同时运行旧 `reference-faithful` 与新
`evaluation-fast`，阻断条件如下：

| 检查 | 要求 |
| --- | --- |
| Canonical | Evidence/Proposal/Decision/Claim/OpenIssue 数量、identity、lineage 相同 |
| Projection | fragment kind/order/text hash 相同；向量在冻结 tolerance 内相同 |
| Watermark | 无 gap、无跨 cohort event、最终位置相同 |
| Retrieval | Top-K source ID、顺序、matched_by 与 canonical reject 相同 |
| Context | rendered context hash、token 数、omitted IDs 相同 |
| MCP | typed status、degraded/abstention 和 trace 引用相同 |
| Safety | OpenIssue、revoke、stale index、wrong scope sentinel 行为相同 |
| Accounting | answer/judge/provider 调用、失败 denominator 与 retry identity 相同 |
| Isolation | 上一 cohort 的 ID、bytes、projection 和 cache 不可被下一 cohort观察 |

任一项不一致时，快速路径只能用于诊断，不能进入正式 paper run。不能因快速路径答案更好而接受不等价。

## 22.14 实施工作包

| ID | 实际代码能力 | 动态退出条件 |
| --- | --- | --- |
| `BHE-00` | StageRecorder 与当前 runner 全阶段计时 | PE08 10-case 能解释 ≥95% wall time，answer/judge 仍为 0 |
| `BHE-01` | 从 Memora/BEAM `_CohortRuntime` 抽取统一 `BenchmarkRuntimeSlot` | CUPID、Horizon、BEAM 使用同一 Slot contract |
| `BHE-02` | 预迁移双 Slot、常驻 API/Worker/MCP、reranker prewarm、安全 reset | 快速模式中 migration/start/model load 次数不超过 Slot 数 |
| `BHE-03` | exact history fingerprint、cohort planner、一次 ingest 多 query | 摄取次数等于 unique history 数；BEAM 20-question cohort 只建一次 |
| `BHE-04` | 两进程调度、CPU/semaphore、checkpoint/quarantine | Slot=1/2 都完成，同身份、无交叉污染；选择实测更优配置 |
| `BHE-05` | evaluation-only batch/cache 原型及等价性 | 参考 smoke 的 projection、Top-K、context 通过 §22.13 |
| `BHE-06` | 下一 Runtime 的 `embed_many` 与 batch projection | 真实 PostgreSQL rollback/idempotency/order/revoke 测试通过 |
| `BHE-07` | 新旧 runner A/B 与资源重估 | Horizon/CUPID/BEAM smoke 完整、无标签、无隐藏 provider call |
| `BHE-08` | 冻结唯一 paper harness identity 与协议 | 只在全部前置门通过后允许正式 paper evaluation |

执行顺序固定为：

```text
BHE-00 → BHE-01 → BHE-02 → BHE-03 → BHE-04
→ BHE-05（需要时）
→ BHE-07 → BHE-08

BHE-06 是产品候选工作，可与 paper harness 分开，不阻塞纯质量实验的等价加速。
```

开发期默认不调用 AI review；只有出现 canonical/security 边界冲突或 `BHE-08` 最终验收时，才允许一次
必要 review。每个失败只保留一个结构化 terminal，不再为同一失败衍生多层 candidate/receipt 文档。

## 22.15 验收目标

正确性硬门：

- §22.13 所有等价性检查 100% 通过；
- cross-cohort/cross-scope 泄露为 0；
- Evidence/Proposal/Decision 与 Canonical Gate 未被绕过；
- answer、judge、hidden provider call 与预注册 denominator 完全一致；
- frozen DG11 candidate inventory 不改变。

复杂度硬门：

```text
fast migration count       = O(slot_count)
API/MCP/model startup      = O(slot_count)
history build count        = O(unique_history_count)
query count                = O(question_count)
embedding batch calls      = O(unique_fragments / batch_size)  # BHE-05/06 enabled
```

初始工程目标而非产品 SLA：

- `BHE-02～05` 完成后，Horizon 10-case smoke wall time 相对当前 faithful runner 至少降低 5 倍；
- 同时分别报告“只做基础设施复用”和“加入 batch/cache”各自收益，不能把收益全部归给检索算法；
- warm query 独立形成 p50/p95/p99，后续再依据真实目标设备冻结 SLA；
- 若未达到 5 倍，依据 stage profile 继续优化最高占比阶段，不启动论文正式 run，也不启动额外审计。

## 22.16 当前执行决定

当前不应继续重复运行完整 Horizon formal，也不应先改 reranker/召回质量参数。下一步应是：

```text
1. BHE-00 补齐阶段计时；
2. BHE-01/02 建立统一常驻 RuntimeSlot；
3. BHE-03 复用 exact history；
4. 用现有 PE08 smoke 做新旧等价与 wall-time A/B；
5. 若 embedding 仍占主导，再实施 BHE-05/06 batch 路径；
6. 重新估算 635,321 个逻辑 embedding item 的实际 batch 数和总时长；
7. 只冻结一个最终 paper harness，再开始正式 benchmark。
```

现有 PE08 smoke 作为历史 functional reference 保留，不覆盖、不包装成新的产品性能结论。此次设计更新
不会修改 `current-state.json`、candidate wheel、Schema、API、权限、删除或 canonical 行为；Schema 继续是
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
