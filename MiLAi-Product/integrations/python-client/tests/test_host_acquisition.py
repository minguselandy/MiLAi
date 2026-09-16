"""Opt-in callback mechanics only; no claims about live Product permission enforcement."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

import milai_client
from milai_client.host_acquisition import (
    AcquisitionHelper,
    Binding,
    Coverage,
    SourcePage,
    SourceRef,
)

SCOPE = Binding("user", "project", "task")


class Backend:
    def __init__(self, *, pages: int = 1, delay: float = 0) -> None:
        self.refs = (SourceRef("document", "v1"),)
        self.pages, self.delay = pages, delay
        self.active = self.peak = 0
        self.revoke_after_read = False
        self.change = None

    async def inventory(self, binding: Binding) -> tuple[SourceRef, ...]:
        return self.refs

    async def read(self, binding: Binding, ref: SourceRef, cursor: int,
                   request_id: str) -> SourcePage:
        self.active += 1
        self.peak = max(self.active, self.peak)
        try:
            await asyncio.sleep(self.delay)
            more = cursor + 1 < self.pages
            page = SourcePage(request_id, binding, ref.source_id, ref.version, binding.task,
                              cursor, cursor + 1 if more else None,
                              Coverage.PARTIAL if more else Coverage.COMPLETE)
            if self.revoke_after_read:
                self.refs = (replace(ref, eligible=False),)
            return self.change(page) if self.change else page
        finally:
            self.active -= 1


def test_module_is_explicit_opt_in_not_added_to_package_default_exports() -> None:
    assert milai_client.__version__ == "0.1.4"
    assert not hasattr(milai_client, "AcquisitionHelper")


@pytest.mark.parametrize("total,bound,status", [(1, 1, Coverage.COMPLETE),
    (20, 16, Coverage.PARTIAL), (2, 2, Coverage.COMPLETE), (1, 0, Coverage.PARTIAL)])
def test_follow_public_cursor_and_do_not_claim_eof_at_page_limit(total, bound, status) -> None:
    async def run() -> None:
        backend = Backend(pages=total)
        helper = AcquisitionHelper(backend)
        pages, coverage = await helper.bounded_scan(SCOPE, backend.refs[0], max_pages=bound)
        assert coverage == status and len(pages) == min(total, bound)
        assert helper.presented == []
        if coverage == Coverage.PARTIAL and pages:
            assert pages[-1].next_cursor is not None
    asyncio.run(run())


@pytest.mark.parametrize("field,value", [
    ("request_id", "another-request"), ("source_id", "other-source"), ("version", "old"),
    ("binding", Binding("another-user", "project", "task")), ("cursor", 99),
    ("next_cursor", 0),
])
def test_reject_cross_scope_stale_misassociated_and_nonadvancing_pages(field, value) -> None:
    async def run() -> None:
        backend = Backend()
        backend.change = lambda page: replace(page, **{field: value})
        helper = AcquisitionHelper(backend)
        page = await helper.read_source(SCOPE, backend.refs[0])
        assert page.coverage == Coverage.UNKNOWN and not page.text
    asyncio.run(run())


def test_qualification_before_after_read_and_before_each_presentation() -> None:
    async def run() -> None:
        backend = Backend()
        helper = AcquisitionHelper(backend)
        ref = backend.refs[0]
        page = await helper.read_source(SCOPE, ref)
        prepared = await helper.presentation(SCOPE, [page.request_id], "pending")
        assert prepared[0].text and helper.presented == []
        helper.record_presentation("sent", prepared)
        helper.record_presentation("sent", prepared)
        assert helper.presented == [("sent", page.request_id)]
        with pytest.raises(ValueError, match="DOES_NOT_MATCH"):
            helper.record_presentation("forged", [replace(page, text="invented body")])
        backend.refs = (replace(ref, eligible=False),)
        hidden = await helper.presentation(SCOPE, [page.request_id], "next")
        assert hidden[0].coverage == Coverage.WITHHELD and not hidden[0].text
        denied = await helper.read_source(SCOPE, ref)
        assert denied.coverage == Coverage.WITHHELD
        backend.refs = (replace(ref, version="v2"),)
        stale = await helper.read_source(SCOPE, ref)
        assert stale.coverage == Coverage.UNKNOWN and not stale.text
        assert not (await helper.presentation(SCOPE, [page.request_id], "changed"))[0].text
        backend.refs = (ref,)
        backend.revoke_after_read = True
        revoked = await helper.read_source(SCOPE, ref)
        assert revoked.coverage == Coverage.WITHHELD and not revoked.text
        assert helper.calls[revoked.request_id].acquired_bytes == len(SCOPE.task.encode())
    asyncio.run(run())


def test_independent_tasks_overlap_and_responses_remain_bound_to_request() -> None:
    async def run() -> None:
        backend = Backend(delay=0.01)
        helper = AcquisitionHelper(backend, max_parallel_source_reads=2)
        bindings = [Binding("user-a", "p", "first"), Binding("user-b", "p", "second")]
        pages = await asyncio.gather(*(helper.read_source(binding, backend.refs[0])
                                       for binding in bindings))
        assert backend.peak == 2 and [p.text for p in pages] == ["first", "second"]
        with pytest.raises(PermissionError, match="CROSS_TASK"):
            await helper.presentation(bindings[0], [pages[1].request_id], "wrong")
        assert len({page.request_id for page in pages}) == 2
    asyncio.run(run())


def test_overload_has_bounded_wait_and_is_not_empty_source_inventory() -> None:
    async def run() -> None:
        backend = Backend(delay=0.03)
        helper = AcquisitionHelper(backend, max_parallel_source_reads=1, queue_timeout=0.002)
        pages = await asyncio.gather(*(helper.read_source(SCOPE, backend.refs[0])
                                       for _ in range(3)))
        rejected = [page for page in pages if page.coverage == Coverage.UNAVAILABLE]
        assert len(rejected) == 2 and backend.peak == 1
        assert all(helper.calls[page.request_id].queue_seconds > 0 for page in rejected)
        backend.refs = ()
        assert await helper.resolve_sources(SCOPE) == ()
    asyncio.run(run())


@pytest.mark.parametrize("error,status", [(PermissionError(), Coverage.WITHHELD),
                                         (OSError(), Coverage.UNAVAILABLE)])
def test_unavailable_or_withheld_qualification_never_discloses_acquired_body(error, status) -> None:
    async def run() -> None:
        backend = Backend()
        helper = AcquisitionHelper(backend)
        page = await helper.read_source(SCOPE, backend.refs[0])

        async def fail(binding):
            raise error
        backend.inventory = fail
        presented = await helper.presentation(SCOPE, [page.request_id], "next")
        assert presented[0].coverage == status and not presented[0].text
    asyncio.run(run())


def test_invalid_external_capacity_configuration_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="POSITIVE_SOURCE_CAPACITY"):
        AcquisitionHelper(Backend(), max_parallel_source_reads=0)


def test_empty_eof_is_complete_and_partial_without_cursor_is_unknown() -> None:
    async def run() -> None:
        backend = Backend()
        backend.change = lambda page: replace(page, text="")
        helper = AcquisitionHelper(backend)
        empty = await helper.read_source(SCOPE, backend.refs[0])
        assert empty.coverage == Coverage.COMPLETE and not empty.text
        backend.change = lambda page: replace(page, coverage=Coverage.PARTIAL, next_cursor=None)
        broken = await helper.read_source(SCOPE, backend.refs[0])
        assert broken.coverage == Coverage.UNKNOWN and not broken.text
    asyncio.run(run())


def test_read_many_returns_source_order_despite_concurrent_completion() -> None:
    async def run() -> None:
        backend = Backend(delay=0.005)
        backend.refs = (SourceRef("one", "v1"), SourceRef("two", "v1"))
        helper = AcquisitionHelper(backend, max_parallel_source_reads=2)
        pages = await helper.read_many(SCOPE, backend.refs)
        assert [page.source_id for page in pages] == ["one", "two"]
        assert backend.peak == 2 and len(helper.calls) == 2
    asyncio.run(run())
