# MCP 0.1.11 calling contract

Local candidate: MCP 0.1.11 / client 0.1.3 / Runtime 0.1.4. The ordinary catalog
still registers 23 tools; legacy still registers 13. Migration remains 0056.
No new authority, grants, automatic governance or model execution is introduced.

Working State get, save and recovery guidance preserve SESSION/TASK/PROJECT.
TASK is the default. SESSION refers to the trusted current session binding and
cannot promise recovery in an arbitrary new session. Ordinary lifecycle guidance
applies when the task or enabled Host workflow needs the checkpoint.

Proposal uses the nine existing operations. CREATE needs a complete canonical
envelope and supporting Evidence; the six other version operations need support
and exact target/head UUIDs. CONTRADICT needs contradicting Evidence; NO_CHANGE
does not invent an evidence requirement. References are UUIDs, unique, disjoint
between branches and bounded to 256 each. OpenIssue resolution requires SUPERSEDE
and resolve_issue_id, expected_issue_revision and addressed_branches together.
Payload remains business JSON. Authority and scope remain Host-owned.

Both Codex catalogs expand generated local Proposal schema references at
tools/list serialization only. 0.1.10 applied this only to ordinary; 0.1.11 also
covers the legacy catalog used by the current Codex connection. Legacy retains
its 13 names and text error format. Both catalogs use the same input model and
runtime checks. See the shipped synthetic examples;
they are executable input envelopes, never authorization to submit or approve.
Host interpretation of conditional schema constraints still needs verification.

Ordinary Note/State backend errors add `error_contract=ordinary-memory-errors-v1`.
MCP `isError=true` is preserved. Existing Note JSON code/fields remain; additional
recovery fields are additive. The SDK's ToolError wrapper can prefix text with
`Error executing tool <name>: `; consumers parse the JSON after that prefix.
Legacy State errors retain their existing text/code format. Do not assume every
MCP error is JSON: authentication and top-level argument guards retain their
existing formats. No backend details object is copied wholesale.

| Failure | Recovery |
| --- | --- |
| INVALID_REQUEST / INVALID_ARGUMENT | CORRECT_INPUT; inspect safe fields path/type/expected |
| STALE_WORKING_STATE / STALE_NOTE | READ_AND_REBASE in the same scope/object; do not only raise expected_version |
| OPERATION_CONFLICT | Reconcile the original request; changed payload needs a new ID after that decision |
| NOTE_OUTCOME_UNKNOWN / WORKING_STATE_OUTCOME_UNKNOWN | Reconcile original operation or controlled identical replay; never assume the write failed |
| Read unavailable/denied | Preserve unavailable/denied; never infer ABSENT, MISS or empty history |

`retryable=false` prohibits a generic automatic retry, not a later informed edit.
client 0.1.3 disables automatic State write retries even when read retries are
configured. Note writes already had that behavior. Only exact-object, bound
Runtime CAS responses can supply current_version; it remains an observation.
Note stale errors require GET because their backend does not supply a version.
Working State has no standalone operation lookup tool. GET only observes current
state; neither it nor a missing Note receipt disproves an in-flight commit.

Existing guidance keys remain. Action hints are marked optional; governance or
deletion suggestions state requires_user_authorization=true. This flag records
a requirement, never an authorization decision. Ordinary Note/State writes do
not acquire a separate governance confirmation step.

Note delete/get/replay/operation receipts consistently expose
physical_deletion_supported=false. Logical deletion blocks all Note versions;
history remains, primary_storage=NOT_IMPLEMENTED, backup_expiry=NOT_SCHEDULED.
Shared Evidence is not revoked. Cleanup submission and status remain admin-scope
tools; list filtering and dispatch both enforce effective scopes. Request only
needed scopes for ordinary integrations. Do not change existing grants to test
visibility, and do not invoke public cleanup to diagnose Host refusals.

Package rollback keeps the database, identities, grants and audit history. This
increment adds no migration; never restore an old database over new user writes.
Public deployment and candidate Host schema validation are separate from local
engineering checks. Model experiments and v0.2-07 U5 remain paused/pending.

The inspected Codex connection uses http://36.140.33.19:7968/mcp, backed by
milai-codex-full-public.service (legacy). The separate OAuth endpoint
https://milai.aigcit.com:7960/mcp forwards to milai-aigcit.service on loopback 7969
and uses ordinary-memory-v1. Do not assume upgrading the OAuth service refreshes
the existing Codex connection. Preserve the selected endpoint's principal/task
binding, credentials and catalog; loading new Host definitions is a separate step.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.
