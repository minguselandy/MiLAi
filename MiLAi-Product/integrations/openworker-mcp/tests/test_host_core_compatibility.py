from milai_openworker_mcp import host_adapter
from milai_openworker_mcp.host import (
    ingress,
    memory_flow,
    orchestrator,
    provider_bridge,
    request_contract,
    task_state,
    tool_compat,
    trace,
)


def test_host_facade_preserves_request_contract_objects() -> None:
    assert host_adapter.OpenAIChatRequest is request_contract.OpenAIChatRequest
    assert host_adapter.OpenWorkerAdapterError is request_contract.OpenWorkerAdapterError
    assert host_adapter.StreamingCompletion is request_contract.StreamingCompletion
    assert host_adapter.EXACT_MODEL_ID == request_contract.EXACT_MODEL_ID
    assert host_adapter.MAX_BODY_BYTES == request_contract.MAX_BODY_BYTES


def test_host_facade_preserves_ingress_objects() -> None:
    assert host_adapter.StartupTaskPolicy is ingress.StartupTaskPolicy
    assert host_adapter._authenticate_ingress is ingress._authenticate_ingress
    assert host_adapter._task_metadata_from_values is ingress._task_metadata_from_values
    assert host_adapter._load_ingress_token is ingress._load_ingress_token
    assert host_adapter._validate_listen_host is ingress._validate_listen_host
    assert host_adapter._load_startup_task_policy is ingress._load_startup_task_policy


def test_host_facade_preserves_tool_compatibility_objects() -> None:
    assert (
        host_adapter.OrdinaryToolCompatibilityError
        is tool_compat.OrdinaryToolCompatibilityError
    )
    assert (
        host_adapter._apply_single_ordinary_tool_required_once
        is tool_compat._apply_single_ordinary_tool_required_once
    )
    assert (
        host_adapter._apply_vllm_json_schema_named_tool_compatibility
        is tool_compat._apply_vllm_json_schema_named_tool_compatibility
    )
    assert (
        host_adapter._vllm_json_schema_named_tool_chunks
        is tool_compat._vllm_json_schema_named_tool_chunks
    )


def test_host_facade_preserves_task_and_memory_objects() -> None:
    assert host_adapter._BoundTaskState is task_state._BoundTaskState
    assert (
        host_adapter.OpenWorkerProviderAdapter._bind_task_state
        is task_state.HostTaskState._bind_task_state
    )
    assert host_adapter._resolve_prepared_context is memory_flow._resolve_prepared_context
    assert host_adapter._memory_terminal_completion is memory_flow._memory_terminal_completion
    assert host_adapter._transport_unavailable_outcome is memory_flow._transport_unavailable_outcome


def test_host_facade_preserves_trace_objects() -> None:
    assert host_adapter._shadow_route_trace is trace._shadow_route_trace
    assert host_adapter._host_access_trace_link is trace._host_access_trace_link
    assert host_adapter._native_request_observation is trace._native_request_observation
    assert host_adapter._evidence_use_trace_result is trace._evidence_use_trace_result


def test_host_facade_preserves_provider_and_http_objects() -> None:
    assert host_adapter.OpenWorkerProviderAdapter is provider_bridge.OpenWorkerProviderAdapter
    assert orchestrator.OpenWorkerProviderAdapter is provider_bridge.OpenWorkerProviderAdapter
    assert host_adapter.Handler is orchestrator.Handler
    assert host_adapter._build_http_server is orchestrator._build_http_server
    assert host_adapter.main is orchestrator.main
