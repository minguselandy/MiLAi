"""Explicit canonical source registration for current request and memory consumers."""

CONTRACT_SOURCE_FILES = (
    "src/milai_lab/contracts/__init__.py",
    "src/milai_lab/contracts/arms.py",
    "src/milai_lab/contracts/benchmark.py",
    "src/milai_lab/contracts/memory.py",
    "src/milai_lab/contracts/operations.py",
    "src/milai_lab/contracts/protocol.py",
    "src/milai_lab/contracts/records.py",
    "src/milai_lab/contracts/request.py",
    "src/milai_lab/contracts/scope.py",
)
MEMORY_SOURCE_FILES = (
    "src/milai_lab/memory/__init__.py",
    "src/milai_lab/memory/embeddings.py",
    "src/milai_lab/memory/mcp.py",
    "src/milai_lab/memory/presentation.py",
    "src/milai_lab/memory/read_tools.py",
    "src/milai_lab/memory/revision_store.py",
    "src/milai_lab/memory/strict_tools.py",
)
MEMORY_FACADE_FILES = (
    "src/milai_lab/baselines/langmem_mcp.py",
    "src/milai_lab/baselines/langmem_revision_store.py",
    "src/milai_lab/baselines/langmem_strict_tools.py",
)
INTEGRATION_SOURCE_FILES = (
    "src/milai_lab/integrations/__init__.py",
    "src/milai_lab/integrations/memory/__init__.py",
    "src/milai_lab/integrations/memory/mem0.py",
    "src/milai_lab/integrations/memory/simplemem.py",
)
INTEGRATION_FACADE_FILES = (
    "src/milai_lab/runners/mem0_native.py",
    "src/milai_lab/runners/simplemem_native.py",
)
ARTIFACT_IO_SOURCE_FILES = (
    "src/milai_lab/harness/artifact_io.py",
)
BENCHMARK_EXECUTION_SOURCE_FILES = (
    "src/milai_lab/harness/benchmark_execution.py",
)
PROVIDER_SOURCE_FILES = (
    "src/milai_lab/providers/chat_bridge.py",
    "src/milai_lab/providers/request_pipeline.py",
    "src/milai_lab/providers/langmem_chat.py",
    "src/milai_lab/methods/langmem_recipe.py",
)
REQUEST_SOURCE_FILES = (
    "src/milai_lab/harness/source_identity.py",
    *CONTRACT_SOURCE_FILES,
    *MEMORY_SOURCE_FILES,
    *MEMORY_FACADE_FILES,
    *INTEGRATION_SOURCE_FILES,
    *INTEGRATION_FACADE_FILES,
    *ARTIFACT_IO_SOURCE_FILES,
    *BENCHMARK_EXECUTION_SOURCE_FILES,
    *PROVIDER_SOURCE_FILES,
    "src/milai_lab/methods/request_context.py",
)
