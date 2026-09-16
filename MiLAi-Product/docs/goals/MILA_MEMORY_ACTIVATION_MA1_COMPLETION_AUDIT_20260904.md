---
document_id: MILA-MEMORY-ACTIVATION-MA1-COMPLETION-AUDIT-20260904
status: PASS_MA1_HOST_MANAGED_RESUME_CANDIDATE
date: 2026-09-04
schema_change_authority: NONE
canonical_change_authority: NONE
---

# MA-1 Host-managed resume completion audit

## Outcome

`milai-mcp 0.1.4` installs `milai codex`. The launcher creates a private per-session loopback
Streamable HTTP MCP, binds it to one Host project/principal/TASK, completes
`milai_working_state_get(scope=TASK)`, and starts Codex only after a valid bounded response.

The default TASK ref is deterministic over repository root, worktree Git directory and branch.
`--task-ref` is the explicit Host override for continuity across those boundaries. No task-ref
argument was added to the MCP tool.

## Security and authority receipt

```text
State payload in argv                                  0
State payload in environment                           0
Runtime MILAI_* credentials inherited by Codex         0
temporary profile permission                           0600
profile present after normal exit                      0
Codex launch after failed required prefetch             0
automatic Working State update                         0
automatic Canonical/destructive mutation               0
Runtime/MCP tool/schema change                          0
safe Working State access audit                         automatic / retained
```

Bootstrap JSON escapes markup delimiters and excludes server post-call guidance. Only
`schema_version/status/authority/state_id/version/payload` enter the data block. Non-active states
(`ABSENT`, `EXPIRED`, `ARCHIVED`, `DELETED`) are accepted only with empty payloads. Oversized State
fails rather than being silently truncated.

## Real execution receipt

Against the running local Runtime at `127.0.0.1:28180`:

```text
explicit TASK smoke   PREFETCH_COMPLETE / ABSENT / version 0
derived TASK smoke    codex:milai-product:main:fd3cd4f7cc8e9ee4
Codex prompt debug    bootstrap observed in developer context
Codex substitute      /bin/true, exit 0
temporary MCP         stopped after child exit
```

The first operator attempt supplied a nonexistent relative env-file path. It failed before MCP or
Codex startup and changed no State. The corrected path passed. This is retained as a fail-closed
configuration receipt, not a failed product sample.

## Package verification

```text
Ruff                                         PASS
strict mypy                                  PASS
focused launcher tests                       PASS
complete MCP pytest                          119 PASS
sdist                                        milai_mcp-0.1.4.tar.gz
wheel                                        milai_mcp-0.1.4-py3-none-any.whl
built-wheel milai codex --help               PASS
```

The MCP wheel depends on the separately built `milai-client` wheel. A single-wheel `uvx` attempt
cannot resolve that unpublished dependency from the public index; installing the two product wheels
together passes. This pre-existing multi-package distribution boundary is not hidden by MA-1.

## Remaining scope

MA-2 checkpoint detection, MA-3 forced semantic checkpoint and MA-4 explicit-history prefetch are
not implemented or claimed. `MCP_AUTO` remains best effort. HC4 cross-session usefulness requires a
new Host-managed evaluation; MA-1 code presence is not that effect proof.

Schema remains `0.1.x EXPERIMENTAL`; implementation remains `CANDIDATE`; schema freeze remains
`NO-GO`.
