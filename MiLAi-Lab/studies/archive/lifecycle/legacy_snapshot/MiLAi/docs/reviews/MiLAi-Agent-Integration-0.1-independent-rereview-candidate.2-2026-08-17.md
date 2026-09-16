# MiLAi Agent Integration 0.1 candidate.2 independent re-review

> Reviewer identity: `/root/af09_independent_review`  
> Independence: separate no-history sub-agent; did not author candidate  
> Review start: `2026-08-17T14:54:51Z` / `2026-08-17T22:54:51+08:00`  
> Review finish: `2026-08-17T15:19:10Z` / `2026-08-17T23:19:10+08:00`  
> Decision: **PASS**  
> Open findings: **P0 0 / P1 0 / P2 0**

## 1. Scope, independence and decision rule

This is a fresh, adversarial re-review of Agent Integration `0.1 candidate.2`. The prior independent
`REVISE` record is the finding baseline, not proof that remediation works. Author matrices, report
titles and test names were used only to locate evidence. Conclusions below are based on current source
inspection, independently recomputed bytes and independently executed behavior.

The re-review read the current Agent Integration design, the implementation contract and applicable
repository instructions, then re-audited UA-00 through UA-08, section 17, sections 19.1 through 19.7,
and especially the five prior findings UA-F01 through UA-F05. The review covered the frozen logical
architecture boundary, Agent contracts, Runtime migrations/source/tests/config/model/artifacts,
SDK/lifecycle, MCP, LangGraph, AutoGen, hooks, examples/evals, security/runbooks/reports, CI, package
locks/manifests, secret scanner and current-byte inventory.

`PASS` here means only that the synthetic/de-identified Agent Integration Beta gate has no open P0 or
P1 and DoD 14 is now satisfied. It does not approve real personal data, remote transport, multi-Agent
governance, Schema freeze or Production readiness.

## 2. Candidate identity and chain of custody

The candidate identity was recorded before this review wrote any file:

| Object | SHA-256 / identity |
|---|---|
| current-byte inventory file | `debb9c2edd90bd072a2d2f3d28d671efd6875d5fda696ae2d55d0ab02a8a25ce` |
| inventory entry count | `322` |
| inventory canonical entries root | `d4f2cdcd52c2d702b8ee3d568c3b54ec39bc83a0e719e8cd79af6db1f669842f` |
| Agent Integration design | `2742f921135780e0ef57cdea5c905a8df87f46f4629a8770ca7baa280db71a9e` |
| package release manifest | `84c947394f3bcfb2132a9f8cc88dc724ffe69fc0b1dc11693a9fb69d97e3a4ef` |
| retained fresh-DB report | `0d9d5732bf34f5ff1e0c0601e8b1cefd3ae435172a5d278e84e2ee8a5f3efd2f` |
| retained three-session report | `4ca8bcde322569a7845912663114d61642eecde4e28865e91bfe9e6648448609` |
| retained clean-install report | `3f2bd3cecab9440e1b6dedc4e2933619bf1cf4200150523f368a876eb141ec7e` |
| prior independent `REVISE` review | `98fa21e4318da6234eef639d1addca4cd027e0d7bb83db5851bbeb97f393d999` |
| frozen architecture manifest | `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` |

Review environment: Linux `5.15.0-86-generic` x86_64, Python `3.11.13`, Ruff `0.16.3`, mypy
`1.20.2`, pytest `8.4.2`, PostgreSQL/pgvector 16/0.8.2 and a loopback Runtime. No credential,
password, bearer token, causal secret or KEK value was printed or copied into this record.

An independent implementation, rather than the inventory builder's conclusion, enumerated every
declared release root. It verified all 322 safe regular paths, lexicographic ordering, uniqueness,
per-entry byte size and SHA-256, then recomputed the canonical JSON entries root. The declared roots
and the inventory were equal: zero missing, zero extra, zero symlink and zero forbidden env/cache/venv
path. Root `.gitignore` and `runtime/docker/initdb/010_roles.sh` are both present. This was repeated
after all dynamic gates and produced the same inventory file SHA and entries root.

## 3. Prior-finding disposition

