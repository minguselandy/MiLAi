# MiLAi 可用性与 Agent 接入设计开发文档 v1

> 文档版本：`0.1.0 DESIGN CANDIDATE`  
> 编制日期：`2026-08-17`（Asia/Shanghai）  
> 目标版本：`MiLAi Agent Integration Beta`  
> Logical Architecture：`1.0.0 FROZEN / INDEPENDENT RELEASE PASS`  
> Runtime：`0.1.x CANDIDATE`  
> Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> 当前数据边界：`synthetic/de-identified only; real personal data denied`  
> 文档性质：实施设计与开发路线，不创建新的 frozen architecture，也不修改 G1～G9、I-01～I-12

---

# 0. 执行结论

MiLAi 当前不是“只有设计、没有实现”的项目。它已经具备本地 Flask API、PostgreSQL/pgvector、
后台 Worker、Evidence/Claim/OpenIssue 治理、Canonical Gate、ContextCapsule、Chat、撤销、追溯和
备份恢复的候选 Runtime。当前真正阻碍使用的不是 canonical core 缺失，而是以下产品化与接入层缺口：

1. 首次启动依赖手工创建 `.env`、生成多组 secret、启动多个进程，缺少安全 bootstrap 和 doctor；
2. 只有底层 REST API，没有稳定的 Agent-facing SDK、能力发现和兼容性合同；
3. 没有 MCP Server，也没有 LangGraph、AutoGen 等框架薄适配；
4. 当前 `/v1/chat` 是确定性答案拼装器，embedding 是测试替身，不代表通用模型质量；
5. 当前一个本地 Bearer token 的 API 面过宽，不适合直接交给模型或多 Agent；
6. Blob encryption/key rotation/recovery 尚未实现，不能导入真实个人数据；
7. Schema 仍在演化，0015～0026 是 forward-only 安全迁移，客户端不能依赖数据库结构。

本设计作出以下决定：

```text
不把 ReMe、Hindsight、Graphiti、Mem0 或 OpenViking 变成 MiLAi canonical backend。

在现有 Runtime 外新增独立 Agent Integration Plane：

Agent Framework
→ lifecycle hook / native adapter / MCP / Python SDK
→ typed Agent Facade
→ existing MiLAi REST API
→ Canonical Gate / governed Proposal path
→ PostgreSQL Canonical Core
```

目标不是让模型拥有“直接修改记忆”的能力，而是建立三个严格分离的能力面：

```text
Recall Plane       自动读取 Gate 后的记忆与 OpenIssue
Observation Plane  记录用户/工具的真实观察为 Evidence
Governance Plane   Agent 只提交 Proposal；人类或独立 Steward 才能批准 canonical 变化
```

第一阶段先达到 `Local Developer Ready + Single-Agent Integration Ready`；真实个人数据必须等
ADR-012 crypto gate 完成后才能进入 `Local Private Beta`。公网、多租户和多 Agent canonical
arbitration 不属于本设计的近期交付。

---

# 1. 规范关系与边界

## 1.1 规范优先级

本文件服从以下规范，不覆盖其语义：

1. `architecture/v1.0/` frozen Logical Architecture；
2. `MiLAi_Logical_Architecture_v1_设计文档.md` frozen MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. `MiLAi_Lean_V1_产品底座与研究核心.md`；
5. 本文；
6. 实验性 adapter、示例和代码注释。

若接入层需要改变对象身份、canonical writer、权限、删除语义、事务原子性或 I-01～I-12，必须先
提交 ADR、crosswalk 和新架构版本；不能用“兼容某个 Agent 框架”作为绕过 frozen invariant 的理由。

## 1.2 本文允许做什么

- 改善本地启动、诊断、示例、文档和 UI；
- 为现有 `/v1/*` API 建立稳定、typed 的客户端合同；
- 新增不持有数据库凭据的 Python SDK、MCP adapter 和框架薄适配；
- 新增 Agent 生命周期 hook；
- 新增能力发现、调用者 trace metadata 和最小 capability scope；
- 增加真实 provider 的可移除 adapter，并建立新 projection version；
- 使用本地下载项目和 benchmark 做隔离对照；
- 完成 ADR-012 后，在独立 gate 下推进真实数据 Local Private Beta。

## 1.3 本文禁止做什么

- 外部 memory engine 或 Agent 直接 DML canonical tables；
- Agent 自动批准自己的 Proposal；
- 将模型回答、摘要、向量命中或 MCP tool output 自动提升为 Evidence/Claim truth；
- 用 framework thread/checkpoint ID 替代 MiLAi Claim/Evidence/OpenIssue ID；
- 在模型上下文中暴露数据库密码、Steward credential、API token 或 causal secret；
- 为了兼容 `memory.update()` 原地覆盖 ClaimVersion；
- 为了兼容 `memory.clear()` 实现无确认的批量删除；
- 在 crypto、remote-access 和真实数据 gate 前导入真实个人数据或公网暴露服务；
- 把 OSPC 作为产品依赖重新接入；其 novelty 已按 hard falsifier 放弃。

---

# 2. 当前可用性基线

## 2.1 已有能力

当前 Runtime 已实现：

```text
Evidence ingest/revoke
DeriveAndDiagnose deterministic validation
OperationProposal + StewardDecision
Claim / immutable ClaimVersion / exact-head CAS
structured OpenIssue + branch relation + discharge rule
L0 exact + L1 FTS/pgvector retrieval
Canonical Gate + RetrievalTrace
protected ContextCapsule
traceable deterministic Chat
Episode capture / governed Settlement
Outbox / Worker / watermark / purge
backup / restore / deletion reconciliation
real PostgreSQL roles and forced RLS
```

`docs/reports/GOALS-completion-audit-2026-08-17.md` 将当前完整 Runtime bytes 绑定到真实 PostgreSQL
`121/121` 测试结果。本文调研时再次执行非 integration 套件，结果为 `34 passed`，Ruff、format 和
strict mypy 均通过。

## 2.2 调研时的实际运行状态

在 `2026-08-17` 当前工作区：

```text
runtime/.venv       present; Python 3.11.13
uv                  present; 0.8.3
runtime/.env        missing
Compose config      fail-fast because required passwords are absent
127.0.0.1:18080     no API process listening
```

因此“代码候选可运行”和“当前实例正在提供服务”必须分开表述。本文要关闭的是从干净 checkout 到
可诊断实例、从 Agent 到 typed memory contract 之间的工程距离。

## 2.3 当前质量边界

| 能力 | 当前状态 | 接入影响 |
| --- | --- | --- |
| Logical Architecture | `1.0.0 FROZEN` | 接入层不能改变 canonical 语义 |
| Runtime correctness | Candidate，synthetic PostgreSQL 全套通过 | 可以建立受控本地集成 |
| Schema | Experimental / forward repair | SDK 必须屏蔽数据库结构和 migration revision |
| Answer composition | deterministic renderer | Agent 框架自己的 LLM 负责生成 |
| Embedding | 16 维 deterministic hash | 只适合测试；语义质量未成立 |
| CommitPolicy | 自动提交关闭 | 所有 Agent Proposal 进入 review |
| Authentication | 单本地 token + configured actor | token 不能进入模型；多 Agent identity 未成立 |
| Blob privacy | plaintext local blob；crypto gate 未实现 | 禁止真实个人数据 |
| Network | loopback only | HTTP MCP remote transport暂不开放 |
| License | MiLAi 尚无公开分发 license | adapter/package 仅作本地候选，不能默认公开发布 |

---

# 3. 相关项目调研

## 3.1 调研方法

调研使用两类证据：

1. 工作区本地源码快照：核对真实版本、tool schema、hook、client 和 MCP 实现；
2. 截至 `2026-08-17` 的官方仓库、官方文档和 MCP 规范：复核当前接口与协议变化。

外部项目更新很快。本文只冻结设计判断，不把网页中的 `latest` 当依赖锁；实际实现必须记录准确
commit、package version、license、lock hash 和本地 patch hash。

## 3.2 本地项目资产

