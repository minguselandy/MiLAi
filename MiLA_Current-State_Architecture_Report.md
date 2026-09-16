# MiLA Current-State Architecture Report

> 审计对象：`/cra/memory/mx_memory/MiLAi`  
> 审计日期：2026-08-25（Asia/Shanghai）  
> 审计方式：静态、只读 repository audit  
> 当前代码标识：Schema `0.1.x EXPERIMENTAL / NO-GO`；Implementation `CANDIDATE`；Logical Architecture `1.0.0 FROZEN`

## 报告边界与证据规则

本报告先恢复 `CURRENT IMPLEMENTATION`，再单独列出 `INTENDED DESIGN` 与 `GAP`。证据优先级为 executable code → tests/evals → retained runtime artifacts → current specs → README/comments → naming。文中：

- `Observed` 表示可直接由当前文件证明；
- `[INFERENCE]` 表示由多处实现迹象推导，但没有单一显式 contract；
- `[UNKNOWN]` 表示当前 repository 无法确认；
- `Documented / Implemented / Status` 用于明确文档与实现冲突。

本轮未执行任何测试、benchmark、migration、服务或会生成产物的命令。测试通过数和实验结论均是 repository 中保留的历史 artifact，不是本轮重跑结果。

---

## 1. Executive Summary

1. **MiLA 当前实际是一个 governed local memory runtime 加外置 Host/Agent controller。** Runtime 是 Flask + PostgreSQL/pgvector + 本地 content-addressed blob store + Outbox worker；任务关系、Need 判断、Host slot/cache 和真正的 provider execution 位于 integration 层。证据：`runtime/src/milai/api/app.py::create_app()`；`integrations/openworker-mcp/src/milai_openworker_mcp/host_adapter.py::OpenWorkerProviderAdapter`。
2. **当前不存在唯一的一条“User Turn → Answer”路径。** 文档指定的主产品路径是 OpenWorker/MCP；同时 Runtime 暴露独立 `/v1/chat`，后者绕过 Task/Need/CACHE，固定 L1 retrieval，并用确定性模板而非 LLM 生成答案。证据：`AGENTS.md:72-76`；`runtime/src/milai/application/chat.py:40-209,287-296`。
3. **Canonical memory 的最终控制权在 PostgreSQL procedure。** API、retriever、Context、worker、LLM、index 都不能直接改变 Claim/OpenIssue；正式变化需要 Proposal、StewardDecision、CAS 和 append-only history。证据：`runtime/migrations/versions/0015_governed_proposals_and_complete_history.py:225-245,252-796`。
4. **Evidence、State 和 Context 在物理实现中确实分开，但不是按三个目录组织。** Evidence 是 CAS bytes + `EvidenceRecord`；StateView 是 Claim/Version/Head/OpenIssue/Grounding 经 ECS/Gate 解析的当前状态；Context 是 RetrievalTrace、ContextCapsule、pointer 和 Host-compiled slot。`RetrievalService`、`ContextRepository` 等模块跨层。
5. **Evidence 到 belief 没有自动 learning loop。** 普通 user/assistant turn 不会自动写 Evidence 或 Claim；Evidence ingest、Proposal create、Steward review 是三个显式动作。`DeriveAndDiagnose` 只分类 caller 已提交的 patch，不从 Evidence/对话中提取 Claim。证据：`runtime/src/milai/application/evidence.py::EvidenceService.ingest()`；`runtime/src/milai/application/derivation.py:50-122`。
6. **Task Identity 与 Task Memory Binding 在 Python client 类型上已明确分离，但只在 Host 进程内生效。** `TaskMemoryState(identity, memory_binding)` 是 host-owned envelope；Runtime DB 中没有 Task、parent/child、relation 或 binding 表。证据：`integrations/python-client/src/milai_client/task_state.py:56-208`；`runtime/src/milai/domain/context_preparation.py:76-108`。
7. **Task continuity 是 process-local、host-evidence-driven 的。** `HostTaskRegistry` 维护 lane、parent/child、suspended 状态和 CAS revision；重启后丢失。跨 session 是否由外部 OpenWorker 持久化并重送 task payload 为 `[UNKNOWN]`。
8. **Need 与 task relation 均为 deterministic heuristic，不由 LLM 决定。** Need resolver 使用英文 lexical/regex 规则；Task resolver 只使用 host task ID、lane、scope/profile 和显式 relation，不读取用户文本、memory 或模型。证据：`milai_client/memory_need.py::DeterministicMemoryNeedResolver`；`milai_openworker_mcp/task_binding.py:89-219`。
9. **CACHE 不是 Redis/DB cache lookup。** Host 保存已编译 Context slot；Runtime 验证 HMAC token、typed Need coverage、task/profile/scope binding、全局 outbox frontier、OpenIssue revisions 和 TTL。miss 是终态，只返回 recommended route，不自动 retrieval。证据：`runtime/src/milai/application/context_preparation.py:458-575`。
10. **代码中没有命名的 `FastPath` class。** eval 把 `{NONE, CACHE, L0}` 定义为 fast routes；Runtime 另有 canonical-gated progressive L1 early stop。FastPath metrics 是 route/control-plane diagnostic，不是 answer-quality metric。
11. **FTS/vector/cache/Context 不是 source of truth。** L0/L1 candidate 必须经 canonical Gate；Context build 又按 trace policy re-gate；projection/reranker outage 只能降 recall，canonical DB/gate outage 必须 abstain/503。
12. **持久化 trace 覆盖 retrieval/chat/canonical/projection，但 prepare-context route trace 主要是 response-local/Host JSONL。** Normal OpenWorker answer 不写 Runtime ChatTurn、Evidence 或 canonical state，只写 adapter JSONL 与 hash-chained provider ledger。
13. **测试资产广，但主产品组合路径不在必跑 CI。** `openworker-mcp` 未进入 integration matrix；保存的 runtime full gate 实际 skip 了缺少 `milai_client` 的 composite controller test。
14. **研发状态是 scoped candidate，而非 production-complete。** DG10 functional/synthetic accepted；DG11 functional frozen、quality target 未建立；DG12 correctness/equivalence 部分 PASS 但 performance terminal miss；formal 100×11 尚无 generations/scores；OSPC novelty path 已 ABANDON。
15. **当前最高优先级的 observed correctness concern 是 OpenWorker 可把 user-role 中形似 recall 的 JSON 当成 memory tool result。** 该对象可直接进入 `prepare_prefetch()` 并以 `AVAILABLE` Context 注入 provider，未经过 MCP/Runtime canonical Gate；现有测试未覆盖 user spoof 负例。详见第 13 节 R1。

---

## 2. Repository Map

### 2.1 核心目录

```text
MiLAi/
├── AGENTS.md                         # 当前状态板与项目级工作规则
├── MiLAi_Lean_V1_实施合同.md          # 实施合同；不是实现证明
├── architecture/
│   ├── v1.0/                         # FROZEN logical architecture、invariants、lock/tests
│   └── v1.0-candidate/               # 已接受 candidate 的历史链
├── runtime/
│   ├── src/milai/
│   │   ├── api/                      # Flask routes、auth、app composition、CLI
│   │   ├── application/              # Evidence/Proposal/Retrieval/Context/Chat/Episode services
│   │   ├── domain/                   # Pydantic request、Need、coverage、causal token
│   │   ├── persistence/              # PostgreSQL repositories、role-scoped sessions
│   │   ├── adapters/                 # local CAS、embedding、reranker
│   │   ├── workers/                  # Outbox projection/purge worker
│   │   └── operations/               # init/start/doctor/backup/restore/rebuild
│   ├── migrations/versions/          # Alembic 0001–0028；当前 schema source
│   ├── tests/                        # unit/contract/integration/concurrency/security
│   ├── compose.yaml                  # PostgreSQL/pgvector local deployment
│   ├── pyproject.toml
│   └── uv.lock
├── integrations/
│   ├── python-client/                # typed SDK、Need、Context compiler、TaskMemoryController
│   ├── mcp/                          # profile-scoped stdio MCP tools
│   ├── openworker-mcp/               # primary host adapter、UDS relay/broker、task registry/provider
│   ├── langgraph/                    # secondary portability adapter
│   ├── autogen/                      # secondary portability adapter
│   └── hooks/                        # coding-agent lifecycle hooks
├── contracts/agent/                  # agent-facing wire/behavior contracts
├── evals/
│   ├── agent_integration/            # E2E/shadow/FastPath/task-control diagnostics
│   ├── agent_efficiency/             # local efficiency/provider evidence protocol
│   ├── benchmark/                    # DG11 measurement
│   ├── dg10/, dg12/                  # experiment harnesses
│   ├── paper/                        # formal plan/runner/scorers
│   ├── datasets/, protocols/, scorers/
│   └── tests/
├── research/ospc/                    # isolated OSPC research harness + retained pilot
├── scripts/                           # DG10/11/12 builders/runners/gates
├── tests/                             # root research/release/regression tests
├── docs/                              # ADR、runbook、report、review、security
├── var/                               # retained DG10/11/12 state/results/ledgers
├── dist/                              # packaged historical experiment artifacts
└── .github/workflows/ci.yml           # current CI definition
```

生成物、`.venv`、`__pycache__`、cache 和大批 retained result 没有被当作模块边界；`var/` 只作为低于 tests 的历史 execution evidence。

### 2.2 工程形态

| 项目 | Current implementation |
|---|---|
| 主要语言 | Python；数据库逻辑为 PostgreSQL SQL/Alembic；另有 Bash、Docker/Compose、少量 HTML/JS/CSS |
| Package structure | 没有 root Python package；`runtime` 与 6 个 integrations 各自独立 package |
| 依赖管理 | Hatch build backend + `uv.lock`；`runtime`、各 integration、`evals/dg10` 分别锁依赖 |
| Runtime dependencies | Flask, Waitress, Psycopg pool, SQLAlchemy/Alembic, Pydantic Settings, Cryptography；optional NumPy/ONNX/tokenizers |
| Test framework | pytest 8 为主；frozen architecture 与 OSPC 同时使用 `unittest` |
| Eval framework | repository-local Python harness/scorer，不是单一第三方 eval framework |
| Configuration | frozen `RuntimeSettings` + `MILAI_*` env allowlist；OpenWorker/MCP 各自 CLI/policy/manifest |
| Persistence | PostgreSQL 16 + pgvector；tenant-scoped local filesystem CAS；Host in-memory slot/registry；JSONL ledgers |
| External model/provider | Runtime Chat 无 answer model；OpenWorker `ProviderExecutionGateway` 只允许 manifest 授权的 local/loopback provider |
| Logging/tracing | structured runtime logs；PostgreSQL trace/audit tables；OpenWorker adapter JSONL；hash-chained provider ledger；eval artifacts |
| Experiment infra | DG10/11/12 scripts、sealed manifests、state JSON、formal paper runner、OSPC isolated harness |

### 2.3 Git / development context

**Observed：** 当前 branch 为 `main`，但 repository 没有任何 commit；`git ls-files` 为 0，所有内容均显示 untracked，`git log` 不可用。因此无法依据 commit frequency 判断“最近频繁变化的模块”，也无法证明 hosted CI run 或 artifact-to-commit provenance。

- Current branch：`main`；`No commits yet`。
- Uncommitted state：整个 repository。
- `[UNKNOWN]` 当前目录是否是从其他 VCS/export 恢复的 working snapshot。
- `[INFERENCE]` `var/` 中带 hash/manifest 的结果可作为 retained evidence，但不是 Git-backed chain of custody，也不是本轮重跑证明。

