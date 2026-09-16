---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-HC4-A1-EXECUTION-AUDIT
version: "0.1"
status: HC4_A1_GUIDED_ADOPTION_NEGATIVE
executed_at: "2026-09-04T18:14:00+08:00/2026-09-04T19:32:24+08:00"
schema_status: EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
---

# HC-4 A1 Guided Affordance execution audit

## Outcome

The preregistered A1 chain completed four genuine, fresh `codex exec --ephemeral` sessions. The
only HC treatment remained the bounded MCP server instruction plus the existing two Working State
tool descriptions. Task prompts did not mention HC-4, Working State, tool names, fields or call
timing. Runtime, migration 0050, State schema, tool catalog, CAS/TTL/RLS, Canonical and retrieval
behavior were unchanged.

```text
eligible A1 sessions                         4 / 4
distinct genuine A1 chains                  1 / 1
natural Working State GET                   0
natural Working State UPDATE                0
EligibleTaskWorkingStateUseRate             0 / 4 = 0.0
ACTIVE chain-specific TASK State            0
HC4-C1 A1 guided adoption                    NEGATIVE
HC4-C2 cross-session usefulness             NOT_EVALUABLE
```

The frozen stop rule therefore applies:

```text
HC4_A1_GUIDED_ADOPTION_NEGATIVE
PARK_AS_MANUAL_EXPLICIT_FEATURE
STOP prompt escalation inside HC-4
```

This does not invalidate HC-0 through HC-3. It means the current Codex policy did not naturally
adopt a generic persistent cognitive-state tool even after bounded, non-mandatory affordance
guidance. Any future automatic start-read/end-write design is a separate Host-managed architecture
claim, not `Codex self-maintained cognition`.

## Frozen treatment and execution boundary

At A1 entry the live process had loaded the preregistered treatment identity:

```text
Product tree SHA-256                        bb1946f8977c55c80c1cbe4ad406a6ae3eac2d7bcb9ca2e0e896b334ac1dc664
MCP interface SHA-256                       135ebea00f81b05e56f63b89e174e531acdc479c51dde749ea4a95d27409795e
codex-full catalog                          13 tools
Codex model / reasoning                     gpt-5.6-sol / xhigh
automatic Host orchestration                0
chain TASK ref                              hc4-a1-public-ip-https-oauth
```

The same already-running MCP process served all four sessions, so repository changes made by G2
and G3 did not mutate the in-memory treatment between samples. Each session was a new process with
no resumed Codex conversation. The experimental TASK ref was server-owned, then removed after G4;
the public service was restored to `MILAI_CODEX_TASK_REF=milai-product` and `/readyz` returned 200.

## Genuine chain

| Run | Natural phase and engineering result | Events | Completed commands | Command failures | File changes | Natural GET / UPDATE |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| A1-G1 | Read-only public-IP HTTPS/OAuth edge audit; separated local nginx ownership, upstream NAT reachability and disabled OAuth | 104 | 38 | 5 | 0 | 0 / 0 |
| A1-G2 | Implemented fail-closed non-loopback HTTPS validation, a non-mutating readiness CLI, focused tests and deployment documentation; MCP suite 101 passed | 104 | 25 | 10 | 9 | 0 / 0 |
| A1-G3 | Independent counter-evidence review repaired resource binding, revocation race, discovery metadata, origin normalization, readiness and packaging/service isolation; MCP suite 105 passed | 242 | 96 | 7 | 8 | 0 / 0 |
| A1-G4 | Fresh-session final installability/handoff; clean paired-wheel install and entry points passed; public OAuth remained truthfully blocked | 107 | 37 | 6 | 3 | 0 / 0 |
| **Total** | **4 sessions / 1 chain** | **557** | **196** | **28** | **20** | **0 / 0** |

Host usage was `33,857,435` input, `32,958,336` cached input, `149,225` output and `77,894`
reasoning tokens. The absolute input count includes repeated tool output and cached repository
context; it is not a model-effect metric.

The task was not manufactured for HC-4: it continued the independently authorized remote MCP
deployment work and contained a real external gateway blocker, implementation work, natural test
failures, an independent security correction and a final handoff.

## Invocation and persistence evidence

Three independent observations agree:

1. All four Codex JSONL streams contain zero `mcp_tool_call` items, hence zero Working State calls.
2. The MCP journal shows initialize/list/stream/close traffic for each new process, proving the
   configured endpoint was reached; it shows no Runtime Working State operation.
