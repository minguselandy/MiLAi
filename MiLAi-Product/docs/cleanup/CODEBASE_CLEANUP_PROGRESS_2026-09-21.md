# MiLAi codebase cleanup progress report

## Report identity

```text
Generated at:              2026-09-21T18:40:28+08:00
Execution state:           PAUSED BY USER
Cleanup contract:          MiLAi 全仓代码整理与模块化重构执行总指令 v1.0
Goal ledger:               docs/cleanup/CODEBASE_CLEANUP_GOAL.md
Current local branch:      cleanup/08-memory-context-foundation
Current branch HEAD:       5c0415b6c2a962fb4a67aad28a0b512041ad2b07
Current origin/main:       77ef5be43c05016d122a128144f635b130b8dc2d
Open pull request:         PR #17
Candidate workflow:        Run #55 / 35587035579
Candidate Product tree:    9213e11fccdea898d459d0f85a389388867eb0fc6b0652108b87e67730a75e0f
Product manifest SHA-256:  87485bde65b626cd4b8ff4cb033848e2002a43da4daf869992ae4241992b7917
Architecture version:      1.0.0 frozen
Conformance:               9 PASS / 35 UNVERIFIED / 0 DEVIATION
```

This report records the exact pause point. No merge, new extraction, behavior change, workflow
rerun, timeout relaxation, or remote cancellation was performed after the pause request. The
already-running GitHub workflow may continue independently, but it does not authorize merging PR
#17 while execution is paused.

## Executive summary

Repository consolidation and source-of-truth work remain complete. Cleanup phases C0 and C1 are
complete. Retrieval modularization C2 is complete and merged. Memory Context modularization C3 is
partially complete: its first dependency-foundation PR is implemented, pushed, locally verified,
and awaiting the final result of its one full composition run. C3's second bounded extraction and
all later phases have not started.

The cleanup has remained behavior-preserving. Frozen Architecture, migrations, Product/Lab/Archive
top-level boundaries, retrieval policy, Context budgets, prompts, authority rules, MCP/CLI/HTTP
contracts, Lab treatments, sealed fixtures and historical receipts were not modified by the active
Memory Context PR.

## Phase status

| Phase | Scope | Status at pause |
| --- | --- | --- |
| C0 | Baseline + inventory | COMPLETE |
| C1 | Safe hygiene | COMPLETE — no deletion met the evidence threshold |
| C2 | Runtime Retrieval modularization | COMPLETE and merged |
| C3 | Runtime Memory Context modularization | IN PROGRESS — first of two planned PRs awaiting CI closure |
| C4 | MCP Server modularization | NOT STARTED |
| C5 | OpenWorker Host modularization | NOT STARTED |
| C6 | Test organization | NOT STARTED |
| C7 | Lab active code organization | NOT STARTED |
| C8 | Compatibility/dead-code audit | NOT STARTED |
| C9 | Current-tree evidence refresh | NOT STARTED |
| C10 | Final cleanup baseline | NOT STARTED |

## Completed baseline hardening before C3

The cleanup exposed several pre-existing engineering weaknesses. They were handled in isolated
PRs rather than mixed into structural extraction:

- Lab deadline evidence was made deterministic instead of relying on a 40 ms whole-request race.
- Product-05 active runners were repaired to use the explicit OpenWorker bridge address instead of
  the now-rejected `0.0.0.0` wildcard listen host.
- Active Lab `tools/` Product dependencies were inventoried and a no-new-private-dependency gate
  was added.
- Runtime backup-test quiescence was made deterministic by waiting for closed role sessions to
  disappear before invoking the unchanged production backup gate.
- PR #16 Run #53 passed all 17 jobs and composition on its first Runtime attempt; it established
  `main=77ef5be43c05016d122a128144f635b130b8dc2d`, the base of the current C3 branch.

## C2 Retrieval result

Retrieval now has explicit internal seams for:

```text
policy
candidates
temporal reasoning
selection and Context budget
acquisition composition
operator execution
result assembly
trace serialization
bounded finalization
```

