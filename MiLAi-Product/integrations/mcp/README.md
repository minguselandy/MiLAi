# MiLAi MCP

当前公网用户请先阅读[MiLAi MCP 工具使用文档（中文，8 工具／9 scope）](../../docs/runbooks/mcp-user-guide.zh-CN.md)。

MiLAi provides host-submitted, governed memory for notes, evidence, task checkpoints,
and reviewed claims. It does not automatically ingest conversations. Notes, evidence,
proposals, and checkpoints are not approved claims. Checkpoints can expire; retention
and deletion policies apply. Available tools and data depend on the profile and permissions.

MiLAi 是一个受治理的记忆与持久化服务，用于宿主提交的笔记、证据、任务检查点和经审核的记忆结论。
它不会自动采集聊天内容；Note、Evidence、Proposal 和检查点不等于已批准的 Claim。
检查点可能过期，数据受保留、权限和删除策略约束。客户端连接标识仍为 `milai`，
展示名为 `MiLAi`，工具标识保持 `milai_*`。

面向 Host 的介绍通过初始化 `serverInfo.description` 提供，而不是只放在 `instructions` 中。
各工具首句说明用途，随后列出关键输入、结果及风险边界；公共规则不复制进每个工具。
本轮描述优化已随 MCP 0.1.14 部署到公网 OAuth 7960；客户端需重新连接以刷新元数据。
全部实际文案见[Host 展示描述清单](../../docs/runbooks/mcp-host-descriptions.md)，
包括普通目录 22 项以及兼容／管理目录的额外或不同描述。

当前 OAuth 私人记忆交付入口：[MCP 使用与安装](../../examples/mcp-release/README.md)。
连接地址为 `https://milai.aigcit.com:7960/mcp`，普通用户登录后使用自己的记忆。
维护者可运行 `sh tools/build_mcp_delivery.sh`（Product 根目录）生成带锁定依赖和校验清单的交付包。
历史静态 Token 的 remote-client 包保留用于旧部署，不适用于此 OAuth 私人配置。

MCP 0.1.15 新增精简目录 `--catalog compact-memory-v1`：8 个入口，
默认 `milai_memory_save(content, operation_id)` 保存 Note；Note 和 Evidence 共用有类型分支的
保存、读取、浏览、删除和状态查询工具。它不叠加到普通 22 工具目录，也不改变既有权限或存储。
高级操作继续选择 `ordinary-memory-v1`；兼容目录 `legacy` 为 13 项。
公网 OAuth 7960 已切换为 0.1.15 compact，并按 8 工具／9 scope 对齐；跨会话协议验收已完成。
每个客户端仍需实际获得对应权限并刷新连接，不能以历史验收替代当前 grant 检查。
详见[精简目录使用说明](../../docs/runbooks/compact-memory.md)及
[发布记录](../../docs/releases/MCP_0.1.15_OAUTH_DEPLOYMENT_20260908.md)。

检索入口和跨会话查询见[检索工具使用合同](../../docs/runbooks/memory-retrieval.md)。
`milai_memory_search` 已包含在当前公网 compact 目录中，并行查询有权限的 Note 与治理来源；
历史／高级目录中的 `milai_memory_resolve` 仍不搜索普通 Note。

Host-submitted memory over Streamable HTTP MCP. The P08 product endpoint is
`http://127.0.0.1:7337/mcp`; stdio remains available only for compatibility and local protocol
debugging. The server uses the official MCP Python SDK v2 line. For the complete Runtime → MCP →
Codex startup sequence, use the
[authenticated HTTP MCP quickstart](../../docs/runbooks/http-mcp.md).

For the external AIGCIT resource-server mode, use the separate
[AIGCIT deployment runbook](../../docs/runbooks/aigcit-http-mcp.md).
It uses verified ES256 access tokens and private per-user scopes (ADR-049), with
optional explicit-owner compatibility mode; it does not
install a local authorization server or accept the legacy static bearer fallback.
Public TLS, resource registration and real-user login remain separate rollout gates.

