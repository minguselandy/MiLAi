# MiLAi Product Current Status

> As of: 2026-09-22
> Repository: `/cra/memory/mx_memory/MiLAi/MiLAi-Product`
> Product status: `0.1.0-candidate`  
> Schema status: `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## Current engineering baseline

- Reconciled repository `main`: `87aa53c73ec0a67ff412923e2151c71def575130`; Git tree
  `0cc79d8797f1cb1c4321839015eab9f3e1bd980a`; main fast `35688919530` passed.
- Local 3A-3R candidate: `9b4aa1670dc75dfc2149baeb75719f017267e92a`, 425 files,
  Product tree `847967d2e212b974d92b0b08d6e0f8b135a3c1080adf61790dcb771b9c832311`,
  manifest SHA `016df6085fc29d9c201c3f22739397e4f82af128152020318bc2ce4647814096`.
  [Partial repair](revalidation/resolver-language/REMEDIATION.md): unchanged corpus
  28 PASS/2 FAIL; client tests 64 PASS/2 XFAIL, Runtime 49 PASS. Final gates pending;
  no full resolver closure, model use or FIXED claim.
- 3A-2R source proof: `faf3922c2b1d037f0c3a019dd1bbaf6dc059be15`;
  PR #36 merged after exact-head fast and final composition passed.
  Merged Host-proof identity: 425 files; manifest SHA
  `44be5e2e93837dcc75b996140f06b10e6142dc34e6a5718a894f79574ddfd352`; Product tree
  `08cd98fea12383fd26cf3f10b39bc04ffea23da2271f45ebe55c772a57ecafe2`.
  [Scoped repair receipt](revalidation/host-continuity/REMEDIATION.md): 24 native tests
  and 2 real PG recovery cases pass, without XFAIL; 4 fresh Host processes / 10 attempts.
  Streaming/concurrent continuation and model use/benefit are not claimed.
- Cleanup C0–C10 is complete. Its historical composition is Run #60 / ID `35632657133`.
  The current Host-repair composition is Run #63 / ID `35685753906`: 17 jobs passed,
  at PR head `ba4723e236aa6fd4949a688d9593059b459a6bd9`, including Runtime/PostgreSQL, all six integrations, Lab fast,
  four historical replay shards, Archive, Product identity and Conformance.
- Frozen Architecture remains version 1.0.0 and immutable. The current implementation map is
  `9 PASS / 35 UNVERIFIED / 0 DEVIATION`; overall status remains honestly `UNVERIFIED`.
  The prior `10/34/0` map was bound to the cleanup Product identity. Adding the explicit
  testkit, native guard and resolver changes update the global manifest; 19 prior receipts
  are now historical. The separate partial Resolver receipt supplies one current SCOPED
  FAIL: 20 receipts, 1 current, 1 current claim, 6 preserved failures and 1 current failure.
  No old receipt was rewritten or silently rebound. Host full composition passed;
  the new Resolver behavior candidate still requires its own final gate.
- `docs/TECH_DEBT.md` records `9 FIXED / 0 NEEDS_REVALIDATION / 1 OPEN` after
  [Resolver diagnosis](revalidation/resolver-language/REVALIDATION.md).
  Host repair is merged; Resolver partial repair keeps both semantic limitations OPEN.
  `NEEDS_REVALIDATION` is not a defect classification and must be resolved by executable diagnosis.
- The current coordinating contract is the
  [post-cleanup development Goal](cleanup/MILA_POST_CLEANUP_DEVELOPMENT_GOAL_v1.0_20260922.md),
  derived from the [post-cleanup roadmap](cleanup/MILA_POST_CLEANUP_DEVELOPMENT_ROADMAP_v1.0_20260922.md).
  Product/Lab status reconciliation completed through PR #27 at main `cf149939eea9f184159ebfb6aab1a3e791988250`;
  tested/merge tree identity and main fast run `35673403788` passed. The user resumed development;
  worker `--once` revalidation completed through PR #28, with main fast `35674495200` passed.
  [Trace Ownership v1](reference/trace-ownership-v1.md) is complete for its scoped testkit: offline contract/join
  implementation merged in PR #30. The [Host producer testkit](reference/host-trace-testkit.md)
  merged in PR #31; the Runtime producer merged in PR #32. The new
  [same-execution slice](reference/trace-ownership-chain.md), merged in PR #33, joins eight actual
  Host/MCP/HTTP/PostgreSQL attempts with a controlled in-process Provider fixture.
  Exact fresh-retrieval/version/Context provenance and failure dispatch states are covered;
  v2 additionally covers actual Claim/cache origins and has a scoped debt receipt.
  PR #34 exact-head fast `35683142058`, merge-tree identity and main fast all passed.
  [3A-2D Host continuity diagnosis](revalidation/host-continuity/REVALIDATION.md) closed in
  PR #35: 18 native controls PASS / 2 FAIL; 2 real PG chains PASS (4 Host processes,
  10 attempts). Exact-head fast `35685033957`, merge-tree and main identity passed.
  3A-2R retired-instance repair closed through PR #36. The
  [3A-3D Resolver diagnosis](revalidation/resolver-language/REVALIDATION.md):
  frozen 30 cases, client 11 PASS/11 FAIL and Runtime 6 PASS/2 FAIL; no Product
  behavior change. PR #37/main fast `35688919530` close the diagnosis with identical
  candidate/merge trees. Original failures and strict XFAIL assertions remain.
  Active work is separate 3A-3R on `fix/resolver-typed-language-boundaries`;
  scoped improvement is proven locally, but two corpus expectations remain unsatisfied
  and final composition/remote closure remain pending. No FIXED claim.
  This is not real model use or a mechanism-effect claim.
  No research experiment is automatically resumed.
- Root CI is the monorepo authority. Full composition is reserved for a material Product behavior
  candidate; docs-only and Lab-only changes use the classified fast path.
- Product/Lab/Archive boundaries are stable. The current work is behavioral closure and evidence,
  not another repository reorganization or file-size-driven refactor.

The sections below are historical status and experiment records. Their dates, pinned commits and
results are immutable evidence; they are not claims about the current HEAD unless explicitly stated
in the current engineering baseline above.

## V02-14: optional Client 0.1.4 source helper, local candidate only

The [Host source runbook](runbooks/host-source-acquisition.md) describes the new explicit-import
`milai_client.host_acquisition` mechanical helper. It does not change existing Agent defaults,
MCP tools, Runtime, permissions, Canonical or State semantics. Client 209 tests, MCP 385 passed
with 7 opt-in skips, and all six adapter static/package gates pass. No release or deployment.

The [Lab report](../../MiLAi-Lab/studies/active/MILA_V0214_HOST_RESULTS_20260909.md) completes
D0–D7 locally: 16/16 final development phases, four independent synthetic confirmation tasks
(H4/4 versus A0 1/4), and all 133 model requests/877,655 raw accounted including failures.
These results do not justify a production default or external generalization. On September 9,
read-only installed checks find public MCP0.1.15/Client0.1.3/Runtime0.1.5; experiments used the
frozen Runtime0.1.4 predecessor pin and are not BGE effect measurements. Schema remains NO-GO.

## Lab cost-first increment completed

[MILA-V02-04 C0–C2 report](../../MiLAi-Lab/studies/active/MILA_V02_COST_FIRST_RESULTS_20260906.md):
24 historical failed reads now succeed in 12 isolated containers with complete source recovery;
Lab 180 tests and required checks pass. This adds no Product behavior or experimental model usage.
Task-cost hard control remains unverified; C3 is not entered and N5 remains incomplete.

## Local v0.2 State payload fidelity correction

Working State now preserves arbitrary JSON payload strings and nested keys, including leading
indentation and terminal newlines. Identifier normalization remains limited to binding fields.
[ADR-040](adr/ADR-040-working-state-payload-fidelity.md) records the compatibility implications:
old normalized receipts are retained, and whitespace-sensitive replay can now conflict.
The current local Product tree is
`c5561412b0440f84e628d69a7c271c96d66bae7f89d4e3f1db46ede97a1608bf`.
Runtime real-PostgreSQL gates: 971 passed, 1 dependency-related skip; Ruff, mypy and build passed.
The [Lab correction and followups](../../MiLAi-Lab/studies/active/MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md)
supersede the earlier decision to stop at a terminal-newline defect. This fix has only run in the
isolated local instance; public deployment, Canonical authority and Schema NO-GO are unchanged.

## MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1 frozen

The current Engineering feature set is frozen as
[`MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1`](goals/MILA_MEMORY_MCP_FUNCTIONAL_BASELINE_V1.md),
bound to Product tree
`f998c2d96c6ae4a4e2ffa246d12257938af29a9e49c60f48ad21e7b50250cad1`.
It includes the full MCP lifecycle, Host-managed continuity, Event reconciliation, persisted-frontier
continuation, and intra-source lexical acquisition in SHADOW. It does not claim Product-11 Research
effect, Dense value, frontier integration, or Formal 500 use.

Development now defaults to failure-driven admission. Real task failures are recorded in the
[Production Failure Ledger](reports/MILA_PRODUCTION_FAILURE_LEDGER.md); new mechanisms require a
reproducible failure, a proven safety/compatibility defect, or an opened Research gate. The first
read-only deployment cost snapshot is recorded in the
[Performance Baseline](reports/MILA_MEMORY_PERFORMANCE_BASELINE_V1_20260905.md). No Git commit/tag was
created from the shared dirty worktree; the Product manifest is the source identity.

The first post-baseline real-use window is recorded in the
[R1 report](reports/MILA_REAL_USE_EXPERIMENT_R1_20260905.md). Three fresh zero-Skill, MCP-only historical
tasks all activated recall and produced correct grounded/abstaining answers. R1 exposed and fixed
`MFL-20260905-001`: an empty Runtime `ABSENT/ABSTAINED` control envelope could be presented by the MCP
facade as a false `HIT`. The deployed facade now returns `MISS` with zero Evidence for that case while
preserving real positive HITs. Current post-fix Product tree identity is
`d93bef8bfdf846963dabddf5635ba254dea7442d42e0eee3dcebb3ae87d9199d` for the R1 deployment; the frozen V1 identity remains
the observation baseline rather than being rewritten retroactively.

The v0.2 usability study has since added bounded MCP Working State error feedback: stale versions,
operation conflicts and ineligible references have distinct reason codes, while unavailable updates
remain explicitly unconfirmed. Current source tree is
`7fdf4f12d8c9ef63a9662145f6a1abb2e053fce2860e60ddcde8eeabcaf1fc0c`; the change is validated in an
isolated study instance and has not been deployed to the public service. No API input schema,
permission, CAS or Canonical semantics changed. MCP gates: 160 passed, 1 opt-in PostgreSQL lifecycle
test skipped; separate real PostgreSQL stale-version and cross-project-reference probes passed.
The [Lab study](../../MiLAi-Lab/studies/active/MILA_V02_MEMORY_FLOW.md) has completed G0–G4 as
`COMPLETED_KEEP_BASELINE`: two development cases, eight A0/A1 pairs, three A0/H1 Host pairs,
one actual-update U/V pair, all 12 G2 followups, and four new planning/writing tasks plus two
followups. A1/H1 had no net task wins; saved-memory net value remains unproved. All 46 allocations,
including startup failures and Host deviations, remain recorded. Normal use and withdrawal of
extra reminders are documented in the [existing runbook](runbooks/http-mcp.md#ordinary-task-continuation).
This does not establish autonomous stale-State repair, dynamic revocation propagation, raw-token
hard-cap enforcement, production reliability, representation generalization or Schema readiness.

The subsequent [MILA-V02-02 LME increment](../../MiLAi-Lab/studies/active/MILA_V02_LME_INCREMENTAL.md)
is `COMPLETED_KEEP_BASELINE`, with no Product source change. Lab repaired a source-session annotation
leak and verified a public-client import optimization in three full484-Event comparisons. No QA
behavior candidate entered L2/L3. Two actual conditional updates and four U/V pairs yielded eight
correct followups, but both histories had negative token and wall-time net gains after generation
cost. All14 allocations are terminal; Lab133 tests/gates passed. Own services stopped with data
retained; A0, D2 SHADOW, public deployment and Schema status remain unchanged.

The requirement-by-requirement [all-experiments audit](reports/MILA_ALL_EXPERIMENTS_COMPLETION_AUDIT_20260905.md)
is historical evidence for the former external-human block. The user subsequently authorized a
separate `SUBAGENT_SEALED` branch. Two role-specific subagents agreed on all 24 cases, but the frozen
A0 trace yielded `0 continuation / 8 intra-source / 16 control` opportunities. Product-11 Research is
therefore terminal for this slice as `PARKED_PRODUCT11_INSUFFICIENT_SUBAGENT_SEALED_OPPORTUNITY`;
X1--X4 were not entered and Formal 500 remains unconsumed.

The final `20260905c` execution is an end-to-end verified artifact chain: dedicated source-only
packets, a pre-execution identity/invocation manifest, 24/24 exact agreement, seal-time proposal
recomputation, and an append-only v0.2 receipt. Architecture re-review returned `PASS`; the earlier
v0.1 receipt remains preserved as superseded history.

## HTTP-PUBLIC-01: explicit public candidate endpoint

An explicitly authorized `codex-full` MCP service is enabled and running at
`http://36.140.33.19:7968/mcp`. Runtime remains private on `127.0.0.1:28180`; `7961` through `7967`
were already occupied and were not displaced. The public MCP passed health/readiness, 401 negative
authentication, authenticated initialize/tools-list and exact 13-tool checks. The database was
advanced additively from migration 0049 to 0050 before Runtime restart.

