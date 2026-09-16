# MiLAi Agent Integration 0.1 independent review

> Reviewer identity: `/root/af09_independent_review`  
> Independence: separate no-history sub-agent; did not author candidate  
> Review start: `2026-08-17T13:21:03Z` / `2026-08-17T21:21:03+08:00`  
> Review finish: `2026-08-17T13:46:26Z` / `2026-08-17T21:46:26+08:00`  
> Decision: **REVISE**  
> Open findings: **P0 1 / P1 4 / P2 0**

## 1. Scope, method and candidate identity

This is an independent, evidence-first review of the current bytes. Author preflight, release-candidate
reports and the author requirements matrix were used only to locate evidence; their conclusions were
not treated as proof. I read the complete current
`MiLAi_可用性与Agent接入设计开发文档_v1.md`, including UA-00 through UA-08, section 17 and
sections 19.1 through 19.7, and inspected the Agent contracts, SDK/lifecycle, MCP, LangGraph,
AutoGen, hook, Runtime authorization/retrieval/Evidence/Proposal/UI/crypto/embedding/operations,
tests, runbooks, threat models, package artifacts, reports, inventory builder, secret scanner and CI.

The pre-edit candidate identity was:

| Object | SHA-256 / identity |
|---|---|
| `docs/reports/UA-current-byte-inventory-2026-08-17.json` | `ca673a7ec303465223c88819c098c4e5155450220c5a0ad958d447dbf922befb` |
| inventory entry count | `319` |
| inventory canonical `entries_sha256` | `549d90c81b5b960b1f54626271794223509cb2f9d5de34ecf01f720e9d78d73c` |
| UA design | `3369efa9e3e13d34fa02266353980063100b4a4fab59549247fcf0884126cdee` |
| Runtime fresh-DB report | `81d1b49c9d687301843843c2efcacc85a5381170fe8a6bdacb7f09e2e59647d6` |
| three-session E2E report | `1d3d42325428dd8a0b96c9ab5bac6b7d5475e42ec9b1b7bb5b9dd5b5fc600bea` |
| clean-install report | `fedda8bb814a0b07d2745b96eb07be11c03e0941f33c9b785619f2aed2b19c73` |
| package release manifest | `5c747eafaff0de3c14bba921f3c54768998a2d7b3c89a5c6980eded19491628a` |

Review environment: Linux `5.15.0-86-generic` x86_64, Python `3.11.13`, Ruff `0.16.3`, mypy
`1.20.2`, pytest `8.4.2`, PostgreSQL/pgvector 16/0.8.2, loopback Runtime on port 28080. No secret
value was printed or copied into this record.

I independently recomputed every listed file's size and SHA-256, verified regular safe relative paths,
sort order and uniqueness, and recomputed the canonical entries digest. All 319 listed entries match.
That proves internal consistency of the list, not completeness or release safety; findings UA-F01 and
UA-F02 show why those are different claims.

The frozen Logical Architecture release was treated as an immutable upstream boundary, not rewritten
for Agent Integration. Its structural validator passed and the following external identities matched:

