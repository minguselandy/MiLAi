# Trace Ownership v1 — offline contract candidate

Status: `3B-1 IN_PROGRESS`; wire version `milai-trace-join-v1`. This document and the
Lab joiner are an offline contract slice, **not** evidence that existing Product/Host
producers emit a complete chain. The ownership debt remains `NEEDS_REVALIDATION`.
No Runtime API, MCP tool, database schema, authorization or Canonical behavior changes.

## Ownership and join keys

The assembled envelope has `schema_version`, `run_id`, `product_lock_digest`, `host`,
`runtime[]`, `mcp[]`, `provider[]`, and `lab`. Lab assembles owner exports after execution;
it must not reconstruct missing Runtime decisions from answers or hidden labels.

| Key / fact | Owner and cardinality | Absence and retry contract |
| --- | --- | --- |
| `run_id`, `product_lock_digest` | Lab; one pinned run per join batch | Required; lock must be verified before Product-backed execution |
| `host.host_attempt_trace_id` | Host; fresh opaque ID per attempt | Required; identical payload does not make a retry the same attempt |
| `host.task_identity_digest` | Host; digest of authorized task binding | Required; retry cannot cross task identity, run or Product lock |
| `host.retry_of` | Host; zero or one prior attempt | Null for first attempt; parent must precede child in a batch |
| `runtime[].retrieval_trace_id` | Runtime; one ID per actual retrieval execution | Required on a Runtime row; no retrieval means no invented row |
| `decision_snapshot_digest` | Runtime; one digest per captured decision snapshot | Null with `NOT_EXPORTED`, `NO_DECISION` or `RUNTIME_UNAVAILABLE` |
| `evidence_set_digest` | Runtime; one digest of the governed evidence set | Same explicit missing-reason rule; never a hash of Lab-selected substitutes |
| Runtime gate, acquisition and selection | Runtime; ordered exact-version lists per retrieval | Empty lists are known empty, not missing observations; unknown lists cannot be exported as empty |
| `mcp[].invocation_id` | MCP/Host transport; one fresh ID per invocation | A successful invocation must bind a Runtime trace; pre-Runtime failure/block may bind null |
| `provider[].request_id` | Host; one fresh logical ID per actual provider invocation | Required even when no native response is received |
| `reader_context_sha256`, `retrieval_trace_ids`, `exposed_versions` | Host; facts about the exact request it assembled and dispatched | Empty exposure is allowed; nonempty exposure requires a context digest and admitted, successfully transported selection |
| `provider_native_request_id` | Provider; zero or one native ID per invocation | Null only with `NOT_ACCEPTED` or `RESPONSE_LOST`; successful response requires ID |
| Provider `status`, `usage` | Provider terminal facts captured by Host transport | `SUCCESS`, `FAILURE`, `UNKNOWN`; missing token counts stay null, never zero-filled |
| Provider `exposure_status` | Host transport; live assembly always supplies it | `DISPATCHED`, `NOT_STARTED`, `UNKNOWN`; unknown is not known empty exposure |
| `lab.result_ref` | Lab; zero or one local result artifact per attempt | Null when no result has been recorded; no score or answer is exported back into Product |
| `memory_ref`, `version_id`, `content_sha256` | The memory's authority; exact immutable identity | Required together; same identity cannot acquire different content within a pinned run |
| `lab.observable_support[]` | Lab; verified post-execution observations | Zero or more exact request/version supports; empty means use `UNKNOWN` |

The `provider` object is an assembled request/response envelope, not a claim that Provider
owns the Host fields. Host terminal (`SUCCESS`, `FAILURE`, `ABSTAIN`, `NO_MEMORY`) describes
attempt disposition, not benchmark correctness. Runtime gate is copied, never reinterpreted
by Host or Lab. Canonical position and binding remain Runtime-owned; the snapshot digest is
only a reference to their owner record, not an independently verifiable authorization proof.

## Exact observation semantics

- `ACQUIRED`: Runtime observed the exact version in its governed acquisition record.
- `SELECTED`: Runtime selected that acquired version. Selection is not injection.
- `EXPOSED`: Host recorded that exact selected version in the dispatched reader request.
  This proves Host-side dispatch, not Provider acceptance or actual model use. Pre-dispatch
  failures must not report exposure; lost responses retain known dispatch and unknown usage.
- `OBSERVABLY_USED`: support names this successful request and an exposed exact version,
  with kind `EVIDENCE_ALIAS`, `STRUCTURED_CITATION`, `TOOL_REFERENCE`, or
  `EXACT_VERSION_REVISION`. The runner must verify the referenced observation exists and
  actually binds the version; supplying a syntactically valid reference is not proof.
- `OUTCOME_ASSOCIATED`: a Lab result is associated with the ordered request/exposure
  sequence. No reward is split over individual memories by this joiner.
- `CAUSALLY_ATTRIBUTED`: never established by this contract. Requires independent
  counterfactual/ablation evidence. Success, adoption and exposure cannot substitute for it.

