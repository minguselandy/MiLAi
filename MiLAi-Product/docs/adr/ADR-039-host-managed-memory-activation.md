# ADR-039: Host-managed memory activation

- Status: Accepted for MA-0 and MA-1 candidate implementation
- Date: 2026-09-04
- Schema authority: none
- Canonical authority: none

## Context

HC4 observed zero natural Working State calls across twelve real sessions. A later zero-Skill
selection matrix proved explicit callability (`1/1`) but produced zero MiLA calls for a generic
resume intent with two, three and thirteen visible tools (`0/3`). Tool metadata and catalog
narrowing therefore cannot guarantee required session continuity.

## Decision

MiLA separates `AUTO`, `HOST` and `EXPLICIT` activation. MCP remains the capability execution layer.
The first Host-controlled operation is a session-start TASK Working State GET performed by a new
`milai codex` launcher before Codex begins reasoning.

MA-1 starts a private loopback Streamable HTTP `codex-full` MCP with a Host-derived TASK binding,
calls the standard MCP tool as a client, validates and bounds the response, and supplies it to Codex
as explicitly non-canonical/untrusted bootstrap data. It does not add a tool, tool argument, Runtime
route, table or authority transition.

## Consequences

- Required resume access no longer depends on model tool-selection policy.
- Codex still decides exploratory recall and Product-11 residual continuation.
- Canonical and destructive actions still require current explicit user authorization.
- A private per-launch MCP is used so task binding stays Host-owned without modifying the public MCP
  schema or trusting a client-supplied task identifier.
- The launcher must protect bootstrap data and Runtime credentials from process-argument and child
  environment exposure.
- Checkpoint generation, compaction hooks and historical-query prefetch remain future separately
  accepted stages.

## Alternatives rejected

- More Server Instructions/tool-description tuning: exhausted by the S0-S3 result.
- State-embedded instructions: cannot bootstrap GET and violates the data/control boundary.
- Always resolve on every turn: adds avoidable latency and noise.
- Direct Runtime read from the launcher: would bypass the MCP product interface.
- Model-supplied task reference: weakens the Host-owned binding boundary.
