# MiLAi Product

当前优先交付：[MiLA MCP 0.1.6 全功能使用与安装](examples/mcp-release/README.md)。
公网入口 `https://milai.aigcit.com:7960/mcp`，OAuth 登录后按账号隔离私人记忆；
[包验证与剩余限制](docs/releases/MCP_0.1.6_HANDOFF_20260908.md)。实验已暂停。

MiLAi Product is the deployable side of the MiLAi personal-memory control plane. It keeps the
working Runtime, PostgreSQL migrations, frozen logical architecture, public contracts, six Agent
adapters, product examples, and product-facing operations documentation in one small repository.

> Status: `0.1.0-candidate`  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`  
> Deployment boundary: local, single-user, single configured tenant  
> Release claim: not production-ready

This repository was created by copying usable product assets from the legacy mixed MiLAi workspace.
The legacy workspace was not edited, moved, or deleted. Research harnesses, benchmark data,
experiment runners, Goal history, run artifacts, virtual environments, model files, logs, and build
outputs are intentionally absent.

## What is included

```text
MiLAi-Product/
├── architecture/v1.0/       Frozen logical architecture and validator
├── contracts/agent/v1/      Public Agent/MCP contracts
├── docs/                     Product goals, status, architecture, audit, ADRs and runbooks
├── examples/                 MCP, generic-agent, LangGraph and AutoGen examples
├── integrations/
│   ├── python-client/        Typed HTTP client (`milai-client`)
│   ├── mcp/                  Streamable HTTP MCP service + stdio compatibility (`milai-mcp`)
│   ├── openworker-mcp/       OpenWorker relay, broker and Host adapter
│   ├── hooks/                Coding-agent lifecycle hooks
│   ├── langgraph/            LangGraph adapter
│   └── autogen/              AutoGen adapter
└── runtime/                  Flask API, worker, PostgreSQL schema and product tests
```

The primary local Codex Host route is:

```text
Codex
→ authenticated Streamable HTTP MCP (`codex-full`, `/mcp`)
→ typed Python client
→ loopback Flask Runtime
→ PostgreSQL Canonical Core / projections / local blob store
→ governed read/write/review/revocation lifecycle
→ Host reasoning and final answer
```

OpenWorker's UDS relay/broker and `reader-lite` remain a supported compatibility route. They are not
the contract used by reasoning-capable MCP Hosts.

Product-05 adds optional Host-owned exchange settlement behind a separate submitter socket. The
Worker/model still sees only `reader-lite`; the Host captures the exact user and terminal assistant
turn after a successful answer, with replay-safe source identity and assistant support lineage.
Omitting the submitter configuration preserves the read-only path. Direct Reader remains the
default. Product-06 removed the rigid model-generated Ledger from its candidate path but did not
improve the 12-case fixed-Context result because four of five remaining misses lacked required
Evidence groups before Reader execution. The completed
[Product-07 Goal](docs/goals/MILA_PRODUCT-07_模型引导证据补全与通用召回_GOAL.md) tested a
query-local same-pool RecallWorkspace. It passed V0 development at 11/12 and 0.9167 coverage, but
the frozen 24-case R3 Context comparison regressed complete EvidenceSets from 10 to 8 and mean group
coverage from 0.5667 to 0.4722. P07-H1 failed, so H2 and Answer/Judge execution were not entered.
Direct remains current; the candidate stays default OFF and formal 500 remains unconsumed.

Product-08 freezes the Codex product boundary: the Host owns semantic sufficiency,
residual queries and the final answer; MiLAi owns scope, revocation, temporal/current validity,
retrieval, Evidence identity and audit. The `agent-memory` profile exposes only
`milai_memory_resolve(query, previous_context_id?)`, returns `memory-evidence-context-v1`, and does
not run an internal Reader, EvidenceLedger, generated `COMPLETE`, or vLLM. Real Codex passed the
required-memory, no-memory and explicit-continuation Streamable HTTP checks. Host capture and real
coding-memory retrieval are successor work; Claude is not a P08 gate and no Claude compatibility
claim is made. See [ADR-030](docs/adr/ADR-030-host-reasoning-mcp-evidence-context.md).

Product-09 completes the real persistent path behind that interface. Trusted HostAgentEvent capture,
PostgreSQL Evidence/projection, service restart and project-scoped Codex recall pass end to end. A
four-case opened-development LongMemEval diagnostic answered 3/4 exactly; multi-session COUNT remains
unresolved even though the required sessions were visible. A longer Host instruction regressed the
slice and was removed, so the product keeps the smaller P08 interface rather than embedding a hidden
Reader prompt. See the
[Product-09 Goal](docs/goals/MILA_PRODUCT-09_Codex_HTTP持久记忆生命周期_GOAL.md).

The completed diagnostic
[Product-10 Goal](docs/goals/MILA_PRODUCT-10_InstancePreservingEvidence与Continuation_GOAL.md)
kept that Host/MiLA boundary closed. Its sealed 24-case matched run localized admission loss, but two
general B1 repairs failed H1: the final arm gained three groups while displacing three and reached only
`+0.04167` mean coverage gain. It therefore ended
`PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED`; continuation and real-Codex stages were not entered.

The Product ships a fixed `milai-codex-full-mcp` HTTP wrapper and retains
`milai-agent-memory-mcp` as its least-privilege read-only alternative. The rejected B1 remains
default-off. Formal 500 scoring was not consumed and proxy instance labels remain non-gold.

The planned
[Product-11 Goal](docs/goals/MILA_PRODUCT-11_ExplicitEvidenceAcquisition与NonDestructiveContinuation_GOAL.md)
does not reopen that B1. It freezes A0 for the first call, develops persistent non-destructive
continuation for novel Evidence, and separately evaluates explicit turn/span acquisition inside
governed sources before any anchor-first renderer rollout. Adjacent hydration becomes presentation
only, never discovery. Goal v0.2 additionally requires the primary continuation arm to resume only
its persisted frontier—without same-query reacquisition—and makes successor idempotency a database
operation-fingerprint invariant. Execution is now authorized subject to stage gates: ADR-032 and the
acceptance contract are frozen. The final label-blind X0 A0 trace passed fresh-DB, 24/24 trace,
Canonical=0 and cleanup gates, but its post-trace PENDING proxy join found `0 continuation / 8
intra-source / 16 control` opportunities. Human completion remains 0/24, so Product behavior and
migration have not started, and Formal 500 remains unconsumed.

Goal v0.6 also includes a proposal-free dual-human X0 handoff. The workflow is ready, but real HUMAN
completion remains 0/24; no Product behavior, migration, or treatment run has entered.

After three consecutive checks, execution is externally blocked awaiting the two genuine submissions.
This is not an experimental terminal and does not authorize A0 reshaping or proxy promotion.

The independent Host Cognitive Affordance delivery now gives `codex-full` a persistent,
scope-bound working memory through `milai_working_state_get` and
`milai_working_state_update`. It stores Codex-owned goals, requirements, hypotheses, decisions,
blockers, memory needs and next actions as append-only `HOST_WORKING` versions with exact CAS, TTL,
retry idempotency, RLS and exact Evidence pointers. Reads and writes are audited automatically
without logging payload text. Working state is fallible Host cognition: it is not Evidence,
Canonical State, a completeness claim, or Product-11 retrieval continuation, and recall never
mutates it. See [ADR-034](docs/adr/ADR-034-host-cognitive-affordance-layer.md) and the
[HTTP MCP runbook](docs/runbooks/http-mcp.md). HC4-A0 passive adoption was negative at 0/8 natural
Working State calls. HC4-A1 then completed a genuine four-session chain under bounded,
non-mandatory guidance and remained 0/4. The frozen stop rule parks self-maintained adoption as a
manual/explicit feature and forbids further prompt escalation inside HC-4. Cross-session usefulness
remains unevaluable, so the current claim is persistence usability rather than a Codex benefit
claim. See the [A1 audit](docs/goals/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1_EXECUTION_AUDIT_20260904_193542.md).

Remote new users use a unique server-issued Bearer credential mapped to a server-owned principal;
first MCP connection performs audited activation. The client sends standard Bearer authorization
without `x-agent-id`. Codex uses `codex mcp add --url ... --bearer-token-env-var ...`; the common
`mcpServers` JSON shape is client-specific configuration, not the MCP protocol. See the
[remote registration guide](docs/runbooks/remote-mcp-json-registration.md).

The MCP package also implements OAuth DCR URL-only onboarding with Authorization Code + S256 PKCE,
browser enrollment, rotating refresh tokens and revocation. It passes loopback and real full-catalog
HTTP tests, but the current public NAT endpoint cannot yet serve a trusted HTTPS origin, so URL-only
public registration remains blocked pending gateway/domain TLS. See the
[OAuth runbook](docs/runbooks/oauth-http-mcp.md) and
[implementation audit](docs/goals/HTTP-OAUTH-DCR-01_IMPLEMENTATION_AUDIT_20260904_093549.md).

The earlier informational-admission/additive-retrieval work is retained under
[ADR-029](docs/adr/ADR-029-informational-context-admission-and-additive-recall.md) as the default-OFF
`P08-PREBASE-CONTEXT-CANDIDATE`; it has no Product-08 execution authority or effect claim.

MiLAi maintains these boundaries:

```text
Evidence is not belief.
Proposal is not commit.
Context is not canonical state.
Confidence is not authority.
```

Only the governed canonical procedure may create a `ClaimVersion` or change an `OpenIssue`.
Retrieval, models, adapters, Formation artifacts, and Context cannot write canonical truth directly.

## Quick start

Prerequisites:

- Python 3.11 or 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose, or PostgreSQL 16 with pgvector
- PostgreSQL client tools for backup/restore operations

```bash
cd runtime
cp .env.example .env
# Replace every placeholder secret and database password before starting.
uv sync --frozen --dev --extra embedding
uv run milai-ops init
uv run milai-ops doctor --json
uv run milai-ops start --background
uv run milai-ops smoke-test
```

Stop the local stack with:

```bash
uv run milai-ops stop
```

The exact first-run and recovery procedures are in:

- [First run](docs/runbooks/first-run.md)
- [Local Runtime](docs/runbooks/local-runtime.md)
- [Agent integration](docs/runbooks/agent-integration.md)
- [Backup and restore](docs/runbooks/backup-restore.md)
- [Projection and purge recovery](docs/runbooks/projection-and-purge-recovery.md)

Do not use real personal data until encrypted storage, key recovery, backup restore, and deletion
propagation have been exercised in the intended deployment.

## Agent entry points

The local Codex interface is authenticated loopback Streamable HTTP MCP. `codex-full` places the
governed lifecycle behind one endpoint; OpenWorker keeps its stdio/UDS compatibility path.

```bash
cd integrations/mcp
uv sync --frozen --dev --python 3.11
export MILAI_BASE_URL=http://127.0.0.1:18080
# Load the four scoped MILAI_AGENT_{READER,SUBMITTER,REVIEWER,OPERATOR}_TOKEN values
# from the Runtime secret store; do not put them in Codex configuration.
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["milai"]}'
export MILAI_AGENT_REQUIRED_AUTHORITY=INFORMATIONAL
export MILAI_CODEX_TOKEN="$(openssl rand -hex 32)"
export MILAI_CODEX_PRINCIPAL_ID=codex-milai
uv run milai-codex-full-mcp \
  --host 127.0.0.1 \
  --port 7337 \
  --resolve-budget-profile MCP_INTERACTIVE_STANDARD_V01
