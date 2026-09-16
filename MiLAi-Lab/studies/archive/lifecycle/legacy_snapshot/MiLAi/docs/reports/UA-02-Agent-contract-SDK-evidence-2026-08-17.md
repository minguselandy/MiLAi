# UA-02 Agent Contract 与 Python SDK 证据

> Decision: `PASS FOR LOCAL AGENT INTEGRATION`  
> Contract: `agent.v1`; Runtime/Schema remain `CANDIDATE/EXPERIMENTAL`

## Implemented contract

- `/v1/capabilities` reports the authenticated profile, effective capability list, API/contract
  versions, routes, consistency modes, limits, data/crypto/embedding/remote facts.
- OpenAPI covers capabilities, health, L0/L1 recall, ContextCapsule, Evidence, Proposal, Claim,
  OpenIssue, trace, causal token, revoke/deletion and Episode. The tool contract fixes exact profile
  catalogs and forbidden operations.
- `AsyncMilaiClient` is the sole HTTP/retry implementation; `MilaiClient` is a sync wrapper. Both
  negotiate `agent.v1` before Agent calls and reject non-loopback origins by default.
- Typed models preserve `OK/DEGRADED/ABSTAINED`, related OpenIssue IDs (including rejected
  candidates), trace, canonical position, fallback and partial Evidence/Proposal outcomes.
- Stable operation IDs become `Idempotency-Key`; network/429/503 retry is bounded with identical
  bytes and key. 409 is typed, non-retryable and never regenerated.
- Prompt formatting is `trust=data-only`, byte/token bounded and records omitted IDs and actual
  budgets. Generic tools use a host-fixed Scope/authority and cannot expose review.
- Evidence carries an explicit data classification. Runtime checks it against `data_mode` before
  writing the Blob; UI enforcement is only a convenience mirror.

## Executable evidence

`integrations/python-client`: Ruff, format, strict mypy and `20 passed`. Tests cover negotiation,
incompatibility, typed request models, partial outcome, close, 429/503 exact replay, 409 no-retry,
formatter budgets, generic catalogs and the mandatory async loop. Runtime contract tests
mechanically compare the typed client's route surface to OpenAPI and prove forbidden review/direct
mutation paths are absent.

The three-session report additionally proves real HTTP calls through the SDK on an isolated
PostgreSQL database, including causal RYW, OpenIssue preservation and post-revoke abstention.
