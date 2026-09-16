# OE-07 candidate.2 independent re-review

## Review identity and decision

| Field | Value |
| --- | --- |
| Reviewer | `/root/af09_independent_review` |
| Independence | separate no-history sub-agent; did not author candidate |
| Review window | `2026-08-18T08:28:42Z` through `2026-08-18T09:15:47Z` |
| Host | Linux `5.15.0-86-generic` x86_64; Python `3.11.13`; Ruff `0.16.3`; mypy `1.20.2`; pytest `8.4.2` |
| Data boundary exercised | synthetic/de-identified local data only |
| Local Optimization Candidate decision | **PASS** |
| Beta/provider decision | **NO-GO — OE-F06 remains OPEN** |
| Runtime / Schema boundary | Runtime `0.1.x CANDIDATE`; Schema `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE` |

The local candidate is acceptable as an `Optimization Candidate`: there are no open local P0 or P1
defects after this re-review. This decision does **not** close the full provider/Beta gate and does not
authorize the final release narrative in §20. Provider-native usage/billing, actual model rounds and
end-to-end model wall time, and a same-model quality/safety A/B are absent. The candidate must remain
local/synthetic and must not be described as Beta, Production, provider-validated, or an SLA.

Open counts at this boundary:

| Class | P0 | P1 | P2 |
| --- | ---: | ---: | ---: |
| Local implementation/candidate | 0 | 0 | 0 |
| External Beta/provider evidence | 0 | 1 (`OE-F06`) | 0 |

## Candidate identity and immutability

Hashes were taken before any review-file edit and independently recomputed from current bytes. The
author remediation report was used only as a map; its conclusions were not treated as evidence.

| Object | Expected | Independently observed before write |
| --- | --- | --- |
| `docs/reports/OE-current-byte-inventory-2026-08-18.json` | `001a7bc964a6043a2e58c2751d2982da0ffef543f879124d33c0facc99a803e4` | exact match |
| Inventory entry count | `346` | `346` |
| Inventory canonical entries root | `66c5e66f892d51ab179bdbcf9990c8da5e613ef6ab734699853e7832b9e81508` | exact match |
| `integrations/package-release-manifest.json` | `d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f` | exact match |
| Frozen `architecture/v1.0/architecture_manifest.json` | external anchor `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e` | exact match |

Independent inventory reconstruction used the declared include roots, rejected symlinks, excluded
only cache/venv paths, and recomputed every file size and SHA-256 plus the sorted canonical JSON
root. Paths were sorted, unique and safe; all 346 entry objects exactly matched. As designed by the
shared inventory helper, the OE inventory excludes itself and the predecessor UA inventory; the new
review is outside candidate inventory scope. Required architecture, CI, contracts, reports,
runbooks/security, Runtime migrations/source/tests/config/model/dist, all integration packages,
examples, evals, scripts and release-safety tests were present.

## Prior findings disposition

This table re-adjudicates every finding in the full 304-line prior review
`docs/reviews/OE-07-independent-review-2026-08-18.md`.

