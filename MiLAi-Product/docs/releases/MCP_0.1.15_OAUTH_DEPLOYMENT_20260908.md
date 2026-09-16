# V02-09 / MCP 0.1.15 compact deployment and acceptance audit

Status: COMPLETED_COMPACT_MCP_USABLE. See the
[final acceptance audit](MCP_0.1.15_FINAL_ACCEPTANCE_20260908.md): raw client receipts
independently pass 12/12, complete tool metadata matches, and deployed-service journal
correlation supports the target connection. Protocol scope only, not model acceptance.
All pending/missing-evidence statements below are retained pre-closeout history.

Latest maintenance evidence (user-reported): synthetic project 海岚文档站模拟项目-32cad4,
12/12 checks, four independent temporary sessions/client processes, eight MCP calls.
A saved project constraints/state; B received only a question and literal project-name
note_query, searched and read version 1 through the returned reference. C updated with
expected_version=1 to version 2, checked the write receipt and read historical version 1.
D searched in a new session and read version 2. The described call count is consistent
(1+2+3+2=8), not independently verified from a trace. Note
`01196ccf-2c95-48f9-8ef2-fea028db06a5` remains ACTIVE and is not to be deleted here.
The reported recovered project state is preserved in the Goal; all changes are synthetic.
Note retrieval was literal, governed retrieval returned MISS, and no independent model
round ran. No automatic recall, semantic retrieval, autonomous decision, conflict rejection
or public deletion acceptance is inferred.

The report supplies a maintenance chain, so it is no longer missing. Raw `results.jsonl`,
`verification.json`, A–D plan files and A–D session files have only been named, not supplied.
Final audit still needs their actual connection metadata (this report does not repeat the
endpoint), session boundaries, version/receipt data and twelve assertions. The Goal remains
incomplete pending that evidence review. Public deletion is not an additional mandatory
step for this update-maintenance chain: C3 retains the separate conflict/deletion engineering
gates. Earlier requests for a full public destructive test were overly restrictive and are
superseded; neither retained Note needs to be changed. No code or deployment change here.

Latest public cross-session evidence (user-reported): 8/8 client checks passed against
`https://milai.aigcit.com:7960/mcp`, with the eight-tool catalog and the same authorized
identity/memory space. Session A `01a08113-829d-7812-bc3c-bb0db889c4dc` (PID 1108)
closed after save returned COMMITTED and durable=true. Fresh session B
`01a08114-2596-7152-b145-a655a24bb1c1` (PID 27532) received only query marker
`cross-session-v8-e92c2de86fb6`, searched and read the returned typed reference.
The user reports exact original text, without passing the old conversation, Note ID or cursor.
Note `fe755cf8-4d90-4f8d-9411-4e48b2212126`, version 1, ACTIVE, is explicitly retained;
this documentation update does not modify or delete it.

The agent independently hashed the supplied synthetic body (UTF-8, no trailing newline),
matching `07b5568edf52e1f2674f694cdcf608ad31fd8c7224fa97867264698454a0236b`.
The body is preserved in the Goal's latest update. This validates the pasted text/digest
pair, not the server response itself. Named raw files `results.jsonl`, `verification.json`,
`A-plan.json` and `B-plan.json` have not been supplied or directly audited here.
The accepted user report covers cross-process Note persistence, literal search and reference
read. It does not establish real-model recall/use, semantic search, cross-account isolation
or public server restart recovery. No model round, deletion or namespace cleanup was run.
Target-client maintenance acceptance remains pending; a model pilot is not required for
this protocol gate. No code, service or business data changed in this evidence update.
Earlier cold-flow-pending statements below describe the state before this report.

Subsequent full client export check: the user pasted the entire milai-standard-test
8-tool JSON. An independent transcription, structural comparison and jq -S/cmp
normalization against this release found no differences in name/title/description,
inputSchema, outputSchema or annotations. Authorized subagent host_schema_audit
independently compared the original pasted message and full release definitions,
with the same result. The metadata-contract portion of target Host acceptance now
has supplied-client-export evidence; no further tools JSON upload is required.

