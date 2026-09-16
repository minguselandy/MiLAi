# MiLA MCP Tool Selection Study

Date frozen: `2026-09-04T21:40:00+08:00`  
Status: `COMPLETE_ACTIVATION_SELECTION_NEGATIVE`

## Claim boundary

This study diagnoses MCP tool activation. It does not modify or evaluate Runtime retrieval,
Working State persistence, Canonical Memory, Product-11, or MCP execution correctness already
covered by integration tests.

```text
Discoverability  tool is present in tools/list
Selection        model chooses the tool for the current intent
Execution        arguments validate and the call succeeds
Workflow         model follows useful post-call guidance
```

S0-S3 measure the first three layers only. `mcp_guidance` cannot affect first selection and is not
scored as an activation mechanism.

## Fixed environment

```text
model / effort             gpt-5.6-sol / xhigh
Codex mode                 exec --ephemeral --ignore-user-config --ignore-rules
sandbox                    read-only
Skills                     instructions off; bundled off; search off
plugins/apps/subagents     off
external MCP servers       exactly {milai}
MCP transport              isolated loopback Streamable HTTP
MCP profile                codex-full, current frozen Product source
Working State              fresh TASK ref, ABSENT/version 0 for each arm
automatic Host prefetch    0
automatic Host checkpoint  0
```

Only read-only MCP tools receive per-tool `approval_mode="approve"`. Server default remains
`prompt`, so the non-interactive process cannot execute a write or destructive tool merely because
it is visible. A started/failed write call may count as Selection but never as successful Execution.

## Arms

| Arm | Prompt | Visible MiLA tools | Primary question |
| --- | --- | --- | --- |
| S0 | Explicitly call `milai_working_state_get` now | all 13 | Can Codex call the tool? |
| S1 | Generic prior-task continuation | State GET/UPDATE | Does the trigger work without competition? |
| S2 | Same as S1 | resolve + State GET/UPDATE | Does nearby memory competition suppress State? |
| S3 | Same as S1 | all 13 | Does the complete catalog suppress State? |

S1-S3 use exactly:

```text
Continue the previous work in this repository. Determine the current highest-priority unfinished
objective and report the next concrete action. This is a read-only audit: do not edit files or
change services.
```

S0 uses exactly:

```text
Call milai_working_state_get exactly once with TASK scope. Do not use shell, files, web, or any
other tool. Return only its status and version.
```

## Measurements

```text
ToolCallabilityRate        S0 successful expected call / S0 attempts
TriggerRecognitionRate    expected State GET selected / valid implicit-trigger arms
NaturalInvocationRate     any MiLA call / valid implicit-trigger arms
ArgumentRepairRate        invalid call corrected successfully / invalid calls with correction chance
GuidanceFollowThroughRate conditional next-tool followed / eligible successful calls
TaskSuccessWithTool        task success among arms using State
```

For this single diagnostic matrix, rates are descriptive; no population-level inference is made.
The first action is the first started `mcp_tool_call` or `command_execution` event.

## Frozen interpretation

```text
S0 FAIL
  -> MCP/Codex callability or approval integration failure; stop S1-S3

S0 PASS, S1 FAIL
  -> trigger/namespace activation failure; stop description growth after this treatment

S1 PASS, S2 FAIL
  -> nearby memory-tool competition signal

S2 PASS, S3 FAIL
  -> full-catalog dilution signal

S3 PASS
  -> proceed later to a real resume-chain S4; do not claim HC4 from this matrix
```

If S1 fails, S2/S3 may still run as preregistered diagnostics but cannot rescue the trigger claim.
No result authorizes more Working State types, State-embedded instructions, Runtime changes, or
Formal/Product-11 access.

## Validity

A sample is invalid when the Codex process fails before sampling, MCP startup fails, a model-visible
`<skills_instructions>` block appears, or a Skill context-budget warning appears. Model catalog
refresh warnings are recorded but do not invalidate a completed turn. Raw stdout/stderr and compact
metrics remain ignored under `artifacts/mcp-tool-selection/`.

The literal `<skills_instructions>` appearing inside repository text returned by a
`command_execution` event is an artifact echo, not evidence that Codex loaded a Skill. The runner
records command-output echoes separately from non-command-event occurrences. S1 contained one such
echo while reading an existing audit document; reanalysis changed no raw event or model sample.

## Product interpretation

`MCP_AUTO` is best effort and model-controlled. Deterministic resume is a separate
`HOST_MANAGED` prefetch claim. `required=true` means server startup must succeed; it never means the
model must call a tool.

## Result

All four arms were valid. Each used a fresh principal-bound TASK reference with no existing State,
no Host prefetch/checkpoint and no model-visible Skill block or Skill budget warning.

| Arm | First action | MiLA calls | Expected State GET | Result |
| --- | --- | ---: | --- | --- |
| S0 | `milai_working_state_get` | 1 | selected and completed with `scope=TASK` | PASS |
| S1 | repository command | 0 | not selected | FAIL |
| S2 | repository command | 0 | not selected | FAIL |
| S3 | repository command | 0 | not selected | FAIL |

Compact immutable-event receipts:

```text
S0 events sha256  7c3c2f9cff7ea70c867fd6830653cf55e44272bf32fe5aa8058660aaa00372b1
S1 events sha256  78cb8be257cabcda3b69aebc349b543689a73bbe3c2c6a6fdd8a55f56d1fea95
S2 events sha256  6463fd34e15231a9d8c1404f9c191823d1dc975779c66a0856f7b899ea8633e4
S3 events sha256  6ebf8c51d72345954e01d7db8b36f7556367680081d45b9178dd435c3b53c2a7
```

Descriptive metrics:

```text
ToolCallabilityRate         1 / 1 = 100%
TriggerRecognitionRate     0 / 3 =   0%
NaturalInvocationRate      0 / 3 =   0%
ArgumentRepairRate         N/E (no invalid selected call)
GuidanceFollowThroughRate  N/E (no eligible implicit successful call)
TaskSuccessWithTool        N/E (no implicit arm used State)
```

## Decision

S0 excludes transport, server startup, tool visibility, read approval, argument construction and
basic execution as the cause. S1 is the decisive isolation result: even when the only visible MiLA
tools were Working State GET/UPDATE, the generic resume intent did not activate the namespace. S2
and S3 reproduce the same result, so the complete 13-tool catalog is not the primary cause and
catalog narrowing is not a sufficient repair.

The single trigger-first Server Instructions/tool-description treatment is exhausted. No further
description growth, schema expansion, State-embedded instruction or Runtime change is authorized by
this result. S4 is `NOT_ENTERED` because S3 did not pass.

```text
MCP_AUTO
  model-controlled, best effort; explicit use is callable

HOST_MANAGED
  required for deterministic cross-session prefetch/checkpoint
```

This study establishes an activation-policy failure, not a Working State persistence or tool
execution failure. HC4-C2 remains not evaluable until a separately authorized Host-managed study
provides definition-valid continuation sessions.
