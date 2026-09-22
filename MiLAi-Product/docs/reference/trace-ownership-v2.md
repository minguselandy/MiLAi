# Trace Ownership v2 — current requests and cache origins

Wire version: `milai-trace-join-v2`. This explicitly imported, serial non-stream
testkit contract covers query-first OpenWorker / reader-lite MCP / Runtime and
post-execution Lab joins. It is not new Runtime or MCP API behavior. v1 remains
the fresh-only historical wire contract; existing evidence is not relabeled.

## Identity and ownership

Runtime rows are keyed by `runtime_request_id`, **not** `retrieval_trace_id`.
Every current HTTP request has its own identity. A cache hit retains the original
retrieval trace; it never invents a fresh retrieval or DecisionSnapshot.

In addition to the v1 runtime fields, v2 requires:

| Field | Meaning |
| --- | --- |
| `runtime_request_id` | Current Runtime-owned request reference |
| `execution_kind` | `FRESH` or `CACHE_REUSE` |
| `origin_runtime_request_id` | Prior fresh Runtime request, null for FRESH |
| `origin_host_attempt_trace_id` | Host attempt that observed that origin, null for FRESH |
| `context_capsule_ref` | Hashed actual persisted capsule ID, or null when none exists |
| `reader_context_sha256` | Hash of the exact released Context text |
| `canonical_position` | Fresh observation position or actual current reuse-validation position |
| `requirement_coverage_digest` | Runtime receipt's requirement-coverage digest, nullable for non-capsule reads |
| `dependency_digest` | Runtime receipt dependency digest, nullable for non-capsule reads |

MCP rows carry current `runtime_request_id`, original `retrieval_trace_id`,
`receipt_reused`, `context_capsule_ref` and the actual supplied `previous_context_ref`.
Provider rows reference `runtime_request_ids` instead of v1 `retrieval_trace_ids`.
Prepared and dispatched bindings include both the current Runtime request and
selected Claim-version references, in addition to Evidence references and Context
SHA. Actual known dispatch, not preparation alone, establishes exposure.

The runtime request, MCP invocation, Host attempt, logical Provider request and
native response identities retain separate owners and separate replay guards.
All other ownership, redaction, usage and observable-use rules from
[v1](trace-ownership-v1.md) continue to apply.

## Cache invariants

`join_attempts` accepts chronological attempts in one run/Product lock/wire version.
A reuse must link to an already observed **fresh** origin under the same task
identity. Trace, capsule, Context digest, canonical position, coverage/dependency
digests and ordered selected versions must match. MCP must report actual reuse
with the same supplied capsule. Missing, later, cross-task or mismatched origins
fail; equal content alone is insufficient. Standalone `join_trace` rejects a cache
row because it has no validated prior-origin batch.

A reused row has `acquired_versions=[]`, null decision/evidence-set digests and
`missing_reason=NO_NEW_RETRIEVAL`. That is an explicit origin reference, not a
missing execution claim. It retains current gate and selected versions. Its
versions must exactly match the prior selection; current Provider exposure must
bind to the current authorized Runtime/MCP invocation. Reusing an original trace
is legal only on this path; fresh retrieval replay still fails.

Actual Canonical mutation or scope change is handled by Product's existing
reauthorization/fallback. If the result is fresh, it is recorded as fresh with its
new trace and versions, even when a prior locator was supplied.

## Exact version meanings

The assembler copies owner hashes; it does not reconstruct them from text.
Evidence versions use the stored Evidence content hash. Canonical Claim versions
use the repository-record digest defined in the [Runtime owner contract](trace-cache-owner.md).
Claim support Evidence IDs are lineage references, not acquired Evidence bodies.
For mixed Contexts, version lists retain Claim selection order followed by actual
Evidence-body selection order, matching the compiler's canonical-before-evidence
rendering. A missing version is rejected, not silently dropped.

`observable_use` remains UNKNOWN without explicit verified support bound to a
successful request and exact exposed version. Neither structural COMPLETE nor
successful fixture transport establishes answer correctness, model use or causal
benefit. Failed and unknown-dispatch requests retain their usage gaps.

## Evidence and limits

The [3B-1 revalidation report](../revalidation/trace-ownership/REVALIDATION.md) binds
the exact Product and Lab source, real Evidence and Claim/cache chain artifacts,
positive/negative tests, observation neutrality, costs and limitations.

Not covered: streaming, concurrent observers, cross-process Host continuity,
arbitrary Context composition, Working State/Note version exports, real model
semantics or mechanism benefit. Unsupported streaming is rejected before dispatch;
an active serial observer rejects concurrent access. These are explicit public
testkit limits, not claims that the product has no other execution paths.

No Product default, permission, Canonical authority, schema or migration changes.
Schema remains `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