For deterministic cross-session resume, use the Host-managed launcher after installing this
package:

```bash
milai codex \
  --runtime-env-file /path/to/runtime/.env \
  --project-id my-project \
  --principal-id codex-local
```

It derives a deterministic repository/worktree/branch fallback, starts a private loopback HTTP MCP,
performs `milai_working_state_get(scope=TASK)` before Codex starts, and injects only bounded,
explicitly non-canonical bootstrap data. The fallback is not a semantic task identity. Use a stable
explicit `--task-ref` when multiple tasks share one branch or continuity must survive a branch,
path, or machine change.

Working State is a replaceable task note with version protection. A successful checkpoint does
not certify its natural-language content. On `STALE_WORKING_STATE`, reload and rebase before
updating; `OPERATION_CONFLICT` requires reconciling the earlier request;
`EVIDENCE_REFERENCE_INVALID` requires qualified sources. An unavailable update is reported as
`WORKING_STATE_OUTCOME_UNKNOWN`: read the current State before retrying, and reuse the operation
ID only for the identical request. These failures do not grant additional permissions.

Working State GET/UPDATE use a shared asynchronous Runtime client created and closed by the server
lifespan. Independent calls can overlap while Runtime CAS protects competing updates. Cancellation
leaves a write outcome unknown. For a controlled
compatibility comparison, the generic `milai-mcp` command accepts
`--working-state-transport sync`; its default is `async`. The fixed `milai-codex-full-mcp` entrypoint
uses async and zero automatic retries. This transport choice does not change memory presentation,
the public tool schemas, or authorization.

Codex-full range resolve also uses a lifespan-owned asynchronous client, with the reader credential
and a fresh authenticated principal binding on each request. Concurrent queries do not share the
synchronous SDK execution lock. The Working State transport switch affects only State GET/UPDATE;
other tools retain their existing role clients. Embedded `build_server` integrations can supply
`resolve_client_factory`; omitting it preserves the synchronous role-client compatibility path.

## Codex full-control product profile

`codex-full` is the Codex product path. One authenticated Streamable HTTP endpoint exposes
resolve/get, Evidence capture, Proposal create/list/get/review, Evidence revoke/deletion status and
namespace cleanup/status, plus persistent `HOST_WORKING` cognitive state get/update. It requires
exactly one Host-bound project and internally routes calls
through reader, submitter, reviewer and operator Runtime credentials. One Codex controls those
roles, so results and audit logs state `SINGLE_HOST_FULL_CONTROL` and
`independent_host_review=false`; Runtime canonical actor separation is retained.

```bash
export MILAI_CODEX_TOKEN="$(openssl rand -hex 32)"
export MILAI_CODEX_PRINCIPAL_ID=codex-milai
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}'
export MILAI_CODEX_TASK_REF=product-11
# Optional for SESSION-scoped state: export MILAI_CODEX_SESSION_REF=session-20260904
# Also set the four MILAI_AGENT_{READER,SUBMITTER,REVIEWER,OPERATOR}_TOKEN values.
uv run milai-codex-full-mcp --host 127.0.0.1 --port 7337
```

See the [full HTTP MCP quickstart](../../docs/runbooks/http-mcp.md). The model cannot select tenant,
principal, role, project scope, authority, consistency or retry policy. Namespace cleanup has no
project argument. Working-state tools likewise expose no project, principal or scope-ref argument;
they use the Host-bound task/session refs. Governed lifecycle mutations retain literal confirmation;
working-state updates use `operation_id` plus exact version CAS. For `codex-full`, each public
`operation_id` is namespaced internally by authenticated principal, bound scope and tool before it
reaches shared Runtime role credentials; retries remain stable without cross-user collisions.
Exact Proposal, Claim, Evidence, deletion and cleanup IDs are rechecked against the server-bound
project before use or return. Proposal creation also checks every supporting and contradicting
Evidence reference against that project before the Runtime mutation is attempted.

