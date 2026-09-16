# MiLAi Host Cognitive Affordance implementation audit

> Timestamp: `2026-09-04 10:53:41 +08:00`  
> Terminal: `PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE`  
> Schema: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Delivered

- ADR-034 and `host-cognitive-state-v1` freeze `HOST_WORKING` as a non-Canonical,
  non-Evidence, non-continuation authority plane.
- Migration `0050_host_cognitive_state` provides one bound head, immutable version/reference
  history, exact CAS, operation-ID replay protection, Runtime-owned TTL, tenant/actor RLS and
  exact live Evidence-pointer validation.
- Runtime exposes internal `/v1/working-state/get` and `/v1/working-state/update`; the typed Python
  client wraps both.
- The single `codex-full` Streamable HTTP endpoint exposes `milai_working_state_get` and
  `milai_working_state_update`, bringing the exact catalog to 13 tools. Project, principal and
  scope reference remain server-owned.
- Access and append audit is automatic by default. Audit rows contain identity/digest/count
  metadata and never the Host JSON payload.
- Backup inventory, current-head documentation, Codex example and HTTP MCP runbook include the new
  plane.

## Verified gates

```text
Runtime Ruff                              PASS
Runtime mypy (178 source files)           PASS
Host domain/migration unit tests          5 passed
Focused real PostgreSQL security test     1 passed
Migration/backup compatibility subset     6 passed
Runtime fresh-DB gate                      900 passed, 1 skipped, 5 deselected
Python Client full                         171 passed; Ruff/mypy/build PASS
MCP full                                   74 passed; Ruff/mypy/build PASS
Runtime build                              PASS
clean wheel install/import                 PASS
frozen architecture validate/lock          PASS
Product/Lab import boundary                PASS
```

The real HTTP chain was also executed with temporary PostgreSQL, Runtime and Streamable HTTP MCP:

```text
TASK get                                   ABSENT
TASK create                                version 1
TASK CAS update                            version 2
TASK get                                   ACTIVE / version 2
authority                                  HOST_WORKING
version rows                               2
automatic append audit events              2
automatic access audit events              2
```

The temporary service, container and database volume were removed after the run.

## Security outcomes

```text
cross-project update                       typed 403
cross-tenant visibility                    0
cross-actor visibility                     0
stale CAS                                  typed 409
operation ID / different payload           typed 409
revoked Evidence on new write              rejected
later-revoked Evidence on read              warning; payload not rewritten
history UPDATE/DELETE                       rejected, including owner
API direct head UPDATE                      denied
Audit-role payload read                     denied
recall-side working-state mutation          0 by construction
working-state direct Canonical write        0 by construction
```

Schema 0.1.x permits an explicit Alembic downgrade for compatibility testing. It is intentionally
destructive for Host working state and its idempotency rows, retains operational audit events, and
requires a verified backup when state may exist. Normal deployment rollback disables the two tools
without downgrading.

## Existing retrieval gate drift

Five retrieval assertions in the already-dirty Product retrieval surface reproduce on a fresh
database independently of the Host state tables: Formation canary selection, QueryPlan token
redaction, query-first HIT readiness, candidate-cap expectation, and DG-11 compare readiness. They
were not changed to make this delivery green. The 900-test fresh-DB gate deselected exactly those
five and kept every other Runtime test. They remain separate retrieval/Product-11 work, not evidence
against the Host cognitive persistence contract.

## Honest remaining gate

HC-4 is not complete. A PASS usability claim requires 10–20 genuine, consecutive coding tasks that
measure cross-session resume, failed-approach recovery, decision recovery, memory-need resolution,
CAS correction and governed promotion. Product-11's retrieval mechanism is currently blocked on
human adjudication, so this audit does not conflate code availability with empirical Codex benefit.

