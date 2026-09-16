# MiLAi DG-13：MiLA vNext MCP-native Governed Agent Memory Runtime Goal

> Goal ID：`DG-13`
> 文档版本：`1.7.1 SCOPED RELEASE / INDEPENDENT REVIEW PASS`
> 生效日期：`2026-08-26`（Asia/Shanghai）
> 当前状态：`M0–M6 GATE PASS / R1 OPERATOR CLOSURE PASS / R2 REGRESSION-SECRET-CONTRACT PASS / INDEPENDENT RELEASE REVIEW PASS / SCOPED LABEL EARNED`
> 第一产品边界：`MCP`
> 首要客户端：`OpenWorker`
> Runtime / Schema：`0.1.x CANDIDATE / 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`
> 数据边界：`SYNTHETIC / PUBLIC DEVELOPMENT / INDEPENDENTLY DE-IDENTIFIED ONLY`
> Provider：仅用于 Agent answer-path 验证的本地 `vLLM`；不是 MiLA Memory Core 依赖
> 本文性质：校正 MiLA 与 Host 的架构 ownership，并记录 DG-13 实施 Gate 与证据；不修改 DG-12 frozen candidate 或 `architecture/v1.0/`

---

# 0. Goal 决定

## 0.1 产品定义

DG-13 以以下产品定位为最高优先级：

> **MiLA 是一个 MCP 原生、Query 可达、Evidence-first、Versioned-state、Governed-write 的 Agent Memory Runtime；它能够在没有完整 TaskIdentity 的情况下，正确解析当前或历史 Memory State，并以有界成本向 Agent 返回可追溯的最小 Context。**

英文产品定义：

> **MiLA is an MCP-native, query-reachable, evidence-first, versioned-state, governed-write Agent Memory Runtime. It resolves current or historical memory state without requiring complete task identity and returns compact, provenance-grounded context at bounded cost.**

MiLA 不是：

```text
Agent Runtime
OpenWorker Task Controller
Provider Gateway
Agent 工作流状态机
完整 Task/Goal/Tool orchestration framework
```

MiLA 负责：

```text
Memory ingest and persistence
Evidence provenance
Governed update and conflict handling
Canonical current/historical state resolution
Exact and bounded retrieval
Canonical Gate
Memory explanation and lineage
Revocation / deletion / forgetting propagation
Minimal provenance-grounded Context
Memory query interpretation
Memory access planning and state addressing
MemoryStateView resolution
Memory access capability and policy
```

产品主张压缩为：

```text
MiLA is Memory, not Agent Runtime.
MCP is the first product boundary, not an incidental adapter.
Query is sufficient to enter Memory retrieval.
Task improves precision and efficiency; it does not decide whether Memory exists.
StateView is a derived read model, not a second truth store.
```

## 0.2 唯一产品主链

```text
Any authorized MCP Client
→ MiLA MCP Facade
→ MiLA Memory Application Kernel
→ Canonical Core / Projection Plane
→ MemoryStateView / minimal Context / typed abstention
```

OpenWorker 的位置是：

```text
OpenWorker = first-party MCP client and conformance target
```

而不是：

```text
OpenWorker Task/Need state = MiLA Memory Core
```

## 0.3 两个控制平面

DG-13 正式冻结 Agent Control Plane 与 Memory Control Plane 的 ownership：

| Control plane | Owner | 负责 | 不负责 |
| --- | --- | --- | --- |
| Agent Control Plane | OpenWorker、Codex、Claude、LangGraph、其他 Host | Agent planning、execution task、tool orchestration、provider invocation、workflow | Canonical Memory truth、Memory query planning、StateView resolution |
| Memory Control Plane | MiLA | query interpretation、state addressing、current/historical resolution、retrieval planning、evidence sufficiency、Context construction、governed update | Provider 调用、Host workflow、完整 Agent Task runtime |

Ownership 校正：

```text
CURRENT:
Host Task/Need can prevent an otherwise valid Memory query from reaching Runtime.

TARGET:
MiLA Query Interpreter owns Memory reachability.
Host TaskContext is an optional scope/ranking/reuse hint.
```

## 0.4 本 Goal 的成功条件

DG-13 首先证明：

1. 普通 MCP Client 不提供 Task identity 也能正确读取 Memory；
2. 受权 MCP Client 能完成 Evidence → Proposal → Review → Canonical update 的治理生命周期；
3. Memory 在 client/session/MCP process 重启后仍由持久 Runtime 恢复；
4. current、historical、conflict、revoked 和 absent 状态具有稳定 typed semantics；
5. Query interpretation、AccessPlan、StateView 和渐进检索由 MiLA Runtime 拥有；
6. Exact 路径不进入 FTS/vector/reranker，Search 路径有界升级；
7. OpenWorker 使用同一 MCP Memory contract 完成真实对话，不建立第二套 memory semantics；
8. 常规开发以可运行行为、正确性和延迟为主，不再以重复审计、receipt 数量或防御性 wrapper 数量代替产品进展。

---

# 1. 规范关系与文档处置

## 1.1 规范优先级

出现冲突时按以下顺序处理：

1. [`architecture/v1.0/`](./architecture/v1.0/) frozen Logical Architecture；
2. [`MiLAi_Logical_Architecture_v1_设计文档.md`](./MiLAi_Logical_Architecture_v1_设计文档.md) 的 frozen MUST；
3. [`MiLAi_Lean_V1_实施合同.md`](./MiLAi_Lean_V1_实施合同.md)；
4. 本 Goal；
5. 其他 DG-13 产品、研究、formal-integrity 文档；
6. 实验性实现、runner、测试和注释。

本文不改变以下 frozen invariant：

```text
Evidence != accepted belief
Proposal != canonical state
ClaimVersion append-only
ClaimHead exact-head CAS
OpenIssue cannot be summarized away
Projection result is candidate only
Canonical Gate precedes applicable Context
Revoke fails closed before asynchronous purge
Agent/MCP/model has no direct canonical write authority
```

## 1.2 DG-13 文档关系

| 文档 | 新状态 | 保留用途 |
| --- | --- | --- |
| 本文 | `ACTIVE PRODUCT GOAL` | DG-13 唯一产品状态板与开发顺序 |
| [`MiLAi_DG-13_MemoryAccessPlan与渐进检索_GOALS.md`](./MiLAi_DG-13_MemoryAccessPlan与渐进检索_GOALS.md) | `SUPERSEDED AS ACTIVE PRODUCT GOAL` | 保留 Host-prefetch、CACHE fallback、效率诊断历史 |
| [`MiLAi_DG-13U_OpenWorker_MCP可用性开发_GOAL.md`](./MiLAi_DG-13U_OpenWorker_MCP可用性开发_GOAL.md) | `RECLASSIFIED: OPENWORKER CLIENT INTEGRATION LANE` | 保留真实 composition、fault、provider 和 cleanup 测试资产 |
| [`MiLAi_DG-13_Research_and_Benchmark_Plan.md`](./MiLAi_DG-13_Research_and_Benchmark_Plan.md) | `SEPARATE / PARKED UNTIL PRODUCT MILESTONE` | 外部项目、benchmark、消融、研究候选 |
| [`MiLAi_DG-13_Formal_Evaluation_Integrity.md`](./MiLAi_DG-13_Formal_Evaluation_Integrity.md) | `SEPARATE GOVERNANCE LANE` | 正式 label/holdout/论文完整性；不阻断 synthetic 产品开发 |
| [`MiLAi_DG-12高效Benchmark与论文实验_GOALS.md`](./MiLAi_DG-12高效Benchmark与论文实验_GOALS.md) | `FROZEN PREDECESSOR STATE` | 保留性能事实、失败结果和正式实验状态；不得由 DG-13 改写 |

旧文档和 artifacts 不删除、不覆盖。它们不能继续把 Host Task planner 写成 MiLA 产品本体，也不能自动晋级本文状态。

## 1.3 ADR-024 处置

[`ADR-024 Host-native Memory Control Plane`](./docs/adr/ADR-024-host-native-memory-control-plane.md) 当前仍是 `PROPOSED / NOT IMPLEMENTED`。本 Goal 对其作如下产品处置：

```text
REJECTED AS MiLA CORE POSITIONING
RETAINED AS OPTIONAL OPENWORKER/HOST INTEGRATION DESIGN MATERIAL
```

具体含义：

- Host 在 provider 前主动 recall 可以保留；
- Need/Availability 分离和 same-call fallback 可以保留；
- Host Task registry、portable lease、Direct/HTTP parity 不再是 MiLA Core 前置；
- MCP 不再被描述为可有可无的 transport；
- 如需正式修改 ADR 状态或 frozen architecture，另行更新 ADR/crosswalk，不在本文静默完成。

## 1.4 事实标签

本文使用：

```text
CURRENT       executable code / tests / artifacts 直接支持
TARGET        本 Goal 要实现的状态
GAP           CURRENT 与 TARGET 的差异
[INFERENCE]   多项迹象支持但没有明确 contract
[UNKNOWN]     当前 repository 无法确认
```

---

# 2. CURRENT IMPLEMENTATION 与开发状态

## 2.1 当前真实产品形态

```text
MCP Client
  ↓ stdio / profile-scoped local capability
integrations/mcp::milai_mcp.server
  ↓ typed Python client / loopback Runtime API
runtime/src/milai
  ├─ Evidence Service
  ├─ Proposal / Canonical Service
  ├─ Retrieval / QueryPlan
  ├─ EffectiveClaimState / Canonical Gate
  ├─ Context compiler
  ├─ Revocation / deletion
  └─ Trace / capability endpoints
  ↓
PostgreSQL Canonical Core + CAS blob + derived FTS/vector projections
```

OpenWorker 当前另有一条专用集成链：

```text
OpenWorker/OpenCode
→ Host provider adapter
→ hidden milai_prepare_context
→ broker/MCP child
→ Runtime
→ Context injection
→ local vLLM
```

后者是客户端集成，不是 MiLA Core 的唯一入口。

## 2.2 当前 MCP 工具面

CURRENT [`integrations/mcp/src/milai_mcp/server.py`](./integrations/mcp/src/milai_mcp/server.py) 按 profile 暴露：

| Profile | CURRENT public tools | 结论 |
| --- | --- | --- |
| `reader-lite` | `milai_recall`、`milai_memory_resolve` | query-first；可选 opaque `previous_context_id`；不要求 Task |
| `reader` | `milai_status`、`milai_recall`、`milai_claim_get`、`milai_open_issues_list`、`milai_trace_get`、`milai_evidence_metadata_get` | 读取、能力和解释 precursor |
| `submitter` | reader tools + `milai_evidence_capture`、`milai_proposal_create` | Evidence 与 Proposal 已分离；不会直接 commit Claim |
| `operator` | reader tools + `milai_evidence_revoke`、`milai_deletion_status_get` | revoke 后 canonical read fail closed、purge 异步 |
| `reviewer` | reader detail tools + `milai_proposals_list`、`milai_proposal_get`、`milai_memory_review` | 独立 actor 与最小 read/review capability；不进入普通模型 catalog |

`milai_prepare_context` 当前被注册为 Host-only hidden operation，参数要求 `active_goal/session_id/agent_id/task_epoch/event` 等 Host 状态。它不是普通 MCP Client 使用 Memory 的前置条件。

## 2.3 当前代码 ownership

| 责任 | CURRENT owner | 关键实现 |
| --- | --- | --- |
| MCP tool catalog/profile | MCP package | `integrations/mcp/src/milai_mcp/server.py::build_server()` |
| Typed public Runtime client | Python Client | `integrations/python-client/src/milai_client/client.py::MilaiClient` |
| Framework-neutral tools | Python Client | `integrations/python-client/src/milai_client/tools.py::create_milai_tools()` |
| Evidence ingest/revoke | Runtime application | `runtime/src/milai/application/evidence.py::EvidenceService` |
| Proposal/review/Claim | Runtime application | `runtime/src/milai/application/proposals.py::ProposalService` |
| Query planning | Runtime application | `runtime/src/milai/application/query_planner.py` |
| Retrieval operators | Runtime application | `runtime/src/milai/application/query_operators.py` |
| Context compile | Runtime application | `runtime/src/milai/application/context.py` |
| Host task state | Python Client/OpenWorker integration | `task_state.py`、`task_memory.py`、`task_binding.py` |
| OpenWorker prefetch | OpenWorker integration | `host_adapter.py::OpenWorkerProviderAdapter.complete()` |
| Hidden composite Runtime route | Runtime application | `context_preparation.py::PrepareContextService.prepare()` |

Runtime migration 中没有把 OpenWorker Task、parent/child relation 或 TaskMemoryBinding 建成 canonical Memory 表。`TaskMemoryState` 代码还显式要求它是 Host-owned object。因此 Task 不能被提升为 Memory Core 必需 state。

## 2.4 截至 2026-08-26 的开发事实

| 事实 | CURRENT 状态 | 证据 |
| --- | --- | --- |
| DG13U owning tests | `PASS`，1093 tests，3 commands，0 retry | `var/dg13/test-gates/dg13u-u1-test-gate-20260826g/receipt.json` |
| DG13U contracted matrix | 37 cases 已实现 | single-case reports / matrix source |
| 最新完整 serial aggregate | `FAIL`，18 attempted、17 PASS，停于 `U1-BROKER-DOWN` | `var/dg13/aggregates/dg13u-u1-20260826g.json` |
| Broker-down 单项修复复测 | `PASS` | `var/dg13/runs/u1-broker-down-fix-20260826a/report.json` |
| 修复后的 37-case aggregate | `NOT RUN` | 没有更新 aggregate artifact |
| 受治理写入→真实 OpenWorker→MCP→vLLM 单轮回答 | `PASS` | `var/dg13/runs/codex-real-write-chat-20260826a/report.json` |
| 同一 OpenCode session 连续两轮 | 两次 `FAIL` | `codex-real-chat-continue-20260826a/b` |
| 连续两轮失败边界 | first-turn memory/provider 成功；runner question hash 绑定失败；second turn 未执行 | Host trace + `_smoke_task_scenario()` |
| 独立 review lane | 实现 precursor 已存在；完整 release review 未完成 | recent code / no final accepted bundle |
| DG13U release | `NOT EARNED` | aggregate 未 PASS，review 未完成 |

