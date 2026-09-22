# Host owner trace testkit v1

The [v2 join](trace-ownership-v2.md) additionally binds current Runtime request,
original retrieval, supplied/current capsule and selected Claim-version references.
The observer copies these facts from the actual MCP response; it does not infer
cache reuse from equal payloads. [Scoped real-chain evidence](../revalidation/trace-ownership/REVALIDATION.md)
now covers fresh Evidence and Claim/cache execution with a controlled Provider fixture.

`milai_openworker_mcp.trace_testkit.ObservedOpenWorkerProviderAdapter` is an explicit
engineering-only subclass of the normal Adapter. The default Adapter/CLI never imports or
enables it. It accepts the original constructor configuration and retains the existing
Provider gateway, capability, deadlines, request/token budgets, authorization and ledger.
It does not grant execution authority or allocate requests.

Use only in an isolated, already-authorized bounded run. Call `complete` normally, then
`owner_traces()` to obtain detached `milai-host-owner-trace-v1` snapshots. Optional `retry_of`
names a previous attempt from this observer and must retain the same process/task binding.
The testkit supports serial non-stream completion only: streams and concurrent/nested calls
are rejected before invocation, not partially observed. It is not an HTTP deployment mode.

## Observed facts

- A fresh opaque `host_attempt_trace_id` is allocated around the actual Adapter call,
  independently of payload bytes. The same ID binds captured Host events and transport calls.
- `task_identity_digest` hashes `[run_id, host_instance, task_session]`; operation identity
  is recorded separately. A restart does not restore or extend the native task graph.
- Each actual transport invocation records its logical request reference, exact payload
  digest, native response reference when observed, and input/output usage when returned.
  Transport exceptions retain null usage; unexpected exceptions remain `UNKNOWN`.
- The original gateway still owns reservation, settlement, duplicate-native-ID detection
  and exception normalization. Transport `SUCCESS` means a returned native transport
  response, not successful parsing, valid accounting, task correctness or memory use.
  Host terminal `RETURNED` means normal Adapter return; `FAILURE` means an exception escaped.
- Allowlisted Host events preserve logical request association, Runtime trace reference,
  legacy attempt reference, original Context/payload digests, injection flag, fresh-resolve
  flag, and recognized cache-reuse outcomes. `null` remains unknown, never an inferred miss.
  Cached Context reuse remains distinct from fresh retrieval and still uses original validation.

References are `<kind>:SHA256(canonical_JSON(original_ID))`; digests use UTF-8 JSON with sorted
keys, unescaped Unicode and compact separators. They are stable owner references, not new
Runtime executions or Provider request IDs. Matching exporters must preserve this algorithm.
The complete source ID-to-reference binding and original traces/ledger stay in restricted run
artifacts outside Git. Hashing is not encryption or authorization to publish private data.

Only fixed event names, digest fields, booleans, token counts and hashed references are exported.
Prompts, answers, native task identifiers, error messages, labels and arbitrary nested legacy
trace payloads are not copied. The original Adapter's local trace file is unchanged and is
**not** made safe to publish by this testkit. The snapshot is a separate allowlisted projection.

## Evidence and limits

The [Product-owned tests](../../integrations/openworker-mcp/tests/test_trace_testkit.py) execute
the real Host Adapter and gateway with synthetic MCP/Provider transports. They verify identical
request payloads, responses, budgets and invocation count with observation off/on; fresh retry
identity; failure/unknown usage; request/Host binding; no-memory; abstain; cache validation;
detached snapshots and redaction. They make zero external model calls and prove no PostgreSQL
persistence or model-use claim.

This is one producer slice of [Trace Ownership v1](trace-ownership-v1.md), not its completion.
Still required: Runtime-owned decision/evidence/version exports, actual MCP transport binding,
cache-origin exact-version provenance, Lab wire assembly, and bounded end-to-end evidence.
Missing Context/version observations on failed requests must remain explicit, not reconstructed
from answer text or substituted with empty known lists. No observable-use claim is emitted.

The [same-execution extension](trace-ownership-chain.md) observes actual query-first MCP
calls and matches their exact framed Context to transport payloads. Snapshots distinguish
`prepared_context_bindings` from `context_bindings` and include `exposure_status`.
Request/response fixture types are explicitly re-exported by this public testkit for
authorized engineering harnesses. The default CLI remains uninstrumented. Cache-origin
and concurrency/stream coverage remain outside this extension.

Development: initial new fixtures accidentally selected the existing no-Provider fallback;
the unknown-exception assertion initially ignored existing gateway normalization; the partial
Context fixture initially omitted its required governance boundary. These test-harness failures
were corrected without changing routing, fail-closed behavior or gateway error semantics.
Final targeted command (OpenWorker package):

```bash
.venv/bin/pytest -q tests/test_trace_testkit.py tests/test_provider_execution.py \
  tests/test_host_adapter.py::test_query_first_passes_only_receipt_locator_on_native_continuation_turn \
  tests/test_host_adapter.py::test_query_first_soft_partial_context_reaches_provider_with_typed_status \
  tests/test_host_adapter.py::test_query_first_denial_or_open_issue_prohibits_provider_execution --tb=short
```

Result: 28 passed in 0.64 s; changed-module Ruff and mypy PASS. Package-wide checks belong to
the affected integration fast gate; no repeated full composition, database suite or model run.
Rollback is a source revert, with no migration. The only default Adapter edit is a transport
Protocol annotation (the concrete default stays `JsonCompletionTransport`). Product manifest
identity changes because the explicitly imported testkit is shipped; this is not a default
behavior change. Schema remains `EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`.
