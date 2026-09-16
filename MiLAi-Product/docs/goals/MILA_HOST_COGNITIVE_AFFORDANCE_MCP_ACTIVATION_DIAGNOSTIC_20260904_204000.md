---
document_id: MILA-HOST-COGNITIVE-AFFORDANCE-MCP-ACTIVATION-DIAGNOSTIC
version: "0.1"
status: COMPLETE_MCP_NATIVE_ACTIVATION_INSUFFICIENT
executed_at: "2026-09-04T20:07:21+08:00/2026-09-04T20:40:00+08:00"
schema_status: EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
---

# MCP-native cognitive activation diagnostic

## Outcome

The user-authorized post-terminal diagnostic removed Skills from the sampled Codex context and
tested both the complete 13-tool catalog and a State-only two-tool client allowlist. Neither arm
produced a natural MiLA call for the same resume-style Product audit.

```text
zero-Skill A1R-G1, old A1 metadata, 13 tools             0 calls
A2-M1, strengthened MCP metadata, 13 tools               0 calls
A2-M2, same metadata, only GET/UPDATE visible             0 calls
```

All counted samples completed their repository audit through native shell/filesystem tools. The
MCP transport initialized, explicit setup GETs succeeded, sampled TASK States were
`ABSENT/version 0`, and no skills-context-budget warning occurred.

Therefore:

```text
Skill context was a confound in the earlier A1 run       removed
13-tool catalog dilution as sufficient explanation       rejected
MCP metadata alone guarantees initial State selection    rejected
```

Catalog size may still affect selection after the model has chosen the MiLA namespace, but the
observed failure precedes that stage.

## Matched evidence

| Sample | Visible tools | Metadata | First action | Natural State calls | JSONL SHA-256 |
| --- | ---: | --- | --- | ---: | --- |
| A1R-G1 | 13 | frozen A1 | repository command | 0 | `79678c1a3af34b565f5cd9f9611cd45823b764e3857456047a2786b25192cdfd` |
| A2-M1 | 13 | strengthened namespace + descriptions | repository command | 0 | `5c2d721949164585ba619489efdf0f97544390af6a975dbea153c7c35551c2e6` |
| A2-M2 | 2 | identical A2 treatment | repository command | 0 | `430654a10752727352a1e707316a18a0daad130e844cf671a46bdee34e48e7e9` |

Raw process evidence is retained in MiLAi-Lab under:

```text
artifacts/hc4-host-cognitive-a1r-mcp-only/a1r-g1/
artifacts/hc4-host-cognitive-a2-mcp-native/a2-m1/
artifacts/hc4-host-cognitive-a2-mcp-native/a2-m2/
```

## Product repair

The MCP facade now publishes the working-state policy at three distinct trust layers:

1. a self-contained first-512-character `InitializeResult.instructions` cue;
2. independently actionable GET and UPDATE tool descriptions;
3. additive `mcp_usage_contract` metadata on every GET result, including `ABSENT`.

The third layer is server-authored and is never persisted inside the Host-authored State payload.
This prevents stale or injected State text from becoming tool policy. It teaches correct subsequent
use after GET has occurred, but cannot bootstrap the first GET.

Guaranteed initial State access therefore requires a Host-owned session-start prefetch. This mode
uses the MCP GET operation and can run with Skills disabled, but its result must be classified as
`HOST_MANAGED`; it is not evidence of natural Codex self-maintained cognition.

## Verification and deployment

```text
MCP Ruff                                      PASS
MCP strict mypy                              PASS (11 source files)
MCP pytest                                   PASS (105 tests)
MCP wheel + sdist                            PASS (0.1.3)
public codex-full service                    restarted / active
public /readyz                               HTTP 200
public explicit TASK GET                     PASS
public mcp_usage_contract authority          SERVER_AUTHORED_USAGE_CONTRACT
public initial_activation declaration        HOST_PREFETCH_REQUIRED_IF_GUARANTEED
```

No Runtime schema, migration, State type, Canonical authority, input schema or tool catalog was
added. The GET output change is additive MCP metadata only.

## Terminal

```text
MCP-native optional affordance                available
MCP-native natural activation                 not demonstrated
post-selection correct-use contract           available
guaranteed first-use mode                     requires separate Host-managed integration
HC4-C2 usefulness                             NOT_EVALUABLE
```

The Product remains `PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE`; Schema remains `0.1.x
EXPERIMENTAL`, implementation remains `CANDIDATE`, and schema freeze remains `NO-GO`.