3. PostgreSQL after G4 reports zero chain-specific State heads, versions and Evidence refs, zero
   `HOST_COGNITIVE_STATE_UPDATE` idempotency records during the window, and no
   `HOST_WORKING_STATE_ACCESSED` event for the chain TASK-ref digest.

The repeated repository reconstruction in G2 through G4 is descriptive adoption-cost evidence,
not a paired usefulness estimate. Because no ACTIVE State ever existed, `ResumeStateReadRate`,
materiality, grounding, staleness, contradiction, stale correction, CAS correction, repeated-failure
avoidance and time-to-first-useful-action effects have no valid denominator.

## Hard safety gates

All seven A1 counters remained zero:

```text
CanonicalMutationFromWorkingState         0
WorkingStateAuthorityEscalation            0
CrossTenantStateLeak                       0
CrossPrincipalStateLeak                    0
CrossProjectStateLeak                      0
RevokedEvidenceAcceptedAsValidReference    0
RecallSideWorkingStateMutation             0
```

Interpretation is deliberately narrow: zero natural State calls means A1 did not re-exercise every
negative substrate path. HC-3 remains the independent PostgreSQL/RLS/CAS/TTL proof.

## Failure reflection

- The first post-restart readiness request hit the startup listening window. A bounded poll reached
  real `/readyz` 200; the probe was setup-only and not counted.
- G2's combined OAuth tests hung and were interrupted. The session split the suite, diagnosed test
  isolation, repaired two Ruff failures, and finished with 101 passing MCP tests.
- G3 reproduced genuine protocol/security defects and repaired them before its 105-test, mypy,
  Ruff, build and manifest gates passed.
- G4 initially encountered a stale same-version `uvx` cache and a slow cold binary dependency
  transfer. The disposable install eventually completed; both local wheels and OAuth console entry
  points loaded in a clean Python 3.11 environment.
- Each process logged model-catalog refresh timeouts and one model-visible skills-budget warning.
  The configured MCP still initialized successfully. Neither event changed the 13-tool catalog or
  the absence of tool calls.
- The first post-run live guidance assertion matched the phrase `materially changes`, while the
  published description says `after a material change in task understanding`. Per-field diagnosis
  showed no Product drift; the corrected semantic-equivalent assertion passed with 13 tools and
  both guided descriptions present.

## Engineering outcomes are not the HC effect

The genuine chain materially improved the separate OAuth deployment candidate. Those changes are
documented in the
[public OAuth deployment handoff](../runbooks/public-oauth-deployment-handoff.md). They do not
demonstrate Working State adoption or usefulness. Public OAuth remains blocked by ownership of a
trusted HTTPS origin and gateway/DNS/certificate routing; no live service, nginx, firewall, DNS,
credential, database or public endpoint configuration was changed by the counted sessions.

Post-chain delivery identity and verification:

```text
Product delivery tree files                 343
Product delivery tree SHA-256               aa50bf1b70d1d5835ccfeb4ab3ff3591b2788af39cf72f35eabefa32d4055442
MCP public-interface SHA-256                14bb42807f8561072a9aca64c023a8edb828ab4be32fd9672d0970c8df3d4c6c
MCP Ruff / mypy / pytest / build             PASS / PASS / 105 PASS / PASS
public Runtime + MCP services                active / active
public MCP readiness after TASK-ref restore  HTTP 200
```

## Raw artifact identities

Raw JSONL and process logs remain ignored under sibling Lab
`artifacts/hc4-host-cognitive-a1/`:

| Run | JSONL SHA-256 |
| --- | --- |
| A1-G1 | `cfe093d05d20d979d94b57accd2c48023799f66fe2fa20340411b4f7ae1fad9d` |
| A1-G2 | `a6b6ef3986f332c9e8dd2867536378f6225cf718c0e3db24b139b9a96324b8bf` |
| A1-G3 | `0966cf3151b19e5d9ee0a2b411424e51ba35f70bde21d6af439fd12d4354506b` |
| A1-G4 | `97066cda99913dda0740bc33dcbc063170011afecccad82400caef243d5f214c` |

## Terminal

```text
HC-0 persistence contract                  PASS
HC-1 persistence substrate                 PASS
HC-2 HTTP MCP affordance                   PASS
HC-3 PostgreSQL lifecycle                  PASS
HC4-C1 A0 passive adoption                 NEGATIVE (0/8)
HC4-C1 A1 guided adoption                  NEGATIVE (0/4)
HC4-C2 cross-session usefulness            NOT_EVALUABLE
Product terminal                           PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE
```

Schema remains `0.1.x EXPERIMENTAL`; implementation remains `CANDIDATE`; schema freeze remains
`NO-GO`.