---

## 3. Runtime Architecture

### 3.1 当前组件图

```text
                         ┌─────────────────────────────────────┐
User / OpenAI-compatible│ OpenWorker Host Adapter             │
chat-completions ───────▶│ Task bind → Need → Route → Slot     │
                         │ → Context compile → Provider gateway │
                         └───────┬──────────────────────┬──────┘
                                 │ prefetch UDS         │ local provider
                                 │ or visible tool call │ completion
                         ┌───────▼────────┐      ┌──────▼────────────┐
                         │ relay / broker │      │ local vLLM/provider│
                         │ policy + peer  │      │ capability/budget  │
                         └───────┬────────┘      └───────────────────┘
                                 │ stdio MCP child
                         ┌───────▼────────┐
                         │ milai-mcp      │
                         │ profile tools │
                         └───────┬────────┘
                                 │ loopback HTTP
┌────────────────────────────────▼────────────────────────────────────┐
│ Flask / Waitress MiLA Runtime                                      │
│ Evidence │ Proposal/Review │ Retrieval │ PrepareContext │ Chat     │
│ Episode  │ Revoke          │ Context   │ Causality       │ Ops     │
└───────────────┬─────────────────────────────┬───────────────────────┘
                │ role-scoped SQL             │ content bytes
        ┌───────▼──────────────────┐    ┌─────▼───────────────────┐
        │ PostgreSQL + pgvector    │    │ tenant local CAS        │
        │ canonical + trace + index│    │ content-addressed blobs │
        └──────────┬───────────────┘    └─────────────────────────┘
                   │ Outbox
            ┌──────▼───────────┐
            │ FoundationWorker │
            │ purge → FTS → vec│
            └──────────────────┘
```

### 3.2 真正的控制 owner

- **一次 OpenWorker execution：** `OpenWorkerProviderAdapter.complete()` 拥有 task binding、Need、route、MCP prefetch/tool call、Context compile、provider call 与 terminal fallback。
- **一次 Runtime retrieval/context：** `RetrievalService.retrieve()` 与 `PrepareContextService.prepare()` 控制；Host 提供 Need 与初始 route，Runtime 做 fail-closed override 和 Gate。
- **一次 canonical mutation：** steward-authorized PostgreSQL `SECURITY DEFINER` procedure 拥有最终控制权。
- **一次 projection/purge：** `FoundationWorker` 选择 lane，PostgreSQL delivery procedures 拥有 lease/order/watermark 状态。
- **Runtime `/v1/chat`：** `ChatService.chat()` 独立控制，固定 L1，不进入 Host task-memory control plane。

### 3.3 决策所有权

| Decision | Owner | Input | Output | Implementation |
|---|---|---|---|---|
| Task relation | OpenWorker Host | task registry snapshot、host task payload/relation、lane、scope/profile | CONTINUE/SUBTASK/SWITCH/RETURN/AMBIGUOUS | deterministic；`task_binding.py::DeterministicTaskRelationResolver.resolve()` |
| Memory Need | OpenWorker Host | current question、known state keys/claims/issues、prior Need | typed Need + L0/L1/NONE | lexical heuristic；`memory_need.py::DeterministicMemoryNeedResolver.resolve()` |
| CACHE candidate | OpenWorker Host | same Need signature、retained slot、eligible relation、safe event | CACHE 或 resolver route | `host_adapter.py:102-127::_requested_memory_route()` |
| Route safety override | Runtime | requested route、event、action/state locator | NONE/CACHE/L0/L1 | deterministic；`context_preparation.py:838-851::_validated_route()` |
| Cache hit | Runtime + signed state + DB | token、Need coverage、binding、frontier、issues、deadline | UNCHANGED 或 terminal miss | `context_preparation.py:458-575`; `context_validation.py::need_covered()` |
| QueryPlan | Runtime | RetrievalRequest/query/policy | versioned plan/operator | deterministic regex；`query_planner.py::QueryPlanner.plan()` |
| Candidate recall/rank | Runtime/index/config | exact/FTS/vector/recent candidates | ranked candidates | heuristic RRF/MMR/temporal/optional reranker |
| Truth applicability | PostgreSQL ECS/Gate | candidate + all policy axes + current canonical state | accept/reject + reason | authoritative deterministic SQL；migration `0017` |
| Progressive stop | Runtime | typed intent、gate result、OpenIssue、RYW/operator/provenance | stop after FTS/vector or continue | `retrieval.py:721-766::_progressive_l1_sufficient()` |
| Context compression | Runtime | six protected sections、byte budget | FULL/COMPACT/MINIMAL | `application/context.py:33-53,79-194` |
| Token-level Context budget | Python client controller | tokenizer/budget/compiler inputs | rendered Host slot | `optimization.py::GovernedContextCompiler`; Runtime itself does not enforce token count |
| Runtime Chat answer | Runtime | gated results + issue IDs | deterministic Chinese text | `chat.py:287-296::_compose_answer()` |
| Memory tool route/call | OpenWorker adapter + external Host loop | memory mode、visible tool schema、presence of tool result | deterministic recall tool call或continue | `host_adapter.py:1136-1166`; provider不参与该route decision |
| Provider answer | local model | compiled messages | completion content | `provider_execution.py::ProviderExecutionGateway.execute()` |
| Proposal relation | Runtime | caller-supplied operation/patch + current head | CREATE/UPDATE/CONFLICT/NO_CHANGE | deterministic `DeriveAndDiagnose` |
| Commit eligibility | Runtime policy | validated proposal | USER_REVIEW | fixed `CommitPolicy.decide()` |
| Canonical commit | steward procedure | approved proposal、expected head/revision、Evidence refs | version/head/issue/history/outbox | PostgreSQL transaction/CAS |
| Write/capture | explicit caller/profile | Evidence or Proposal request | persisted noncanonical object | no implicit ordinary-turn write |
| Invalidate/revoke | operator/steward | Evidence ID、confirmation/idempotency | block + Context invalidation + deletion workflow | governed TX-05 |

### 3.4 主要依赖图与 coupling

```text
OpenWorker host_adapter
 ├─ milai_client task_state / memory_need / task_memory / context_policy
 ├─ milai_openworker_mcp task_binding / transport / provider_execution
 └─ MCP UDS wire
      └─ broker → milai-mcp → milai-client HTTP → Runtime API

Runtime API app
 ├─ Application services
 │   ├─ Domain request/policy objects
 │   ├─ Persistence repositories ── SQL procedure names/migration schema
 │   └─ Blob/embedding/reranker adapters
 └─ Flask current_app.extensions service locator

PostgreSQL Outbox ── FoundationWorker ── ProjectionRepository + BlobStore
```

Observed coupling：

- Runtime package不 import integrations；`runtime/tests/unit/test_external_dependency_boundary.py` 与 `tests/test_product_architecture.py` 固化此边界。
- integrations 通过 HTTP/MCP wire 和 duplicated typed envelopes 依赖 Runtime contract，不依赖 Runtime internals。
- repositories 以 SQL function/procedure 字符串强耦合 migrations。
- `ContextRepository.material()` 同时知道 RetrievalTrace、Gate、ClaimVersion、OpenIssue、Evidence/Blob，是明确跨层模块。
- canonical schema 存在有意的 deferrable FK cycle：`ClaimVersion ↔ StewardDecision`、`OpenIssue ↔ StewardDecision`；procedure 必须在单事务中构造完整图（`0004_canonical_state_schema.py:285-290,570-590`）。
- global/process mutable state 包括 `HostTaskRegistry`、retained task contexts、last Need、pending recall、client `SessionSlotRegistry`；它们有锁，但均不跨进程重启。
- `[INFERENCE]` 静态 import 审阅未发现 active Python circular import；数据库图中存在上述显式 cycle。

### 3.5 所有主要入口

| 类型 | Entry file / symbol | 下一层 | 最终 runtime/orchestrator |
|---|---|---|---|
| Runtime API | `runtime/pyproject.toml` → `milai.api.cli:main` | `api.app.create_app()` → Waitress | Flask service graph |
| Runtime worker | `milai.workers.main:main` | `FoundationWorker.run()/run_once()` | projection/purge loop |
| DB check | `milai.persistence.cli:main` | `Database.ping()` | role-attested PostgreSQL |
| Ops CLI | `milai.operations.cli:main` | init/start/stop/doctor/smoke/backup/restore/rebuild | local runtime orchestrator |
| MCP server | `integrations/mcp/.../server.py::main()` | `build_server()` + profile tools | `AsyncMilaiClient` → Runtime HTTP |
| OpenWorker relay | `milai_openworker_mcp.relay:main` | `relay()` | validated UDS byte relay |
| OpenWorker broker | `milai_openworker_mcp.broker:main` | `Broker.run()` / `_serve_connection()` | exact `milai-mcp --profile` child |
| OpenWorker adapter | `milai_openworker_mcp.host_adapter:main` | `Handler.do_POST()` | `OpenWorkerProviderAdapter.complete()` |
| Hook CLI | `milai_hooks.cli:main` / `config:main` | lifecycle hook | Python client |
| FastPath eval | `evals/agent_integration/fast_path_shadow.py::main()` | `run_shadow()` / `_summarize()` | synthetic route/task diagnostic |
| OSPC benchmark | `research/ospc/run_benchmark.py::main()` | fixture runner/scorer | isolated research harness |
| DG12 eval | `evals/dg12/eh04_reconfirmation.py::main()`；`evals/paper/dg12_v3/runner.py` | frozen harness/producer/scorer | research execution plane |
| Test harness | pytest via each `pyproject.toml`; architecture/OSPC unittest | unit/integration suites | CI workflow |

---

## 4. End-to-End Execution Path

### 4.1 主产品路径：OpenWorker prefetch mode

```text
1  POST /v1/chat/completions
   host_adapter.py::Handler.do_POST()
        ↓
2  parse messages / question / request-local IDs
   host_adapter.py::_messages(), _question(), _logical_request_id()
        ↓
3  bind host Task state
   OpenWorkerProviderAdapter._bind_task_state()
   → TaskMemoryState.from_host_payload()
   → bind_host_task()
   → DeterministicTaskRelationResolver
   → HostTaskRegistry CAS transition
        ↓
4  resolve typed Memory Need
   DeterministicMemoryNeedResolver.resolve()
        ↓
5  choose requested route
   _requested_memory_route(): NONE / CACHE / L0 / L1
        ↓
6  TaskMemoryController.prepare_context()
   → McpUnixClient.prepare_memory_context()
   → persistent UDS
   → Broker._serve_connection()
   → per-connection milai-mcp child
   → MCP milai_prepare_context
   → Runtime POST /v1/memory/prepare-context
        ↓
7  Runtime typed policy + route + CACHE/retrieval
   context_routes.prepare_context()
   → PrepareContextService.prepare()
   → RetrievalService.retrieve() when route L0/L1
   → QueryPlanner → exact/FTS/vector → canonical Gate
   → persistent RetrievalTrace
   → ContextService.build() → persistent ContextCapsule/pointers
   → signed validation token + slot coverage
        ↓
8  Host validates envelope and compiles slot
   TaskMemoryController + GovernedContextCompiler
   → retained process-local task context
   → PrefetchContext
        ↓
9  compile execution Context
   context_policy.py::compile_agent_messages()
        ↓
10 provider execution
   ProviderExecutionGateway.execute()
   → budget/capability reservation in hash-chained ledger
   → loopback completion transport
        ↓
11 final OpenAI-compatible response
   host_adapter.py::_completion()
        ↓
12 post-turn writes
   adapter JSONL + provider ledger only
```

