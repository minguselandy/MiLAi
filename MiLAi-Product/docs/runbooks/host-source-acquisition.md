# Opt-in Host source acquisition — Client 0.1.4 candidate

Date: 2026-09-09. Local integration candidate, **not published or enabled by default**.
Schema remains `0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE`.

## What this adds

`milai_client.host_acquisition` provides mechanical types and an asynchronous helper for
trusted Host source adapters: `Binding`, `SourceRef`, `SourcePage`, `SourceBackend`,
`Acquisition`, `Coverage` and `AcquisitionHelper`.

The caller explicitly supplies an adapter and chooses whether acquisition is needed. Importing
the module does not read files, search memory, create State, run models, save Notes or change
existing Agent lifecycle defaults. Existing `MilaiClient`, MCP tools and `run_agent_turn` behavior
remain unchanged. No Lab or benchmark dependency is shipped in the Client package.

The helper validates current source qualification before and after a read, correlates responses
to the exact request/binding/version/cursor, bounds concurrent reads and queue waits, and separates
acquisition from actual presentation. Semantic questions—whether history is needed, which facts
justify a plan, whether a choice is ambiguous, what to save—remain Host responsibilities.

## Trusted adapter contract

- Construct `Binding` from the authenticated current principal/project/task, not source text or
  a model's proposed identity. An ID is not authorization.
- `inventory(binding)` returns only the currently bound sources and their qualification/version.
  File eligibility must come from the Host's trusted filesystem boundary. Product sources must
  use the existing public read/permission path; a helper must never bypass it.
- `read(binding, ref, cursor, request_id)` returns the exact source/version/range and correlation ID.
  A changed version requires requalification; do not silently reuse an old cursor on new text.
- `COMPLETE` on a selected tail page means that range reached EOF, not that all preceding history
  was read. `bounded_scan` starts at zero; only an actual EOF completes that scan. The page limit
  returns `PARTIAL` with continuation. Do not label a search result full-history coverage.
- `WITHHELD`, `UNAVAILABLE` and `UNKNOWN` cannot disclose bodies. A timeout bounds the caller's
  wait; it does not guarantee that an underlying filesystem thread or remote operation stopped.
- A deleted/revoked source is rechecked at the next presentation boundary. Content already sent
  cannot be unsent. Do not keep old text in another unchecked transcript path.

## Minimal Host use

```python
from milai_client.host_acquisition import AcquisitionHelper, Binding

# trusted_backend implements SourceBackend; no automatic source ingestion.
helper = AcquisitionHelper(trusted_backend, max_parallel_source_reads=4,
                           queue_timeout=1, read_timeout=10)
binding = Binding(principal=principal_id, project=project_id, task=task_id)
refs = await helper.resolve_sources(binding)

# Select through the current request or a Host retrieval policy, never evaluator labels.
ref = select_current_source(refs)
pages, coverage = await helper.bounded_scan(binding, ref, max_pages=8)

# The Host reserves input/output/final-delivery resources before each model/tool send.
request_id = next_model_request_id()
eligible_pages = await helper.presentation(
    binding, [page.request_id for page in pages], request_id)
receipt = await send_model_request(eligible_pages)
if receipt.transmission_confirmed:
    helper.record_presentation(request_id, eligible_pages)
```

The example's selection, budget and transport functions belong to the surrounding Host. The
helper does not infer them or maintain a model budget implicitly. `calls` retains received byte
counts and queue/read timing, including body I/O that later qualification masks. Presentation
receipts require the acquired content to match; repeated identical receipts are not double-counted.
An assembled request is not proof of transmission. Unknown usage must remain reserved in the
Host ledger and stop subsequent model sends; an observed response can confirm transmission even
when its usage is unknown.

For a cold resume, reconstruct the trusted binding and adapter in the new process. Obtain current
source/Note/State inventories through their normal interfaces. Do not restore stale helper pages
or depend on copied model messages. A missing Working State does not prevent ordinary source reads.
Optional Note save stays separately authorized through the existing public API; files are not
silently ingested into Product memory.

## Compatibility, install and rollback

This is an additive **Client 0.1.3 → 0.1.4** change within the existing pre-1.0 series. Existing
MCP dependency range `milai-client>=0.1.3,<0.2` admits the candidate, but no deployment is implied.
The helper is available through an explicit module import and is not wired into existing defaults.
There are no new dependencies, HTTP/MCP tools, database migrations, permission scopes, Canonical
procedures or State schemas.

After the local package gates pass, an opt-in Host may install the built candidate wheel in an
isolated environment and provide its own trusted adapter. Do not replace the public service's
Client installation as part of this runbook. To roll back, disable the explicit helper integration
and restore the previously pinned Client 0.1.3 wheel. No data conversion is required; existing
Notes and State use their original public contracts. No schema or database rollback is involved.

Completed local gates: Client 209 tests (19 new), MCP 385 passed/7 opt-in skips; hooks 52,
OpenWorker 176, LangGraph 5 and AutoGen 6 passed. All six adapters pass locked Ruff/mypy and
wheel/sdist builds. Candidate wheel SHA256:
`58e5d82a1e82ccff1111bea28184ac2958ea62028cf2698e8ef1fb273cab38d4`.
The skips are optional PG/auth calibration, not evidence of new-wheel real-PG validation.

## Current deployed pin versus experiment pin

Read-only inspection on **2026-09-09** verified active public service entrypoints and installed
package metadata: **MCP 0.1.15 / Client 0.1.3 / Runtime 0.1.5**. Runtime's BGE deployment is
described separately in `docs/releases/BGE_HTTP_0.1.5_DEPLOYMENT_20260909.md`. This task did not
restart those services, install the new Client there, reauthenticate a public user, or write
public memory.

The V02-14 experiment intentionally used the frozen predecessor delivery **MCP 0.1.15 / Client
0.1.3 / Runtime 0.1.4**, with an isolated deterministic hash backend. Delivery SHA256:
`18344e991596de27c8033b8a5ebb69de235ea98bfee0f0008061900d5fd49b41`.
Those effect measurements are **not Runtime 0.1.5/BGE quality or latency measurements**.

## Evidence and limits

The Lab report `MiLAi-Lab/studies/active/MILA_V0214_HOST_RESULTS_20260909.md` records the failed
development iterations, full 16-phase development pass, four independent synthetic confirmation
scenarios and the conditional integration decision. Four synthetic scenarios cannot justify a
production default, statistical significance or external-user generalization. Lexical retrieval
and the readiness-first prompt/schema remain Lab/Host policy, not this mechanical SDK module.

Public PG evidence covers scoped reads, CAS, deletion and revocation under the pinned prior Client.
The new helper does not change those server semantics. Large-tenant behavior, server saturation
rejection, cold filesystem/remote-source scaling, public Runtime 0.1.5/BGE effect tests and durable
arbitrary-source adapters are outside the verified range. A future release still requires an
explicit release/deployment decision.