Evidence directory: `MiLAi-Lab/artifacts/v0209-host-schema-gMLtlCew/`, including
PROVENANCE.md. Both normalized tool-map files have SHA-256
`63fd97fd3fb33402e1cf6aebac277b48bcbfbfe6fa293cc2408eb237c7c33e9a`.
These hashes describe normalized pasted/transcribed metadata, not the unavailable
original Windows file bytes. Wrapper name, tools map/order, resources and authStatus
are not server initialize fields. Open Working State payload/output object schemas
match design and are not a claim of fully fixed business output fields. No new
business calls, token verification or cold-use evidence was supplied. Earlier
missing-export statements below remain dated history; only the cold-flow/maintenance
and unsupplied initialize/visual evidence remain unproven by this export.

Latest target-client evidence: the user reports reconnecting to the exact public OAuth
endpoint successfully and receiving all eight compact tool names, matching the release
snapshot. This is user-confirmed client directory refresh, not an agent-observed login.
The user saved the full tools/Schema export at
`C:/Users/Mingx/Documents/ChatGPT/test/milai-test-results/latest-tools.json`; it has not
been attached or inspected in this workspace. Exact client Schema fidelity remains
unverified. The user explicitly performed no writes/deletes, so the target-client
cross-session save/search/read/use/maintenance gate remains pending. Earlier statements
below that no target directory evidence existed record the pre-confirmation state.

The user first authorized executing V02-09, then explicitly authorized operations and
subagent audit. The latter authorizes the selected public switch and synthetic acceptance,
not arbitrary user-memory changes, fabricated identity, or a model pilot.

## Outcome and unchanged boundaries

At **2026-09-08 20:35:24 Asia/Shanghai**, `milai-aigcit.service` switched to the final
MCP 0.1.15 package and `--catalog compact-memory-v1`. Public address remains
`https://milai.aigcit.com:7960/mcp`; active PID 3839065, NRestarts 0.
Public registration contains 8 tools; visibility is filtered by existing scopes:

```text
milai_memory_search   milai_memory_read   milai_memory_list
milai_memory_save     milai_memory_delete milai_memory_status
milai_working_state_get                  milai_working_state_update
```

Default save creates a Note using content + operation_id. Shared finite typed branches
retain Note/Evidence/Claim differences, exact action scopes, CAS and original operation-ID
namespacing. Old names are not publicly dispatchable in compact. Ordinary 22 and legacy 13
remain separate selectable catalogs; no tool layering or new scopes. No database migration,
permission, identity, canonical transaction, automatic maintenance or retrieval algorithm
change. Runtime 0.1.4 and SDK 0.1.3 wheels match the prior deployed delivery byte-for-byte.

Two integration defects were fixed: the private search manager's raised Note error now
uses the same safe source-status classification as returned errors; incomplete Evidence
read/list error wrappers now defer to the typed client cause and produce complete recovery
metadata. There is no added retry, source-text disclosure or Evidence capture-status API.

## Requirement-by-requirement evidence

| Gate | Evidence and disposition |
| --- | --- |
| C0 / U01 | ADR-054, compact contract/mapping and generated release snapshot. Signed initialize/tools/list checks all 3 catalogs and every individual scope: maximum 8 vs ordinary 22 / legacy 13. No scope removed to manufacture savings. |
| C1 / U02–U04 | `test_compact_memory.py`: each Note/Evidence/Claim branch including UPDATE_NOTE checks original scopes before backend call; all old/admin names denied; typed defaults/CAS/confirmation/source and unsupported fields tested. |
| C2 / U05 | Signed protocol save/list/search references are callable typed NOTE/EVIDENCE/CLAIM reads. Added explicit Host content/source_refs/embedded Claim payload fidelity, including tool-shaped data. Claim discovery/read routing uses protocol fixtures, not a new canonical PG scenario. |
| C2 / U12 source state | Search regressions cover independent scopes, MISS vs failure, timeout/cancellation, and no retry. Compact-specific Note unavailable and Evidence read/list unavailable cases pass with safe classification/recovery. No semantic recall or exhaustive history claim. |
| C3 / U06 | Real PG plus HTTP cut before forwarding/after commit, single write attempt, durable receipts, altered-payload conflict and identical old/new catalog replay for Note/Evidence. Same Note CAS competition yields one winner, not silent overwrite. |
| C3 / U07 | Client A process saves; after listener/Runtime restart, B process receives only question/literal hint and legal identity. B discovers references then pins version and pages full original body; no old ID/cursor/answer is provided. Checkpoints are separately restored. No real model consumption claim. |
| C3 / U08 | New tokens and concurrent users share listeners but not memory; foreign Note reads denied, same query returns no foreign Note, concurrent independent writes have different IDs. |
| C3 / U09 | Logical Note deletion and Evidence revocation block historical bodies, dependent Notes, search and old receipts/replays, including after restart. Deletion response matches target/request, immediate APPLIED gates and pending physical/backup completion. No actual physical erasure claimed. |
| C3 / U10–U11 | Confirmed save directly readable; receipts/content survive restarted test Runtime/MCP. Independent concurrent read/write and same-version Note competition pass. No new global serialization lock was introduced. SESSION checkpoint test retains the same trusted binding; it is not all-session search proof. |
| C3 / U12 pagination | Real Note and Evidence cursors continue correctly and reject changed identity/filter; text/source pagination are distinct. No cursor treated as identity or permanent snapshot. |
| C4 / local part U13 | Final same wheel installed independently twice, hashes and all source bytes checked. Installed full suite, signed metadata snapshot, actual unprivileged CLI registration and real PG test pass. |
| C5 / target part U13 | Public switch/auth checks and supplied client metadata comparison pass. User reports prior 8/8 cold-read checks and subsequent 12/12 four-session save→search/read v1→update/receipt/history→search/read v2 checks. **Maintenance is user-reported; raw connection/session/call/check evidence remains unaudited.** No model-use, semantic-search, cross-account or public deletion claim. |