关键文件：

- 输入：`integrations/openworker-mcp/src/milai_openworker_mcp/host_adapter.py:1265-1364::Handler/main`。
- Task：同文件 `:548-669::_bind_task_state()`；`task_binding.py:89-315`。
- Need/route：同文件 `:102-127,671-910`；`integrations/python-client/src/milai_client/memory_need.py:137-262`。
- UDS/MCP：`transport.py::McpUnixClient.prepare_memory_context()`；`broker.py:357-535`；`integrations/mcp/src/milai_mcp/server.py:97-463`。
- Runtime composite：`runtime/src/milai/api/context_routes.py:90-103`；`runtime/src/milai/application/context_preparation.py:55-575`。
- Provider：`provider_execution.py:499-699::ProviderExecutionGateway`；`host_adapter.py:1191-1262`。

**ID ownership：** HTTP handler 不生成 Runtime session/turn record。task ID 优先取 incoming `user`，其次 `--task-session-id`，否则按 run/request sequence 生成；Runtime request ID 由合法 `X-Request-ID` 或 UUID4 产生。`session_id/agent_id/profile_id/task_epoch` 由 Host 填入 prepare-context，只用于 binding/token，不在 Runtime DB 建 Task。

**Post-turn update：** normal provider answer 不调用 Evidence ingest、Proposal、review、Episode settlement 或 Runtime Chat；因此不会更新 memory truth、StateView、Runtime cache table或 ChatTurn。Host 仅更新 process-local retained slot/last Need，并追加 JSONL/ledger。

### 4.2 主产品可见 tool route（auto mode）

```text
first model-facing turn
OpenWorker request with milai_recall tool
→ host_adapter emits tool_calls, provider is not called
→ OpenWorker executes milai-mcp-relay stdio
→ UDS broker → milai-mcp::milai_recall
→ Runtime /v1/memory/query
→ tool result added to next messages
→ host_adapter extracts recall object
→ prepare_prefetch() → compile_agent_messages()
→ ProviderExecutionGateway → final response
```

此路径与 prefetch path 的关键差异：

- `auto` 暴露 `milai_recall` 给 Host/model tool loop；`prefetch` 使用隐藏 composite `milai_prepare_context`。
- `relay.py::relay()` 在 visible tool path 使用；prefetch 的 `McpUnixClient` 可直接连 broker socket，不经过 relay executable。
- MCP profile/policy由 broker `_bind_effective_need_policy()` 覆盖；reader-lite 不把 composite tool列入 model-visible tools。
- 如果缺 tool、tool result 未出现或 MCP/context unavailable，Host 返回 `UNKNOWN`，通常不调用 provider（`host_adapter.py:1122-1189`）。

### 4.3 独立 Runtime `/v1/chat` 路径

```text
POST /v1/chat
→ api/context_routes.py::chat()
→ ChatRequest.model_validate()
→ ChatService.chat()
   ├─ optional live USER_CONFIRMATION Evidence check
   ├─ hard-coded RetrievalRequest(route="L1", limit=5)
   ├─ RetrievalService.retrieve()
   │   → QueryPlanner.plan()
   │   → exact + FTS + vector/recent/fallback
   │   → canonical Gate
   │   → RetrievalTrace write
   ├─ ContextService.build()
   │   → trace-bound re-gate
   │   → six-section ContextCapsule/pointers write
   ├─ _compose_answer() deterministic renderer
   └─ ChatTurn write
→ HTTP response
```

证据：`runtime/src/milai/api/context_routes.py:147-159`；`runtime/src/milai/application/chat.py:40-209,287-329`；`runtime/src/milai/persistence/context_repository.py:342-408`。

该路径的真实例外：

| Condition | Behavior | Writes |
|---|---|---|
| action-sensitive 且无 live confirmation | 不 retrieval；模板 abstain | ChatTurn，无 RetrievalTrace/Capsule |
| canonical DB/Gate unavailable | HTTP 503 / `CANONICAL_UNAVAILABLE` | 无 RetrievalTrace、无 ChatTurn |
| retrieval 成功执行但无安全结果 | abstain | RetrievalTrace + abstained ChatTurn；无 Capsule |
| successful result | build capsule；模板 answer | RetrievalTrace + Capsule/pointers + ChatTurn |

**Observed：** `/v1/chat` 不调用 `PrepareContextService`，所以没有 Memory Need、CACHE、task relation、Host route 或 ACTION_VALIDATE；`derived_result` 也没有进入 `_compose_answer()`。

### 4.4 Memory 写链与 answer 链是分离的

```text
Explicit observation
→ POST /v1/evidence
→ EvidenceService.ingest
→ CAS bytes + TX-01 EvidenceRecord/outbox

Explicit candidate
→ POST /v1/proposals
→ DeriveAndDiagnose (classify supplied patch)
→ CommitPolicy = USER_REVIEW
→ persistent noncanonical OperationProposal

Explicit review
→ POST /v1/proposals/{id}/review
→ steward DB role + canonical procedure/CAS
→ Claim/Version/Head or OpenIssue + history/outbox

Later execution
→ retrieval/Gate/Context
```

没有现成 orchestrator 把普通 turn 自动串成上述三步；这不是根据设计补齐的推测，而是当前调用图事实。

---

## 5. Core Data Model

### 5.1 Execution / memory 核心对象

| Object | File | Owner | Persistent? | Mutable? | Main fields / identity | Created by | Read by |
|---|---|---|---|---|---|---|---|
| `SessionContext` | `runtime/src/milai/persistence/database.py:27` | Runtime auth | No，request/transaction-local | frozen | tenant_id, actor_id | `authenticated_context()` | all repositories |
| `EvidenceRecord` | `persistence/evidence_repository.py:40`; migration `0003` | Evidence plane / DB | Yes | identity immutable；revoke/retention mutable | evidence_id, source_type/ref, subject, observed/captured time, blob/hash, permission, retention | TX-01 | Gate, Context, lineage, Chat, deletion |
| `ContentBlob` | migration `0003_evidence_plane.py:35-61` + BlobStore | DB metadata + filesystem CAS | Yes | physical state/key metadata mutable | tenant/blob ID, URI, length, media, delete/erasure state | Evidence ingest | Evidence/pointer/deletion/worker |
| `OperationProposal` | migration `0004:71-144`; domain `proposals.py` | proposal service / DB | Yes | status only | operation, patch, evidence refs, scope, authority, derivation snapshot | explicit caller | steward review/audit |
| `Claim` | migration `0004:49-70` | canonical DB | Yes | append-only identity | unique subject/predicate/claim_type | approved CREATE | Head/ECS/retrieval |
| `ClaimVersion` | migration `0004:252-328` + later axes | canonical DB | Yes | append-only | payload, scope, valid/system time, lifecycle/epistemic/freshness/confidence/authority, provenance | steward procedure | ECS/Gate/retrieval/context |
| `ClaimHead` | migration `0004:329-360` | canonical DB | Yes | exact-head CAS | claim_id → current_claim_version_id | canonical procedure | L0/ECS/cache coverage |
| `OpenIssue` | migration `0004:180-251` | canonical DB | Yes | identity fixed；status/revision CAS | type, target, branches, scope, discharge, authority, status, revision | conflict/revoke/review | ECS, Context, cache validation |
| `GroundingRelation` | migration `0004:412-472` | canonical provenance | Yes | append-only | XOR ClaimVersion/OpenIssue → Evidence, relation type, proposal | canonical procedure | lineage/Gate/Context |
| `GroundingBlock` | migration `0004:473-532` | canonical validity | Yes | controlled active→released | version, cause, type, restoration/release | revoke/reground | ECS/Gate |
| `StewardDecision` / transitions | migrations `0004`, `0015`, `0024` | governance/history | Yes | append-only | proposal, actor/policy/reason/result/sequence；old/new edge | steward procedure | replay/audit |
| `effective_claim_state` | migrations `0017` | PostgreSQL | derived view | recomputed | current head + all applicability axes/blocks/issues | SQL view | Gate/L0 |
| `RetrievalRequest` / `QueryPlan` | `domain/retrieval.py:31-102` | caller / planner | request-local；plan copied to trace | frozen Pydantic | route/query/locators/policy/time/causal; deterministic operator | API/PrepareContext + QueryPlanner | RetrievalService/trace |
| `RetrievalTrace` | migration `0008`; repository `RetrievalTraceCommand` | RetrievalService / DB | Yes | append-only | plan, snapshot/watermarks, accepted/rejected, fallback, abstention, causal wait | every successful retrieval execution | Context/Chat/audit |
| `StateKeyRef` | `domain/context_preparation.py:25-37`; client mirror | Host | No | frozen | scope + subject/predicate/type + optional claim/issues/frontier | Host Need resolver | route/L0/coverage；must be revalidated |
| `MemoryNeedSignature` | `domain/context_preparation.py:40-62`; client mirror | Host | No | frozen/hash-addressed | scope, authority, consistency, claims/keys/issues, temporal/evidence/intent | deterministic Need resolver or external caller | route/cache/retrieval |
| `MemorySlotCoverage` | `domain/context_validation.py:50-81` | Runtime | token payload, not DB row | frozen | exact heads/state keys/issue revisions/policy/frontier/depth | PrepareContext | `need_covered()` / next CACHE |
| `ContextValidationState` | `domain/context_validation.py:153-290` | Runtime token codec | HMAC token only | renewed on hit | binding, frontier/issues, capsule/hash, counters, issued/expires | PrepareContext | next CACHE turn |
| `ContextCapsule` | migrations `0006`, `0009`; `application/context.py` | Runtime Context / DB | Yes, TTL | invalidate/purge/expire | six sections, trace, hash, budget, status, expires | ContextService + DB procedure | Chat, pointer recovery, Episode, Host response |
| `ContextPointer` | migrations `0006`, `0009` | Runtime Context / DB | Yes, TTL-bound | invalidate/purge | capsule/evidence/hash + permission/retention snapshots | Context procedure | explicit recovery |
| `ChatTurn` | migration `0009`; `RecordChatCommand` | Runtime Chat / DB | Yes | append-only | answer, capsule/trace, refs, action/confirmation/abstention | Runtime `/chat` only | replay/audit/Episode |
| `Episode` / settlement | domain `episodes.py`; migration `0011` | Runtime/Steward DB | Yes | status/revision CAS + append-only history | Evidence/Chat/Capsule refs, residual proposals/issues | explicit capture/settle | replay/operations |
| `DeletionRequest` | migrations `0006`, `0019` | TX-05/worker | Yes | workflow progress mutable | evidence/blob, logical/index/context/blob/backup progress, proof/errors | revoke | API/worker/audit |
| `ProjectionDelivery` / `IndexWatermark` | migration `0007` | worker/DB | Yes | lease/retry/watermark mutable | projection + outbox event / contiguous sequence | worker procedures | worker/RYW/status |
| search document/embedding stores | migrations `0007`, `0028` | worker | Yes, replaceable | rebuild/purge/replace | ClaimVersion text/16d embedding；fragment/window/128d embedding | projection worker | L1 retrieval |
| `TaskIdentityState` | client `task_state.py:56-130` | Host | No | immutable snapshots replaced | task/parent/status/generations/scope/profile/goal/lane/ops/workspace/artifacts/epochs | host payload/fallback | relation resolver/registry/adapter |
| `TaskMemoryBinding` | client `task_state.py:133-163` | Host | No | immutable snapshots replaced | task ID, known claims/keys/issues, frontier, slot ID/token/coverage | host payload/registry | Need/cache candidate |
| `TaskMemoryState` | client `task_state.py:166-208` | Host | No | frozen envelope | explicit identity + memory_binding separation | host payload parser | task binding |
| `TaskMemoryIdentity` | client `task_memory.py:47-68` | Host cache controller | No | frozen | tenant/session/agent/profile/task_epoch | adapter | TaskMemoryController slot key |
| `TaskMemorySlot` / `MemorySlot` | client `task_memory.py`, `optimization.py` | Host | process-local | replaced/evicted | token/coverage/context/digests/usage | TaskMemoryController/compiler | next turn/provider prompt |
| `TaskRelationDecision` / `TaskBindingContext` | client `task_state.py:372-457` | Host | turn-local | frozen | relation/confidence/reasons/compatibility/cache constraint/transition revisions | resolver/registry | adapter trace/route |
| adapter/provider trace | OpenWorker JSONL + ledger | Host/provider gateway | filesystem persistent for run | append-only | route/timing/hash/capability/budget/provider result | adapter/gateway | experiment audit |