这些事实不能被解释为“MiLA 无法多轮记忆”。现有多轮失败发生在 OpenWorker observation/test binding，并未执行第二次 MCP recall。

## 2.5 当前最高可信结论

```text
Canonical Memory Core                         IMPLEMENTED / CANDIDATE
Public MCP query-only recall                  IMPLEMENTED / CONTRACT TESTED
MCP Evidence capture + Proposal               IMPLEMENTED / CONTRACT TESTED
MCP operator revoke                           IMPLEMENTED / CONTRACT TESTED
MCP Steward review                            IMPLEMENTED / M5 GATE PASS
Task-free generic MCP product E2E             PASS / M1-M6 FRESH DATABASE
Governed write → single-turn OpenWorker recall PASS
OpenWorker same-session continuation           PASS / M1 REAL + M3 CONFORMANCE
General MCP Memory Service release             NOT EARNED
```

---

# 3. 当前问题的重新诊断

## 3.1 P0：产品边界被 Host 逻辑遮蔽

原 DG-13 把：

```text
Task → Need → AccessPlan → Lease → Provider
```

放在产品中心，导致“OpenWorker task continuity 是否通过”被错误等同于“MiLA memory 是否可用”。

正确分层为：

```text
MiLA Core:
  principal + query + scope + time + consistency + budget
  → Memory resolution

Optional client hints:
  task_id + goal + workspace + artifact + known StateKey
  → improve scope/ranking/reuse only
```

## 3.2 P0：核心 MCP lifecycle 尚未形成一个简短产品证明

当前已经有大量组件、fault、manifest 和 OpenWorker runner，但仍缺少一条优先级最高、普通用户可理解的 smoke：

```text
start Runtime + MCP
→ generic client tools/list
→ task-free recall
→ capture Evidence
→ create Proposal
→ authorized review
→ recall current state
→ restart MCP client/server
→ recall same persisted state
→ revoke/forget
→ recall fails closed
```

## 3.3 P1：公共读取结果还不是统一的 MemoryStateView

CURRENT `milai_recall` 已返回 status、items、OpenIssue、trace、consistency 和 canonical position，但 claim、issue、provenance、currentness 和 typed absence 仍分散在多个工具/结果字段中。

TARGET 不建立新的 StateView 数据库，而是形成 query-time `MemoryStateView` read model。

## 3.4 P1：精确 StateKey 寻址仍不够直接

CURRENT 已有 `milai_claim_get(claim_id)`、L0 current state 和 StateKey precursor，但普通 MCP Client 已知 subject/predicate/type 时仍缺少稳定公共 exact-state contract。

DG-12 事实表明 `StateAddressabilityRate=0.916667`，因此首先应打通地址，而不是先换 embedding 或构建 graph。

## 3.5 P1：效率瓶颈分属三条链

必须分别处理：

```text
MCP online access
Deep search
Cold/incremental materialization
```

已知 development evidence：

- 单轮真实 OpenWorker exact 中，Runtime 约 `53 ms`，memory control 约 `1297 ms`；`[INFERENCE]` 二者之间的未解释残差位于 Host/MCP/broker/IPC/serialization 组合，但现有 artifact 尚不足以把残差归因给某一 stage，M0 必须实测；
- warm deep 10-case 中 `recent_canonical + reranker + FTS` 约占 Runtime query `97.9%`；
- governed history build `842.921 s`，占对应 first phase `92.376%`；
- vector 与 query embedding 在该 warm block 仅约 `0.9% / 0.6%`。

因此当前优化顺序是：

```text
query reachability + one-call trace
→ eliminate any M0-proven per-turn startup/connection churn
→ canonical exact address
→ scoped temporal/FTS candidate reduction
→ conditional reranker
→ incremental projection materialization
→ vector/model replacement only with new profile evidence
```

## 3.6 P1：防御性编程和审计资产已经超过日常开发需要

CURRENT DG13U 为 release integrity 构建了大量 hash、receipt、reconciliation、source inventory、case manifest 和 review bundle。这些资产对一次受控 release 有价值，但不应成为每个小修复的默认前置或产品核心复杂度。

必须区分：

```text
Product trace
  = Memory 结果为何成立；必须保留

Security boundary
  = principal/profile/scope/authority/revoke；必须保留

Development audit ceremony
  = 重复 manifest、全树 hash、每 patch 独立 review；默认减少
```

## 3.7 相关 Memory 设计的采用边界

外部项目是机制输入与 benchmark baseline，不是 MiLA Runtime dependency。详细证据和 transplant 计划由 [`MiLAi_DG-13_Research_and_Benchmark_Plan.md`](./MiLAi_DG-13_Research_and_Benchmark_Plan.md) 管理；本 Goal 只冻结 ownership：

| 机制来源 | DG-13 吸收 | DG-13 不吸收 |
| --- | --- | --- |
| MemoryOS / EverMemOS | storage-update-retrieval-generation 分层；episode/semantic/recollection 可作派生 view | 自动 consolidation 直接写 canonical truth |
| True Memory | raw Evidence 保留；抽取/summary 不能替代 source | 仅靠 raw event search 代替版本、权限、冲突治理 |
| LongMemEval / SelRoute / SwiftMem | indexing/retrieval/reading 分层诊断；query-type routing；先缩小 candidate universe | 每个 query 固定跑统一 hybrid pipeline |
| DimMem / Chronos / TSM | type/entity/time/reason/purpose 显式维度；valid/system time 分离 | 一开始构造全局 graph/event KB |
| Zep / TOKI / GEM | provenance、双时间、版本轨迹、冲突与 state trajectory correctness | graph 或 LLM judge 获得 canonical authority |
| OBLIVION / RF-Mem | read/write 分离；easy fast path；不确定时升级 | embedding entropy 单独决定 authority/currentness |
| MRAgent / HippoRAG / TA-Mem | 困难 multi-hop 的 bounded reconstructive candidate | 默认所有 query 进入 agentic reconstruction |
| OpenViking / Hindsight / Graphiti / Mem0 / Memo 类本地项目 | projection、candidate producer、baseline、可替换 adapter | production backend 直接成为 MiLA truth store |

所有 transplant 必须满足：

```text
external output
→ candidate/projection only
→ Canonical Gate
→ Evidence Sufficiency
→ Context
```

M0–M3 不引入新的 Memory Engine。只有 M7 的 matched experiment 证明具体机制对稳定 failure slice 有收益，才进入后续产品 Goal。

---

# 4. TARGET 产品架构

## 4.1 总体架构

```text
┌─────────────────────────────────────────────────────────┐
│ Agent / Host                                            │
│ OpenWorker · Codex · Claude · LangGraph · Custom        │
└───────────────────────────┬─────────────────────────────┘
                            │ MCP
                            ▼
┌─────────────────────────────────────────────────────────┐
│ 1. MCP Facade                                           │
│ authenticated principal · capability/scope · schemas    │
│ typed result/error · structured content · resource link │
└───────────────────────────┬─────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────┐
│ 2. Memory Application Kernel                            │
│ Query Interpreter · MemoryAccessPlanner                 │
│ StateAddressService · MemoryStateViewService            │
│ ProgressiveRetrieval · CanonicalGate                    │
│ EvidenceSufficiency · ContextCompiler                   │
└───────────────┬───────────────────────┬─────────────────┘
                │                       │
                ▼                       ▼
┌───────────────────────────┐  ┌──────────────────────────┐
│ 3. Canonical Core         │  │ 4. Projection Plane      │
│ EvidenceRecord + CAS      │  │ Optional address locator │
│ Claim / ClaimVersion      │  │ Alias / Entity postings  │
│ ClaimHead / OpenIssue     │  │ Temporal / FTS / vector  │
│ Grounding / Proposal      │  │ Optional graph / summary │
│ StewardDecision / Outbox  │  │ projection watermark     │
└───────────────┬───────────┘  └─────────────┬────────────┘
                └──────────────┬──────────────┘
                               ▼
┌─────────────────────────────────────────────────────────┐
│ 5. Context and Audit                                    │
│ MemoryStateView · ContextCapsule · ContextPointer       │
│ ContextReceipt/AccessTrace wire views · RetrievalTrace  │
└─────────────────────────────────────────────────────────┘
```

MCP 是外部产品协议边界。它不要求同机内部组件重复穿越：

```text
MCP process
→ one application-kernel invocation
→ persistent DB/client pool
```

TARGET 禁止把正常 recall 实现成每次都重建的：

```text
MCP process
→ broker
→ child process
→ loopback HTTP
→ Runtime
```

M0 先确认是否存在 per-call process/client 启动；若确认，M1 消除该 churn 并复用连接。只有 matched profile 证明模块抽取收益明确时，才把现有 Runtime application services 收敛为真正的 in-process kernel。Direct Python/HTTP 仍可作为内部诊断接口，但不是 DG-13 外部等价产品面，也不要求三 transport parity。

## 4.2 六类核心 Memory State

| 类别 | 核心对象 | Authority | 生命周期 |
| --- | --- | --- | --- |
| Evidence State | EvidenceRecord、ContentBlob、provenance、permission、retention、revoke | observation only | durable |
| Canonical State | Claim、ClaimVersion、ClaimHead、Grounding | authoritative governed state | durable/versioned |
| Epistemic State | OpenIssue、challenge branches、grounding status | governed uncertainty/conflict state | durable/versioned |
| Derived View State | profile、summary、procedure view | non-authoritative derived read state | rebuildable |
| Context State | MemoryStateView、ContextCapsule、ContextPointer | query-time derived / existing durable capsule | bounded/TTL/invalidation |
| Projection State | optional address locator、alias/entity、FTS、temporal、vector、graph candidate | non-authoritative candidate index | rebuildable |

Task、goal、provider messages、tool loop 和 workflow node 不自动属于这六类 Memory state。需要长期记住的 task status、goal decision 或 workflow fact，应作为普通 typed Canonical Claim 写入，而不是复制 Host Task registry。

同一 Canonical Core 可使用 `memory_kind` 区分内容，不建立六套 authoritative store：

```text
EPISODIC_EVENT
CURRENT_STATE
PREFERENCE_PROFILE
PROCEDURE_WORKFLOW
ENVIRONMENT_GOTCHA
RESOURCE_ARTIFACT
AGENT_DECISION_OUTCOME
```

这些 kind 在 M2 Schema/contract 评审前仅为 TARGET vocabulary；不得在 Goal 文档中假定现有表已经具有这些字段。

强制关系：

```text
Projection State != Canonical State
Context State    != Canonical State
Derived View     != independent truth store
```

## 4.3 MemoryStateView

`MemoryStateViewService` 是一次 MCP query 的动态 read model，不是新表或第二 truth store。它解析：

```text
ClaimHead
+ ClaimVersion
+ valid-time / system-time
+ ScopePredicate
+ permission / retention / revoke
+ Grounding
+ OpenIssue
────────────────────────────────
MemoryStateView
```

目标请求语义：

```yaml
MemoryStateViewRequest:
  query: "当前 DG13 进行到哪里？"
  targets:
    state_keys: []
    claim_ids: []
    entities: []
  temporal:
    valid_at: null
    known_at: null
    range: null
  required_freshness: CURRENT
  consistency_mode: CANONICAL_REQUIRED
  authority_floor: INFORMATIONAL
  budget:
    max_items: 12
    max_context_tokens: 2500
    max_latency_ms: 500
  hints:
    task_id: null
    project_id: "MiLA"
    artifacts: []
    previous_context_id: null
```

`principal`、tenant 和可读 scope 必须由 MCP authentication context、固定 profile 或受信 deployment policy 导出；普通 tool arguments 不能自报 principal 后取得权限。

目标结果语义：

```yaml
MemoryStateView:
  status: RESOLVED | PARTIAL | CONTESTED | ABSENT | DENIED | UNAVAILABLE
  states:
    - state_key: {}
      value: {}
      claim_id: ""
      version_id: ""
      valid_time: {}
      system_time: ""
      scope: {}
      authority: ""
      freshness: ""
      epistemic_status: ""
      evidence_refs: []
      open_issue_ids: []
  dependencies:
    claim_versions: []
    issue_revisions: []
    policy_epoch: ""
    canonical_position: 0
  resolution_trace: {}
```

M0 可以先把现有 `RecallEnvelope` 映射到该语义，不要求立即新增同名 public class 或数据库对象。

“当前 State”不是最后写入的一行。一个 state 只有同时满足以下条件，才可以作为 CURRENT 返回：

```text
StateKey matches
AND scope matches
AND valid-time is currently applicable
AND system-time is visible at the requested position
AND principal is authorized
AND Evidence/Claim is not revoked or superseded for this read
AND unresolved OpenIssue is exposed or blocks certainty as policy requires
```

## 4.4 Task 是可选 hint

主读取请求只要求：

```text
authenticated principal/profile
query or exact address
scope policy
consistency
budget
```

可选 hint：

```text
task_id
goal
workspace/artifact
known StateKey / Claim ID
temporal/entity hints
```

强制 invariant：

