# DG-13U U0 run and reconciliation contract v1

Status: `0.1 CANDIDATE / U0 BASELINE ONLY`  
Data boundary: `SYNTHETIC OR INDEPENDENTLY DE-IDENTIFIED`  
Formal evaluation input: prohibited

This contract freezes the development-run surface required before any DG-13U U1 behavior change.
It does not accept ADR-024, close the owner decisions in DG-13 Goal section 9.2, or establish a U1
release result.

The current executable provider/task behavior is frozen separately in
`contracts/agent/v1/dg13u-current-provider-inventory.md`; that observed baseline must not be mistaken
for the proposed U1 request subset.

## Operator entrypoint

The repository entrypoint is:

```bash
runtime/.venv/bin/python scripts/run_dg13u_openworker.py \
  --run-id <unique-run-id> \
  --case-id <one-case-id>
```

The executable package intersection requires Python `>=3.11,<3.13`. The runner rejects any other
interpreter before creating a run directory or invoking an external process.

One invocation owns exactly one case and executes these terminal stages in order:

```text
preflight -> package -> start -> readiness -> smoke -> report -> cleanup
```

Cleanup always runs for resources created by that invocation. It must not stop, restart, upgrade, or
reconfigure the existing local vLLM. A failed stage prevents later charge-bearing work; it does not
silently retry the case. The runner stores durable artifacts below
`var/dg13/runs/<run-id>/` and temporary/cache data below `var/dg13/tmp/<run-id>/`. Short UDS paths may
use `/dev/shm/milai/<short-run-id>/` and are removed only when owned by the same run.

The initial selectors are:

| Case ID | Provider calls | Purpose |
| --- | ---: | --- |
| `U0-IDENTITY-READINESS` | 0 | exact source/package/image/MCP/Runtime/provider/tokenizer identity and readiness |
| `U0-CURRENT-PREFETCH` | bounded by its frozen manifest | current-wheel combined baseline; never historical DG10 evidence |

An unknown selector is rejected before a run directory or external process is created.

## Run identity and artifacts

`run_id`, `case_id`, and `turn_id` are immutable. Their canonical join key is:

```text
access_id = <run_id>:<case_id>:<turn_id>
```

Every expected OpenWorker turn has exactly one `access_id`. Until every component can carry this
field natively, `join-reconciliation.json` must bind that same `access_id` to all observed native
identities:

```json
{
  "access_id": "...",
  "logical_request_id": null,
  "mcp_connection_sequence": null,
  "mcp_request_id": null,
  "runtime_request_id": null,
  "runtime_trace_id": null,
  "context_digest": null,
  "provider_native_request_id": null,
  "terminal": "..."
}
```

Null is valid only when the plan proves that stage was not expected, such as MCP for `NONE` or the
provider for strict memory unavailability. Missing identity for an attempted stage is an unaccounted
call and fails reconciliation.

Each run directory is mode `0700`; regular artifacts are mode `0600`. It contains at least:

```text
manifest.json
readiness.json
stage-trace.jsonl
join-reconciliation.json
report.json
cleanup-receipt.json
```

Provider-consuming cases additionally contain a run-local provider capability and ledger. Secrets,
request/response bodies, prompts, Context bytes, tokens, DSNs, and raw MCP frames are not artifacts.
Only IDs, hashes, typed statuses, counts, and bounded timings are retained.

## Frozen identity

`manifest.json` is written before smoke and binds:

- source tree content identity; because the current repository has no commit, a fabricated Git SHA is
  prohibited;
- exact wheel/sdist hashes and installed entrypoint origins;
- OpenWorker/OpenCode image ID, config digest, relay and broker bytes;
- exact MCP executable bytes and resolved package version;
- Runtime source, migration head, live API version and process identity;
- vLLM endpoint, version, model ID, container/image/start identity and model byte closure;
- tokenizer and chat-template bytes;
- fixture and request-contract digests, data boundary, deadlines, token/call ceilings, and retry policy;
- accepted owner-decision receipt digest, or explicit `null` during U0.

Every run revalidates the live endpoint/version/model/tokenizer/container identity. Identity drift
terminates that case before a provider completion. The runner never manages the vLLM lifecycle.

## Stage trace and readiness

Each trace row contains only:

```text
schema, run_id, case_id, access_id?, stage, attempt=1,
started_at, finished_at, duration_ms, status, reason_code,
input_digest?, output_digest?, native_identity?
```

Required stage names are:

```text
OPENWORKER
ADAPTER_PARSE
TASK
NEED
UDS
MCP_HANDLER
RUNTIME
CANONICAL_GATE
CONTEXT_COMPILE
PROVIDER
RECONCILIATION
CLEANUP
```

Readiness reports Runtime live/ready/capabilities, broker socket and child catalog, adapter health,
OpenWorker health/MCP catalog, and vLLM health/version/model separately. Component readiness is not a
combined E2E result.

## Report and result rules

`report.json` includes:

```text
status: PASS | FAIL | BLOCKED | NOT_RUN
baseline_label: DG13U_U0_CURRENT_BASELINE
u1_product_usable: false
stage terminals and latency p50/p95/p99 where N permits
expected/observed/unaccounted MCP and provider calls
visible memory tool events
correctness counters as 0/N with N shown
artifact paths, sizes, and SHA-256
known identity or composition gaps
```

`PASS` is allowed for U0 only when the selected case's frozen expectations are fully reconciled. It
does not imply any `U1-G*` PASS. Historical or mixed-identity artifacts, direct shadow, mocks, or an
empty denominator cannot satisfy `U0-CURRENT-PREFETCH`.

Provider failures are never automatically retried. Before a new explicit run, the prior report must
state whether a request was issued, its native ID if observed, and the provider-ledger terminal.

## Cleanup receipt

The cleanup receipt lists only run-owned PIDs, containers, networks, databases, sockets, ports,
ledgers, and temporary paths. Each item records `removed`, `not_created`, or `preserved_external`.
Unknown or pre-existing objects are never removed. The existing vLLM is always
`preserved_external`.
