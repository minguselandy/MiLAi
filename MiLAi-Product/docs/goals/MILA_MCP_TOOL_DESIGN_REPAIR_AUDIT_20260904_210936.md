---
document_id: MILA-MCP-TOOL-DESIGN-REPAIR-AUDIT-20260904-210936
status: PASS_PROTOCOL_REPAIR_MCP_AUTO_ACTIVATION_NEGATIVE
date: 2026-09-04
schema_change_authority: NONE
canonical_change_authority: NONE
---

# MiLA MCP tool-design repair audit

## Decision

The 13-tool `codex-full` catalog remains intact. It is already separated by user intent and risk:
read, capture, proposal, review, exact revocation and namespace cleanup are not collapsed into one
action switch. The earlier 13-tool versus 2-tool matched probe produced zero natural Working State
calls in both conditions, so catalog size alone did not explain HC4 adoption failure.

The repair applies a 90/10 policy:

```text
server instructions  cross-tool routing, mandatory resume/checkpoint policy, trust boundary
tool description     what/when/side effect/retry safety in one or two short paragraphs
input schema         ordinary argument shape and literal constraints
error result         problem + reason + fix + example when useful
success result       short conditional next-step guidance
Runtime              capability, scope, CAS, confirmation and idempotency enforcement
```

## Primary-source basis

- OpenAI Codex MCP documentation states that Codex reads MCP server `instructions`, recommends it
  for cross-tool workflows and constraints, and requires the first 512 characters to be
  self-contained: <https://learn.chatgpt.com/docs/extend/mcp?surface=cli>.
- OpenAI model guidance recommends putting tool-specific guidance in descriptions: what the tool
  does, when to use it, required inputs, side effects, retry safety and common errors; cross-tool
  guidance belongs in system/server instructions:
  <https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.5>.
- OpenAI guidance recommends crisp one-to-two-sentence descriptions and verification before
  consequential actions:
  <https://developers.openai.com/api/docs/guides/latest-model?model=gpt-5.2>.

## Implemented changes

1. The first 512 characters of `InitializeResult.instructions` now contain a mandatory TASK resume
   gate, material checkpoint gate, exact Working State tool names and the untrusted-data boundary.
2. All catalog entries have short intent titles and standard MCP `ToolAnnotations`.
3. Missing/unexpected arguments and invalid confirmation literals are intercepted before generic
   SDK validation and returned as corrective MCP errors.
4. Every successful `codex-full` tool result includes additive server-authored `mcp_guidance`.
5. `mcp_usage_contract` remains outside Host-authored Working State payload.
6. No tool, business input schema, Runtime route, database schema, authority or Canonical behavior
   was added or removed.

## Safety interpretation

Annotations and response guidance are hints, not security primitives. Destructive and governance
tools remain separate and still require current authorization, exact server-bound scope,
confirmation literals and operation idempotency. Working State remains `HOST_WORKING` and cannot
mutate Canonical Memory.

## Verification plan

```text
in-process catalog/flow tests             required
real Streamable HTTP lifecycle tests      required
Ruff + mypy                               required
complete MCP package suite                required
wheel build                               required
7968 readiness/catalog/error smoke        required
zero-Skill model adoption smoke           diagnostic only
```

## Verification receipt

```text
Ruff                                            PASS
mypy (11 MCP source files)                      PASS
MCP package tests                               105 PASS
sdist + wheel build                             PASS (milai_mcp 0.1.3)
7968 /readyz                                    HTTP 200
public Streamable HTTP tools/list               13 tools
2025-11-25 initialize instructions over wire    PASS / 1,541 chars
standard annotations over public wire           PASS
Working State success guidance over public wire PASS
actionable missing-argument error over wire     PASS
```

The zero-Skill A3 model smoke is not an HC4 PASS gate. It initialized the server and listed tools
but made zero natural MCP calls. Therefore the protocol/tool-design repair passes while natural
namespace activation remains unproven. A standard MCP server cannot force an unsolicited first tool
call; deterministic prefetch remains a separate Host-managed mode.

## Post-repair tool-selection isolation

The Lab then froze and executed S0-S3 using isolated principal-bound TASK references, no Skills, no
Host prefetch/checkpoint and MiLA as the only external MCP server:

| Arm | Visible tools | Result |
| --- | --- | --- |
| S0 explicit State GET | all 13 | selected and completed `1/1` |
| S1 generic resume | State GET/UPDATE | no MiLA call `0/1` |
| S2 generic resume | resolve + State GET/UPDATE | no MiLA call `0/1` |
| S3 generic resume | all 13 | no MiLA call `0/1` |

S0 proves that the repaired MCP is callable. S1 is the decisive negative: reducing the catalog to
the two Working State tools did not activate the namespace. S2/S3 reproduce the result, so 13-tool
dilution is not the primary cause and catalog narrowing is not a sufficient repair.

The one permitted trigger-first metadata treatment is exhausted. Further description growth,
State-embedded instructions, new cognitive State types and Runtime changes are not authorized by
this finding. Product modes are now stated explicitly:

```text
MCP_AUTO     model-controlled, best effort
HOST_MANAGED deterministic lifecycle access, separate implementation/claim
```

The repair remains a PASS for MCP protocol and execution UX. `MCP_AUTO` natural activation is a
negative result, not an execution defect. HC4 cross-session usefulness remains unevaluable until a
separately authorized Host-managed path creates valid continuation opportunities.