```text
Task omitted
→ task-bound Context reuse prohibited
→ exact/search retrieval still runs
```

```text
Task unknown
≠ MemoryRequirement.NONE
≠ memory unavailable
```

还必须区分两种 Task：

```text
Agent Execution Task
  owner = Host
  examples = invocation, plan node, workspace, tool lineage
  role in MiLA = optional hint only

Remembered Task State
  owner = MiLA Canonical Core after governed commit
  examples = DG13.status=M1_ACTIVE, work_package=M2_COMPLETE
  representation = ordinary versioned Claim
```

最终原则：

> **执行 Task 在 Host；需要长期记住的 Task 状态在 Canonical Memory。**

## 4.5 Query-first、Task-enhanced 读取链

```text
MCP milai_memory_resolve(query, optional hints)
→ Authenticated Principal / Policy Gate
→ QueryMemoryIntent
    ├─ NOT_NEEDED
    ├─ POSSIBLE
    └─ REQUIRED
→ MemoryAccessPlanner
    ├─ EXACT
    ├─ BOUNDED_PROBE
    ├─ SEARCH
    └─ RECONSTRUCT
→ Candidate Generation
→ Canonical Gate
→ query-specific Evidence Sufficiency
→ MemoryStateView
→ minimal ContextCapsule / typed outcome
```

`NOT_NEEDED` 只有在 Query Interpreter 明确判断当前请求不需要长期 Memory 时成立。Task 缺失、Host Need 未命中、projection 不可用、MCP adapter 出错都不能生成 `NOT_NEEDED`。

调用来源必须提供 requirement floor：

```text
EXPLICIT_READ
  public Agent-visible milai_memory_resolve default
  floor = POSSIBLE
  may return ABSENT/ABSTAINED, never NOT_NEEDED

PREFETCH_AUTO
  authenticated Host integration mode
  floor = NONE
  Query Interpreter may return NOT_NEEDED
```

`invocation_mode` 只影响最低访问工作量，不授予 scope、authority、write 或 review capability。普通 client 不能通过把自己标记为 Host 来扩大权限；MCP profile/credential 决定是否允许 `PREFETCH_AUTO`。

`POSSIBLE` 不直接触发完整 L1，而执行有界 probe：

```text
StateKey alias
Entity postings
Temporal range
small FTS top-k
recent episode references within authorized scope
```

probe 无有效信号才停止；有强信号才升级 SEARCH。

| Query type | 第一访问路径 | 典型升级条件 |
| --- | --- | --- |
| 当前项目、偏好、配置状态 | exact StateKey / ClaimHead | 地址缺失、scope ambiguous、OpenIssue |
| 历史状态 | bitemporal ClaimVersion | 时间不明确、多版本 conflict |
| 明确时间范围 | temporal index | 候选过多、需要语义关联 |
| 文件名、工具名、代码、专有词 | FTS / alias index | literal miss |
| paraphrase | filtered vector | score margin 低、候选冲突 |
| 更新、纠正、冲突 | ClaimVersion trajectory + OpenIssue | 缺少 source Evidence |
| “为什么改变” | transition + provenance adjacency | lineage 不完整 |
| 多 session 组合 | bounded hybrid | evidence sufficiency 未满足 |
| 多跳且中间 cue 未知 | bounded reconstruction | 仅在 M7 研究 lane 启用 |

## 4.6 两种客户端调用方式

### Agent-visible MCP tool

Agent/model 显式调用公开 `milai_memory_resolve`。适合通用 MCP Client。

### Host-prefetch MCP call

Host 在 provider 前调用同一读取语义并注入 Context。适合 OpenWorker。

两者必须共享：

```text
same principal/profile rules
same Runtime QueryPlan
same Canonical Gate
same MemoryStateView/typed outcome
same trace semantics
```

“共享语义”指同一 Kernel、Gate、StateView 和 typed outcome；它不表示二者具有相同 requirement floor。Agent 显式请求 Memory 时不得再次被 heuristic 判为 `NONE`。

Host-prefetch 可以优化 Agent 使用体验，但不能定义或复制 MiLA Memory Core。

---

# 5. MCP 产品合同

## 5.1 目标工具面与兼容迁移

MiLA vNext 的 TARGET MCP tool surface 保持粗粒度；一个 Agent Memory 请求对应一次 governed operation。

核心读取：

```text
milai_memory_resolve
milai_memory_get
milai_memory_explain
milai_memory_capabilities
```

写入与治理：

```text
milai_evidence_capture
milai_memory_propose
milai_memory_review
milai_memory_delete
milai_memory_export
```

这些是 TARGET product names，不代表 CURRENT 已实现。M0 必须先冻结与现有工具的 versioned compatibility matrix；它不是简单一对一改名：

| CURRENT tool | TARGET tool / semantic owner | 迁移决定 |
| --- | --- | --- |
| `milai_recall` | `milai_memory_resolve` | 同一 kernel/domain result；旧工具保留 CURRENT wire schema，新工具返回 versioned vNext schema |
| `milai_claim_get` | `milai_memory_get` | 扩展为 StateKey/ClaimID exact；旧名暂作 alias |
| `milai_status` | `milai_memory_capabilities` | status 字段并入 capability result；禁止第二套 capability truth |
| `milai_trace_get` + `milai_evidence_metadata_get` | `milai_memory_explain` | explain 组合 trace/provenance；每个引用独立授权，detail resource 仍可独立读取 |
| `milai_evidence_capture` | same | 保留稳定名称与 Evidence-only 语义 |
| `milai_proposal_create` | `milai_memory_propose` | 前者兼容映射；不得直接 commit Claim |
| Runtime review API | `milai_memory_review` | M5 reviewer-only；CURRENT 已注册专用 profile |
| `milai_evidence_revoke` | `milai_memory_delete` command | 旧 command 保持 schema；新 command 必须有 target、mode、idempotency、confirmation 与独立 scope |
| `milai_deletion_status_get` | deletion resource/status read | 保持只读工具或迁移为 `memory://deletion-requests/{id}`；不得与 delete command 混为同一权限 |
| no current tool | `milai_memory_export` | TARGET operator/user-data capability；不进入 M1/M2 前置 |
| `milai_prepare_context` | OpenWorker extension over resolve | 不作为公共 Core 前置；不得拥有独立 query/gate semantics |

兼容规则：

```text
one implementation
one authorization policy, evaluated per referenced resource
one internal domain result
versioned wire adapters
old wire schema remains compatible during migration
```

CURRENT `milai_recall` 的 `OK / DEGRADED / ABSTAINED`、字段名和错误行为在 compatibility window 内保持；TARGET `milai_memory_resolve` 的新 statuses 由单一显式映射产生。M0 为每个旧 status 做 contract test，禁止旧 Client 被静默切换到新 schema。

`milai_memory_delete` 不做隐式多动作。它必须显式区分 `REVOKE_EVIDENCE | REQUEST_FORGET | REQUEST_PURGE`，使用外部写入 idempotency key，并按 mode 检查 capability/confirmation。状态查询保持 read-only。

禁止为了重命名复制 resolver、检索逻辑、缓存或 capability policy。旧 endpoint/tool 的移除只在真实 client migration 完成后单独决定。

## 5.2 主读取合同

M1 `milai_memory_resolve` 的最小显式输入：

```yaml
query: non-empty string
```

MCP authentication context、profile 启动配置或可信 deployment policy 绑定；不接受普通 tool argument 自报：

```yaml
tenant/principal identity:
granted capabilities:
maximum readable scope:
maximum authority:
server-side resource ceilings:
```

调用者可以在已授权上限内请求更窄的 scope、authority、consistency 和 budget；Runtime 取 requested 与 granted ceiling 的安全交集。

M1 可接受：

```yaml
invocation_mode: EXPLICIT_READ  # PREFETCH_AUTO only for authorized Host profile
requested_scope: {}
required_authority: INFORMATIONAL
required_freshness: CURRENT
consistency_mode: CANONICAL_REQUIRED
budget: {}
entities: []
temporal: {}
```

M6 在 configurable detail profile 增加可选、只收窄的提示；省略时 wire/result 仍无任何
Task-shaped 字段：

```yaml
task_context:
  project_ids: []
  entities: []
  memory_types: []
  action_risk: LOW | MEDIUM | HIGH  # trace-only; non-authoritative
```

M2 增加精确 target：

```yaml
state_keys: []
claim_ids: []
evidence_depth: STATE_ONLY | SUPPORT_POINTERS | RAW_EVIDENCE
```

M3 增加在线 reuse locator：

```yaml
previous_context_id: null
```

Frozen contract 保持两个正交轴，不引入 `STRICT_CURRENT` 新 enum：

```text
required_freshness = CURRENT | STALE
consistency_mode    = EVENTUAL | READ_YOUR_WRITES | CANONICAL_REQUIRED
```

例如“必须读取当前 canonical state”表达为：

```text
required_freshness=CURRENT
consistency_mode=CANONICAL_REQUIRED
```

最小输出必须保留：

```yaml
status: HIT | PARTIAL | CONTESTED | ABSENT | ABSTAINED | DENIED | UNAVAILABLE
items: []
open_issue_ids: []
evidence_refs: []
consistency:
canonical_position:
trace_id:
degraded_components: []
abstention_reason:
context_receipt: null
```

M0 必须决定如何兼容 CURRENT `ABSTAINED`、fallback 和 derived result，不允许仅为新 enum 新建第二套 outcome。

## 5.3 Typed failure

以下语义必须分离：

```text
ABSENT       = 权限范围内没有适用 Memory
CONTESTED    = 存在 live OpenIssue / conflict
DENIED       = principal/capability/scope 不允许
UNAVAILABLE  = MCP/Runtime/canonical store 不可访问
ABSTAINED    = 证据/authority/consistency 不足
```

结果还必须保留当轮 requirement：

```yaml
memory_intent: NOT_NEEDED | POSSIBLE | REQUIRED
requirement: NONE | EXACT | SEARCH | RECONSTRUCT
availability: AVAILABLE | DEGRADED | UNAVAILABLE
```

因此：

```text
requirement=EXACT + availability=UNAVAILABLE
→ UNAVAILABLE

requirement=NONE
→ NOT_NEEDED
```

二者不能通过 fallback 互相转换。

禁止：

```text
transport error → empty HIT
Task missing → no-memory
projection down → authority downgrade and stale truth acceptance
cache miss → require another user turn
broad catch → generic UNKNOWN with lost cause
```

## 5.4 Capability、profile 与权限

目标 permission vocabulary：

```text
memory.read
memory.evidence.write
memory.propose
memory.review
memory.delete
memory.export
```

| Profile | 能做什么 | 不能做什么 |
| --- | --- | --- |
| `reader-lite` | 单一 query-first recall | write/review/revoke；模型选择 scope/authority |
| `reader` | recall + exact/detail/trace/status | write/review/revoke |
| `submitter` | capture Evidence、create Proposal | approve own proposal、direct Claim write |
| `reviewer` | inspect/review pending Proposal | submitter 与 reviewer 同一 actor 自批；capture/propose；direct DML |
| `operator` | revoke、deletion status | ordinary Agent 默认获得 capability |

`reviewer` 必须是独立 capability/profile。它可以由本地 Steward UI 或受信 MCP Host 使用，不进入普通模型 tool catalog。

HTTP MCP 采用资源绑定的 authorization 和最小 scope；STDIO 从受控环境取得 credentials。每次工具调用重新校验 principal、scope 和 handle ownership，不能把 MCP connection/process 当作权限或 conversation identity。MCP server 不把收到的 client token 原样透传给下游 Runtime；如果调用受保护下游，应使用面向该资源的独立凭据。

`milai_memory_explain` 不能因为 caller 可读某个 Context/Trace，就自动允许读取其全部 lineage。对每个 ClaimVersion、Evidence、OpenIssue、ContextPointer 和 resource link，Runtime 都重新检查：

```text
tenant
caller permission and scope
retention / legal hold readability
Evidence revoke and GroundingBlock
historical/current access policy
Blob physical state when body is requested
```

父对象 authorization 不向子引用传播。Primary target 不可读时返回受控 `DENIED`/policy-defined non-disclosure outcome；部分 lineage 不可读时只返回可读子集和 typed incompleteness，不暴露被拒对象正文或可猜测内部字段。

## 5.5 Runtime 内部读取规划

公开 Agent 只发一次 coarse-grained memory request。Runtime 内部执行：

```text
Principal/Permission Gate
→ QueryMemoryIntent
→ exact StateKey/Claim address
→ if insufficient: scoped temporal/FTS
→ if insufficient: filtered vector
→ if needed: conditional small-set rerank
→ optional evidence recovery
→ Canonical Gate
→ MemoryStateView
→ minimal Context/result
```

Need、cache validator、route decider、retriever、state resolver 不拆成一串公开 MCP tools。

## 5.6 MCP Resources

在 M2 以后提供可检查、URI-addressed detail：

```text
memory://state/{state_key}
memory://claims/{claim_id}
memory://claims/{claim_id}/versions/{version_id}
memory://evidence/{evidence_id}
memory://open-issues/{issue_id}
memory://contexts/{context_id}
```

`milai_memory_resolve` 默认返回 structured `MemoryStateView` 和最小正文；Claim lineage、完整 Evidence、历史版本通过 resource link 按需读取，避免全部进入 prompt。

Resource subscriptions / update notification 只作为 V2 capability-negotiated 优化。第一可用版本不依赖 push invalidation。

## 5.7 Reuse 不是 semantic route

CURRENT `NONE / CACHE / L0 / L1` 混合了需求与执行优化。TARGET 分离为：

