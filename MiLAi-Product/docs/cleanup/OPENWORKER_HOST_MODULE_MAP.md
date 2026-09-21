# OpenWorker Host internal module map

## Compatibility boundary

The supported executable and historical import path remains:

```python
from milai_openworker_mcp.host_adapter import OpenWorkerProviderAdapter
from milai_openworker_mcp.host_adapter import main
```

`host_adapter.py` remains the 27-line compatibility facade introduced before C5. It mirrors the
public and historical private symbols from `host.orchestrator`. `host/orchestrator.py` is now a
415-line HTTP/CLI assembly module that explicitly reexports the extracted owners. The new host
modules are internal and do not create a new public API.

The existing `orchestrator.OpenWorkerProviderAdapter` monkeypatch point used by the executable
exposure contract remains live because `main()` still resolves that module global directly.

## Final responsibility map

| Module | Responsibility | Principal symbols |
| --- | --- | --- |
| `host/request_contract.py` | Frozen model/field contract, message validation, memory-tool hiding and memory-reading policy | `OpenAIChatRequest`, `StreamingCompletion`, `OpenWorkerAdapterError` |
| `host/ingress.py` | Bearer validation, exact native metadata headers, token-file policy, listen-address policy and startup task policy | `StartupTaskPolicy`, `_authenticate_ingress`, `_load_ingress_token`, `_validate_listen_host` |
| `host/tool_compat.py` | Single ordinary-read state machine, vLLM JSON-schema adaptation and SSE wire rendering | `OrdinaryToolCompatibilityError`, `_apply_single_ordinary_tool_required_once`, `_vllm_json_schema_named_tool_chunks` |
| `host/task_state.py` | Host/native task identity, transitions, generations and cache-reuse binding | `HostTaskState`, `_BoundTaskState`, `_bind_task_state`, `_bind_native_task_state` |
| `host/memory_flow.py` | Recall decoding, prepared-context resolution and fail-closed memory terminal rendering | `_prepared_prefetch`, `_resolve_prepared_context`, `_memory_insufficient_outcome`, `_memory_terminal_completion` |
| `host/trace.py` | Payload-free route, access, request and evidence-use trace projections | `_shadow_route_trace`, `_host_access_trace_link`, `_native_request_observation`, `_evidence_use_trace_result` |
| `host/provider_bridge.py` | Provider capability/configuration, settlement and complete request orchestration | `OpenWorkerProviderAdapter` |
| `host/orchestrator.py` | HTTP handler/server, CLI assembly and historical compatibility exports | `Handler`, `_build_http_server`, `main` |
| `host_adapter.py` | Stable executable/import facade | historical public and private host symbols |

## Equivalence evidence

The extraction baseline is Product commit
`0bd5ed414bd11ef8841025b5177f7b79f6e92a00`, where `host/orchestrator.py` contained 3,735 lines.

A recursive AST comparison searched every final `host/*.py` module for every named class and
function in that baseline:

```text
baseline recursive definitions: 81
exact AST matches:              80
same-name changed definitions:  1 (OpenWorkerProviderAdapter class container)
missing definition names:       0
```

The class container changed because task binding methods now come from the internal
`HostTaskState` base. All original methods—including `__init__`, task binding, settlement,
content-free trace recording and `complete()`—remain individually AST-identical. The final
`test_host_core_compatibility.py` fixes facade-to-owner identity for request, ingress, tool,
task-state, memory-flow, trace, provider, HTTP and CLI objects.

## Preserved boundaries

- Explicit loopback/private literal listen addresses, Bearer auth, auth-before-parse and the
  process-lifetime ingress token are unchanged.
- Task lifecycle, generation, transition validation and cache-reuse constraints are unchanged.
- The memory-required provider barrier, provider ordering, settlement and trace privacy are
  unchanged.
- Model ID, request fields, ordinary-tool policy, provider budgets and exact error codes are
  unchanged.
- No Runtime behavior, DB schema/migration, MCP server, Lab, Frozen Architecture or historical
  receipt changed.
