# MILA-V02-07 execution index

Status: LOCAL_CANDIDATE_PACKAGED_AGENT_VALIDATION_PENDING, 2026-09-08.

Product source: `/cra/memory/mx_memory/MiLAi-Product`, dirty worktree based on
`1b5e4a7122da2b38b9a57bba143215cc0afa3387`. The Git commit alone does not identify
the current implementation. Product ADR-051 records the Note storage decision.
No model requests or public mutations/deployment were executed for this Goal.

User's 48-call public report: REPORT_ONLY. Its original files have not been
independently obtained or replayed. Existing public synthetic objects are untouched.

## Local engineering evidence

- Existing PG exact-state regression extended with actual diagnostic assertions:
  failed before the fix (HIT with UNSATISFIED/EXACT_STATE). A diagnostic run
  identified STRICT_ACCEPTED_BINDING_INCOMPLETE under STRICT_OPERATOR for L0.
- Fixed canonical lookup mode and exact binding labels. Existing PG exact-state
  and lean-recall tests: 18 passed. This includes real Canonical creation/read,
  two address forms, historical reads and scope exclusion, not model behavior.
- MCP public schema/examples and safe-error tests: 2 passed. These use real MCP
  argument parsing with test Runtime clients; they are not PG/OAuth evidence.
- MCP whole package: 275 passed, 5 skipped (optional integration environments).
- New project-qualified Evidence GET and existing unreadable-source regression:
  2 passed against the owned disposable PostgreSQL. Foreign-project read asserts
  that BlobStore.read is never invoked. No real OAuth/browser claim is made.
- Runtime mypy: 191 source files passed. MCP mypy: 15 source files passed.

Isolated database: owned container `milai-mcp-full-ff139ac7`, localhost port 41883;
new unique `milai_mcpbase_*` database. Connection material stays in a private
temporary file, never in this index or Product packages. No shared/public service
was restarted. No persistent operation IDs or source bodies are stored here.

Additional local progress: migration 0056 and Note domain/repository/service/API/SDK/MCP
implemented. One real-PG CRUD/CAS/history/cursor/deletion check passed (1.42s).
One signed-private MCP ASGI -> actual HTTP Runtime -> new disposable PostgreSQL
check passed (6.34s): Note tools, Evidence exact content, two test subjects and
old-token denial of new Note catalog entries. This does not claim native-client
cold recovery or real OAuth login. The temporary Runtime process and its test DB
were stopped/dropped by the existing lifecycle helper.

Further implementation: Evidence browse now spans Runtime/SDK/MCP, with exact filters,
current eligibility before LIMIT and signed caller/filter-bound cursors. New opt-in
catalog contains 22 tools. Capture/list expose Evidence read references. Note get
pages source refs independently; list/search omit bulky provenance and retain read IDs.
The same signed MCP -> real HTTP Runtime -> isolated PG test was extended, not a new
harness: 1 passed in 4.66s. It covers two-user Evidence browse, cursor binding,
source-page reconstruction and post-revocation Note get/history/list/search/replay/
operation withholding while an independent Note remains readable. An initial check
failed because the fixture omitted the normalized null file digest; corrected the
expected metadata, without weakening content or eligibility assertions.

Search rendering now includes typed Evidence references and current-Canonical Claim
references, preserving returned version identity separately. Existing renderer checks
cover this addition; renderer/input selection: 9 passed (1.02s). Ordinary tool argument
errors reuse the MCP argument models and omit submitted data; the same real-PG MCP
check also verifies source-input redaction: 1 passed (4.57s).

Package checks at this increment: MCP 275 passed / 6 skipped (18.91s, before the final
renderer/error additions; the affected 9-test selection and PG test passed afterwards).
Skips are optional PG-environment gates, including the separately executed ordinary
slice. SDK 188 passed (1.35s). Runtime existing Note PG test 1 passed (1.40s).
Scoped Ruff and mypy passed: Runtime 196, MCP 16, SDK 14 source files.
Runtime/SDK/MCP local source and wheel builds succeeded; versions are development
versions, not a new pinned release, and none were deployed publicly.

The entries above are intermediate results. The following delivery record supersedes
their pending implementation/restart/package statements; their failures remain recorded.

## Candidate delivery

Pair: MCP 0.1.7 / client 0.1.2 / Runtime 0.1.2 / migration 0056_host_notes.
Product contracts/mcp/ordinary-memory-v1.md maps executable checks and result rules;
the adjacent tools.json captures actual tools/list, 22 tools with explicit scope mapping.
Legacy remains default; public service and OAuth grants were not updated.

Latest adjacent selection: `uv run pytest -q tests/test_ordinary_memory_postgres.py
tests/test_input_contracts.py`, with owned role URLs and MILAI_MCP_BASELINE_E2E=1:
3 passed in 11.30s. Real HTTP MCP and Runtime, PostgreSQL, two signed fixture subjects,
two fresh native protocol client processes, Runtime/MCP restart, real HTTP cuts before
forwarding/after commit, original-operation reconciliation, source revocation and
mixed concurrent requests. Empty migration downgrade/upgrade succeeds; nonempty Note
storage refuses downgrade. No model is present in these clients.

54 parent RPC calls include all 17 expected errors; peak client concurrency 4.
Complete-response P50/P95/P99: 51.90/61.42/78.59ms; HTTP errors/timeouts: 0/0.
Database connection acquisition (checkout plus any wait): 51 samples, P95 1.587ms,
maximum 3.864ms. HTTP pool wait remains unmeasured. Scale: 7 Notes, 2 Evidence,
2 subjects. Native subprocess/catalog calls are outside this timing denominator.
These small local samples are diagnostics, not public-service or capacity claims.