| 项目 | 本地身份 | 可借鉴能力 | 不可照搬语义 |
| --- | --- | --- | --- |
| Mem0 | `2.0.18`；commit `001c235229be8795e3834520467bd0d661ed8f34`；Apache-2.0 | add/search/get/list 工具面，user/session/agent scope，Codex/MCP/plugin lifecycle hook，async event status | 模型主动 add、原地 update、直接 delete 不能等于 canonical mutation |
| Graphiti | `0.29.3`；commit `401c59a65bdeb22a44136901ff30231e6998a7fe`；Apache-2.0 | Episode provenance、双时间、图检索、MCP stdio/HTTP、group scope、异步 ingestion | graph fact/invalidation 不能直接 supersede Claim；图数据库不能成为唯一事实源 |
| ReMe | snapshot `0.4.1.6`；无 Git metadata；Apache-2.0 | pre-reasoning hook、上下文压缩、tool result offload、可读文件、FastMCP job exposure | auto memory/dream 和文件路径不能创建 canonical truth |
| Hindsight | snapshot packages `0.9.0`；无 Git metadata；MIT | retain/recall/reflect 分离、bank isolation、多路召回、token budget、harness-agnostic Agent SDK、operation polling | extracted world fact、mental model、reflect answer 不能自动成为 Claim |
| Benchmarks | BEAM、CUPID、HorizonBench、LongMemEval/V2、Memora、PAHF | 长程记忆、更新、冲突、偏好、abstention、agent task success | benchmark schema/答案不能回写产品状态 |

本地 `ReMe/` 与 `hindsight/` 缺少 Git metadata。它们可以继续作为源码参考，但任何正式 baseline 都
必须先生成 snapshot manifest；不能只写版本字符串。

## 3.3 Web-only 参考

### OpenViking

OpenViking 的官方设计将 Resource、Memory、Skill 统一在层级 `viking://` 命名空间，提供目录递归
检索、可观察路径、session commit 后异步抽取，以及内建 HTTP MCP endpoint。值得借鉴：

- Resource/Memory/Skill 类型分离；
- L0/L1/L2 层级内容和 pointer 式读取；
- MCP 与 REST 共用服务能力，而不让每个 Agent 框架复制客户端；
- recall 的类型配额和字符预算；
- 资源上传使用短期、单次 token，而不是把长期 API key 暴露给模型。

不能直接采用其“session commit 后抽取结果进入 memory”的权威语义。OpenViking 还宣布从 `0.3`
起将主体切换为 AGPLv3，并对部分 CLI/examples 保留 Apache-2.0 例外；任何代码复用或生产部署前必须
单独做 commit 级 license review。当前不需要下载它作为 MiLAi Runtime 依赖。

### LangGraph

LangGraph 官方明确区分：

```text
Checkpointer = thread-scoped short-term execution state
Store        = cross-thread long-term application data
```

MiLAi 应当作为受治理的 long-term memory service，而不是替换 LangGraph checkpointer。LangGraph 的
interrupt/human-in-the-loop 适合承载 Proposal review，但 `Store.put()` 的原地 key-value 语义不能直接
映射到 ClaimVersion 写入。

### AutoGen AgentChat

AutoGen 提供 `Memory` protocol：`query`、`update_context`、`add`、`clear`、`close`。MiLAi 可以实现
兼容 adapter，但必须收缩语义：

- `query/update_context` 映射到 Recall + ContextCapsule；
- `add` 只能创建 Evidence 或 pending Proposal；
- `clear` 默认返回 `OPERATION_NOT_ENABLED`，不能映射成全量删除；
- `close` 只释放客户端资源，不修改 canonical state。

### Model Context Protocol

MCP 已成为跨 Agent framework 的最小公共接入面。官方 `2026-07-28` 版本引入 stateless core、
header-based routing、cacheable catalogs、MRTR 和授权强化；同时新版本发布不代表所有宿主已经升级。

MiLAi MCP adapter 必须：

- 使用官方 Tier-1 SDK，不自写协议栈；
- 协商协议版本，并保留至少一个已验证旧版本兼容矩阵；
- 默认使用本地 `stdio`，HTTP transport 继续绑定 loopback；
- tool list 根据 adapter profile/capability 固定且确定性排序；
- 所有输入 typed validation，所有输出结构化、限长、脱敏；
- 对写入、撤销等敏感操作保留 human-in-the-loop；
- 不依赖协议 session 保存 hidden authority，显式传递 trace/capsule/operation handle。

## 3.4 可吸收模式与拒绝项

| 来源 | 吸收进 MiLAi | 明确拒绝 |
| --- | --- | --- |
| Mem0 | 工具分类、scope UX、SessionStart/UserPrompt/Stop hooks、event status | proactive model write 成为事实；原地 update |
| Hindsight | retain/recall 分离、框架无关 tool factory、token budget、async handle | reflect answer 提升 authority；自动 extracted fact 成为 belief |
| Graphiti | Episode provenance、temporal candidate、MCP packaging、group filter | invalidation 直接改 Claim；默认图数据库依赖 |
| ReMe | before-reasoning hook、tool output offload、文件/pointer recovery、job→tool schema | auto-memory 直接写 canonical；文件名充当 identity |
| OpenViking | Resource/Memory/Skill 分层、hierarchical context、可观察 retrieval path | session extraction 直接成为 truth；未审计 AGPL 代码复制 |
| LangGraph | short/long-term 分离、interrupt review、节点注入 | 用 Store 替代 canonical core |
| AutoGen | Memory protocol adapter shape | `clear()` 直接批量删除 |
| MCP | 通用发现和调用、structured result、协议级兼容 | 将“工具可调用”误认为“工具已获治理授权” |

## 3.5 调研结论

没有一个相关项目同时提供 MiLAi 所需的 Evidence/belief 分离、append-only governance、OpenIssue、
authority、fail-closed deletion 和 Agent interoperability。最合理路线不是选一个替换 MiLAi，而是：

```text
以 MiLAi 保持 canonical authority；
吸收外部项目的接入形状、hook、MCP、budget 和可观察性；
外部项目继续作为隔离 baseline 或 future derived backend。
```

---

# 4. 目标、非目标与发布层级

## 4.1 目标

### U-01 可重复可启动

从干净 checkout 经一条受文档和测试约束的路径完成 secret 初始化、数据库启动、migration、role
attestation、worker/API 启动和 smoke test，不需要用户手写 SQL。

### U-02 可诊断

用户能够判断：配置、数据库角色、migration head、Blob root、Worker、projection lag、deletion gap、
provider 和 Agent adapter 哪一层不可用；诊断输出不得泄漏 secret 或正文。

### U-03 稳定客户端合同

提供 framework-neutral Python SDK、OpenAPI contract、typed error、retry/idempotency 语义和能力发现，
客户端不读取数据库表、不硬编码 Alembic revision。

### A-01 通用 Agent Recall

Agent 在每次推理前能够自动取得 Canonical Gate 后的 Claim、live OpenIssue、Evidence refs 和 trace；
当数据不足或 canonical unavailable 时得到明确 abstention。

### A-02 受治理写入

Agent 能记录真实用户/工具观察为 Evidence，并能提交结构化 Proposal；Agent 自己不能批准 Proposal，
也不能直接移动 ClaimHead、关闭 OpenIssue 或删除 canonical history。

### A-03 MCP 与原生框架适配

至少提供 MCP stdio、通用 function-tool wrapper、LangGraph reference node 和 AutoGen Memory adapter；
所有 adapter 复用同一 typed client，不复制业务规则。

### A-04 可评测、可替换

真实 embedding/provider、框架 adapter 和外部 baseline 都可拆除；每个回答和写入都能回放到请求、
trace、Evidence、Proposal 和决定。

### S-01 本地私密数据门

在 ADR-012 完成 envelope encryption、key lifecycle 和 backup recovery 后，才能把状态从 synthetic-only
提升为 Local Private Beta。

## 4.2 非目标

- 公网 SaaS；
- 家庭账号、跨设备 session；
- 多 autonomous Agent canonical arbitration；
- 自动 Scope Evolution 或 Profile/Pattern Promotion；
- Graphiti/OpenViking/Hindsight 在线 production backend；
- 通用 Agent framework 或模型路由平台；
- OSPC 论文候选；
- 在没有目标设备数据时冻结性能 SLA。

## 4.3 发布层级

| 层级 | 准入条件 | 可用数据 | 对外叙事 |
| --- | --- | --- | --- |
| `Developer Ready` | bootstrap/doctor/smoke、现有 core gates | synthetic | 可重复本地开发 |
| `Agent Integration Ready` | SDK、MCP stdio、hooks、framework smoke | synthetic/de-identified | 单可信 Agent 可接入 |
| `Local Private Beta` | crypto/key/backup、真实数据协议、脱敏与恢复 gate | approved local personal data | 本地私有试用 |
| `Remote Beta` | TLS/OAuth/session/device/rate limit/incident gate | separate approval | 本文不交付 |
| `Production` | Schema/API freeze、SLO、运维和安全审计 | separate approval | 本文不宣称 |

---

# 5. 目标架构

## 5.1 组件图

