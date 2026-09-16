# DG-13U U1 owner decision proposal v1

Status: `PROPOSED / OWNER ACCEPTANCE REQUIRED`  
Goal: `DG13-U1 = LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE`  
Data boundary: `SYNTHETIC OR INDEPENDENTLY DE-IDENTIFIED`  
Formal evaluation: prohibited

This document makes the nine decisions required by
`MiLAi_DG-13_MemoryAccessPlan与渐进检索_GOALS.md` section 9.2 reviewable as one bounded set. It is not
an acceptance receipt. Until the owner explicitly accepts this exact version or a replacement, no
behavior-changing U1 patch is authorized.

## Proposed decisions

1. **ADR-024 disposition** — Accept Host-controlled memory before provider execution and the
   orthogonal Requirement/availability/action semantics for the DG13U U1 MCP-only slice. This does
   not activate Direct/HTTP, portable lease, push invalidation, offline snapshot, U2/U3/U4, or edit
   `architecture/v1.0/`. Any broader vNext promotion still follows ADR-024 architecture change
   control.
2. **Release label** — The only successful label is
   `LOCAL_OPENWORKER_MCP_CURRENT_STATE_USABLE`. It is local, reader-only, STRICT_CURRENT, and limited
   to synthetic or independently de-identified data. It is not Production, Beta, remote-ready,
   formal-benchmark evidence, or general retrieval.
3. **Three representative StateKey families** — Freeze one synthetic release fixture with these
   exact families:

   | Family | StateKey | English intent | Chinese intent |
   | --- | --- | --- | --- |
   | current project state | `orchid-release / release.target / PROJECT_STATE` | current release target | 当前发布目标 |
   | current project config | `orchid-release / release.database / PROJECT_CONFIG` | current release database/config | 当前发布数据库/配置 |
   | governed project decision | `orchid-release / release.decision / PROJECT_DECISION` | current governed release decision | 当前受治理的发布决定 |

   The exact accepted aliases are:

   | StateKey | Exact aliases |
   | --- | --- |
   | `orchid-release / release.target / PROJECT_STATE` | `current release target`; `当前发布目标` |
   | `orchid-release / release.database / PROJECT_CONFIG` | `current release database`; `current release config`; `当前发布数据库`; `当前发布配置` |
   | `orchid-release / release.decision / PROJECT_DECISION` | `current governed release decision`; `当前受治理的发布决定` |

   The U0 fixture manifest must bind this same list byte-for-byte. Collision between two live aliases
   is a typed ambiguity and must not be resolved by lexical tie-breaking. The Cedar/other-scope twin
   is a negative fixture, not another family. The machine-readable byte freeze is
   `contracts/agent/v1/dg13u-u1-candidate-fixture.json` at SHA-256
   `47175b17cdc8444955d28cf3ec2f6d96964faf2099decf34bd317cf7729bb555`.
4. **Strict failure actions** — Preserve the memory status independently from the action:

   | Memory status | Execution action | Provider |
   | --- | --- | --- |
   | `NO_MEMORY_NEEDED` | `CONTINUE` | `ALLOWED` |
   | `CONTEXT_READY_CURRENT` | `CONTINUE` | `ALLOWED` |
   | `MEMORY_REQUIRED_BUT_UNAVAILABLE` | `RETRY` | `PROHIBITED` |
   | `MEMORY_INSUFFICIENT` | `ASK_USER` | `PROHIBITED` |
   | `GOVERNANCE_BLOCKED` | `ABSTAIN` | `PROHIBITED` |

   The original typed reason remains present. The middleware never executes a memory-dependent
   provider answer for the last three rows and never converts them to Need `NONE`.
5. **Task continuity** — U1 continuity is limited to one live adapter process. Adapter restart drops
   registry, slot, retained Context, and any pending operation identity. No durable, portable, or
   cross-session reuse claim is made.
