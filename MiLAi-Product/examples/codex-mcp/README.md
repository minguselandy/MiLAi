# Codex + MiLAi MCP

For AIGCIT login and private per-user memory, merge
[milai-aigcit-client.toml.example](milai-aigcit-client.toml.example) into the client's
configuration and follow the [AIGCIT runbook](../../docs/runbooks/aigcit-http-mcp.md).
This profile uses OAuth and automatically scopes memory by verified identity.
The bearer examples below describe the separate legacy/local deployment mode.

Run the persistent MiLAi Streamable HTTP MCP service, then merge
[`config.toml.example`](config.toml.example) into the project-scoped `.codex/config.toml` or the
user Codex config. The complete first-run and least-privilege token procedure is in the
[HTTP MCP quickstart](../../docs/runbooks/http-mcp.md). Keep credentials and identity out of tool
arguments:

```bash
export MILAI_BASE_URL=http://127.0.0.1:18080
export MILAI_AGENT_READER_TOKEN="...reader credential..."
export MILAI_AGENT_SUBMITTER_TOKEN="...submitter credential..."
export MILAI_AGENT_REVIEWER_TOKEN="...reviewer credential..."
export MILAI_AGENT_OPERATOR_TOKEN="...operator credential..."
export MILAI_AGENT_SCOPE_JSON='{"project_ids":["my-project"]}'
export MILAI_AGENT_REQUIRED_AUTHORITY=INFORMATIONAL
export MILAI_AGENT_CONSISTENCY_FLOOR=CANONICAL_REQUIRED
export MILAI_CODEX_TOKEN="$(openssl rand -hex 32)"
export MILAI_CODEX_PRINCIPAL_ID=codex-my-project
export MILAI_CODEX_TASK_REF=product-11

milai-codex-full-mcp \
  --host 127.0.0.1 \
  --port 7337 \
  --resolve-budget-profile MCP_INTERACTIVE_STANDARD_V01
```

In another shell, export the same inbound credential and start Codex:

```bash
export MILAI_CODEX_TOKEN="...same value..."
curl --fail http://127.0.0.1:7337/readyz
codex mcp list
codex
```

With Codex CLI 0.153.0, the equivalent registration command is:

```bash
codex mcp add milai \
  --url http://127.0.0.1:7337/mcp \
  --bearer-token-env-var MILAI_CODEX_TOKEN
codex mcp list --json
```

`codex-full` exposes the complete governed lifecycle. Tenant, principal, Runtime role credentials,
project scope, authority, consistency and budget stay Host-owned. Capture permission, Proposal
scope/authority, working-state scope identity and the namespace-cleanup project are injected by the
facade. `milai_working_state_get` / `milai_working_state_update` persist Codex's fallible task model
as `HOST_WORKING`; they do not change Canonical Memory.

The dedicated executable fixes authenticated Streamable HTTP, `codex-full`, and zero automatic
Runtime retries. The same Codex Host controls all lifecycle stages, and every mutation is marked
`SINGLE_HOST_FULL_CONTROL`; review is not represented as independent-Host review. The read-only
`milai-agent-memory-mcp` remains available for least-privilege deployments.

For a memory-dependent task, Codex should call `milai_memory_resolve`, reason over the returned
evidence, and answer directly. If evidence reveals a specific missing semantic need, it may make a
focused follow-up call. `continuation: null` is not a statement that memory is complete.

This is MCP Interactive Mode: MiLAi is available, but tool invocation remains a Host-model choice.
Use a Host-prefetch wrapper when memory access must be guaranteed before reasoning.

HTTP-FULL-01 covers the local Codex full lifecycle over Streamable HTTP. Stdio remains an
implementation compatibility/debug transport.

For a different machine that only needs to register against the existing public endpoint, use the
token-free [remote-client bundle sources](remote-client/README.md). The built archive is under
`integrations/mcp/dist/remote-client/`; transfer its token separately.
