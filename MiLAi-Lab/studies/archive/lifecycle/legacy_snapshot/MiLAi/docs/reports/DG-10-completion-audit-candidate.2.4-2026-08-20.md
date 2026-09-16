# DG-10 Completion Audit — candidate.2.4

Status: `GOAL IN_PROGRESS / PV-LOCAL AUTHOR CANDIDATE COMPLETE / EXTERNAL PROVIDER LANE NOT EXECUTED`  
Date: `2026-08-20` (Asia/Shanghai)  
User boundary: use the existing vLLM only; do not call an external model API and do not change the
vLLM startup.  
Data boundary: `SYNTHETIC / DEIDENTIFIED ONLY`

## Decision

The complete DG-10 Definition of Done is **not achieved**. The user-selected PV-LOCAL lane has
completed its author gates through `PVL-04`, but the original Goal explicitly requires an approved
external billing Provider, native receipt/invoice reconciliation, and independent review. Those
requirements cannot be relabeled as local vLLM evidence. `PVL-05`, `OE-F06`, `AIG-01`, Provider/Beta
and Production therefore remain open/no-go.

## Definition-of-Done audit

| # | Current verdict | Authoritative current evidence or missing fact |
| --- | --- | --- |
| 1 | `NOT MET` | The user approved existing vLLM-only execution, not an external Provider/model, spend ceiling, egress, Host and time window. |
| 2 | `NOT MET` | No external Provider adapter/dependency/Host execution approval closure was created or used. The local adapter is bound only to the existing self-hosted vLLM. |
| 3 | `NOT MET / LOCAL ANALOG MET` | Candidate.2 has an exact uninterrupted 1,000-call local A/B with 1,000 unique native IDs; no external charge-bearing Provider capture exists. |
| 4 | `NOT MET / LOCAL ANALOG MET` | Local vLLM tokenizer pre-count equals native usage for every call; external Provider usage/cached-input counters are absent. |
| 5 | `NOT MET` | A self-hosted vLLM request ID is not an upstream billing receipt; no request-ID-to-invoice mapping exists. |
| 6 | `NOT MET` | External actual cost and ≤1% billing reconciliation cannot be proven because no external request or bill exists. |
| 7 | `MET FOR PV-LOCAL` | 500 baseline and 500 optimized calls include token, model-round, wall-time, quality and safety aggregates. |
| 8 | `NOT MET / LOCAL CONCLUSIONS PRESENT` | Candidate.2 gives local OG-01/03/04/05/08/09 observations; the Goal requires real-Provider conclusions. Reader-lite is exactly 250 target-model tokens. |
| 9 | `MET LOCAL CANDIDATE` | Rebuilt client/MCP wheel and sdist clean-install offline; package gate candidate.2 is complete. |
| 10 | `MET LOCAL CANDIDATE` | All four archives and the 34-entry musl wheelhouse passed member, secret and offline installation checks. |
| 11 | `MET LOCAL CANDIDATE` | Both MCP protocols and independent wire Host expose exactly `milai_recall`; forbidden tools remain absent. |
| 12 | `MET LOCAL CANDIDATE` | Reader-lite exposes query only. Scope, authority, consistency, profile, limit and token remain Host-owned; policy arguments are rejected before Runtime access. |
| 13 | `MET LOCAL CANDIDATE` | OpenWorker base/derived image, OpenCode, Python, uv, relay, broker, config and wheelhouse identities are digest-bound. |
| 14 | `PARTIAL` | OpenWorker upstream redistribution authorization remains unavailable; the derived image stayed local and was not distributed. |
| 15 | `MET LOCAL CANDIDATE` | Host restart/recreate and E2E restart preserve exact config bytes/semantics, MCP template, Host policy and tool catalog after equal discovery phases. |
| 16 | `MET LOCAL CANDIDATE` | Worker env/config/debug/proc/bash/Skill/log/crash probes found no MiLAi token or Runtime DSN. |
| 17 | `MET LOCAL CANDIDATE` | Worker has one read-only reader-lite socket mount, an internal network without gateway, and no host network, privilege, Docker socket or direct Runtime/PostgreSQL route. |
| 18 | `NOT MET / LOCAL ANALOG MET` | PV-LOCAL OpenWorker Agent completed S1-S10 with 12 vLLM calls; no external Provider Agent was authorized. |
| 19 | `MET FOR PV-LOCAL` | OpenIssue, trace, abstention, degraded, revocation, stale projection and same-session reuse scenarios passed. |
| 20 | `PARTIAL` | Local canonical-down and broker/socket/adapter failure paths fail closed; external Provider outage behavior was not executed. |
| 21 | `MET LOCAL CANDIDATE` | Reports retain normalized/hash evidence only; secret/archive scans pass and external requests/cost are zero. |
| 22 | `PARTIAL` | Local disable, socket unmount/remount, broker stop/recovery, restart/recreate and base-image rollback passed. External credential revoke and partial-cost reconciliation are inapplicable/unexecuted. |
| 23 | `NOT MET` | No fresh independent reviewer decision exists; `PVL-05` and `OE-F06` remain open. |
| 24 | `MET` | Runtime remains `0.1.x CANDIDATE`; Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR FREEZE`. |
| 25 | `MET` | No claim of Remote MCP, real personal data, Production or Schema freeze is made. |

## Primary evidence bindings

- vLLM identity: `0463fff90754f54c887ed79e54b5db5593b1860cf593c4a89a66c1828eaa3f0e`;
- candidate.2 exact A/B: `976f2043768dd5085df4f0e4a734b692c16805bb9ccfb34e6873e6d5099fc7df`;
- candidate.2.4 Agent E2E: `074de379177514b17a05dfde525c7861940f51e6a322e6df9d49a331d0305144`;
- candidate.2 package gate: `1047c85f8fbcaf60517d774b658a331ea65aaf00aa17e6818425dc57e0e13b37`;
- candidate.2 Host gate: `97ea8bdf7c8ccadc29918a95483a236b62372bf13ef882b4ef8ca0cc1ac722d0`;
- candidate.2 wheelhouse manifest: `9a969faa0ef7135d2484e4e5e4987a015ef99a007bf2a3ccbdb979ccc4d3e2c5`;
- package release manifest: `7e3ac6f942c133bfdb32040d24f6464aa3c52acfb8915f170bf48777c536fd5a`.

The final byte inventory is generated after all report/document updates and is intentionally bound
outside this recursively inventoried document.

## Highest permitted statement

```text
MiLAi has completed one exact self-hosted vLLM same-model local author candidate and
credential-isolated local stdio MCP/OpenWorker validation for synthetic/de-identified workloads;
independent PV-LOCAL review and external-provider billing validation OE-F06 remain open.
```
