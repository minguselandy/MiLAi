from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

_RUN_ID = re.compile(r"[a-z0-9][a-z0-9._-]{7,95}")
_RESOURCE_ID = re.compile(r"[a-z0-9][a-z0-9._:/-]{2,255}")
_PROCESS_ROLE = re.compile(r"[a-z][a-z0-9-]{1,31}")
_PROCESS_MARKER = re.compile(r"[0-9]{1,32}")


class ResourceRegistryError(RuntimeError):
    """A fail-closed run-owned resource registry failure."""


class ResourceOwnership(StrEnum):
    RUN_OWNED = "RUN_OWNED"
    PRESERVED_EXTERNAL = "PRESERVED_EXTERNAL"


@dataclass(frozen=True, slots=True)
class ProcessGeneration:
    """Immutable identity of one run-owned process generation."""

    role: str
    pid: int
    marker: str
    generation: int


ProcessCleanup = Callable[[ProcessGeneration], None]
ProcessAbsent = Callable[[ProcessGeneration], bool]


@dataclass(frozen=True, slots=True)
class ResourceHandle:
    kind: str
    identity: str
    ownership: ResourceOwnership
    cleanup: Callable[[], None] | None = None
    absent: Callable[[], bool] | None = None
    process_generation: ProcessGeneration | None = None


class RecoveryPlan(Protocol):
    plan_path: Any
    sha256: str | None

    def binding(self) -> dict[str, str]: ...

    def replace_process(
        self,
        role: str,
        expected_pid: int,
        expected_marker: str,
        new_pid: int,
        new_marker: str,
    ) -> None: ...


@dataclass(slots=True)
class _ProcessSlot:
    generation: ProcessGeneration
    index: int