```text
┌──────────────────────────────── Agent Host ────────────────────────────────┐
│ LangGraph / AutoGen / custom loop / coding agent / MCP-capable client     │
│                                                                           │
│  short-term checkpoint     model/tool loop       user approval UI         │
└──────────────┬────────────────────┬────────────────────┬───────────────────┘
               │ native adapter     │ MCP stdio          │ review link
               ▼                    ▼                    ▼
┌──────────────────────── MiLAi Agent Integration Plane ────────────────────┐
│ lifecycle hooks │ framework adapters │ MCP adapter │ typed Python SDK      │
│ prompt-safe formatter │ capability profile │ retry/idempotency │ telemetry │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │ loopback REST; bearer held by host only
                                   ▼
┌──────────────────────────── MiLAi Runtime ─────────────────────────────────┐
│ Flask Agent/API Facade                                                    │
│ Evidence │ Proposal/Review │ Retrieval │ Context │ Trace │ Deletion        │
│                    Canonical Procedure / Canonical Gate                    │
└──────────────────────┬──────────────────────────┬──────────────────────────┘
                       │                          │ outbox
                       ▼                          ▼
             PostgreSQL/pgvector         one projection worker
             Canonical Core              + local encrypted blob store*

* encryption is mandatory only after Local Private Beta gate is passed.
```

## 5.2 关键边界

### Agent Host

- 拥有模型和 framework 的短期执行状态；
- 决定何时调用 recall，但默认由 before-model hook 自动 recall；
- 保管 MiLAi client credential，不把 credential 放进 prompt/tool result；
- 对敏感工具显示确认 UI；
- 将 MiLAi 输出作为 data，不作为 developer/system instruction。

### Integration Plane

- 没有 PostgreSQL DSN、migration owner 或 Steward DB credential；
- 只调用公开 REST contract；
- 做 schema translation、限长、错误归一和 framework glue；
- 不实现 ECS、authority、Scope 或 OpenIssue 的第二套规则；
- 不缓存可提升 authority 的当前状态；必要缓存必须带 trace、TTL 和 canonical position。

### Runtime

- 继续是唯一规则执行位置；
- Agent Facade 不创建第二套 canonical endpoint；
- 所有候选仍进入现有 Evidence/Proposal/Decision/procedure；
- retrieval/context 继续统一通过 Canonical Gate。

## 5.3 短期与长期状态分工

| 状态 | Owner | 例子 |
| --- | --- | --- |
| Agent thread/checkpoint | Agent framework | 当前 node、tool call、pending interrupt |
| Working context | MiLAi ContextCapsule 或 host state | active goal、constraints、Gate 后 memory |
| Observation | MiLAi Evidence | 用户声明、工具结果、文件读取 |
| Governed long-term belief | MiLAi ClaimVersion/OpenIssue | 经 review 的偏好、事实、冲突 |
| Derived search | MiLAi projection 或离线 backend | FTS/vector/graph candidate |
| Model answer | Agent host + MiLAi trace refs | 不自动成为 Evidence 或 Claim |

---

# 6. Agent-facing 稳定合同

## 6.1 合同层次

```text
Level 0  Existing /v1 REST primitives
Level 1  milai-agent-client typed facade
Level 2  lifecycle hooks and framework adapters
Level 3  MCP tool/resource exposure
```

所有 Level 2/3 只能调用 Level 1；Level 1 只能调用公开 REST API。禁止 adapter import
`milai.persistence` 或访问 Migration model。

## 6.2 能力发现

新增只读 endpoint：

```text
GET /v1/capabilities
```

建议响应：

```json
{
  "api_version": "1",
  "implementation_status": "CANDIDATE",
  "schema_status": "0.1.x EXPERIMENTAL",
  "data_mode": "SYNTHETIC_ONLY",
  "routes": ["L0", "L1"],
  "consistency_modes": ["EVENTUAL", "READ_YOUR_WRITES", "CANONICAL_REQUIRED"],
  "agent_profiles": ["reader", "submitter"],
  "features": {
    "context_capsule": true,
    "proposal_review": true,
    "auto_commit": false,
    "real_embedding": false,
    "encrypted_blob": false,
    "remote_access": false,
    "multi_agent_governance": false
  },
  "limits": {
    "query_chars": 2000,
    "max_results": 50,
    "max_evidence_bytes": 1048576
  }
}
```

该 endpoint 只报告运行事实，不以配置文案伪造 readiness。SDK 启动时执行兼容检查；不兼容应返回
`INCOMPATIBLE_RUNTIME`，而不是继续猜测字段。

## 6.3 Python Client

最低接口：

```python
class AsyncMiLAiClient:
    async def capabilities() -> CapabilityDocument: ...
    async def health() -> HealthStatus: ...
    async def recall(request: RecallRequest) -> RecallEnvelope: ...
    async def recall_exact(request: ExactRecallRequest) -> RecallEnvelope: ...
    async def build_context(request: ContextRequest) -> ContextEnvelope: ...
    async def get_claim(claim_id: UUID) -> ClaimEnvelope: ...
    async def list_open_issues(status: str | None = None) -> list[OpenIssueEnvelope]: ...
    async def get_trace(trace_id: UUID) -> RetrievalTraceEnvelope: ...
    async def capture_evidence(request: EvidenceCaptureRequest, operation_id: str) -> EvidenceReceipt: ...
    async def create_proposal(request: ProposalRequest, operation_id: str) -> ProposalReceipt: ...
    async def revoke_evidence(request: RevocationRequest, operation_id: str) -> DeletionReceipt: ...
    async def issue_causal_token(outbox_ids: list[UUID]) -> CausalToken: ...
    async def close() -> None: ...
```

同时提供同步薄包装，但异步实现是唯一逻辑源。

SDK 必须：

- 读取 `MILAI_BASE_URL` 与 host-owned token；
- 默认拒绝非 loopback URL，除非显式 remote gate 配置；
- 为每次调用生成合法 `X-Request-ID`；
- 写请求要求调用者提供稳定 `operation_id`，映射为 `Idempotency-Key`；
- 只对网络失败、429/503 和明确 retryable 错误执行有界重试；
- 写重试复用同一个 key 和完全相同的 canonical payload；
- 409 CAS/idempotency conflict 不自动改写请求后重试；
- 将 abstention 作为成功的安全结果，而不是异常；
- 关闭时清理连接池，不触碰 server state。

## 6.4 Recall Facade

Agent-facing request：

```yaml
query: string
scope: {}
authority: INFORMATIONAL | ACTION_SAFE | USER_CONFIRMED
consistency: EVENTUAL | READ_YOUR_WRITES | CANONICAL_REQUIRED
mode: HYBRID | EXACT
claim_id: optional UUID
limit: 5
byte_budget: 16384
include_open_issues: true
causal_token: optional string
```

SDK 将其确定性映射到现有 `/v1/memory/query`，必要时再调用 `/v1/context-capsules`。统一输出：

```json
{
  "status": "OK",
  "items": [],
  "open_issues": [],
  "retrieval_trace_id": "...",
  "context_capsule_id": "...",
  "consistency": "CANONICAL_REQUIRED",
  "canonical_position": 42,
  "degraded_components": [],
  "fallback": null,
  "abstention_reason": null
}
```

`status` 只允许：

```text
OK
DEGRADED
ABSTAINED
```

`ABSTAINED` 时 `items` 必须为空；adapter 不能把旧缓存或模型常识伪装成当前 MiLAi 记忆。

## 6.5 Model Context 格式

默认不把 raw Evidence 正文直接拼进 system prompt。SDK 提供结构化、限长的 formatter：

```text
<milai-memory-data trust="data-only" trace_id="...">
  ACTIVE STATE: ...
  OPEN ISSUES: ...
  EVIDENCE REFS: ...
</milai-memory-data>
```

规则：

- 该块位于 user/tool data channel，不得进入 developer instruction；
- Claim payload 中即使出现“忽略之前指令”也只能作为数据；
- live OpenIssue、authority、Scope、valid time 和 abstention 不得在 formatter 中丢失；
- raw pointer recovery 是显式、按需操作，必须重新校验 hash/permission/retention/revocation；
- formatter 记录实际 byte/token budget 和被省略对象 ID；
- 最小 protected context 超预算时返回 `CONTEXT_BUDGET_INFEASIBLE`。

## 6.6 Observation 与 Proposal

避免提供含混的 `memory.add(text)` 作为唯一写入口。SDK 分成：

```text
capture_evidence(...)  = 记录发生过的观察
create_proposal(...)   = 建议如何解释/更新 canonical belief
```

高层 helper `propose_from_observation()` 可以顺序执行二者，但必须返回两个独立 receipt：

