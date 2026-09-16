# HC-4 execution audit

Date: `2026-09-04T13:40:43+08:00`  
Frozen plan: `MILA-HOST-COGNITIVE-AFFORDANCE-HC4-EXPERIMENT-PLAN@0.1`  
Terminal: `HC4_INCOMPLETE`

## Outcome

HC-4 executed eight genuine fresh-Codex session-tasks in two continuous coding workstreams. Every
session received the frozen `codex-full` server instruction over a reachable authenticated HTTP MCP.
None selected an MCP tool, so natural Working State GET/UPDATE use was `0/8`.

The result is not eligible for the plan's PASS or PARKED usefulness decision. The preregistered
minimum is 10 real tasks, 3 distinct chains and 6 continuation sessions; observed counts are 8, 2
and 0. Chain A remains blocked by Product-11's human-label and continuation-opportunity gates. No
independently authorized real schema/migration feature exists for Chain B, and HC-4 itself grants no
schema or Runtime behavior-change authority. No task, State, failure or continuation was fabricated
to fill the matrix.

HC-0～HC-3 therefore retain their earlier product terminal:
`PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE`. HC-4 adds an incomplete but important natural-invocation
signal; it does not disprove the already-tested persistence substrate.

## Frozen identity and treatment

The pre-run Product tree was
`6cfb2418a79cbc7b140d39b66fcc71c939837a129d83ec4de293ca1f276cc2a1`. The sibling Lab lock has
logical digest `0d84fd0a713e80b24bdeda5559962a23446a55307317efc3fd6adc9ad02bcbea`
and verified the exact Product manifest and public interfaces.

After the genuine Chain-C/Chain-D engineering changes, the delivery manifest was regenerated at
339 files with tree SHA-256
`037af05021176fd6034788cb70f239b2e3daae1a6f50054b25e0db4ad89c263c`; manifest file SHA-256 is
`5845d462fcae2b6432d7697d3714820184c3fff550da1dc66e948409c599d1e1`. This post-run identity does
not replace the frozen pre-run treatment lock. The sibling post-run lock verified with logical
digest `8a19fab166928ce3bfd036fc6e7f6ff8e6bb1b7b5bdce6c09c0c275cd7377c48` and file SHA-256
`a6459909faf55fb769149dd8da69d2bc0992d352d79e9a3f4074253863fe7991`.

The only affordance text remained the server-owned instruction frozen in the plan. Session prompts
contained genuine engineering tasks and safety bounds; they never required GET/UPDATE, prescribed
State fields or seeded State content. Every counted session was a new `codex exec --ephemeral`
process with a stable chain-specific server-owned TASK ref and no resumed conversation.

The Runtime, MCP and fresh pgvector PostgreSQL ran locally. JSON events received independent
wall-clock timestamps. Raw JSONL remains ignored in the Lab; exact hashes are recorded in the Lab
study.

## Counted execution

| Run | Work | Result | Working State |
| --- | --- | --- | ---: |
| H4-C1 | reproduce retrieval drift | five failures separated into four causes | 0 calls |
| H4-C2 | first repair | confidentiality/availability/stale assertions repaired | 0 calls |
| H4-C3 | independent correction | compound-subject and redaction generality repaired | 0 calls |
| H4-C4 | final regression | Formation canary leakage fixed; 907 pass / 1 optional skip | 0 calls |
| H4-D1 | refactor boundary audit | zero-logic query/recollection seam selected | 0 calls |
| H4-D2 | implementation | facade/type extraction; 910 pass / 1 optional skip | 0 calls |
| H4-D3 | counter-evidence repair | trace/status removed from seam; import closure 63 -> 2 | 0 calls |
| H4-D4 | independent handoff | no edit; fresh PostgreSQL 912 pass / 1 optional skip | 0 calls |

Across the eight valid runs: 861 timestamped events, 365 command starts, 55 non-zero diagnostic
commands, 18 file-change events, 49,183,387 input tokens, 47,709,312 cached input tokens, 181,110
output tokens and 86,449 reasoning-output tokens were observed. Token counts are Host telemetry, not
cost estimates.

## Cognitive metrics

```text
CognitiveStateUseRate                       0 / 8 = 0.0
successful natural updates                  0
ACTIVE TASK state                           0
definition-valid continuation sessions      0
CrossSessionStateReadRate                   undefined (zero denominator)
state-entry correctness sample              empty
USEFUL / NEUTRAL / HARMFUL                  not adjudicable
```

The main PostgreSQL instance ended with zero `host_cognitive_state` heads, zero versions, zero
Evidence refs and zero state-update idempotency records. MCP transport sessions were established,
so simple endpoint absence does not explain non-use. Tool salience/model invocation remains an
unresolved mechanism; HC-4 forbids repairing it by adding a mandatory prompt or new State schema.
A post-run focused `codex-full` profile test confirmed that the tool catalog and minimal
non-canonical Working State instructions remain registered (`1 passed, 1 deselected`).

