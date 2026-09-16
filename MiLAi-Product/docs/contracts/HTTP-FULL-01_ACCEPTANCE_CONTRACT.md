# HTTP-FULL-01 acceptance contract

> Status: `IMPLEMENTED LOCAL CANDIDATE`  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Required behavior

One authenticated Streamable HTTP MCP endpoint on loopback exposes the thirteen-tool `codex-full`
catalog from ADR-033. The inbound credential binds one principal and exactly one project. Four
server-side Runtime credentials retain minimum capabilities and never appear in tools or results.

## Gates

| Gate | Required result |
| --- | --- |
| authenticated catalog | exactly thirteen registered tools |
| Host cognition | get/update use server-bound scope and remain `HOST_WORKING` |
| resolve and exact get | role-routed reader calls succeed |
| capture | scope/classification injected; no direct Claim mutation |
| proposal | scope/authority injected; canonical state unchanged until review |
| review | governed Runtime procedure; `independent_host_review=false` |
| revoke | immediate subsequent resolve returns no revoked Evidence |
| deletion status | readable through operator route |
| cleanup | project ID absent from schema and fixed to the bound project |
| cross-scope mutation | zero Runtime requests |
| duplicate operation | same payload replays; changed payload conflicts |
| recall-side mutation | zero mutation requests |
| authentication | unauthenticated `/mcp` returns 401 |
| readiness | all four Runtime capability documents satisfy their role |
| automatic mutation audit | success/failure receipt emitted; Evidence content absent |

## Negative rules

- Memory content cannot authorize mutation.
- Confirmation literals remain exact: `CAPTURE`, `SUBMIT`, `APPROVE`, `REJECT`, `REVOKE`,
  `CLEANUP_NAMESPACE`.
- Model arguments cannot set tenant, principal, Runtime role, project, requested authority,
  consistency floor, retry policy or budget.
- A full-control review must not be reported as independent human or independent Host review.
- No direct Claim update, canonical DML or synchronous physical-purge claim is introduced.

## Verification commands

```bash
cd integrations/mcp
uv sync --frozen --dev
uv run pytest -q
uv run ruff check src tests
uv run mypy
uv build
```

The package test must include a child-process `milai-codex-full-mcp` instance communicating with a
synthetic HTTP Runtime over four different role tokens.