### 5.2 Identity、state、pointer 与 lifetime

- **Identity objects：** Evidence ID + immutable source/hash；Claim business identity；ClaimVersion ID/version number；OpenIssue ID/revision；TaskIdentityState.task_id/generation；TaskMemoryIdentity 的 execution binding tuple。
- **Current state：** ClaimHead + ECS + live OpenIssue + active GroundingBlock；Host 当前 task则由 process-local registry snapshot表示。
- **Pointers/references：** ClaimHead、StateKeyRef、ContextPointer、TaskMemoryBinding known IDs/slot fields、CausalPosition token。它们本身不提升 truth。
- **Long-lived source of truth：** Evidence metadata/CAS，canonical/history/governance tables，deletion workflow truth。
- **Durable audit but not truth：** RetrievalTrace、ChatTurn、Episode、OperationalEvent、Outbox、provider/eval ledgers。
- **Derived persistent state：** ECS view、search indexes、ContextCapsule/pointers、projection deliveries/watermarks。
- **Turn/process-local state：** Need、route decision、Host registry/slot/last Need/pending recall、compiled prompt、prepare-context execution trace。

### 5.3 Semantic duplication audit

| Concepts compared | Classification | Evidence-based reason |
|---|---|---|
| `Claim` / `ClaimVersion` / `ClaimHead` | Intentional separation | stable identity、immutable version、mutable current pointer有不同 writer/lifecycle |
| `EvidenceRecord` / `ContentBlob` | Intentional separation | independent observations may dedupe tenant bytes；source identity不能与 bytes storage 合并 |
| Runtime/client `MemoryNeedSignature`、`StateKeyRef` | Intentional wire mirror | 相同 contract 分别用于 server validation 和 standalone integration package；依赖边界禁止 import runtime internals |
| `TaskIdentityState` / `TaskMemoryIdentity` | Intentional separation | 前者是 host semantic task；后者是窄的 cache token binding tuple |
| `TaskMemoryBinding` / `TaskMemorySlot` / `MemorySlot` | Potential overlap | 都携带 slot/token/coverage语义；shipped adapter实际用 controller private slot，未把新 slot完整 round-trip 回 host payload |
| `ContextCapsule` / `PrefetchContext` / compiled `MemorySlot` | Intentional staged representations | DB governed material → Host-safe view → token-budgeted prompt/cache；不同 owner/lifetime |
| `DeterministicRecallRouter` + `SessionSlotRegistry` / Need resolver + `TaskMemoryController` | Potential overlap | generic client lifecycle和主 OpenWorker composite path分别拥有 route/cache control，存在行为漂移可能 |
| `OutboxEvent.state/lease/...` / `ProjectionDelivery` | Potential overlap / likely legacy fields | production worker使用后者；静态搜索未见更新前者 delivery fields |
| 16d search projection / 128d window projection | Intentional compatibility, retirement `[UNKNOWN]` | migration 0028 保留两套，当前不能判定旧路径 deprecated |
| `integrations/openworker-mcp/adapter.py` / `host_adapter.py` | Deprecated/inactive source vs active | wheel显式 exclude `adapter.py`；product architecture test将其视为 inactive |

---

## 6. Evidence → StateView → Context Mapping

### 6.1 模块映射

| Module | Current responsibility | Logical layer | Notes |
|---|---|---|---|
| `application/evidence.py`, `evidence_repository.py`, BlobStore | capture/source/hash/body access | Evidence | ingest不自动变成 Claim |
| `operational_event`, Outbox, transition tables, ChatTurn, provider ledger | what happened / replay records | Evidence-like trace / Infrastructure | ChatTurn不是 canonical EvidenceRecord |
| canonical repositories + migrations 0004/0015/0017/0024 | governed belief evolution | StateView / Storage | formal writer是DB procedure |
| `effective_claim_state`, canonical Gate | resolve current applicability | StateView | 唯一 authoritative applicability boundary |
| `OpenIssue`, `GroundingBlock` | unresolved/invalid current state | StateView | 不是“附注”；会影响 Gate/Context/cache |
| `RetrievalService` | recall candidates + Gate + trace | StateView → Context / Control | 同时做 candidate selection和state validation，跨层 |
| FTS/vector/fragments | derived candidate lookup | Context support / Index | outage只能降 recall，不能自封 authority |
| `ContextRepository.material()` | trace lookup、re-gate、hydrate Evidence/issues | StateView → Context | 明确跨层且知道多种存储对象 |
| `ContextService`, Capsule/pointers | execution-conditioned six-section working set | Context | persistent但TTL/derived，不是 truth |
| Need/route/coverage/token | what current execution needs + reuse proof | Context control | Host生成Need；Runtime验证 |
| TaskMemoryController/compiler/PrefetchContext | Host slot、token budget、prompt assembly | Context / Runtime control | process-local |
| OpenWorker task registry/relation | current execution/task continuity | Runtime / Host StateView | 不属于 canonical memory StateView，且未持久化 |
| Flask app/services/MCP/broker/provider gateway/worker | orchestration、trust boundary、execution | Runtime / Infrastructure | ownership分散但路径可追踪 |
| tests/evals/var artifacts | contracts、diagnostics、research evidence | Evaluation | retained结果不等于本轮 pass |

### 6.2 单层与跨层行为

**明确单层：** CAS + EvidenceRecord（Evidence）；Claim/Version/Head/OpenIssue/ECS（StateView）；ContextCapsule/compiler prompt（Context）；projection delivery/worker（Infrastructure）。

**Evidence 与 State 混合：** `GroundingRelation` 是 State validity的一部分，同时连接 Evidence provenance；`RetrievalTrace`/`ChatTurn` 是 execution evidence，但不会自动成为 EvidenceRecord 或 belief。

**State 与 Context 混合：** `RetrievalService` 在一次服务内同时召回 Context candidates、调用 ECS/Gate解析StateView并持久化trace；`ContextRepository.material()` 又重新 Gate。

**Context 可能反向成为 truth source 的 observed exception：** 正常 Runtime path禁止这一点，但 active OpenWorker adapter 会扫描 `role in {tool,user}` 的任意 nested JSON；只要含 string `status`、list `items`、list `open_issue_ids` 就作为 recall result，直接由 `prepare_prefetch()` 渲染。user-role 伪造对象不经过 Runtime Gate，详见 R1。

**Ownership 不清楚的状态：** TaskMemoryBinding声明slot/token/coverage，实际 retained slot归 TaskMemoryController私有；ContextCapsule TTL与Host token TTL分别更新；跨session task owner在repository中未找到。

### 6.3 Intended design 对照

| Topic | Documented | Implemented | Status |
|---|---|---|---|
| Online answer chain | Evidence → StateView → Context → Model → Answer/Trace | 主 OpenWorker路径大体符合；Runtime `/chat`固定L1+模板，不调用模型；两条路径分立 | Partial / mismatch |
| DeriveAndDiagnose | 从 Evidence提取candidate、查询state、诊断relation/OpenIssue | caller已提供完整patch/operation；模块只观察head并分类 | Partial / mismatch |
| Context budget | token budget下的working set | Runtime只硬执行byte budget；token budget由外部client compiler执行 | Split ownership / partial |
| Chat response contract | `claim_refs`, `consistency_mode`, boolean `degraded` | `used_claim_version_ids`, `degraded_components`；无后两字段；tests按实现 | Code/tests vs contract mismatch |
| L1 | FTS+vector→Gate→bundle | typed current query可在canonical-gated FTS后progressive stop；tests固化 | Implemented extension; Gate preserved |
| Task continuity | long-lived task continuity | typed Host模型存在；registry/slot仅进程内，DB无Task | Partial；durable continuity `[UNKNOWN]` |
| Model/embedding client in Runtime | implementation contract列在线LLM/embedding | embedding/reranker存在；Runtime Chat无answer LLM；provider只在integration | Mismatch in Runtime, externalized in product path |
| OSPC status | AGENTS/README部分文字仍称pending | code/pilot/contract已terminal `ABANDON` | Documentation mismatch |

---

## 7. Task / Goal Model

### 7.1 Current task model

`TaskMemoryState` 明确由两部分组成：

```text
TaskMemoryState
├── TaskIdentityState
│   ├── task_id / parent_task_id / status
│   ├── task_generation / binding_generation
│   ├── project_scope / profile_identity
│   ├── active_goal_id / version / summary
│   ├── execution_lane_id / plan_node_id
│   ├── unresolved_operation_ids
│   └── workspace/artifacts/created/last-active epochs
└── TaskMemoryBinding
    ├── known_claim_ids / known_state_keys
    ├── relevant_open_issue_ids
    ├── canonical_position_seen
    └── slot_id / validation_handle / coverage
```

证据：`integrations/python-client/src/milai_client/task_state.py:56-208`。这是代码层面对 Task Identity 与 Task Memory Binding 的真实分离，不是根据设计强行映射。

### 7.2 创建、恢复与 relation

| Question | Current implementation |
|---|---|
| task如何创建 | Host传 `milai_task_state`；缺失时 `from_host_payload()` 创建 ACTIVE generation=1 fallback state。adapter task ID取 incoming `user` → configured `task_session_id` → per-request generated ID |
| task ID如何保持 | 依赖Host每turn发送稳定payload/`user`/configured session ID；Host registry按ID/lane保留 |
| 跨turn恢复 | 同一 adapter进程内 `HostTaskRegistry` + `_task_contexts` + last Need |
| 跨session恢复 | `[UNKNOWN]`；repository没有durable Task store。若外部Host不重送完整identity/binding，当前代码无法恢复 |
| parent/child | `parent_task_id` + registry `_parent_child_edges`；只在 SUBTASK structured relation创建 |
| current task | execution lane的 `_active_by_lane` 指针 |
| active goal | host payload的ID/version/summary；fallback为 `Continue the host-owned task.`；Runtime仅把summary用于binding/Context |
| current question | 当前messages最后的user text；不是TaskIdentity字段，不持久化为task state |
| status | enum ACTIVE/SUSPENDED/COMPLETED；registry transitions实际主要产生ACTIVE/SUSPENDED |
| continuation | same host task ID + compatible scope/profile；或same unresolved operation |
| subtask | explicit `SUBTASK` 且 incoming.parent_task_id == lane-active task |
| return/resume | suspended target + explicit RETURN/strong suspended task match，或lane为空时suspended candidate |
| switch | explicit SWITCH、completed unrelated lineage，或empty lane/task start |
| unknown/ambiguous | incompatible without explicit rebind，或insufficient host execution evidence → AMBIGUOUS → TENTATIVE empty binding；不改变registry；execution继续但NO_MEMORY |
| cache eligibility | 仅 CONTINUE、source存在且incoming identity完全相同，才 `ELIGIBLE_FOR_VALIDATION` |