```json
{
  "evidence": {"status": "COMMITTED", "evidence_id": "...", "outbox_id": "..."},
  "proposal": {"status": "PENDING_REVIEW", "proposal_id": "..."},
  "canonical_changed": false
}
```

Evidence 成功而 Proposal 失败不是事务损坏：观察仍然真实存在。SDK 必须公开 partial outcome，允许用
同一 operation IDs 恢复，不能删除 Evidence 伪装全局回滚。

## 6.7 Candidate Extraction

自然语言到 `ProposalCreateRequest` 的转换属于 adapter/model boundary，不进入 canonical transaction。
定义可选协议：

```python
class MemoryCandidateExtractor(Protocol):
    async def extract(
        self,
        observation: EvidenceReceipt,
        current: RecallEnvelope,
    ) -> list[ProposalDraft]: ...
```

每个 draft 必须通过本地 Pydantic schema 和 deterministic validator，并携带：

```text
model/provider identity
template version
input snapshot hash
supporting/contradicting Evidence refs
requested Scope and authority
expected ClaimHead when updating
```

Extractor 没有 review tool，也不持有 Steward credential。默认 `AUTO_EXTRACT=false`。

## 6.8 Consistency 选择

| 场景 | 默认模式 | 行为 |
| --- | --- | --- |
| 普通知识/偏好召回 | `EVENTUAL` | 允许 projection 落后，返回 watermark/degraded |
| 刚批准写入后的同一工作流 | `READ_YOUR_WRITES` | 用 outbox IDs 签发 causal token；超时走 canonical fallback |
| 行动、安全、权限、删除状态 | `CANONICAL_REQUIRED` | DB 不可用即 abstain/503 |
| 精确 Claim ID | L0 + `CANONICAL_REQUIRED` | 不依赖 embedding |

Agent adapter 不得用 L1 语义分数替代 authority 判断。

## 6.9 Error 与 retry 合同

| 类别 | 例子 | Adapter 行为 |
| --- | --- | --- |
| 安全结果 | `ABSTAINED` | 正常返回，禁止模型补写 memory |
| 输入错误 | `INVALID_REQUEST` | 不重试，返回 typed validation detail |
| 身份/权限 | 401/403、`TENANT_MISMATCH` | 不重试，不向模型暴露 token detail |
| 并发 | `VERSION_CONFLICT`、`ISSUE_REVISION_CONFLICT` | 重新 recall，要求新的人类/策略决定 |
| 幂等冲突 | `IDEMPOTENCY_CONFLICT` | 终止；operation ID 被错误复用 |
| 不可用 | `CANONICAL_UNAVAILABLE` | 有界重试后 abstain |
| 降级 | `PROJECTION_DEGRADED` | 可继续但展示 degraded/fallback |
| 预算 | `CONTEXT_BUDGET_INFEASIBLE` | 缩小非 protected 内容或请求更大预算 |
| 禁用 | `OPERATION_NOT_ENABLED` | 不尝试绕过 |

---

# 7. 生命周期 Hook

## 7.1 标准生命周期

```text
on_session_start
→ before_model
→ after_user_observation / after_tool_observation
→ on_demand_recall
→ after_model
→ before_compaction
→ on_session_end
```

## 7.2 Hook 行为

| Hook | 默认行为 | 禁止行为 |
| --- | --- | --- |
| `on_session_start` | health/capabilities；载入 active goal 和 live issues 摘要 | 全库 dump 到 prompt |
| `before_model` | 以本轮 query/scope 自动 recall；构建 ContextCapsule | 依赖模型“想起来才搜索” |
| `after_user_observation` | 在用户已同意的 capture policy 下写 USER_STATEMENT Evidence | 自动批准 Claim |
| `after_tool_observation` | allowlist 工具输出，记录 source_ref/hash/time | 将工具自然语言解释当事实 |
| `on_demand_recall` | 允许模型发起额外精确/多跳搜索 | 绕过 Canonical Gate |
| `after_model` | 记录 ChatTurn/Episode refs；可生成 ProposalDraft | 把模型回答自动记为 Evidence |
| `before_compaction` | 建立 protected Capsule；持久化 recoverable refs | 通过摘要关闭 OpenIssue |
| `on_session_end` | capture Episode；返回 pending Proposal/review link | 自动 Settlement 或批量删除 |

## 7.3 Capture Policy

默认策略：

```yaml
capture_user_statement: explicit_or_allowlisted
capture_tool_observation: allowlisted_tools_only
capture_model_output: false
auto_create_proposal: false
auto_review_proposal: false
capture_raw_prompt: false
```

允许用户选择 `OFF`、`ASK_EACH_TIME`、`ALLOWLISTED` 三档。任何模式都不能改变 canonical review
规则。敏感来源、凭据、完整 Prompt、未脱敏工具日志始终拒绝 capture。

---

# 8. MCP Adapter 设计

## 8.1 进程与 transport

MCP adapter 是独立可选包：

```text
default: stdio child process
optional: loopback Streamable HTTP
remote: disabled until Remote Access Gate
```

Adapter 只持有 scoped MiLAi API credential，不持有数据库 DSN。使用官方 Python MCP SDK，锁定
版本和 license，记录兼容矩阵。首个 release 至少验证：

```text
MCP 2026-07-28 client
one preceding widely deployed protocol version
stdio reconnect
stateless HTTP request routing when enabled
```

## 8.2 Capability profiles

| Profile | 默认对象 | Tools |
| --- | --- | --- |
| `reader` | 普通 Agent | status、recall、get claim/issues/trace |
| `submitter` | 可信单 Agent host | reader + capture Evidence + create Proposal |
| `operator` | 人类运维宿主 | 另行启动；revoke/status/recovery；不注入普通模型 |
| `reviewer` | 本地人类 UI | 不通过通用 MCP 暴露 |

Tool catalog 由启动 profile 决定并确定性排序，不能让模型通过参数把 reader 升级为 submitter。

## 8.3 第一版工具

### Read-only

```text
milai_status
milai_recall
milai_claim_get
milai_open_issues_list
milai_trace_get
milai_evidence_metadata_get
```

### Candidate-write

```text
milai_evidence_capture
milai_proposal_create
```

### Sensitive operator-only

```text
milai_evidence_revoke
milai_deletion_status_get
```

明确不提供：

```text
milai_proposal_review
milai_claim_update_direct
milai_open_issue_resolve_direct
milai_delete_all
milai_clear_tenant
milai_database_query
```

## 8.4 Tool result

所有工具同时返回 machine-readable structured result 与短文本摘要。短文本不得丢失：

```text
status / abstention
authority
degraded state
canonical/retrieval trace ID
open issue refs
pending review state
```

不得返回 embedding 数组、数据库 row dump、secret、完整未请求正文或无限列表。默认最大结果数和
byte budget 由 capabilities 公布，超限必须分页或返回 pointer。

## 8.5 敏感调用确认

- capture Evidence：显示 source、subject、Scope、正文摘要与 retention；
- create Proposal：显示 operation、target、authority、Evidence branches；
- revoke：必须提供 Evidence ID、reason、字面确认，并显示 fail-closed/异步 purge 后果；
- bulk operation：首版完全不提供；
- tool call、输入 fingerprint、结果 ID 和 request ID 写入脱敏 audit event。

## 8.6 MCP Resources

第二阶段可以提供只读 URI：

```text
milai://claims/{claim_id}
milai://open-issues/{issue_id}
milai://retrieval-traces/{trace_id}
milai://context-capsules/{capsule_id}
```

Resource read 仍需当前 authorization，并重新校验 tenant、TTL 和 retention。cache hint 不能越过
Claim/OpenIssue/revoke 的 canonical position；敏感 current state 默认 `no-store`。

---

# 9. Framework Adapter

## 9.1 通用 Function Tool

提供与具体模型 SDK 无关的 JSON Schema tool definitions：

```python
tools = create_milai_tools(
    client=client,
    profile="reader",
    recall_policy=AgentRecallPolicy(
        scope={"project_ids": ["my-project"]},
        authority="ACTION_SAFE",
        consistency_floor="CANONICAL_REQUIRED",
        max_limit=5,
    ),
)
```

每个 framework wrapper 只负责转换：

```text
framework tool schema
↔ MiLAi common tool schema
↔ typed client
```

不得在每个 wrapper 中复制权限、重试、Scope 或 output formatting 规则。

`AgentRecallPolicy` 由可信 host 在构造 adapter 时冻结。LangGraph state、AutoGen query kwargs、MCP
tool arguments 和模型生成的 JSON 都不得覆盖或扩大 Scope/authority、降低 consistency floor，或提高
limit；出现这些字段时必须拒绝或按 host policy 收窄，且测试要证明 HTTP client 未收到扩大后的请求。