| Finding | Disposition | Independent evidence and adversarial result |
|---|---|---|
| UA-F01, P0 — leaked Runtime sdist and unsound scanner | **CLOSED** | The old `332884607`-byte artifact and SHA `10f194cb3bd78c9d00cb97ba9add8aee1be1c3146182b983e5daf0de183a32c1` are absent from the repository and all 12 retained artifacts. The current Runtime sdist is `252401` bytes, SHA `8794145a8dc2808d69c838dce84f7f78bbdc0662daa686d4a2bf29d8be839e37`, with 131 regular members restricted to packaging metadata plus `.env.example`, `.python-version`, Docker bootstrap, migrations, source, tests and locks. Independent extraction of every wheel/sdist found no live `.env`, `var`, Blob, backup, log, cache, nested `dist`, unsafe path/link or any of 17 current configured secret values. The archive-aware scanner passed the candidate and an independently constructed tar→zip→payload compressed-secret counterexample was detected at the exact nested member. `runtime/pyproject.toml:43-67`, `scripts/scan_ua_secrets.py:15-33,62-225`, and `tests/test_release_safety.py:31-95` implement the current boundary. |
| UA-F02, P1 — incomplete/cache-bearing inventory | **CLOSED** | `scripts/build_ua_inventory.py:9-47` names the complete roots and exclusions; `:50-75` rejects missing roots and symlinks. Independent enumeration exactly matched 322 entries and proved `.gitignore` and the exact-role bootstrap are included while `.cache`, venvs, tool caches, `__pycache__`, live `.env` and symlinks are absent. Missing-root, nested-cache and symlink negatives passed in the eight-test release-safety suite. |
| UA-F03, P1 — checked-in CI static scope failed | **CLOSED** | The checked-in Runtime scope is now exactly `src tests migrations` (`.github/workflows/ci.yml:79-84`); format, Ruff and strict mypy passed current bytes. The frozen step sets bundle scope for the entire step and verifies the external manifest anchor (`:86-96`); validator, lock and 19 adversarial tests passed. CI also contains the five-package integration matrix and allowlisted Runtime build/archive scan (`:118-149`). |
| UA-F04, P1 — model-controlled framework recall policy | **CLOSED** | `AgentRecallPolicy` freezes a canonical JSON copy of host Scope and fixes authority, consistency floor and maximum limit (`integrations/python-client/src/milai_client/models.py:17-72`). Generic tools always use it; LangGraph rejects policy keys from state (`integrations/langgraph/src/milai_langgraph/nodes.py:10-31`); AutoGen rejects scope/authority/consistency/limit kwargs (`integrations/autogen/src/milai_autogen/memory.py:34-62`); MCP omits Scope/authority arguments and applies the host floor/cap (`integrations/mcp/src/milai_mcp/server.py:70-94`). Independent attacks using a mutated original nested Scope, mutated returned copy, broader Scope, changed authority, `EVENTUAL` and a huge limit either failed before the client or reached it only as the frozen host Scope, `ACTION_SAFE`, `CANONICAL_REQUIRED`, limit 5. |
| UA-F05, P1 — ProposalDraft validation bypass | **CLOSED** | `ProposalDraft` now requires and checks operation, model/template identity, lowercase snapshot SHA-256, disjoint Evidence branches, Scope, requested/patch authority, canonical patch fields and target/expected head (`integrations/python-client/src/milai_client/models.py:428-541`). AgentMemory, generic tools, LangGraph, MCP typed input and the E2E adapter validate at the model/framework boundary before submission (`lifecycle.py:245-260`, `tools.py:199-206`, `nodes.py:111-122`, `server.py:232-244`, `evals/agent_integration/adapter_probe.py:150-156`). Independent raw/missing/spoofed model, template, snapshot, Evidence-overlap, authority-mismatch and missing-head attacks produced zero Proposal POSTs; a locally stale head was read then rejected with zero POSTs. Two valid retries had identical operation ID and canonical body bytes. The low-level SDK transport remains server-facing; no reference model/extractor path sends an unvalidated dict to it. |

### Credential and KEK incident closure

The prior review's contemporaneous old `.env` byte hash no longer matches the live environment, and no
old environment backup or leaked sdist remains. The re-review did not retain old secret values merely
to repeat an authentication attempt. Instead it independently established the reusable control and
current state:

- `runtime/src/milai/operations/credential_rotation.py:36-84` requires exact confirmation, a regular
  `0600` environment, stopped Runtime, complete fields, loopback exact-role DSNs and encrypted Blob
  material; it generates five new DB passwords, six new bearer/causal tokens and a new KEK/reference;
- lines `86-118` put Blob rotation, all five `ALTER ROLE` operations and atomic environment replacement
  inside the pre-commit compensation boundary; lines `120-133,232-250` verify every new exact role and
  reject old DB connections without emitting values;
- an independent injected failure during the second role alteration proved the database context saw
  the exception, the environment was byte-for-byte restored at `0600`, Blob rotation was reversed and
  the returned error was generic;
