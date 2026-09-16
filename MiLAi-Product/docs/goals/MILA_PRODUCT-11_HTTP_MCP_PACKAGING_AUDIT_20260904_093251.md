---
document_id: MILA-PRODUCT-11-HTTP-MCP-PACKAGING-AUDIT
version: "0.1"
status: PASS_BASELINE_HTTP_MCP_WRAPPER_USABLE
created_at: "2026-09-04T09:32:51+08:00"
goal: MILA-PRODUCT-11@0.7
package: milai-mcp@0.1.1
---

# Product-11 baseline HTTP MCP packaging audit

## Result

The existing `milai-agent-memory-mcp` entry point is a complete local authenticated Streamable HTTP
wrapper for the current baseline. No new MCP field, tool or Product-11 continuation assertion was
added.

```text
transport                    Streamable HTTP (fixed)
profile                      agent-memory (fixed)
automatic Runtime retries    0 (fixed)
public tools                 milai_memory_resolve only
public input                 query + optional previous_context_id
output                       memory-evidence-context-v1
inbound auth                 Bearer token → fixed principal/scope digest
health                       /healthz
readiness                    /readyz → Runtime capabilities
```

`MILAI_MCP_HTTP_BEARER_TOKEN` authenticates Codex to MCP. A distinct `MILAI_AGENT_TOKEN`
authenticates MCP to Runtime. Neither credential is a model tool argument.

## Verification

From `integrations/mcp`:

```text
uv sync --frozen --dev        PASS
pytest                        66 PASS
Ruff                          PASS
strict mypy                   PASS (6 source files)
wheel + sdist                 PASS
```

The HTTP smoke starts the installed console script as a child process against a synthetic Runtime,
checks public liveness/readiness, rejects unauthenticated `/mcp` with 401, negotiates the current MCP
client protocol, observes exactly one tool with the exact two-field input schema, calls it once, and
receives governed `memory-evidence-context-v1` Evidence with the fixed project scope.

A separate clean environment installed the built `milai-client` and `milai-mcp` wheels, invoked
`milai-agent-memory-mcp --help`, and imported both packages successfully. This proves the console
entrypoint does not depend on the editable source environment.

Local `codex-cli 0.153.0` was inspected directly. Its supported registration route is:

```text
codex mcp add <name> --url <streamable-http-url>
  --bearer-token-env-var <environment-variable-name>
```

The canonical usage instructions are in `docs/runbooks/http-mcp.md`.

## Claim boundary

This PASS is packaging/transport usability for the current baseline. Product-11 persisted-frontier
state, novel continuation selection and fine acquisition remain blocked by X0 human adjudication.
`continuation: null` therefore stays non-assertive. Formal access/scoring, Reader, vLLM and semantic
retry remain zero; the public MCP schema is unchanged.