Relation实现：`integrations/openworker-mcp/src/milai_openworker_mcp/task_binding.py:89-219,259-315`。它明确是“Pure lexicographic resolver with no model or memory-query dependency”；记录的 LLM/embedding/retrieval/training/hidden provider calls 均为0。

### 7.3 Partial / unconnected task behaviors

- `HostTaskRegistry.begin_operation()` / `bind_tool_result()` 与 `ExecutionBindingToken` 实现 delayed result/ABA/orphan判定，并有 unit tests；静态调用搜索未发现 active `host_adapter.py` 调用，故当前 shipped turn path中是 **Partial/unwired**。
- `COMPLETED` 状态可解析，但 active adapter transition没有清晰的 completion写路径；`completed_unrelated_lineage`也未由当前 request parsing提供，状态为 **Partial/unwired**。
- host payload内的 `TaskMemoryBinding.slot_id/slot_validation_handle/slot_coverage` 可解析；active adapter使用 `TaskMemoryController`私有slot，没有把新slot完整写回/持久化，形成 ownership ambiguity。
- Runtime `Episode` 不是Task；它只捕获 Evidence/Chat/Capsule refs并显式settle。

---

## 8. Memory Lifecycle

### 8.1 当前真实生命周期

```text
Explicit Evidence arrival
  ↓ data-mode / size / typed request validation
Local CAS write
  ↓
TX-01 EvidenceRecord + idempotency + operational event + outbox
  ↓
[separate explicit proposal]
caller-supplied patch + Evidence refs
  ↓ DeriveAndDiagnose classification
PENDING_REVIEW OperationProposal
  ↓ [explicit steward review]
Claim/ClaimVersion/Head OR OpenIssue + grounding/history/outbox
  ↓ FoundationWorker
FTS/vector/fragments projections (derived)
  ↓ query / Need-conditioned retrieval
exact + FTS + vector + fallback candidates
  ↓ ECS / canonical Gate
current valid StateView + provenance pointers
  ↓
RetrievalTrace → ContextCapsule/pointers → Host compiled slot/prompt
  ↓
Runtime template answer OR external provider execution
  ↓
ChatTurn or Host JSONL/provider ledger
  ↓
No implicit Evidence/Claim update
```

### 8.2 Operations

| Operation | Trigger | Input | Target | Side effect | Provenance behavior |
|---|---|---|---|---|---|
| write/ingest | explicit Evidence API/tool/client policy | source/content/time/classification/permission/retention/idempotency | CAS + ContentBlob/EvidenceRecord | outbox/event；same bytes tenant-dedupe但new observation | immutable source/hash；Evidence不是Claim |
| append proposal | explicit submitter/client | operation, patch, Evidence refs, expected state | OperationProposal | PENDING_REVIEW；不改canonical | derivation snapshot + outbox/event |
| commit/create/update | explicit steward APPROVE | proposal + expected head/revision | Claim/Version/Head | atomic CAS/version/history/outbox | Decision + Grounding + transition |
| conflict/open | approved CONTRADICT | both branches + Evidence | OpenIssue | Head不移动；issue identity/revision/branches保留 | full governance history |
| no-change | approved NO_CHANGE | proposal + existing head | no new version/head move | may attach governed result | Decision/outbox retained |
| reground | explicit TX-06 | new Evidence + blocked version | new ClaimVersion + Head | release old block only after new grounding | new decision/version/grounding |
| retrieve | query/prepare/chat | locator/query/policy/causal frontier | derived candidates | Gate + persisted RetrievalTrace | accepted/rejected/fallback/watermark recorded |
| cache | same Need + retained eligible task slot | signed token/coverage/binding | Host slot | revalidate DB frontier/issues；renew token | prepare trace response/Host JSONL；无 DB cache row |
| invalidate | revoke/settle/frontier change | Evidence/task/issue state | Context pointers/capsule or token reuse | synchronous invalidation or next-turn miss | deletion/transition/outbox |
| supersede | approved update | exact old head + new version | ClaimHead | pointer CAS to immutable Vn+1 | VersionTransition；旧版本保留 |
| revoke | operator/steward explicit request | Evidence ID + confirmation/idempotency | Evidence/groundings/context/deletion | logical block immediate；purge async | synthetic governed proposal/decision + deletion request |
| purge/erase | worker Outbox | revoke/purge event + lease | search/context bytes/CAS | delete derived rows/body；verified CAS absence | delivery result/hash/watermark/erasure proof |
| settle | explicit steward Episode settle | expected revision + residuals | Episode/context TTL | SETTLED；expire referenced context | settlement + transition + outbox |
| compact/summarize | Context build/compiler budget pressure | six sections/objects | Context representation | FULL→COMPACT→MINIMAL；Host item tiers | original pointers retained；no truth promotion |
| delete/forget | no general hard-delete API | — | — | current semantics是revoke/block/purge/erase，不删除Evidence/Claim history | auditable history retained |
| promote/demote | no generic operation | — | — | axes只能经governed new version/procedure演化 | cannot be inferred from other axes |

### 8.3 Admission policy

- Runtime验证data classification与active data mode，但classification是trusted caller assertion，不做PII detection（`runtime/README.md`）。
- Python client `CapturePolicy`默认 OFF；model output与prompt不能作为 Evidence；user/tool observations仅在显式policy下capture；普通response没有implicit capture。
- CommitPolicy固定 `USER_REVIEW`，不存在auto-commit。
- Evidence CAS write发生在DB transaction之前；DB失败/idem conflict后的orphan file cleanup未找到，详见R10。

### 8.4 Revoke / delete时序

```text
operator revoke request
→ steward governed TX-05 wrapper
→ APPLIED revoke Proposal + APPROVE Decision
→ Evidence.revoked + GroundingBlock + OpenIssue revision
→ Context invalidation + DeletionRequest + outbox       [synchronous]
→ Gate immediately fails closed
→ worker purge lane: old derived/context bytes
→ FTS/vector lanes: including DG11 fragment/window rows [asynchronous]
→ CAS verified unlink/absence proof when no live refs/hold
→ backup deletion obligation/audit completion
```

历史 Evidence/Claim/Decision/transition不物理删除。`blob already absent` 会生成 `VERIFIED_ALREADY_ABSENT` proof，而不是失败。

---

## 9. Memory Control Plane

### 9.1 完整决策链

```text
Host messages + Task payload
  ↓ Task relation / registry transition
AMBIGUOUS? ── yes → tentative empty binding → NONE → provider with NO_MEMORY
  ↓ no
Deterministic Memory Need
  ├─ unrecognized/greeting/simple arithmetic → NONE
  ├─ exact known key/claim → L0
  └─ history/conflict/explanation/current without exact locator → L1
  ↓
same typed Need + retained slot + identical continuing task + safe event?
  └─ yes → CACHE candidate
  ↓
Runtime route validation
  ├─ canonical-changing/action event → force L1
  └─ L0 without locator → L1
  ↓
NONE ───────→ terminal no memory
CACHE ──────→ signed proof + Need coverage + DB frontier/issues
               ├─ hit → UNCHANGED retained Context
               └─ miss → terminal DEGRADED/ABSTAIN + recommended route
L0 ─────────→ exact current head → canonical Gate
L1 ─────────→ exact/FTS → optional progressive stop
               → vector/recent/canonical fallback → Gate → optional rerank/operator
  ↓
Context Capsule → Host compile/slot → provider execution
```

### 9.2 Need signals

`DeterministicMemoryNeedResolver.resolve()` 接收 current question、scope、authority/consistency、known state keys/claim IDs、open issue IDs、canonical position与previous Need。它以英文token/regex识别 greeting、arithmetic、retry、current/history/conflict/explanation等意图；无model/embedding/retrieval call。

输出 signature字段：scope、required authority、consistency floor、claim IDs、StateKeyRefs、issue IDs、temporal need、evidence need、intent class。默认resolver通常要求 `SUPPORT_POINTERS`，不生成 `RAW_EVIDENCE`。

**Observed coverage boundary：** tokenizer regex只匹配 `[a-z0-9]`，无法识别的提问走NONE/default分支；中文或未覆盖表述可能不触发memory。现有行为不是LLM语义判断。

### 9.3 CACHE key、validation 与 scope

CACHE不是单一字符串key lookup；有效性由三组条件共同定义：

1. **Host candidate gate：** prior Need signature相同、retained context存在、Task relation为完全相同identity的CONTINUE、event不属于GOAL_CHANGED/MEMORY_AFFECTING_TOOL_RESULT/CANONICAL_POSITION_CHANGED/ACTION_PROPOSED。
2. **Binding digest：** tenant/principal profile/session/agent/profile/task_epoch/goal/scope/authority/consistency/limit/constraints/byte budget/token budget/slot TTL/compiler/router/tokenizer/policy/task budget/action digest（`context_preparation.py:640-669`）。query/event/route/Need不在digest；Need单独验证。
3. **Runtime validation：** HMAC、typed Need exact coverage、policy identity、claim heads/state keys/open issue revisions、global canonical position、deadline/counters/TTL。

Cache会检查task identity吗？**间接且分层检查。** Host先要求same TaskIdentity；Runtime token再绑定session/profile/task_epoch/goal等，但Runtime不知道parent/child relation本身。

Cache会检查state version吗？**会。** exact claim head versions、state-key head versions、issue revisions与global frontier均在coverage/token/DB snapshot中。

Cache会检查scope/validity吗？**scope/authority/consistency/temporal/evidence depth检查。** validity由前次Gate和global frontier失效共同保守保证；hit时不逐item重跑完整Gate。

`canonical_snapshot_outbox_sequence` 名称并非canonical-only：SQL取tenant所有 Outbox 的max sequence。因此任意Evidence、proposal、Episode等event都可使所有slot失效，安全但粗粒度。

### 9.4 Route 与 FastPath

- Runtime不自动发现Need；Host必须提交typed signature与requested route。
- `/v1/memory/query` 的route也是caller必填；Runtime只执行。
- Runtime safety override见3.3；L2永远返回 `ROUTE_DISABLED`。
- eval定义fast routes为 `{NONE, CACHE, L0}`；代码另有progressive L1，但指标不把L1计入fast route。
- progressive FTS stop要求非ACTION_SAFE、非RYW、无operator、CURRENT_STATE、Gate后唯一result、无OpenIssue且有lexical anchor。
- history/explanation的vector stop要求provenance；conflict要求live issue。
- 因而正常progressive path不会绕过canonical Gate，只跳过后续vector/rerank。

### 9.5 Retrieval conversion

```text
RetrievalRequest
→ versioned QueryPlan (regex/operator)
→ RetrievalCandidate rows from exact/FTS/vector/recent/fallback
→ weighted fusion
→ GatedBatch from evaluate_canonical_candidates()
→ hydrated result dicts + optional deterministic derived_result
→ RetrievalTrace
→ ContextMaterial re-gate/hydration
→ six-section ContextCapsule
→ client envelope validation
→ GovernedContextCompiler / PrefetchContext
→ model messages
```

L0通过claim ID或完整 `(subject_id,predicate,claim_type)` 读取Head；不依赖vector。L1真实次序为 exact + FTS → optional gated sufficiency → vector + optional recent/canonical fallback → fusion → Gate → optional reranker/MMR/temporal/operator。

### 9.6 Hidden fallback inventory

