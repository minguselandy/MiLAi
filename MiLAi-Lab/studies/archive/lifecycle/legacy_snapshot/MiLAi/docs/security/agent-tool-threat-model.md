# Agent Integration Tool Threat Model

> Status: `ACCEPTED FOR AGENT INTEGRATION BETA`  
> Boundary: loopback, single trusted host, synthetic/de-identified data only

## Assets and trust boundaries

- Canonical authority remains in Runtime procedures and the independent reviewer credential.
- The Agent host owns `base_url`, token, fixed Scope and required authority; none are model fields.
- MCP/SDK/framework outputs are untrusted data. Evidence/Claim text never becomes a system or
  developer instruction.
- Adapters have no database URL, migration role, Steward database credential or key material.

## Threat/control matrix

| Threat | Required control | Executable evidence |
|---|---|---|
| Tool parameter raises profile/tenant/Scope | Catalog fixed at process start; strict unknown-argument rejection; authenticated tenant ignores body | MCP profile/schema tests; E2E host-fixed Scope |
| Optional TaskContext widens Scope or grants action authority | Runtime intersects project/entity/type hints with Host-bound constraints; disjoint scope is invalid; action-risk is trace-only; reader-lite has no TaskContext field | M6 matched ablation, widening negative and exact schemas |
| Agent self-reviews or directly mutates Claim | Review exists only on a dedicated credential/profile with no capture/propose capability; submitter has no review capability; Runtime rejects same-actor review; no direct-update/issue-resolve/bulk-delete tool | contract auth negatives, exact catalogs and M5 lifecycle E2E |
| Prompt injection in Claim/Evidence | `trust=data-only`, bounded structured output, no raw source by default | SDK formatter and adapter tests |
| Credential reaches model/output/log | token only in host environment; confirmation summary uses content hash/length; config copies placeholder | secret scan, MCP tests, UI contract |
| Replay duplicates a write | stable host operation ID, identical key/payload retry; 409 never regenerated | SDK retry/idempotency tests and lifecycle replay |
| Revoked/stale projection is returned | every candidate re-enters Canonical Gate; trace records `GROUNDING_BLOCKED` | three-session E2E Session 3 |
| Live uncertainty is flattened | top-level relevant `open_issue_ids`; ContextCapsule preserves branches/discharge rule | three-session E2E Session 2 |
| Personal data enters before approval | server checks asserted `data_classification` against data mode before Blob write; UI mirrors but does not replace it | Evidence API negative and privacy review |
| Oversized result exfiltration | 65,536-byte MCP/common-tool result cap; bounded list limits | adapter unit tests |
| Remote exposure | SDK rejects non-loopback by default; Runtime bind validator loopback-only; HTTP MCP absent | settings/client negative tests |

## Accepted residual risks

- Data classification is an authenticated host/user assertion; MiLAi does not claim automatic PII
  detection. Misclassification remains a user/host policy risk.
- Local environment tokens are transitional bearer credentials, not remotely revocable principals.
- Multiple ordinary framework workers may share one orchestrator identity; the dedicated local
  reviewer is a separately derived Runtime actor, but no general per-Agent RLS or delegation is
  claimed.
- The project is not licensed for public package distribution and the Runtime/Schema remain
  candidate/experimental.

Any remote transport, multiple independent Agent principals, public distribution or automatic
candidate extraction requires a new security review and ADR.