| Finding | Prior severity | Candidate.2 disposition | Independent basis |
| --- | --- | --- | --- |
| `OE-F01` cache binding/public override | P0 | **CLOSED** | Runtime lifecycle computes an internal binding before validation and compares the prior slot key before asking live watermarks/Issues (`integrations/python-client/src/milai_client/lifecycle.py:143-224,274-315,317-327`). Router keys include query, goal, known IDs, Scope, authority, consistency, canonical position, semantic Issue digest, context binding, limit and policy version (`optimization.py:436-450`); the context binding includes compiler version, tokenizer, every token/byte budget field, constraints and TTL (`optimization.py:192-221`). TTL, canonical position and semantic Issue state are revalidated (`optimization.py:1300-1322`). Independent one-leg-at-a-time probes changed 19 dimensions and every case performed a new L1 recall. Public sync/async method signatures contain no `cache_validated`; passing it raises `TypeError`. Legacy checkpoints without the new key fail validation. |
| `OE-F02` Hook stdin policy override | P0 | **CLOSED** | Hook policy/budget names are rejected from stdin and values are loaded from host environment (`integrations/hooks/src/milai_hooks/cli.py:19-59,71-119`). Independent probes rejected all seven declared policy/budget fields. Common aliases and a nested policy object could be present but had no effect: observed transport remained host Scope `host`, `ACTION_SAFE`, `CANONICAL_REQUIRED`, limit `3`. A cross-process checkpoint under a changed host Scope routed L1 and issued a second recall. |
| `OE-F03` volatile `request_id` invalidates cache | P1 | **CLOSED** | `open_issue_semantic_projection()` validates and retains governed Issue semantics while omitting request/transition transport metadata, then sorts branches and Issues (`optimization.py:1213-1297`). Independent repeated reads with `request_id` changing produced `L1 -> CACHE` with one recall; changing only governed revision produced `L1` and a second recall. This directly reproduces the prior live-shape failure condition. |
| `OE-F04` weak OpenIssue validation / Runtime capsule incomplete | P1 | **CLOSED** | The compiler requires represented Issue IDs and target match (`optimization.py:906-930`), then validates live status, positive revision, type, Scope object, authority, non-empty discharge and branch structure, unique supported relations, and both conflict branches (`optimization.py:1213-1289`). Independent malformed cases covering resolved, zero revision, wrong target, empty branches/discharge, bad authority/type/relation and one-sided conflict all failed closed. Runtime now selects and serializes revision/type/Scope/authority/branches/discharge (`runtime/src/milai/persistence/context_repository.py:105-125,170-180`) and preserves them in the minimal capsule (`runtime/src/milai/application/context.py:140-169`). The fresh 152-test exact-role run executed the live capsule assertion at `runtime/tests/integration/test_context_chat_api.py:308-339`. |
| `OE-F05` UUID route/transport mismatch | P1 | **CLOSED** | Router precedence sends one typed Claim UUID to L0 exact, an OpenIssue UUID to governed L1, and ambiguous/multiple UUID input to L1 (`optimization.py:351-389`). Sync lifecycle carries `exact_claim_id` into `recall_exact` (`lifecycle.py:226-242`); async and AutoGen have the same transport split. Independent sync probes observed exact transport for Claim and unchanged generic query transport for OpenIssue/multiple UUID. Package tests cover sync, async and AutoGen. |
| `OE-F06` provider/billing/same-model quality proof | P1 | **OPEN — external Beta blocker** | The retained benchmark explicitly identifies `offline-synthetic`, `no-llm-called`, null pricing, zero provider calls, `provider_usage_verified=false`, null extra model rounds and null end-to-end Agent wall time (`docs/reports/OE-00-agent-efficiency-benchmark-2026-08-18.json`). The independent rerun reproduced those null/unverified fields. There is no provider-native request/usage receipt, invoice reconciliation, approved target model tokenizer measurement, or same-model A/B quality/safety score. Local proxy token results cannot close this finding. |
| `OE-F07` scale cwd/raw reproducibility | P2 | **CLOSED** | Runner derives root from `__file__` and sets absolute Alembic script/prepend paths (`evals/agent_efficiency/postgres_scale.py:31-39`); the regression asserts both (`evals/agent_efficiency/test_benchmark.py:46-51`). Both retained raw JSON files are inventory-bound and preserve the adverse sample. An independent full run launched from `/tmp` migrated, measured 1/1k/10k/100k, passed thresholds, closed connections and dropped its database. |

No new P0/P1/P2 finding was opened.

## Adversarial checks

### Cache, policy, Issue and transport

An independent in-memory harness used actual candidate classes and fake read-only transports. It did
not call author test helpers. A fresh baseline slot was established for each leg. Changing each of
the following prevented CACHE and caused a second governed recall:

`query`, active goal, Scope, required authority, consistency floor, limit, router policy version,
compiler representation version, tokenizer ID, `max_memory_tokens`, `max_tool_schema_tokens`,
`max_total_milai_tokens`, budget `max_bytes`, budget class, verified flag, context byte budget,
constraints, configured TTL, and elapsed TTL.

Additional outcomes:

- canonical watermark advance invalidated the slot;
- a missing relevant Issue or malformed Issue made validation return false/fail closed;
- changing only transport `request_id` did not alter semantic digest or snapshot;
- changing Issue revision did invalidate and replace;
- the high-level sync and async APIs rejected a caller-supplied cache-validation boolean;
- low budget could not reuse a higher-budget old slot, and protected minimum remained infeasible
  rather than dropping live Issue state;
- OpenIssue and multiple-UUID input never used Claim exact transport;
- Hook stdin could neither broaden Scope nor lower authority/consistency nor increase limit/budget/TTL.

