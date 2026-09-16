# Request timing v1 — optional, read-only operational observations

Status: CANDIDATE. Enable `MILAI_REQUEST_TIMING_ENABLED=true` with INFO-level JSON Runtime
logging. It is off by default. This adds logs, not response fields, tools, database entities or
memory content. Authorization, audit, transactions and payload disclosure still run normally.

Runtime emits `event=runtime_request_timing` with `request_id_fingerprint` (first 16 hex characters
of SHA-256 over the response request ID) and `safe_metadata`:

- `schema_version=request-timing-v1`;
- `application_ms`: Flask before-request hook to after-request hook, including authentication,
  application work and JSON response construction; excludes Waitress's prior dispatch queue,
  response transmission, this log write and later response hooks;
- `status_code`: completed Flask response status, including errors;
- `durations_ms.db_pool_acquire_ms` and matching `counts`: pool connection-context acquisition;
  a failed acquisition still records elapsed time but no successful hold;
- `durations_ms.db_connection_hold_ms` and matching `counts`: acquired connection until release
  begins, including role checks, transaction scope binding, application queries and commit/rollback.
  Asynchronous pool reset/maintenance after return is excluded.
- Optional additive `durations_ms.db_transaction_enter_ms` and `db_transaction_exit_ms`, with
  matching counts: the explicit psycopg transaction context's entry and exit. Exit includes commit
  or rollback, or their failure; its presence is not a successful-commit receipt. A failed entry
  records entry only. These intervals are nested inside connection hold, not extra time to add to it.
  For a successful single-acquisition/single-transaction request, hold minus enter minus exit is
  the remaining connection work (role/scope setup, queries, application work and local scheduling).
  Exit is not pure WAL/disk time, and nested transaction exits may release a savepoint rather than
  commit a top-level transaction. Older observations without these optional fields remain valid;
  missing fields must not be interpreted as zero.

Both database durations aggregate request-local calls; they are not pure SQL execution time.
Optional blob observations use the same request timer: `blob_write_ms` spans the complete write
call; `blob_lock_wait_ms` spans exclusive flock acquisition; `blob_encode_ms` spans new-content
encoding/encryption; `blob_file_sync_ms` and `blob_directory_sync_ms` span the respective fsync
calls (directory counts cover each level). Opening and closing handles are excluded from these
sync measurements. These aggregate wall times include scheduling and are not pure device I/O times.
Inner intervals are nested in blob write and cannot be added to it. Hashing, directory/file
creation, rename, verification and other uninstrumented work remain in its residual. Optional
`evidence_ingest_observer_ms` spans the configured post-ingest callback, including a callback
failure; missing means unmeasured/not executed, not zero. Observations do not change locking,
sync order, encryption, error propagation or commit authority. No content/path/identity is logged.

Database startup `open()` and `ping()` do not use this per-request pool measurement. Empty counts
mean no instrumented acquisition, not proof that a route performed no database work. Nested or
parallel acquisitions can overlap, so do not generally add durations as a wall-time partition.
Timers live in a ContextVar reset at request teardown, including errors and reused worker threads.

The MCP `codex-full` entrypoint honors the same flag. Successful Working State GET/UPDATE emit
`MILAI_WORKING_STATE_TIMING ` followed by a JSON object containing:

- `schema_version=mcp-working-state-timing-v1`, tool name;
- `runtime_request_id_fingerprint` calculated by the same rule, or null if absent;
- `runtime_client_ms`: the complete awaited SDK call, including any compatibility negotiation,
  client scheduling/connection wait, network, Runtime processing and configured retries;
- `handler_ms`: handler entry through bounded response construction, including that SDK call;
  excludes this log write, later MCP encoding, dispatch before entry and response transmission.
- Optional additive `handler_start_monotonic_s` and `handler_end_monotonic_s`: the same entry/end
  boundary on `time.monotonic()`, in seconds. They are not UTC timestamps. Use them across processes
  only after independently verifying a shared monotonic clock (for example, the same Linux host
  boot and time namespace). Otherwise retain the duration-only observation and leave the split
  unknown. On a verified shared clock, client start to handler start includes client preparation,
  transport, framework dispatch and validation; handler end to client end includes this log write,
  framework encoding, transport and client processing. Neither side is pure network/queue time.
  Reject inconsistent timestamp ordering or duration agreement rather than clamping it to zero.

MCP error/cancellation paths retain their existing error/audit records and do not emit a success
timing event. Missing events or null/unmatched request IDs remain missing; never infer a zero.
Correlate per request before aggregating. Do not subtract unrelated P95 values or classify the
client-minus-handler residual as pure network or queue time. Fingerprints are correlation hints,
not identity/authorization or a collision-free operation receipt; duplicate matches are ambiguous.

Logs contain neither payload, SQL, source references, principal/task names nor credentials.
The Runtime uses its existing redacting JSON formatter. The MCP line contains only the fields
listed above. The capability does not guarantee a gateway SLO, cancellation of a remote write,
full queue observability, tenant fairness or storage/semantic correctness.

## Optional default SDK HTTP transport phases

`HttpxAsyncTransport(timing_enabled=True)` emits `MILAI_HTTP_TRANSPORT_TIMING ` with
`schema_version=http-transport-timing-v1`. The Codex-full CLI enables it for its default async
State and resolve clients under the same timing flag; custom transports remain caller-owned.
It is disabled by default. No retry, pool limits, payload, authorization or commit behavior changes.

Fields are `runtime_request_id_fingerprint` from the public X-Request-ID header (or null),
`started_monotonic_s`, `finished_monotonic_s`, `transport_ms`, response `status_code` (or null),
`trace_events` and `dropped_events`. At most 32 events retain only an allowed event name and
`monotonic_s`; callback info, headers, bodies, exception text, URL and method are never logged.
Allowed HTTP/1.1 events cover TCP connection, TLS, request headers/body, response headers/body
and response close, each with started/complete/failed suffixes. Other events are ignored.
Missing events, unsupported/mock trace paths and dropped events are unmeasured, not zero.

The interval includes the default transport's HTTP await and JSON decoding, but excludes SDK
encoding/negotiation outside this call, its log write and the caller's later processing.
An HTTP status is not a confirmed SDK result or operation receipt (JSON decoding may still fail).
Cancellation/transport failure preserves its original exception and can emit a partial trace;
null status does not mean that a remote operation did not commit.

Connect includes DNS/socket scheduling where applicable. Waiting for response headers includes
server queueing, processing, network and local scheduling; it is not pure network latency.
Trace intervals can nest and must not be summed with total transport time. Pool/pre-dispatch
waiting has no independent guaranteed callback and may remain residual. Correlate exact request
fingerprints before subtracting application time; a reused connection need not emit connect.
Shared-clock requirements above also apply to these monotonic timestamps. Instrumentation adds
work and does not establish performance improvement, fairness or a fully observed queue.