class ResourceRegistry:
    """Tracks exact run-owned resources with generation-safe process replacement.

    Generic resources retain the existing ``register``/``snapshot``/``cleanup_all``
    contract. Processes that may be rebuilt must use ``register_process``. Their
    callbacks receive an immutable :class:`ProcessGeneration`; the registry also
    guards callbacks retained from an old snapshot, so a stale cleanup cannot act
    on a replacement generation.
    """

    def __init__(self, run_id: str, recovery: RecoveryPlan | None = None) -> None:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ResourceRegistryError(
                "run_id must contain 8-96 lowercase URL-safe characters"
            )
        self.run_id = run_id
        self.recovery = recovery
        self._handles: list[ResourceHandle] = []
        self._keys: set[tuple[str, str]] = set()
        self._processes: dict[str, _ProcessSlot] = {}
        self._closed = False
        self._lock = threading.RLock()

    def register(self, handle: ResourceHandle) -> None:
        """Register a generic resource, preserving the runner's current API."""

        with self._lock:
            self._ensure_open()
            self._validate_handle(handle)
            key = (handle.kind, handle.identity)
            if key in self._keys:
                raise ResourceRegistryError("resource identity was registered twice")
            if handle.process_generation is not None:
                raise ResourceRegistryError(
                    "process generations must use register_process"
                )
            self._keys.add(key)
            self._handles.append(handle)

    def register_process(
        self,
        role: str,
        pid: int,
        marker: str,
        cleanup: ProcessCleanup,
        absent: ProcessAbsent,
    ) -> ProcessGeneration:
        """Register generation one of a replaceable run-owned process role."""

        with self._lock:
            self._ensure_open()
            self._validate_process_identity(role, pid, marker)
            if role in self._processes:
                raise ResourceRegistryError("process role was registered twice")
            generation = ProcessGeneration(role, pid, marker, 1)
            handle = self._process_handle(generation, cleanup, absent)
            key = (handle.kind, handle.identity)
            if key in self._keys:
                raise ResourceRegistryError("resource identity was registered twice")
            self._keys.add(key)
            self._handles.append(handle)
            self._processes[role] = _ProcessSlot(
                generation=generation,
                index=len(self._handles) - 1,
            )
            return generation

    def replace_process(
        self,
        role: str,
        expected_pid: int,
        expected_marker: str,
        new_pid: int,
        new_marker: str,
        cleanup: ProcessCleanup,
        absent: ProcessAbsent,
    ) -> ProcessGeneration:
        """CAS-replace an absent process generation with the next generation.

        The caller must normally stop the old process first. The exact old absence
        probe is checked before either the durable recovery plan or the in-memory
        slot changes. Missing roles, stale expectations, repeated replacements,
        and an old process that is still present all fail closed.
        """

        with self._lock:
            self._ensure_open()
            self._validate_process_identity(role, expected_pid, expected_marker)
            self._validate_process_identity(role, new_pid, new_marker)
            slot = self._processes.get(role)
            if slot is None:
                raise ResourceRegistryError("process role is not registered")
            current = slot.generation
            if (current.pid, current.marker) != (expected_pid, expected_marker):
                raise ResourceRegistryError("process generation CAS mismatch")
            if (new_pid, new_marker) == (current.pid, current.marker):
                raise ResourceRegistryError(
                    "replacement process generation is unchanged"
                )
            old_handle = self._handles[slot.index]
            assert old_handle.absent is not None
            try:
                old_absent = old_handle.absent()
            except Exception as exc:
                raise ResourceRegistryError("old process absence probe failed") from exc
            if not old_absent:
                raise ResourceRegistryError(
                    "old process must be absent before replacement"
                )

            generation = ProcessGeneration(
                role,
                new_pid,
                new_marker,
                current.generation + 1,
            )
            new_handle = self._process_handle(generation, cleanup, absent)
            new_key = (new_handle.kind, new_handle.identity)
            old_key = (old_handle.kind, old_handle.identity)
            if new_key != old_key and new_key in self._keys:
                raise ResourceRegistryError(
                    "replacement resource identity is registered"
                )

            if self.recovery is not None:
                replace_recovery = getattr(self.recovery, "replace_process", None)
                if replace_recovery is None:
                    raise ResourceRegistryError(
                        "recovery plan does not support process replacement"
                    )
                try:
                    replace_recovery(
                        role,
                        expected_pid,
                        expected_marker,
                        new_pid,
                        new_marker,
                    )
                except Exception as exc:
                    raise ResourceRegistryError(
                        "recovery process replacement failed"
                    ) from exc

            self._keys.remove(old_key)
            self._keys.add(new_key)
            self._handles[slot.index] = new_handle
            self._processes[role] = _ProcessSlot(generation, slot.index)
            return generation

    def snapshot(self) -> tuple[ResourceHandle, ...]:
        """Return an immutable point-in-time view of registered handles."""

        with self._lock:
            return tuple(self._handles)

    def cleanup_all(self) -> dict[str, Any]:
        """Reconcile each current run-owned resource exactly once."""

        with self._lock:
            if self._closed:
                raise ResourceRegistryError(
                    "resource registry cleanup is not repeatable"
                )
            self._closed = True
            handles = tuple(reversed(self._handles))

        rows: list[dict[str, Any]] = []
        failed = False
        for handle in handles:
            ownership = self._ownership_value(handle.ownership)
            if ownership == ResourceOwnership.PRESERVED_EXTERNAL:
                rows.append(
                    {
                        "kind": handle.kind,
                        "identity": handle.identity,
                        "ownership": ownership,
                        "state": "preserved_external",
                        "attempts": 0,
                    }
                )
                continue
            assert handle.cleanup is not None and handle.absent is not None
            error_type: str | None = None
            try:
                handle.cleanup()
                reconciled = handle.absent()
            except Exception as exc:  # noqa: BLE001 - receipt records only the type
                reconciled = False
                error_type = type(exc).__name__
            if not reconciled:
                failed = True
            row: dict[str, Any] = {
                "kind": handle.kind,
                "identity": handle.identity,
                "ownership": ownership,
                "state": "removed" if reconciled else "cleanup_failed",
            }
            if error_type is not None:
                row["error_type"] = error_type
            rows.append(row)

        receipt: dict[str, Any] = {
            "schema": "milai.dg13u.u1-cleanup-receipt.v1",
            "run_id": self.run_id,
            "status": "FAIL" if failed else "PASS",
            "existing_vllm_preserved": True,
            "external_lifecycle_mutations": 0,
            "items": rows,
        }
        if self.recovery is not None:
            try:
                binding: dict[str, Any] = self.recovery.binding()
                binding["status"] = "PASS"
            except Exception as exc:  # noqa: BLE001 - terminal receipt stays writable
                failed = True
                binding = {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                }
                receipt["status"] = "FAIL"
            receipt["recovery_plan"] = binding
        return receipt

    def _process_handle(
        self,
        generation: ProcessGeneration,
        cleanup: ProcessCleanup,
        absent: ProcessAbsent,
    ) -> ResourceHandle:
        if not callable(cleanup) or not callable(absent):
            raise ResourceRegistryError(
                "run-owned process requires cleanup and absence callbacks"
            )

        def guarded_cleanup(
            *,
            frozen: ProcessGeneration = generation,
            callback: ProcessCleanup = cleanup,
        ) -> None:
            if self._is_current(frozen):
                callback(frozen)

        def guarded_absent(
            *, frozen: ProcessGeneration = generation, probe: ProcessAbsent = absent
        ) -> bool:
            if not self._is_current(frozen):
                return True
            return probe(frozen)

        return ResourceHandle(
            "process",
            f"process/{generation.role}:{generation.pid}",
            ResourceOwnership.RUN_OWNED,
            cleanup=guarded_cleanup,
            absent=guarded_absent,
            process_generation=generation,
        )

    def _is_current(self, generation: ProcessGeneration) -> bool:
        with self._lock:
            slot = self._processes.get(generation.role)
            return slot is not None and slot.generation == generation

    def _ensure_open(self) -> None:
        if self._closed:
            raise ResourceRegistryError("resource registry is already closed")

    @staticmethod
    def _ownership_value(ownership: object) -> str:
        value = str(ownership)
        if value not in {
            ResourceOwnership.RUN_OWNED,
            ResourceOwnership.PRESERVED_EXTERNAL,
        }:
            raise ResourceRegistryError("resource ownership is invalid")
        return value

    @classmethod
    def _validate_handle(cls, handle: ResourceHandle) -> None:
        if not handle.kind or _RESOURCE_ID.fullmatch(handle.identity) is None:
            raise ResourceRegistryError("resource identity is invalid")
        ownership = cls._ownership_value(handle.ownership)
        if ownership == ResourceOwnership.RUN_OWNED and (
            handle.cleanup is None or handle.absent is None
        ):
            raise ResourceRegistryError(
                "run-owned resource requires cleanup and absence probes"
            )
        if ownership == ResourceOwnership.PRESERVED_EXTERNAL and (
            handle.cleanup is not None or handle.absent is not None
        ):
            raise ResourceRegistryError(
                "external resource cannot receive a cleanup callback"
            )

    @staticmethod
    def _validate_process_identity(role: str, pid: int, marker: str) -> None:
        if not isinstance(role, str) or _PROCESS_ROLE.fullmatch(role) is None:
            raise ResourceRegistryError("process role is invalid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
            raise ResourceRegistryError("process pid is invalid")
        if not isinstance(marker, str) or _PROCESS_MARKER.fullmatch(marker) is None:
            raise ResourceRegistryError("process marker is invalid")


def process_snapshot_by_role(
    handles: tuple[ResourceHandle, ...],
) -> Mapping[str, ProcessGeneration]:
    """Return process generations from a registry snapshot, keyed by role."""

    return {
        generation.role: generation
        for handle in handles
        if (generation := handle.process_generation) is not None
    }
