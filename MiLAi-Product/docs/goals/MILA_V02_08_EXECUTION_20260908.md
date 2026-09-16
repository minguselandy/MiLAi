# MILA-V02-08 execution audit

Status: HTTP_DEPLOYED_HOST_RENDERING_PENDING. The full Goal is not complete.
Latest deployment: user subsequently authorized deploying the description changes.
MCP 0.1.14 is installed and active on OAuth 7960 (PID 3610216, zero restarts),
with verified server description and 22 readable tool descriptions. Full locked
suite: 354 passed / 6 PG-conditional skips in 23.27s; Ruff, mypy, build, independent
install and unprivileged preflight passed. Public health/readiness and 401 gates
passed; environment, bindings, grants and metadata stayed unchanged. Runtime and
7968 PIDs stayed unchanged. Rollback restores pinned 0.1.13 without a data restore.
See [the 0.1.14 receipt](../releases/MCP_0.1.14_OAUTH_DEPLOYMENT_20260908.md).
The local-only statements below record the prior turn, not current deployment state.

Latest local-only follow-up: user requested improving all Host-facing descriptions.
The implementation now sets MCP initialize serverInfo.title/description (previously
description was unset), explicitly states host submission/no automatic conversation
ingestion, distinguishes unapproved objects from reviewed Claims and expirable State,
and provides readable titles and purpose-first descriptions for all profiles. Ordinary
22-tool descriptions plus 17 additional/variant descriptions are available in the
[review inventory](../runbooks/mcp-host-descriptions.md). Docstring whitespace is
normalized at registration, not duplicated as separate hand-maintained metadata.
Tool IDs, catalogs, input schemas, risk hints, permissions and storage behavior are
unchanged. Legacy Host lifecycle gates are retained while the automatic-memory wording
is removed. This description change is not deployed; public OAuth remains installed
0.1.13. No public restart/write, client reconfiguration or model test was performed.
New tests inspect eight profiles and signed synthetic OAuth initialize/tools/list;
they verify that ordinary schemas/risk flags match the deployed 0.1.13 snapshot.
Final local verification: locked MCP pytest passed 354 tests with 6 PG-conditional
skips in 22.97s; Ruff and mypy (19 files) passed, as did git diff --check.
Scratch package build succeeded under /tmp/milai-description-build-fSpTsr without
overwriting release artifacts. Its same-version files are buildability evidence,
not a published release. No PG rerun was needed for presentation-only changes.
Earlier deployment records below remain history rather than evidence of this follow-up.

Latest server repair: MCP 0.1.13 is deployed on the OAuth HTTPS endpoint. Ordinary
now has 22 tools (namespace cleanup submission removed, scoped status retained),
suggested_next_step replaces mcp_guidance with optional/non-authorizing metadata,
and common OAuth prose is deduplicated with a concise Proposal envelope fallback.
Final MCP suite: 345 passed / 6 conditional skips; isolated signed PG/HTTP slice:
1 passed, including three scopes, CAS, unknown-commit cuts, cold query and restart.
See [the 0.1.13 receipt](../releases/MCP_0.1.13_OAUTH_DEPLOYMENT_20260908.md) and
[ADR-053](../adr/ADR-053-ordinary-mcp-advisory-and-admin-boundary.md).
This closes the ordinary server's cleanup exposure issue without a Host-policy bypass;
remote UI rendering/repetition and actual Agent use still require their own evidence.
Earlier counts, advisory fields and deployment statements below are dated history.

Latest deployment: on the user's subsequent public-update request, the payload-hint
fix was versioned and deployed as MCP 0.1.12 to the OAuth HTTPS endpoint only.
Release tests passed (341 / 6 conditional skips), installed diagnostics and 23
registered schemas matched, and public edge/configuration-preservation checks
passed. Client remains 0.1.3 / Runtime 0.1.4; 7968 remains MCP 0.1.11. See the
[0.1.12 deployment receipt](../releases/MCP_0.1.12_OAUTH_DEPLOYMENT_20260908.md).
Earlier "local/not deployed" statements below describe the preceding turn.

User follow-up after the OAuth rollout confirms that their client loaded 23 tools,
including `milai_memory_search`, and reports direct Proposal object schemas, rejection
of nine invalid-operation requests, reads in all three State scopes with matching
recovery hints, field-specific nonretryable errors, and distinct deletion/physical
erasure/backup-expiry guidance. This is user-reported acceptance evidence, not a rerun
by this agent. Their Windows-local report was not accessible from this workspace.
The user explicitly did not verify UI `unknown` rendering, three-scope write/recovery,
SDK unknown-commit fault behavior, or independently installed deployment versions.
Earlier local engineering/deployment receipts are separate evidence, not substitutes
for those missing client checks.