| Condition | Fallback behavior | Location | Semantic consequence |
|---|---|---|---|
| invalid/missing X-Request-ID | UUID4 | `api/app.py:53` | trace仍有ID，但caller correlation改变 |
| missing host task payload | fallback ACTIVE task/general goal | `task_state.py:177-208`; `host_adapter.py:548-568` | identity依赖user/config/random ID |
| lane empty | SWITCH/task start；suspended candidate则RETURN | `task_binding.py:120-130` | implicit initial relation |
| relation evidence不足/incompatible | AMBIGUOUS/TENTATIVE empty binding | `task_binding.py:131-195,283-293` | registry不变；execution以NO_MEMORY继续 |
| KNOWN_OBJECT无locator | event改为EXPLICIT_MEMORY_REQUEST | `host_adapter.py:641-643` | L1而非stable exact path |
| unrecognized Need | NONE | `memory_need.py::resolve()` | provider仍运行但无memory |
| retry lexical signal | reuse previous typed Need | same | 依赖process-locallast Need |
| CACHE invalid/missing/stale | terminal miss + recommended L0/L1 | `context_preparation.py:555-575` | Runtime不自动升级；Host当前实现返回UNKNOWN |
| canonical-changing/action event | override NONE/CACHE/L0为L1 | `_validated_route()` | fail-closed refresh |
| causal wait timeout/dead letter | canonical search fallback | `retrieval.py:306-443` | recall可降级，Gate仍保留 |
| projections unavailable/both lanes | canonical search fallback | same | index不成truth |
| snapshot advances during query | merge canonical fallback | same | avoid stale omission |
| reranker unavailable | deterministic base ranking | `retrieval.py:509-525` | ranking degrade，不跳Gate |
| canonical DB unavailable | abstain/503 | Retrieval/Chat | 无authority answer；可能无persistent trace |
| Context over byte budget | FULL→COMPACT→MINIMAL→error | `application/context.py:33-53` | protected sections优先；无silent overflow |
| raw Evidence requested | `NEEDS_RECOVERY` | `context_preparation.py:341-396` |正文必须pointer recovery，不颁发normal slot token |
| MCP/prefetch unavailable | UNKNOWN, no provider | `host_adapter.py:1122-1189` | fail-closed但不跟随recommended route |
| tool expected但缺result | UNKNOWN, no provider | same | no hidden model guess |
| Runtime action confirmation missing | abstain | `chat.py:50-84` | no retrieval；records abstained ChatTurn |
| revoked/unreadable Evidence | metadata + `content=None` | `evidence.py:100-120` | 不读取blob |
| worker failure | bounded retry→DEAD_LETTER；gap blocks watermark | migration `0007` | RYW可timeout/dead-letter |
| blob already absent | verified-already-absent proof | BlobStore | deletion可证明完成 |
| idempotent retry | replay stored response | DB TX procedures | 不重复执行mutation |

### 9.7 Write / update after execution

| Execution type | Persistent writes after response/action |
|---|---|
| OpenWorker normal answer | adapter JSONL + provider ledger；无 Runtime ChatTurn/Evidence/Claim |
| OpenWorker tool recall | Runtime RetrievalTrace；之后adapter/provider trace；无automatic memory write |
| Runtime `/chat` success | RetrievalTrace + Capsule/pointers + ChatTurn |
| Runtime `/chat` abstain | 视分支为ChatTurn only、Trace+ChatTurn或无write |
| explicit capture | Evidence/CAS/idempotency/event/outbox |
| explicit proposal/review | Proposal；随后governed canonical graph/history/outbox |
| revoke | governed proposal/decision + logical block/invalidation/deletion；worker异步progress |

---

## 10. Persistence Architecture

### 10.1 Persistence mechanisms

| Mechanism | Data | Writers | Readers | Lifetime/versioning | Auditable? | Role |
|---|---|---|---|---|---|---|
| PostgreSQL `milai` schema | Evidence metadata、canonical graph/history、issues、trace/chat/episode/deletion、outbox/projections/indexes | API/steward/worker/audit的allowlisted procedures | role-scoped repositories | long-lived；Alembic 0001–0028；row/version/revision/sequence | Yes | formal truth + durable audit + derived state |
| pgvector inside PostgreSQL | 16d parent embeddings；128d DG11 windows | worker | L1 retrieval | replaceable/rebuildable；projection identity in 0027 | delivery/result trace | derived index only |
| local tenant CAS filesystem | Evidence content bytes/encrypted envelope | EvidenceService；purge worker erase | Evidence/pointer recovery | content-addressed；physical lifecycle ACTIVE→PURGE_PENDING→ERASED | DB metadata + erasure proof | Evidence bytes source |
| Host process memory | TaskRegistry、task graph、retained Context slots、last Need、pending tool timing | OpenWorker adapter/controller | same adapter process | process lifetime；generation/revision CAS but no durable backing | adapter JSONL only | temporary working/task state |
| validation/causal HMAC tokens | cache coverage/frontier/binding/counters/expiry；RYW min position | Runtime codec | next request | bounded TTL；not server-stored | payload verifiable, issuance not generally DB-persisted | proof, not state store |
| OpenWorker JSONL + provider ledger | route/task/Need/timing/provider reservation/result | adapter/gateway | experiment/review tooling | run-scoped append-only；provider ledger hash-chain | Yes within file boundary | execution evidence |
| `var/`, `dist/`, reports | experiment state/results/manifests | scripts/historical runs | reviewers/eval state board | retained snapshot；many hashes/manifests | partially self-verifying | research evidence, not online memory |

没有发现 production Redis、graph DB、external vector DB 或 standalone cache service。OpenViking只作为隔离eval baseline，production backend明确PARK。

### 10.2 Source-of-truth classification

| Classification | Objects |
|---|---|
| Evidence truth | `EvidenceRecord` identity/source/permission/retention/revoke；`ContentBlob` identity/physical state；CAS bytes |
| Canonical StateView truth | `Claim`, `ClaimVersion`, `ClaimHead`, `OpenIssue`, `GroundingRelation`, `GroundingBlock`, `StewardDecision`, transitions |
| Deletion workflow truth | synchronous revoke/block/context invalidation；`DeletionRequest` async progress/proof |
| Durable audit/evidence, not current truth | `OperationalEvent`, `OutboxEvent`, `RetrievalTrace`, `ChatTurn`, Episode/settlement, backup manifest/obligation, quarantine ledgers |
| Derived state/index | ECS view, search documents/embeddings/fragments/windows, delivery/watermark |
| Derived Context/cache | ContextCapsule/pointer, Host PrefetchContext/MemorySlot, validation token |
| Explicitly noncanonical | undecided Proposal, retrieval candidate/result, summary, LLM output, external memory/tool payload |

### 10.3 Migration evolution

| Revisions | Effective responsibility |
|---|---|
| 0001–0003 | runtime metadata/pgvector；tenant/actor/RLS/event；Evidence/blob/idempotency/outbox/TX-01 |
| 0004–0005 | canonical object graph/ECS；proposal/review TX-02/03/04/06 |
| 0006–0009 | revoke/context/deletion；projection/watermark/FTS/vector；Gate/trace；Context/Chat |
| 0010–0014 | backup/restore/rebuild；Episode；persisted QueryPlan；confirmation；outbox causal naming |
| 0015–0017 | governed public wrappers、complete history、governed revoke、authoritative ECS/Gate |
| 0018–0023 | causal trace/position；verified erasure与SHA repair；trace-conditioned Gate |
| 0024–0026 | legacy history/provenance/TX-05 reconciliation，无法证明时migration fail closed |
| 0027 | embedding model/projection identity |
| 0028 | DG11 document fragments + 128d window embeddings |

**Observed：** code schema head 为 `0028_dg11_window_projection`。`[UNKNOWN]` 当前实际部署DB是否已迁移到0028。

### 10.4 Roles、RLS 与 authority

- migration owner拥有schema/DDL；具体部署role名 `[UNKNOWN]`。
- `milai_api`、`milai_steward`、`milai_worker`、`milai_audit` 均设计为NOINHERIT/NOBYPASSRLS/NOSUPERUSER；tenant tables ENABLE/FORCE RLS。
- `Database` 对 expected role做session/current user、owner与privilege attestation；每transaction设置tenant/actor，pool return rollback + `RESET ALL`（`persistence/database.py:39-55,103-169`）。
- API可写Evidence/proposal/context/trace/chat/episode capture；Steward可review/revoke/settle/rebuild/retry；Worker可写delivery/index/purge/erasure；Audit负责backup/expiry procedure而不能写canonical state。
- 所有profile的persistent tenant/actor来自static Runtime settings；profile token能力不同，但DB actor不区分具体Bearer profile。prepare-context token额外绑定principal profile。
- `[UNKNOWN]` Audit role在线connection abstraction；通用`Database`拒绝`milai_audit`。

### 10.5 Versioning 与 audit guarantees

- Evidence capture identity由trigger保护；同idempotency key + same fingerprint重放原response，conflict fingerprint整事务拒绝。
- ClaimVersion、Decision、VersionTransition、OpenIssueTransition append-only；ClaimHead和OpenIssue用exact CAS。
- 0024要求每个version/issue revision具有连续、non-null governed provenance；不可证明的legacy行进入immutable quarantine或migration fail closed。
- Outbox `outbox_sequence`是全局change feed；`canonical_commit_seq`只表示canonical decision，二者有意分离。
- Projection watermark只能跨过连续delivered events；dead-letter/gap阻塞后续visibility。
- Context pointer recovery每次重验capsule状态/TTL、Evidence revoke/retention/permission、blob/hash及snapshot。

---

## 11. Tests and Evaluation

### 11.1 Test inventory

以下数量是静态扫描到的 test definitions，不含参数化展开；本轮未运行。

| Test area | Files / definitions | Category | What is covered | Important uncovered boundary |
|---|---:|---|---|---|
| `runtime/tests/unit` | 28 / 147 | unit/regression | settings、blob、planner、fusion、Need/cache/context、embedding | CLI `worker --once` wiring；capsule/token TTL组合 |
| `runtime/tests/contract` | 5 / 12 | API contract | schemas/routes/capabilities | external Host composition |
| `runtime/tests/integration` | 8 / 57 | PostgreSQL integration/E2E | Evidence、canonical、retrieval/context/chat、worker、backup、Episode、migrations | composite controller可被importorskip；disjoint issue；128d rebuild |
| `runtime/tests/concurrency` | 1 / 16 | invariant/concurrency | head/issue CAS、conflict、history、REGROUND/revoke | — |
| `runtime/tests/security` | 1 / 5 | security | roles/RLS/tenant/pool reset | OpenWorker HTTP listener boundary |
| root `tests/` | 67 / 345 | DG10/11/12/regression/diagnostic | release、experiment contracts/artifacts | 大部分不在regular CI |
| `evals/tests` | 11 / 80 | eval harness/regression | shadow metrics、paper runner/scoring | 不在regular CI；不是product execution |
| `evals/agent_efficiency` tests | 5 / 41 | benchmark/protocol | local benchmark/provider evidence | real provider evidence absent |
| Python client | 10 / 104 | unit/integration | Need、task state、slots、capture、router/cache、client/context/loop | durable task restart |
| MCP | 1 / 14 | contract | profile allowlist、policy binding、reconnect/confirmation | active host E2E |
| OpenWorker MCP | 7 / 32 | host/controller | relation/lanes/CAS/delayed result、adapter、UDS、provider、settlement | absent from CI；user-shaped recall spoof |
| LangGraph / AutoGen / Hooks | 4 / 16 | adapter smoke | secondary portability | primary product quality |
| frozen architecture | 19 tests | lock/contract | bundle structure/hash/crosswalk | CI lock scope仅bundle，不验证all source drift |
| OSPC | 1 / 9 | research harness | scorer/fixture/hard falsifier | novelty path已abandoned |

