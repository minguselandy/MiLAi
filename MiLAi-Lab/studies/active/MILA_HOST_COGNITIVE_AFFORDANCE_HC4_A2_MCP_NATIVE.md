# HC-4 A2 MCP-native activation probe

Date frozen: `2026-09-04T20:24:02+08:00`  
Status: `COMPLETE_MCP_METADATA_AND_CATALOG_REDUCTION_INSUFFICIENT`

## Question

Can a self-contained MCP namespace cue plus independently actionable tool descriptions activate a
Working State read in a zero-Skill Codex session?

This is a mechanistic prompt-delivery probe, not a cross-session usefulness result and not a
replacement for the four-session A1R minimum.

## Matched comparison

Control is A1R-G1: zero Skills, old A1 MCP metadata, TASK State `ABSENT/version 0`, and zero natural
MCP calls. Treatment repeats the exact G1 task prompt, model, reasoning, repository, TASK ref and
zero-Skill CLI configuration. Only these model-visible MCP metadata strings change:

```text
codex-full InitializeResult.instructions
milai_working_state_get description
milai_working_state_update description
```

Tool names, catalog count, schemas, Runtime, database, State contents and automatic orchestration
remain unchanged. The new first 512 characters contain both State tool names, the resume and
material-update triggers, exact TASK argument, non-canonical authority and untrusted-data rule.

## Primary observation

```text
natural milai_working_state_get before first repository command
```

Secondary observations are any later natural GET/UPDATE, argument validity, the absence of a Skill
instruction block/warning, and whether `ABSENT` is handled without blocking normal work.

An explicitly named tool call is excluded. A natural GET after repository archaeology is adoption
but does not satisfy the ordering claim. Any Skill warning invalidates the probe.

## Interpretation

```text
GET before first command
  -> OBSERVED_MCP_NATIVE_RESUME_ACTIVATION (single mechanistic probe only)

GET only after commands
  -> OBSERVED_LATE_MCP_ACTIVATION

zero natural State calls
  -> MCP_METADATA_PROMPT_INSUFFICIENT
```

No outcome authorizes automatic Host orchestration or a Host Cognitive usefulness claim.

## A2-M1 result — full 13-tool catalog

The matched treatment completed under the frozen zero-Skill configuration. Codex performed the
requested audit correctly, but its first action was a repository command and it never selected an
MCP tool.

```text
events                                             35
command executions                                 28 (14 started + 14 completed)
natural MCP tool calls                              0
natural Working State GET / UPDATE                  0 / 0
skills-context-budget warning                       0
stderr                                              empty
events JSONL SHA-256                                5c2d721949164585ba619489efdf0f97544390af6a975dbea153c7c35551c2e6
```

Interpretation: `MCP_METADATA_PROMPT_INSUFFICIENT` for the 13-tool catalog. Strengthening only the
MCP namespace instructions and the two State-tool descriptions did not activate a State read.
This is not a transport or task-completion failure and it does not yet isolate catalog dilution.

Raw evidence is retained under
`artifacts/hc4-host-cognitive-a2-mcp-native/a2-m1/`.

## A2-M2 preregistration — two-tool catalog dilution diagnostic

Date frozen: `2026-09-04T20:35:00+08:00`

A2-M2 repeats the exact A2-M1 task prompt and holds fixed the model, reasoning effort, zero-Skill
flags, Product repository, MCP source code, MCP metadata treatment and automatic orchestration at
zero. It uses a fresh server-owned TASK ref with `ABSENT/version 0` State. The sole model-visible
change is the Codex MCP client allowlist:

```toml
enabled_tools = ["milai_working_state_get", "milai_working_state_update"]
```

The server may continue to register its 13-tool `codex-full` profile; only the two State tools are
presented to the sampled model. No task prompt may mention MiLA, MCP, Working State, tool names,
State fields or invocation timing.

Primary observation remains:

```text
natural milai_working_state_get before first repository command
```

Interpretation is frozen before execution:

```text
A2-M2 primary observed while A2-M1 was zero
  -> evidence consistent with full-catalog tool-selection dilution

A2-M2 has a late State call while A2-M1 was zero
  -> weak evidence consistent with catalog dilution; ordering claim still fails

A2-M2 has zero State calls
  -> reducing 13 tools to 2 is insufficient; catalog size is not an adequate explanation
```

This is one matched mechanistic diagnostic, not a usability PASS and not authorization to split the
public endpoint or add State types. A positive result would justify a future minimal cognitive
profile experiment; a negative result would stop catalog-size tuning as the primary repair.

## A2-M2 result — State-only client allowlist

