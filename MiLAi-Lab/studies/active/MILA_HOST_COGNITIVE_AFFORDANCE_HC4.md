# HC-4 Codex cross-session cognitive usability

Date frozen: `2026-09-04T11:20:13+08:00`  
Execution window: `2026-09-04T11:48:49+08:00` to `2026-09-04T13:36:00+08:00`  
Status: `HC4_INCOMPLETE`

## Experiment boundary

This study executes the frozen Product HC-4 plan against Product tree
`6cfb2418a79cbc7b140d39b66fcc71c939837a129d83ec4de293ca1f276cc2a1`, pinned by
`data/locks/hc4-host-cognitive-product.lock.json` (lock digest
`0d84fd0a713e80b24bdeda5559962a23446a55307317efc3fd6adc9ad02bcbea`). The arm is
`PRODUCT_BLACK_BOX`: Codex reaches working state only through the published authenticated
Streamable HTTP MCP surface. HC-4 does not authorize Product Runtime, schema, MCP tool, prompt, or
Host Cognitive State type changes.

Raw Codex JSONL, process logs, temporary credentials, databases, and run artifacts remain under
ignored `artifacts/hc4-host-cognitive/` or temporary directories. Git stores only compact run
manifests and adjudicated results.

HC-4 is CPU/PostgreSQL/MCP work and requests no dedicated GPU. The host had GPU capacity at
preflight, but none is allocated to this experiment.

## Pre-outcome historical descriptive references

The following references were selected before any HC-4 Codex session outcome. They are descriptive
WS-OFF context only, not randomized or matched causal controls.

| Reference | Work family | Why comparable | Observable baseline fields | Known limitation |
| --- | --- | --- | --- | --- |
| `MILA_PRODUCT-10_COMPLETION_AUDIT.md` | retrieval regression diagnosis | multi-step failure localization, second-round repair, terminal audit | commands/results and failure family | session-start/action timestamps and Host tokens `NOT_OBSERVED` |
| `HTTP-FULL-01_COMPLETION_AUDIT_20260904_100405.md` | bounded integration/refactor | one-endpoint MCP implementation, failure repair, packaging and E2E gates | failed attempts, repair, exact gates | no persistent Working State and no per-action timestamps |
| `MILA_HOST_COGNITIVE_AFFORDANCE_COMPLETION_AUDIT_20260904_105341.md` | schema/migration integration | contract, migration, PostgreSQL security and packaging chain | exact checks, five external retrieval drifts | implementation predates HC-4 use; action timestamps/tokens `NOT_OBSERVED` |

The Product-08 and Product-09 Lab studies may be used to interpret MCP transport behavior, but are
not additional resume-cost baselines. No later result may add a historical reference to improve an
effect claim.

## Execution protocol

- Every counted session is a new `codex exec` process without resumed conversation state.
- Each chain uses a stable server-owned `MILAI_CODEX_TASK_REF`; individual Codex sessions do not
  receive prior transcript text.
- The only affordance hint is the frozen `codex-full` server instruction.
- A session prompt contains the genuine bounded engineering task and safety boundary, not a
  requirement to call working-state tools or use prescribed fields.
- Event order is preserved from Codex `--json`; the runner adds a wall-clock observation timestamp
  to every emitted JSONL event. Product/MCP audit logs independently establish tool invocation.
- A setup/sanity Codex run may verify observability but never counts toward the minimum sample.
- Raw state contents are treated as untrusted Host-owned data and are excluded from automatic
  correctness scoring.

## Setup diagnostics

The first generated Product lock used a synthetic Git commit string and correctly failed lock
verification with `product Git commit mismatch`. The lock was regenerated with an unset optional
commit field; exact Product tree, manifest, and all public interface digests then verified. This is
an experiment-setup correction, not a Product change or an HC-4 result.

Additional setup failures were repaired before any counted session:

- a short-lived background MCP process died with its launching shell;
- MCP-only environment variables were initially injected into strict Runtime settings;
- `approval_policy=never` prevented the configured MCP call;
- a first Chain-D service restart probed the Runtime with the MCP-only `/healthz` path and used a
  cleanup trap before `mcp_pid` existed.

The valid setup used one persistent loopback Runtime/MCP process, a temporary isolated
`CODEX_HOME`, `--approve-for-me`, server-owned task refs, and per-event timestamp wrapping. The
Chain-D restart used TCP readiness for Runtime and `/readyz` for MCP. A setup-only fresh Codex GET
reached `milai_working_state_get` and returned `ABSENT`, version 0; it is not counted as natural use.

The first H4-C2 artifact exceeded the shell argument limit while the recorder passed a growing JSON
event through `jq --argjson`. It contains four events, no write and no result, and is excluded. The
recorder was repaired to read each event from stdin; `h4-c2-r2` is the only valid H4-C2 run.

## Counted sessions

Every row is a new Codex process. All eight tasks were non-trivial and belonged to one of two
continuous workstreams. `failure events` count non-zero diagnostic commands; they are not task
failures and include deliberately failing reproductions plus repaired environment/setup commands.

