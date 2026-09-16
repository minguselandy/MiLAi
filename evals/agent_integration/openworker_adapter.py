"""Compatibility entry point for the installed OpenWorker integration product."""

from milai_openworker_mcp.host_adapter import (
    Handler,
    OpenWorkerAdapterError,
    OpenWorkerProviderAdapter,
    _recall_from_messages,
    _recall_query,
    _should_recall,
    _task_seed,
    _tool_name,
    main,
)

__all__ = [
    "Handler",
    "OpenWorkerAdapterError",
    "OpenWorkerProviderAdapter",
    "_recall_from_messages",
    "_recall_query",
    "_should_recall",
    "_task_seed",
    "_tool_name",
    "main",
]


if __name__ == "__main__":
    main()