Non-loopback startup is fail-closed unless both `--allow-non-loopback` and a public base URL are
provided. The two services are persistent systemd units; the inbound token is held in a root-only
file outside the repository. The user cancelled WebSocket delivery, so `7969` remains free and MCP
streaming uses the standard HTTP/SSE channel. See [ADR-035](adr/ADR-035-explicit-non-loopback-codex-full-mcp.md),
the [acceptance contract](contracts/HTTP-PUBLIC-01_ACCEPTANCE_CONTRACT.md), and the
[deployment audit](goals/HTTP-PUBLIC-01_DEPLOYMENT_AUDIT_20260904_141458.md).

The listener is plain HTTP and therefore remains a candidate deployment: firewall source
restriction or HTTPS termination is required before transmitting its Bearer token over an
untrusted network.

The current new-user path uses a server-issued, per-user Bearer credential. The credential itself
maps to one server-owned principal; the client no longer sends the non-standard `x-agent-id`
header. First MCP connection atomically activates the user without local MiLAi installation or
approval. The server stores only Token digests and automatically appends issue/register/revoke
audit. See [ADR-037](adr/ADR-037-standard-http-mcp-bearer-principal-binding.md) and the
[remote registration guide](runbooks/remote-mcp-json-registration.md).

The endpoint implements MCP Streamable HTTP JSON-RPC, but the public deployment still uses static
Bearer onboarding. Exact AIGCIT-style URL-only Codex login is not claimed: it requires an HTTPS
OAuth Authorization Server with discovery, client registration, authorization-code/PKCE and user
login. A common `mcpServers` object is client configuration, not part of the MCP protocol.