```yaml
MemoryRequirement:
  NONE | EXACT | SEARCH | RECONSTRUCT

ReusePolicy:
  TRY | FORBIDDEN
```

执行规则：

```text
previous_context_id present
→ Runtime validates principal, scope, coverage and dependencies
→ valid: reuse
→ miss/expired/changed: same-call primary plan
```

Cache/Context miss 不是 terminal outcome，不要求用户再发一个 Turn。

第一版不公开 portable offline `MemoryLease`，也不新增 `ContextReceipt` durable table/object。`ContextReceipt` 只是现有 `ContextCapsule` / `ContextPointer` / `RetrievalTrace` 的 versioned wire view，由 Runtime context assembler 签发：

```yaml
ContextReceipt:
  context_capsule_id: "opaque"
  requirement_coverage: {}
  dependency_digest: ""
  canonical_position: 0
  issued_at: ""
  expires_at: ""
  invalidation_sequence: 0
  freshness_at_issue: CURRENT | STALE
  consistency_mode_at_issue: EVENTUAL | READ_YOUR_WRITES | CANONICAL_REQUIRED
```

Durable owner、tenant identity、TTL、status、invalidation 和 purge 继续由 frozen `ContextCapsule` / `ContextPointer` 管理。客户端下次只提交 `previous_context_id=context_capsule_id`。Receipt 是 locator，不是 bearer authority；Runtime 每次调用重新授权，并通过现有 Pointer recovery 与 axis-complete ECS/Gate 在线验证依赖。Runtime 不可用时，receipt 不能被宣称为 CURRENT。

M3 只允许复用不含 Host-only Active Goal/constraints 的 task-free MemoryStateView capsule。包含
protected Active Goal、Task binding 或 Host constraints 的 capsule 不进入 task-free reuse；其
复用只是 M6 候选能力，最小 M6 未实现并继续禁止。以后若启用，必须同时匹配 TaskContext 且
继续执行完整 revalidation。

## 5.8 MCP 协议依据

本 Goal 对 MCP 的使用遵循官方协议，而不是把“Tool 一定由模型主动调用”当成架构前提：

- Tools 以 model-controlled 为常见模式，但协议不强制特定交互模型，因此 OpenWorker prefetch 与 Agent-visible invocation 可以复用同一 tool contract；
- tool result 可返回 `structuredContent`、resource link 和 embedded resource；
- tools/resources catalog 可以随当轮 authorization 变化，但不能以 connection-local 可变状态替代授权；
- MCP connection/stdio process 不是 conversation/session identity；跨请求状态使用显式 opaque handle；
- resource subscription 可用于未来 invalidation，但不是 M1 正确性的前置。

参考：

- [MCP Tools specification, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)
- [MCP Resources specification, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)
- [MCP Base Protocol overview, 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/basic)
- [MCP Authorization specification, 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)

---

# 6. Memory 生命周期

## 6.1 受治理写入

```text
MCP submitter
→ milai_evidence_capture
→ durable EvidenceRecord
→ milai_memory_propose / milai_proposal_create compatibility alias
→ pending OperationProposal
→ independent reviewer capability
→ StewardDecision
→ controlled canonical procedure
→ ClaimVersion / ClaimHead / OpenIssue
→ Outbox
→ projections
```

写入时必须保持：

```text
Evidence capture does not create a Claim
Proposal does not change canonical state
Submitter cannot approve itself
Projection cannot commit truth
```

产品层可使用下列用户可理解的 mutation intent：

```text
CREATE
SUPPORT
CORRECT
SUPERSEDE
CHALLENGE
REVOKE
DELETE
FORGET
```

它们不能绕过 frozen transaction vocabulary。M0/M5 必须冻结显式映射：

| Product intent | Frozen internal operation / lifecycle |
| --- | --- |
| `CREATE` | `CREATE` |
| `SUPPORT` | `SUPPORT` / `REVALIDATE` / `REGROUND`，由 evidence 与当前 grounding 决定 |
| `CORRECT` | `SUPERSEDE`、`CONTEXTUALIZE`、`WEAKEN` 或 `NO_CHANGE`；禁止原地改 ClaimVersion |
| `SUPERSEDE` | `SUPERSEDE` + exact-head CAS |
| `CHALLENGE` | `CONTRADICT` + OpenIssue branch/revision；默认不移动 Head |
| `REVOKE` | Evidence revoke lifecycle；同步 canonical fail-closed，非 Claim hard delete |
| `DELETE` | deletion request/status + retention/purge policy；不得直接 DML ClaimHead |
| `FORGET` | policy-governed revoke/delete workflow；不得由 retrieval result 自动执行 |

完整 frozen operation 集继续是：

```text
CREATE · SUPPORT · WEAKEN · REVALIDATE · REGROUND
SUPERSEDE · CONTEXTUALIZE · CONTRADICT · NO_CHANGE
```

本文不新建 `commit_decision` 或 `claim_evidence_edge` 同义 truth source：数据库继续使用 `steward_decision` 与 `grounding_relation`。

## 6.2 读取

```text
MCP milai_memory_resolve/get
→ principal/profile policy
→ query intent + exact or progressive retrieval
→ canonical applicability validation
→ MemoryStateView
→ compact result + provenance pointer/resource link + ContextReceipt + trace
```

## 6.3 更新、冲突和撤销

```text
Correction/Supersede
→ new Evidence + Proposal + exact-head review/CAS
→ append ClaimVersion

Conflict
→ preserve Head as policy requires
→ create/update OpenIssue with branches

Revoke/Forget
→ synchronous canonical block
→ active Context invalidation
→ asynchronous derived purge
→ later read cannot re-enter through stale projection
```

---

# 7. 可用性定义与发布层级

## 7.1 可用性定义

对声明支持的 MCP operation `o`：

```text
Usable(o) =
  Reachable(o)
  AND SemanticallyCorrect(o)
  AND Persistent(o)
  AND BoundedCost(o)
  AND ExplicitFailure(o)
  AND Operable(o)
```

其中：

```text
SemanticallyCorrect =
  principal/scope correct
  AND time/currentness correct
  AND authority satisfied
  AND Canonical Gate passed
  AND provenance traceable
```

## 7.2 发布层级

| Milestone | 产品含义 | 阻断条件 |
| --- | --- | --- |
| `M0 BASELINE_REPLAYABLE` | CURRENT path、query-only shadow 和阶段 latency 可重放 | 只见最终 UNKNOWN；没有 first failing boundary；shadow 改变行为 |
| `M1 MCP_QUERY_READ_USABLE` | 普通 MCP Client 无 Task 使用 `milai_memory_resolve`；OpenWorker 用相同合同完成单轮和 fresh-resolve 连续两轮 | 依赖 Host Task；第二轮未到 MCP；silent NONE；错误 scope/currentness；无 typed failure |
| `M2 EXACT_STATE_USABLE` | MemoryStateView current/historical + canonical StateAddress exact hot path | 新 truth store；exact 依赖 projection；Addressable/Reachable/Resolved 混报 |
| `M3 REUSE_AND_FAILURE_USABLE` | receipt hit/revalidation、miss same-call fallback 与 unavailable typed | miss 终止；TTL 冒充 CURRENT；MCP failure 变 NONE；Host 第二 truth |
| `M4 BOUNDED_RETRIEVAL_EFFICIENT` | exact/search 按结构性成本合同运行 | exact 进入 search；无 candidate/budget/latency 边界 |
| `M5 GOVERNED_LIFECYCLE_OPERABLE` | capture→proposal→review→update→revoke/delete 与 delta projection 闭合 | self-approval；restart 丢 state；revoke re-entry；projection 可写 truth |
| `M6 TASK_ENHANCEMENT_PROVEN` | Task 可提高精度/效率，但 task-free path 保持可用 | Task 再次成为 reachability gate；无 matched ablation |

M1 已包含首要客户端真实连续对话；M1 与 M2 形成第一个 scoped MiLA Memory Runtime 可用版本。M3 闭合复用和故障语义；M4/M5 分别扩展 Search 与 governed lifecycle。M6/M7 不阻断 task-free Core release。

---

# 8. 效率合同

## 8.1 EXACT

```text
logical MCP calls        = 1
auxiliary LLM calls      = 0
embedding calls          = 0
vector calls             = 0
reranker calls           = 0
broad canonical scans    = 0
```

固定路径：

```text
ClaimID or exact canonical StateKey tuple
→ Claim identity / ClaimHead / ClaimVersion
→ EffectiveClaimState
→ Canonical Gate
→ minimal hydrate
→ MemoryStateView
```

`StateAddressService` 首先解析 canonical identity：

```text
(tenant, subject, predicate, memory_kind, normalized scope)
→ claim_id
→ ClaimHead / EffectiveClaimState
```

该解析可以使用 canonical table 上的普通 B-tree/unique physical index，但正确性不依赖新的 projection table。可选 `StateAddressIndex` 只能是由 Outbox 维护、可重建的 locator accelerator：命中只提供 candidate ID，miss/down 必须回到有界 canonical equality lookup。权限、时间、scope、revoke、OpenIssue 和 authority 仍由 Canonical Gate 决定。

## 8.2 SEARCH

```text
principal/scope/time hard filter first
→ temporal/FTS
→ filtered vector only when sparse result insufficient
→ rerank only a bounded small candidate set
→ stop immediately when evidence sufficiency is met
```

每个 stage 必须有：

```text
candidate cap
deadline
token/byte budget
attempted/stop reason
```

projection 分离保存：

```text
raw_text       = source-recoverable content
lexical_text   = aliases/entities/fact keys/vocabulary bridge
semantic_text  = embedding-clean text; no forced lexical expansion
temporal_fields = valid/system/event time
```

不要把 lexical enrichment、summary 和 raw value 拼成唯一 embedding text。

检索阶段 lazy hydration：

```text
candidate id/key/version/score/time/scope
→ Canonical Gate
→ hydrate accepted value and provenance pointer
→ raw Evidence only when requested
```

## 8.3 MCP access

- 普通 resolve 目标为一次 Agent call、一次 MCP logical call、一次 Application Kernel resolution；
- MCP server/client、DB pool 和必要 Runtime client 应长期复用，不为每个 Turn 重启完整 composition；
- 先 profile MCP decode、broker/IPC、Runtime/kernel、SQL、hydrate 分项，再决定优化位置；
- 同机首选 MCP facade 直接调用 application kernel；若暂时保留 loopback Runtime，至少使用 persistent client/connection pool；
- 不为假设中的 Direct/HTTP 提前三套实现；
- OpenWorker answer path 的 vLLM 调用不计入 MiLA Core recall call count。

## 8.4 写入和物化

同步必须完成：

```text
raw Evidence persistence
provenance
Proposal/Review canonical transaction
ClaimVersion/ClaimHead/OpenIssue
outbox position
canonical Claim identity/Head/ECS and ordinary physical indexes
```

可异步微批：

```text
FTS projection
embedding
entity/time extraction
summary/graph candidate
```

Projection 未 ready 时 exact canonical read 仍应工作；Search 返回 typed degraded，而不是旧 truth。

## 8.5 性能报告分表

```text
MCP Online Read
Deep Search
Cold/Incremental Materialization
OpenWorker Client Overhead
Provider Answer Latency
```

禁止用一个总体 speedup 混合五种成本。

---

# 9. 开发纪律：少防御、少仪式、强边界

## 9.1 “减少防御性编程”的准确含义

应减少：

- 同一 payload 在多层重复类型猜测和校验；
- 为尚未支持的 transport、旧 schema 或假想 client 预建 fallback；
- broad `except Exception` 后返回 `UNKNOWN`；
- 将内部 invariant violation 包装数层后丢失原始错误；
- raw prompt hash 等脆弱字段作为唯一业务关联键；
- 一个对象在 request、cache、registry、trace 中各有一套可变 truth；
- 为通过测试硬编码 case/fixture/provider answer；
- 失败后扩大 timeout、增加 retry、sleep 或重复全量矩阵。

推荐：

```text
validate once at MCP/HTTP/DB boundary
→ typed internal value
→ simple deterministic domain path
→ one stable error mapping at boundary
```

内部不变量在 development 中可以直接 assertion/typed exception 失败；不要伪装成可恢复业务结果。

## 9.2 不能删除的核心防线

以下是 Memory correctness，不是审计冗余：

```text
authentication and fixed capability profile
tenant/scope/authority/permission/retention checks
Evidence/Proposal/Decision separation
append-only version and exact-head CAS
OpenIssue preservation
Canonical Gate
revoke fail-closed
idempotency for external writes
bounded request/result/deadline
canonical unavailable abstention
```

## 9.3 审计预算

### 日常单项开发

只需要：

```text
exact command/test node
first failing boundary
original exception
minimal code diff
single positive + relevant negative twin
```

不需要默认生成：

```text
全仓 source manifest
每文件 SHA inventory
独立 reviewer bundle
多层 receipt/receipt-of-receipt
新 audit state machine
```

### Milestone candidate

M0～M6 milestone 默认只生成一个可读结果目录；不为每个 milestone 建独立 governance package：

```text
one aggregate result
one short environment/command record
known limitations
```

只有结果横跨多个 runner/artifact 时才增加一个简短 index；不默认计算全树 hash。

### Release review

只有目标 scoped release 的全部 owning gate PASS 后才进行至多一次独立只读 review。单个 M0/M1 patch 不触发 review。Reviewer 不参与日常开发、不重复打分、不产生 canonical authority。

需要独立 Codex review 时，执行身份和约束使用 [`codex_sol_xhigh.md`](./codex_sol_xhigh.md)；它只审查已闭合 milestone artifact，不代替 owning tests，也不在失败单项调试期间反复调用。

Formal paper integrity 继续由独立 lane 管理，不复制到产品开发。

