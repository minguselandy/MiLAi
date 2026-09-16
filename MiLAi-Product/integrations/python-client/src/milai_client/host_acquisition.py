"""Opt-in, callback-based source acquisition for one asynchronous Host session.

Import this module explicitly; existing client/agent-loop behavior is unchanged. The caller
supplies an authorized backend whose inventory reports current disclosure eligibility and whose
pages translate public cursor/EOF semantics. This helper never grants source access, performs
semantic retrieval, writes memory, or decides whether evidence is sufficient for a task.

Use one helper on one event loop. Its semaphore is instance-local, not a service-wide lock.
Rebuild outgoing material with ``presentation`` immediately before each send. Record presentation
only after the transport confirms the corresponding payload; preparation alone is not a receipt.
Already transmitted content cannot be retracted by a later eligibility change.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol


class Coverage(StrEnum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    WITHHELD = "WITHHELD"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Binding:
    principal: str
    project: str
    task: str


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    version: str
    kind: str = "SOURCE"
    eligible: bool = True
    entrypoint: str = "source_read"
    size_bytes: int | None = None
    searchable: bool = True
    product_populated: bool | None = None


@dataclass(frozen=True)
class SourcePage:
    request_id: str
    binding: Binding
    source_id: str
    version: str
    text: str
    cursor: int
    next_cursor: int | None
    coverage: Coverage
    range_kind: str = "SOURCE_RANGE"


class SourceBackend(Protocol):
    """Caller-owned public source adapter; qualified inventory is not canonical authority."""

    async def inventory(self, binding: Binding) -> tuple[SourceRef, ...]: ...

    async def read(self, binding: Binding, ref: SourceRef, cursor: int,
                   request_id: str) -> SourcePage: ...


@dataclass(frozen=True)
class Acquisition:
    page: SourcePage
    queue_seconds: float
    latency_seconds: float
    acquired_bytes: int


class AcquisitionHelper:
    def __init__(self, backend: SourceBackend, *, max_parallel_source_reads: int = 4,
                 queue_timeout: float = 1, read_timeout: float = 10) -> None:
        if max_parallel_source_reads < 1 or queue_timeout <= 0 or read_timeout <= 0:
            raise ValueError("POSITIVE_SOURCE_CAPACITY_AND_TIMEOUTS_REQUIRED")
        self.backend = backend
        self.pool = asyncio.Semaphore(max_parallel_source_reads)
        self.queue_timeout, self.read_timeout = queue_timeout, read_timeout
        self.calls: dict[str, Acquisition] = {}
        self.presented: list[tuple[str, str]] = []

    async def resolve_sources(self, binding: Binding) -> tuple[SourceRef, ...]:
        return await asyncio.wait_for(self.backend.inventory(binding), self.read_timeout)

    async def read_source(self, binding: Binding, ref: SourceRef, cursor: int = 0) -> SourcePage:
        rid, start = uuid.uuid4().hex, time.monotonic()
        page = SourcePage(rid, binding, ref.source_id, ref.version, "", cursor, None,
                          Coverage.UNKNOWN)
        acquired, queue, received_bytes = False, 0.0, 0
        queued_at = None
        try:
            current = next((item for item in await self.resolve_sources(binding)
                            if item.source_id == ref.source_id), None)
            if current is None:
                page = replace(page, coverage=Coverage.UNAVAILABLE)
            elif not current.eligible:
                page = replace(page, coverage=Coverage.WITHHELD)
            elif current.version != ref.version:
                page = replace(page, version=current.version, coverage=Coverage.UNKNOWN)
            else:
                queued_at = time.monotonic()
                await asyncio.wait_for(self.pool.acquire(), self.queue_timeout)
                acquired, queue = True, time.monotonic() - queued_at
                returned = await asyncio.wait_for(
                    self.backend.read(binding, ref, cursor, rid), self.read_timeout)
                received_bytes = len(returned.text.encode())
                latest = next((item for item in await self.resolve_sources(binding)
                               if item.source_id == ref.source_id), None)
                if latest is not None and not latest.eligible:
                    page = replace(page, coverage=Coverage.WITHHELD)
                elif (latest is not None and latest.version == ref.version
                      and returned.request_id == rid and returned.binding == binding
                      and returned.source_id == ref.source_id and returned.version == ref.version
                      and returned.cursor == cursor):
                    page = returned
                    if ((page.next_cursor is not None and page.next_cursor <= cursor)
                            or (page.coverage == Coverage.PARTIAL and page.next_cursor is None)
                            or (page.coverage == Coverage.COMPLETE
                                and page.next_cursor is not None)):
                        page = replace(page, text="", coverage=Coverage.UNKNOWN)
                    elif page.coverage not in (Coverage.COMPLETE, Coverage.PARTIAL):
                        page = replace(page, text="")
        except PermissionError:
            page = replace(page, text="", coverage=Coverage.WITHHELD)
        except (TimeoutError, OSError):
            page = replace(page, text="", coverage=Coverage.UNAVAILABLE)
        finally:
            if acquired:
                self.pool.release()
            elif queued_at is not None:
                queue = time.monotonic() - queued_at
        self.calls[rid] = Acquisition(page, queue, time.monotonic() - start, received_bytes)
        return page

    async def bounded_scan(self, binding: Binding, ref: SourceRef,
                           *, max_pages: int) -> tuple[list[SourcePage], Coverage]:
        """Follow this source's public cursor; the bound applies to this one source."""
        pages, cursor = [], 0
        for _ in range(max_pages):
            page = await self.read_source(binding, ref, cursor)
            pages.append(page)
            if page.coverage != Coverage.PARTIAL:
                return pages, page.coverage
            assert page.next_cursor is not None
            cursor = page.next_cursor
        return pages, Coverage.PARTIAL

    async def read_many(self, binding: Binding, refs: tuple[SourceRef, ...]) -> list[SourcePage]:
        return list(await asyncio.gather(*(self.read_source(binding, ref) for ref in refs)))

    async def presentation(self, binding: Binding, request_ids: list[str],
                           model_request_id: str) -> list[SourcePage]:
        """Recheck disclosure before a send; this method never marks a payload as sent."""
        acquired = [self.calls[rid].page for rid in request_ids]
        if any(page.binding != binding for page in acquired):
            raise PermissionError("CROSS_TASK_PRESENTATION")
        try:
            current = {item.source_id: item for item in await self.resolve_sources(binding)}
        except PermissionError:
            return [replace(page, text="", coverage=Coverage.WITHHELD) for page in acquired]
        except (TimeoutError, OSError):
            return [replace(page, text="", coverage=Coverage.UNAVAILABLE) for page in acquired]
        pages = []
        for page in acquired:
            ref = current.get(page.source_id)
            if ref is None or not ref.eligible or ref.version != page.version:
                status = (Coverage.WITHHELD if ref is not None and not ref.eligible
                          else Coverage.UNKNOWN)
                pages.append(replace(page, text="", coverage=status))
            else:
                pages.append(page)
        return pages

    def record_presentation(self, model_request_id: str, pages: list[SourcePage]) -> None:
        """Record the caller's actual transport receipt, not an assembled/unknown send."""
        for page in pages:
            if page.text:
                if self.calls[page.request_id].page != page:
                    raise ValueError("PRESENTATION_DOES_NOT_MATCH_ACQUISITION")
                entry = (model_request_id, page.request_id)
                if entry not in self.presented:
                    self.presented.append(entry)