The OAuth/DCR implementation is now present and passes loopback protocol and real `codex-full`
HTTP tests: RFC 9728/RFC 8414 discovery, DCR, exact resource binding, S256 PKCE, one-time browser
enrollment, access/refresh issuance, refresh rotation, revocation, audited principal propagation
and the exact 13-tool catalog. Public activation remains blocked because the current NAT exposes
only plaintext `36.140.33.19:7968`; this host cannot complete trusted certificate validation on the
public address's 80/443. See [ADR-038](adr/ADR-038-oauth-dcr-url-only-mcp-onboarding.md), the
[OAuth acceptance contract](contracts/HTTP-OAUTH-DCR-01_ACCEPTANCE_CONTRACT.md), and the
[OAuth deployment runbook](runbooks/oauth-http-mcp.md). The exact implementation and deployment
boundary is recorded in the
[HTTP-OAUTH-DCR-01 audit](goals/HTTP-OAUTH-DCR-01_IMPLEMENTATION_AUDIT_20260904_093549.md).

The deployed completion evidence is recorded in the
[HTTP-REMOTE-REGISTRATION-01 audit](goals/HTTP-REMOTE-REGISTRATION-01_COMPLETION_AUDIT_20260904_154914.md).

The earlier token-free helper archive remains a historical compatibility artifact, not the
new-user registration path.

## HTTP-FULL-01: single-endpoint Codex full lifecycle

The local Codex product route now has one authenticated `codex-full` Streamable HTTP endpoint at
`127.0.0.1:7337/mcp`. Its exact thirteen-tool catalog covers resolve/get, persistent Host working
state get/update, Evidence capture, Proposal create/list/get/review, Evidence revoke/deletion status
and namespace cleanup/status. Scope and authority are Host-owned; the facade requires exactly one
project, injects capture/proposal policy, and removes the project argument from namespace cleanup.

One inbound Codex principal controls four minimum-capability Runtime credentials. Runtime canonical
actors remain role-separated, but this is explicitly not independent-Host review: mutation results
and structured audit logs record `SINGLE_HOST_FULL_CONTROL` and `independent_host_review=false`.
Migration 0032 and the canonical procedure remain unchanged. See
[ADR-033](adr/ADR-033-codex-full-single-endpoint-http-mcp.md), the
[HTTP-FULL-01 contract](contracts/HTTP-FULL-01_ACCEPTANCE_CONTRACT.md), and the
[HTTP MCP runbook](runbooks/http-mcp.md).

This integration capability is independent of Product-11's blocked experimental stages and does not
claim persisted-frontier continuation.

## Host Cognitive Affordance: HC-0 through HC-3 implemented

Migration `0050_host_cognitive_state` adds a separate `HOST_WORKING` plane with a stable state
lineage, immutable append-only versions, exact-version CAS, retry-safe operation IDs, Runtime-owned
TTL, tenant/actor RLS and exact live Evidence-reference validation. Automatic access/append audit is
enabled by default and records only safe identity/digest metadata, never the working payload.

The `codex-full` MCP now exposes `milai_working_state_get` and
`milai_working_state_update`. Codex controls the JSON semantics; tenant, principal, project and
scope reference remain server-owned. Recall never writes this state, and the state cannot directly
write Canonical memory or impersonate Product-11's retrieval continuation state. Backup inventory,
Python client methods, Runtime routes and HTTP MCP documentation are updated. See
[ADR-034](adr/ADR-034-host-cognitive-affordance-layer.md), the
[contract](contracts/MILA_HOST_COGNITIVE_STATE_CONTRACT.md), and the
[execution Goal](goals/MILA_HOST_COGNITIVE_AFFORDANCE_GOAL.md).

Current substrate terminal remains `PARTIAL_HOST_COGNITIVE_PERSISTENCE_USABLE`: HC-0 through HC-3
are implemented and their deterministic/security gates pass. HC4-C1 now separates adoption from
usefulness. Its sealed A0 passive-affordance baseline executed 8 genuine fresh-Codex tasks across 2
continuous chains; the authenticated 13-tool MCP was reachable, but natural Working State
GET/UPDATE use was 0/8. A0 is therefore `HC4_A0_PASSIVE_ADOPTION_NEGATIVE`, not ordinary sample
noise. With no ACTIVE State, HC4-C2 cross-session usefulness remains `NOT_EVALUABLE`.

HC4-A1 changed only server instructions and the existing two tool descriptions to explain resume,
material decision/failure/blocker and next-action use cases while retaining Codex choice. Its
independently authorized public-IP HTTPS/OAuth chain completed four fresh sessions, but natural
Working State use remained 0/4. JSONL, MCP journal and PostgreSQL agree that no GET/UPDATE occurred
and no ACTIVE State existed. The frozen rule therefore records
`HC4_A1_GUIDED_ADOPTION_NEGATIVE`, stops prompt escalation, and parks self-maintained State as a
manual/explicit feature. HC4-C2, CAS/stale correction and natural restart usefulness remain not
evaluable. See the [A0 audit](goals/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXECUTION_AUDIT_20260904_134043.md),
[A1 audit](goals/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_A1_EXECUTION_AUDIT_20260904_193542.md), and
[plan/tracker](goals/MILA_HOST_COGNITIVE_AFFORDANCE_HC4_EXPERIMENT_PLAN.md).

A later zero-Skill tool-selection isolation made the boundary more precise. Explicitly requesting
`milai_working_state_get(scope=TASK)` succeeded with all 13 tools visible (`1/1`), while the same
generic resume intent selected no MiLA tool with only State GET/UPDATE, with resolve plus State
GET/UPDATE, or with all 13 tools (`0/3`). Callability is therefore proven; 13-tool dilution is not
the primary failure and catalog narrowing is not a sufficient repair. The trigger-first metadata
treatment is exhausted. `MCP_AUTO` remains model-controlled/best-effort; deterministic continuity
requires a separately implemented and accepted `HOST_MANAGED` lifecycle path. See the
[MCP affordance contract](contracts/MILA_CODEX_MCP_AFFORDANCE_CONTRACT.md) and
[tool-design audit](goals/MILA_MCP_TOOL_DESIGN_REPAIR_AUDIT_20260904_210936.md).

