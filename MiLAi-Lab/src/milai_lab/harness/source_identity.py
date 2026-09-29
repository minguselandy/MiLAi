"""Explicit canonical source registration for current request and memory consumers."""

CONTRACT_SOURCE_FILES = (
    "src/milai_lab/contracts/__init__.py",
    "src/milai_lab/contracts/arms.py",
    "src/milai_lab/contracts/memory.py",
    "src/milai_lab/contracts/operations.py",
    "src/milai_lab/contracts/protocol.py",
    "src/milai_lab/contracts/records.py",
    "src/milai_lab/contracts/request.py",
)
MEMORY_SOURCE_FILES = (
    "src/milai_lab/memory/__init__.py",
    "src/milai_lab/memory/presentation.py",
)
REQUEST_SOURCE_FILES = (
    "src/milai_lab/harness/source_identity.py",
    *CONTRACT_SOURCE_FILES,
    *MEMORY_SOURCE_FILES,
    "src/milai_lab/methods/request_context.py",
)