6. **Read authority and provider ingress** — The OpenWorker's only MiLA memory authority is the
   `reader-lite` profile-scoped MCP UDS socket. It receives no MiLA token, Runtime URL, DSN, secret
   directory, write/review/revoke capability, provider capability, or direct Runtime/vLLM route. It
   additionally receives one run-owned Host provider HTTP origin and a random ingress Bearer token.
   That token authenticates only the OpenWorker-to-Host HTTP boundary; it is not a MiLA read token or
   an upstream provider capability. The Host binds only to the run-owned Docker bridge gateway and a
   random port, compares the token in constant time, and accepts no request from another network.
7. **First memory transport** — MCP over the existing profile-scoped UDS broker is the only U1
   memory transport. Direct and HTTP *memory* transports are not implemented or silently selected
   as fallback. The separate OpenWorker-to-Host provider HTTP origin in decision 6 is required by the
   product chain and does not grant memory authority.
8. **Provider request subset** — U1 accepts an OpenAI-compatible chat request containing only:

   ```text
   model, messages, stream, stream_options,
   tools, tool_choice,
   temperature, top_p, max_tokens, seed, response_format
   ```

   The U1 OpenWorker config declares the single exact model
   `Qwen3.6-35B-A3B-FP8`; `AUTO`, unknown models, and implicit gateway model routing are rejected.
   `stream` is forwarded unchanged. For `stream=true`, `stream_options` is required to be exactly
   `{ "include_usage": true }`, and Host streams the upstream SSE without buffered reconstruction;
   for `stream=false`, `stream_options` must be absent and Host returns one JSON completion.

   `messages` preserves declared `system`, `user`, `assistant`, and synchronous `tool` roles and
   content/tool-call identifiers. Memory Context is injected without reconstructing the rest of the
   accepted request. Fields absent from the request remain absent unless vLLM requires a documented
   product default. Any other top-level provider field is rejected before provider I/O with
   `PROVIDER_REQUEST_UNSUPPORTED`; it is not ignored or guessed. The U0 live request-key inventory
   must prove that real OpenWorker can operate within this subset or this decision must be revised.
   Historical-gateway account, billing, rate-limit, AUTO-routing, and authorization-remapping
   semantics are explicitly out of scope. Host replaces the relevant local safeguards with ingress
   isolation/authentication, exact-model validation, bounded body/deadline limits, stable typed
   errors, and its existing one-attempt provider capability.
9. **Task producer and delayed results** — The OpenWorker Host integration, outside model-visible
   content, produces `task_id`, task generation, relation, scope/profile binding, and synchronous
   operation identity from the real OpenWorker session lifecycle. Model text, retrieval, and test-only
   private payload injection cannot produce these identities. Asynchronous/delayed tool-result
   rebinding is explicitly `UNSUPPORTED_IN_U1`; synchronous ordinary tool calls/results remain in the
   provider subset and must pass through unchanged. The first wire design is
   `contracts/agent/v1/openworker-task-metadata-headers.md` at SHA-256
   `b36feaff924cc10275040a458f17449907621b4ecadf5af2f92771784db60c4f`: OpenWorker emits only
   its native process, session, and synchronous operation identities through `chat.headers`; the
   Host derives relation and same-process generation while scope/profile/authority remain owned by
   the mounted capability.
   For this local U1 slice, `OPENWORKER_URL` points directly to the run-owned Host adapter `/v1`
   endpoint. The historical gateway is excluded because exact image inspection proves that it drops
   custom request headers; changing that external gateway or moving metadata into the body is not an
   implicit fallback. Host validation order is ingress Bearer authentication, exact single-value
   metadata-header validation, bounded body parsing, typed provider-semantics validation, hidden MCP
   if required, and provider execution if allowed. Reachability or possession of the ingress token
   does not let Worker-selected text, body fields, or headers choose scope/profile/authority.

## Acceptance receipt requirements

An acceptance must identify:

```text
document path
document SHA-256
decision: ACCEPT | REVISE
owner identity
accepted_at
```

`REVISE` must name the numbered decisions being replaced. Reviewer output, implementation status,
tests, or a later green E2E cannot substitute for this owner receipt.