| Frozen object | SHA-256 |
|---|---|
| `architecture/v1.0/architecture_manifest.json` | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` |
| frozen release archive | `dc43e4a5facb6037e14a98ca4f50e26a8bb599c3bd38440e8bcbd3869a3e4ff1` |
| frozen release receipt | `15c98d883e5048719898f91cb0f4f4aaa994f422311141d6d77ac4d6a79febc4` |
| independent release verification | `5643c3bac6a114b48170dd1b6ddb5e035c8aa1cd579393e29c3b8ec50768f10d` |

The old frozen all-workspace source locks are expected to differ after the separately governed Agent
Integration work. I did not refresh them or misrepresent such expected drift as a failure of the frozen
logical architecture.

## 2. Findings

| ID | Severity | Finding and exact evidence | Required change | Re-verification |
|---|---|---|---|---|
| UA-F01 | **P0** | The retained and inventory/manifest-authorized Runtime sdist is a credential-bearing workspace dump. `integrations/package-release-manifest.json:14-16` and the byte inventory at `:894-896` bind `runtime/dist/milai_runtime-0.1.0.tar.gz`, SHA `10f194cb3bd78c9d00cb97ba9add8aee1be1c3146182b983e5daf0de183a32c1`, size `332884607`. Independent `tarfile` inspection found 188 regular members: an exact copy of live `runtime/.env` (archive-member SHA equals local file SHA `928979125a13cb31b3342eab6407ef6debe0f084dac7bfe6e9d27a8d2a919ba7`), with 35 populated fields including DB URLs/passwords, API/causal/reader/submitter/operator/reviewer credentials and the Blob KEK; 3 backup members; 1 live Blob; 26 cache members; 4 logs; and 13 smoke reports. No values were displayed. `scripts/scan_ua_secrets.py:8-19,47-78` reads a compressed archive as opaque bytes, so its reported `PASS` (`17` secret values, `288` files, zero matches) is a false negative. | Quarantine/destroy the unsafe sdist and treat all embedded credentials and KEK as exposed: rotate them before reuse. Add explicit sdist include/exclude policy and build only from a clean, staged source set. Recursively inspect/decompress every retained archive for exact secrets and prohibited members. Rebuild all affected artifacts, then regenerate package manifest and UA inventory. Do not release any artifact descended from these bytes. | A fresh clean-room build must yield a deterministic sdist containing no `.env`, secret value, backup, Blob, cache, log, runtime report or local state; an archive-aware exact-secret scanner must fail on a seeded compressed-secret negative fixture and pass the rebuilt artifacts; rotated credentials must be accepted and old credentials rejected; clean install and manifest/inventory digest checks must pass. |
| UA-F02 | **P1** | The 319-entry inventory is internally valid but not complete or policy-conformant. `scripts/build_ua_inventory.py:9-37` omits the exact-role bootstrap/config `runtime/docker/initdb/010_roles.sh` (current SHA `38094279bef383a8d7adfabe46b417962380aab91e157a7c6087f176d5ab2593`) and root `.gitignore`, while `:38-50` does not exclude a `.cache` path component. Consequently inventory lines `1509-1519` include three Hugging Face `.cache` files. The builder also silently ignores a named include target that is absent instead of failing. The omitted Docker script is operational source used to establish four least-privilege roles, not disposable state. | Define an explicit complete candidate root set including Docker/bootstrap and relevant build configuration; reject every missing required include; reject `.cache`, env, venv and other local/generated state at any depth; enumerate the intended immutable model payload separately from downloader cache; regenerate and independently re-audit the inventory. | Independent exhaustive enumeration over the declared release roots must have zero missing/extra files, zero forbidden path components, safe/sorted/unique paths and exact per-file size/SHA/root. Add negative tests for missing include targets, nested `.cache`, symlinks and archive-contained forbidden files. |
| UA-F03 | **P1** | The current candidate layout does not pass its checked-in Runtime static command. CI specifies `uv run ruff format --check .` at `.github/workflows/ci.yml:79-84`. Replaying the equivalent command with `--no-cache` failed: two model/cache README code blocks would be reformatted, including `runtime/var/models/all-MiniLM-L6-v2/README.md:51`; only 116 files were reported formatted. Source-scoped `src tests migrations` Ruff format/check and strict mypy all passed, so this is a gate/scope failure, not a Runtime Python-source defect. | Make the CI/static scope explicit and consistent with the release inventory, or configure audited exclusions for immutable model/data assets and caches. Do not make a nominal `.` gate depend on whether ignored/generated files happen to exist. | Run the exact checked-in CI commands against the exact staged release tree and a clean checkout; both must pass, with an assertion that all intended Python sources and no model/cache payloads are selected. |
| UA-F04 | **P1** | The framework references do not enforce the accepted host-fixed Scope/authority boundary. The threat model says the host owns fixed Scope and required authority and neither is a model field (`docs/security/agent-tool-threat-model.md:8-12`), and section 17 requires that a model cannot set credential scope (`MiLAi_可用性与Agent接入设计开发文档_v1.md:1467-1475`). But `integrations/langgraph/src/milai_langgraph/nodes.py:12-23` reads scope, authority, consistency and limit from mutable graph state; `integrations/autogen/src/milai_autogen/memory.py:29-49` reads them from each query's open-ended kwargs. An adversarial in-process replay demonstrated both adapters forwarding caller-supplied broad scope, `USER_CONFIRMED`, `EVENTUAL` and limit 20 unchanged. Runtime tenant/capability checks remain present, so this did not demonstrate cross-tenant access, but the documented defense is absent at the adapter boundary and safe use depends on every downstream graph/orchestrator preventing model-controlled values. | Bind allowed Scope, required authority, consistency floor and maximum limit in immutable host configuration when constructing each adapter/node. Model/framework state may supply only the query (and narrower values after deterministic validation), never broaden or weaken host policy. | Add adversarial LangGraph and AutoGen tests that place broader Scope, changed authority, weaker consistency and excessive limits in model/state/kwargs and prove they are rejected or narrowed to the host policy. Re-run the same cross-adapter E2E. |
| UA-F05 | **P1** | The promised local deterministic ProposalDraft validation is bypassable on actual framework/tool paths. The design requires every extracted draft to pass local Pydantic validation and carry model identity, template, input snapshot hash, evidence branches, Scope/authority and expected head (`MiLAi_可用性与Agent接入设计开发文档_v1.md:580-598`). `ProposalDraft` implements those checks (`integrations/python-client/src/milai_client/models.py:370-465`), but `AgentMemory.create_proposal` accepts a raw dict and forwards it unchanged (`lifecycle.py:245-255`); LangGraph takes `proposal_candidate` directly from state (`integrations/langgraph/src/milai_langgraph/nodes.py:103-113`); MCP accepts an arbitrary dict and forwards it (`integrations/mcp/src/milai_mcp/server.py:227-250`). Server validation prevents direct canonical application and review remains separate, but it permits optional model/template identity and does not establish the client-side extraction snapshot guarantee. | Require `ProposalDraft.model_validate` at every model/extractor/framework candidate boundary, or separate an explicitly typed human-authored proposal path that cannot be reached from model state/tool input. Preserve the validated canonical serialization and snapshot identity through retries. | Negative tests must prove raw/missing/spoofed model identity, template, snapshot hash, Evidence overlap, authority mismatch and stale expected head are rejected before any HTTP call; valid drafts must serialize identically across SDK/MCP/framework retries. |

UA-F01 is independently sufficient to block promotion. UA-F02 and UA-F03 also make DoD 11 false.
UA-F04 and UA-F05 are defense-boundary gaps that must be resolved even after repackaging.

## 3. Independently replayed commands and results

All Python/pytest/Ruff invocations used `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`,
`ruff --no-cache` or `mypy --cache-dir=/dev/null` as applicable. Temporary virtual environments and
the fresh PostgreSQL database were outside candidate roots and removed. The first database harness
attempt used a name rejected by the product's safety validator and aborted before creation; the rerun
used the required `milai_smoke_` prefix.

| Gate / command (abridged, no secrets) | Independent result |
|---|---|
| SHA-256 of inventory/design/four named reports/package manifest | All exact expected values matched. |
| Python inventory verifier: regular safe paths; sorted/unique; every size/SHA; canonical entries digest; independent declared-root enumeration | Listed bytes `PASS`: 319, no per-entry drift, recomputed root `549d90...d73c`. Completeness policy `FAIL` per UA-F02. |
| Package-manifest independent per-lock/per-artifact size/SHA verification | `PASS`: 6 packages, 12 artifacts, zero digest/size mismatch. It faithfully authenticates the unsafe Runtime sdist. |
| Archive inspection with `tar -tzf`, `tar -xOzf .../.env \| sha256sum`, and Python `tarfile`/`zipfile` member audit | `FAIL`: UA-F01; no unsafe traversal names, but secret/local/cache members are present. Other five sdists and all six wheels had no prohibited path component; all typed packages contained `py.typed`. |
| `scripts/scan_ua_secrets.py --env-file runtime/.env` | Reported `PASS`, 17 unique secret values / 288 files / zero paths; adversarial archive inspection proves this is a false negative. |
| Python-client Ruff format/check, strict mypy, pytest | `PASS`: 10 files formatted; lint pass; 7 typed source files; **20 passed**. |
| MCP package same gates | `PASS`: 4 files; 2 typed source files; **6 passed**. |
| LangGraph package same gates | `PASS`: 3 files; 2 typed source files; **2 passed**. |
| AutoGen package same gates | `PASS`: 3 files; 2 typed source files; **2 passed**. |
| Hooks package same gates | `PASS`: 4 files; 3 typed source files; **2 passed**. |
| Four executable synthetic examples | Generic, official MCP client, LangGraph and AutoGen all `PASS`. |
| Runtime `ruff format --check --no-cache .` | `FAIL`: two model/cache README files would be reformatted; UA-F03. |
| Runtime source-scoped Ruff format/check and strict mypy (`src tests migrations`) | `PASS`: 115 files formatted, lint pass, 60 typed source files. |
| Fresh disposable exact-role PostgreSQL full suite, migrations through 0027 | **142 passed in 78.65s**; exit 0; zero connections before drop; owner `milai_owner`; drop `PASS`. |
| Six fresh temporary venv wheel installs, Python `-I` imports, PEP 561 check | All six `PASS`; wheel hashes matched the clean-install report. This validates wheels, not the unsafe sdist. |
| ONNX benchmark replay on the current local model/13 fixtures | deterministic `0.5384615`, ONNX `0.8461538`, gain `0.3076923`, failure rate `0`, identity `cacae453...4bc7`; result agrees with the recorded quality gate (timing is observational, not an SLO). |
| `milai-ops doctor --json --env-file .env` | `PASS`: 17 PASS / 0 WARN / 0 BLOCKED; exact roles, 0027 head, zero projection lag/dead letters, live/ready and Agent v1 negotiation. |
| `milai-ops status --json --env-file .env` | `PASS`: reader capability, loopback/stdio only, remote/multi-agent false, `SYNTHETIC_ONLY`, Runtime `CANDIDATE`, Schema `0.1.x EXPERIMENTAL / NO-GO`. |
| Frozen `architecture/v1.0/scripts/validate_bundle.py` and external release hashes | Structural validator `PASS`; frozen identities match section 1. No frozen manifest was refreshed. |

The named three-session report was not accepted merely by filename. Its exact bytes were hashed and
its fields inspected: generic SDK, official MCP stdio protocol `2026-07-28`, independent JSON-RPC wire
host `2025-11-25`, LangGraph and AutoGen read are listed; Session 1 is pre-review `ABSTAINED`; Session
2 preserves the `OPEN` issue, both branches, discharge rule and unchanged head; Session 3 returns
`GROUNDING_BLOCKED` after revoke and records completed purge/erase; `hard_failures` is empty and the
temporary database cleanup has zero connections. The current source's constituent adapter tests and
fresh 142-test Runtime suite were independently replayed.

## 4. UA-00 through UA-08 verdict matrix

| Slice | Independent verdict | Current evidence and boundary |
|---|---|---|
| UA-00 design/permission preflight | **REVISE** | ADR-020/021/022, Agent v1 compatibility policy, exact server capabilities and no-integration-DB-import test are present; no adapter exposes review/direct Claim DML. Host-fixed framework policy is contradicted by UA-F04. |
| UA-01 bootstrap/doctor | **PROVEN for current implementation** | Live doctor/status passed; fresh exact-role PostgreSQL 142/142 and cleanup passed; loopback, role, migration, Blob and worker checks fail closed in the suite. This does not cure the release sdist. |
| UA-02 contract/SDK | **PROVEN for wheel/source** | Versioned OpenAPI/tool contract, sync/async client, typed envelopes/errors, bounded retry with identical key/payload, 409 no retry, partial Evidence/Proposal outcome, clean install and PEP 561 all replayed. |
| UA-03 lifecycle/governed write | **REVISE** | Capture modes, model-output rejection, secret pattern rejection, stable operation IDs, Episode refs and pending-review link pass. Extracted ProposalDraft validation is bypassable (UA-F05). |
| UA-04 MCP stdio | **PROVEN within local stdio boundary** | Exact reader/submitter/operator catalogs, no reviewer/direct/bulk tools, strict unknown args, sorted tools, current/preceding protocol, reconnect and sensitive literal checks pass; report binds both official and independent-wire hosts. Remote HTTP remains disabled. |
| UA-05 framework references | **REVISE** | Generic/LangGraph/AutoGen/hook tests and examples pass; the exact three-session report preserves trace/OpenIssue/revoke behavior and checkpoint references. UA-F04 and UA-F05 leave the reference adapter boundary incomplete. |
| UA-06 retrieval quality | **PROVEN for the declared fixture/device boundary** | ONNX identity/0027 path, independent 13-case quality gain, zero failure, CPU/local-only policy and Runtime outage/fallback safety tests pass. This is not an SLO or external-provider authorization. |
| UA-07 Local Private Beta | **NO-GO** | Crypto, rotation, tamper/wrong-key, server-side classification, import dry-run and restore paths are exercised by the 142-test suite, but user approval and environment-specific independent recovery acceptance are absent as documented. UA-F01 additionally leaks the current KEK/credentials into a retained artifact, so no private-data promotion is permissible. |
| UA-08 release candidate | **REVISE** | Exact reports and wheels are reproducible, but the retained sdist is unsafe, the secret scan is unsound for archives, inventory is incomplete/contains cache, the exact current static gate fails, and open P0/P1 findings remain. |

## 5. Section 17 and section 19 gates

| Requirement | Verdict | Evidence |
|---|---|---|
| 17.1 client contract | **PROVEN** | Client 20 tests plus independent source inspection/replay cover negotiation, envelopes, budgets, typed errors, retry/idempotency, partial outcome and close. |
| 17.2 MCP | **PROVEN within stdio/local scope** | MCP 6 tests, exact catalogs, two protocols, official/independent hosts in E2E, output caps and profile-substitution rejection. |
| 17.3 lifecycle | **PROVEN except ProposalDraft boundary** | Capture/model-output/idempotency/Episode behavior passes; UA-F05 remains. |
| 17.4 framework | **REVISE** | Checkpoint separation, recall/context, interrupt and AutoGen clear/read tests pass; host-fixed policy and candidate validation fail UA-F04/F05. |
| 17.5 security | **REVISE** | Real-role/cross-tenant/revoke/remote/data-mode tests pass, but UA-F01 is a credential release and UA-F04 contradicts the stated adapter control. |
| 17.6 three-session E2E | **PROVEN for synthetic/de-identified candidate** | Exact machine report content/hash plus independent constituent tests; OpenIssue branches and rejected/stale candidate semantics remain visible, revoke is fail closed and cleanup passes. |
| 19.1 UG-01 | **PROVEN for source/runtime** | Doctor/status and fresh database suite pass. Unsafe packaging is handled under UA-08/DoD 11. |
| 19.2 IG-01 | **PROVEN for SDK wheel** | Contract, package-local quality and clean isolated install pass. |
| 19.3 IG-02 | **PROVEN** | Local stdio/two-host/profile/negative/protocol evidence passes. |
| 19.4 IG-03 | **REVISE** | Same E2E semantics are evidenced, but reference policy boundaries require UA-F04/F05 remediation. |
| 19.5 QG-01 | **PROVEN within benchmark boundary** | Reproduced quality gain and full safety suite; external cost zero/local CPU. |
| 19.6 SG-01 | **NOT SATISFIED / LOCAL PRIVATE BETA NO-GO** | Missing user approval and environment-specific independent recovery acceptance; UA-F01 is an additional blocking regression. |

## 6. Agent Integration Beta DoD 1-14

| DoD | Verdict | Independent basis |
|---:|---|---|
| 1 | **PROVEN for current source/runtime** | Live 17-check doctor/status and fresh 142-test exact-role database. |
| 2 | **PROVEN** | SDK/MCP retrieval plus E2E Gate/OpenIssue behavior. |
| 3 | **PROVEN** | RecallEnvelope, formatter, MCP/framework outputs and E2E preserve abstention/degraded/trace; top-level OpenIssue IDs include rejected-candidate outcomes. |
| 4 | **PROVEN** | Agent profiles expose only Evidence capture/Proposal submit; server capability negatives deny submitter review; no direct canonical mutation tool or DB access. |
| 5 | **PROVEN** | Identical payload/key bounded retries, 409 stop, hook/Episode replay and server idempotency tests. |
| 6 | **PROVEN** | Capture policy and AutoGen/lifecycle negatives reject model/assistant output as Evidence; no path auto-creates a Claim. |
| 7 | **CONTRADICTED at release boundary** | No model-context/log leak was observed in normal adapter behavior, but UA-F01 packages all configured token/DB credentials and the KEK into the retained sdist, a stronger credential disclosure than this DoD is intended to prevent. |
| 8 | **PROVEN** | Session 3 and Runtime tests show immediate canonical block/`GROUNDING_BLOCKED`, followed by purge/erase. |
| 9 | **PROVEN** | Exact report covers generic + official/independent MCP + LangGraph and AutoGen read with independent current constituent replays. |
| 10 | **PROVEN** | Runtime AST boundary and lock contain no external memory framework; external projects remain reference/import input, never canonical authority. |
| 11 | **CONTRADICTED** | UA-F01/UA-F02: unsafe opaque package contents, omitted Docker/build config and included cache mean there is no complete policy-conformant current-byte inventory. |
| 12 | **PROVEN** | Design, live health/capabilities and known limitations all state Runtime `CANDIDATE`, Schema `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`. |
| 13 | **PROVEN as a prohibition** | Live mode/report are `SYNTHETIC_ONLY`; Local Private Beta remains explicit NO-GO. No real-data authorization is inferred from crypto implementation. |
| 14 | **CONTRADICTED** | This independent review has one open P0 and four open P1 findings. |

## 7. Final decision and permitted boundary

**REVISE.** The current bytes must not be promoted to `MiLAi Agent Integration 0.1 Beta`, even for
synthetic/de-identified use, because the retained Runtime sdist contains live credentials/local state,
the inventory is not complete/policy-conformant, the current candidate layout fails its exact static
gate, and framework host-policy/draft-validation gaps remain.

This decision does not alter or reopen the frozen Logical Architecture 1.0.0. It also does not promote
the Schema, Runtime, remote access, multi-Agent governance or real-data use:

```text
Logical Architecture 1.0.0: FROZEN and unchanged
Schema 0.1.x: EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
Runtime 0.1.x: CANDIDATE
Remote access: DISABLED
Multi-Agent governance: DISABLED
Local Private Beta: NO-GO
Synthetic/de-identified Agent Integration 0.1 Beta: REVISE / NOT PROMOTED
```

After all five findings are closed, a new immutable candidate identity, archive-aware secret scan,
clean staged artifacts, complete inventory and fresh independent review are required. DoD 14 cannot be
self-closed by the author.

## 8. Post-review chain of custody

The only repository file added by this review is this record under `docs/reviews/`, which is outside
the candidate inventory include set. No candidate source, contract, test, package, report, inventory,
manifest, design, frozen bundle or existing review was modified. Post-write verification must retain:

```text
inventory file SHA-256: ca673a7ec303465223c88819c098c4e5155450220c5a0ad958d447dbf922befb
entry count: 319
entries SHA-256: 549d90c81b5b960b1f54626271794223509cb2f9d5de34ecf01f720e9d78d73c
per-entry drift: 0
```
