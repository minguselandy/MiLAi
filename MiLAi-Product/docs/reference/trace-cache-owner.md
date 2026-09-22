# Runtime Claim and cache owner observations

Status: local producer evidence, `3B-1 IN_PROGRESS`, 2026-09-22. This extends the
public opt-in testkit; it does not yet complete the Host/MCP/Provider/Lab cache join.

## Proven scope

The repository observer hashes each actual `gate_and_hydrate` Claim record before
query-dependent scores or rendering are added. `content_sha256` is canonical JSON
SHA-256 of `{"schema_version":"milai-claim-version-record-v1","record":record}`.
The record is the repository's JSON-safe projection of Claim/version identity,
subject/predicate/type, version number, payload, scope, valid/system time,
lifecycle/epistemic status/freshness/authority/confidence, derivation policy,
model/template and canonical commit sequence. This is a version-record digest,
not the Evidence body hash and not a rendered-Context hash.

Additive `milai-runtime-owner-trace-v1` fields distinguish:

- `materialized_claim_versions`: versions actually returned through the observed
  governed repository path and present in retrieval results;
- `selected_claim_version_refs` and `selected_claim_versions`: the compiler's
  selected exact versions, bound back to those records;
- `selected_support_evidence_refs`: supporting Evidence references, **not** proof
  that the referenced Evidence bodies were acquired or exposed.

Existing `materialized_evidence_versions` and `selected_versions` retain their
Evidence-only meaning. A missing Claim record or missing selected version remains
a PARTIAL observation, not an invented hash or an empty acquisition claim.

`ObservedRuntime` additionally exports `context_capsule_ref`,
`selected_claim_version_refs`, and `reuse_validation`. Successful reuse retains the
original retrieval trace and has **no fresh owner DecisionSnapshot**. Its separate
validation facts bind the current Runtime request, actual REUSE terminal, original
trace, capsule, coverage/dependency digests and current validation canonical
position. An issuance position is never substituted for validation position.
Malformed or mismatched observations emit a fixed gap without changing the HTTP
response. No raw content, credential, query, Claim ID or capsule ID is exported.

`reader_gate=ADMITTED` for the exact-state path means that Runtime returned a HIT,
AVAILABLE, correctly resolved governed State with selected Claim versions and no
open issue. It is an observational projection, not an added authorization decision
or a claim that the model used the content.

## Execution evidence

Source commit: `00ff8c3a1f4a524ddbc5f7e149f64128e88b7a12`; source Git tree:
`8f30f4eb02cdb3eabd6edb40d135e9198efd2aa3`.
Product 425 files; tree
`fb1493ec85bada22c39fa90a83cb00e9839f1d76e188aead53dead5b07ab22f1`;
manifest SHA `a69d35c60ebfae072a86ef418af4be170c91f365c30a75caf5b11ff70a3ebe23`.

Five real PostgreSQL cases use isolated synthetic tenants and official Evidence /
Proposal / Review APIs. They prove:

1. Exact Claim read: normal, baseline observer and owner observer preserve reader /
   governance fields, observer semantic digest and repository-call digest.
2. Wrong-scope exact read: same neutrality checks and no exposed Claim version.
3. Actual loopback HTTP receipt hit: fresh current request, same original trace,
   capsule, Context digest and exact Claim versions; no fresh retrieval invented.
4. Scope change: no receipt reuse; fresh scoped result has no selected Claim.
5. Governed Claim supersession: no old receipt reuse; fresh version and content
   digest differ from the original.

From `MiLAi-Product/runtime`, with the isolated role-specific
`MILAI_MIGRATION_DATABASE_URL`, `MILAI_TEST_API_DATABASE_URL`,
`MILAI_TEST_STEWARD_DATABASE_URL`, and `MILAI_TEST_WORKER_DATABASE_URL` configured:

```bash
.venv/bin/pytest -q tests/integration/test_claim_owner_trace_pg.py \
  tests/unit/test_observed_runtime.py tests/unit/test_runtime_owner_trace.py \
  --junitxml=/path/to/new-private-junit.xml --tb=short
.venv/bin/mypy src/milai/testkit/runtime_owner_trace.py src/milai/testkit/observed_runtime.py
```

Final exact-source execution: **29 passed / 0 skipped, 2.85 s**. Changed-file Ruff
and source mypy passed. Six reuse-binding unit cases cover success and mismatched
stage, request, position, digest and origin trace. HTTP observation failure tests
preserve the original response and allow only fixed safe error codes.

JUnit: `/cra/memory/mx_memory/evidence/post-cleanup-3b1-cache-runtime-20260922-6NwY4o/junit.xml`;
SHA `807aed4b4b00e12e1cc6463c0eab6a1c0f3f24f8540e16439ef2329a933a1fb5`.
PostgreSQL 16.14, dedicated container `milai-3a1-worker-once-20260922`, database
`milai_worker_once`, migration head `0056_host_notes`, endpoint during this run
`127.0.0.1:32793`. The container is stopped; data is retained. No shared service,
model request, experiment allocation, full composition or historical replay ran.

Initial test iterations compared naturally different CURRENT read timestamps.
The test now fixes only the State-address clock across its paired reads, retaining
CURRENT semantics; no Product time behavior changed. Initial import/style findings
were corrected. An overly broad explicit mypy invocation included historical test
helpers outside the configured source gate and reported existing test typing
errors; it was not used to justify unrelated repairs. Final mypy scope is the two
changed source modules.

## Remaining work

The existing Lab assembler still rejects receipt reuse and does not yet admit the
new Claim fields. Extend and version the cache join to bind a current authorized
invocation to an observed prior origin, retain replay rejection, and reject missing
or mismatched origins. Then bind actual Host/MCP context injection and Provider
dispatch through a bounded same-execution run. The HTTP tests above do not prove
that cross-layer path, concurrent/stream behavior, actual model use or trace debt
closure. 3B-1 and its debt remain unfinished; 3B-2 is not admitted by this slice.

No public Runtime route/MCP tool, schema, migration, permission, Canonical mutation
rule or default retrieval/ranking/budget/Prompt policy changed. Source rollback is
main `489ea7ca8c3756630f32da0e2c52a0940c97d74e`; no database rollback is required.
Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