The same follow-up exposed a remaining presentation bug: generic `payload` guidance
mixed CREATE business payload with Working State capacity/reference limits. A local
source fix now selects State guidance only from trusted State operation context;
CREATE uses `business JSON object`. Missing/list/string CREATE payload regressions
cover both catalogs, while State ingress and backend tests retain its real limits
and verify no private backend values enter hints. No validation rules, permissions,
transaction behavior or schema migrations changed. This follow-up fix is not deployed;
both public MCP services remain on the original independently installed 0.1.11 bytes.
Follow-up checks from `integrations/mcp`: `uv run --locked pytest -q
tests/test_input_contracts.py tests/test_working_state_async.py` passed 65 tests;
after strengthening the State hint assertion, full `uv run --locked pytest -q` passed
341 tests with 6 PG-conditional skips in 22.86s. Locked Ruff and mypy (19 files) passed.
`uv build --out-dir /tmp/milai-payload-hint-build-urnyrQ` passed without overwriting
release artifacts; those same-version scratch build files are buildability evidence
only, not a new published 0.1.11 delivery. No PG rerun was needed for fixed diagnostic
text/context selection; previous transaction evidence remains separate. No public
restart, business mutation, model experiment or schema freeze was performed.

The user subsequently requested the separate public OAuth endpoint as well:
`https://milai.aigcit.com:7960/mcp` now runs MCP 0.1.11 / client 0.1.3 with its
existing ordinary catalog. Public health, metadata, registration and rejection
checks passed. Real-user authenticated tools/list and the pre-existing external
revocation-metadata gap remain open; see the
[OAuth deployment receipt](../releases/MCP_0.1.11_OAUTH_DEPLOYMENT_20260908.md).
Following explicit user authorization, the existing 7968 HTTP service was switched to
MCP 0.1.11 / client 0.1.3 and shared Runtime 0.1.4. Health, authentication, deployed
schemas and the existing Host's read call passed. See the
[deployment receipt](../releases/MCP_0.1.11_HTTP_DEPLOYMENT_20260908.md).
Earlier deployment-gate statements below are retained as execution history.
User explicitly requested execution of the design Goal. Local zero-model changes
and isolated engineering fixtures are in scope; public deployment, public business
mutations and model experiments remain separately gated. No subagents were used.

Baseline: Product HEAD 1b5e4a7, 143 already-modified tracked files plus extensive
untracked work. Existing changes were retained; no commit/reset was performed.
The 0.1.9 catalog hash matched the design's
0890f5857727ee3614820c2c3219e76ec5416616a98e44ee044c7c2910b043c7.
Before editing, server.py hash was
63124e6fb9bdc77a713421c2521ad31897fee707ba3fa526c29b91717e64dc83,
input_contracts.py 398224ffaf9f527cd84be7916018ce5350985570f104c4b36185389c839915e6,
ordinary_memory.py f0abc73337130c958cd46aa0670c55295fac533889276a3654f472ac033ec544,
Runtime State domain d7d256277bdc93615b90e7221b86041abbb8c422c327032ff69a9bdd794cf6b0.
These identify inspected files, not a clean or complete baseline tree snapshot.

Candidate versions: MCP 0.1.11 / client 0.1.3 / Runtime 0.1.4; migration stays 0056.
The initial 0.1.10 delivery and checks below are retained; the subsequent endpoint
correction and 0.1.11 verification are recorded in the addendum.
No authority, identity, scope binding, TTL, canonical procedure, permission or
deletion transaction was changed. No new ADR/migration is required for these
presentation/validation diagnostics and SDK retry changes. State validation now
reports its existing combination/payload constraints at field locations.

## Requirement evidence

