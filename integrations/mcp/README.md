# MiLAi MCP

Local stdio-only MCP server. The server uses the official MCP Python SDK v2 line, which serves the
2026-07-28 protocol and the preceding initialized-session protocol on the same stdio endpoint.

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
tenant clear, or database query tool. Tokens stay in the child-process environment and are never
tool arguments or tool results. Remote MCP transport is not approved.

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