The real coding tasks independently closed five retrieval assertion drifts and introduced a
query-only recollection facade with lazy-compatible application exports. The final empty-database
Runtime gate passed 912 tests with one optional cross-package skip. These are Product engineering
outcomes, not evidence that Working State was useful; no HC Runtime/schema/MCP surface or State type
changed during A0. A1 only changes affordance text and does not reclassify those engineering
outcomes as Working State evidence.

## Memory Activation MA-0 / MA-1

MiLA now separates `AUTO`, `HOST` and `EXPLICIT` activation as Host policy rather than a custom MCP
annotation. `milai-mcp 0.1.4` adds `milai codex`, the first deterministic HOST path. It derives or
accepts a stable TASK ref, starts a private loopback Streamable HTTP MCP, performs
`milai_working_state_get(scope=TASK)`, validates and bounds the result, and only then launches Codex
with explicitly non-canonical developer-context data.

State and bearer data stay out of argv; inherited Runtime credentials are removed from the Codex
environment; the temporary profile is `0600` and is deleted with the temporary MCP at exit. A real
Runtime-backed ABSENT/derived-task smoke and Codex `debug prompt-input` check pass. This implements
resume prefetch only: checkpoint detection/generation and historical-query prefetch remain pending,
and HC4 usefulness has not been reclassified. See [ADR-039](adr/ADR-039-host-managed-memory-activation.md),
the [activation contract](contracts/MILA_MEMORY_ACTIVATION_POLICY_V1.md), and the
[completion audit](goals/MILA_MEMORY_ACTIVATION_MA1_COMPLETION_AUDIT_20260904.md).

## Product-11 D1/D2 engineering baselines complete; Research X0 parked

Product-11 execution is authorized subject to its preregistered stage gates. It freezes Product-10's
final tree as the baseline and separates two claims: persistent retrieval continuation
must add novel cumulative Evidence without changing the first-call A0 Evidence projection; explicit
intra-source lexical/Dense retrieval must turn `NOT_DISCOVERED` groups into direct anchors without
crediting adjacent hydration as discovery.

The v0.2 contract correction requires P11-A primary candidates to originate only from the sealed
persisted frontier, with global reacquisition and pool extension disabled. It also replaces
request-ID idempotency with a database operation fingerprint, narrows `FRONTIER_EXHAUSTED`, freezes
macro metric formulas and bounds the state tree with profile-owned limits.

[ADR-032](adr/ADR-032-explicit-acquisition-nondestructive-continuation.md) is accepted and the
[Product-11 acceptance contract](contracts/MILA_PRODUCT-11_ACCEPTANCE_CONTRACT.md) is frozen. Lab
retains the original proposal-free HUMAN path unchanged as historical and optional. A later
user-authorized `SUBAGENT_SEALED` path bound two distinct subagent identities to separate source-only
packets, required exact normalized agreement, and kept
`human_adjudication_status=NOT_PERFORMED`. It is model-assisted development evidence, not human gold.

The authenticated HTTP MCP baseline is complete and usable independently of the Research block.
Phase D1 has now also implemented a default-off persisted-frontier continuation: Call 2 restores only
exact saved candidates, performs no global reacquisition/pool extension/replanning, excludes seen or
online-ineligible Evidence, disables adjacent hydration during continuation rendering, and appends an
idempotent successor. Migration `0053` hardens authenticated edge-principal binding, content identity,
replay validation and bounded state-tree writes. Public MCP input remains
`query + optional previous_context_id`.

Lab completed a final label-blind A0 trace over a non-Formal 24-case/238-turn candidate slice. Fresh DB,
24/24 trace, Canonical=0, Product label access=0 and cleanup passed. Both independent subagents then
agreed on 60 instance groups and 70 exact acceptable turn refs. The post-agreement frozen join found
`0 continuation / 8 intra-source / 16 control` opportunities against required minima 8/8/8. X0 is
therefore parked for insufficient opportunity and **quantitative effect runs did not start**.
Engineering D1 migration/behavior remains complete without making P11-C1 effect claims. See the
[D1 completion report](goals/MILA_PRODUCT-11_PHASE_D1_CONTINUATION_COMPLETION_REPORT_20260905.md),
the [tracker](goals/MILA_PRODUCT-11_TRACKER.md), and
[X0 audit](goals/MILA_PRODUCT-11_X0_EXECUTION_AUDIT.md).

Phase D2 now adds a lexical-only explicit intra-source acquisition SHADOW. Exact official coarse
Evidence IDs are revalidated in PostgreSQL and converted to governed `(source_type, session_id)`
pools; bounded direct-turn candidates are emitted only as content-free diagnostics. They do not
change public MemoryContext, continuation frontier, Canonical state, or MCP input/catalog. Migration
`0054_intra_source_shadow` is deployed and the candidate profile runs `SHADOW`. Full Runtime,
fresh PostgreSQL, MCP/client, package builds and three independent subagent boundary reviews pass.
This is an Engineering telemetry baseline, not a P11-C2 effect claim. See the
[D2 completion report](goals/MILA_PRODUCT-11_PHASE_D2_INTRA_SOURCE_SHADOW_COMPLETION_REPORT_20260905.md).

No further Research treatment is eligible on this slice. It must not be reshaped to manufacture
continuation opportunities, and Formal 500 must not be used to fill the denominator. The MCP schema,
Host prompt, Reader, vLLM and Canonical model remain unchanged. See the
[Product-11 Goal](goals/MILA_PRODUCT-11_ExplicitEvidenceAcquisition与NonDestructiveContinuation_GOAL.md).

## Product-10 terminal: instance coverage unresolved

Product-10 completed X0--X2 and ended
`PARKED_PRODUCT10_INSTANCE_COVERAGE_UNRESOLVED`. The sealed 24-case/36-group paired A0 covered
`29/36` instances. X1 established admission loss, and the paired A0 localized three target
`DISCOVERED_NOT_ADMITTED` groups, so B1 was required. The first general
repair produced no new group and lost one; the second admitted all three target groups but displaced
three A0 groups through budget/adjacency changes, including two previously full-coverage cases. Its
mean gain was `+0.04167`, below `+0.05`, and H1's case-level zero-loss guard failed `2 > 0`.

Both effect runs used exact paired candidate pools and passed fresh PostgreSQL, scope/snapshot,
Canonical=0, zero-retry, behavior-neutral trace and cleanup gates. Only 1 A0 / 2 B1 continuation
opportunities were audited, below the required 6, so no continuation migration/frontier was built;
X4 real Codex and formal 500 scoring were not entered. B1 remains default-off. See the
[Product-10 Goal](goals/MILA_PRODUCT-10_InstancePreservingEvidence与Continuation_GOAL.md),
[Tracker](goals/MILA_PRODUCT-10_TRACKER.md), [completion audit](goals/MILA_PRODUCT-10_COMPLETION_AUDIT.md),
[ADR-031](adr/ADR-031-instance-preserving-evidence-continuation.md), and
[acceptance contract](contracts/MILA_PRODUCT-10_X1_X3_ACCEPTANCE_CONTRACT.md).

The MCP package now includes `milai-agent-memory-mcp`, a fixed authenticated Streamable HTTP wrapper
for the one-tool Host reasoning facade. It fixes `agent-memory` and zero automatic retries while
leaving scope, credentials and budget profile Host-owned; the public tool arguments remain `query`
and optional `previous_context_id`.

