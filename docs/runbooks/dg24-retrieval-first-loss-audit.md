# DG-24 Retrieval First-Loss Audit Runbook

## Scope and claim boundary

DG-24 is a behavior-neutral, opened-development diagnostic audit. It traces the current product retrieval path, runs official read-only channel probes only after every product trace is sealed, and reopens pre-sealed gold/proof registries only after both execution planes are sealed.

The audit may localize candidate loss and route a successor experiment. It does not claim that recall improved, a retrieval rule is causal, multi-channel union is superior, Reader behavior improved, the formal holdout improved, or the candidate is production-ready. The candidate remains disabled by default. The public MCP schema, PostgreSQL schema, canonical state, and `architecture/v1.0` bundle are outside the mutation scope.

## Three-plane execution order

Use fresh, write-once run directories and preserve every failed run.

1. Product plane: execute the fixed ten-case order once per request with labels unavailable; seal `ProductRetrievalTraceV01` and all embedded `CandidateLifecycleTraceV01` records.
2. Official probe plane: only after the product seal, call the existing official executor/repository/index once at the widest verified cap for every requirement/channel. Derive smaller supported cutoffs offline from that same result. Type cutoffs above the verified official ceiling as unavailable.
3. Scorer plane: only after product and probe seals, reopen the exact S0 gold/proof registries, verify their digests, and score sealed bytes without importing or invoking Runtime retrieval.

Never feed probe results into product Binding, rerun a product request after probing starts, or run a Reader, generative Provider/controller, judge, reranker, cue generator, treatment, or leave-one-rule-out experiment.

## Stage sequence

1. S0 freezes the case order, input-only manifest, source closure, stage/source bindings, reason codes, audit caps, safety boundary, and opaque scorer-registry seals.
2. S1 validates schemas, occurrence identity, dedup lineage, drop/rediscovery, irrecoverable loss, proof state, authorized absence, and forbidden gold fields using synthetic fixtures.
3. S2 executes matched trace-OFF/trace-ON product runs and requires equality for request semantics, repository calls, channel decisions, candidate order, dedup, Gate, EvidenceSet, Interpretation/Binding, RequirementState, Sufficiency, and operator readiness.
4. S3 executes and seals all ten label-free product traces before any probe.
5. S4 validates the already-sealed official probe collection without rerunning products or probes.
6. S5 verifies both execution seals, reopens only the exact pre-sealed registries, and validates every role, equivalence group, and proof-obligation mapping.
7. S6 scores sealed artifacts twice and requires byte-stable independent recomputation of all attribution reports.
8. S7 runs targeted and predecessor regressions, contracts, strict typing, Ruff, real PostgreSQL integration/security on a fresh database, cleanup, architecture validation/lock, privacy scanning, and source/artifact manifest verification.
9. S8 verifies all stage identities and 33 deliverables, projects label-free lifecycle/channel/dedup reports from the sealed product, and seals one honest terminal disposition.

## Failure reflection and repair

On failure:

1. Preserve the failed receipt, traces, partial artifacts, logs, and run identity. Append one unique record to `var/dg24/failure-index.jsonl`.
2. Identify the first authoritative failing boundary and reproduce it once. Do not let later aggregate passes erase it.
3. Extract the general invariant that failed, such as official-cap ownership, payload/attestation separation, semantic-vs-timing digest ownership, or product/probe plane separation.
4. Make one narrow instrumentation or audit-harness repair. Do not change retrieval rules, Top-k, channels, seeds, label mappings, product behavior, public/database schemas, or canonical state.
5. Add a synthetic, contract, property, or failure-injection test that detects the mechanism independent of the triggering case.
6. Use a fresh run ID. Never retry automatically or overwrite the failed namespace.

If the same blocking condition remains after the bounded diagnosis and repair cycle, publish the applicable predeclared PARKED or safety disposition rather than manufacturing a pass.

## PostgreSQL and security verification

S7 creates a fresh ephemeral database with separate owner, API, steward, worker, and audit roles, runs the repository integration and security suites, and drops the database in a `finally` path. The receipt must show that the database was configured, tests actually ran, cleanup passed, the audit role stayed read-only, cross-tenant/wrong-scope/revoked/unreadable evidence failed closed, official FTS/dense/temporal paths were exercised, and no canonical/outbox/watermark mutation was introduced by DG-24.

Credentials, database names, raw connection strings, and secrets must not be written to audit artifacts. Only a one-way database-name digest is retained.

## Verification and rollback

Verify every `{path, sha256, size}` identity before accepting S8. Verify the S0 transitive closure against current bytes, separately classify expected probe/evaluation-only source supersession, and require the frozen architecture manifest digest and release lock.

Rollback requires no migration or data rewrite: keep the audit observer and candidate disabled, stop producing optional traces, retain append-only audit evidence, and continue through the existing product path. Do not delete failed artifacts or alter earlier DG20–DG23 receipts.

## Successor boundary

Use `SuccessorRoutingReportV01` only to preregister a later hypothesis. A later treatment needs its own goal, denominator, safety gates, and formal authorization. DG-24 itself performs no treatment and estimates no causal effect.