The public import remains:

```python
from milai.application.retrieval import RetrievalService
```

`retrieval.py` remains the high-level orchestration facade. It is currently 2,407 lines / 113,883
bytes, reduced from approximately 196 KB before C2. Sixty-six extracted helper functions, the
trace-stage mapping, and `_LegacyReplayPrefix` were moved with AST-equivalent definitions. The
final decision/trace/response phase was isolated behind an explicit finalization boundary without
changing acquisition, ranking, gate, trace, or response semantics.

Retrieval PR #15 Run #51 ultimately passed all 17 jobs and composition. A repeated backup-test
quiescence race observed during that run was fixed separately in PR #16.

## C3 Memory Context foundation candidate

### Implemented scope

PR #17 extracts only dependency-leaf responsibilities into:

```text
runtime/src/milai/application/memory_context_core/
    __init__.py
    common.py
    contracts.py
    provenance.py
    semantics.py
    units.py
```

Responsibilities are:

| Module | Responsibility |
| --- | --- |
| `contracts.py` | Compilation results, adjacency-reader protocol, typed token-accounting error |
| `common.py` | Hash/identity, token estimate, authority, position, sufficiency and stable uniqueness primitives |
| `semantics.py` | Query-IR classification, Reader-safe semantic projection, operand validation |
| `provenance.py` | Derived/canonical Evidence and source-reference collection |
| `units.py` | Reader evidence units, status text and bounded envelope rendering |

The following remain in `memory_context.py` for the second bounded PR:

```text
MemoryContextCompiler
activation
Evidence views and adjacency windows
window ordering
full Context rendering and fitting
receipt composition
trace projection
```

`memory_context.py` is currently 3,716 lines / 144,201 bytes, reduced from 3,995 lines / 153,970
bytes at C3 start. The first PR deliberately optimizes dependency direction and compatibility, not
maximum line reduction.

### Compatibility evidence

- Twenty-five moved class/function definitions are AST-identical to
  `77ef5be43c05016d122a128144f635b130b8dc2d`.
- `_OPAQUE_READER_KEYS` has an identical constant expression.
- `milai.application.memory_context` explicitly re-exports all moved contracts and helpers at both
  runtime and mypy boundaries.
- Existing private Runtime consumer `_reader_semantic_value` remains available from the facade.
- Existing test-only `_order_windows` remains in the original module and is untouched.
- `test_memory_context_core_compatibility.py` fixes facade-to-core object identity for every symbol
  extracted in this PR.

### Local candidate verification

```text
Targeted Memory Context/compatibility tests     121 passed
Runtime unit suite                              1053 passed / 1 skipped
Runtime Ruff                                    PASS
Runtime strict mypy                             PASS / 219 source files
Runtime wheel and sdist                         PASS
Distribution module-path snapshot               PASS / 7 required paths
Product manifest --check                        PASS
Repository boundary verifier                    PASS
Behavior receipt verifier                       PASS
Frozen Architecture lock                        PASS
Current Conformance verifier                    PASS / status UNVERIFIED
```

One local attempt using `pytest -m 'not integration'` entered two unmarked files under
`tests/integration/test_host_notes.py` and failed setup because no local PostgreSQL URLs were
configured. The remaining selected tests reported 1,081 passed / 1 skipped. This is a test-marker
observation, not a Memory Context regression; it was not changed in the structural PR. The explicit
`tests/unit` run passed, and PR #17's real PostgreSQL Runtime job passed remotely.

## PR #17 / Run #55 status at pause

Pull request:

```text
https://github.com/minguselandy/MiLAi/pull/17
```

Workflow:

```text
Run number:   55
Run ID:       35587035579
Branch HEAD:  5c0415b6c2a962fb4a67aad28a0b512041ad2b07
```

Status captured at report generation:

| Job | Status |
| --- | --- |
| Fail-fast source boundaries | SUCCESS |
| Product Runtime and PostgreSQL | SUCCESS |
| Product identity manifest | SUCCESS |
| Current implementation conformance receipt | SUCCESS |
| Archive index and reorganization evidence | SUCCESS |
| python-client integration | SUCCESS |
| MCP integration | SUCCESS |
| OpenWorker integration | SUCCESS |
| hooks integration | SUCCESS |
| LangGraph integration | SUCCESS |
| AutoGen integration | SUCCESS |
| Lab active package and study boundary | SUCCESS |
| replay: presentation-v1 | SUCCESS |
| replay: presentation-v2-wrong-intent | SUCCESS |
| replay: presentation-v2-corruption | SUCCESS |
| replay: presentation-v2-positive | IN PROGRESS |
| Product/Lab/Archive composition | NOT STARTED — waiting on replay |

Therefore PR #17 is not approved for merge at this pause point. Fifteen of sixteen prerequisite
jobs are successful, but the required composition result does not yet exist.

## Current Git state

```text
Local branch == remote branch:
  cleanup/08-memory-context-foundation
  5c0415b6c2a962fb4a67aad28a0b512041ad2b07

Local main == origin/main:
  77ef5be43c05016d122a128144f635b130b8dc2d

PR branch base:
  77ef5be43c05016d122a128144f635b130b8dc2d
```

Before the pause documentation was created, the PR branch worktree was clean and exactly matched
its remote branch. This report and the local Goal status update are intentionally not committed or
pushed, so the frozen PR #17 candidate identity and its single composition run remain unchanged.

## Preserved immutable areas

No current cleanup change touched:

```text
MiLAi-Product/architecture/v1.0/**
MiLAi-Lab/studies/archive/**
MiLAi-Artifact-Archive historical bytes
DB migrations/schema
MCP tool names or schemas
CLI/HTTP contracts
retrieval thresholds, weights or routes
Context budget or activation thresholds
prompt/system policy
authority, scope, permission, token or confirmation semantics
Lab sealed fixtures, labels, configs or result JSON
historical diagnosis/remediation receipts
```

## Deferred work

### Immediate closure when resumed

1. Read the final status of Run #55 without rerunning it.
2. Require `presentation-v2-positive=SUCCESS` and composition to have actually executed and passed.
3. Re-check `origin/main` and PR mergeability.
4. Merge PR #17 only if its tested merge base remains valid.
5. Do not require a duplicate post-merge full composition when the tested merge tree is identical;
   record the merged main SHA.
6. Add this pause report to the next appropriate documentation commit without changing the tested
   PR #17 tree retroactively.

### C3 second bounded PR

Resume from the merged PR #17 main and extract dependency-complete groups for activation, windows,
ordering, rendering, receipts and the compiler. Preserve:

```text
from milai.application.memory_context import MemoryContextCompiler
from milai.application.memory_context import _reader_semantic_value
from milai.application.memory_context import _order_windows
```

Do not change thresholds, budget arithmetic, ordering keys, serialized Context bytes, receipt
mapping, exact-token accounting or experiment treatment. Use targeted tests/Ruff/mypy during
development and one full 17-job composition only for the final subsystem candidate.

### Remaining phases

- C4 MCP Server: two medium PRs after checking Lab private dependencies.
- C5 OpenWorker Host: two medium PRs preserving PR #4 ingress behavior exactly.
- C6 test organization with receipt node-ID wrappers.
- C7 Lab thin runners and method seams without changing datasets/treatments.
- C8 explicit compatibility registry and evidence-backed dead-code audit.
- C9 rerun the five FIXED TECH_DEBT behaviors against one final Product tree and add new
  `post-cleanup.receipt.json` files without rewriting historical receipts.
- C10 final module map, cleanup results, final identity and one final composition baseline.

## Resume invariant

The next execution must begin with read-only reconciliation:

```text
Run #55 final result
PR #17 state and mergeability
origin/main identity
local branch/working-tree state
Product manifest and Conformance freshness
```

No new extraction should begin until PR #17 is either safely merged or explicitly abandoned and
the new exact green base is recorded.