```

Available command entry points include:

```text
milai-api
milai-worker
milai-db-check
milai-ops
milai-mcp
milai-codex-full-mcp
milai-agent-memory-mcp
milai-mcp-broker
milai-mcp-relay
milai-openworker-adapter
milai-hook
milai-hook-config
```

MCP profiles are exact allowlists. Model tool input cannot select tenant, broaden scope, lower the
consistency floor, raise candidate limits, inject credentials, or modify a Claim directly.
`codex-full` lets one Codex control Proposal and Review through role-routed Runtime credentials, but
marks that path as `SINGLE_HOST_FULL_CONTROL` and never calls it independent review.

## Development checks

Runtime:

```bash
cd runtime
uv sync --frozen --dev --python 3.11
uv run ruff check src tests migrations
uv run mypy
uv run pytest -q
uv build
```

Frozen architecture:

```bash
runtime/.venv/bin/python architecture/v1.0/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0/scripts/verify_lock.py \
  --scope bundle \
  --mode release \
  --expected-manifest-sha256 ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e
```

Each adapter has its own `pyproject.toml` and `uv.lock`:

```bash
cd integrations/python-client   # or mcp/openworker-mcp/hooks/langgraph/autogen
uv sync --frozen --dev --python 3.11
uv run ruff check src tests
uv run pytest -q
uv build
```

The product repository must never import from a sibling `evals`, `research`, or root `scripts`
package. Benchmark and experimental work belongs in `MiLAi-Lab` and consumes the product only
through published interfaces or an explicit source identity.

## Documentation

- [Product identity manifest](product.manifest.json)
- [Product goals](docs/PRODUCT_GOALS.md)
- [Authenticated HTTP MCP quickstart](docs/runbooks/http-mcp.md)
- [JSON-only remote MCP registration and use](docs/runbooks/remote-mcp-json-registration.md)
- [Completed Product-08 Codex HTTP MCP baseline](docs/goals/MILA_PRODUCT-08_Codex_ClaudeCode_MCP证据上下文产品基线_GOAL.md)
- [Product-08 lightweight tracker](docs/goals/MILA_PRODUCT-08_TRACKER.md)
- [Latest completed Goal: Product-07 same-pool EvidenceSet selection](docs/goals/MILA_PRODUCT-07_模型引导证据补全与通用召回_GOAL.md)
- [Product-07 lightweight tracker](docs/goals/MILA_PRODUCT-07_TRACKER.md)
- [Latest completed experiment: Product-06 model-native Reader](docs/goals/MILA_PRODUCT-06_Reader集合证据消费与最小执行闭环_GOAL.md)
- [Product-06 tracker](docs/goals/MILA_PRODUCT-06_TRACKER.md)
- [Product-05 OpenWorker Memory lifecycle, user isolation, and grounded evidence use](docs/goals/MILA_PRODUCT-05_OpenWorker记忆闭环用户隔离与集合证据消费_GOAL.md)
- [Latest completed Goal: Product-04 planning and Reader availability without TypeBinding](docs/goals/MILA_PRODUCT-04_QueryTaskContract语义归一化与通用召回_GOAL.md)
- [Latest completed delivery Goal: Product-03 OpenWorker MCP usability](docs/goals/MILA_PRODUCT-03_默认基线校正与代表失败族召回优化_GOAL.md)
- [Product-02 completed delivery Goal](docs/goals/MILA_PRODUCT-02_AnswerTurn证据装配与精准召回_GOAL.md)
- [Product-02 execution tracker and terminal evidence](docs/goals/MILA_PRODUCT-02_TRACKER.md)
- [Product-01 historical Goal](docs/goals/MILA_PRODUCT-01_本地可用性与简单精准召回_GOAL.md)
- [Current status](docs/PRODUCT_CURRENT_STATUS.md)
- [Product architecture](docs/PRODUCT_ARCHITECTURE.md)
- [Code audit](docs/CODE_AUDIT.md)
- [Frozen logical architecture](architecture/v1.0/README.md)
- [Lean V1 implementation contract](docs/reference/MiLAi_Lean_V1_实施合同.md)

## Known release constraints

- The Runtime and Schema remain candidates; logical-architecture freeze is not product release.
- No project license has been selected. Packages and the OpenWorker-derived image remain local-only.
- Remote MCP and public network deployment are not approved.
- Product paths copied from experimental work remain default-off unless their product gate is
  explicitly documented.
- `MCP_INTERACTIVE_WIDE_V01` is an opt-in local usability profile; deprecated
  `OPENWORKER_USABILITY_WIDE_V02` is only an exact alias. This is not a default release decision,
  and the formal 500-case LongMemEval holdout remains untouched.
- The product split removes repository clutter; it does not by itself establish retrieval quality,
  LongMemEval parity, or production security.