Request order, acquisition/selection/exposure order, failed invocations and partial usage
remain intact. No cost aggregation, scoring or inferred use is performed. A selected but
unexposed version earns no use claim. Revision lineage belongs to the later ledger; an exact
version citation does not itself prove a valid correction or later reuse.
Output `version_use[]` reports support separately for each exposed version. Request-level
`observable_use=OBSERVABLY_USED` means at least one version has support, never all versions.

## Validation, redaction, replay and versioning

`milai_lab.analysis.trace_join.join_trace` validates one envelope. `join_attempts` joins
chronological attempts in one pinned run, rejects replay of attempt/request/native/retrieval/
invocation IDs, and checks retry edges and immutable version identities. One current Runtime
row binds exactly one MCP invocation; one request may reference several current retrievals.

The candidate currently covers **fresh retrieval**. Cache-origin references across attempts,
fan-out sharing of one native request, and legacy payload-derived attempt IDs are not silently
coerced into it. A later producer slice must specify and test cache provenance before claiming
Host continuity coverage; replay rejection must not be bypassed by inventing fresh retrievals.

`join_status=COMPLETE` means only that represented digest/native-ID fields have no declared
gaps. It does not establish provenance, full path coverage, known usage, model use or Product
conformance. `PARTIAL` preserves missing values and reasons. Structural validation is not
authentication; the runner must bind owner export hashes and exact executable/Product identity.

All objects reject additional keys. The payload contains only opaque references, lowercase
SHA-256 digests, enums, token counts and ordered lists. No prompt, body, answer, hidden score,
gold label, credential or raw native task ID is allowed. Producers must use run-scoped opaque
aliases for sensitive identifiers before export; allowed string syntax is not a privacy filter.
Source artifacts remain access-controlled outside Git. Hashes are not encryption and may still
leak low-entropy values; they are not permission to publish private material.

The candidate's optional `exposure_status` preserves compatibility with original offline
fixtures, but actual producer assembly always includes it. `NOT_STARTED`/`UNKNOWN` cannot
contain proven exposed versions. UNKNOWN adds an explicit gap; missing native identity uses
`NOT_OBSERVED` when dispatch itself is unknown, instead of claiming a known lost response.

Owner digests retain their owner's documented serialization/meaning and must not be rewritten
to fit this join. `facts_sha256` alone hashes the complete submitted envelope using UTF-8 JSON,
sorted object keys, unescaped Unicode and compact separators; array order remains significant.
Replay is rejected rather than silently dropping potentially billable requests. Re-running the
pure function on identical input returns identical output without mutation or external I/O.
Incompatible finalized wire semantics require a new version; v0.x historical records remain
unchanged and cannot be relabeled v1 without owner-complete provenance.

## Current evidence and remaining gate

Offline implementation and tests:

- [Lab joiner](../../../MiLAi-Lab/src/milai_lab/analysis/trace_join.py)
- [Synthetic contract tests](../../../MiLAi-Lab/tests/unit/test_trace_join.py): success, retry,
  abstain, failure, no-memory, unknown-use, redaction, identity mismatch and replay.

These tests call no model, Runtime or database. They prove validator behavior, not live owners.
Existing [retrieval testkit](retrieval-trace-testkit.md) and Host access-link/provider traces are
inputs to the next compatibility/export slice, not automatically complete v1 producers.
In particular, the current Host query-first/prefetch attempt ID is payload-derived, and the
provider trace base has a logical request ID but lacks an explicit attempt join field. Identical
retry payloads therefore cannot be assumed to have fresh attempt identity from those bytes alone.

The explicit [Host owner testkit](host-trace-testkit.md) now supplies fresh observational
attempt identity and actual transport-call association without changing those legacy bytes or
the default Adapter. Its Product-owned synthetic-transport tests do not yet prove Runtime
decision/version provenance or complete the end-to-end Lab join.

The [Runtime owner export](retrieval-trace-testkit.md#opt-in-runtime-owner-export-v1) adds
actual DecisionSnapshot digests, recorded trace/position and exact materialized Evidence
versions behind `--owner-trace`. Its empty/visible/wrong-scope PostgreSQL cases prove this
producer slice, not that a separate Host attempt consumed that same Runtime execution.

Before 3B-1 PASS: implement/verify narrowly scoped public read-only producer exports, bind
actual Runtime/Host/Provider facts for the six terminal cases, prove observation neutrality and
cache-origin semantics, and close the Product debt with Product-owned executable evidence.
Before 3B-2 PASS: produce the opportunity ledger from a real bounded run with its own verified
Product lock and method/input identity. Neither gate is satisfied by the synthetic tests here.

The [same-execution probe](trace-ownership-chain.md) now joins real MCP/HTTP/PostgreSQL
owner facts through a controlled Provider fixture for eight attempts. Fresh execution,
exact Evidence hashes, Context dispatch and three failure states are covered. Cache hits,
Claim versions and actual model use remain unproven; 3B-1 stays IN_PROGRESS.

Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