The lower-level `RecallRoutingInput` still has an internal `cache_validated` field, but direct router
use cannot return cached content or mutate a slot. All supported lifecycle coordinators calculate
that field only after current key/watermark/Issue/TTL validation; it is no longer a public lifecycle
argument.

### PostgreSQL, frameworks and scale

| Gate | Independent result |
| --- | --- |
| Fresh exact-role Runtime | `152 passed in 77.39s`; unique temporary DB; cleanup `connections_before_drop=0`, drop `PASS`; temporary report SHA-256 `ce219225bdf12ecf69efd68abb0cc5c264883e3041a14d818549d4c3d727654c` |
| Three-session E2E from `/tmp` | `PASS`; Generic, official MCP `2026-07-28`, independent JSON-RPC wire `2025-11-25`, LangGraph and AutoGen read; conflict branches/discharge/head preserved; revoke/stale projection/purge/erase passed; no hard failures; cleanup `PASS`; temporary report SHA-256 `ddb5495b88775bf058573072b66df6ff0c8c4e9f19ea8b78f503f161236f7deb` |
| Retained scale attempt 1 | Raw SHA-256 `6c45ca45e4ea2a0fb8cab12a254b2b89d87b7ae6f216edf489e82202d1346469`; status `FAIL`; 10k C1 L0/L1 p95 `86.477/96.286 ms`; 100k measured; cleanup `PASS` |
| Retained scale retry | Raw SHA-256 `9164974103ad03de0365b13a468a9e8ceefd065e064f2cea834e0d146b578f35`; status `PASS`; 10k C1 L0/L1 p95 `20.819/33.596 ms`; 100k measured; cleanup `PASS` |
| Independent scale from `/tmp` | status `PASS`; 10k C1 L0/L1 p95 `21.205/28.218 ms`; 100k measured (C1 p95 `26.332/73.203 ms`); cleanup `connections_before_drop=0`, drop `PASS`; temporary report SHA-256 `93eb99e34013ca360ff0e36c48dce9b99c4e641dcb5f45f1944e66377e8a3562` |

The first scale failure is not hidden or overwritten. The report's claim that an unrelated workload
caused it was not independently proved. What the two retained samples plus independent rerun prove
is narrower: the candidate can meet OG-06/07 under the measured local condition, and latency is
host-load sensitive. These numbers are candidate observations, not a stable SLA.

## Package, archive, CI-shaped and frozen-boundary gates

- Independently recomputed all 12 wheel/sdist size and SHA entries in the package manifest and all
  six lock hashes. There were exactly 12 package artifacts plus six intentional `dist/.gitignore`
  files; no unmanifested wheel/sdist remained.
- Independently opened every archive: 296 members, 2,873,815 uncompressed bytes, no duplicate member,
  unsafe path, link, forbidden `.env`/cache/venv/var/backup/log member, or unsafe archive structure.
- Archive-aware secret scan covered 348 current files and 296 archive members using 17 local secret
  values without printing them: zero file/member match, forbidden member or unsafe archive.
- Six fresh temporary virtual environments installed retained wheels and imported with `python -I`;
  PEP 561 markers passed. Temporary report SHA-256:
  `89573c96d71f15740c65eaced0bdfa4b95e318c776d7945b54c3b004bd955945`.
- Package-local format/Ruff/mypy/pytest all passed: Python SDK `76`, MCP `9`, LangGraph `4`, AutoGen
  `6`, Hooks `6`. Benchmark/release-safety tests: `12` passed.
- Independent offline 20/100/500 runner passed. At 100 turns it reproduced 10,280 evaluation tokens,
  20 logical recalls and 85.480% proxy reduction, while keeping provider calls `0`, usage unverified,
  extra model rounds null and end-to-end model wall time null. Temporary report SHA-256:
  `0d39ae587964b13b623d5868d9aa7ef9fe570c66c7c339ebfcf2b83b9c3d0e00`.
- Frozen architecture validation and release external-anchor verification passed. Exact bundle-scope
  unit run: 18 passed, one expected complete-workspace Git-lock skip. A preliminary unit invocation
  that failed to propagate `MILAI_ARCHITECTURE_LOCK_SCOPE=bundle` to the unittest process exposed
  the expected old all-workspace source-lock drift; rerunning the checked-in bundle-scoped command
  passed. Frozen bundle bytes and manifest were not changed.