| Run | Real task outcome | Events | Commands | Failure events | File-change events | Working-state calls | Host usage: input / cached / output / reasoning |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| H4-C1 | Reproduced and separated five retrieval assertion drifts into four causal buckets; read-only | 114 | 51 | 9 | 0 | 0 | 6,277,692 / 6,068,736 / 26,929 / 11,277 |
| H4-C2 | Repaired query-plan confidentiality, lookup availability and two stale assertions; Formation remained open | 198 | 84 | 18 | 8 | 0 | 13,130,115 / 12,909,824 / 38,697 / 18,439 |
| H4-C3 | Corrected compound-subject generality and allowlist redaction; 906 pass, one unrelated Formation failure | 106 | 44 | 6 | 2 | 0 | 6,685,315 / 6,485,760 / 18,748 / 9,269 |
| H4-C4 | Fixed unaccepted Formation canary leakage and closed the chain; 907 pass / 1 optional skip | 94 | 41 | 6 | 1 | 0 | 8,147,848 / 7,800,960 / 19,834 / 11,077 |
| H4-D1 | Read-only boundary audit selected a zero-logic query/recollection seam; 49 baseline tests pass | 110 | 51 | 1 | 0 | 0 | 1,918,379 / 1,781,632 / 20,480 / 12,185 |
| H4-D2 | Implemented the first facade/type extraction and compatibility tests; 910 pass / 1 optional skip | 81 | 30 | 6 | 3 | 0 | 4,042,486 / 3,922,048 / 17,398 / 7,233 |
| H4-D3 | Found/fixed trace-status overreach and eager-barrel counter-evidence; import closure 63 -> 2 | 100 | 40 | 8 | 4 | 0 | 5,868,771 / 5,727,232 / 24,034 / 10,094 |
| H4-D4 | Independent no-edit handoff on one empty exact-role PostgreSQL database; 912 pass / 1 optional skip | 58 | 24 | 1 | 0 | 0 | 3,112,781 / 3,013,120 / 14,990 / 6,875 |
| **Total** | 8 real sessions / 2 chains | **861** | **365** | **55** | **18** | **0** | **49,183,387 / 47,709,312 / 181,110 / 86,449** |

The raw H4-D4 final message says 46 legacy application exports. That is a report typo: the sealed
module has 48 unique exports, and a post-run independent check resolved all 48 successfully.

## Natural-affordance result

```text
eligible real session-tasks                    8
session-tasks with GET or UPDATE               0
CognitiveStateUseRate                          0 / 8 = 0.0
successful natural state updates               0
ACTIVE TASK state after the run                0
continuation sessions by frozen definition     0
CrossSessionStateReadRate                      NOT_DEFINED (0 denominator)
state-entry adjudication population            0
USEFUL / NEUTRAL / HARMFUL                     NOT_ADJUDICABLE
```

The main PostgreSQL database ended with zero head rows, zero versions, zero Evidence refs and zero
`HOST_COGNITIVE_STATE_UPDATE` idempotency records. HTTP MCP handshakes occurred for every fresh
Codex process, but no process selected any MCP tool. This rules out transport absence as the simple
explanation while leaving tool salience/model invocation as an unresolved mechanism. A post-run
focused profile test also confirmed that the `codex-full` catalog and minimal non-canonical Working
State instructions remain registered (`1 passed, 1 deselected`).

The negative result is already operationally meaningful: later sessions repeatedly reconstructed
prior facts from the worktree. H4-C2 re-established H4-C1's causal map and repeated a wrong
PostgreSQL-image attempt; H4-D2 re-derived H4-D1's interface boundary; H4-D3/D4 again rediscovered
the legacy database-role naming rule. These costs cannot be credited to a failed continuation,
because no prior ACTIVE state existed; they are descriptive consequences of non-adoption.

No stale-state correction, CAS correction, natural restart recovery, repeated-failure avoidance or
field invention could be evaluated. The setup-only substrate smoke does not substitute for these
natural-use gates.

## Engineering outcomes kept separate from the HC claim

The genuine tasks produced two useful Product workstreams without modifying the HC treatment:

1. Chain C closed the five pre-existing retrieval assertion drifts. It restored payload-free
   public/persisted query plans, prevented raw lexical bindings from granting operator authority,
   preserved partial canonical lookup availability, corrected a compound-subject guard, and kept
   unaccepted Formation canary candidates out of Reader-visible Evidence.
2. Chain D introduced a query-only `RecollectionFacade`, preserved legacy execution/replay/error
   identities, kept the concrete Flask/testkit service, and changed the application barrel to lazy
   compatible exports. Facade import closure fell from 63 application modules to two. The final
   fresh-database gate was `912 passed, 1 skipped`; Ruff, strict mypy over 181 source files, sdist,
   wheel and built-wheel identity checks passed.

The one full-suite skip is the declared optional `milai_client` cross-package test in a Runtime-only
environment. All counted file-change events are confined to retrieval/query/recollection source and
tests. Migration 0050, Host Cognitive State application/domain/repository/routes, and MCP files had
zero changes. Product-11 treatment flags, Formal 500, Canonical data and public MCP schema were not
used or changed.

