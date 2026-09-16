# UA-05 Framework 与三会话 E2E 证据

> Decision: `PASS`  
> Fixture: isolated PostgreSQL + encrypted temporary Blob + synthetic tenant

## Frameworks

- Generic async loop performs mandatory pre-model `CANONICAL_REQUIRED` recall and no implicit
  write.
- LangGraph runs recall then Context nodes; checkpoint keeps framework state and MiLAi references
  only. Tool capture can produce host-classified `RUNTIME_OBSERVATION`; human interrupt never
  reviews.
- AutoGen implements the official `Memory` protocol. Query/update_context add `milai-memory-data`
  as user data; add requires confirmed/redacted user/tool input; clear fails closed.
- Coding hook installer is atomic, idempotent, scope-explicit, preserves unrelated hooks and
  defaults capture to `OFF`.
- Four example directories each have an executable offline smoke; all four pass.

Package gates: Python client `20 passed`, MCP `6 passed`, LangGraph `2 passed`, AutoGen `2 passed`,
Hooks `2 passed`; all corresponding Ruff/format/strict-mypy gates pass.

## Three-session result

Machine report: `docs/reports/UA-05-three-session-agent-e2e-2026-08-17.json`  
SHA-256: `1d3d42325428dd8a0b96c9ab5bac6b7d5475e42ec9b1b7bb5b9dd5b5fc600bea`

1. Generic SDK captures Python 3.11 Evidence and pending CREATE Proposal. Recall is ABSTAINED before
   independent review; after APPROVE, worker projection and causal token, generic/MCP/LangGraph
   independently accept the same V1 with their own persisted trace.
2. MCP captures Python >=3.12 contradiction and submits CONTRADICT. Review creates one OpenIssue;
   Head stays V1. Generic ContextCapsule and LangGraph preserve both branches and discharge rule;
   generic/MCP/LangGraph/AutoGen all abstain and return the issue reference.
3. LangGraph captures independent CI/runtime `RUNTIME_OBSERVATION` Evidence. Governed SUPERSEDE
   resolves the issue and creates V2. MCP operator revokes one resolution Evidence; the same issue
   reopens `WAITING_EVIDENCE`. Before purge, stale FTS/vector candidates are rejected as
   `GROUNDING_BLOCKED` through generic/MCP/LangGraph. Physical reconciliation finishes
   `derived_purge=COMPLETED`, `primary_bytes=ERASED`.

The report records `hard_failures=[]`; cleanup confirms owner `milai_owner`, zero connections and
successful temporary database removal.