## 9.4 单项失败调试

```text
failed gate
→ select one failing case
→ reproduce once with no automatic retry
→ inspect first failing boundary
→ prove root cause
→ minimal fix
→ exact case PASS
→ negative twin PASS
→ owning module/suite PASS
→ milestone aggregate
```

所有 attempts 进入结果记录；不能只保留最后一次 PASS。完整 37-case OpenWorker matrix 不用于定位一个 MCP Core 单项失败。

## 9.5 测试频率

```text
per edit       exact test node
per logical fix owning module/package tests
per milestone  MCP product smoke + relevant integration matrix
before release full declared regression + one independent review
```

当前 1093-test gate 是 milestone regression evidence，不是每个小 patch 的固定成本。

## 9.6 并行资源

- 不同 package 的 unit/contract tests 可以并行；
- 共用 PostgreSQL database/port/socket 的 stateful tests 必须隔离或串行；
- generic MCP Core E2E 不调用 vLLM，可与 provider test 并行；
- real OpenWorker + vLLM 一次只运行一个 case；
- latency/throughput 窗口独占，不能与 cold build 或其他 GPU workload 混跑；
- 并发只缩短物理 wall time，不增加逻辑 retry、provider/MCP call 或删除失败分母。

---

# 10. 工作包与执行顺序

## M0 — Baseline 与安全边界

状态：`COMPLETE / BASELINE REPLAYABLE (2026-08-26)`

目标：在不改变对外行为的前提下，建立 Query reachability、阶段成本和真实 composition 的最小基线。

交付：

1. 本 Goal 成为 DG-13 唯一 active product board；
2. 冻结 CURRENT tools → TARGET tools 的 compatibility mapping；
3. 在 frozen `RetrievalTrace` 上补齐 requested intent、planned/attempted/terminal stage、stop/fallback reason 和 canonical position，并把 MCP/Host span 关联成 `AccessTrace` 只读 view；不新增 durable AccessTrace 表或第二 trace truth；
4. 为 MCP decode、broker/IPC、Runtime/kernel、SQL、rerank、hydrate 分段计时；
5. shadow 运行 `query-only intent` 与 CURRENT `Task-gated Need`，记录 fingerprint、typed intent/route disagreement，不保存 query 明文且不改变 production result；
6. 建立不含 OpenWorker/vLLM 的 generic MCP task-free smoke；
7. 保留主产品 `OpenWorker → MCP → Runtime → vLLM` composition CI；
8. 保留 user-role forged tool-result negative test，防止伪造 memory context；
9. 明确 `milai_prepare_context` 为 OpenWorker extension，不拥有独立 canonical semantics；
10. 不新增 Direct/HTTP、portable lease、Task registry、graph 或 learned router。

M0 不生成全仓 source inventory、每文件 hash、重复 review bundle 或新的 audit state machine。

M0 是短前置，不是新 P0 平台工程：完成一条 generic replay、一条 OpenWorker composition replay、trace 字段闭合和 shadow disagreement 统计后立即进入 M1；不等待旧 37-case aggregate、formal holdout 或独立 review。

退出条件：可以重放 CURRENT 路径，并明确报告：

```text
query-only intent = POSSIBLE/REQUIRED
CURRENT task-gated path = NONE
```

的实际 case 数、第一阻断边界与阶段延迟。

M0 完成事实（synthetic development evidence，不获得 release label）：

- CURRENT→TARGET 所有权与 outcome 映射已冻结在 [`docs/contracts/DG13-MCP-vNext-compatibility-v0.1.md`](./docs/contracts/DG13-MCP-vNext-compatibility-v0.1.md)；CURRENT `OK / DEGRADED / ABSTAINED` wire 合同有独立 contract test；
- 固定 5 例 query-only shadow 回放中，4 例为 `POSSIBLE/REQUIRED`，其中 3 例与 CURRENT `NONE` 发生分歧；第一阻断边界为 `HOST_TASK_GATE | HOST_TYPED_NEED_FILTER`，见 [`var/dg13/m0/dg13-m0-baseline-20260826a/report.json`](./var/dg13/m0/dg13-m0-baseline-20260826a/report.json)；
- generic stdio MCP smoke 在无 Task、无 OpenWorker、无 vLLM 条件下列出并调用仅需 `query` 的 CURRENT tool，重启 MCP process 后重放通过；
- 真实 `OpenWorker→MCP→fresh Runtime→vLLM` 单例回放 `PASS`，MCP `1/1`、provider `1/1`、自动重试 `0`、cleanup `PASS`，见 [`var/dg13/runs/dg13-m0-openworker-replay-20260826a/report.json`](./var/dg13/runs/dg13-m0-openworker-replay-20260826a/report.json)；
- 该真实链已关联 Host attempt、RetrievalTrace 与 canonical position；实测 `host_total=1669.346 ms`、`UDS=1661.352 ms`、`broker/IPC=1239.934 ms`、`MCP handler=421.418 ms`、`Runtime=413.125 ms`、`context compile=4.2 ms`。Runtime 内部 SQL/rerank/hydrate 由 RetrievalTrace `stage_metrics` 记录；
- MCP SDK 在 tool handler hook 前完成 JSON-RPC decode，因此当前 `mcp_decode_ms=null`，只能报告上界为 MCP protocol overhead（本例 `8.293 ms`）；该字段保持显式未观测，不伪造精确 decode 时间。

## M1 — Standalone MCP Read Usability

状态：`GATE PASS（2026-08-26）`

目标：实现 Query-first `milai_memory_resolve`，使任意授权 MCP Client 无 Task 也能进入持久 Memory read；OpenWorker 作为首要 conformance client 使用相同合同。

真实纵向用例：

```text
fresh Runtime with governed fixture
→ start milai-mcp reader-lite
→ MCP initialize + tools/list
→ milai_memory_resolve(query) without task metadata
→ AccessOutcome v0.1 adapted from existing RecallEnvelope + provenance + trace
→ restart MCP process/client
→ recall same canonical state

same MCP contract
→ OpenWorker prefetch or Agent-visible tool
→ local vLLM first answer
→ same OpenCode session second user turn
→ fresh milai_memory_resolve call reaches MCP
→ local vLLM second answer
```

部署约束：

```text
one logical MCP call
long-lived MCP server/client where current deployment permits
persistent Runtime/DB connection pool
no full composition restart in the steady per-turn path
```

若 M1 暂时仍通过 loopback Runtime API，应复用 persistent client。只有 M0 证明 broker child/client connection 是 per-call 主残差时，M1 才把其持久化列为 behavior change；是否进一步抽取 in-process Application Kernel 同样由 profile 决定，不以架构洁癖触发重写。

OpenWorker `U1-TASK-CONTINUE` observation binding 已按原生 `sessionID + operation/message ID`
闭合；未扩展 MiLA Core Task schema，也未使用文本相似度。Host `query-first` 模式在每个
native operation 直接调用同一 `milai_memory_resolve(query)` 合同，不经过 Host Need resolver。
M1 验收时每轮都是 fresh resolve；M3 起 Host 可只携带上轮 opaque
`previous_context_id`，仍每轮发起一次 resolve，且不缓存 Memory items/head/OpenIssue。

最低矩阵：

| 类别 | 必须覆盖 |
| --- | --- |
| Language | 中文、英文、中英混合 |
| Reachability | Task omitted、Task unknown、query-only REQUIRED/POSSIBLE |
| State | current、absent、abstention；不在 M1 新实现 historical resolver |
| Governance | revoked、wrong scope、authority insufficient；已有 OpenIssue refs 不得丢失 |
| Failure | Runtime unavailable、malformed request、deadline |
| Persistence | MCP process/client restart；canonical state retained |
| Client | generic MCP client + real OpenWorker/vLLM single turn + same-session second turn |
| Trace | requested/planned/attempted/terminal/fallback complete |

M1 只在 OpenWorker answer-path conformance case 使用 vLLM；Core read tests 不依赖 provider。M1 不依赖 OpenWorker Task、Host Need resolver、ContextReceipt reuse、formal benchmark 或新的 retrieval engine。

退出 Gate：

```text
Task omitted does not disable retrieval
SilentMemoryNeedNone = 0/N
WrongScopeAcceptance = 0/N
RevokedMemoryAcceptance = 0/N
StaleAsCurrent = 0/N
typed unavailable/absent/denied/abstained are distinct
one generic smoke and one OpenWorker smoke PASS
same-session second turn reaches MCP without requiring reuse
logical MCP calls per resolve = 1; automatic retry = 0
p95 does not regress against the declared M0 baseline
```

M1 验收证据：

- generic fresh Runtime/MCP smoke 共 `21` 次 target 调用、`2` 个 MCP process/client session，
  Task metadata omitted，重启后同一 canonical ClaimVersion retained；每次 logical call `1`、
  automatic retry `0`，见
  [`var/dg13/m1/dg13-m1-generic-20260826a/report.json`](./var/dg13/m1/dg13-m1-generic-20260826a/report.json)；
- generic `mcp_handler_ms` 的 `p95=53.144 ms`，低于另一次 M0 运行的 `421.418 ms`，21 个
  observation non-regression `PASS`；该比较跨运行且不是 matched latency ablation，只作本地
  smoke 观察值，不拥有因果性能声明；
- 真实 `OpenWorker→MCP→fresh Runtime→vLLM` 同 session 两轮均使用
  `milai_memory_resolve`，MCP `2/2`、provider `2/2`、automatic retry `0`、cleanup `PASS`，见
  [`var/dg13/runs/dg13-m1-task-continue-query-first-20260826a/report.json`](./var/dg13/runs/dg13-m1-task-continue-query-first-20260826a/report.json)；
- 两条 Host AccessTrace 为同一 session hash、不同 operation hash，均
  `fresh_resolve=true`、`HIT`、`SEARCH→VECTOR`、无 cache reuse；原始 prompt/answer 未持久化；
- Runtime PostgreSQL 集成覆盖 EN/CN/mixed、Task omitted、absent、wrong scope、authority
  insufficient、revocation、live OpenIssue 与 malformed Task field；client/MCP contract 覆盖
  distinct typed 503/timeout/DENIED/UNAVAILABLE boundary。

M2 验收证据：

- fresh database 从空库迁移到 `0030_memory_state_view_gate`；迁移只扩展 Canonical Gate 的
  bitemporal mode，没有建立 `state_view` truth table；
- 普通 stdio MCP `reader-detail` 的真实 smoke 共 `5` 次调用、`2` 个 MCP process/client
  session，覆盖 StateKey current、ClaimID current、addressed `milai_memory_resolve` exact、
  SUPERSEDE 后 current 和 `valid_at + known_at` historical；不启动 projection worker 仍全部
  `PASS`，见
  [`var/dg13/m2/dg13-m2-generic-20260826e/report.json`](./var/dg13/m2/dg13-m2-generic-20260826e/report.json)；
- 每次 exact logical MCP call `1`、automatic retry `0`，auxiliary LLM / embedding / vector /
  reranker / broad head scan 均为 `0`；5 个 observation 的最大 `mcp_handler_ms=48.028 ms`；
- Runtime integration 明确覆盖当前/历史版本、错误 scope、minimal hydration、live OpenIssue
  `CONTESTED`，以及 OpenIssue 创建前 `known_at` 不被后来的冲突污染；
- 全量回归：Runtime `274 passed / 1 environment skip`、OpenWorker `101 passed`、Python Client
  `159 passed`、MCP `31 passed`；Python Client/MCP mypy PASS。Runtime 全量 mypy 仍保留
  `context_preparation.py` 的 9 个既存类型基线错误，不属于 M2 变更文件。

M3 验收证据：

- fresh database 从空库迁移到 `0031_task_free_receipt`；迁移不新增表，只增加在既有
  `ContextCapsule` / `ContextPointer` 上签发 task-free wire view 的受控函数；
- 普通 stdio MCP `reader-detail` real smoke 共 `6` 次调用、`4` 个独立 MCP process/client
  session，覆盖有效 receipt reuse、未知 locator 同调用 EXACT、SUPERSEDE/head change 同调用
  EXACT、scope coverage miss，以及 Runtime 停机后 `REQUIRED + EXACT + UNAVAILABLE`；automatic
  retry `0`、数据库 cleanup `PASS`，见
  [`var/dg13/m3/dg13-m3-generic-20260826a/report.json`](./var/dg13/m3/dg13-m3-generic-20260826a/report.json)；
- Runtime integration 另行覆盖 expired receipt、owner mismatch、current/historical reuse、
  OpenIssue 创建后的 invalidation 与 `CONTESTED` fallback；TTL 从不单独证明 CURRENT，每次
  reuse 均在 `REPEATABLE READ` snapshot 中重跑 canonical position、Gate 和 Evidence pointer
  校验；
- OpenWorker 只按 native session 保存 opaque `context_capsule_id`；第二轮把 locator 显式传回
  同一个 `milai_memory_resolve`，不缓存 Memory items/head/OpenIssue，不建立第二 canonical
  truth；transport failure 继续生成 `MEMORY_REQUIRED_BUT_UNAVAILABLE` 并禁止 provider；
- 最终回归：Runtime fresh DB `279 passed / 1 environment skip`，见
  [`var/dg13/test-gates/dg13-m3-runtime-20260826e/report.json`](./var/dg13/test-gates/dg13-m3-runtime-20260826e/report.json)；
  Python Client `160 passed`、MCP `31 passed`、OpenWorker `101 passed`；Runtime M3 touched files、
  Python Client 与 MCP mypy PASS。

M4 验收证据：

