# Product-08 Codex Streamable HTTP MCP E2E

Date: 2026-09-03  
Status: `PASS_PRODUCT08_CODEX_HTTP_MCP_USABLE`

This study validates the Product-08 external boundary:

```text
Host owns semantic sufficiency.
MiLAi owns memory correctness.
```

P08 acceptance uses Codex only. Claude Code is not an entry gate or a claimed compatibility target.
The earlier additive-retrieval candidate remains historical and default OFF.

## Real Codex HTTP result

Codex CLI `0.151.0` connected by URL to an independently running Product `milai-mcp` Streamable
HTTP service. A deterministic black-box Runtime surrogate fixed retrieval content while preserving
real HTTP MCP initialization, Bearer authentication, protocol sessions, tool discovery, tool calls,
continuation and Host answers.

| Scenario | Resolve calls | Model arguments | Result | Wall time |
| --- | ---: | --- | --- | ---: |
| memory required | 1 | `query` | exact `P08-CEDAR-731` | 25.985 s |
| memory not needed | 0 | none | exact `4` | 11.658 s |
| explicit continuation | 2 | `query`; then `query + previous_context_id` | exact two-part marker | 32.450 s |

The continuation returned a distinct Evidence identity. Codex never controlled identity, tenant,
scope, authority, consistency, credentials or budget. The service exposed public `/healthz` and
`/readyz`; unauthenticated `/mcp` was rejected and authenticated MCP traffic used `POST`, `GET` and
`DELETE` on `/mcp`.

Artifacts:

- `var/product08/codex-http-memory-required.json`
- `var/product08/codex-http-no-memory.json`
- `var/product08/codex-http-continuation.json`
- reusable runner: [`tools/run_product08_codex_mcp.py`](../../tools/run_product08_codex_mcp.py)

These are Host/transport/facade mechanism results. They do not measure PostgreSQL retrieval quality,
real coding-memory utility or LongMemEval accuracy.

The final Product pin is `data/locks/product08-host-mcp.lock.json`: Product tree
`d866c5ff82f67bacc7594be4cddb159e1d0181bf8eb4f71a309185883ff0cc1a` over 329 files, lock digest
`5b15eb6c2c592f4ae0dc50bd0e639f3833ab164652da6fe9f998350a568fc386`, verification `valid=true`.

## Failure and general repair

The first HTTP readiness attempt called the synchronous Runtime client directly inside the MCP
server's async event loop. It failed before Codex execution. The repair runs the bounded Runtime
capability probe in a Starlette thread pool. This is transport-level and applies to every Runtime;
no prompt phrase, benchmark rule, retry, retrieval expansion or Reader treatment was added.

## Product boundary

- P08 product transport: authenticated loopback Streamable HTTP at `/mcp`.
- `agent-memory` exposes only `milai_memory_resolve(query, previous_context_id?)`.
- vLLM, internal Reader, EvidenceLedger and generated `COMPLETE` are absent.
- stdio remains OpenWorker compatibility and local protocol-debug transport, not P08 evidence.
- one HTTP process binds one configured Bearer credential to one trusted principal/scope.
- non-loopback TLS/OAuth and multi-principal token issuance remain outside P08.

Host event capture, live PostgreSQL recall and multi-turn coding usability are successor goals. The
formal LongMemEval 500-case holdout was not authorized or consumed.