The sealed second-round scorer originally listed two losses because it disagreed with the rendered
coverage metric on an adjacent hydrated turn. The v2 correction fixes that group undercount to three;
v3 `065812c5…b5659` separately aligns the future H1 threshold with the pre-registered full-case
guard. Neither correction rewrites the sealed run; the H1 failure and terminal are unchanged.

## Product-09 historical terminal and Product-10 audit qualification

The Product-09 historical terminal remains recorded after the Product-10 terminal. Its behavior tree
was the fixed A0 starting point, but its historical result JSON is documentary evidence rather than the
Product-10 matched denominator.

Product-09 recorded the intended product path that Product-08 intentionally left open:

```text
trusted HostAgentEvent
→ PostgreSQL Raw Evidence
→ official projection worker
→ authenticated Streamable HTTP MCP
→ Codex reasoning Host
```

Two runs recorded capture, event-id idempotency, projection, prompt-directed tool behavior and project
isolation on one local synthetic configuration. The restart covered API/worker/MCP, not PostgreSQL;
only the fix target was queried after restart. Three persisted Evidence rows and three projection rows
remained after that application-stack restart, while Canonical tables stayed empty.

A four-case opened-development LongMemEval diagnostic then wrote and projected 1,772 historical
turns using 8 capture workers and ran four Codex calls concurrently. One run recorded normalized
EM/F1 `3/4 / 0.75`: ordinary user lookup, assistant-answer lookup and state update passed;
multi-session set COUNT answered 2 instead of 3. All required sessions were Host-visible. Exact
answer-turn measurement used a Qwen model-assisted, non-human-adjudicated proxy: 3/4 cases were
complete and micro turn visibility was 6/7. These observations do not prove memory-only causality.

A recorded longer-instruction run scored 2/4 and selected an obsolete state value; its exact treatment
identity and replication are not preserved, so this is not a causal effect claim. The product keeps the
shorter P08 instruction and does
not reintroduce EvidenceLedger, internal Reader, generated COMPLETE or case-specific prompts. This is
a bounded documentary diagnostic, not a LongMemEval benchmark claim. The 500-case source files were
read before subsetting, but no formal 500-case scoring run was performed.

See the [Product-09 Goal](goals/MILA_PRODUCT-09_Codex_HTTP持久记忆生命周期_GOAL.md) and
[Tracker](goals/MILA_PRODUCT-09_TRACKER.md). Final Product tree identity is
`557ad090…9171f`; Lab lock digest is `d3c22762…4ae78`. That lock verifies the current behavior tree but
is not embedded in the historical results, so it cannot retrospectively bind their execution bytes.

## Product-08 Codex HTTP MCP baseline complete

Product-08 treats Codex as the reasoning Host. The authenticated `agent-memory` Streamable HTTP profile
accepts only `query` and optional `previous_context_id`, calls the existing governed Runtime, and
renders the result as `memory-evidence-context-v1`. Host Agents decide ordinary answer sufficiency,
form residual queries and write answers. MiLAi retains scope, revocation, time/currentness, routing,
Evidence identity, continuation assertions and retrieval audit ownership. vLLM, EvidenceLedger and
generated `COMPLETE` are absent from this normal path.

P08-0 passes 62 MCP tests including an authenticated child-process HTTP smoke; neutral
Standard/Wide/Research budget names are available and the old OpenWorker names remain exact aliases.
`reader-lite` retains its stdio `access-outcome-v0.1`, so existing OpenWorker behavior is not silently
broken. Real Codex CLI 0.151.0 then passed three black-box Streamable HTTP scenarios: required memory
invoked once, an unrelated arithmetic
control made zero memory calls, and an explicit continuation made exactly two calls with the second
bound to `previous_context_id`; all three final answers were exact. This validates Host integration,
not real-database retrieval quality.

P08 acceptance uses Codex only. Host capture/restart recall and real coding-memory retrieval are
successor work; they do not weaken the completed HTTP transport/facade result. Claude Code is not a
P08 gate and no Claude compatibility claim is made. See the [Goal](goals/MILA_PRODUCT-08_Codex_ClaudeCode_MCP证据上下文产品基线_GOAL.md),
[Tracker](goals/MILA_PRODUCT-08_TRACKER.md), and [ADR-030](adr/ADR-030-host-reasoning-mcp-evidence-context.md).

The earlier Additive Recall / Informational Admission implementation remains default OFF and is now
named `P08-PREBASE-CONTEXT-CANDIDATE`. Its context testkit and pending real-Dense gate are preserved
under [ADR-029](adr/ADR-029-informational-context-admission-and-additive-recall.md); no effect or
formal-holdout claim is made.

## Product-07 terminal: no general Evidence gain

[Product-07](goals/MILA_PRODUCT-07_模型引导证据补全与通用召回_GOAL.md) completed with
`PARKED_PRODUCT07_NO_GENERAL_EVIDENCE_GAIN`. Its query-local, non-persistent RecallWorkspace remains
default OFF and is not selected; current direct behavior is unchanged.

The B1 selector first passed the opened V0 development gate with 11/12 complete EvidenceSets,
0.9167 mean Reader-visible group coverage and zero previously complete losses. Because it recovered
at least one V0 case, the preregistered B2 candidate-ID selector was skipped. The earlier residual
SHADOW remains transport-only evidence: two Qwen calls proposed five queries, but no read was run
because the required evidence was already in the acquired pool.

After freezing B1, the authoritative 24-case R3 Context-only run produced:

```text
A complete / mean group coverage             10/24 / 0.5667
B1 complete / mean group coverage              8/24 / 0.4722
B1 complete / coverage gain over A                -2 / -0.0944
B1 recovered shapes / old-complete losses          2 / 4
any-gold-session recall A / B1                22/24 / 17/24
candidate/order/hydration/budget match        24/24
window-closure match                          22/24
tenant leak / Canonical mutation                0 / 0
```

P07-H1 therefore failed both the required effect direction and zero-regression gates. P07-H2,
residual official reads, D0/D1, Answer/Judge and real OpenWorker Answer effect were not entered.
R3 used the effective Runtime ceiling of 16,384 tokens and made zero hidden model, Provider, Answer
or Judge calls. Formal 500 remains unauthorized and unconsumed.