`confirmation` literals remain accident guards. They are not server-verified proof that a current
user authorized an action. Mutation audit and result summaries therefore record
`authorization_evidence=NOT_SERVER_VERIFIED` and `confirmation_role=ACCIDENT_GUARD_ONLY` in
`SINGLE_HOST_FULL_CONTROL` mode. Revocation and namespace cleanup expose the Runtime's exact
reason-code enum in JSON Schema so error guidance cannot suggest an invalid value.

### Cognitive activation boundary

`codex-full` publishes a compact mandatory resume/checkpoint policy in standard MCP server
instructions and in both Working State tool descriptions. On resume/continue/prior-work requests,
the advertised policy requires `milai_working_state_get(scope=TASK)` before repository archaeology
or answering. Every `milai_working_state_get` result also includes a
server-authored `mcp_usage_contract`, even when State is `ABSENT`. The contract is deliberately
separate from `payload`:

```text
mcp_usage_contract   trusted description of how to use the tools
payload              fallible HOST_WORKING data; never instructions
```

Do not store tool instructions inside initial Working State. That creates a trust-boundary error
and cannot solve first-call discovery: Codex must already select GET before it can see the State.
The tool surface follows a 90/10 description policy: short descriptions explain intent, selection
time, side effects and retry safety; JSON Schema and actionable error results handle edge cases.
Every tool publishes standard MCP read-only/destructive/idempotent/open-world annotations. Every
successful `codex-full` result adds short `mcp_guidance` for the natural next step, without making
that step automatic. Retrieved data remains untrusted.

Zero-Skill selection isolation proved explicit GET callability (`1/1`) but found zero natural MiLA
calls for the same generic resume intent with two, three and thirteen visible tools (`0/3`). Catalog
reduction is therefore not a sufficient activation mechanism, and trigger-first metadata tuning is
exhausted.

Standard MCP exposes the policy but cannot force a client/model to call a tool. `milai codex` now
implements the separate `HOST_MANAGED` path: it performs the session-start GET before launching
Codex and supplies the bounded result as untrusted context. This is not a natural
self-maintained-cognition claim and does not require a Skill.

For remote users, set `MILAI_CODEX_USER_REGISTRY` and issue one credential-owned principal per user
with `milai-codex-user issue`. The command outputs a common `mcpServers` client configuration
object. First MCP connection atomically activates the pending user and automatically appends
registration audit. Only the standard `Authorization: Bearer` header is required; no client header
selects identity or authority. See the
[JSON-only remote registration guide](../../docs/runbooks/remote-mcp-json-registration.md).

For token-free client onboarding, set `MILAI_OAUTH_DB` and use a trusted HTTPS public base URL.
The server then exposes OAuth Protected Resource/Authorization Server metadata, DCR,
Authorization Code + S256 PKCE, rotating refresh tokens, revocation, and a one-time enrollment
consent page. When OAuth persistence is enabled, a non-loopback HTTP public base URL is rejected
before the edge database is created; loopback HTTP remains available for local development and
tests. After a gateway is configured, verify it without credentials or state-changing OAuth calls:

```bash
uv run milai-oauth-readiness --base-url https://<your-milai-host>
```

The probe uses the platform trust store and has no option to disable certificate verification. See
the [OAuth DCR runbook](../../docs/runbooks/oauth-http-mcp.md).

## Read-only reasoning-capable Host profile

`agent-memory` remains the least-privilege read-only profile. It exposes one query-first tool:

```text
milai_memory_resolve(query, previous_context_id?)
```

The response is `memory-evidence-context-v1`: governed evidence, source identity, proven snapshot
metadata, optional Runtime-proven continuation, and machine-readable warnings. It deliberately
does not expose Runtime ranking scores, QueryIR, Binding, Sufficiency, Reader drafts, or a generated
answer. The Host judges ordinary answer sufficiency and writes the final response; MiLAi continues
to own scope, revocation, temporal validity, canonical currentness, evidence identity, routing and
retrieval provenance.

