# Compact MCP: content first

中文用户手册：[MiLAi MCP 工具使用文档](mcp-user-guide.zh-CN.md)，包含全部 8 工具的参数示例和常见错误处理。

Current OAuth scope profile: eight tools / nine branch-specific scopes; client request,
enabled scopes and active resource metadata were aligned on 2026-09-09. See the
[alignment receipt](../releases/MCP_COMPACT_SCOPE_ALIGNMENT_20260909.md).
Existing user tokens still need actual consent for missing scopes; tool count is not scope count.

MCP 0.1.15 compact was deployed to public OAuth 7960 on 2026-09-08 after explicit
user authorization; target Host protocol acceptance is complete. See the
[final acceptance audit](../releases/MCP_0.1.15_FINAL_ACCEPTANCE_20260908.md) and the
[deployment receipt](../releases/MCP_0.1.15_OAUTH_DEPLOYMENT_20260908.md).
Do not infer client directory refresh from server rollout. Select exactly one catalog:

```sh
milai-codex-full-mcp --host 127.0.0.1 --port 7337 --catalog compact-memory-v1
```

Retain the existing trusted Runtime/OAuth environment; this example does not create
credentials or authorize a public listener. Use `ordinary-memory-v1` for advanced
Proposal/Review/diagnostics (22 tools), or `legacy` for the old 13-tool interface.
Compact exposes at most 8, filtered by current scopes; a shared tool still checks
the selected action's original permission. See [the contract and mapping](../../contracts/mcp/compact-memory-v1.md).

## Save and read

For an authorized ordinary note, call `milai_memory_save` with two required fields:

```json
{"content":"Synthetic project: verify the red filter before enabling tracking.","operation_id":"a-fresh-operation-id"}
```

This is an example, not a requested write. There is no automatic conversation capture,
mandatory GET after save, Evidence conversion or approval. Read the returned
`read_tool`/`read_arguments` when details are needed. To edit, use the same save tool:

```json
{"content":"Replacement full body","operation_id":"a-fresh-edit-id","options":{"action":"UPDATE_NOTE","memory_id":"00000000-0000-4000-8000-000000000099","expected_version":1}}
```

Use the actual returned ID and current version. Omitted metadata stays unchanged;
empty arrays clear it. A conflict requires reading and rebasing, never increasing a
version blindly. Unknown Note commits use `milai_memory_status` with
`target={kind: NOTE_WRITE, operation_id: original-id}`. An absent receipt does not
prove an in-flight write failed. Preserve identical input for controlled replay.

For source observations, explicitly choose CAPTURE_EVIDENCE with source_type,
source_ref, subject_id, observed_at and confirmation=CAPTURE as required by Schema.
Do not invent source timestamps, quotes or authorization. Evidence is immutable;
there is no UPDATE_EVIDENCE or independent capture-status branch.

## New-session discovery

Start `milai_memory_search` with the current question, optionally one short literal
`note_query`. The new session need not receive old IDs, cursors or history. Inspect
both source statuses, then call returned `milai_memory_read` typed references.
For long Notes, pin the returned version and follow `next_offset`; source_refs use
`next_source_offset` separately. Continue Note inventory with memory_list, identical
selection/query and cursor. Governed continuation uses previous_context_id.

MISS is only a bounded result, not proof of no history. Differentiate no permission,
unavailability, timeouts and empty results. A targeted follow-up or one small browse
page may help; do not automatically list 50 or expand queries. Storage time is not
event time. Working State is a separate scoped checkpoint, not searchable history;
recover the same scope and revalidate the fallible checkpoint before action.

## Delete and maintain

`milai_memory_delete` needs explicit current intent. NOTE requires ID, current version
and DELETE; all versions become unreadable, history remains, physical deletion is
unsupported. EVIDENCE requires ID, reason_code and REVOKE; source eligibility blocks
synchronously while physical purge/backup stages remain separate. Inspect those via
memory_status target EVIDENCE_DELETION, not a fabricated capture receipt.

No namespace wipe or canonical Claim mutation is exposed here. An advanced catalog
is not a workaround for Host refusal or absent user authorization. Notes referencing
revoked Evidence remain subject to current source eligibility, even at old versions.

## Deployment and rollback boundary

After separate authorization, install the hash-checked 0.1.15 delivery in a new pinned
venv, verify its actual initialize/tools/list, then change only the chosen service's
executable and catalog. Preserve issuer, resource, identity, project, scopes and data.
Refresh the actual client directory; old cached aliases are rejected by compact.
Rollback selects ordinary or restores the pinned 0.1.14 executable. No table deletion,
memory migration, grant change or database restore is required. Real-user Host and
synthetic-object cold-recovery acceptance remain separate from local engineering.

No local or paid model requests are authorized by this runbook. UTF-8 byte savings
are not tokenizer counts or evidence of model selection quality or long-term benefit.