- Runtime-owned `MemoryAccessPlanner` 为 `POSSIBLE/REQUIRED` 生成 candidate、deadline、
  context 和 reranker 上限；`QueryPlan v10` 与 `search_trace` 记录实际候选数、
  escalation/stop reason、deadline outcome 和 tokenizer-independent context token upper bound；
- temporal/FTS 候选在排序前执行 tenant/principal/project/time 硬分区，以及请求指定的
  entity/type 硬分区；filtered vector 仅在 sparse insufficiency 后升级，reranker 仅处理
  Canonical Gate 接受的小候选集，`POSSIBLE` 路径 reranker 始终为零；
- 真实 fresh PostgreSQL + `reader-detail` stdio MCP matched slice 每侧 `8` 轮，
  quality hit `8/8 → 8/8`，Runtime kernel p95 `45.431 ms → 14.524 ms`，
  candidate max `3 → 1`，context upper bound `2733 → 902`，目标路径
  vector/recent/reranker calls 均为 `0`、automatic retry `0`、cleanup `PASS`，MCP handler p95
  `62.094 ms → 41.537 ms`，见
  [`var/dg13/m4/dg13-m4-bounded-20260826e/report.json`](./var/dg13/m4/dg13-m4-bounded-20260826e/report.json)；
- 真实 PostgreSQL integration 覆盖 statement timeout 转换为
  `SEARCH_BUDGET_EXHAUSTED`、超大 canonical value 整项丢弃而不截断内容，以及
  entity/type/scope/time hard partition；报告绑定当前相关源码 aggregate SHA-256
  `04646af427fabd5e92464f22fbb77234d2e2df615b564725090c9d1e4fbaa352`。最终发布回归见下方
  R2 fresh-database Runtime gate `299 passed / 1 environment skip`。

M5 验收证据：

- 真实 fresh PostgreSQL 上由 `submitter/reviewer/reader-detail/operator` 四个独立 profile 完成
  Evidence capture → pending Proposal → reviewer-only list/get read path → approve/reject → CREATE / immutable
  SUPERSEDE / CONTRADICT → current/CONTESTED read → revoke/delete/purge；共 `28` 次真实 stdio MCP
  process/client session、automatic retry `0`、cleanup `PASS`，见
  [`var/dg13/m5/dg13-m5-lifecycle-20260826c/report.json`](./var/dg13/m5/dg13-m5-lifecycle-20260826c/report.json)；
- Runtime 对 `5/5` 个 review decision 验证 submitter/reviewer actor 均不同；profile capability
  互斥，submitter review 与 reviewer capture 均被拒绝，legacy local admin token 不计入产品
  actor-separation 证明；迁移 `0032_reviewer_actor_separation` 还在 canonical procedure 层拒绝
  同 actor 审批（HTTP `403 SELF_REVIEW_FORBIDDEN`，Proposal 保持 pending、Decision 为零），并把
  Proposal list/detail 限定到 reviewer；reader/submitter/operator 均被拒绝；
- projection delta outbox/watermark `3 → 6 → 16`；故意配置的无效 provider 使 worker 在启动阶段
  非零退出，期间 exact canonical current 不变；这只证明“错误配置下 worker 不启动而 canonical
  仍可用”，不证明 in-flight provider failure 或 lease recovery。另一个正常 incremental/rebuild
  replay 序列达到预期 watermark 且 canonical Claim/Version 数不变；set-based admission cap `128`，embedding
  micro-batch 配置和 lease/inference/projection-write/complete 分段指标均落证；
- revoke 后 projection purge 前 exact read 已立即 `ABSTAINED`，删除状态从
  `PENDING/PENDING` 经 worker 变为 `COMPLETED/ERASED`，没有 stale projection re-entry；
- 报告绑定当前相关源码 aggregate SHA-256
  `02517025251ede919380bed50d33879cdfa1a6ee13aa5048ee314dd6655cd7cc`；list/get 证明的是
  reviewer-only 应用读取路径被实际调用，不声称证明任何人类 reviewer 的理解或判断过程。

M6 验收证据：

- 没有新增 migration、Task truth 或 Task identity；detail-profile `task_context` 只接受
  project/entity/type narrowing 与 trace-only action-risk，Runtime 在既有 planner/Gate 前和
  Host-bound scope/hints 求交；task-off 响应保持完全不含 Task-shaped 字段，`reader-lite`
  schema 不变；
- 真实 fresh PostgreSQL、同一个 `reader-detail` stdio MCP process/session 上交替运行 matched
  task-off/task-on 每侧 `8` 轮，quality `8/8 → 8/8`，candidate max `2 → 1`，context token upper
  bound `1819 → 902`，Runtime kernel p95 `47.573 ms → 12.292 ms`，MCP handler p95
  `83.875 ms → 28.878 ms`；共 `18` 次 resolve、`16` 次
  trace recovery、automatic retry `0`、cleanup `PASS`，见
  [`var/dg13/m6/dg13-m6-task-20260826c/report.json`](./var/dg13/m6/dg13-m6-task-20260826c/report.json)；
- task-on/off RetrievalTrace 的 required authority 相同；`action_risk=HIGH` 仅记录
  `ACTION_RISK_OBSERVED_NO_POLICY_EFFECT`，不能改变 authority/consistency；越出 Host project
  scope 的 TaskContext 在请求层被拒绝，不会因空交集退化成无分区宽搜索；task-on 签发的
  receipt 被等价 task-off 请求复用时仍不返回任何 Task-shaped 字段；
- 报告绑定当前相关源码 aggregate SHA-256
  `29b97b471f7f29759b63596f9e4a6c5f47e79022395b066073639f7ccc0fdddd`；最终发布回归见 R2。

Release closure 验收证据：

- 单一 operator-facing isolated smoke 在 `0032_reviewer_actor_separation` 上完成
  health→ingest→pending Proposal→显式测试 Steward review→projection→L0/L1→context/trace→
  revoke/stale abstention→deletion；临时库连接数归零、临时 Blob root 精确移除，见
  [`runtime/var/reports/smoke-fe33d8ae7f28467b8f3c3553111a262d.json`](./runtime/var/reports/smoke-fe33d8ae7f28467b8f3c3553111a262d.json)，
  SHA-256 `83b9c2a6293c421decad279db4f32b2ceea296c497fd3ae0ce909ea5c0355284`；
- final fresh-database Runtime gate `299 passed / 1 environment skip`（仅 Runtime venv 未安装
  `milai_client` 的组合测试环境 skip），数据库 cleanup `PASS`，见
  [`var/dg13/test-gates/dg13-release-runtime-20260826e/report.json`](./var/dg13/test-gates/dg13-release-runtime-20260826e/report.json)，
  SHA-256 `ea3eec499c8bdce3d201983f7cbc15c792a4a59182ee418eb7c16afc34e1b650`；
- Python Client `162 passed`、MCP `33 passed`、OpenWorker `101 passed`；Runtime/Python Client/MCP
  ruff 与 strict mypy 均 `PASS`，OpenWorker ruff `PASS`；产品生成的 MCP 配置含独立 reviewer
  profile 且 `--max-retries 0`；
- Agent contract test `2 passed`，`contracts/agent/v1` 的 `5` 个 JSON/YAML 文件全部解析成功；
  archive-aware secret scan `PASS`：`1405` files、`2471` archive members、`229070288` bytes、
  `17` 个已知 secret 值均无路径或归档成员命中，且无 unsafe archive；
- 上述非 Runtime regression/static/contract/secret 的实际命令、UTC 时间、退出码和原始摘要见
  [`docs/reports/DG-13-R2-verification-receipt-2026-08-26.json`](./docs/reports/DG-13-R2-verification-receipt-2026-08-26.json)；
- 汇总 release disposition 见
  [`docs/reports/DG-13-scoped-release-disposition-2026-08-26.json`](./docs/reports/DG-13-scoped-release-disposition-2026-08-26.json)。
  R1/R2 已闭合；本轮唯一独立 release review 对 candidate disposition SHA-256
  `f2eedd91ff67f20440d2cdb9bc9615f16331c0a5ea54f43fa353f11cc8a1fc07` 返回
  `ACCEPT / PASS`，P0/P1/P2 均无未解决项；scoped label 已获得。

## M2 — MemoryStateView + Exact State Hot Path

状态：`GATE PASS / 2026-08-26`

目标：把 StateView 从分散字段收敛为 Runtime-owned 动态读模型，并把 current/historical state 从宽检索中分离出来。

交付：

1. `MemoryStateViewService` 动态解析 Head/Version/time/scope/permission/revoke/Grounding/OpenIssue；不新增 authoritative `state_view` 表；
2. `StateAddressService` 通过 canonical Claim identity/Head/ECS 解析 StateKey；不依赖 derived projection；
3. `milai_memory_get` 支持 StateKey / ClaimID exact read；
4. `milai_memory_resolve` 对可合成地址的 current query 进入 exact path；
5. 支持 `valid_at` 与 `known_at` 的 current/historical resolution；
6. OpenIssue 以 `CONTESTED` 或 policy-limited result 显式暴露；
7. addressable、reachable、correctly-resolved 分别 trace 和计量；
8. minimal hydration，只读取被 Gate 接受的 value/provenance pointer。

结构性成本 Gate：

```text
auxiliary LLM calls = 0
embedding calls     = 0
vector search       = 0
reranker calls      = 0
broad head scan     = 0
logical MCP call    = 1
```

M2 不引入 vector、graph、learned task resolver 或 reconstructive retrieval。

## M3 — Same-call Fallback、ContextReceipt 与 Typed Availability

状态：`GATE PASS / 2026-08-26`

目标：把复用从 semantic route 中移除；任何 reuse miss 在同一次 MCP 调用内回到 primary plan，并使 Memory required-but-unavailable 具有确定语义。

交付：

```text
previous_context_id
→ authenticate and validate receipt
→ coverage/dependency/currentness valid: REUSE
→ miss/expired/head changed/issue changed: same-call EXACT or SEARCH
```

以及：

```text
REQUIRED + Runtime unavailable → UNAVAILABLE
REQUIRED + permission denied   → DENIED
REQUIRED + evidence inadequate → ABSTAINED
NONE                           → NOT_NEEDED
```

强制禁止：

```text
receipt miss → terminal UNKNOWN
Runtime unavailable → Need.NONE
TTL not expired → claim CURRENT without validation
context_id → bearer authority
```

OpenWorker reuse/failure conformance 属于本阶段的客户端 Gate：

- Agent-visible 与 prefetch 模式调用同一 `milai_memory_resolve` kernel semantics；
- M1 已通过的 single-turn 与 fresh-resolve second-turn 继续 PASS；
- receipt reuse 不改变 generic MCP 与 OpenWorker 的 Gate/StateView semantics；
- MCP/Runtime unavailable 不被 Host 改写为 no-memory；
- Host 不建立第二套 canonical truth。

第一版只做在线验证的 `ContextReceipt`；不实现 portable offline CURRENT lease 或 push invalidation。

## M4 — Query-aware Bounded Search

状态：`GATE PASS / 2026-08-26`

交付顺序：

1. `POSSIBLE` intent 的 low-cost bounded probe；
2. current-state query 已由 M2 exact path 截流，不默认宽 `recent_canonical`；
3. principal/scope/project/entity/time/type hard partition；
4. temporal/FTS first；
5. filtered vector only on sparse insufficiency；
6. conditional top-10～30 reranker；
7. query-type evidence sufficiency stop；
8. lazy hydration 与 explanation/evidence recovery；
9. raw/lexical/semantic/temporal projection keys 分离；
10. reconstructive L2 继续 parked，除非简单路径出现稳定 failure slice。

每一 stage 记录 candidate universe、耗时、budget、escalation 与 stop reason。质量 non-inferior 与候选/延迟/token 改善必须同时报告。

不优先更换 embedding、vector DB 或引入 Neo4j/DAG。

## M5 — Governed Lifecycle 与 Incremental Projection

状态：`GATE PASS / 2026-08-26`

目标：闭合 MCP governed write product lifecycle，并把 projection 维护从 canonical transaction 中分离为可重放 delta。

治理交付：

```text
submitter captures Evidence
→ proposes operation
→ independent reviewer approves/rejects
→ immutable ClaimVersion / OpenIssue transition
→ reader resolves updated StateView
→ operator revoke/delete/forget lifecycle
```

- 实现最小权限 `reviewer` MCP profile 与 `milai_memory_review`；不挂普通 model catalog；
- submitter/reviewer actor 不得自批；
- correction/supersede/conflict/revoke/delete 各有真实 PostgreSQL E2E；
- product mutation intent 映射 frozen operations，不新增同义 canonical tables；
- revoke 同步 fail closed，purge 与 projection cleanup 异步。

物化交付：

- governed write、fragment、embedding、projection write/index 分段计时；
- delta outbox / set-based micro-batch；
- per-projection watermark；
- restart/rebuild 与 incremental update 分开；
- projection down 不影响 exact canonical correctness；
- 不把 evaluation same-lease reuse 写成产品 persistence。

## M6 — Optional Task Enhancement

状态：`GATE PASS / 2026-08-26`

目标：只把 Task 作为可选效率/精度增强，不恢复 Host-gated Memory reachability。

候选能力：

```text
TaskContext scope narrowing
known StateKey hints
project/workspace/artifact ranking prior
task-bound ContextReceipt reuse
non-authoritative action-risk classification hint
```

TaskContext 永远不能授予 action authority。Action-sensitive output 仍必须由 ECS 的明确 `ACTION_SAFE`、无 live issue/block，以及新鲜、内容绑定、可读且未撤销的 `USER_CONFIRMATION` Evidence 共同通过最终 Gate。

任何 Task enhancement 必须通过 task-on/task-off matched ablation 证明：

