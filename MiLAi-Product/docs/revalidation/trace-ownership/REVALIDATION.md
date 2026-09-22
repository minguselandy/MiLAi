# Trace ownership revalidation — Phase 3B-1

Date: 2026-09-22. Local scoped decision: **FIXED**. Work-package remote closure
remains pending until exact-head fast CI, protected merge and main identity pass.
This is engineering trace provenance, not a model-effect or production-readiness claim.

## Contract and decision

The public opt-in testkits observe the actual Runtime repository/HTTP execution,
MCP call, Host injection and Provider transport. Lab consumes only published
exports and joins them using [v1 fresh](../../reference/trace-ownership-v1.md) or
[v2 current-request/cache-origin](../../reference/trace-ownership-v2.md) contracts.
No Product default instrumentation, new DB schema, MCP tool or Runtime route is added.

The original ownership gap is closed for the declared serial query-first testkit
surface: actual Runtime-owned decision/version facts, MCP invocation, Host request
injection, Provider native result/unknown usage and Lab attempt/result reference
are bound in one execution. Cached Context retains its fresh origin and binds a
new authorized Runtime request; it does not become a fake acquisition.

Evidence body hashes and Claim repository-record digests remain distinct.
Supporting Evidence references on a Claim are not claimed as acquired bodies.
Missing source/version/decision fields fail or remain explicit gaps. No hidden
score, answer, prompt or credential enters the published join. Hashes are not
encryption; artifacts remain private outside Git.

## Exact identities

Final test/Evidence-probe source: `519ba02bbedc7507237bb78267679ef0cf62cf71`, Git tree
`555f9e4a7d5cbd3244072fc567bd5f90b10f10d0`.
Claim/cache probe source: `83e69ed74a30a76f16bb6b039f4b7013b1cf2d77`, Git tree
`77027a933bd82cf6f43ad20a36ea08e02c27b842`.
Their only diff is two Product test files: the added Host query-first neutrality
case and test whitespace. Product executable/manifest and all three Lab method
files are identical. Each run retains its own exact containing commit and lock;
the earlier run is not rewritten to claim the later commit.

Both use Product 425 files, tree
`22c011d0d9dc267c2a82a71cd9a4c2b2fdbb199f65aa0084eaf25d6583487f8a`, manifest SHA
`0a3f2b1ada1e00d98133acc287c24fe8837e9775aef1d9f5c73def90e2da17ae`.

## Bounded real-chain results

| Path | Host attempts / fixture calls | Result |
| --- | --- | --- |
| Evidence fresh | 8 / 7 | Success, retry, abstain, no-memory, three failure dispatch states; exact Evidence body hash |
| Claim / cache | 10 / 9 | Five genuine reuse validations; governed supersession forces fresh retrieval/new version, then new-version reuse |

Each chain uses real broker/MCP subprocess, authenticated loopback HTTP Runtime,
isolated PostgreSQL and the official role-separated `milai-worker --once` CLI.
Claims are created/superseded through official Proposal/Review, not direct Lab SQL.
Provider is an in-process fixture; tokenizer is synthetic. Real model requests,
actual model tokens and new experiment allocations are all zero.

Every provider row has use UNKNOWN and causal attribution NOT_ESTABLISHED.
Each chain retains three unknown fixture usages. Known fixture units are 20/12
(Evidence input/output) and 30/18 (Claim input/output), not model token totals.
The runs took 3.284 s and 4.329 s respectively, without a performance claim.

Artifacts:

- Evidence: `/cra/memory/mx_memory/evidence/post-cleanup-3b1-evidence-chain-20260922-r1`;
  owner facts SHA `a4de9e534459c27ceceb78a60a0dc4c347e73ac198f30c43b8cd5c16aa582de4`,
  joined SHA `916bf65d943c6597fc69f36f21eb65e93d8204f72ccdad985caa1e64b8b770f8`.
- Claim/cache: `/cra/memory/mx_memory/evidence/post-cleanup-3b1-cache-chain-20260922-r1`;
  owner facts SHA `334697abd0a74281988e0b9464f804c7479e69f79019352556488bc00b966c95`,
  joined SHA `255134404300cadf8e0575369589d6dc56e9c4007d045293a29c23a54629d1f5`.

Each manifest pins method/input/Product hashes before startup, enforces at most
8 or 10 Host attempts/fixture calls and 120 seconds, verifies installed CLI source
locations, and writes new private artifacts. Reproduction uses the command in the
[fresh-chain runbook](../../reference/trace-ownership-chain.md), with the corresponding
commit/new output directory; add `--canonical-cache` for the Claim/cache run.

## Narrow validation

Runtime at final source: 34 PASS / 0 skips, 4.07 s, including eight real PG cases:

```text
.venv/bin/pytest -q tests/integration/test_claim_owner_trace_pg.py tests/integration/test_runtime_owner_trace_pg.py tests/unit/test_runtime_owner_trace.py tests/unit/test_observed_runtime.py --tb=short --junitxml=<new-private-runtime.xml>
```

OpenWorker at final source: 13 PASS / 0 skips, 0.58 s:

```text
.venv/bin/pytest -q tests/test_trace_testkit.py --tb=short --junitxml=<new-private-host.xml>
```

Lab changed join/assembly/v2 tests: 76 PASS, 0.29 s. Changed-file Ruff and source
mypy pass for affected Runtime/Host/Lab modules; both Lab boundary gates pass.
Runtime normal/baseline/traced fields, observer semantics and repository calls
match for empty/visible/wrong-scope Evidence and exact/wrong-scope Claims. Host
plain/observed fresh and cached calls preserve payload/response/budget/call count.
Replay, mismatched origin/version/context/scope, wrong current request and unknown
dispatch are rejected or retained explicitly, never repaired by invented facts.

JUnit directory: `/cra/memory/mx_memory/evidence/post-cleanup-3b1-close-20260922-qRgRZg`.
Runtime SHA `c3ce77e86f36b03e94778b6f33a20f851247d7e382191caf7a0186323f6a6e8d`;
Host SHA `53739797bf45915ee79522f41dbe43d5a3d08a4aa92d559bfe08942025c3b034`.
The machine receipt records the authoritative exact hashes.

PostgreSQL 16.14 / migration `0056_host_notes`, dedicated container
`milai-3a1-worker-once-20260922`, synthetic tenants and role-separated DB users.
Actual endpoints were `127.0.0.1:32794` (Claim probe) and `127.0.0.1:32795`
(Evidence probe/final PG tests). Owned processes and DB are stopped; data remains.
Package-wide checks are delegated to classified fast CI; no full composition,
historical replay or unrelated DB suite is repeated.

Development failures and limits from the [Runtime slice](../../reference/trace-cache-owner.md)
and [fresh-chain slice](../../reference/trace-ownership-chain.md) remain preserved.
New v2 tests initially found only line-format issues; a script mypy attempt in the
Lab-only environment lacked public Product testkit imports. Configured source
mypy passes, and the real runner executes with pinned public editable packages.

## Limits and next work

The receipt is **SCOPED G7**, not complete architecture conformance. Serial,
non-stream query-first execution only; no cross-process continuity, arbitrary
multi-context composition, streaming/concurrent tracing, real model use or research
benefit claim. Unsupported stream/concurrent observations fail explicitly.
Host Continuity and Resolver remain separate diagnosis work packages. 3B-2 still
needs a real Opportunity Ledger; a trace join is not that ledger.

Rollback: source revert to main `489ea7ca8c3756630f32da0e2c52a0940c97d74e`;
no DB migration rollback. Schema stays `EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
