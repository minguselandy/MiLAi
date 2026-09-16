# MCP 0.1.14 — Host-first descriptions

Authorized target: `https://milai.aigcit.com:7960/mcp`, `milai-aigcit.service` only.
Candidate MCP 0.1.14 / client 0.1.3 / shared Runtime 0.1.4.

This release fills initialize serverInfo.title/description and supplies human-readable
titles and purpose-first descriptions across all profiles. It explains explicit Host
submission, no automatic conversation ingestion, authority differences and expirable
checkpoints. Tool descriptions retain authorization, retry and deletion boundaries.
See [the full inventory](../runbooks/mcp-host-descriptions.md).

Ordinary remains 22 tools. Tool IDs, input schemas, risk annotations, permissions,
OAuth identities/grants, storage and Canonical behavior are unchanged. No migration
or Runtime restart is needed. Do not change the separate 7968 legacy service.

Install into a new pinned venv with `/opt/milai-aigcit/python/bin/python3.11`.
Verify under the existing unprivileged service account before switching, retaining
ProtectHome and all environment/binding settings. Rollback restores intact 0.1.13
without touching user data. Protocol metadata tests do not establish remote Host UI
rendering or real Agent cross-session acceptance. No model or public memory mutation
is part of this rollout. The existing external OAuth revocation metadata gap remains.

Exact checks, installed version and deployment outcome belong in the separate
0.1.14 deployment receipt; this handoff alone does not assert a completed rollout.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.
