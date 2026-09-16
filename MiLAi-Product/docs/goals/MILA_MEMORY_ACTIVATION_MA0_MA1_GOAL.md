---
document_id: MILA-MEMORY-ACTIVATION-MA0-MA1-GOAL
status: COMPLETE_MA1_HOST_MANAGED_RESUME_CANDIDATE
date: 2026-09-04
schema_change_authority: NONE
canonical_change_authority: NONE
---

# Memory Activation MA-0 / MA-1 Goal

## Objective

Make TASK Working State access deterministic at a new Codex session boundary without changing MCP
tool schemas, Runtime persistence or Canonical Memory.

## Authorized scope

```text
MA-0  freeze AUTO / HOST / EXPLICIT activation policy
MA-1  implement milai codex session-resume launcher
```

Not authorized here:

```text
MA-2 checkpoint detector
MA-3 forced semantic checkpoint
MA-4 historical-query prefetch
Product-11 behavior
new State types or schema
automatic Canonical/destructive mutation
```

## Gates

1. Stable Host TASK binding derives from repository/worktree/branch or explicit Host override.
2. A private loopback HTTP MCP starts with that binding.
3. Host completes `milai_working_state_get(scope=TASK)` before Codex starts.
4. MCP/read/validation failure stops launch.
5. Bootstrap is bounded, explicitly non-canonical and payload instructions remain untrusted.
6. State/token stay out of argv; Runtime credentials stay out of the Codex environment.
7. Temporary MCP/profile cleanup succeeds.
8. Full MCP package static, test and build gates pass.

## Completion receipt

Focused tests cover stable binding, markup isolation, inactive-state handling, bootstrap limits,
private-profile lifecycle, credential scrubbing, Host-owned option protection, strict call ordering
and fail-closed prefetch. A real Runtime-backed smoke using an isolated derived TASK binding
completed the required prefetch as `ABSENT/version=0`, then launched a non-model `/bin/true` Codex
substitute and cleaned up.

Codex `debug prompt-input` independently confirmed the bootstrap appears in the developer context.
The State did not become a positional user prompt. Complete MCP package Ruff, strict mypy, pytest,
sdist/wheel build and combined built-wheel entrypoint checks pass.