- the current environment has 12 pairwise-distinct secret fields of the required lengths; every one of
  the five DSNs embeds its corresponding password and exact loopback role. Live doctor independently
  connected as owner/API/Steward/Worker/Audit and verified the exact roles;
- the retained incident receipt records the time-local old-password rejection and old-reader `401`.
  It is corroboration, not the sole basis for closure; source, current state, full real-DB tests,
  archive absence and the independent failure injection are separately verified here.

Post-commit verification is deliberately outside the compensation block. Once PostgreSQL has committed
new passwords, restoring an old `.env`/KEK would create a worse cross-plane inconsistency. A verification
error therefore leaves the Runtime stopped with the already committed new environment and permits
diagnosis or another rotation using those new credentials. That is fail-closed and recoverable; it is
not an open finding. The runbook's rollback statement is read in the surrounding pre-commit transaction
context, not as a promise to resurrect expired credentials after commit.

## 4. Independently executed gates

| Gate / command (abridged; no secrets) | Result |
|---|---|
| independent inventory enumeration and digest recomputation | **PASS** — 322 entries; zero mismatch/missing/extra/symlink/forbidden; root `d4f2cdcd...9842f`; inventory SHA `debb9c2e...a25ce` |
| independent package-manifest size/SHA and six lock recomputation | **PASS** — 12/12 artifacts and 6/6 locks |
| independent extraction of all 12 wheels/sdists | **PASS** — 287 regular members total; zero unsafe/forbidden/current-secret match; old leaked sdist absent; Runtime allowlist 131 members |
| `scripts/scan_ua_secrets.py --env-file runtime/.env` | **PASS** — 323 files, 287 archive members, 17 configured values, zero path/member match, forbidden member or unsafe archive |
| independent nested compressed-secret counterexample | **PASS** — synthetic secret detected through tar→zip→payload; two members traversed |
| `pytest -q tests/test_release_safety.py` | **8 passed** |
| Runtime exact checked-in format/Ruff/mypy scope | **PASS** — 116 files formatted; Ruff pass; mypy 63 source files |
| frozen bundle validator, external-anchor release lock and unittest discovery with step-level bundle scope | **PASS** — validator/lock pass; 18 passed, one scope-appropriate skip |
| Python client format/Ruff/mypy/pytest | **PASS** — 30 tests |
| MCP package same gates | **PASS** — 7 tests |
| LangGraph package same gates | **PASS** — 4 tests |
| AutoGen package same gates | **PASS** — 3 tests |
| hooks package same gates | **PASS** — 2 tests |
| independent generic/LangGraph/AutoGen/official-MCP policy attacks | **PASS** — no policy expansion; no client call on rejected override |
| independent invalid/stale Proposal matrix and valid retry comparison | **PASS** — 7 pre-POST rejections; zero invalid POST; valid retries identical |
| six builds to isolated `/tmp` output directories | **PASS** — each produced one wheel and one sdist; retained candidate artifacts were not overwritten |
| six fresh venv installs, dependency resolution, Python `-I` import and PEP 561 marker | **PASS** — Runtime plus all five integrations |
| fresh disposable exact-role PostgreSQL full Runtime gate | **144 passed in 73.22s**; migration base→0027; cleanup zero connections and drop PASS; independent temporary report SHA `d0a33c29a28041d39afb054e38fa13b9ed9678ce12116b3a6ad46606ee1520dd` |
| fresh isolated three-session E2E | **PASS** — generic SDK, official MCP `2026-07-28`, independent wire `2025-11-25`, LangGraph and AutoGen read; all three sessions PASS; no hard failure; cleanup PASS; temporary report SHA `506ce80d2247ef5585fa4549b1d83e45f0c24ff603508241b5f3088116f6690d` |
| live `milai-ops doctor --json` | **PASS** — 17 PASS / 0 WARN / 0 BLOCKED; exact roles, migration 0027, zero lag/dead letter, live/ready, crypto and Agent compatibility |
| live `milai-ops status --json` | **PASS** — loopback/stdio only, `SYNTHETIC_ONLY`, remote/multi-Agent false, Runtime candidate and Schema experimental/no-freeze |

The three-session replay was inspected semantically, not accepted by exit code. Session 1 abstained
before review. Session 2 retained both `CONTRADICT_BRANCH` and `SUPPORT_BRANCH`, the live `OPEN`
OpenIssue, its discharge rule and unchanged Claim head. Session 3 moved the issue to
`WAITING_EVIDENCE` after revoke, rejected the stale projection as `GROUNDING_BLOCKED`, completed
derived purge and primary erase, and dropped the temporary database with zero connections.