The final Product tree `17df2c8f...face3` verifies through the Product-owned manifest and
`product07-product-final.lock.json`. No public MCP/API contract, database Schema, permission,
Canonical authority or migration changed. Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA
FREEZE`.

## What exists now

The product repository contains:

- complete `milai-runtime` source and tests;
- the ordered Alembic chain from 0001 through 0049;
- frozen Logical Architecture 1.0 plus its validation evidence closure;
- Python client, MCP, OpenWorker MCP, hooks, LangGraph, and AutoGen packages;
- public Agent contracts and runnable examples;
- local operations, security, backup, credential, projection, deletion, and integration runbooks;
- a product-only CI definition.

The online implementation already covers:

```text
Evidence capture and lineage
Evidence revocation and deletion progress
OperationProposal and Steward review
ClaimVersion / ClaimHead / OpenIssue evolution
FTS and optional dense projection
Canonical Gate and consistency handling
ContextCapsule, MemoryContext and retrieval traces
Runtime, worker and operations CLIs
local MCP and OpenWorker UDS integration
```

## Status that must not be overstated

- The Runtime is a candidate, not a production release.
- Schema 0.1.x is not frozen.
- Authenticated loopback Streamable HTTP MCP is approved for P08. One explicitly authorized public
  candidate is deployed on 7968 with static-Bearer same-project Host registration; it is not a
  general production-network or tenant-isolation approval. OAuth is implemented and tested but
  public activation remains blocked on trusted TLS/gateway routing.
- No project license or OpenWorker image redistribution authorization has been established.
- Real personal data remains blocked until encrypted backup/key-recovery and deletion drills pass.
- Historical benchmark and Goal receipts are not copied into Product and do not act as release
  evidence here.
- Formation and advanced retrieval modules remain in the Runtime source closure, but many are
  default-off experimental paths and are not promised product behavior.

## Latest known usability facts from the source workspace

### Product-06 terminal: Reader transport usable, gain unresolved

[Product-06 v1.1](goals/MILA_PRODUCT-06_Reader集合证据消费与最小执行闭环_GOAL.md) completed with
`PARTIAL_PRODUCT06_LEDGER_REMOVED_READER_GAIN_UNRESOLVED`. It confirmed that
`EvidenceLedgerV01` was a rigid Qwen pre-answer draft contract, not database state: four of the six
unsuccessful final Product-05 Ledger cases were Host calculation-protocol rejections and only two
were semantic misses.

The delivered default-OFF replacement is one bounded `VllmEvidenceReaderSession`. Qwen can answer
directly or request the adapter-internal safe decimal calculator; tool results return through standard
`tool` messages, citations are filtered to Reader-visible aliases, and Reader/provider failures become
one terminal insufficient response rather than an OpenWorker operation repeat. It adds no MCP tool,
database object, QueryIR enum, TypeBinding, or Canonical authority.

The fixed 12-case R2 real-chain run completed 12/12 paired cases on fresh PostgreSQL with 12 isolated
tenants and 24 native OpenWorker operations. After correcting two deterministic scorer false negatives
for valid abstentions, direct and model-native both scored 7/12: no gains, no losses, no unsupported
answers, invalid citations, Host rejections, retries, leaks, or Canonical mutations. Four of the five
baseline-wrong cases lacked at least one required Evidence group in the frozen Reader Context, so a
Reader-only repair could not reach H1 without inventing facts or violating the preregistered ban on
widening retrieval. R3 and the formal 500-case holdout were not entered. Direct remains the default;
model-native is an execution-safe diagnostic, not a reliability claim. Details are in the
[Product-06 tracker](goals/MILA_PRODUCT-06_TRACKER.md).

### Product-05 terminal: lifecycle usable, Reader treatment unresolved

Product-05 now connects the existing `MemoryWriteIntent`/`MemoryWriteHandoff` and an independent
submitter MCP lane to real OpenWorker exchange settlement. The final fresh-PostgreSQL run used two
tenant-bound Runtime/OpenWorker stacks on one database and observed:

```text
source identity / capture / projection       1.0 / 10 of 10 / 10 of 10
restart recall                               2 of 2 tenants
native OpenWorker operations / Qwen calls    5 / 5
assistant support lineage                    1.0
cross-tenant read/write/projection leaks      0 / 0 / 0
duplicate Evidence / self-amplification       0 / 0
model-visible write tools                     0
automatic semantic retries                    0
Canonical mutations                           0
```

The security namespace remains `tenant_id`, supplied by trusted Runtime deployment identity.
`subject_id` remains semantic and cannot select a tenant. This proves two independently configured
local tenant stacks, not single-process dynamic multi-user SaaS.

The fixed-Context Reader ablation did not establish P05-H2. Inventory and one-pass structured
answers missed the preregistered effect gate. Three bounded two-pass ledger repairs remained
unstable: the final 13-case B2 run had four Host calculation-validation rejections; among the nine
completed pairs, ledger improved only one case in one capability family. No method earned the
required three additional correct cases across two families with every safety/consistency gate.
The 24-case S2 confirmation was therefore not entered.

The terminal is
`PARTIAL_PRODUCT05_MEMORY_LIFECYCLE_USABLE_READER_CONSUMPTION_UNRESOLVED`. Direct Reader remains
the default; inventory, one-pass grounded, and two-pass ledger implementations remain default-OFF
experimental paths. Product-05 made no public MCP/API, database migration, permission, or Canonical
authority change, and the formal 500-case holdout was not consumed. Details are in the
[Product-05 tracker](goals/MILA_PRODUCT-05_TRACKER.md) and
[Goal](goals/MILA_PRODUCT-05_OpenWorker记忆闭环用户隔离与集合证据消费_GOAL.md).

Product-02 passed a fresh local Product lifecycle with golden capture/query/trace/revoke flow,
24/24 scenarios, 100/100 warm typed requests, deterministic model-outage fallback, zero governance
leaks, and zero read-path canonical mutations. Read-after-write P95 was 1.096 s and
retrieval-plus-Context P95 was 60.454 ms.

Its sealed matched 128-case run passed every infrastructure, identity, governance, provider and
strict-sufficiency hard gate. The U2 EvidenceSet candidate nevertheless reduced exact answer-turn
coverage from 0.418129 to 0.052632 and Qwen Judge accuracy from 0.265625 to 0.078125. The candidate
is therefore parked default OFF and the simple B0/B1-equivalent baseline remains selected. The
128 entry gate failed, so no 500-case Product/Answer/Judge confirmation was run and the formal
holdout was not consumed.

Post-terminal Lab analysis localized the B2 regression more narrowly. B0 and B2 had identical
accepted references; B2 changed the LOOKUP presentation boundary to `DECISION_ACCEPTED_ONLY`.
Because 114/128 EvidenceSets were empty, average Reader Prompt size fell from 2898.7 to 216.2
tokens and useful Raw Evidence was removed before Context packing. The selected B0 treatment used
`progressive_context_evidence_v0_1=true`, while that Product snapshot's settings default was
`false`. Product-03 subsequently repaired the real OpenWorker usability boundary and selected the
simple wide baseline; Product-02's B2 treatment remains parked and does not define current behavior.

## Split verification state

Latest Product-07 affected-surface closure:

```text
Product-07 affected unit tests                    67 passed
Runtime Ruff / strict mypy / build                PASS / PASS (171 files) / PASS
Runtime full fresh-PostgreSQL suite               868 passed / 4 failed / 2 skipped
Lab tests / Ruff / strict mypy                     59 / PASS / PASS (26 files)
Lab active import boundary / build                PASS / PASS
R3 Context-only path                              24/24 executed; H1 FAIL
R3 tenant leak / Canonical mutation               0 / 0
formal 500                                        NOT ENTERED / NOT CONSUMED
Product final tree / lock                         17df2c8f...face3 / PASS
```

The four Runtime full-suite failures are existing DG11/DG17 query-contract expectation conflicts
(`query_plan` payload redaction, current-query operator completeness, legacy candidate-cap
expectation, and compare-operator abstention). They do not overlap the Product-07 RecallWorkspace
tests, but they keep the repository-wide test gate from being reported as PASS. Two tests skipped
because one optional client package and one additional test URL were unavailable.

Product-06 affected-surface closure:

```text
OpenWorker MCP tests / Ruff / strict mypy     175 / PASS / PASS (14 files)
Lab tests / Ruff / strict mypy                 59 / PASS / PASS (26 files)
OpenWorker and Lab wheel + sdist               PASS
Lab active import boundary                     PASS
fresh PostgreSQL R2 real chain                 PASS (12 tenants / 24 operations)
Product tree / OpenWorker interface            bd5240ab...e694 (319) / e19ef264...e7a (16)
```

Product-05 affected-surface closure:

```text
OpenWorker MCP tests / Ruff / strict mypy     150 / PASS / PASS (13 files)
MCP tests                                      54 passed
Lab tests / Ruff / strict mypy                 56 / PASS / PASS (26 files)
OpenWorker and Lab wheel + sdist               PASS
fresh PostgreSQL two-tenant lifecycle          PASS
Product behavior tree identity                 18e29cd9...a2982 (318 files)
```

Earlier extraction and package snapshot:

```text
Copy-first extraction from legacy workspace      COMPLETE
Legacy workspace mutation                        0
Frozen architecture validate_bundle.py           PASS
Frozen architecture bundle release lock          PASS
Runtime migration files 0001–0049                PRESENT
Product import from evals/scripts                 REMOVED FROM COPIED TESTS
OpenWorker wheelhouse copied                      NO
Runtime Ruff / strict mypy                        PASS / PASS (170 source files)
Runtime unit tests                                717 passed
Runtime wheel + sdist                             PASS
Python client tests                               170 passed
MCP / Hooks / LangGraph / AutoGen tests           54 / 6 / 5 / 6 passed
OpenWorker tests                                  112 passed
All six adapter builds                            PASS
OpenWorker artifact leakage scan                  PASS
Product behavior tree identity                    04b35653...3f20 (311 files)
```

The earlier Runtime count above is its then-current unit suite. Product-02's separate fresh local PostgreSQL gate supplies
its install/start/migration/smoke and lifecycle evidence, while Product-03 V02 adds three isolated
actual OpenWorker/PostgreSQL replays; no production database was touched. Database-mutating
integration tests were not rerun as part of that narrow capacity follow-up. Product-05 now declares
and passes strict mypy for OpenWorker MCP. Release status still depends on the separate security,
recovery, licensing, and distribution gates below.

The Product repository validates the frozen `architecture/v1.0` **bundle** scope. The legacy
project-scope source lock includes research and experiment paths deliberately excluded from Product,
so its failure in this smaller repository is expected and is not a Product release gate.

The non-self-referential behavior tree and eight public interface identities are stored in
`product.manifest.json`. Rebuild it with `python3 tools/build_product_manifest.py` only after an
intentional behavior-bearing source change. The builder carries the legacy source identity as
snapshot provenance and does not read the sibling Lab, Archive, or legacy repository.

Current Product-08 delivery identity is recorded in `product.manifest.json` and the Lab
`product08-host-mcp.lock.json`; regenerate both only after intentional behavior-bearing changes.

Current Product-07 delivery identity: tree
`17df2c8fd601ce497fe8c6913b2bf3b63b1b911082bf95390ddf4281a4fface3` over 320 files;
final Lab lock digest `98a9b091f3053b38615e94e13cefcc890e0e4268bb6ee7f561fd1d2c5151959b`.
The R3 effect result remains pinned to the pre-run behavior tree
`01ad17757beb15f3a27044c8f73fd14c95b3888748e97d6bf1ea0b33f3094612`; the final tree differs only
by the general mypy variable-name repair and regenerated Product manifest, not by post-R3 selector
tuning.

Product-06 identity: tree `bd5240ab89c8ef3d6c16c565e46ba6a22621803e1d0a74856a386ae177d5e694`
over 319 files; OpenWorker interface `e19ef264a231bb54ef95e177e10f125252acc578355d070cd0c54906d99d2e7a`
over 16 files; Product-06 Lab lock digest
`86e79b6c401a10f4f3ce8f3763b319d68f7e854e7dd7e86fb95f9a5c9fd23b1c`. The R2 execution itself
remains pinned to its earlier lock digest `ac578345…fd413`; both locks cover the identical behavior
tree, while the R4 lock records the regenerated Product manifest digest.

## Product-02 terminal decision

Product-01 established S0-S3 local usability, identity/context integrity, grounded-relation repair,
23/24 product scenarios, and 100/100 warm typed requests. Its Product commit `1b5e4a7` was then used
for the matched 128-case S4 run `product01-s4-128-20260901T143318Z`.

S4 completed rather than remaining active. Both arms had `1.0` context success. The B1 candidate
raised evidence-group coverage from `0.6015625` to `0.625` and Qwen Judge accuracy from `0.28125`
to `0.3125`, but session Recall@5 and NDCG@5 decreased, and strict Wrong COMPLETE remained `1`.
The terminal was `FAIL_S4_REPAIR_OR_KEEP_BASELINE`; the 500-case confirmation was not entered.
The metric named `reader_visible_gold_span_coverage` also measured visible gold sessions rather
than exact answer-bearing turns or spans, so it cannot support a span-level claim.

The completed contract is
[MILA-PRODUCT-02](goals/MILA_PRODUCT-02_AnswerTurn证据装配与精准召回_GOAL.md). The user explicitly
authorized execution on 2026-09-02. U0 passed:

- the three inherited dirty files were reviewed and preserved;
- Raw Evidence remains source-ready but cannot independently grant `COMPLETE`;
- completion-shaped operator mappings now require exact MATCH-Binding operand lineage, while legal
  binding-backed time and quantity operators remain complete;
- the former span-named session proxy is now `reader_visible_gold_session_coverage`;
- exact answer-turn and optional exact-span metrics distinguish a session hit from the actual
  answer-bearing source turn;
- 93 affected Product tests, 8 Lab metric tests, exact serialization replay, and Product/Lab import
  boundary checks passed.

U1 then evaluated the direct Dense lane and bounded same-session expansion against the repaired A0
baseline. Product targeted tests proved role/channel opportunity, identity-lineage preservation and
the cross-session/scope/revocation guards. On the retrospective opened-development 8-case slice,
A0/A1/A2 all obtained `0.625` exact answer-turn and Reader-visible answer-span coverage, so neither
treatment earned the `+0.03` effect gate. A1/A2 remain default OFF and A0 was selected. The selected
A0 subsequently passed all 24 outcome-blind identity, serialization, atomic-unit and failure-class
cases with zero Reader/Judge calls and zero canonical mutation.

U2 added internal `LeanRecallPlan`, exact-lineage `EvidenceSet`, AcceptedBinding-only operator
inputs, ordinary/strict sufficiency separation, and role-first atomic Context. Its targeted 8-case
and outcome-blind 24-case gates passed. A recoverable first 128 run then exposed three strict false
COMPLETE cases; the general temporal-anchor and event-compatibility causes were repaired and 68
targeted tests passed.

The authoritative Lab runs are `artifacts/product02-u3-local-final-006` and
`artifacts/product02-u3-longmemeval-128-007`, pinned to Product tree `3c7cc1b1...f5ba`, Lab lock
logical digest `6f286925...8d1b`, and sealed label manifest `6238c10c...1412`.
All hard gates and 384 Answer/Judge calls passed, but B2 lost 0.365497 exact answer-turn coverage,
0.303030 required-role coverage, and 0.187500 Qwen Judge accuracy versus B1; paired accuracy had
1 win, 25 losses, and a 95% bootstrap interval of `[-0.2578125, -0.1171875]`. The terminal is
`PASS_LEAN_MEMORY_USABLE_KEEP_SIMPLER_BASELINE`.

## Product-03 OpenWorker MCP result and immediate priorities

Product-03 v1.1 reached `PASS_OPENWORKER_MCP_USABLE_WIDE_BASELINE` on a fresh local,
synthetic/deidentified stack. Native OpenWorker operations traversed the query-first Host adapter,
real UDS broker/`milai-mcp`, Runtime Context and local Qwen. Relay discovery independently exposed
exactly `milai_memory_resolve` and `milai_recall`.

The Host-owned `OPENWORKER_USABILITY_WIDE_V01` profile uses 50 results, 120 candidates, 8192 Memory
Context tokens, a 2000 ms Runtime search ceiling, 65536 model context, 2048 answer tokens and a 10 s
MCP timeout. It does not relax scope, permission, revocation, identity or Canonical authority.

The representative result is 12/12 semantically correct flows, including cross-session evidence
composition, with 6/6 enabled wins against 0/6 memory-disabled controls and zero scope/revocation/
no-memory leaks. A 32-operation concurrency 4→8 run had 32/32 MCP attempts and contexts, zero MCP
failure, timeout, OOM or queue saturation. Broker replacement produced a new socket inode; the old
Worker did not follow it and an explicit recreate recovered. Full affected checks passed: Runtime
`774 passed, 1 skipped`, Python Client 165, MCP 52 and OpenWorker 106, plus Ruff, configured mypy,
four package builds and the locked image build.

Because the wide simple baseline passed OW1 and OW3, the pre-authorized comparison rule did not call
for T1. T1 remains default OFF. Product-03 is complete; Product-04 now addresses the narrower
semantic-contract problem before any budget/latency sweep. B2, advanced Formation/Graph/ReFind,
public API/Schema changes, remote MCP and the 500-case formal holdout remain outside this result.
The detailed result is in the Product-03 Goal; private operation linkage and summaries remain in the
corresponding Lab run directory.

A post-terminal corrective replay then used one opened-development LongMemEval case with 44 real
source sessions and 466 material turns. It first proved that explicit WIDE reads were still being
clamped by Runtime defaults, then proved that Host discarded a valid Runtime-owned Context after MCP
diagnostic compaction. The repaired path now treats non-empty explicit reads as `REQUIRED` while
keeping auto prefetch `POSSIBLE`, and directly accepts authenticated
`GOVERNANCE_ADMITTED_SOFT_RANKED` Runtime Context without granting typed completion authority.

The final actual OpenWorker operation used the requested 120-candidate / 8192-token / 2000-ms plan,
the run-local corrective summary reports 20 selected governed Evidence units including the gold
source, compiled 24,576 bytes / 5,858 memory tokens, and returned the exact answer through one local
Qwen call. Runtime remained `PARTIAL`; MCP
calls were 1, automatic retries 0 and Canonical mutations 0. This is a single-case usability result,
not a general LongMemEval accuracy claim, and the formal 500-case holdout remains untouched.
The corrective affected-surface gate passed: Runtime intent tests 30, Python Client 167,
OpenWorker 106 and Lab 46, plus relevant Ruff, strict Runtime/Python-Client mypy and Product pin
verification.

### Expanded-budget V02 candidate

`OPENWORKER_USABILITY_WIDE_V02` is now available as an explicit, default-OFF local deployment
profile. It preserves the 50-result / 120-candidate plan while raising the Runtime presentation
ceiling to 16,384 Context tokens and 5,000 ms. The V02-only MCP wire ceiling and the Host's explicit
context ceiling are both 262,144 bytes/characters; model context remains 65,536 and answer output
remains 2,048 tokens. Omitting the broker profile preserves ordinary Product defaults.

Three isolated opened-development replays traversed the actual OpenWorker product path. Two large-
haystack ordinary lookups (439 and 466 turns) passed with one MCP resolve and one Qwen call each.
The 484-turn multi-session collection/count case also reached Qwen once with 11,604 governed memory
tokens, but Runtime honestly remained `PARTIAL / UNBOUNDED` and the answer was incorrect. Exact case
identities remain in the restricted Lab manifest rather than Product documentation. This changes the
failure from unavailable memory to best-effort partial availability; it does not establish object/set
semantics, accepted Binding or completeness.

Immediate priority is therefore usability and semantic correctness, not a budget/latency sweep:
retain V02 as opt-in, keep soft `PARTIAL` evidence provider-visible without converting it to typed
`COMPLETE`, and address object-instance/member identity only through a general representation and
dedup contract. No case-ID, reference answer, synonym or domain-specific route was added. The formal
500-case holdout remains unauthorized and untouched.

## Product-04 terminal implementation

Product-04 replaced the failed Raw TypeBinding direction with a planning-only contract and a usable
Reader boundary:

```text
query
→ QueryTaskContractV01
→ QueryExecutionPlanV01
→ MemoryQueryIRV02 compatibility projection
→ official acquisition / Governance
→ Memory Availability
    ├─ Raw natural language → Reader
    └─ externally verified structured operand → deterministic Operator