| Gate | Current evidence / boundary |
| --- | --- |
| T0 / F4 | Current Host metadata: 13 tools, proposal: unknown. Installed 0.1.6 tools/list: object reference, short descriptions; all Host tools prepend the same exact 1541-character instructions. Twelve full descriptions match; review differs further. Not a unique process/cache diagnosis. |
| V01 | Actual signed private HTTP tools/list: 23; legacy tests retain 13, annotations and direct dispatch rejection. No new tools/scopes. |
| V02 | tests/test_working_state_async.py: three scopes, ABSENT/ACTIVE, concurrent get/write hints and binding identity; real PG slice repeats three scopes and CAS. |
| V03 | tests/test_input_contracts.py: nine operations, generated Schema and parser, nonempty refs, UUID/duplicates/cross-branch/authority/OpenIssue errors; shipped proposal-examples-0.1.10.json. Runtime rules reviewed in domain/proposals.py. |
| V04 | Both Codex catalogs expose Proposal as object with generated constraints and no $ref in 0.1.11. 0.1.10 covered only ordinary; the endpoint addendum corrects that gap. Candidate target Host rendering remains UNVERIFIED; not replaced by SDK results. |
| V05 | Runtime State domain test and signed HTTP/PG calls: both invalid ID/version combinations, invalid ID, oversized payload produce safe field locations. Ordinary MCP rejects private invalid argument types before Runtime dispatch. |
| V06 | Real PG: two concurrent updates from one head yield exactly one commit in each scope; loser receives STALE_WORKING_STATE/current_version=2 in MCP. Other principal remains ABSENT and cannot obtain foreign version. |
| V07 | Real HTTP before/after-commit cuts for Note and State; original-ID identical replay does not double-commit. Changed payload same ID conflicts. Async cancellation keeps UNKNOWN audit and independent read alive. No State operation-get tool invented. |
| V08 | Safe field projection; private backend body/token canaries absent. Exact-object CAS detail correlation required; foreign/auth errors with version details cannot disclose them. isError stays true. |
| V09 | Candidate wire descriptions: 6632 characters total, zero old full-prefix repeats. OAuth routing and per-source permission regressions pass. Guidance flags are optional/authorization-required where appropriate. Host-side repetition in the current old connection persists; candidate Host gate pending. |
| V10 | Real PG/HTTP Note deleted get, delete receipt and operation receipt agree on physical_deletion_supported=false; history/replay checks and source revocation protection retained. No physical purge claimed. |
| V11 | Existing signed private admin tests cover hidden/denied calls and local synthetic positive cleanup. Current-user intent remains an external prerequisite, not something a confirmation literal proves. No actual Host refusal trace is available; no destructive public probe was made. |
| V12 | Full MCP regression includes dual-source scope/failure/timeout/MISS/ref/route tests; real Note slice includes snippets, new-client recovery and Runtime/listener restart. Semantic completeness and Agent selection remain unproven. |
| V13 | Legacy text errors retained, ordinary backend error contract versioned, Note JSON fields additive; locked tests/static/types and package installation described below. No data rollback. |

F1–F3/F5/F6 local repairs are implemented. F4 has a concrete wire/Host discrepancy
and a candidate serialization adjustment; target Host success is pending. F7 has
local authorization evidence but no observed Host refusal to reproduce. This does
not satisfy the full Goal's target-client terminal gate or predecessor U5.

## Commands and results

Commands run from their package roots, with `uv run --locked`:

- MCP `pytest -q tests/test_working_state_async.py tests/test_codex_full_profile.py`:
  19 passed after T1. Proposal/HTTP/State slice later 39 passed; recovery slice 54.
- MCP full `pytest -q`: final 333 passed / 6 PG-conditional skips in 23.18s;
  `ruff check src tests` and `mypy` (19 source files) passed. These are successive
  runs, not summed independent tests.
- MCP `pytest -q tests/test_ordinary_memory_postgres.py`, with
  `MILAI_MCP_BASELINE_E2E=1` and isolated migration/API/Steward/worker role URLs:
  final 1 passed in 15.70s. `MILAI_V07_CATALOG_PATH` exported the real signed tools/list.
- Client `pytest -q`: 190 passed; State no-retry selector 4 passed separately.
- Runtime `pytest -q tests/unit tests/contract`: 1016 passed in 12.70s.
- Runtime `pytest -q tests/integration/test_host_notes.py tests/integration/test_host_cognitive_state.py -k 'not large_reference'`:
  final 4 passed / 1 deselected in a fresh owned database with API/Steward/Audit roles.
  The unchanged 1024-reference migration/capacity case was not rerun; neither reference
  capacity nor migrations changed. One preceding attempt was 3 passed/1 skipped
  because Audit role URL was absent; it is not counted as successful audit coverage.
- All affected packages: `ruff check src tests` (Runtime adds `migrations`), `mypy`,
  `uv build`. Lock metadata refreshed offline after package version changes.
- `git diff --check`: passed. Existing broad dirty-worktree changes were not committed.

Evidence directory:
`MiLAi-Lab/artifacts/v02-08-mcp-contract-repair/`.
It holds host-visible-baseline.json, installed-0.1.6-wire.json, host-comparison.json,
final-0.1.10-tools.json, HTTP metrics and retained test logs. Host material was
obtained without triggering another model generation or reading a credential store.
The old installed-package inspection initially lacked pytest; adding the existing
test site-packages to that one inspection process's path succeeded without modifying
the installed environment or starting a public service.