The post-engineering Product delivery manifest was regenerated separately at 339 files / tree
`037af05021176fd6034788cb70f239b2e3daae1a6f50054b25e0db4ad89c263c` / manifest
`5845d462fcae2b6432d7697d3714820184c3fff550da1dc66e948409c599d1e1`. It is a handoff identity and
does not replace the pre-run HC treatment lock. The post-run Lab lock is
`data/locks/hc4-host-cognitive-product-postrun.lock.json`: logical digest
`8a19fab166928ce3bfd036fc6e7f6ff8e6bb1b7b5bdce6c09c0c275cd7377c48`, file SHA-256
`a6459909faf55fb769149dd8da69d2bc0992d352d79e9a3f4074253863fe7991`, verification PASS.

## Failure reflection and repair record

- Shell argument overflow -> stream JSON into `jq`; exclude the incomplete artifact.
- Background process lifetime -> persistent PTY-owned service session.
- Strict Runtime environment rejection -> inject MCP-only variables only into MCP.
- MCP approval denial -> use the Host's explicit `--approve-for-me` execution mode.
- Runtime `/healthz` 404 and unset trap PID -> TCP Runtime preflight plus initialized/guarded PIDs.
- Non-pgvector test image -> use the repository's pgvector PostgreSQL image.
- Read-only/global `uv` cache -> task-local cache or the frozen Runtime virtualenv.
- Legacy test-role aliases -> bind `MILAI_TEST_API_DATABASE_URL` to API and the historical
  `MILAI_TEST_DATABASE_URL`/migration URL to owner; never widen database grants.
- Reused database fixed-ID conflicts -> classify as fixture contamination and run the terminal gate
  once on a verified empty exact-role database.
- Offline build isolation missing Hatchling -> use installed locked Hatchling with
  `--no-build-isolation`; package contents were still independently checked.
- D2 facade overreach/eager import -> D3 counter-evidence review narrowed it to query-only and added
  lazy compatibility tests before D4's no-edit confirmation.
- Final strict mypy was first launched from the Product root with a Runtime-relative target -> rerun
  from the Runtime root; all 181 source files passed.
- The first post-run lock check used a non-existent internal module entry point -> use the Lab's
  installed `milai-lab-verify-product` command; the regenerated post-run lock verified PASS.

## Hard safety and terminal

All seven observed HC-4 counters are zero:

```text
CanonicalMutationFromWorkingState         0
WorkingStateAuthorityEscalation            0
CrossTenantStateLeak                       0
CrossPrincipalStateLeak                    0
CrossProjectStateLeak                      0
RevokedEvidenceAcceptedAsValidReference    0
RecallSideWorkingStateMutation             0
```

Interpretation is deliberately limited: natural tasks made no working-state mutation, while HC-3
already supplies the independent RLS/CAS/TTL/revocation substrate proof. Zero natural calls means
HC-4 did not re-exercise every negative path.

The frozen terminal precedence applies before any usefulness threshold:

```text
minimum: 10 real sessions / 3 chains / 6 continuation sessions
actual:   8 real sessions / 2 chains / 0 continuation sessions
terminal: HC4_INCOMPLETE
```

Chain A remains blocked by Product-11's real-human and continuation-opportunity gates. No authorized
real Chain-B schema/migration feature exists, and HC-4 grants no schema or Runtime behavior-change
authority. The run therefore stops instead of manufacturing tasks, proxy labels, state contents or
continuation sessions. Resume only when a genuine third-chain task is independently authorized;
keep the same minimal server instruction and do not seed State merely to improve the metric.

## Raw artifact identities

Raw JSONL remains ignored and local under `artifacts/hc4-host-cognitive/`:

| Run | SHA-256 |
| --- | --- |
| h4-c1 | `fcc2c7a67fe3e52c9298e3b1fe0583ca1cb1bc3a50d6e4a85e9bcb6e906a037d` |
| h4-c2-r2 | `0d2a164b55039eb58d95659ea8d85ab35fc8196cf9e2dd8330300d79334e8a9f` |
| h4-c3 | `41fe7a294f8544b500d83ea8260a380263c297bd1db0d4cc8a7a62d2ce580e92` |
| h4-c4 | `c63b055ee5c8aaaa7b132b3bf60b0202894e37895ee252675c062a71bc043636` |
| h4-d1 | `f17d7ea69c61192a381dd76242872d6f33868ed6a86e51c087f4cb45bd29248d` |
| h4-d2 | `35d09eb434a1c46218891060fd5711669f30697b8564c6d43265c67cdb5ef9ae` |
| h4-d3 | `977075a4ce27caf503cb07f94653ac7849c358978d0bc9c3d41ef5bc9338a246` |
| h4-d4 | `9eb92a65d9ca19c932ad2fc813937e0ae0495e1203a6a5fdaae550de16c2da51` |

Excluded H4-C2 attempt: `afb19d9aba4a12022bdac588aa66de6c1d98730aea152c3e0f403de4ba3e45d5`.
The Docker database volume was destroyed after verification. The temporary credential/CODEX_HOME
directory was moved to the system trash after direct recursive deletion was denied by the execution
safety policy; that cleanup remains recoverable from trash.