pytest采用strict config/markers；有coverage配置但CI没有coverage threshold。未发现Hypothesis/property-based框架；invariant主要靠显式与DB concurrency cases。

### 11.2 Tests实际定义的 architecture contracts

- Need/CACHE：typed coverage、task/profile/scope binding、global position invalidation、raw evidence recovery、cache miss/NONE无hidden retrieval、budget和L0 override（`runtime/tests/unit/test_context_preparation.py:155-532`）。
- Canonical：absence/head/issue CAS、conflict保留branches、direct DML denial、Evidence≠Claim、revoke rollback（`runtime/tests/concurrency/test_canonical_transactions.py:249-855`）。
- Retrieval：L0不依赖vector、L2关闭、hybrid trace、RYW fallback、axis-complete Gate、vector degrade/canonical abstain（`runtime/tests/integration/test_retrieval_api.py:234-789`）。
- Context/Chat：fixed sections、pointer recovery、append-only ChatTurn、issue closure、revoke invalidation、confirmation（`test_context_chat_api.py:435-659`）。
- Worker/deletion：ordered projections、watermark gaps、dead-letter、purge/erasure proof、rebuild（`test_projection_worker.py:198-730`）。
- Task control：same task/lanes/ambiguous/delayed/ABA与zero-LLM（`integrations/openworker-mcp/tests/test_task_binding.py:86-260`）。
- Formal eval：fixed denominator、all failures retained、无任意retry、label-free execution then scoring（`tests/test_dg12_paper_v3.py:38-235`; `evals/paper/dg12_v3/runner.py:57-561`）。

### 11.3 Current architecture invariants

| Invariant | Evidence | Status |
|---|---|---|
| I-01 EvidenceRecord ≠ ClaimVersion | schema/procedures；`test_canonical_transactions.py:729` | Enforced |
| I-02 immutable Evidence identity + idempotency | TX-01 triggers/procedure；Evidence integration tests | Enforced |
| I-03 canonical变化只有Steward procedure | grants/wrappers；direct DML denial tests | Enforced |
| I-04 append-only governed history/quarantine | triggers + migrations 0015/0024 + concurrency tests | Enforced after 0024 code head |
| I-05 Head/OpenIssue exact CAS | procedures + race tests | Enforced |
| I-06 CONTRADICT不移动Head、保留Issue branches | procedure + test `:329` | Enforced |
| I-07 ECS为唯一applicability入口 | authoritative view/Gate + retrieval tests | Enforced in Runtime |
| I-08 index/cache/Context/LLM不得提升truth | Runtime Gate/re-gate + outage tests；OpenWorker user-shaped recall例外 | **Partially enforced end-to-end** |
| I-09 axes正交 | schema/Gate/procedure + illegal mapping tests | Enforced |
| I-10 revoke同步阻断、异步可证明清理 | TX-05/worker/erasure tests；DG11 completion/rebuild语义有gap | Core authority enforced；cleanup status partial |
| I-11 tenant/RLS/roles | FORCE RLS/role attestation/security tests；Host listener边界未统一 | Runtime enforced；end-to-end partial |
| I-12 mutation/outbox atomic + authority answer trace/RYW | procedures/trace tests；unavailable Chat无trace、Host answer分立 | Partially enforced end-to-end |
| Task continuity | Host typed model + relation tests | Process-local only；durable contract absent |
| Cache validity | runtime unit/integration strong coverage | Runtime enforced；primary composition CI partial |
| Context isolation | DB Context cannot mutatecanonical；normal pathsre-gate | Partial due R1 input authenticity |
| Route correctness | deterministic tests + shadow metrics | Tested locally；not fully CI-gated primary path |

### 11.4 CI实际覆盖

`.github/workflows/ci.yml` 当前定义：

1. PostgreSQL/pgvector + least-privilege roles；locked Runtime install；ruff/mypy；frozen bundle verification；full Runtime pytest；OSPC verification；build/release safety。
2. Integration matrix只含 `python-client`, `mcp`, `langgraph`, `autogen`, `hooks`；另运行selected provider protocol tests。

关键边界：

- primary `integrations/openworker-mcp` 不在matrix。
- root DG10/11/12 suites与`evals/tests`大多不在regular CI。
- runtime composite test使用`pytest.importorskip("milai_client")`/`milai_openworker_mcp`/tokenizer；保存的EH04 full gate为251 passed、1 skipped，明确缺`milai_client`；Core02也是229 passed、1 skipped。
- CI设置`MILAI_ARCHITECTURE_LOCK_SCOPE=bundle`；只有scope `all` 才验证source commit drift。
- 当前Git没有commit/tracked file，因此hosted CI历史与commit provenance `[UNKNOWN]`。

### 11.5 Metrics

| Metric | Meaning | Computed where | Input | Current role |
|---|---|---|---|---|
| `prechange_state_addressability` | REQUIRED+CURRENT_STATE turns中预先存在canonical StateKey比例 | `evals/agent_integration/fast_path_shadow.py:527-543` | synthetic sealed turns | architecture diagnostic |
| `fast_path_execution_coverage` | fast-eligible turn实际terminal route属于允许的NONE/CACHE/L0比例 | same `:544-549` | expected route sets + actual trace | route diagnostic；非answer metric |
| `false_fast` / action-safe subset | independently fast-ineligible却走fast route | `:550-559` | shadow labels | safety diagnostic |
| `unsafe_cache_turns` | CACHE不在expected route set | `:560-564` | cache route trace | cache safety diagnostic |
| task-boundary unsafe cache | reuse prohibited却CACHE | `:565-569` | relation/cache labels | continuity safety diagnostic |
| cache request/hit/miss/coverage/frontier | structured cache validation效果 | `:571-604` | trace events | architecture diagnostic |
| relation precision/recall/false merge/split | task resolver质量 | `:381-429,656-798` | synthetic task sequence | architecture diagnostic |
| Need/StateKey resolution | typed Need与governed key availability | `:807-846` | synthetic turns | architecture diagnostic |
| route fidelity/trace completeness | expected vs actual route、trace fields | `:847-868` | shadow run | regression diagnostic |
| route/control latency/calls/tokens | local control-plane costs | `:874-899` and agent efficiency | local synthetic | research/optimization diagnostic；非SLA |
| retrieval hit@3 / coverage@3 / span survival | relevant item/span是否保留 | `evals/analysis/retrieval.py:32-89` | benchmark outputs | retrieval research metric |
| EM/F1/quality gates | answer accuracy/non-regression/token safety | `evals/analysis/quality.py:7-49` | answer/reference | research gate；local scorer标为NOT_OFFICIAL |
| DG11 bootstrap deltas | 50×3 arms hit/coverage/span/EM/F1/calls | `evals/benchmark/dg11_measurement.py:177-363` | fixed 150 records | research experiment metric |
| provider protocol gates | quality/safety/token/cost/component budget | `evals/agent_efficiency/provider_ab.py:1854-1904` | required 1,000 calls | real-provider regression gate；evidence absent |
| LongMemEval | EM/F1/hit@k/NDCG/coverage | `evals/paper/scorers/longmemeval.py` | formal outputs/labels | paper metric |
| Horizon | official accuracy/CI/paired delta | `evals/paper/scorers/horizon.py` | formal outputs/labels | paper metric |
| Memora | FAMA/deletion leak/presence/forgetting | `evals/paper/scorers/memora.py` | formal outputs/labels | paper metric |
| OSPC recall/false closure/cost | identity/branch/evidence/dependency/discharge/legal success | `research/ospc/scorer.py:21-217` | 40 synthetic fixtures | abandoned research-path diagnostic |

FastPath shadow明确声明 `SYNTHETIC_ONLY`、answer/judge calls=0、`ROUTE_LABEL_ONLY_NO_ANSWER_MODEL`；不得把其100% route coverage解释成answer quality或product metric。

### 11.6 Retained result interpretation

- EH04 DEV 20-turn artifact：route fidelity=1.0、trace completeness=1.0、relations 20/20、fast coverage 18/18；不是formal confirmation answer run。
- performance terminal：StateKey resolution 0.7333 vs target 0.9333；expected-result membership 0.8；online/deep/cold controls不完整。
- DG12 formal当前没有raw generations、scored records或final metrics。
- OSPC pilot有40 synthetic fixtures、8个Bmin infeasible，hard falsifier结论 `ABANDON`。
- `[UNKNOWN]` 当前clean environment能否通过所有tests；所有passed counts均为retained artifact。

---

## 12. Current Development State

| Workstream / component | State | Current evidence and boundary |
|---|---|---|
| Logical Architecture 1.0.0 | Implemented/frozen document bundle | candidate.5 accepted、bundle/tests/manifest存在；不冻结schema/implementation |
| Runtime / Schema 0.1.x | Implemented candidate / Experimental NO-GO | Flask/Postgres/worker vertical slice；schema head 0028；production deployment revision `[UNKNOWN]` |
| Evidence/canonical/retrieval/context/revoke/Episode | Implemented candidate | code + DB integration/concurrency tests；本轮未重跑 |
| Runtime answer LLM | Not implemented inside Runtime | `/chat`使用deterministic renderer；provider在OpenWorker integration |
| Persistent Task store | Not implemented in repository | Task types/registry有实现，但只process-local |
| Delayed tool-result binding / task completion | Partially implemented | registry APIs/tests存在；active host adapter wiring未找到 |
| Agent Integration UA | Implemented / scoped PASS | candidate.2 independent re-review PASS；仅synthetic/deidentified边界 |
| OE local provider protocol | Implemented / local PASS | local review candidate.4.6 PASS |
| OE real provider evidence | Partial / NO-GO | OE-F06 open；无真实1,000-call usage/model/billing证据 |
| DG-01–DG-09 / LC | Implemented historical candidates | reports记录scoped PASS；counts为历史snapshot，非current rerun |
| OSPC RC001–008 | Implemented then deprecated/abandoned | code/tests/pilot完成；novelty hard falsifier触发ABANDON |
| DG10 | Implemented / scoped accepted | controlled adjudication ACCEPT；仅functional synthetic/deidentified；production/schema仍NO-GO |
| DG11 functional | Implemented / frozen candidate | R00–R06 retained PASS/freeze manifest |
| DG11 quality/generalization | Partial / target not established | v1 holdout failed；v2在provider reservation前capability failure，400/400 unresolved；no rerun |
| DG12 CORE/PD01 | Implemented / PASS artifact | product terminal artifacts存在 |
| DG12 PD02 performance | Implemented functionality / terminal target miss | safety/equivalence存在；online/deep/cold缺失；speed claim false |
| DG12 EH04 | correctness/equivalence PASS artifact；performance miss | 251 pass/1 skip retained gate；composite test被skip |
| DG12 formal PE00V3/PE01V3 | harness implemented / authorized | label-free gates与resource authorization完成 |
| DG12 formal PE02V3+ | Planned/blocked before execution | labels/contexts/answers/scores仍0；resource preflight pending |
| FastPath/StateAddressability | Partially implemented diagnostics | route/task/cache metrics与DEV artifact；非answer-quality proof |
| OpenViking production | Parked | 只允许隔离evaluation native baseline；formal results不存在 |
| generic LangGraph/AutoGen/direct client | Implemented portability smoke | secondary，不是权威产品路径 |
| inactive OpenWorker `adapter.py` | Deprecated/inactive | wheel exclude；active入口为`host_adapter.py` |