Later sessions repeatedly reconstructed prior facts from repository history and diffs. That is
descriptive recovery friction, not a measured continuation failure, because no prior ACTIVE State
existed. CAS correction, semantic stale correction, natural restart recovery, repeated-failure
avoidance and spontaneous field invention were therefore not demonstrated.

## Failure reflection and repair

Execution failures were preserved and classified instead of hidden:

- a synthetic Git commit in the first lock failed exact verification; the optional commit field was
  removed and the replacement lock verified;
- a growing event passed through a shell argument exceeded `ARG_MAX`; the incomplete four-event
  H4-C2 artifact was excluded and stdin streaming produced the valid replacement;
- short-lived background services, strict Runtime environment contamination, MCP approval denial,
  an incorrect `/healthz` probe and an unset cleanup PID were each repaired before counted use;
- a non-pgvector database image, read-only `uv` cache, legacy API/owner test-variable naming, reused
  fixed-ID database state and offline Hatchling isolation were repaired without widening grants or
  changing Product settings;
- D2's too-wide facade/eager-import implementation passed behavior tests but failed its architectural
  purpose; D3 narrowed it to query-only, added lazy-compatible exports and regression tests; D4 made
  no further change;
- the final strict mypy command was initially run from the wrong working directory and the first
  post-run lock check named a non-existent internal module; rerunning from the Runtime root and using
  the installed Lab verifier produced clean PASS results.

The user-requested failure policy was therefore followed: reproduce, attribute, repair generally,
retest, and exclude invalid setup runs rather than tuning away evidence.

## Product engineering outcome

Chain C made general retrieval repairs:

- public and durable QueryPlan projection is allowlist-based and payload-free, including legacy
  trace reads;
- raw lexical bindings cannot grant query-operator authority;
- canonical lookup remains available under honest PARTIAL readiness;
- compound-subject rejection applies only to the canonical subject embedded in a different compound;
- a canary-only Formation candidate without accepted coverage cannot become Reader-visible Evidence.

Chain D added [recollection.py](../../runtime/src/milai/application/recollection.py) and a lazy
compatible [application barrel](../../runtime/src/milai/application/__init__.py). The facade owns
only the structural `retrieve` boundary and execution/replay value types. Existing imports retain
object identity, while concrete trace/status, Flask composition and testkit access remain on
`RetrievalService`. Importing the facade now loads two application modules rather than 63.

Final verification:

```text
focused facade/Product-11/redaction/testkit tests   71 passed
fresh exact-role PostgreSQL Runtime suite           912 passed / 1 optional skip
Ruff                                                 PASS
strict mypy                                         PASS / 181 source files
sdist + wheel                                       PASS
built-wheel import closure and legacy identities   PASS
git diff --check                                    PASS
```

The skip is the declared optional `milai_client` cross-package test in the Runtime-only environment.
All HC-4 file-change events are confined to retrieval/query/recollection source and tests. Migration
0050, Host Cognitive State domain/application/repository/routes, MCP source, public MCP schema,
Canonical data, Product-11 treatment flags and Formal 500 had zero change/use.

One raw D4 message says 46 legacy application exports; the module contains 48 unique exports and an
independent post-run check resolved all 48. This is a report-text correction, not a code change.

## Safety and cleanup

All seven observed counters remained zero:

```text
CanonicalMutationFromWorkingState
WorkingStateAuthorityEscalation
CrossTenantStateLeak
CrossPrincipalStateLeak
CrossProjectStateLeak
RevokedEvidenceAcceptedAsValidReference
RecallSideWorkingStateMutation
```

Because natural State calls were zero, HC-4 did not independently re-exercise every negative path;
the HC-3 PostgreSQL RLS/CAS/TTL/revocation suite remains the substrate evidence.

All per-session test databases and the main synthetic Docker volume were deleted. Temporary Runtime
credentials and the isolated Codex home were moved to the system trash after direct recursive
deletion was denied by the execution safety policy, so that final local cleanup is recoverable.

## Resume rule

Resume HC-4 only after a genuine third-chain task is independently authorized. Keep the exact minimal
server instruction, create a new chain-specific TASK ref, and continue with fresh Codex sessions.
Do not seed a State or add mandatory tool-use language merely to improve invocation metrics. If a
natural State is eventually created, only later fresh sessions may enter the continuation
denominator.

Detailed run metrics and raw artifact hashes are in the sibling Lab study
`studies/active/MILA_HOST_COGNITIVE_AFFORDANCE_HC4.md`.