- Dependency/source search found no Runtime or integration import/lock dependency on Mem0, Graphiti,
  Hindsight, OpenViking or ReMe. DoD 14 is satisfied.

## OE package disposition

| Work package | Independent disposition |
| --- | --- |
| OE-00 | **PASS (offline/local)** — deterministic fixtures/workloads and 1/1k/10k/100k generator are reproducible; provider pricing remains null. |
| OE-01 | **PARTIAL / provider gate OPEN** — exact counter interfaces and no-fabrication behavior pass; no provider-native usage/billing reconciliation exists. |
| OE-02 | **PASS** — one-slot replace/remove/unchanged and complete cache invalidation binding passed independent probes. |
| OE-03 | **PASS** — deterministic router, reader-lite, internal cache validation and non-escalating host policy pass. |
| OE-04 | **PASS locally; provider tokenizer pending** — injected exact counter, protected Issue minimum, structured downgrade and infeasible behavior pass. |
| OE-05 | **PASS as local candidate observation** — independent 10k/100k exact-role run passes; adverse retained sample prevents SLA interpretation. |
| OE-06 | **PASS (local synthetic)** — Generic/MCP/LangGraph/AutoGen/Hook contracts and fresh three-session E2E pass. |
| OE-07 | **PASS for local Optimization Candidate; Beta/provider incomplete** — this re-review closes all local prior findings, while OE-F06 remains external. |

## OG-00 through OG-12

| Gate | Disposition | Boundary |
| --- | --- | --- |
| OG-00 Reproducible Baseline | **PASS offline/local** | Input hashes/workloads and local reports are reproducible; target provider/model/pricing snapshot is absent. |
| OG-01 Token Truth | **PARTIAL** | No token value is fabricated, but there is no provider-native reconciliation. |
| OG-02 No Quadratic Growth | **PASS** | 500-turn/500-update one-slot tests and zero-byte unchanged behavior pass. |
| OG-03 Compact Tools | **PARTIAL** | Reader-lite is one tool and under 250 proxy tokens; target-provider count is absent. |
| OG-04 Context Budget | **PARTIAL** | 512/1,024/1,600 and infeasible behavior pass under injected exact counter; target-provider tokenizer proof is absent. |
| OG-05 Session Cost | **PASS for evaluation tokenizer only** | 100-turn `10,280 < 30,000`; not billing evidence. |
| OG-06 Warm L0 | **PASS as measured candidate gate** | Retained retry `20.819 ms`; independent `/tmp` run `21.205 ms`; first adverse sample remains visible. |
| OG-07 Warm L1 | **PASS as measured candidate gate** | Retained retry `33.596 ms`; independent `/tmp` run `28.218 ms`. |
| OG-08 Cold Start | **PARTIAL** | Prewarm behavior/readiness is tested, but the specified separately retained post-ready first-query/provider-specific proof is absent. |
| OG-09 Quality | **PARTIAL** | Local governed conflict/revoke/authority regressions pass; same-model provider task-quality A/B is absent. |
| OG-10 Frameworks | **PASS local synthetic** | Four adapters plus Hook share the tested host-policy/governance boundary. |
| OG-11 Failure Safety | **PASS for exercised local faults** | Policy/budget/TTL/watermark/Issue changes, revoke, stale projection and DB/provider-local failure paths fail closed. |
| OG-12 Independent Review | **PASS for local candidate; NO-GO for Beta** | Zero open local P0/P1; external P1 OE-F06 remains. |

## Definition of Done 1–15