```

The contract describes operation preference, output shape, explicit source/time constraints and
retrieval hints. It does not prove subject/action/relation semantics in Raw prose. Unknown memory
computations now fall back to governed Reader recall instead of becoming an unavailable query.
Trusted `PARTIAL` or `ABSTAINED` soft Context is Provider-available after denial, open-issue and
infrastructure checks. Raw prose never becomes a deterministic operand or grants `COMPLETE`.
The progressive read can stop on this availability signal without spending another channel call;
its terminal Sufficiency remains `PARTIAL` or `UNSATISFIED`.

The implementation is deliberately internal. It does not change public request/response JSON, MCP
contracts, PostgreSQL Schema, permissions, revocation or Canonical authority. The terminal is
`PASS_PRODUCT04_READER_AVAILABILITY_WITHOUT_TYPEBINDING`: Runtime unit 717, Python Client 170, MCP
54 and OpenWorker MCP 112 tests passed; the Runtime and affected integration builds, Ruff, configured
strict mypy, public
serialization checks and frozen architecture validation passed. The current non-self-referential
Product tree and all seven public interface identities are recorded in `product.manifest.json`.

The three opened Product-03 diagnosis families now retain a governed Reader path whenever evidence
is available. Count and other structured-looking Raw questions remain `PARTIAL/UNSATISFIED` inside
Runtime rather than being computed from regex Binding. This preserves answerability through Qwen
without forging a deterministic result.

Product-04 did not launch a native OpenWorker/Qwen black-box replay before its terminal. A later
two-case replay on the Product-04 tree supersedes Product-03 only as the latest real-chain diagnostic;
it does not alter Product-04's terminal claim or establish LongMemEval accuracy.
The formal 500-case holdout remains unauthorized and untouched; WIDE_V02 and experimental retrieval
remain default OFF.

## Rollback

This split is copy-only. The legacy `/cra/memory/mx_memory/MiLAi` workspace remains the recovery
source. Removing or disabling the new Product directory does not alter the legacy code or data.
There has been no database migration or canonical mutation as part of repository extraction.
