# HC-4 A1R MCP-only replication

Date frozen: `2026-09-04T20:07:21+08:00`  
Execution started: `2026-09-04T20:12:00+08:00`  
Status: `A1R_PENDING_1_OF_4`

## Purpose

HC4-A1 observed zero natural Working State calls, but all four A1 processes also emitted a
skills-context-budget warning that was absent from A0. A1R removes that uncontrolled context
change. It is a replication of the already frozen A1 guidance, not a stronger prompt treatment and
not a Host-managed State experiment.

## Single changed condition

For every counted Codex process:

```text
--ignore-user-config
skills.include_instructions=false
skills.bundled.enabled=false
skill_search=false
plugins=false
apps=false
recommended_plugins=false
multi_agent=false
```

MiLAi is the only configured external MCP server. Native Codex filesystem/shell tools remain
available because the sampled work is genuine coding work. No Skill name, description, instruction
block, plugin, app or subagent is available to the model.

The following are held fixed:

```text
model / reasoning                    gpt-5.6-sol / xhigh
MCP profile                          codex-full
MCP catalog                          13 tools
A1 server instructions               unchanged
Working State GET/UPDATE descriptions unchanged
Runtime / schema / PostgreSQL         unchanged
automatic start GET / end UPDATE      0
task-prompt State guidance            0
```

The isolated HTTP MCP process uses server-owned TASK ref `hc4-a1r-mcp-only` and loopback endpoint
`http://127.0.0.1:17968/mcp`. Setup probes and explicitly requested MCP calls never count as natural
adoption.

## Preflight gates

Before a counted sample:

```text
model-visible <skills_instructions> block       absent
Exceeded skills context budget event            absent
configured external MCP servers                 exactly {milai}
explicit setup-only working_state_get            succeeds
MCP task state before natural samples            ABSENT / version 0
```

Failure of either of the first two gates invalidates the sample. Model-catalog refresh diagnostics
are recorded separately and do not validate or invalidate MCP visibility unless MCP startup fails.

## Sampling and interpretation

A1R uses fresh `codex exec --ephemeral` processes and natural non-trivial work. Prompts may specify
the real engineering objective and safety boundary but cannot mention HC-4, Working State, State
tools, fields or invocation timing.

```text
natural GET or UPDATE > 0
  -> adoption observed under MCP-only context; proceed to quality/usefulness adjudication

four valid sessions and natural GET/UPDATE == 0
  -> A1 guided adoption negative survives removal of the Skill confound

skill warning or Skill block appears
  -> sample invalid; repair isolation before continuing
```

A setup-only visibility question may test whether the model can verbally report MCP metadata, but
it is not an adoption sample. Explicitly naming a tool proves callability only and is also excluded.

## Safety and authority

The seven HC-4 hard safety counters remain required at zero. A1R authorizes no Product Runtime,
schema, Canonical, retrieval, migration, public-service or MCP behavior change. Schema remains
`0.1.x EXPERIMENTAL`; implementation remains `CANDIDATE`; schema freeze remains `NO-GO`.

## Setup and first-sample receipt

The zero-Skill isolation mechanism was tested before G1:

```text
skills.include_instructions=false                 PASS
skills.bundled.enabled=false                      PASS
model-visible <skills_instructions>               absent
skills-context-budget warning                     absent
MiLA MCP tools/list                               13
working_state_get server schema                   {scope=SESSION|TASK|PROJECT}
explicit exact-schema setup GET                   PASS / ABSENT / version 0
```

An earlier candidate using only `--ignore-user-config` plus
`skip_host_skill_discovery` was rejected before sampling because it still injected 384 Skill
entries and emitted the skills-budget warning. A first explicit callability probe also guessed the
invalid argument `state`; direct MCP `tools/list` proved that the server had correctly published
`scope`, and a second probe with the exact argument succeeded. Neither probe is an adoption event.

A setup-only verbal-visibility probe, with no tool invocation or repository read, reported the MCP
server instructions and tools as `NOT_VISIBLE` even though the server log independently recorded
the initialize/list/stream lifecycle. This result is diagnostic: it does not show transport failure,
and it does not count as natural adoption.

### A1R-G1

G1 was a fresh, read-only resume audit of the highest-priority authorized Product workstream. The
prompt named no State concept, MCP tool, field or invocation time. It correctly found Product-11
blocked at external dual-human X0 adjudication and made no Product or service change.

```text
events                                             32
command executions                                 26
file changes                                       0
skills-context-budget warning                      0
natural MCP tool calls                             0
natural Working State GET / UPDATE                 0 / 0
post-sample TASK State                             ABSENT / version 0
events JSONL SHA-256                               79678c1a3af34b565f5cd9f9611cd45823b764e3857456047a2786b25192cdfd
```

Raw evidence remains ignored under
`artifacts/hc4-host-cognitive-a1r-mcp-only/a1r-g1/`. The isolated loopback MCP process was stopped
after post-sample verification; the public 7968 service and its server-owned `milai-product` TASK
binding were never changed.

One valid zero-Skill sample with zero natural calls is insufficient for either positive or negative
A1R terminal. Product-11 supplied no genuine next coding phase because the audit confirmed that
repository-side behavior work is forbidden before two real human submissions. G2-G4 therefore
remain pending rather than being manufactured from the same external blocker.