## Commands and results

From `integrations/mcp`: `uv lock --offline`; `uv run --locked ruff check src tests`;
`uv run --locked mypy`; `uv run --locked pytest -q`.
Final: **383 passed / 7 conditional skips in 26.86s**; Ruff passed; mypy 21 files passed.
The skips are not passes. Compact PG is run separately with its required owned environment.

From the same directory, final independent test install:
`/tmp/milai-v0209-clean-install-FBJBPDhp/final-venv/bin/python -m pytest -q`:
**383 passed / 7 conditional skips in 26.76s**.
Only this test install adds pytest 8.4.2; deployed venv contains no extra test dependency.

Final installed-package PG invocation:
`python3 /tmp/milai_v0209_owned_pg.py /tmp/milai-v0209-clean-install-FBJBPDhp/final-venv/bin/python`.
The orchestrator supplies a newly created, labelled, loopback-only pgvector PG16 container,
five independent roles, random database and synthetic content. It invokes installed Python
pytest on `tests/test_compact_memory_postgres.py`, with `MILAI_MCP_COMPACT_E2E=1`.
**1 passed in 10.84s**. Runtime embedding is deterministic local hashing, not a model call.

Final trace and cleanup receipts: `MiLAi-Lab/artifacts/v0209-75212b48032e6031/`.
Runtime PIDs 3835214 / 3835540; fresh clients 3835458 / 3835577 / 3835673.
Owned container 21432e4c803d2f4eed650b414edda901f3e527daa5a9aca7eae9062b060f666e
was removed after label verification; its synthetic PG storage was tmpfs. The test drops
only its random database and stops only its created processes. Logs/blobs remain as local
synthetic evidence. Existing experiment/public services and data were not cleaned.

Earlier successful local/installed candidates: artifacts `v0209-40f277f9d86922f0`,
`v0209-10a97beb67334314`, `v0209-144b8f38a6524a44`, `v0209-99f8045978d26678`.
One orchestrator attempt `v0209-db6ac02a4bdb07e7` ran before test dependency installation
finished and did not enter pytest; failure and cleanup were retained, preflight added,
and an explicit new run passed. Initial lint and missing exporter test-client setup were
corrected before gates; the focused unavailable-status regression failed before its fix.

## Independent review

User-authorized subagent `/root/compact_audit` read Goal/ADR, registration, scopes,
private dispatch, schemas, errors, reference adaptation and tests. It found no security
deployment blocker, but identified incomplete Evidence recovery and a weak deletion-stage
assertion. Both were fixed and independently rechecked. Final narrow independent command:
`.venv/bin/pytest -q tests/test_compact_memory.py -k 'evidence_unavailability or recovery_uses or search_reports_note'`:
5 passed / 23 deselected in 1.38s. Reviewer made no edits or service/data changes.
This is separately authorized code review, not a backend/model pilot, user login or Host test.

## Cost and usability measurements

Generated snapshot: `contracts/mcp/compact-memory-v1.release-0.1.15.tools.json`.
Exporter uses actual signed local protocol calls and the same JSON serialization:
ensure_ascii=false, sort_keys=true, separators=(',', ':'). All per-scope tool names are
recorded in the snapshot, not only full-scope counts.