## 9.2 LangGraph

推荐节点：

```text
milai_recall_node
milai_context_node
milai_capture_observation_node
milai_prepare_proposal_node
human_review_interrupt
```

集成原则：

- LangGraph checkpointer 继续保存 graph/thread state；
- MiLAi 保存跨 thread 的 Evidence、Claim 和 OpenIssue；
- `milai_recall_node` 在 model node 前运行，不完全依赖 tool choice；
- `human_review_interrupt` 展示 Proposal，真正 review 请求由可信 host 发出；
- `proposal_candidate` 必须先执行 `ProposalDraft.model_validate()`，缺 model/template/snapshot、Evidence
  branch 冲突、authority 不一致或 stale expected head 时，在任何 HTTP 请求前失败；
- 不实现可写 `BaseStore.put()` 到 canonical Claim；如需兼容 Store，只提供 read-through view 或把
  `put()` 收缩为 Evidence capture。

## 9.3 AutoGen

实现 `MiLAiMemory`：

```text
query           → recall
update_context  → append prompt-safe ContextCapsule data
add             → capture Evidence only, optional ProposalDraft
clear           → OPERATION_NOT_ENABLED
close           → close HTTP client
```

多 Agent team 仍共享一个可信 orchestrator identity；本文不提供 agent-to-agent authority delegation。
如果需要区分 Agent，只能先记录 non-authoritative `caller_label`，不能伪装 canonical actor。

## 9.4 Coding Agent / Hook-based Host

借鉴 Mem0/ReMe 的 hook 形状，但使用 MiLAi governance：

```text
SessionStart       health + scoped recall
UserPromptSubmit   automatic recall; optional user Evidence capture
PostToolUse        allowlisted tool observation capture
PreCompact         protected Capsule + pointer
Stop               Episode refs + pending Proposal summary
```

Hook 安装器必须幂等、可卸载、保留其他项目 hook，并且只写明确的项目或用户配置文件。默认不启用
自动 capture，不把绝对 token 或正文写进 hook config。

## 9.5 MCP-capable Host

优先直接连接 `milai-mcp`，避免维护每个宿主的专用插件。若宿主还支持 lifecycle hooks，MCP 提供
on-demand tools，hook 负责 mandatory pre-model recall；二者不得重复 capture 同一观察，operation ID
必须由 host session/turn/tool-call 的稳定组合生成。

---

# 10. 本地可用性设计

## 10.1 安全初始化

扩展 `milai-ops`：

```text
milai-ops init
milai-ops doctor [--json]
milai-ops status [--json]
milai-ops smoke-test
milai-ops agent-config --transport stdio --profile reader
```

`init` 必须：

- 默认 `data_mode=SYNTHETIC_ONLY`；
- 生成彼此不同的 owner/API/Steward/Worker/Audit 密码；
- 生成彼此不同且不少于 32 字符的 API/causal secrets；
- 生成 tenant/actor UUID；
- 创建 `.env` 时使用 `0600`；
- 目标已存在时拒绝覆盖，除非显式、可恢复的 rotation workflow；
- 只显示字段已生成，不回显 secret；
- 校验所有 URL 中的角色用户名精确匹配。

## 10.2 Doctor

Doctor 按层报告：

```text
OS / architecture
Python / uv / lock
Docker / Compose
port conflicts
env fields without values
loopback binding
PostgreSQL/pgvector
exact DB roles and ownership
Alembic current/head
blob root permissions
API live/ready
worker lease / projection lag / dead letter
backup client major version
Agent SDK/MCP compatibility
data mode / crypto gate
```

输出使用 `PASS/WARN/BLOCKED/NOT_CONFIGURED`；退出码稳定并有 JSON schema。`WARN` 不能掩盖
crypto、role、tenant、migration 或 remote-bind blocker。

## 10.3 启停体验

保留现有 Compose PostgreSQL 基线，新增受测的 local profile 或 wrapper：

```text
database → migration → db-check → worker → API → smoke
```

必须支持：

- 前台开发模式，日志可读；
- 后台本地 profile，healthcheck 可观察；
- Ctrl-C/SIGTERM 正常退出；
- 重复启动不破坏数据；
- 停止默认保留 volume；
- 不提供无确认删除 volume 的快捷命令；
- API/Worker 永远不使用 migration owner。

## 10.4 Smoke test

使用专用临时 smoke database、独立 blob root 和 synthetic tenant 完成；禁止把 smoke test 指向当前
用户数据库或已有个人数据目录：

```text
health
→ ingest synthetic Evidence
→ create pending Proposal
→ verify no Claim exists before review
→ review through explicit test steward path
→ L0 and L1 recall
→ build ContextCapsule
→ inspect RetrievalTrace
→ revoke Evidence
→ verify stale projection rejected and answer abstains
→ verify deletion status
```

Smoke 数据不能混入真实 tenant。测试完成后只清理启动时精确创建且已验证 owner/连接数的临时
database/blob root，并留下结果报告；不得提供指向工作数据库或宽目录的清理参数。

## 10.5 UI

现有 UI 保留 review/correct/confirm/trace/revoke/Episode/Settlement。增加：

- Runtime/Schema/data-mode banner；
- Agent connection status 和 capability profile；
- pending Proposal inbox；
- Claim/Evidence/OpenIssue/Trace 联合查看；
- degraded/projection lag/backup obligation；
- 明确区分 logical revoke、canonical block、derived purge、primary erase、backup expiry；
- 一键复制非敏感 MCP stdio config；
- 不显示或复制 token；
- real-data gate 未通过时在 Evidence 输入处阻断并说明原因。

## 10.6 文档与示例

交付：

```text
docs/runbooks/agent-integration.md
docs/runbooks/first-run.md
docs/runbooks/credential-rotation.md
contracts/agent/v1/openapi.yaml
contracts/agent/v1/tool-contract.json
examples/generic-agent/
examples/langgraph/
examples/autogen/
examples/mcp-client/
```

示例全部使用 synthetic data 和占位 secret；每个示例具有可自动运行的 smoke test，不能只是 README
代码片段。

---

# 11. Model 与 Embedding 可用性

## 11.1 决策

Agent Integration Beta 不要求 MiLAi 自己生成自然语言回答。Agent framework 的 model 负责 answer
composition，MiLAi 负责返回 Gate 后的结构化 context 和 trace。这能最快形成真实接入，同时保持模型
与 canonical transaction 分离。

## 11.2 Embedding Provider

当前 deterministic hash 只保留用于测试。定义：

```python
class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    dimensions: int
    normalization: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
```

真实 provider 准入条件：

- explicit config，不在 import time 联网；
- 模型、dimension、normalization、code version 全部进入 projection identity；
- provider/dimension 改变创建新 projection version；
- 双写/重建期间旧新 projection 不混合分数；
- timeout/rate limit/batch/retry 可配置且有界；
- 正文是否发送外部 provider 必须由 data policy 和用户同意决定；
- provider 不可用时 L0/FTS 继续，vector 显式 degraded；
- 在本地 benchmark 上证明相对 deterministic baseline 的实际增益后才设为默认。

## 11.3 Optional Candidate Extractor

可接入 host model 或本地 model 生成 ProposalDraft；它不是 Runtime 启动依赖。评测至少覆盖：

```text
fact extraction precision
unsupported proposal rate
conflict detection recall
Scope/authority accuracy
Evidence branch attribution
prompt injection resistance
cost/latency
human rejection rate
```

在真实数据 gate 前只使用 synthetic/de-identified fixture。

---

# 12. 身份、授权与安全

## 12.1 当前过渡方案

本地 stdio adapter 由可信 host 启动，token 只存在子进程环境中；模型看到 tool schema，不看到 token。
Adapter profile 建立工具 allowlist。该方案只适用于 single-user loopback candidate。

## 12.2 Capability scopes

在开放 HTTP MCP 或多个 Agent 前，新增 API credential scope：

```text
memory:read
evidence:capture
proposal:create
evidence:revoke
proposal:review
operations:admin
```

原则：

- 普通 Agent：`memory:read`；
- 可信 submitter：加 `evidence:capture`、`proposal:create`；
- model 永远不获得 `proposal:review`、`operations:admin`；
- revoke 使用独立 operator host 和显式确认；
- scope 在 server 端检查，不能只靠 MCP 隐藏工具；
- token 以 hash 存储、可撤销、可轮换、有 last-used metadata，不记录明文；
- credential 与 tenant/actor/capability 绑定，body `tenant_id` 永远不可信。