Two reviewer-harness mistakes were corrected transparently and are not candidate failures. First, an
initial shell command applied `MILAI_ARCHITECTURE_LOCK_SCOPE=bundle` only to `verify_lock.py`, so the
following unittest process intentionally exercised all-workspace historical locks and failed on
expected post-freeze drift. Re-running the exact CI step-level environment passed. Second, all six
isolated builds succeeded, but their first follow-up inspection invoked an unavailable bare `python`;
inspection was rerun with the Runtime virtual-environment interpreter and passed. No candidate artifact
was rebuilt in place in either case.

## 5. UA-00 through UA-08 verdict matrix

| Slice | Verdict | Current independent basis and boundary |
|---|---|---|
| UA-00 design/permission preflight | **PASS** | Current ADRs/contracts/capabilities preserve PostgreSQL canonical authority, scoped Agent profiles, no integration DB dependency, no Agent review/direct canonical mutation and host-owned Scope/authority. The frozen architecture remains unchanged. |
| UA-01 bootstrap/doctor | **PASS** | Live 17-check doctor/status, exact roles, loopback/data-mode checks, fresh 144-test database and clean teardown passed. Rotation is controlled and secret-free. |
| UA-02 contract/SDK | **PASS** | Versioned contracts, sync/async typed SDK, negotiation, errors, bounded retry/idempotency, partial outcome, package tests, isolated build/install and PEP 561 pass. |
| UA-03 lifecycle/governed write | **PASS** | Before-model recall, capture policy, model-output rejection, stable IDs, Episode refs/pending review and strict ProposalDraft boundary all pass. Agent still cannot review. |
| UA-04 MCP stdio | **PASS within local stdio scope** | Exact profile catalogs, strict arguments/schema, no review/direct/bulk tools, current/preceding protocols, official/independent hosts, reconnect, policy clamp and Proposal preflight pass. Remote HTTP remains disabled. |
| UA-05 framework references | **PASS** | Generic, LangGraph, AutoGen and hooks preserve host policy, trace/OpenIssue/abstention and checkpoint/reference separation. Fresh cross-adapter E2E passed. |
| UA-06 retrieval quality | **PASS for the declared local fixture/device boundary** | The unchanged ONNX result remains inventory-bound (SHA `59260f4b50968d0bee236c07ee4e9ae94356260b33c255400439c0867aaa74f8`), 13-case gain is `0.3076923`, and full Runtime outage/fallback/identity tests passed. This is not an SLO. |
| UA-07 Local Private gate | **IMPLEMENTATION EVIDENCE PASS; RELEASE GATE NO-GO** | AEAD, wrong-key/tamper, rotation, encrypted backup/restore, server-side data classification and import dry-run paths pass. Real personal data remains denied because explicit user approval and environment-level independent recovery acceptance are absent. This intentional NO-GO does not block synthetic/de-identified Agent Integration Beta. |
| UA-08 release candidate | **PASS for synthetic/de-identified Beta** | Complete recomputable inventory, safe allowlisted artifacts, recursive scanner plus counterexample, CI/static/frozen gates, builds/installs, fresh real-DB suite, fresh E2E, known limitations and this independent review all pass. |

## 6. Section 17 and section 19 gates

| Requirement | Verdict | Evidence |
|---|---|---|
| 17.1 client contract | **PASS** | Client 30-test suite plus source/adversarial replay cover negotiation, typed envelopes/errors, close, retries, idempotency, abstention and deterministic Proposal serialization. |
| 17.2 MCP | **PASS within stdio/local scope** | Seven tests and independent official-client replay cover exact catalogs, strict schemas, policy floor/cap, Proposal preflight, bounded outputs, two protocols and substitution rejection. |
| 17.3 lifecycle | **PASS** | Mandatory recall, idempotent capture, assistant-output denial, exact provenance, protected OpenIssue context, refs-only session end and strict raw Proposal validation pass. |
| 17.4 framework | **PASS** | Host-fixed policy, LangGraph checkpoint/reference separation, AutoGen data-only memory and human-review interrupt pass; models cannot control the policy. |
| 17.5 security | **PASS for declared boundary** | Fresh exact-role/RLS/cross-tenant/revoke/remote/data-mode tests, scanner, archive audit, credential remediation and no-review/no-direct-write profile checks pass. |
| 17.6 three-session E2E | **PASS** | Fresh replay preserved rejected candidates/OpenIssue branches and CAS head, then revoke/reopen/stale-projection fail-closed behavior and cleanup. |
| 19.1 UG-01 Developer Ready | **PASS for current synthetic local Runtime** | Init/doctor/status/smoke implementation, live checks and fresh full suite pass; packaging is now clean. |
| 19.2 IG-01 SDK Ready | **PASS** | Contract, sync/async package quality, build, isolated install, PEP 561 and retry semantics pass. |
| 19.3 IG-02 MCP Ready | **PASS for local stdio** | Two hosts/protocols, isolated catalogs and adversarial policy/schema/tool negatives pass. |
| 19.4 IG-03 Framework Ready | **PASS** | Same governed E2E semantics are observed through generic/MCP/LangGraph and AutoGen read; host policy and state separation are enforced. |
| 19.5 QG-01 Retrieval Quality | **PASS within frozen benchmark boundary** | Inventory-bound ONNX gain and Runtime safety regressions pass; no broader performance claim is made. |
| 19.6 SG-01 Local Private Data | **NO-GO, as required** | Crypto implementation exists, but user approval and environment-specific independent recovery acceptance do not. `LOCAL_PERSONAL_DATA` is not authorized. |
| 19.7 Agent Integration Beta | **PASS for synthetic/de-identified use** | DoD 1-14 below are satisfied and there is no open P0/P1. |

