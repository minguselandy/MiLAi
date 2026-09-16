# MCP 0.1.7 candidate handoff — 2026-09-08

Status: PUBLIC DEPLOYMENT COMPLETED after the user's explicit upgrade instruction;
real-client consent/tool-list verification pending, no new model experiment.
MILA-V02-07 actual Agent-use evidence remains incomplete.

On 2026-09-08 05:08 UTC the approved paired upgrade was deployed at
https://milai.aigcit.com:7960/mcp. Runtime schema is 0056_host_notes;
API/Worker/MCP run from /opt/milai-aigcit/releases/ordinary-v1. Runtime/MCP
readiness passes, and protected-resource metadata, Auth resource status and AS
metadata agree on 12 MiLAi scopes. The full grant intersection exposes the 22-tool
ordinary-memory-v1 catalog. Actual authenticated client listing awaits renewed consent.
Existing identity namespace, issuer, data roots and encryption keys were preserved.
See MCP_0.1.7_PUBLIC_SWITCH_PLAN_20260908.md for backup, failures and rollback details.

The packaged archive was built before deployment, so its original local-candidate
wording describes the build-time state. Its bytes and recorded SHA remain unchanged.

The public capture schema previously concealed Runtime constraints, exact Canonical
reads could report contradictory sufficiency, and users lacked ordinary independent
Note CRUD. This pair repairs capture/CREATE/error contracts and exact binding, adds
versioned noncanonical notes, Evidence full reads/browse and typed read references.

Pair: MCP 0.1.7 + Python client 0.1.2 + Runtime 0.1.2 + migration 0056_host_notes.
Select `--catalog ordinary-memory-v1` on either MCP entrypoint to expose up to 22
authorized tools. Legacy remains the default. New scopes require separate enablement
and consent; old grants do not gain Note or full Evidence capabilities.

The existing engineering slice now uses a real HTTP MCP listener and PostgreSQL,
two signed synthetic subjects and two fresh native MCP protocol client processes.
It cuts actual Runtime HTTP connections before forwarding and after a confirmed
commit, reconciles by the original operation ID, restarts Runtime and the MCP
listener, and recovers exact paged content and durable receipts. These are protocol
clients without a model, not evidence of Agent autonomous selection or reasoning.

The bounded local run records every parent RPC, including expected errors, plus
client concurrency and complete-response P50/P95/P99. Existing Runtime metrics
record database connection acquisition (checkout plus any wait); HTTP pool wait
is not separately instrumented. The fault proxy adds transport overhead; these numbers
are engineering diagnostics, not public latency or capacity claims. Current index
path is direct PG, with no asynchronous Note index to catch up.

0056 introduces independent Note head/version/source-reference tables, forced RLS,
restricted grants and transactional write/operation procedures. Existing Claim and
Working State meaning is unchanged. Empty Note storage can downgrade; nonempty
storage refuses downgrade. Roll back application binaries while retaining data.
The existing backup inventory includes Note tables so migration 0056 does not
break backup creation. Its quiescent single-tenant restriction remains. Restore an
older-schema archive with its matching Runtime before upgrading; this pair's
Note backup check covers schema 0056 and retained logical tombstones.
Notes currently support logical deletion only; physical purge NOT_IMPLEMENTED,
backup expiry NOT_SCHEDULED. No global Note expiry, hidden summary model, dense
retrieval or automatic maintenance was added.

Install from the verified archive into new virtual environments. Installation
does not migrate a database, restart a service or modify authentication. Maintainers
must preserve identity namespace and choose the target database explicitly before
using the packaged Alembic resources. See the included README, contract index and
ADR-051 for compatibility and exact disclosure semantics.

Full Goal completion, Schema freeze, generality and long-term net benefit are not
claimed. Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE /
NO-GO FOR SCHEMA FREEZE.