```text
precision improves
or latency/candidate/token cost decreases
while task-free correctness remains non-inferior
```

Task 缺失时仍必须 fresh EXACT/SEARCH。learned Task resolver 默认不实现；ambiguous classifier 只在真实 failure slice 证明必要时进入 M7。

M6 实际选择最小可证子集：project scope narrowing、entity/type hard-partition hints 与
non-authoritative action-risk trace。known StateKey Task hint、project/workspace/artifact learned
ranking、task-bound protected ContextReceipt 没有足够 failure slice，继续不实现；task-free
receipt 仍只覆盖其有效的 Runtime request constraints。

## M7 — Benchmark and Research

状态：`SEPARATE / NOT PRODUCT CRITICAL PATH`

产品 regression 先覆盖 current/historical/update/temporal/conflict/abstention/evidence/deletion/rollback/scope/permission/workflow/gotcha。之后才执行 LongMemEval、LongMemEval-V2、Memora、HorizonBench、LoCoMo、外部项目 matched transplant、消融和 novelty protocol。

优先研究候选：

```text
Query Reachability:
  addressable vs reachable vs correctly-resolved

State-aware Progressive Retrieval:
  current/historical/conflict/explanation use different sufficiency

Dual-lane Memory:
  Canonical State lane + Raw Evidence lane

Semantically Covered Context Reuse:
  requirement coverage + dependency validity, not query-string equality
```

默认 PARK：graph、DAG tags、reconstructive L2、learned query router、portable lease、push invalidation、automatic forgetting。只有稳定 failure slice、matched mediator evidence 和 untouched confirmation 后，才另立产品 Goal。

DG-12 formal candidate、label 和 holdout 状态不因本 Goal 自动改变。

---

# 11. 测试与 Gate

## 11.1 测试所有权

| 层级 | Owner | 主要目的 |
| --- | --- | --- |
| Unit | Runtime/MCP/Python Client package | typed boundary、query plan、gate、profiles |
| Contract | MCP Server + Client | tools/list、schema、typed outcomes、capability isolation |
| Integration | MCP → Runtime → PostgreSQL | persistence、current/historical、governance、revoke |
| Client conformance | OpenWorker integration | provider-time use、multi-turn、socket/failure |
| Benchmark | evals | dataset mapping、quality/cost measurement；不拥有产品语义 |

## 11.2 M1 Gate

```text
G1 MCP catalog/profile              PASS
G2 milai_memory_resolve task-free   PASS
G3 CN/EN/mixed intent               PASS
G4 scope/authority/revoke           PASS
G5 restart persistence              PASS
G6 typed outcomes                   PASS
G7 generic client smoke             PASS
G8 real OpenWorker/vLLM single turn PASS
G9 same-session second turn reaches MCP PASS
G10 RetrievalTrace/access view complete PASS
G11 logical MCP call=1; automatic retry=0 PASS
G12 p95 non-regression vs declared M0 baseline PASS
```

## 11.3 M2 Gate

```text
MemoryStateView is derived, not stored truth PASS
current and historical bitemporal resolution PASS
canonical StateAddress resolution PASS
Addressable / Reachable / CorrectlyResolved separate PASS
OpenIssue exposed or blocks certainty per policy PASS
EXACT has zero LLM/embedding/vector/reranker/broad scan PASS
one logical MCP call PASS
```

## 11.4 M3 Gate

```text
valid receipt reuse                          PASS
head/issue/scope change invalidates reuse    PASS
receipt miss same-call primary route         PASS
Runtime unavailable remains REQUIRED         PASS
same semantics as generic MCP client          PASS
no second canonical truth in Host cache       PASS
```

## 11.5 M4 Gate

```text
POSSIBLE bounded probe has fixed cap/deadline               PASS
temporal/FTS precedes filtered vector where applicable      PASS
vector escalation reason recorded                          PASS
reranker is conditional and candidate-bounded              PASS
Gate precedes sufficiency                                  PASS
quality non-inferior within declared slice                 PASS
candidate count / p95 / context tokens improved            PASS
```

## 11.6 M5 Gate

```text
Evidence capture does not create Claim          PASS
Proposal remains pending before review          PASS
independent review is required                  PASS
approved CREATE visible to reader               PASS
SUPERSEDE creates immutable new version          PASS
CONTRADICT preserves OpenIssue semantics         PASS
revoke blocks stale read immediately             PASS
restart retains canonical state and lineage      PASS
delta projection watermark advances              PASS
projection failure does not change exact truth   PASS
```

## 11.7 M6 Gate

```text
Task omitted still reaches fresh EXACT/SEARCH        PASS
task-off correctness non-inferior                    PASS
TaskContext project/entity/type only narrows         PASS
disjoint Host scope is rejected                      PASS
action-risk does not grant authority                 PASS
matched candidate and context cost improve           PASS
reader-lite schema remains task-free                 PASS
```

## 11.8 安全回归

Release 前必须为零：

```text
WrongScopeAcceptance
StaleCurrentAcceptance
RevokedEvidenceReentry
UnauthorizedCanonicalWrite
SubmitterSelfApproval
CanonicalUnavailableFalseCertainty
```

常规开发报告实际 case count 和失败数即可；单侧置信上界、完整 provenance bundle 和独立审查只在 release/formal lane 生成，不作为每个 patch 的门。

---

# 12. 指标

## 12.1 可用性

```text
query-only vs Task-gated intent disagreement
task-free resolve success rate
SilentMemoryNeedNone
current-state accuracy
historical-state accuracy
abstention correctness
conflict/OpenIssue preservation
restart persistence success
governed write lifecycle completion
typed failure coverage
one-command smoke success
OpenWorker single-turn and second-turn MCP reachability
```

## 12.2 效率

```text
MCP logical calls / request
MCP decode/stdio/UDS/broker/kernel/SQL/hydrate p50/p95/p99
EXACT p50/p95/p99
SEARCH per-stage p50/p95/p99
candidate count per stage
SearchAvoidanceRate
FTS→vector escalation rate
vector→reranker escalation rate
context/result bytes and tokens
evidence ingest throughput
canonical commit latency
projection lag
incremental vs rebuild throughput
```

## 12.3 产品正确性与治理

```text
wrong-scope acceptance
stale-current acceptance
revoked re-entry
OpenIssue loss/false closure
unauthorized capability escalation
idempotency conflict correctness
version/head CAS correctness
trace→ClaimVersion/Evidence replayability
```

必须独立报告：

```text
StateAddressabilityRate
StateAccessReachabilityRate
StateAddressResolutionAccuracy
```

不再用一个 FastPath 指标混合“有地址”“计划到达地址”和“解析正确”。

---

# 13. 当前状态板

## Implemented

- Evidence/ClaimVersion/ClaimHead/OpenIssue/Canonical Gate/PostgreSQL core；
- L0、FTS、vector、Context、RetrievalTrace；
- MCP stdio server 和 profile-based tool catalog；
- task-free `milai_recall(query)` public contract；
- Evidence capture、Proposal create、Evidence revoke MCP tools；
- OpenWorker hidden-prefetch precursor；
- real local vLLM 单轮 answer path；
- 1093-test DG13U owning regression gate；
- task-free `milai_memory_resolve` 及 OpenWorker same-session fresh-resolve；
- 动态 `MemoryStateViewService`、canonical `StateAddressService` 与 0030 bitemporal Gate；
- Runtime/Python Client/MCP `milai_memory_get` StateKey/ClaimID current/historical exact read；
- Addressable/Reachable/CorrectlyResolved、exact structural cost 与 StateAddress SQL span；
- `ContextReceiptService` 在线 reauthorization、coverage/dependency/currentness 校验；
- receipt miss/expired/head/OpenIssue/scope change同调用回到 primary EXACT/SEARCH；
- Python Client/MCP/OpenWorker 显式 `previous_context_id` locator 与 typed unavailable/denied。
- Runtime-owned `MemoryAccessPlanner`、`QueryPlan v10` 与 candidate/deadline/context/reranker 上限；
- query-aware progressive retrieval、Gate-before-sufficiency、sparse-only vector escalation 与
  conditional small-set reranker；
- tenant/principal/project/entity/time/type ranking-before hard partition 及 PostgreSQL statement deadline；
- whole-item context budget，超限时 typed abstention，不截断 canonical value。
- reviewer-only pending inbox / inspect / approve-reject MCP lifecycle，以及独立
  submitter/reviewer Runtime actor 与互斥 capability；
- governed CREATE/SUPERSEDE/CONTRADICT/reject/revoke/delete 的真实 PostgreSQL 纵向闭环；
- transactional delta outbox、set-based delivery admission、per-projection watermark、embedding
  micro-batch stage metrics，以及不改 canonical truth 的 incremental/rebuild replay。
- detail-profile optional TaskContext project/entity/type narrowing 与 non-authoritative action-risk
  trace；task-off/reader-lite 继续保持无 Task schema 与 query-first reachability。
- `0032_reviewer_actor_separation` canonical procedure actor-separation、reviewer-only Proposal
  inspection，以及 product `agent-config` 的 reviewer profile / automatic retry `0` 默认值；
- operator start→smoke→report→cleanup 与最终 regression/secret/contract release disposition。

## Partial

- TARGET `milai_memory_explain/capabilities` 及后续 tool family 的完整 vNext 命名迁移；
- Runtime-owned QueryMemoryIntent 与 deterministic `MemoryAccessPlanner` 已进入在线 read kernel；
- Memory Application Kernel in-process MCP invocation；CURRENT 仍有 client/loopback/broker composition；

## Residual scoped limitations

- DG-12 speed targets terminal miss 是已记录的范围限制；不得补发 speed claim，也不由 DG-13
  scoped product closure 改写。

## Parked

```text
Direct/HTTP external product parity
portable offline lease
push invalidation
learned Task resolver
graph truth store
DAG tags
reconstructive retrieval agent
remote/multi-agent governance
formal novelty claims
```

`ContextReceipt` 的在线验证属于 M3，不在 parked 集；离线可携带 CURRENT lease 继续 parked。

---

# 14. Definition of Done

DG-13 Core 只有在以下全部成立时才算完成：