该变化涉及权限边界，实施前需要 ADR 和真实 role/negative tests。

## 12.3 Prompt/tool injection

威胁：Evidence、Claim payload、外部文件或 tool result 中可能包含伪指令，诱导 Agent 读取 secret、
扩大 Scope、调用写工具或删除记忆。

控制：

- memory block 标记为 untrusted data；
- 默认只返回 Claim payload 和 refs，不返回任意 raw source；
- tool 输出结构化并限长；
- model 不能控制 API base URL、tenant、credential 或 adapter profile；
- write tool 参数在 host UI 中独立展示；
- `proposal:create` 与 `proposal:review` 分离；
- revoke/bulk/remote tool 需要 out-of-band confirmation；
- 禁止 token passthrough；下游 provider 使用不同 credential；
- 对 tool descriptions 和 annotations 做 source lock，防 coordinated substitution；
- 记录 allow/deny 两条 audit path。

## 12.4 Remote boundary

HTTP MCP 只允许 loopback。启用远程前必须完成：

```text
TLS
OAuth 2.1 / audience-bound token
session/device revocation
CSRF/CORS/cookie policy where applicable
rate limiting and request size limits
secret rotation
security logging and incident runbook
tool-level scopes
prompt injection/data exfiltration test
```

不得把当前本地 Bearer token 直接放到公网。

## 12.5 Multi-Agent boundary

当前 configured actor 表示一个本地用户/可信 host，不表示多个 Agent 的独立身份。第一版允许多个
framework worker 通过同一 orchestrator 读取，但：

- 不得声称 per-agent RLS；
- 不得让 agent label 获得 authority；
- 不实现 agent-to-agent delegation；
- 并发 Proposal 仍通过 existing CAS；
- 所有 write 汇聚到一个 submitter policy；
- 真正 multi-agent governance 需要独立 principal、grant、eligible Evidence 和 arbitration ADR。

---

# 13. 真实数据 Local Private Beta Gate

## 13.1 Crypto

实现 ADR-012，而不是只在文档中声明：

```text
per-tenant data-encryption key
AEAD ciphertext + nonce + algorithm/version
separate key-encryption key / key reference
atomic write and integrity verification
rotation with resumable progress
key backup and verified recovery
missing/wrong key fail closed
shared blob tenant boundary
secure erase semantics and deletion reconciliation
```

密钥不能存入数据库 dump、日志、Prompt、`.env.example` 或 source tree。具体 OS keyring/file/HSM
选择必须由 ADR 和目标设备恢复演练决定。

## 13.2 Data mode

新增 fail-fast mode：

```text
SYNTHETIC_ONLY
DEIDENTIFIED_ALLOWED
LOCAL_PERSONAL_DATA
```

`LOCAL_PERSONAL_DATA` 启动必须证明 encryption/key provider/backup recovery gate 已通过，否则 API 拒绝
Evidence ingest。不能仅依赖 UI banner。

## 13.3 Source-specific migration

真实来源导入必须记录：

```text
source system and export version
consent and allowed Scope
source identity → Evidence source_ref mapping
observed/captured time semantics
permission/retention mapping
content hash and duplicate policy
dry-run report
reversible staging / reject list
```

外部 memory 导入结果先成为 Evidence；不能把 Mem0/Hindsight/Graphiti/OpenViking 的 derived fact
直接写成 Claim。

---

# 14. 可观察性与运行合同

## 14.1 每次 Agent recall

记录：

```text
request ID and caller profile
query fingerprint, not plaintext
scope/authority/consistency
route and planner version
canonical position / watermarks
accepted/rejected candidate IDs and reason codes
fallback/degraded/abstention
context budget/compression level
duration and provider cost metadata
```

## 14.2 每次 Agent write

记录：

```text
operation ID / request fingerprint
source type/ref fingerprint
Evidence/Proposal/Decision IDs
caller profile and host instance
policy/template/model identity
replay/conflict/partial outcome
outbox and causal position
```

不记录正文、token、密码、完整 prompt 或异常 message 中的敏感内容。

## 14.3 Agent status

SDK/MCP 提供聚合只读状态：

```text
runtime ready
schema/API compatibility
data mode
canonical availability
worker/projection lag
degraded components
pending review count
open issue count
crypto/remote gates
```

状态不能将 “liveness OK” 等同于 “canonical ready”。

---

# 15. 代码与包布局

推荐保持 core 与 adapters 可移除：

```text
MiLAi/
├─ runtime/                         # existing canonical Runtime
│  ├─ src/milai/
│  └─ tests/
├─ contracts/
│  └─ agent/v1/
│     ├─ openapi.yaml
│     ├─ tool-contract.json
│     └─ examples/
├─ integrations/
│  ├─ python-client/
│  │  ├─ pyproject.toml
│  │  ├─ src/milai_agent/
│  │  └─ tests/
│  ├─ mcp/
│  │  ├─ pyproject.toml
│  │  ├─ src/milai_mcp/
│  │  └─ tests/
│  ├─ langgraph/
│  ├─ autogen/
│  └─ hooks/
├─ examples/
│  ├─ generic-agent/
│  ├─ langgraph/
│  ├─ autogen/
│  └─ mcp-client/
└─ evals/
   ├─ adapters/
   ├─ manifests/
   └─ results/
```

包规则：

- Python client 只依赖 HTTP/Pydantic 基础库；
- MCP 依赖只在 `integrations/mcp`；
- LangGraph/AutoGen 依赖只在对应 optional package；
- Runtime 不能 import integrations；
- integrations 不能 import Runtime persistence/application internals；
- 每个包独立 lock、license inventory 和 build test；
- tool/OpenAPI schema 由单一 typed contract 生成或机械一致性校验；
- distribution 暂为本地 artifact，项目 license 决定前不公开发布。

---

# 16. 开发路线

本文使用 `UA-*`（Usability/Agent Integration），不与 frozen G/I 或现有 DG/LC 混用。

## UA-00 设计与权限预检

交付：

- 本文；
- current REST/API/schema inventory；
- proposed ADR-020 Agent Integration Plane；
- proposed ADR-021 scoped client capability；
- tool threat model；
- API compatibility policy。

Gate：没有 adapter direct DB、review exposure 或新 canonical semantics。

## UA-01 Bootstrap 与 Doctor

交付：

- `milai-ops init/doctor/status/smoke-test`；
- 安全 `.env` 生成和权限检查；
- 受测 local start profile；
- first-run runbook；
- current head/role/blob/worker/provider diagnosis。

Gate：干净环境可重复启动；缺 secret、错误角色、错误 migration、remote bind、broad blob root 都 fail
fast；不覆盖已有 `.env` 或 volume。

## UA-02 Agent Contract 与 Python SDK

交付：

- `/v1/capabilities`；
- Agent OpenAPI/tool contract；
- async/sync typed client；
- RecallEnvelope/ContextEnvelope；
- typed error/retry/idempotency；
- generic function tools；
- package build/install。

Gate：SDK 不依赖 DB/schema；所有现有 failure paths 有 contract tests；token 不出现在 trace/log/model context。

## UA-03 Lifecycle 与受治理写入

交付：

- lifecycle hooks；
- capture policy；
- Observation → Evidence；
- optional ProposalDraft extraction boundary；
- pending review UI/link；
- Episode refs；
- duplicate hook/idempotency tests。

Gate：模型回答不自动成为 Evidence；Agent 不能 review；重试不重复 canonical side effect。

## UA-04 MCP stdio

交付：

- official-SDK MCP server；
- reader/submitter/operator profiles；
- read/candidate-write tools；
- structured/limited outputs；
- stdio config generator；
- protocol compatibility matrix；
- at least two MCP host smoke tests。

Gate：默认 tool list 不含 review、direct mutation、bulk delete；model 无 credential；敏感 call 可拒绝。

## UA-05 Framework References

交付：

- LangGraph nodes + human interrupt example；
- AutoGen Memory adapter；
- generic async Agent loop；
- coding-agent hook example；
- framework version/lock/license manifest。

Gate：同一 E2E fixture 在至少两类框架与 MCP 上得到相同 canonical result/trace；framework checkpoint
和 MiLAi long-term state 不混用；模型状态/kwargs 不能扩大 host recall policy，所有 extractor/tool
proposal 必须在 HTTP 前通过同一 `ProposalDraft` contract。

## UA-06 Retrieval Quality

交付：

- real `EmbeddingProvider`；
- projection version migration/rebuild；
- FTS/vector fallback；
- benchmark adapters；
- target-device measurement；
- provider privacy policy。

