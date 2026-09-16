# ADR-044: Bound database waiters and distinguish acquisition backpressure

Status: ACCEPTED FOR IMPLEMENTATION / Schema remains NO-GO FOR SCHEMA FREEZE.

The direct PG timing test demonstrated pool acquisition timeout returning a generic HTTP500 on
Working State. Pool size and waiting time were bounded, but psycopg_pool's default max_waiting=0
left queue length unbounded. Reuse the existing pool's queue; do not add a global semaphore or queue.

RuntimeSettings and WorkerSettings expose database_pool_max_waiting, default32, range1–1024,
configured by MILAI_DATABASE_POOL_MAX_WAITING. Each existing API, Steward and worker pool owns its
own bound. The setting cannot silently select the library's unlimited zero option.

At request connection acquisition only, translate TooManyRequests and PoolTimeout into a typed
DatabaseCapacityError with POOL_QUEUE_FULL or POOL_WAIT_TIMEOUT. It remains a DatabaseUnavailable
subclass so existing read abstention/unavailable envelopes remain valid and fail closed. Unhandled
capacity errors, including Working State and Evidence routes, return HTTP503 with the existing
error envelope, code DATABASE_CAPACITY_EXCEEDED, retryable=true and details.reason. Existing paths
that already translate DatabaseUnavailable may keep their established abstention reason instead.
Startup and health dependency errors keep their existing unavailable handling.

An acquisition failure proves only that this acquisition obtained no connection. An HTTP operation
may already have committed another transaction or stored an unreferenced blob. The error is not a
NOT_COMMITTED receipt and does not authorize blind overwrite. SDK retry configuration remains as
before; fixed codex-full and this Goal use zero retries. A failed Working State write remains UNKNOWN
through the existing MCP recovery contract. Explicit operation replay and current-head reads remain
distinct. Error details contain no DSN, credentials, principal identity or payload.

No SQL schema, Canonical authority, tenant binding, permission or transaction procedure changes.
No migration. Normal successful responses are unchanged. Reverting removes the queue bound/error
classification; do not keep the stronger backpressure claim after rollback.

This is per-pool bounded admission, not gateway queue capacity, per-tenant fairness, remote request
cancellation, an SLA, or a higher throughput claim. Waitress/HTTP dispatch and high-cost processing
need their own evidence. Real PG tests must cover queue full versus timeout, authenticated denial,
independent Steward capacity, subsequent recovery, no falsely committed rejected State, and exact
scope/binding isolation. No new overload load tier is authorized by this change.
