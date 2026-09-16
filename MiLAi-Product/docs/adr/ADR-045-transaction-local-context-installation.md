# ADR-045: Install transaction-local tenant and actor in one statement

Status: Accepted implementation candidate; Schema remains NO-GO FOR SCHEMA FREEZE.
Date: 2026-09-07

## Context

Every governed Database.connection installs tenant and actor before yielding the connection.
The original two SELECT statements add two round trips per scoped transaction. Retained v0.2
resolve traces show seven transactions per ordinary query, with connection hold time expanding
under concurrency. Those timings include Python scheduling and do not isolate PostgreSQL cost.

## Decision

After the existing per-transaction least-privilege role attestation, issue one parameterized
SELECT containing both set_config calls. Both retain is_local=true. The expressions have no
dependency on one another; neither result is consumed. No caller receives the connection until
the complete statement succeeds. An error still exits and rolls back the same transaction.

Transaction characteristics remain before role attestation. Statement timeout remains a
separate setting after context installation. No role check is cached, removed or merged into
the context statement; no tenant/actor value is stored on the pooled connection outside the
transaction. Isolation levels, read-only behavior, role identity, RLS, retry, CAS and commit
semantics are unchanged. There is no migration or new public API.

## Verification and limits

Real PostgreSQL controls must exercise success, body error and cancellation, pool reuse with a
different tenant/actor, absence of leaked local settings, and role rejection before yield.
Existing role/RLS and full runtime regressions remain required. Service timing must be measured
separately; saving one round trip does not establish a concurrency or latency SLO.

The implementation was checked with four real PostgreSQL controls (three transaction outcomes
and per-transaction role rejection), 16 adjacent controls, and 1038 full runtime checks without
skips. Public scoped recall preserved source inputs and the normalized first response; c1 met
the 300ms gate, while c8 P95 was 1306.270ms and stopped further rounds. Full P1 remains unmet.

Rollback is the source-only restoration of two parameterized SELECTs. No persisted business
data or schema needs conversion. Do not merge role attestation with context installation or
reuse one transaction across application phases on the strength of this decision.