`http-engineering.json` records 96 instrumented parent tool calls, p50 51.89 ms /
p95 59.88 ms / p99 71.43 ms. It excludes six directly issued CAS-race RPCs and native
child protocol/metadata calls; it is not a complete physical request count, a model
latency measurement or a capacity claim. No tokenizer or model requests were made.

The first PG/HTTP attempt failed because SDK max_retries=2 silently repeated a
State write after a cut. The fixture exposed a product bug, not a transient reason
to retry for green. client 0.1.3 adds no_retry=True for State writes and dedicated
network/503 tests. The following real cut tests passed. Earlier UUID-fixture,
CREATE-error-ordering and lint failures are retained in this execution history.

## Delivery and remaining gate

Package source, current snapshot and examples live in Product; run artifacts live
in Lab. The archive is `integrations/mcp/dist/delivery/milai-mcp-delivery-0.1.10.tar.gz`
with a SHA-256 sidecar and internal SHA256SUMS. Installation creates new venvs only;
it does not start services, migrate databases, change OAuth or publish anything.
MCP and Runtime installers both completed into separate new environments under
`/tmp/milai-v0208-install-vTK6NX`; uv pip check, CLI help and Runtime import passed.
Logs are install-mcp.log/install-runtime.log in Lab. Verified wheel digests are
compared with the final archive; package/checksum manifests remain external to the
archive to avoid a self-referential hash. No public service was started or replaced.

An additional three security tests initially called the internal server method,
which bypasses protocol extensions, instead of exercising MCP tools/call. They
were corrected to use the actual protocol client; private argument-type errors
are sanitized before any Runtime I/O. The final 333-test suite is fully green.

Rollback uses previous compatible packages/configuration while preserving data,
identities and audit. No new migration or database restore. Model experiments stay
paused and public deployment stays unauthorized by this local execution request.
To close V04 and the Host portion of V09, the target Host must load the candidate
definition and expose its converted schema without generating another model run.
The current session's old 13-tool metadata cannot prove that future candidate view.

Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE.

## Continuation: actual Host endpoint and 0.1.11

The previous goal turn made implementation/delivery progress. This continuation
revalidated the unchanged 0.1.10 archive hash, stopped owned PG container and old
13-tool Host metadata. No new deployment approval had arrived.

Read-only systemd/process inspection revealed two live MCP services. A targeted
read of only `[mcp_servers.milai]` and its `url` in `/root/.codex/config.toml`
confirmed this session's connection is `http://36.140.33.19:7968/mcp`.
No credential values/store were read. `milai-codex-full-public.service` launches
the Product workspace MCP venv with the default legacy catalog, and references
the existing `/cra/memory/mx_memory/MiLAi/runtime/.env`; that file's contents were
not inspected. The separate OAuth service uses installed MCP 0.1.8 on loopback
7969. Both loopback /healthz reads returned status=ok. Those unauthenticated
health reads do not prove user scopes or a refreshed tools/list.

The initial handoff's implication that upgrading AIGCIT alone would address this
Host was incomplete. 0.1.10's ordinary-only reference expansion also missed the
actual legacy target. 0.1.11 corrects serialization for both Codex catalogs,
without changing the current endpoint, names, parser, error content, grants or
public process. The nine Proposal operations now run Schema and tools/call checks
in both catalogs; ordinary's previous schema-only branch was strengthened to
exercise its actual protocol parser too.

MCP adjacent input/legacy-profile/real-HTTP tests: 38 passed. Full locked MCP
pytest/Ruff/mypy and package receipts are in `mcp-0.1.11-final.log` and the
0.1.11 delivery receipt in the existing Lab artifact directory. New snapshots
record 13 legacy/23 ordinary tools, both with a direct Proposal object. The prior
signed PG slice and unchanged Runtime/client receipts remain applicable to their
unchanged transaction code; no PG or model run was repeated for this serialization
correction. No public service was restarted. The shared workspace venv is not a
pinned release; any authorized deployment must use an independently installed venv.

[The concrete 0.1.11 handoff](../releases/MCP_0.1.11_HANDOFF_20260908.md) identifies
the correct service, shared Runtime impact, preserved bindings, rollback and the
remaining zero-generation Host export gate. 0.1.10 is retained as historical
candidate evidence, not the recommended artifact for the current Host. The full
Goal still needs target Host definitions and evidence for any claimed cleanup
refusal; automatic continuation is not public deployment authorization.
