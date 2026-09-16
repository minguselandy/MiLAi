---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-GOAL
version: "0.5"
status: PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE
created_at: "2026-09-04"
schema_status: EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
---

# MiLAi Host Cognitive Affordance Goal

## Outcome

HC-0 through HC-3 are implemented as a local candidate. HC4-C1's A0 passive-affordance baseline is
sealed `HC4_A0_PASSIVE_ADOPTION_NEGATIVE` after 8 tasks / 2 chains and 0/8 natural Working State
use. The preregistered A1 bounded-guidance chain then completed 4 more fresh sessions with 0/4
natural use and ended `HC4_A1_GUIDED_ADOPTION_NEGATIVE`. HC4-C2 usefulness is not evaluable;
`PASS_HOST_COGNITIVE_AFFORDANCE_CODEX_USABLE` is not claimed.

## Phase status

| Phase | Status | Evidence |
| --- | --- | --- |
| HC-0 Contract Freeze | COMPLETE | ADR-034 and Host Cognitive State contract |
| HC-1 Persistence Substrate | COMPLETE | migration 0050, domain/service/repository, real PostgreSQL test |
| HC-2 HTTP MCP Tools | COMPLETE | two `codex-full` tools, Python client, HTTP child-process test |
| HC-3 Codex Instructions | COMPLETE | short MCP instructions and runbook usage protocol |
| HC-4 Real Coding Usability | A0_NEGATIVE / A1_NEGATIVE | A0: 8 tasks / 2 chains / 0 calls; A1: 4 tasks / 1 chain / 0 calls; C2 not evaluable |

## Frozen non-claims

```text
HOST_WORKING != Canonical
HOST_WORKING != Evidence
HOST_WORKING != RetrievalContinuationState
working state does not assert sufficiency or COMPLETE
working state never auto-promotes into a Claim
```

## HC-4 adoption then usefulness

HC-0～HC-3 remain frozen. A0 proved that passive capability visibility did not produce natural
adoption. A1 changed only server instructions and the existing two descriptions to explain useful
resume/material-change triggers without requiring a call. It completed one genuine four-session
public-IP HTTPS/OAuth deployment-readiness chain:

```text
G1 initial task
G2 fresh-session resume
G3 real decision/failure/blocker/phase change
G4 fresh-session resume and completion
```

Task prompts did not mention HC-4, State, tool names, fields or invocation timing. All four valid A1
sessions made zero natural calls, so the frozen rule stops prompt escalation and parks the
self-maintained route as a manual/explicit feature. No ACTIVE State existed; HC4-C2 did not enter.
Host-managed prefetch/update, if pursued, requires a separate Goal and cannot claim Codex
self-maintained cognition.

- [HC-4 experiment plan](MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXPERIMENT_PLAN.md)
- [HC-4 execution tracker](MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXPERIMENT_TRACKER.md)
- [HC-4 execution audit](MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXECUTION_AUDIT_20260904_134043.md)
- [HC-4 A1 execution audit](MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1_EXECUTION_AUDIT_20260904_193542.md)

## Current terminal status

```text
PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE
```

The current self-maintained route is parked. Promotion to
`PASS_HOST_COGNITIVE_AFFORDANCE_CODEX_USABLE` is not available from more prompt escalation. A future
Host-managed design must be preregistered as a different architecture claim and must independently
meet the C2 minimum sample, restart/CAS/stale-correction and safety gates.
Product-11 remains an independent deterministic retrieval goal.

A later user-authorized, zero-Skill MCP diagnostic did not reopen this terminal: strengthened MCP
metadata produced zero calls with both 13 visible tools and a two-tool State-only allowlist. The
facade now returns a server-authored `mcp_usage_contract` separately from untrusted State payload,
which improves correct use after selection but does not claim initial activation. See the
[MCP activation diagnostic](MILA_HOST_COGNITIVE_AFFORDANCE_MCP_ACTIVATION_DIAGNOSTIC_20260904_204000.md).

Implementation and verification details are recorded in the
[2026-09-04 completion audit](MILA_HOST_COGNITIVE_AFFORDANCE_COMPLETION_AUDIT_20260904_105341.md).