Runtime configured full-PG run: 1160 passed, 10 failed, 6 skipped. Nine failures were
outdated migration-head expectations; one migration test reused a database containing
Note history. Updated expected head and isolated migration fixtures; only the ten
failed selectors rerun: 10 passed. An earlier unconfigured run failed on missing PG
environment and is not counted as product success. Of five optional Audit checks,
three passed initially; one needed a fresh fixture (previous state had expired),
and backup coverage exposed a real missing Note-table inventory entry. Product backup
inventory now includes all three Note tables. The two repaired checks passed in a
new database (5.58s), including original text/history/tombstone archive restoration.
The optional composite-adapter check remains unrun. This is not one clean full-suite run.

The final MCP check initially parsed an MCP framework-prefixed error as bare JSON;
adjusted only the assertion parser. Runtime correctly returned a safe content-field
error for more than 65536 UTF-8 bytes. Failure log and repaired run are both retained.
MCP full package: 275 passed / 6 optional skips before final adjacent additions;
SDK: 188 passed. Runtime/MCP/SDK scoped Ruff and mypy passed (196/16/14 files).
All three final packages built. Final MCP Ruff/mypy also passed after the assertion fix.

Archive: `/cra/memory/mx_memory/var/milai-v07-delivery-20260908/milai-mcp-delivery-0.1.7.tar.gz`

SHA-256: `60f1f6926e720ac0fdd5b58aa815042fc334a2bf8dece80405354c196bb2ca98`.

`sh tools/build_mcp_delivery.sh <output>` builds the paired archive. Extracted final
archive, ran its install.sh separately for mcp/runtime into new environments; both
exit 0. Isolated imports from /tmp report MCP 0.1.7, client 0.1.2, Runtime 0.1.2.
No database migration or public service action is performed by installation.

Evidence under `/cra/memory/mx_memory/var/`:

- mila-v07-engineering-20260908.json: request timings, fresh process IDs, aggregate scope.
- mila-v07-final-mcp.log and mila-v07-final-mcp-repair.log: failed parser and corrected selection.
- mila-v07-runtime-pg.log and mila-v07-runtime-pg-repair.log: original run and ten repaired selectors.
- mila-v07-audit-role-check.log and mila-v07-backup-and-audit-repair.log: role/backup checks.
- mila-v07-final-build.log and mila-v07-final-install.json: final build and clean installation.
- mila-v07-delivery-pin.json: archive SHA, 291 source/contract/lock file hashes and installed versions.

Note deletion is logical across all versions; physical purge NOT_IMPLEMENTED and
backup expiry NOT_SCHEDULED. Backups retain the existing quiescent single-tenant
restriction. Restore older-schema archives using the matching Runtime before upgrade.
Timestamp pagination is not retained MVCC. No large-load or new model experiment ran.

## Read-only historical U5 audit

Inspected artifacts/v02-mcp-usability/filehash-20260908a without executing its scripts.
G-010 records actual working_state_update; R-host-baseline-head identifies Working
State v1. host-bootstrap.context occurs verbatim in the developer input of
R_host-032-request.json. Recovery is HOST_LIFECYCLE_PREFETCH, with no model-selected
Memory call. This is old Working State, not an ordinary Note.

The first actual tools read existing source/tests/README. The first code change adds
sha512 while preserving sha256 default, order/duplicates and per-file error handling.
R_host-037-request.json includes the real tool output for 23 successful unittest cases;
delivery-check.json verifies the necessary CLI conditions. The initial preamble claims
review before those reads; it is not treated as proof of prior understanding. Overall
semantic quality and causal advantage over the intact normal files remain unevaluated.

Hash index: `/cra/memory/mx_memory/var/mila-v07-historical-audit.json` (11 inspected files).
No additional model requests. Historical evidence does not exercise new Note APIs or
prove autonomous activation. U5 new ordinary-memory Agent usage remains pending and
unauthorized. Full Goal completion and generality are not claimed.

## U5 execution proposal awaiting user resumption

Remaining required evidence is actual native Agent use of the new ordinary Note
interface. The old G/R_host cannot fill that gap: its saved object is Working State.
No further broad regression, performance expansion or public deployment is needed
to request this next step. Archive SHA was rechecked against the delivery pin.

Proposed first batch: one local coding G/R chain, two fresh native Agent sessions,
same installed candidate, same synthetic private principal/project, normal files
and source-reading tools retained. G sees only the predecessor task and saves its
actual reusable work through note_add; R starts without G conversation/response
cache and continues using the saved Note through the public HTTP MCP interface.
No conversion of the old checkpoint into a fabricated new Note. No new Judge,
summary model, public write, real-user data or paid model service.

Suggested outer ceiling, pending explicit acceptance: 2 sessions, 24 total model
requests, 400000 cumulative raw tokens, 32768 input tokens and 4096 output tokens
per request, 15 minutes for the batch, model concurrency 1, paid requests 0. This
is based on the prior G (11 requests / 112892 raw) and R_host (6 / 75986 raw),
with room for ordinary task completion; it is not a per-session 30-second gate.
Actual client/model configuration and separate G/R task inputs must be pinned
before the first request after authorization, using the existing transport ledger.
Do not silently retry, switch models or append another condition after a failure.

Classify actual recovery as AGENT_TOOL_SELECTION or HOST_LIFECYCLE_PREFETCH from
the trace. First use must be supported by content in the actual model input and
the subsequent concrete action. A successful ordinary file-only continuation does
not prove Note use. If G elects not to save, record the missing opportunity without
forcing a second generation or pretending the chain passed.

This is an approval-ready execution proposal, not authorization or a started batch.
The blocking prerequisite is the user's explicit resumption of the paused model
experiment under Goal U5 and section 7.2. Public rollout remains separate.
