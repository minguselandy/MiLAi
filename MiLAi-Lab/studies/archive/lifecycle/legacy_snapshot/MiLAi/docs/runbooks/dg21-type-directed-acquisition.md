# DG-21 Type-Directed Acquisition Runbook

## Scope and default state

DG-21 is an internal, default-disabled acquisition candidate. Production and public MCP behavior
must remain unchanged unless an owner separately authorizes promotion. The Runtime defaults remain:

- `retrieval_deterministic_recovery_enabled = false`
- `retrieval_type_directed_acquisition_enabled = false`
- no DG-21 persistent temporal projection
- zero residual Provider/controller calls and zero automatic retries

The frozen execution policy is `dg21-opened-dev-v0.1`, digest
`bcf532e8edcc6e06c1ba238230347866d5a53eea9e954fd4f6243f8f08d53ef4`.
Do not select profiles from case IDs, expected answers, scorer fields, or free-form evidence text.

## Safe diagnostic sequence

When a request remains unresolved, diagnose in this order:

1. Confirm the `MemoryQueryIR`, target requirement, RequirementState epoch, capability digest, and
   policy digest.
2. Classify exactly one first-loss owner. A later loss may be a secondary reason but must not replace
   the first loss.
3. Confirm the selected channel is executable, target-local, within its declared time axis, and has
   not already executed for that requirement.
4. Confirm the official executor performed at most one additional pass, excluded already-seen
   regions, and preserved scope, authority, time, revoke, and retention gates.
5. Inspect Binding and Sufficiency. Never infer COUNT completeness from a truncated context or use
   source-observed time as event time.
6. Keep the product label-free until its context is sealed. Only then may the frozen Reader protocol
   run, and scoring starts only after a complete Reader product seal.

Cases are evidence for a missing invariant, not selector inputs. A correction is acceptable only if
it is expressed through typed requirements, capability/state contracts, or governed provenance and
passes positive and negative synthetic coverage.

## Reader failures

A strict-JSON, transport, identity, or context-drift failure stops that matched run. Do not retry in
place, change seed, increase output limits, alter the prompt/model, accept malformed JSON, or reuse an
answer across arms.

Successful post-seal Reader calls may be checkpointed and reused only when all of these match:

- case, arm, token budget, and logical request ID
- exact context bytes and SHA-256
- frozen model, provider contract, and matched seed
- `finish_reason = stop`, one provider call, no context truncation
- label-free and formal-holdout-free source artifact

Conflicting records fail closed. A repeated failure of the exact same identity is quarantined and is
reported as a terminal blocker; it is not converted into a product answer.

## Temporal lane

The accepted DG-21 temporal result is query-time proof over governed candidates. WP06 was not entered.
Do not create an event projection, migration, table, index, dual-write, or backfill unless the owner
provides the exact authorization phrase `DG21_TEMPORAL_SCHEMA_AUTHORIZED` after a fresh WP05 decision
of `NEEDS_PERSISTENT_EVENT_PROJECTION`.

## Rollback

Rollback is flag-first:

1. Keep both DG-21 Runtime settings false.
2. Load the prior deterministic policy/version and verify its digest.
3. Confirm old QueryIR compatibility and the exact COMPLETE/NO_TARGETABLE zero-work paths.
4. Run Runtime unit/contract, DG-21 evaluation, strict mypy, Ruff, and fresh PostgreSQL
   integration/security gates.
5. Preserve failed artifacts and issue a new receipt; never overwrite a sealed run.

There is no DG-21 schema rollback because WP06 was not entered. Existing non-DG-21 repository
migrations are outside this lane and must not be represented as DG-21 temporal completion.

## Current terminal boundary

S1-S6 and S8 pass their respective gates, including preference expressivity, safe query-time temporal
proof, and real PostgreSQL/security coverage. S7 is not correctness-sealed: one exact Reader identity
repeatedly violated the frozen strict-JSON contract, and the label-free D/2048 trace used 10 additional
acquisition calls against a ceiling of 8. Five latency repeats are therefore not authorized.

Allowed statement: DG-21 demonstrated type-pruning and typed-channel behavior on its frozen synthetic
and opened-development evidence, while the matched Core lane remains parked.

Forbidden statements include production improvement, formal LongMemEval improvement, temporal schema
completion, or full DG-21 success.
