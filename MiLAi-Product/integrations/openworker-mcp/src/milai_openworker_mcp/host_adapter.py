"""Compatibility facade for the OpenWorker host adapter.

The implementation lives in :mod:`milai_openworker_mcp.host.orchestrator`.
This module intentionally mirrors its public and historical private symbols:
older integrations and tests imported helper functions from this path.
"""

from __future__ import annotations

from .host import orchestrator as _orchestrator

# Preserve the historical module surface, including private test seams.  The
# implementation's globals remain in ``orchestrator`` so function behavior is
# unchanged; this only keeps attribute lookup stable for existing consumers.
for _name in dir(_orchestrator):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_orchestrator, _name)

__all__ = [
    _name
    for _name in dir(_orchestrator)
    if not _name.startswith("_")
]


if __name__ == "__main__":
    _orchestrator.main()
