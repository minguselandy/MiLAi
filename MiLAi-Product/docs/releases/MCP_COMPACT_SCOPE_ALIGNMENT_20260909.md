# Compact OAuth tool/scope alignment — 2026-09-09

Status: DEPLOYED_8_TOOLS_9_SCOPES; REAL_CLIENT_REAUTHORIZATION_PENDING.
User requested aligning scopes with the deployed tools. This is a configuration-only
change on the existing OAuth 7960 resource, not a new MCP package or rewritten grant.

## Scope contract

The union of all supported branches of compact-memory-v1 is nine existing permissions:

| Public tool | Scope for each supported branch |
| --- | --- |
| milai_memory_save | NOTE add/update: milai.note.write; EVIDENCE capture: milai.evidence.capture |
| milai_memory_search | Note source: milai.note.read; governed source: milai.memory.read |
| milai_memory_read | NOTE: milai.note.read; EVIDENCE: milai.evidence.read; CLAIM: milai.memory.read |
| milai_memory_list | NOTE: milai.note.read; EVIDENCE: milai.evidence.read |
| milai_memory_delete | NOTE: milai.note.delete; EVIDENCE: milai.evidence.revoke |
| milai_memory_status | NOTE_WRITE: milai.note.read; EVIDENCE_DELETION: milai.memory.read |
| milai_working_state_get | milai.state.read |
| milai_working_state_update | milai.state.write |

Excluded from this resource profile: milai.proposal.create, milai.proposal.review,
milai.operations.admin. Advanced/legacy catalog definitions and their separate examples
are retained. No scope rename, branch merging, privilege escalation, identity or database
change. Tool visibility may require any branch; execution still requires the selected
branch's permission. See ADR-055 and the compact contract.

## Actual deployment

At 09:34:45 Asia/Shanghai, only `milai-aigcit.service` restarted from PID 3839065 to
2115981. Same pinned MCP 0.1.15 wheel/venv and `--catalog compact-memory-v1`, backend
127.0.0.1:7969, public resource `https://milai.aigcit.com:7960/mcp`.

Added files (old configuration preserved):

- `/etc/milai-aigcit/compact-scopes.env`: nine scopes only.
- `/etc/systemd/system/milai-aigcit.service.d/zzzzzzz-compact-scopes.conf`: final EnvironmentFile override.
- `/opt/milai-aigcit/releases/compact-scopes-20260909/`: before/after verifier receipts and rollback script.

After confirming public metadata showed exactly nine scopes, refreshed only this resource
with the existing Auth `/resources/register` contract. HTTP 200 response reported ACTIVE,
the nine expected scopes and applied_within_seconds=10. Independent `/resources/status`
lookup then confirmed exact resource, active=true, status=active and the same nine scopes.
No user grant, credential, other resource registration or namespace was edited.

Read-only `verify_scope_alignment.py after` confirmed:

- enabled scopes = public metadata scopes = active Auth resource scopes = exact nine.
- public and local 7969/7968 health/readiness all 200; missing/invalid Bearer both 401
  with the correct resource-metadata challenge.
- Other MILAI environment values and binding-file SHA-256 unchanged; launch argv unchanged.
- API PID 3328692, worker PID 3328694 and legacy 7968 PID 3328695 unchanged.

The first preflight draft named the wrong legacy unit (PID 0); it is retained as
before-draft.json. The unit was corrected using the actual listener process's cgroup,
and before.json was regenerated before any deployment mutation. After comparison uses
that corrected baseline. No old user-memory record was read, rewritten or deleted.

## Source examples and checks

Updated AIGCIT and private-workflow client/environment/service/proxy examples, the reauthorization script,
runbook and compact contract. The old script incorrectly promised 22 tools and requested
12 scopes; it now requests the compact nine and expects eight tools only if actually granted.
Paired service/proxy examples now both use backend 7969, avoiding the separate legacy port.
The user's separate client machine/configuration was not edited remotely.
The private-workflow sample also contained the old eight-scope request and redundant
oauth_resource; its current endpoint settings now match the compact sample. The ordinary
sample retains its historical profile with an explicit warning that 7960 is now compact.

OpenAI Docs was used for client guidance: server-advertised scopes may take precedence
over configured fallback scopes, so metadata alignment and explicit requested scopes
must be checked, not just the existence of a config entry.
[Official MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

Tests (integrations/mcp):

- `uv run --locked pytest -q tests/test_compact_scope_profile.py`: 2 passed in 2.18s.
- `uv run --locked pytest -q`: 385 passed / 7 conditional skips in 32.31s.
- `uv run --locked ruff check src tests`: passed after two long test lines were fixed.
- `uv run --locked mypy`: passed, 21 source files.
- Installed unprivileged 0.1.15 CLI with nine-scope environment: eight registered tools,
  exact release metadata, missing identity denied; no listener or fabricated login.
- `systemd-analyze verify` and `sh -n rollback.sh`: passed.

Tests derive the nine-scope union from real facade alternatives and private backend
permissions, compare examples and exercise signed nine-scope vs old eight-scope grants.
The old grant remains restricted; the change does not create permissions in an old token.
Independent authorized subagent identified the initial service/proxy example mismatch;
both ports and a pairing regression assertion were corrected before handoff.
The independent reviewer then rechecked the live final drop-in, PID, nine-scope agreement
and unchanged configuration boundaries and reported no remaining deployment blocker.
No Runtime/MCP implementation or wheel changed, so no rebuild, migration or fresh PG
run was needed. Released 0.1.15 archive and embedded historical examples were not overwritten.

## Client follow-up and rollback

Server alignment is complete; user consent/token result is not yet verified. Use the
updated client example and reauthorization script on the actual client machine. The
script resets only its named saved MCP authorization; it was not run by this agent.
Restart the old client process and check granted/effective scopes, eight visible tools
including memory_list and a legal Note read. Do not send tokens or cookies for diagnosis.
An old legacy eight-scope token intersects the new profile at only five scopes; it may
still see seven tools and must not be misreported as fixed merely because login succeeds.

Rollback: run the scoped `rollback.sh` only when authorized. It disables only the new
drop-in, restarts the same pinned service and refreshes the exact resource registration
from the restored metadata; verify ACTIVE and the previous 12-scope set. This does not
restore user grants or touch data. Script syntax checked; live rollback not exercised.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.
