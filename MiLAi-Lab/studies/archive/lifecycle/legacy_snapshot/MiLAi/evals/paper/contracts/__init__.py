"""Public contracts shared by paper memory adapters and runners."""

from .adapter import (
    AdapterCapabilities,
    AdapterStats,
    CapabilityStatus,
    MemoryAdapter,
    MemoryEvent,
    MemoryQueryResult,
)
from .records import (
    ContextArchiveError,
    ContextRecord,
    read_context_archive,
    write_context_archive,
)

__all__ = [
    "AdapterCapabilities",
    "AdapterStats",
    "CapabilityStatus",
    "ContextArchiveError",
    "ContextRecord",
    "MemoryAdapter",
    "MemoryEvent",
    "MemoryQueryResult",
    "read_context_archive",
    "write_context_archive",
]