```bash
export MILAI_BASE_URL=http://127.0.0.1:18080
export MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN"
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}'
export MILAI_AGENT_REQUIRED_AUTHORITY=INFORMATIONAL
export MILAI_MCP_HTTP_BEARER_TOKEN="$(openssl rand -hex 32)"
export MILAI_MCP_HTTP_PRINCIPAL_ID=codex-milai
uv run milai-agent-memory-mcp \
  --host 127.0.0.1 \
  --port 7337 \
  --resolve-budget-profile MCP_INTERACTIVE_STANDARD_V01
```

`milai-agent-memory-mcp` is the product wrapper. It fixes authenticated Streamable HTTP,
`agent-memory`, and zero automatic Runtime retries; its CLI intentionally exposes only bind/path
and Host-owned budget-profile settings. Use the general `milai-mcp` executable only for legacy
stdio and non-product profiles.

The inbound HTTP credential is separate from `MILAI_AGENT_TOKEN`, which authenticates this service
to Runtime. One P08 process binds one credential to the fixed `MILAI_AGENT_SCOPE_JSON`; identity and
scope are never model arguments. Public probes are `/healthz` and `/readyz`; `/mcp` requires an
`Authorization: Bearer ...` header.

For a sealed replay, the Host may set `MILAI_AGENT_AS_OF` to one timezone-aware RFC 3339 value.
The facade forwards that Host-owned value as the resolve reference time without adding an MCP tool
argument, so the model cannot choose or drift the replay boundary. If it is unset, Runtime uses the
normal request-time boundary.

`continuation: null` means only that Runtime made no continuation assertion. It never means all
relevant memory has been found or that an answer is complete. A non-null continuation is forwarded
only when Runtime supplies a concrete frontier assertion.

| Host-owned profile | Results / candidates | Context / deadline | Recommended calls |
| --- | ---: | ---: | ---: |
| `MCP_INTERACTIVE_STANDARD_V01` | 50 / 120 | 8,192 tokens / 2,000 ms | 3 |
| `MCP_INTERACTIVE_WIDE_V01` | 50 / 120 | 16,384 tokens / 5,000 ms | 3 |
| `MCP_RESEARCH_V01` | 50 / 120 | 16,384 tokens / 5,000 ms | 5 |

The call count is Host guidance, not a semantic protocol limit. The deprecated aliases
`OPENWORKER_USABILITY_WIDE_V01` and `OPENWORKER_USABILITY_WIDE_V02` resolve to Standard and Wide;
the facade reports both requested and resolved names.

MCP Interactive Mode makes memory available but cannot guarantee that a Host model invokes it.
Guaranteed-memory deployments must perform Host-owned prefetch before model reasoning and report
their results separately.

```bash
export MILAI_BASE_URL=http://127.0.0.1:18080
export MILAI_AGENT_TOKEN="$MILAI_AGENT_READER_TOKEN"
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}'
export MILAI_AGENT_REQUIRED_AUTHORITY=ACTION_SAFE
export MILAI_AGENT_CONSISTENCY_FLOOR=CANONICAL_REQUIRED
export MILAI_AGENT_MAX_LIMIT=3
uv run milai-mcp --profile reader-lite
```