The two-tool arm completed with a fresh server-owned TASK binding. An explicit setup call proved
that the server registered 13 tools and the new task State was `ABSENT/version 0`; the counted
Codex process was presented only `milai_working_state_get` and
`milai_working_state_update` through `enabled_tools`.

```text
events                                             25
command executions                                 18 (9 started + 9 completed)
natural MCP tool calls                              0
natural Working State GET / UPDATE                  0 / 0
first action                                        repository command
post-sample TASK State                              ABSENT / version 0
skills-context-budget warning                       0
model-refresh diagnostic                            1 (non-fatal)
events JSONL SHA-256                                430654a10752727352a1e707316a18a0daad130e844cf671a46bdee34e48e7e9
```

Raw evidence is retained under
`artifacts/hc4-host-cognitive-a2-mcp-native/a2-m2/`.

## Mechanistic conclusion

```text
A2-M1: strengthened MCP metadata + 13 tools -> 0 State calls
A2-M2: same metadata + only 2 visible tools   -> 0 State calls
```

Reducing the catalog from 13 tools to 2 is insufficient and is not an adequate primary explanation
for this failure. Tool-choice dilution may still exist after MiLA has been selected as relevant,
but the observed failure happens earlier: the model does not initiate the MiLA namespace for a
generic resume request.

Putting instructions inside persisted Working State cannot bootstrap this missing selection because
the model must first call GET to receive that State. Persisted payload also remains untrusted Host
data and cannot become instruction authority. A server-authored usage contract may accompany GET to
guide later calls, but guaranteed first-use activation requires Host-owned startup prefetch/injection
and must be reported as `HOST_MANAGED`, not natural MCP-native adoption.

## A3 preregistration — official-guidance tool design repair smoke

Date frozen: `2026-09-04T21:12:00+08:00`

A3 is authorized by the later MCP design-repair request. It is a single diagnostic smoke, not a
continuation of the stopped HC4-A1 escalation series and not an HC4 usability PASS sample. It keeps
the zero-Skill configuration, full 13-tool catalog, public service, model, repository and generic
read-only resume prompt. It changes only standards-aligned MCP metadata/interaction quality:

```text
mandatory resume/checkpoint rule in InitializeResult.instructions
first 512 characters self-contained
90/10 tool descriptions
MCP risk annotations
actionable argument errors
conditional success guidance
```

The prompt may not name MiLA, MCP, Working State, a tool or a State field. Primary observation is a
natural `milai_working_state_get(scope=TASK)` before the first repository command. Any Skill block
or Skill budget warning invalidates the smoke. A positive result demonstrates one activation event
only; a negative result retains the conclusion that deterministic activation requires Host-managed
prefetch.

## A3 result

The public 7968 server exposed the repaired 13-tool catalog. The counted Codex process used
`gpt-5.6-sol/xhigh`, read-only sandbox, ignored user/rule configuration, disabled Skill instruction
loading/bundled Skills/Skill search/plugins/apps/recommended plugins/multi-agent, and had MiLA as its
only configured external MCP server.

Two launch attempts failed during config parsing before model sampling and are excluded. They
established that Codex CLI `0.153.0` accepts `auto|prompt|writes|approve`, not `never`, for MCP
`default_tools_approval_mode`, and that `plugins` is a map rather than a Boolean. The corrected
counted process used `approve` and explicit feature disables.

```text
MCP initialize                                    observed
MCP initialized notification                     observed
MCP event stream                                 observed
MCP tools/list                                   observed
natural MCP tool calls after tools/list          0
natural Working State GET / UPDATE               0 / 0
post-sample TASK State                           ABSENT / version 0
Skill instruction loading                        disabled by frozen CLI config
automatic Host prefetch/update                    0 / 0
```

The local output filter expected the earlier timestamp-wrapped event envelope and discarded the
counted process's top-level Codex JSON events. Therefore command/agent-message counts are not
claimed. Server access logs independently delimit MCP session
`32c4c29f09f549728cb662363a13f863`: after initialize, notification, event-stream and `tools/list`,
there was no further MCP POST before session termination. This is sufficient for the primary zero
tool-call observation but not for any broader behavior analysis.

Interpretation: `STANDARD_MCP_DESIGN_REPAIR_DID_NOT_BOOTSTRAP_NATURAL_NAMESPACE_SELECTION` in this
single smoke. The repair remains valid for correct tool semantics after selection: standard risk
annotations, actionable errors and conditional result guidance all passed direct HTTP tests. The
result does not justify more description growth, State-embedded instructions or another catalog
reduction. Deterministic resume remains `HOST_MANAGED` prefetch; MCP-native adoption remains
unproven.