Gate：相对 deterministic baseline 有可复现增益；provider outage 只降低 recall；模型变化不混合
projection；没有安全 hard-gate regression。

## UA-07 Local Private Beta

交付：

- ADR-012 crypto implementation；
- key rotation/recovery；
- encrypted backup/restore drill；
- data mode enforcement；
- source-specific import dry-run；
- privacy/security review；
- Local Private Beta report。

Gate：错误/缺失 key fail closed；备份恢复后 ciphertext、IDs、lineage、blocks、deletion obligations 对账；
真实数据需用户明确批准。

## UA-08 Release Candidate

交付：

- versioned SDK/MCP packages；
- clean-room setup；
- complete current-byte inventory；
- allowlist-built artifacts and recursive archive-member secret/cache/path scan；
- E2E/failure/security/performance report；
- independent integration review；
- known-limitations document。

Gate：只能提升为 `Agent Integration Beta` 或 `Local Private Beta`，不得顺带宣称 Schema frozen 或
Production ready。

---

# 17. 测试与验收

## 17.1 Client contract

```text
capabilities negotiation
all request/response schema round-trip
unknown fields fail closed where required
typed error mapping
network timeout / 429 / 503 bounded retry
write retry preserves idempotency key and payload
409 never silently regenerated
abstention is preserved
client close releases resources
```

## 17.2 MCP

```text
tools/list deterministic and profile-specific
input schema rejects tenant/base-url/profile override
host consistency floor/limit cannot be weakened or expanded
ProposalDraft strict schema rejects invalid/stale candidates before proposal POST
structured output contains trace/abstention/degraded
no secret/raw embedding/unbounded content
reader cannot discover or invoke write tools
submitter cannot review
operator revoke requires exact ID/reason/confirmation
stdio restart/reconnect
protocol version compatibility
malicious tool description/result substitution rejection
```

## 17.3 Lifecycle

```text
before-model recall occurs without model tool choice
same turn/hook replay is idempotent
assistant output is not Evidence
allowlisted tool observation has exact provenance
compaction preserves live OpenIssue and discharge rule
session end creates refs, not automatic Claim
stale/revoked pointer disappears from next turn
raw model Proposal must pass model/template/snapshot/Evidence/authority/head validation
```

## 17.4 Framework

```text
LangGraph checkpoint remains independent
LangGraph interrupt resumes same Proposal
AutoGen query/update_context consume RecallEnvelope
AutoGen clear fails closed
generic tool wrapper and MCP yield equivalent results
multi-worker concurrent proposals preserve CAS
framework state/kwargs cannot mutate host-owned recall policy
```

## 17.5 Security

```text
token never enters prompt/tool result/log/trace
wheel/sdist member scan opens nested archives and rejects live env/cache/log/backup/blob members
model cannot set tenant or credential scope
cross-tenant read/write denied with real login roles
prompt injection in Evidence cannot call review/revoke
server enforces scope even if adapter is bypassed
remote URL rejected by default
oversized output/payload rejected
revoke immediately invalidates Agent context
canonical outage produces abstention
```

## 17.6 E2E Agent fixture

```text
Session 1:
user/tool observes Python 3.11
→ Evidence
→ pending CREATE Proposal
→ Agent cannot recall it as canonical truth
→ human APPROVE
→ causal token
→ next recall returns V1 with trace

Session 2:
new Evidence reports Python >=3.12
→ CONTRADICT Proposal
→ review creates OpenIssue, Head remains V1
→ pre-model Capsule contains both branches and discharge rule
→ Agent presents uncertainty

Session 3:
admissible CI/runtime Evidence resolves issue
→ governed SUPERSEDE creates V2
→ revoke resolution Evidence
→ same issue reopens
→ stale FTS/vector/MCP cache cannot return action-safe V2
→ Agent abstains with deletion/trace refs
```

必须在 generic SDK、MCP 和至少一个 native framework adapter 上回放。

---

# 18. 评测计划

## 18.1 产品指标

| 维度 | 指标 |
| --- | --- |
| Setup | clean bootstrap success、doctor blocker accuracy、manual secret exposure=0 |
| Integration | framework/MCP contract pass、tool schema stability、hook replay correctness |
| Retrieval | recall/precision、authority/scope reject correctness、stale rejection |
| Context | protected item recall、byte/token budget、pointer recovery、false closure |
| Governance | unsupported Proposal rate、human reject rate、CAS/idempotency correctness |
| Safety | cross-tenant exposure、delete fail-open、credential leakage、prompt injection success |
| Operations | API/tool latency distribution、projection lag、retry/dead-letter、recovery |
| Answer | attribution、abstention、OpenIssue presentation、later-task success |

任何平均质量分都不能抵消以下 hard failure：

```text
cross-tenant exposure
Agent self-review or direct canonical write
live OpenIssue omitted/closed
revoked Evidence still raises authority
canonical unavailable but answer claims certainty
idempotent retry duplicates state
secret reaches model context
real plaintext data accepted before crypto gate
```

## 18.2 本地 benchmark 使用

| 资产 | MiLAi 评测用途 |
| --- | --- |
| LongMemEval | 跨 session recall、时间、更新、abstention |
| LongMemEval-V2 | agent trajectory、multimodal refs、query latency |
| BEAM | 128K～10M 分层长程能力、冲突、顺序、instruction/preference following |
| Memora | remembering/reasoning/recommending 与 forgetting-aware accuracy |
| HorizonBench | 演化偏好与旧偏好 hard negative |
| CUPID | contextual preference，而非静态 global profile |
| PAHF | feedback-driven personal Agent baseline |

先实现统一 adapter：

```text
prepare(run_spec) → immutable manifest
ingest(snapshot) → Evidence/Proposal IDs
review(frozen_policy_or_labels) → canonical state
query(question) → RecallEnvelope/answer/trace
score(output) → metrics + hard failures
cleanup(run_id) → isolated cleanup report
```

ReMe/Hindsight/Graphiti/Mem0 继续通过隔离 baseline adapter 运行，不接收 canonical DSN 或 production
credential。OpenViking 在 license/commit 未冻结前只作外部概念参考。

## 18.3 性能阈值

本文不编造 SLA。UA-06 在目标设备上冻结：

```text
dataset/workload hash
concurrency and warm/cold state
database/index size
provider/model/version
CPU/RAM/GPU
p50/p95/p99 latency
throughput and projection lag
token/model cost
failure/fallback rate
```

之后才能决定默认 result limit、context budget、worker concurrency 和 provider。

---

# 19. Gate 与 Definition of Done

## 19.1 UG-01 Developer Ready

- 安全 init、doctor、status、smoke 全部通过；
- clean environment 无手工 SQL；
- 配置/角色/migration/blob/worker/API fail-fast；
- runbook 与真实命令一致；
- synthetic data banner 和 gate 生效。

## 19.2 IG-01 SDK Ready

- Agent OpenAPI/tool contract versioned；
- sync/async SDK build、clean install、contract suite 通过；
- capability negotiation、typed errors、idempotency/retry 完整；
- Runtime/Schema 细节不泄漏为客户端依赖。

## 19.3 IG-02 MCP Ready

- stdio MCP 在至少两个 host 上通过；
- reader/submitter/operator catalog 隔离；
- review/direct-write/bulk-delete 不可发现；
- prompt/credential/tool substitution negatives 通过；
- current + compatibility protocol versions 通过。

## 19.4 IG-03 Framework Ready

- generic loop、LangGraph、AutoGen 中至少两种完成同一 E2E；
- before-model recall、human review、revoke/abstain 可回放；
- framework short-term state 与 MiLAi long-term state 明确分离。

## 19.5 QG-01 Retrieval Quality

- real provider 相对 deterministic baseline 有可复现增益；
- provider outage/dead-letter 不提升 authority；
- benchmark manifest、cost 和失败分布完整；
- 没有 hard safety regression。

## 19.6 SG-01 Local Private Data

- encryption/key rotation/recovery/backup drill 通过；
- data mode server-side enforcement；
- source import dry-run 和 reject list；
- privacy/security review；
- 用户明确批准真实数据试用。

## 19.7 Agent Integration Beta DoD

只有以下事实同时成立才可发布：

1. 新用户能从干净 checkout 可重复启动和诊断；
2. Agent 通过 SDK/MCP 获取 Gate 后记忆和 OpenIssue；
3. abstention/degraded/trace 不在 adapter 中丢失；
4. Agent 只能 capture Evidence、提交 Proposal，不能 self-review；
5. write retry 不产生重复副作用；
6. model output 不自动成为 Evidence 或 Claim；
7. token、DB credential、正文不进入日志或模型 context；
8. revoke 后所有 Agent 接入面立即 fail closed；
9. generic + MCP + native framework E2E 通过；
10. external projects 不成为 Runtime 启动依赖或 canonical authority；
11. 当前完整 source/contract/test/package bytes 有可复算 inventory；
12. 文档继续明确 Schema experimental、Implementation candidate；
13. 真实数据只在 SG-01 后启用；
14. 独立 reviewer 没有开放 P0/P1。