`reader-lite`（默认）暴露 query-only `milai_memory_resolve` 与兼容窗口内的
`milai_recall`；`reader-detail` 额外暴露 `milai_memory_get` 以及
Claim/OpenIssue/Trace/Evidence metadata 按需恢复工具，
旧 `reader` 仅作为兼容别名保留。Profiles are exact allowlists. The `reader-lite` resolve schema
accepts `query` and the optional opaque `previous_context_id`; consistency, authority, scope and limit are fixed by the Host, and any
model-supplied policy argument is rejected before a Runtime request. `milai_memory_resolve`
returns `access-outcome-v0.1` with distinct HIT/PARTIAL/CONTESTED/ABSENT/ABSTAINED/DENIED/
UNAVAILABLE states. A locator is not bearer authority: Runtime reauthorizes and validates coverage,
dependencies and currentness online; miss/expiry/change returns to EXACT/SEARCH in the same call.
`milai_memory_get` 只接受一个 ClaimID 或严格的
`{subject,predicate,claim_type}` StateKey；可选 `valid_at`/`known_at` 读取双时态历史状态。
返回的 `memory-state-view-v0.1` 分开报告 addressable/reachable/correctly-resolved，并保留
OpenIssue、provenance pointer 与 exact structural cost。带已知地址 hint 的 detail-profile
`milai_memory_resolve` 进入同一 exact path。
DG-13 M4 在 configurable `reader-detail` resolve 中增加只能收窄候选的
`entities` / `memory_types` hints；`reader-lite` 仍只允许 query 和 opaque locator。
Runtime 为每次 Search 生成 candidate/deadline/context/reranker 上限，在排序前执行
tenant/principal/project/time 及可选 entity/type 硬分区，只在 sparse insufficiency 后进入
filtered vector，并在 Canonical Gate 后才判断 sufficiency。
DG-13 M6 仅在 configurable detail profiles 增加可选 `task_context`：允许
`project_ids`、`entities`、`memory_types` 与非权威 `action_risk` hint。Runtime 将前三者与
Host-bound scope/已有 hints 求交；无交集请求直接拒绝，`action_risk` 只进入
`task_enhancement` trace，不能改变 authority 或 consistency。`reader-lite` 和 task-off
`reader-detail` 仍保持 query-first，不需要 Task identity。
DG-13 M5 增加不进入普通模型 catalog 的独立 `reviewer` profile：它可通过
`milai_proposals_list` / `milai_proposal_get` 检查 canonical pending Proposal，并以
`milai_memory_review` 执行显式 `APPROVE` / `REJECT`。review decision 与 confirmation 必须一致；
reviewer credential 只具备 read/review capability，不能 capture/propose，submitter 也不能
review，因此普通模型不能自批。There is deliberately no direct Claim update, issue resolution,
tenant clear, or database query tool. Tokens stay outside tool arguments and tool results. P08
approves authenticated loopback Streamable HTTP. Explicit non-loopback deployment follows ADR-035;
Bearer-only first-use multi-principal registration follows ADR-037. All users of one process remain
collaborators inside its one Host-bound project; this is not tenant/project isolation.

`ACTION_SAFE` requires a non-empty host-configured Scope. Scope, authority, profile, base URL and
token cannot be supplied by a model tool call. The consistency floor cannot be weakened and the
limit cannot exceed the host maximum. Proposal tool input is validated as a strict `ProposalDraft`
before any HTTP request. Current `2026-07-28` and legacy `2025-11-25` stdio clients are covered by
executable interoperability tests.

DG-13 vNext names migrate under the single-owner compatibility contract in
[`docs/contracts/DG13-MCP-vNext-compatibility-v0.1.md`](../../docs/contracts/DG13-MCP-vNext-compatibility-v0.1.md).
`milai_memory_resolve`（M1，M3 online reuse，M4 bounded Search，M6 optional TaskContext）、
`milai_memory_get`（M2）与
reviewer-only `milai_memory_review`（M5）已从 TARGET family 注册；其余 TARGET
名称在各自 owning milestone 前仍不注册。

`reader-lite` retains `access-outcome-v0.1` over stdio for OpenWorker compatibility. It is not the
Codex HTTP facade. This keeps the P08 interface small without rewriting Runtime or silently
breaking the existing OpenWorker adapter.
# Existing private HTTP MCP and Host-managed startup

For the ordinary OAuth plugin and the optional existing-connection launcher in MCP
0.1.5, see [private working memory](../../docs/runbooks/private-working-memory.md).
`milai codex --mcp-url ...` uses an ordinary client bearer credential and the existing
public TASK read; it does not start a privileged local MCP or accept identity overrides.
The public `prepare_http_working_context` Python helper exposes the same bounded read
for trusted Host integrations. Reads are attributed to the Host, and writes remain
model-selected. This helper does not implement OAuth credential acquisition or refresh.