### 12.1 Document / code / artifact mismatches

| Source says | Higher-priority current evidence says | Status |
|---|---|---|
| `AGENTS.md` / OSPC README部分文字：RQ pending/novelty unvalidated | contract + `pilot_metrics.json` + pilot report：ABANDON | stale documentation mismatch |
| `AGENTS.md`前段：OE candidate.4.4等待acceptance | later candidate.4.6 review：local PASS；real-provider仍NO-GO | stale checkpoint / partial mismatch |
| old DG11 GOALS仍可被读作current state | AGENTS明确其仅历史；`var/dg11/current-state.json`与final artifacts接管 | historical document, not state board |
| Runtime README称head 0027 | migration tree当前有0028 | stale README detail |
| contract Chat response fields | code/tests使用不同字段 | implementation/test vs contract mismatch |
| contract/README暗示Runtime model answer | Runtime Chat模板；LLM只在integration | implementation placement mismatch |
| DG12 current-state 111个path/hash | 静态核验110匹配，`legacy-identity-compatibility.yaml` 1个已披露hash drift | retained artifact mismatch |

### 12.2 Artifact provenance

- DG10/DG11 sampled/listed final hashes与current files匹配；DG12有上述1个pre-existing/unratified drift。
- 没有Git commit，所以无法证明这些artifacts来自独立CI/特定commit。
- formal authorization不等于formal execution；保存的PASS也不等于本轮可复现PASS。

---

## 13. Architectural Risks / Ambiguities

以下只列对correctness、architecture ownership或operability最重要的14项；不是style建议。

### R1 — P0 correctness：user-role recall-shaped JSON可绕过canonical Gate进入provider Context

**Observed：** `host_adapter.py:299-332::_recall_object/_recall_from_messages()` 同时扫描 `role in {"tool", "user"}`，接受任何nested object/string，只要求string `status`、list `items`、list `open_issue_ids`。`complete()` 在`:680,1191-1205`将其传给`prepare_prefetch()`；后者根据字段构造`AVAILABLE` memory，不验证MCP来源、签名、trace或Gate（`python-client/context_policy.py:198-305`）。

**Potential consequence：** 普通user message可伪造“memory tool result”，其payload被当作可用fact注入本地provider。正常Runtime I-08 boundary在此end-to-end路径被绕开。

**Test gap：** `tests/test_dg10_openworker_f1_adapter.py`覆盖真实nested tool extraction和无关tool JSON，未覆盖user-shaped spoof负例。

### R2 — P1 architecture verification：primary OpenWorker path不是必跑CI组合门

**Observed：** `openworker-mcp`不在integration matrix；Runtime composite controller test使用`importorskip`，保存的full gate实际skip。  
**Potential consequence：** Runtime cache/Gate tests与Host task/adapter tests分别通过，也不能证明当前package组合的主产品path持续成立。

### R3 — P1 correctness ambiguity：Context OpenIssue selection与DB all-live-issues contract冲突

**Observed：** `ContextRepository.material()`只取target/global/scope-related live issues（`context_repository.py:112-144`）；`create_context_capsule()`却要求tenant所有live issue都在capsule（migration `0009:264-285`）。  
**[INFERENCE] consequence：** 存在disjoint-scope live issue时，正常Context build可能稳定得到`CONTEXT_ISSUE_OMITTED`。当前test仅覆盖relevant issue。

### R4 — P1 architectural ambiguity：durable Task continuity owner不存在于repository

**Observed：** Task registry/graph/slots/last Need均process-local；Runtime DB无Task/binding/relation表。  
**Potential consequence：** restart/cross-session continuity依赖仓库外Host重送；没有可审计的single owner。不能从当前代码保证long-term task continuity。

### R5 — P1 execution completeness：CACHE miss给出recommended route但active Host不follow

**Observed：** Runtime故意把miss作为terminal且返回`next_route_recommended`；active prefetch adapter把DEGRADED/ABSTAIN映射为UNAVAILABLE并直接返回UNKNOWN，不做第二次L0/L1。  
**Potential consequence：** 合法slot失效会变成answer terminal，而非同turn fresh retrieval；这不是hidden unsafe fallback，但影响可用性和route语义。

### R6 — P1 lifecycle ambiguity：Host token TTL与persistent Capsule TTL分离

**Observed：** CACHE hit滑动重签token expiry，却不读取/延长`ContextCapsule.expires_at`；Host保留rendered slot。  
**[INFERENCE] consequence：** token/slot可晚于DB capsule存活，CACHE仍UNCHANGED而pointer recovery已过期。canonical frontier仍验证，故更像provenance/recovery lifecycle gap而非stale truth bypass。

### R7 — P1 deletion/projection semantics：0028 rebuild与purge completion未覆盖新lanes

**Observed：** `rebuild_search_projection()`只清旧`search_document/search_embedding`，0028未patch其清理fragments/windows；purge lane在FTS/vector删除DG11 rows之前可先把`derived_purge_status`置COMPLETED。  
**Potential consequence：** 128d derived rows在rebuild后残留；删除状态有短暂/持续语义不准确。Gate因revoke仍fail closed，所以未观察到authority leak。

### R8 — P1 action safety：live confirmation未绑定具体query/action且可重用

**Observed：** application仅检查source type/ref nonce/subject/content与±5分钟；未绑定query/action digest/profile，未consume；future observed_at也未显式拒绝。DB procedure校验更弱，只要求近期matching source pattern。  
**Potential consequence：** 同一confirmation/nonce可在窗口内用于不同action-sensitive queries；direct DB caller不能获得application级exactness保证。

### R9 — P1 security boundary ambiguity：OpenWorker HTTP adapter不强制loopback或request auth

**Observed：** CLI接受任意`--listen-host`并直接创建`ThreadingHTTPServer`；Handler无authorization check。Provider endpoint与Runtime另有loopback/credential约束。  
**Potential consequence：** 安全性依赖外部network namespace/firewall/eval harness配置，而非adapter本身；实际deployment exposure `[UNKNOWN]`。

### R10 — P1 semantic coverage：Need resolver以英文lexical heuristic为主

**Observed：** resolver token regex/keywords不做中文语义、embedding或model判断；无法识别时可能NONE。  
**Potential consequence：** memory-relevant中文/非模板化request可能跳过retrieval；现有FastPath metric仅synthetic route labels，不能证明真实语言coverage。

### R11 — P1 trace ownership：两条answer path的审计对象不统一

**Observed：** Runtime Chat持久化RetrievalTrace/Capsule/ChatTurn；OpenWorker normal answer只写Host JSONL/provider ledger；PrepareContext NONE/CACHE/rejection trace主要response-local。canonical unavailable时Runtime也可能无法写trace。  
**Potential consequence：** “一次用户execution”的统一DB trace/replay不成立；跨store correlation依赖request/hash/run metadata。

### R12 — P1 operational correctness：`milai-worker --once` help与实现相反

**Documented：** help称只验证dependency且不处理jobs（`workers/main.py:259-265`）。  
**Implemented：** CLI注入真实repository，`--once`调用`run_once()`并实际lease/process；`milai-ops start`把它当preflight（`:290-309`; `operations/local_runtime.py:388-390`）。  
**Potential consequence：** 被认为read-only的preflight可修改projection、purge与blob state；unit test只用`repository=None`。

### R13 — P2 storage/provenance：blob-first orphan与DB key reference缺口

**Observed：** CAS write先于DB idempotency/transaction；失败后未找到orphan sweeper。加密envelope含key reference，但`StoredBlob`/DB ingest command不传，`content_blob.key_reference`保持NULL。  
**Potential consequence：** filesystem可有DB-unreferenced bytes；DB不能直接审计encrypted blob key identity。

### R14 — P1 provenance/evaluation：无Git history且formal/real-provider evidence未产生

**Observed：** all files untracked/no commits；DG12 formal generations/scores=0；OE real-provider evidence缺失；DG12 state map有1个known hash drift。  
**Potential consequence：** 当前不能把local artifacts提升为commit-bound、hosted-CI或formal product claims。

---

## 14. Unknowns

1. `[UNKNOWN]` 当前工作树在clean、fresh environment中能否通过全部Runtime、root、eval和integration tests；本轮未执行。
2. `[UNKNOWN]` 实际部署数据库的Alembic revision、schema owner role、数据规模与真实watermarks/dead letters。
3. `[UNKNOWN]` 外部OpenWorker是否持久化并跨session重送完整TaskIdentity/TaskMemoryBinding；repository自身不持久化。
4. `[UNKNOWN]` production/eval部署是否把OpenWorker adapter限制在可信loopback/network namespace，是否另有front-door authentication。
5. `[UNKNOWN]` 是否有仓库外CAS orphan sweeper或encrypted-key inventory reconciler。
6. `[UNKNOWN]` Audit role的实际connection/runner implementation；通用Runtime `Database`不接受audit role。
7. `[UNKNOWN]` 当前Host slot的实际eviction/restart policy，以及token TTL超过capsule TTL是否是有意contract。
8. `[UNKNOWN]` 16d projection的退役计划；0028当前同时保留16d与128d，不能称旧路径deprecated。
9. `[UNKNOWN]` saved JSON/report是否来自独立CI runner；无Git/hosted-run provenance可验证。
10. `[UNKNOWN]` DG12 formal 100×11的answer quality、cost、latency、failure distribution；尚未执行。
11. `[UNKNOWN]` OE真实provider 1,000-call evidence能否满足quality/safety/budget gates。
12. `[UNKNOWN]` Runtime之外是否存在普通turn→Evidence/Proposal的生产capture orchestrator；当前repository主路径未调用。

---

## 15. Recommended Next Investigation

下一轮建议只深入以下5个问题，先补证据，不先做redesign：

1. **验证OpenWorker memory input authenticity boundary。** 为user-role recall-shaped JSON、伪造tool result、真实broker/MCP result建立最小adversarial trace，确认R1的可达性与影响范围。
2. **跑一次clean primary-path composition gate。** 同时安装Runtime、client、MCP、openworker-mcp与tokenizer/PostgreSQL，确保composite test不skip，并记录exact package/artifact identity。
3. **构造Context/OpenIssue与cache TTL边界矩阵。** 覆盖disjoint scope live issue、capsule先过期/token后过期、revoke/issue revision/frontier变化，确认R3/R6的真实runtime结果。
4. **核查Task durability contract。** 从真实OpenWorker host lifecycle追踪restart、cross-session、RETURN/subtask、delayed tool result，确定repository外是否有持久owner，以及哪些typed字段实际round-trip。
5. **验证0028 deletion/rebuild semantics。** 对16d/128d两套projection做只读设计审计后，在隔离测试库观察rebuild与purge各阶段的rows/status/proof，确认R7是否影响删除SLO或审计声明。

---

## Final Self-Check

- 已先恢复current implementation，再列intended design/gap。
- 已分别trace OpenWorker主路径、visible tool路径与Runtime `/chat`，未根据目录名猜测。
- 已扫描unit/contract/integration/concurrency/security/root/eval/integration tests与CI实际选择。
- 已区分persistent truth、durable audit、derived index、Context和process-local cache。
- 已区分Task Identity与Task Memory Binding，并指出其durability边界。
- 已列出Need/CACHE/Route/FastPath、fallback、write/update/invalidate路径。
- 已对关键inference与unknown显式标记。
- 本轮未修改任何源代码、配置、测试、schema或artifact；只新增本报告。