---

# 20. 风险与缓解

| 风险 | 后果 | 缓解 |
| --- | --- | --- |
| MCP 最新规范采用不一致 | 不同 host 无法连接 | 官方 SDK、版本协商、兼容矩阵、stdio first |
| Agent 忘记 recall | 回答缺少历史 | mandatory before-model hook + on-demand tool |
| Agent 过度 capture | 噪声/隐私进入 Evidence | capture policy、allowlist、confirmation、size/redaction |
| Agent self-confirmation | 错误 canonical state | 不暴露 review；server capability scope；独立 UI |
| framework Store 语义冲突 | 原地覆盖历史 | 只做 facade/node；put 收缩为 Evidence |
| prompt injection in memory | 越权工具或数据外泄 | data-only formatting、host policy、tool scopes、confirmation |
| current token 过宽 | adapter 被绕过 | token 不给模型；尽快实现 scoped server authorization |
| deterministic embedding 质量低 | 召回差 | L0/FTS 保底；UA-06 provider+benchmark |
| external provider 泄露正文 | 隐私风险 | data policy、local provider/opt-in、redaction、separate credential |
| schema forward-only | upgrade/adapter drift | REST contract、capability negotiation、backup/forward repair |
| OpenViking license 变化 | 代码复用合规风险 | 仅概念参考；commit-level legal gate |
| 多 Agent 共用 actor | 无法追责/授权 | single orchestrator boundary；multi-agent governance parked |
| 过早追求一键部署 | 掩盖角色/secret 错误 | init/doctor fail-fast；不弱化 role separation |

---

# 21. 待决 ADR

## ADR-020（提议）：Agent Integration Plane

决定 SDK/MCP/framework adapter 的进程边界、依赖方向、API compatibility 和 release inventory。

## ADR-021（提议）：Client Principal 与 Capability Scope

决定本地 scoped token 的存储、绑定、撤销、轮换、actor mapping 和 HTTP MCP 升级条件。

## ADR-022（提议）：Real Embedding Provider Baseline

决定首个真实 provider、projection identity、重建/切换、privacy 和目标设备评测。

## ADR-012（已有，待实施）：Blob Encryption/Key

本文不创建同义 ADR。Local Private Beta 必须以 ADR-012 的实际代码、Migration、故障测试和恢复演练
关闭该门。

开放问题不能由实现静默决定：

1. Python client/MCP 是独立 distribution 还是 monorepo workspace packages；
2. 首个 MCP 兼容旧版本选择；
3. local scoped token 是否需要持久表，或先采用进程级 capability file；
4. 第一个真实 embedding 使用本地模型还是显式远程 provider；
5. target device 与真实 workload；
6. 项目公开 license；
7. crypto key provider 与灾难恢复介质。

---

# 22. 推荐实施顺序

```text
P0
UA-00  ADR/API inventory
UA-01  init + doctor + smoke
UA-02  capabilities + Python SDK + contracts
UA-03  before-model recall + controlled capture/proposal
UA-04  MCP stdio reader/submitter

P1
UA-05  LangGraph/AutoGen/reference agents
UA-06  real embedding + benchmark
ADR-021 server-side scoped credentials

P2 / separate approval
UA-07  crypto/key/real-data Local Private Beta
Remote Access Gate
multi-agent governance
```

最早可交付的高价值纵向切片：

```text
milai-ops init/doctor
→ API/worker ready
→ generic SDK before-model recall
→ MCP reader tools
→ user/tool Evidence capture
→ pending Proposal
→ human review UI
→ causal recall + ContextCapsule
→ revoke + next-turn abstention
```

该切片不依赖真实 LLM、外部 memory backend 或公网服务，能够直接证明“MiLAi 可启动、Agent 可接入、
写入受治理、删除可传播”。

---

# 23. 研究来源

## 23.1 本地权威材料

- `AGENTS.md`
- `MiLAi_Logical_Architecture_v1_设计文档.md`
- `architecture/v1.0/`
- `MiLAi_Lean_V1_实施合同.md`
- `MiLAi_Lean_V1_设计规划与开发路线_v1.md`
- `docs/reports/GOALS-completion-audit-2026-08-17.md`
- `runtime/README.md`
- `docs/runbooks/local-runtime.md`
- `runtime/src/milai/api/`
- `runtime/src/milai/application/`
- `runtime/src/milai/domain/`
- `runtime/tests/`

## 23.2 本地相关项目

- `/cra/memory/mx_memory/mem0`
- `/cra/memory/mx_memory/graphiti`
- `/cra/memory/mx_memory/ReMe`
- `/cra/memory/mx_memory/hindsight`
- `/cra/memory/mx_memory/benchmarks/*`

## 23.3 官方外部资料（访问日期 2026-08-17）

- [Mem0 MCP](https://docs.mem0.ai/platform/mem0-mcp)
- [Mem0 Agent integration](https://docs.mem0.ai/cookbooks/integrations/agents-sdk-tool)
- [Graphiti MCP Server](https://github.com/getzep/graphiti/blob/main/mcp_server/README.md)
- [ReMe repository](https://github.com/agentscope-ai/ReMe)
- [Hindsight Retain](https://hindsight.vectorize.io/developer/retain)
- [Hindsight API Quickstart](https://hindsight.vectorize.io/developer/api/quickstart)
- [OpenViking MCP Integration](https://github.com/volcengine/OpenViking/blob/main/docs/en/guides/06-mcp-integration.md)
- [OpenViking Context Types](https://github.com/volcengine/OpenViking/blob/main/docs/en/concepts/02-context-types.md)
- [OpenViking license transition discussion](https://github.com/volcengine/OpenViking/discussions/992)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [AutoGen Memory and RAG](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/memory.html)
- [MCP 2026-07-28 release](https://blog.modelcontextprotocol.io/posts/2026-07-28/)
- [MCP Tools specification](https://modelcontextprotocol.io/specification/draft/server/tools)
- [MCP Security Best Practices](https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices)

---

# 24. 最终定位

完成本文路线后，MiLAi 应被准确描述为：

> 一个可在本地重复启动、可通过 typed SDK/MCP 接入单个可信 Agent orchestrator、以 Evidence 为输入、
> 以 Proposal/Decision 治理长期 belief、在冲突和删除时 fail closed、并为每次记忆使用提供 trace 的
> personal memory runtime。

在 SG-01 之前必须继续追加：

```text
Agent Integration: BETA / synthetic or de-identified
Schema: 0.1.x EXPERIMENTAL
Implementation: CANDIDATE
Real personal data: DENIED
Remote/multi-agent governance: NOT ENABLED
```

---

# 25. 2026-08-17 实施回填

本文的 Developer Ready 与 Single-Agent Integration Ready 纵向切片已实现：ADR-020/021/022、
versioned contract、可用性 CLI、scoped capabilities、typed SDK/lifecycle、MCP stdio profiles、
LangGraph/AutoGen/hooks、AES-256-GCM Blob/rotation，以及 ONNX provider/0027 projection identity。

已验证 fresh exact-role Runtime、strict host policy、typed Proposal boundary、六包 clean install 和
synthetic 三会话 E2E：Evidence → pending CREATE Proposal → pre-review ABSTAINED → 独立 reviewer
APPROVE → conflict/OpenIssue → governed supersede → revoke/reopen → stale projection fail closed。
SDK/MCP/LangGraph/AutoGen 共享 canonical result/trace。Candidate.1 的独立审查发现一个 P0 和四个
P1；candidate.2 已删除泄露 sdist、轮换全部凭据/KEK、修复 inventory/CI/host policy/ProposalDraft
边界，正在等待独立 re-review。当前准确状态为：

```text
Agent Integration: 0.1 RELEASE CANDIDATE.2 / SYNTHETIC_ONLY
Schema: 0.1.x EXPERIMENTAL / NO-GO
Implementation: CANDIDATE
Real personal data: DENIED pending user approval and independent recovery acceptance
Remote/multi-agent governance: NOT ENABLED
```

Candidate.2 实施证据与剩余独立 gate 见
`docs/reports/UA-08-agent-integration-release-candidate-2026-08-17.md` 和
`docs/reports/UA-08-candidate.2-security-remediation-evidence-2026-08-17.md`。