| DoD | Disposition | Evidence/boundary |
| ---: | --- | --- |
| 1 | **PARTIAL** | Exact injected counters and explicit unverified fallback pass; no real supported-provider usage record. |
| 2 | **PASS** | Replace/remove/unchanged and 500-update bounded slot behavior. |
| 3 | **PASS** | NONE/L0/L1 rules and action-safe/current-state governed paths; cache changes cannot bypass recall. |
| 4 | **PASS local** | Reader-lite one-tool default and profile non-escalation. |
| 5 | **PASS** | Goal/constraints/ECS/Issue/branches/discharge/authority/trace protected by compiler and Runtime capsule. |
| 6 | **PASS** | Infeasible minimum fails explicitly; no protected Issue eviction. |
| 7 | **PASS** | Cache/search/reranker remain derived and cannot manufacture canonical authority. |
| 8 | **PASS** | Canonical position, Issue revision, policy and TTL changes invalidate cache/slot. |
| 9 | **PASS local synthetic** | Generic/MCP/LangGraph/AutoGen/Hook host policy boundary passes. |
| 10 | **OPEN for Beta** | 100/500 bounded local workloads pass, but actual provider tokens, model rounds and end-to-end model wall time are absent. |
| 11 | **PASS local** | Independent 1/1k/10k/100k and concurrency runs retained; both PASS and FAIL raw samples disclosed. |
| 12 | **OPEN for Beta** | Local safety/trace regressions pass; same-model provider quality comparison is absent. |
| 13 | **PASS for local candidate** | Packages, clean install, examples/adapter E2E, CI-shaped static/tests, security scan and this independent re-review pass. |
| 14 | **PASS** | No external memory engine is a Runtime/integration dependency. |
| 15 | **PASS** | Schema remains explicitly `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`. |

## Commands and reproducible results

The following command families were executed against current bytes; credentials were read only by
the existing local runners and were never printed or recorded:

```text
independent Python inventory reconstruction
  346 entries; exact per-file size/SHA match; root 66c5e66f...e81508

independent package manifest/archive reconstruction
  12 artifacts and 6 locks exact; 296 archive members; no unsafe/forbidden members

package-local ruff format --check; ruff check; mypy; pytest -q
  SDK 76, MCP 9, LangGraph 4, AutoGen 6, Hooks 6 — all PASS

PYTHONPATH=scripts:runtime/src:integrations/python-client/src \
  runtime/.venv/bin/python -m pytest -q \
  evals/agent_efficiency/test_benchmark.py tests/test_release_safety.py
  12 passed

PYTHONPATH=scripts runtime/.venv/bin/python scripts/scan_ua_secrets.py \
  --env-file runtime/.env
  PASS; 348 files; 296 archive members; zero matches/forbidden/unsafe

PYTHONPATH=runtime/src runtime/.venv/bin/python scripts/run_runtime_full_gate.py \
  --env-file runtime/.env --report /tmp/oe-c2-independent-runtime-full.json
  152 passed; cleanup PASS

(cwd=/tmp) evals/agent_integration/e2e.py --report /tmp/oe-c2-independent-e2e.json
  PASS; three sessions; cleanup PASS

(cwd=/tmp) evals/agent_efficiency/postgres_scale.py \
  --output /tmp/oe-c2-independent-scale.json
  PASS; 10k L0/L1 21.205/28.218 ms; 100k measured; cleanup PASS

scripts/run_package_clean_install_gate.py \
  --output /tmp/oe-c2-independent-clean-install.json
  six isolated installs/imports PASS

architecture validate_bundle.py; verify_lock.py --scope bundle --mode release \
  --expected-manifest-sha256 ac16f3b...55d0e
  PASS
MILAI_ARCHITECTURE_LOCK_SCOPE=bundle python -m unittest discover \
  -s architecture/v1.0/tests -v
  18 passed; 1 expected scope skip
```

## Required remaining evidence for Beta/provider closure

`OE-F06` can be closed only by a new, inventory-bound run using an approved target provider/model and
the same frozen task set. It must retain provider request identity and provider-native input/cached
input/output usage, reconcile pricing/billing, report actual additional model rounds and end-to-end
Agent wall time, measure the target tokenizer/tool catalog/budgets, record post-ready first-query
latency, and score same-model baseline versus optimized task quality, OpenIssue preservation,
authority, abstention and deletion/revocation safety. Until that exists, `Optimization Candidate` is
the highest honest status.

## Post-write immutability verification

After creating this review, the inventory was independently reconstructed a second time: 346 files,
no symlink, exact per-file entries, and canonical root
`66c5e66f892d51ab179bdbcf9990c8da5e613ef6ab734699853e7832b9e81508`. The inventory file remained
`001a7bc964a6043a2e58c2751d2982da0ffef543f879124d33c0facc99a803e4`; package manifest remained
`d31ce50ee96fc7a45087e6a719a3c5aede1eb1b277db1521e1d34ffeaa557e9f`; frozen architecture manifest
remained `ac16f3b7f9413a7b2d8373b6e7d306697df0bc7908572bb3b0344260d8a55d0e`. The new review is outside
candidate inventory scope. Its final SHA-256 is reported out of band because a file cannot
self-authenticate its own digest.