## 7. Agent Integration Beta DoD 1-14

| DoD | Verdict | Independent basis |
|---:|---|---|
| 1 | **PASS** | Live init/doctor/status behavior plus a fresh base→0027 exact-role 144-test database and clean teardown. |
| 2 | **PASS** | SDK/MCP and fresh E2E return canonical-gated memory plus live OpenIssue branches. |
| 3 | **PASS** | Typed envelopes, formatter, MCP/framework output and E2E retain abstention, degraded fields and trace pointers. |
| 4 | **PASS** | Agent profiles expose Evidence capture and Proposal submission only; review/direct Claim mutation/bulk deletion are absent and server authorization negatives pass. |
| 5 | **PASS** | Client/framework retries preserve operation ID/body; Runtime idempotency replay/conflict tests pass without duplicate side effects. |
| 6 | **PASS** | Lifecycle/AutoGen/capture negatives reject model or assistant output as Evidence; Proposal never directly creates canonical state. |
| 7 | **PASS** | Current source/artifacts/archive members contain none of the 17 configured values; logs/context remain bounded and redacted; the prior leaked artifact is absent and credentials/KEK were rotated. |
| 8 | **PASS** | Fresh Session 3 proves immediate `GROUNDING_BLOCKED` across adapters, followed by purge and primary erase. |
| 9 | **PASS** | Fresh E2E covers generic SDK, official and independent-wire MCP, LangGraph and AutoGen read. |
| 10 | **PASS** | Runtime dependency/AST tests and locks keep external projects out of startup and canonical authority; external projects remain references/import sources only. |
| 11 | **PASS** | Independent exhaustive enumeration proves a complete, safe, recomputable 322-entry source/contract/test/package inventory and all 12 artifacts. |
| 12 | **PASS** | Design, health/capability output and known limitations state Runtime `CANDIDATE` and Schema `0.1.x EXPERIMENTAL / NO-GO`. |
| 13 | **PASS as a prohibition** | Live mode is `SYNTHETIC_ONLY`; real personal data, remote access and multi-Agent governance remain disabled. |
| 14 | **PASS** | This independent candidate.2 re-review closes UA-F01 through UA-F05 and has zero open P0/P1. |

## 8. Final decision and permitted boundary

**PASS.** MiLAi Agent Integration `0.1 candidate.2` may be promoted to the synthetic/de-identified
Agent Integration Beta described by the design. All prior findings UA-F01 through UA-F05 are closed;
there are no open P0, P1 or P2 findings.

The precise boundary remains:

```text
Logical Architecture 1.0.0: FROZEN and unchanged
Agent Integration 0.1: PASS for synthetic/de-identified Beta
Runtime 0.1.x: CANDIDATE
Schema 0.1.x: EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
Real personal data / Local Private Beta: NO-GO
Remote transport: DISABLED
Multi-Agent governance: DISABLED
Public distribution / Production readiness: NOT APPROVED
```

## 9. Post-review custody rule

This review adds only this file under `docs/reviews/`, which is intentionally outside the candidate
inventory roots. It does not modify source, contract, test, package, report, inventory, manifest,
design or frozen architecture bytes. Post-write verification must therefore retain, and did retain:

```text
inventory file SHA-256: debb9c2edd90bd072a2d2f3d28d671efd6875d5fda696ae2d55d0ab02a8a25ce
entry count: 322
entries SHA-256: d4f2cdcd52c2d702b8ee3d568c3b54ec39bc83a0e719e8cd79af6db1f669842f
per-entry drift: 0
frozen architecture manifest SHA-256: ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e
```