| Catalog | Full-scope tools | tools/list UTF-8 bytes | instructions UTF-8 bytes | initialize result bytes |
| --- | ---: | ---: | ---: | ---: |
| legacy | 13 | 19,983 | 466 | 1,097 |
| ordinary-memory-v1 | 22 | 34,397 | 1,794 | 2,425 |
| compact-memory-v1 | 8 | 17,806 | 1,522 | 2,153 |

Tool-list byte reduction is about 48.2%; no tokenizer was run, so no token saving or
model-selection improvement is claimed. Default Note save has 2 required fields and
1 product call; verification GETs are test cost, not mandatory product overhead.
The final PG report records 58 parent helper calls including 9 expected/observed errors,
119,902 response bytes, end-to-end p50 49.82ms / max 78.68ms; 78 Runtime timing samples
have application p50 3.207ms / max 66.366ms. These populations differ: native clients,
CAS race and extra internal/health requests are not all parent helper calls. Do not turn
them into an overall net-cost score or a synchronized old/new speed benchmark. No model
pilot, external embedding request, autonomous summary or maintenance was run. A0 retained.

## Final package, installation and public checks

Final archive: `integrations/mcp/dist/delivery/v0209-final/milai-mcp-delivery-0.1.15.tar.gz`.
Archive SHA-256: `18344e991596de27c8033b8a5ebb69de235ea98bfee0f0008061900d5fd49b41`.
MCP wheel SHA-256: `ee24607e0f365468a7ace818bb66718cc397bfaba33f8d6db22dd7ef2f61ae7b`.
All 48 manifest entries and sidecar passed; all 22 source files match both installed
copies and the wheel. Earlier pre-audit same-version archive is preserved under the
parent delivery directory but is **not** the final deployed artifact.
Embedded status docs reflect pre-switch build time; this receipt supersedes those
status statements without rewriting the released archive.

Built with `sh tools/build_mcp_delivery.sh integrations/mcp/dist/delivery/v0209-final`.
Release root `/opt/milai-aigcit/releases/product-v0209-0.1.15`.

```sh
MILAI_INSTALL_PYTHON=/opt/milai-aigcit/python/bin/python3.11 sh /opt/milai-aigcit/releases/product-v0209-0.1.15/milai-mcp-delivery-0.1.15/install.sh /opt/milai-aigcit/releases/product-v0209-0.1.15/oauth-mcp-venv mcp
systemd-analyze verify /etc/systemd/system/milai-aigcit.service
systemctl daemon-reload
systemctl restart milai-aigcit.service
```

Only new override `zzzzzz-compact-0.1.15.conf` was added. Existing unit/drop-ins are
preserved in the release's mode-0700 rollback directory. User/Group milai-mcp and
ProtectHome stay unchanged. Unprivileged installed `verify_oauth.py preflight` verifies
exact 8-tool schemas/titles/descriptions/instructions against the signed snapshot and
denies listing without identity; it starts no listener and forges no public user.

`verify_oauth.py before` / `after` receipts verify trusted public health/readiness 200,
missing/invalid Bearer 401 with exact resource challenge, reachable JWKS and active
resource registration. All MILAI environment, both env files, binding file, protected
metadata and 12 scopes are unchanged. Shared API 3328692 / worker 3328694 and legacy
7968 MCP 3328695 stayed active with unchanged PIDs. Probes originate on deployment host.
No public business save, delete, revoke, review or cleanup was performed.

External Auth still omits revocation_endpoint_auth_methods_supported; prior user OAuth
usability confirmation does not prove fresh full refresh/revocation conformance. No
checker or security boundary was weakened. Valid-user OAuth and target Host acceptance
cannot be inferred from health or installed registration checks.

Rollback: `sh /opt/milai-aigcit/releases/product-v0209-0.1.15/rollback_oauth.sh` renames only
the new override to `.disabled`, reloads and restarts pinned 0.1.14 ordinary. `sh -n`
passed; live rollback was not exercised. No table, memory, identity or credential
restoration needed. Refresh client metadata when switching back to the larger catalog.

Remaining required action: use the actual authorized 7960 OAuth Host to refresh its
directory and perform the synthetic save → new conversation with only a question →
search → read → use constraints → maintain/delete loop. No Token need be shared.
Until direct evidence exists, do not mark the Goal COMPLETED_COMPACT_MCP_USABLE.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.
