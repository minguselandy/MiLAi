"""Bounded, process-local frozen encoder vectors with literal input identities."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

EncodingKey = tuple[str, str, str]


class BaseEncodingCache:
    """Retain only inputs used by the current completed feature computation.

    The budget covers literal UTF-8 keys and tensor payloads. Python/container
    overhead is not a measured RSS bound. No task-conditioned workspace, model
    weights, permission decision, persisted vector or approximate key is stored.
    """

    def __init__(self, max_bytes: int) -> None:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("Base encoding cache needs a positive byte budget")
        self.max_bytes = max_bytes
        self.entries: OrderedDict[EncodingKey, tuple[Any, int]] = OrderedDict()
        self.active: set[EncodingKey] | None = None
        self.bytes = 0
        self.counters = dict(requests=0, hits=0, misses=0, same_call_reuses=0,
                             evictions=0, stale_input_removals=0, oversized_skips=0,
                             resets=0, completed_feature_calls=0, peak_accounted_bytes=0)

    @contextmanager
    def scope(self) -> Iterator[None]:
        if self.active is not None:
            raise RuntimeError("Base encoding cache scopes cannot overlap")
        self.active = set()
        try:
            yield
        except BaseException:
            self.clear()
            raise
        else:
            for key in list(self.entries):
                if key not in self.active:
                    self.bytes -= self.entries.pop(key)[1]
                    self.counters["stale_input_removals"] += 1
            self.counters["completed_feature_calls"] += 1
        finally:
            self.active = None

    def get(self, key: EncodingKey) -> Any:
        if self.active is None:
            raise RuntimeError("Cache lookup requires a current feature scope")
        self.active.add(key)
        self.counters["requests"] += 1
        if key not in self.entries:
            self.counters["misses"] += 1
            return None
        self.counters["hits"] += 1
        self.entries.move_to_end(key)
        return self.entries[key][0]

    def put(self, key: EncodingKey, vector: Any) -> None:
        if self.active is None or key not in self.active:
            raise RuntimeError("Cache insertion requires a current observed input")
        size = sum(len(part.encode("utf-8")) for part in key)
        size += vector.numel() * vector.element_size()
        if size > self.max_bytes:
            self.counters["oversized_skips"] += 1
            return
        if key in self.entries:
            self.bytes -= self.entries.pop(key)[1]
        while self.entries and self.bytes + size > self.max_bytes:
            self.bytes -= self.entries.popitem(last=False)[1][1]
            self.counters["evictions"] += 1
        self.entries[key] = (vector.detach().clone(), size)
        self.bytes += size
        self.counters["peak_accounted_bytes"] = max(
            self.counters["peak_accounted_bytes"], self.bytes)

    def clear(self) -> None:
        self.entries.clear()
        self.bytes = 0
        self.counters["resets"] += 1

    def report(self) -> dict[str, Any]:
        return {**self.counters, "entries": len(self.entries),
                "accounted_bytes": self.bytes, "max_accounted_bytes": self.max_bytes,
                "byte_scope": "Literal UTF-8 keys + tensor payloads; Python overhead/RSS unknown",
                "scope": "Current public encoder inputs only; full workspace recomputed"}