1. 一个普通 MCP Client 可从 clean local setup 发现并调用 MiLA；
2. `milai_memory_resolve` 只凭 authenticated principal + query 即可进入 Memory path；
3. Task 完全省略时 current/historical/absent/conflict retrieval 仍正确；
4. Query interpretation、AccessPlan、StateView 与 progressive retrieval 由 Runtime 拥有；
5. MemoryStateView 从 Canonical Core 动态解析，没有第二 truth store；
6. Addressable、Reachable、CorrectlyResolved 分别计量；
7. Exact 满足零 LLM/embedding/vector/reranker/broad scan；
8. ContextReceipt miss/changed dependency 在 same call 回到 primary route；
9. Search 有 candidate、deadline、token 和 escalation 边界；
10. typed failure 不把 unavailable、absent、denied、contested 混为 `UNKNOWN` 或 `NONE`；
11. capture→proposal→independent review→canonical update→recall 闭合；
12. correction/supersede 产生 immutable new version；challenge 保留 OpenIssue；
13. revoke/forget 同步 fail closed，stale projection 不 re-enter；
14. MCP client/server 重启不丢失 Runtime canonical memory；
15. 一条 operator-facing 命令完成 start→smoke→report→cleanup；
16. OpenWorker 使用同一 MCP semantics 完成单轮和真实第二轮对话；
17. 当前声明范围内测试和至多一次独立 release review PASS；
18. 日常开发没有把重复审计资产作为 behavior change 前置；
19. 没有修改 frozen DG-12 candidate 或依赖 formal holdout；
20. Runtime/Schema 仍准确标记 `CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。

允许的 scoped release label：

```text
DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE
```

它不等于：

```text
Production ready
Remote MCP ready
Real personal data approved
Schema frozen
General SOTA retrieval
Paper claim confirmed
```

---

# 15. 当前唯一下一执行清单

按顺序执行：

```text
[x] M0-1 冻结 CURRENT→TARGET tool compatibility mapping，不复制实现
[x] M0-2 补齐 RetrievalTrace，并生成非持久 AccessTrace view 与阶段 latency
[x] M0-3 shadow 对比 query-only intent 与 Task-gated Need；不改变行为
[x] M0-4 建立 generic task-free MCP smoke 与主产品 OpenWorker composition CI
[x] M1-1 实现最小 milai_memory_resolve：principal + query + optional hints
[x] M1-2 单项验证中文、英文、中英混合及 typed outcome
[x] M1-3 generic client PASS 后，用同一合同完成 OpenWorker→vLLM 单轮与 fresh-resolve 第二轮
[x] M2-1 实现动态 MemoryStateViewService；不建 authoritative StateView 表
[x] M2-2 实现 canonical StateAddressService + exact StateKey/Claim hot path
[x] M2-3 分别报告 Addressable / Reachable / CorrectlyResolved 与 exact 成本
[x] M3-1 实现 ContextReceipt 鉴权、coverage/dependency/currentness 校验
[x] M3-2 receipt miss/expired/head或issue变化时同一次调用回到 EXACT/SEARCH
[x] M3-3 闭合 REQUIRED unavailable/denied/insufficient typed availability
[x] M4-1 实现 POSSIBLE bounded probe 与固定 candidate/deadline/token cap
[x] M4-2 证明 temporal/FTS 优先、filtered vector 条件升级与 bounded rerank
[x] M4-3 运行 matched quality/cost non-inferiority Gate
[x] M5-1 实现独立 reviewer profile、canonical Proposal inspect 与 approve/reject
[x] M5-2 证明 submitter/reviewer actor 分离及 CREATE/SUPERSEDE/CONTRADICT/revoke/delete 闭环
[x] M5-3 证明 delta projection watermark、failure isolation、incremental/rebuild replay
[x] M6-1 实现只能收窄 scope/candidate 且不能授予 authority 的可选 TaskContext hint
[x] M6-2 运行 task-on/task-off matched correctness/candidate/token/latency ablation
[x] M6-3 回归证明 Task omitted 仍进入 fresh EXACT/SEARCH 且 ordinary client 不依赖 Host Task
[x] R-1 运行单一 operator-facing start→smoke→report→cleanup 闭环并核对 DoD
[x] R-2 运行最终声明范围 regression/secret/contract check，形成 release disposition
```

前三个实现单元冻结为：

```text
M0 RetrievalTrace-backed AccessTrace view + query-only shadow
→ M1 task-free milai_memory_resolve
→ M2 MemoryStateView + Exact State hot path
→ M3 online ContextReceipt + same-call fallback + typed availability
→ M4 query-aware bounded Search + hard partitions + bounded Context
→ M5 governed MCP lifecycle + independent reviewer + incremental projection
→ M6 optional TaskContext narrowing + matched non-inferiority/cost ablation
```

M6 Gate、R1/R2 与本轮唯一独立 release review 均已通过；DG-13 scoped product closure 完成。
M7 benchmark/research 不属于该 release，也不作为本次 closure 前置。

当前禁止：

```text
继续扩建 Host Task Runtime 来证明 MiLA Core
让 Task 缺失阻断 informational recall
为 Direct/HTTP/offline lease/push 提前建抽象层
先换 embedding/vector DB
先接 Neo4j/OpenViking/Hindsight/Graphiti/Mem0 production backend
先跑大规模 formal benchmark
用重复审计/manifest 数量代替真实 MCP product smoke
失败后 broad rerun、自动 retry、延时放宽或 catch-all UNKNOWN
```

## 15.1 M2 实施反思与改进

1. 初版历史 Gate 只按 `known_at` 选择 ClaimVersion，却复用了当前 ECS OpenIssue 状态；这会让
   后来出现的冲突污染过去视图。修正为从 append-only `open_issue_transition` 重建时点状态，
   同时继续让 revoke/retention/permission 对历史读取 fail closed。
2. 初版 exact trace 将 StateAddress SQL 包含在 MCP 总耗时，却没有计入 Runtime
   `repository_sql_ms`。修正为有序 `state_address_resolution_ms → EXACT` stage，并在持久
   RetrievalTrace/AccessTrace 中报告独立 span。
3. 初版 resolve 允许多个 exact target 或 temporal target 缺失时静默回到 L1。修正为请求层
   fail closed：M2 每次只接受一个 canonical target，`valid_at/known_at` 必须绑定该 target，
   RYW/causal token 与 ACTION_SAFE scope 也在入口校验。
4. 全量测试首轮漏绑定 owner migration URL，形成跨库读写的伪失败；测试命令现固定同时绑定
   owner/API/Steward/Worker/Audit 五个角色 URL。另一次临时库名被安全前缀检查拒绝后，改用
   `milai_smoke_` 受控前缀，未绕过保护。

M2 以后继续采用单项实现、单项测试、fresh database/real MCP 最短纵向闭环，不用 broad retry
掩盖边界错误。

## 15.2 M3 实施反思与改进

1. 初始方案考虑直接复用含 protected Active Goal/constraints 的 task-bound capsule，
   但这会把 Host state 带入 task-free Memory 合同。修正为在既有
   `ContextCapsule` / `ContextPointer` 上使用固定 task-free protected-section 形状；
   不建新 receipt 表，也不允许 task-bound capsule 进入该路径。
2. 仅检查 receipt 中已有 ClaimVersion 的 head/dependency digest，会漏掉“新写入了一条
   对当前 query 有关的 Claim”。第一版因此同时要求 canonical position 未前进；
   这是保守 invalidation，但保证新候选不被旧 receipt 遮蔽。以后只能用能证明
   query coverage 完整性的依赖索引放宽，不能用 TTL 放宽。
3. `READ_YOUR_WRITES` 需要重放 causal token 并等待当轮位置，所以 receipt 对 RYW
   不能直接命中；实现将其视为可解释 miss，并在同一调用进入 primary route。
4. 为制造 canonical `DENIED` fixture，曾尝试提交不可读 Evidence，写入面正确返回
   `409`；尝试修改已接受 Evidence permission 又被 immutable trigger 拒绝。没有为测试
   绕过这两道治理不变量；`DENIED` 由 MCP scope/capability boundary 与 Runtime typed
   mapping 测试证明，真实 canonical flow 继续保持“不可读 Evidence 不能成为可接受
   grounded Claim”。
5. MCP 初版只在 tool schema 增加 `previous_context_id`，但 strict allowlist 仍会拒绝它。
   修正后 schema 与 execution allowlist 由同一 contract test 同时锁定，避免“可发现但不可调用”。
6. Runtime 全量 Gate 的首次失败是旧 contract test 仍断言 `context_receipt is None`。
   这不是行为回退；更新断言以检查新的可验证 wire contract，并用 fresh database
   重跑全量 Gate，没有放宽 Runtime 逻辑。

M3 后续强制使用“locator 不是 authority”的命名与测试；任何 reuse 命中都必须产生
当轮 `REUSE_VALIDATION`，miss 产生可解释 fallback，Runtime 不可用时不得离线声称 CURRENT。

## 15.3 M4 实施反思与改进

1. 既有 L1 已有“候选 → Gate → sufficiency”骨架，但 candidate limit 由内部
   heuristic 隐式扩张，没有请求级 deadline 和 Context 上限。修正为 Runtime-owned
   `MemoryAccessPlan`，并把计划与实际消费同时写入 trace，避免“有 limit 参数”被误当成
   整条 search 已有界。
2. entity 硬分区初版把 entity 直接等同于 canonical `subject_id`，真实 PostgreSQL
   fixture 中 entity 实际位于 payload，造成合法结果假阴性。修正为在 subject/predicate/type/
   canonical payload 的规范化内容上做 literal `strpos` 存在性过滤，不引入 wildcard 语义；
   exact、FTS、vector 和 fallback 用同一分区合同，并以 fresh-database regression 锁定。
3. matched smoke 初版 query 含 `current`，Query Planner 正确生成 LATEST_VALID_STATE operator，
   因而不应在第一个 FTS 结果后停止。没有削弱 temporal operator safety；改用不含
   显式 temporal operator 的 informational matched slice 专门验证 FTS stop。
4. smoke 的第一个 fixture 使用 `ACTION_SAFE`，Gate 正确要求走完更强候选链，
   不适合证明 informational early-stop。保留 fixture 的高 authority，但将读取要求设为
   `INFORMATIONAL`；没有为性能 Gate 放宽 action-safe 权威规则。
5. deadline 实际传入 candidate generation 与 Canonical Gate 的 PostgreSQL statement；
   timeout 转为 `SEARCH_BUDGET_EXHAUSTED` 并停止后续 vector。trace/audit/hydration 仍可产生
   deadline 外的收尾开销，因此 trace 同时报告 Runtime 总耗时和 search deadline outcome，
   不将两者混为一个数。
6. Context budget 采用保守 UTF-8 byte count 作 tokenizer-independent token upper bound；
   只选择完整 Gate-accepted item。首项已超限时返回 typed
   `CONTEXT_TOKEN_BUDGET_EXCEEDED`，绝不截断 canonical value 后伪装成完整事实。
7. 首轮 Runtime full gate 的唯一失败是测试把 reranker cap `20` 误写成固定配额，
   而实现在当轮 candidate cap 仅 `12` 时正确收紧为 `12`。修正为
   `min(20, candidate_cap)` 上限断言，没有扩大实际 reranker 工作量；二次 fresh gate 通过。

## 15.4 M5 实施反思与改进

1. Runtime 已有 Proposal review/StewardDecision、transactional projection outbox、per-projection
   watermark 和 rebuild 过程；M5 复用这些 canonical owner，没有为 MCP 再建 Proposal、Claim、
   审核或 projection 状态表。release review 后发现 canonical procedure 仍允许同 actor 自批，
   因此增加 `0032_reviewer_actor_separation` wrapper migration；它不新增业务表，并撤销对被包装
   旧 procedure 的 Runtime role 执行权。
2. 初始 Agent auth 把 reviewer 配成全 capability，并把所有命名 token 映射为同一个 local
   actor；仅靠不同 token 不能证明独立审批。修正为 reviewer 最小
   `memory:read + proposal:review`，并由 local actor namespace 对每个命名 profile 派生稳定且
   不同的 actor；legacy 全能力 local admin 仅保留兼容，不进入产品 Gate。
3. 第一版 smoke 能用 opaque Proposal ID review，却没有证明 reviewer 看过 canonical pending
   内容，形成 blind approval 风险。增加 reviewer-only `milai_proposals_list` /
   `milai_proposal_get`，并要求每次 review 前真实读取该 Proposal；review decision 与 confirmation
   不一致时在发出 Runtime 请求前拒绝。
4. 独立审批不能只靠测试约定。MCP catalog 让 submitter/reviewer capability 互斥，Runtime 再拒绝
   proposer actor 自批；真实 smoke 对 CREATE、SUPERSEDE、CONTRADICT、REJECT 和 revoke fixture
   涉及的 `5/5` 个 StewardDecision 直接检查 proposer/decision actor 不同。
5. 既有 worker 已实现 outbox set-based admission cap `128`、fragment embedding batch、独立
   watermark 与 rebuild/retry。M5 选择用实际增量、失败、恢复、rebuild 和 purge 序列证明这些
   能力，而没有复制一套“更现代”的 materialization 框架。
6. 故意配置无效 embedding provider 后 worker 非零退出，属于 projection availability failure，
   不代表 canonical transaction 失败；在失败窗口 exact current 仍正确，恢复后 watermark 前进。
   这把“derived 暂不可用”和“canonical 不确定”分开，避免为可用性 smoke 放宽 Gate。
7. smoke 的每次调用都新建 stdio MCP process/session，刻意证明进程重启不丢 canonical state；
   因此其中 call timing 包含启动成本，只作为 lifecycle 观察值，不声明 steady-state 延迟。
8. release review 发现 Proposal list/get 原先复用普通 `memory:read`，会让非 reviewer 看见完整
   patch/evidence。修正为 `proposal:review`，并在真实 HTTP/DB negative 中锁定 reader、submitter、
   operator 的 list/detail 拒绝；同一测试还锁定 same-actor review `403` 后零 Decision 残留。
9. lifecycle smoke 的故障步实际是无效 provider 配置导致 worker 启动失败，不是处理中的 provider
   故障；文档据此降格为 startup isolation，并与独立的 incremental/rebuild replay 证明分开。

## 15.5 M6 实施反思与改进

1. 第一版为了显式说明 task-off，仍在无 Task 请求的响应中加入
   `task_enhancement.present=false`。fresh full gate 中既有安全测试正确要求整个 task-free
   响应连 Task-shaped 字段都不存在；修正为只在 caller 实际提供 TaskContext 时返回增强 trace，
   task-off wire shape 完全保持 M1–M4 合同。新库二次 full gate 通过。
2. project/entity/type 求交若得到空列表后直接送入现有查询，会把“空约束”解释成“无分区”，
   反而扩大搜索。实现没有使用这种 silent intersection；TaskContext 与 Host-bound constraints
   完全不相交时入口 `400 INVALID_REQUEST`，部分重叠时只保留交集。
3. M6 没有接受 `task_id/session_id/active_goal`，也没有建立 Task 表。有效请求只把收窄后的
   scope/entity/type 送入原有 Runtime planner、RetrievalTrace 和 Canonical Gate；已有 task-free
   receipt 只覆盖这些 Runtime request constraints，不声称 task-bound protected capsule reuse。
4. `action_risk` 只形成 `ACTION_RISK_OBSERVED_NO_POLICY_EFFECT` trace；matched task-on/off 的
   RetrievalTrace 直接比较 required authority 一致。没有让 `HIGH` 风险自动获得 ACTION_SAFE，
   更没有替代 USER_CONFIRMATION Evidence 与 ECS 最终 Gate。
5. 两次直接运行 integration 单项最初分别因 cwd 下找不到 `alembic.ini`、未加载多角色 DB URL
   而停在 fixture setup；没有为方便而连接默认库。将验证移入受控 fresh-database runner，
   每次从空库迁移并自动 drop；正式 full gate 也使用同一清库机制。
6. matched smoke 在同一个真实 MCP process/session 中交替 arms，避免把进程启动差异当成
   Task 收益。最终 Gate 由 quality non-inferior 加 candidate/context 两项结构性改善拥有；
   同时报告 p95，但不把这个小型 synthetic slice 宣称为通用延迟结论。
7. 候选列表中的 known StateKey Task hint、workspace/artifact learned prior 和 protected
   task-bound receipt 没有稳定 failure slice，因此没有为了“做满列表”实现。M6 只交付可以由
   matched 消融证明的最小 narrowing 子集，M7 仍是独立 research lane。
8. release review 增加 defense-in-depth：ContextReceipt 存储 outcome 时显式丢弃
   `task_enhancement`，并让 task-on 签发的 receipt 在等价 task-off 请求中真实复用；复用响应仍
   完全没有 Task-shaped 字段。最终 M4/M5/M6 报告均绑定并核对当前相关源码 SHA-256，避免旧
   PASS 报告替新源码背书。

---

_Last updated：2026-08-26 · M0–M6、R1/R2、independent release review PASS；scoped label earned；Runtime/Schema 仍为 CANDIDATE / EXPERIMENTAL / NO-GO._
