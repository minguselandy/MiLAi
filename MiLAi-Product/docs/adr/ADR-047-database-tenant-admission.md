# ADR-047: Optional per-tenant database admission

Status: accepted for experimental development; NO-GO FOR SCHEMA FREEZE.

The real PostgreSQL capacity test reproduced a noisy tenant holding every shared
connection and causing a peer tenant to time out. The bounded global wait queue
alone does not reserve capacity for another tenant.

Add optional `MILAI_DATABASE_POOL_MAX_PER_TENANT` to API and worker settings.
Omitting it preserves existing behavior. When enabled, a Database instance admits
at most that many outstanding acquisitions/held connections for a trusted tenant
UUID. Excess requests fail immediately through the existing safe HTTP 503
`DATABASE_CAPACITY_EXCEEDED`, with reason `TENANT_CONCURRENCY_LIMIT`. There is no
extra waiting queue, automatic retry, semantic classification or persistent entity.

Claim capacity before pool acquisition and release it after connection return on
success, failure or cancellation. The counter mutex never covers SQL or the
request body. Remove idle tenant counters. Different actors/projects within one
tenant cannot evade the cap. Identity comes from SessionContext after the existing
authentication boundary; memory content and caller payload cannot choose it.

This is admission isolation, not general fair scheduling. With two active tenants,
a pool of two and a cap of one leave a slot for each; arbitrary tenant counts do
not gain a universal starvation bound. Unbound internal maintenance and health
operations remain governed by the global pool. Existing separate API, Steward and
worker pools remain separate: limits are per pool/process, not fleet-wide quotas.
Deployment must account for every process and role pool, API threads, global
queue, database server and CPU capacity. No whole-service SLO follows from the
connection mechanism alone.

The current public Runtime binds its configured tenant at authentication; changing
an MCP project or delegated actor does not select another tenant. Direct Product
tests can share a Database between two authenticated app instances to verify this
mechanism. Those tests do not establish a public multi-tenant gateway deployment.

Authentication, RLS, role attestation, CAS, idempotency, statement timeouts and
transaction commit/rollback remain unchanged. Admission failure only describes
this acquisition; a multi-operation request might have committed earlier work.
No migration is required. Rollback disables the optional setting and restores
unpartitioned behavior without touching any data.

Verification: retain the disabled-mode interference reproduction; use real PG for
enabled-mode tenant/actor isolation, excess admission rejection, peer operation,
release after rollback/cancellation, and public State/CAS/replay behavior. Scope
broader fairness and load results separately.
