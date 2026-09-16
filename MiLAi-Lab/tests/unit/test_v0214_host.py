"""D1-D4 mechanical contracts: scope, current disclosure, delivery and durable reserves."""

import asyncio
import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from milai_lab.methods.host_acquisition import (
    AcquisitionHelper,
    Binding,
    Coverage,
    SourcePage,
    SourceRef,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from v0214_budget import BudgetContract, DeliveryBudget
from v0214_delivery import Readiness, check_delivery
from v0214_source_binding import FileSources, acquire_for_task

SCOPE = Binding("person", "project", "task")


class Backend:
    def __init__(self, *, delay=0, change=None):
        self.refs = (SourceRef("same.txt", "v1"),)
        self.delay, self.change = delay, change
        self.active, self.peak = 0, 0

    async def inventory(self, binding):
        return self.refs

    async def read(self, binding, ref, cursor, request_id):
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(self.delay)
            page = SourcePage(request_id, binding, ref.source_id, ref.version,
                              binding.task, cursor, None, Coverage.COMPLETE)
            return self.change(page) if self.change else page
        finally:
            self.active -= 1


@pytest.mark.parametrize("size,max_pages,expected", [
    (0, 1, Coverage.COMPLETE), (20, 1, Coverage.COMPLETE),
    (20, 0, Coverage.PARTIAL), (70000, 16, Coverage.PARTIAL),
])
def test_scan_empty_one_zero_and_more_than_sixteen(tmp_path, size, max_pages, expected):
    (tmp_path / "source-01.txt").write_text("a" * size)

    async def run():
        backend = FileSources({SCOPE: tmp_path})
        helper = AcquisitionHelper(backend)
        ref = (await helper.resolve_sources(SCOPE))[0]
        pages, status = await helper.bounded_scan(SCOPE, ref, max_pages=max_pages)
        assert status == expected
        assert helper.presented == []
        if pages and status == Coverage.PARTIAL:
            assert pages[-1].next_cursor is not None
        if status == Coverage.COMPLETE:
            assert "".join(page.text for page in pages) == "a" * size
    asyncio.run(run())


@pytest.mark.parametrize("change", [
    lambda p: replace(p, request_id="late-other-request"),
    lambda p: replace(p, binding=Binding("other", "project", "task")),
    lambda p: replace(p, source_id="different.txt"),
    lambda p: replace(p, version="v0"),
    lambda p: replace(p, coverage=Coverage.PARTIAL, next_cursor=0),
    lambda p: replace(p, coverage=Coverage.PARTIAL, next_cursor=None),
])
def test_late_wrong_scope_version_and_broken_cursor_do_not_disclose(change):
    async def run():
        helper = AcquisitionHelper(Backend(change=change))
        page = await helper.read_source(SCOPE, SourceRef("same.txt", "v1"))
        assert page.coverage == Coverage.UNKNOWN and page.text == ""
    asyncio.run(run())


def test_version_revocation_rechecks_before_presentation_and_cold_recovery(tmp_path):
    source = tmp_path / "source-01.txt"
    source.write_text("old material")

    async def run():
        backend = FileSources({SCOPE: tmp_path})
        helper = AcquisitionHelper(backend)
        ref = (await helper.resolve_sources(SCOPE))[0]
        page = await helper.read_source(SCOPE, ref)
        prepared = await helper.presentation(SCOPE, [page.request_id], "not-sent")
        assert helper.presented == []
        helper.record_presentation("sent", prepared)
        assert helper.presented == [("sent", page.request_id)]
        backend.withheld.add((SCOPE, ref.source_id))
        hidden = await helper.presentation(SCOPE, [page.request_id], "second")
        assert hidden[0].coverage == Coverage.WITHHELD and hidden[0].text == ""
        backend.withheld.clear()
        source.write_text("current material")
        stale = await helper.read_source(SCOPE, ref, cursor=1)
        assert stale.coverage == Coverage.UNKNOWN and stale.text == ""
        cold = AcquisitionHelper(FileSources({SCOPE: tmp_path}))
        new_ref = (await cold.resolve_sources(SCOPE))[0]
        assert (await cold.read_source(SCOPE, new_ref)).text == "current material"
        assert cold.calls.keys() != helper.calls.keys() and cold.presented == []
    asyncio.run(run())


def test_tasks_with_identical_filename_are_correlated_and_cross_presentation_denied():
    async def run():
        backend = Backend(delay=0.005)
        helper = AcquisitionHelper(backend, max_parallel_source_reads=2)
        scopes = [Binding("u1", "p", "first"), Binding("u2", "p", "second")]
        pages = await asyncio.gather(*(helper.read_source(s, backend.refs[0]) for s in scopes))
        assert [p.text for p in pages] == ["first", "second"] and backend.peak == 2
        with pytest.raises(PermissionError, match="CROSS_TASK"):
            await helper.presentation(scopes[0], [pages[1].request_id], "bad")
    asyncio.run(run())


def test_bounded_pool_overload_timeout_and_unavailable_are_not_no_source():
    async def run():
        backend = Backend(delay=0.03)
        helper = AcquisitionHelper(backend, max_parallel_source_reads=1, queue_timeout=0.002)
        pages = await asyncio.gather(*(
            helper.read_source(SCOPE, backend.refs[0]) for _ in range(3)))
        assert backend.peak == 1
        assert sum(page.coverage == Coverage.UNAVAILABLE for page in pages) == 2
        timeout = AcquisitionHelper(backend, read_timeout=0.001)
        assert (await timeout.read_source(SCOPE, backend.refs[0])).coverage == Coverage.UNAVAILABLE
        backend.refs = ()
        assert await helper.resolve_sources(SCOPE) == ()
    asyncio.run(run())


TOOLS = [{"name": "lookup", "parameters": {"type": "object", "properties": {
    "id": {"type": "string"}, "days": {"type": "integer", "default": 3},
    "mode": {"enum": ["brief", "full"]}}, "required": ["id"]}}]


@pytest.mark.parametrize("arguments,error", [({}, "required"),
    ({"id": 5}, "type"), ({"id": "new", "mode": "unknown"}, "enum"),
    ({"id": "old"}, "current")])
def test_required_type_enum_current_input(arguments, error):
    result = check_delivery({"action": "business", "calls": [
        {"name": "lookup", "arguments": arguments}]}, TOOLS, current_inputs={"id": "new"})
    assert not result.structurally_valid and result.readiness == Readiness.NEEDS_CLARIFICATION
    assert result.errors


def test_optional_missing_does_not_inject_default_and_semantics_stays_unknown():
    result = check_delivery({"action": "business", "calls": [
        {"name": "lookup", "arguments": {"id": "new"}}]}, TOOLS)
    assert result.structurally_valid and result.readiness == Readiness.READY
    assert result.complete_plan[0]["arguments"] == {"id": "new"}
    assert result.semantic_correct is None and not result.external_executed


@pytest.mark.parametrize("missing", ["subject identity", "business ID", "date", "address",
                                     "coordinates"])
def test_missing_business_inputs_allow_explicit_clarification_without_guess(missing):
    for action in ("clarify", "abstain"):
        result = check_delivery({"action": action, "calls": [],
                                 "answer": f"Please provide {missing}."}, TOOLS)
        assert result.structurally_valid and result.readiness == Readiness.NEEDS_CLARIFICATION
        assert result.first_intent is None


def test_final_reserve_generation_slot_and_durable_unknown_usage(tmp_path):
    contract = BudgetContract(3, 65536, 4096, 9000)
    ledger = tmp_path / "budget.jsonl"
    budget = DeliveryBudget(ledger, contract)
    assert budget.reserve("one", 30000) == "ALLOW"  # no restored 20k raw cap
    resumed = DeliveryBudget(ledger, contract)
    assert resumed.allow(7000) == "UNKNOWN_USAGE_STOP"
    with pytest.raises(ValueError, match="USAGE_BOUND"):
        resumed.settle("one", 30001)
    assert resumed.allow(7000) == "UNKNOWN_USAGE_STOP"
    resumed.settle("one", 22000)
    assert resumed.reserve("two", 7000) == "ALLOW"
    resumed.settle("two", 6000)
    assert resumed.allow(7000) == "FINAL_ONLY"
    assert resumed.allow(7000, final=True) == "ALLOW"
    assert resumed.allow(70000, final=True) == "CONTEXT_LIMIT"
    limited = DeliveryBudget(tmp_path / "historical.jsonl", replace(contract, raw_limit=20000))
    assert limited.allow(12000) == "FINAL_ONLY"
    assert limited.allow(12000, final=True) == "ALLOW"


def test_selective_long_source_deterministic_and_no_memory_needed(tmp_path):
    source = tmp_path / "source-01.txt"
    source.write_text("unrelated schedule note\n" * 4000 + "Project Orion lookup id=ZX-91.\n"
                      + "unrelated schedule note\n" * 4000)

    async def run():
        backend = FileSources({SCOPE: tmp_path})
        helper = AcquisitionHelper(backend)
        task = {"question": "Retrieve Project Orion's id", "business_tools": TOOLS}
        pages, info = await acquire_for_task(helper, backend, SCOPE, task)
        assert info["mode"] == "LEXICAL_SEARCH" and info["coverage"] == "PARTIAL"
        assert any("ZX-91" in page.text for page in pages)
        again = await backend.search(SCOPE, task["question"], TOOLS)
        assert info["search"]["spans"] == again["spans"]
        none, mode = await acquire_for_task(helper, backend, SCOPE,
                                             {**task, "history_needed": False})
        assert none == [] and mode["mode"] == "NO_MEMORY_NEEDED"
        exact, direct = await acquire_for_task(helper, backend, SCOPE,
            {**task, "exact_source": "source-01.txt"})
        assert len(exact) == 1 and direct["mode"] == "EXACT_READ"
    asyncio.run(run())


def test_queue_accounting_excludes_inventory_and_counts_timeout():
    class SlowInventory(Backend):
        async def inventory(self, binding):
            await asyncio.sleep(0.025)
            return self.refs

    async def run():
        backend = SlowInventory(delay=0.025)
        helper = AcquisitionHelper(backend, max_parallel_source_reads=1, queue_timeout=0.004)
        pages = await asyncio.gather(*(helper.read_source(SCOPE, backend.refs[0])
                                       for _ in range(3)))
        rejected = [helper.calls[p.request_id] for p in pages
                    if p.coverage == Coverage.UNAVAILABLE]
        assert len(rejected) == 2
        assert all(0 < item.queue_seconds < item.latency_seconds / 2 for item in rejected)
    asyncio.run(run())


def test_revoked_during_read_counts_received_bytes_but_never_presents_body():
    class Revoked(Backend):
        async def read(self, binding, ref, cursor, request_id):
            page = await super().read(binding, ref, cursor, request_id)
            self.refs = (replace(ref, eligible=False),)
            return page

    async def run():
        helper = AcquisitionHelper(Revoked())
        page = await helper.read_source(SCOPE, SourceRef("same.txt", "v1"))
        assert page.coverage == Coverage.WITHHELD and page.text == ""
        assert helper.calls[page.request_id].acquired_bytes == len(SCOPE.task.encode())
        prepared = await helper.presentation(SCOPE, [page.request_id], "model")
        helper.record_presentation("model", prepared)
        assert helper.presented == []
    asyncio.run(run())


def test_presentation_unavailable_is_masked_and_receipt_cannot_invent_page():
    async def run():
        backend = Backend()
        helper = AcquisitionHelper(backend)
        page = await helper.read_source(SCOPE, backend.refs[0])
        with pytest.raises(ValueError, match="DOES_NOT_MATCH"):
            helper.record_presentation("forged", [replace(page, text="not actually read")])
        helper.record_presentation("sent", [page])
        helper.record_presentation("sent", [page])
        assert helper.presented == [("sent", page.request_id)]

        async def missing(binding):
            raise OSError("offline")
        backend.inventory = missing
        hidden = await helper.presentation(SCOPE, [page.request_id], "not-sent")
        assert hidden[0].coverage == Coverage.UNAVAILABLE and hidden[0].text == ""
    asyncio.run(run())


def test_symlink_and_withheld_inventory_do_not_read_forbidden_body(tmp_path, monkeypatch):
    forbidden = tmp_path / "outside.txt"
    forbidden.write_text("not authorized")
    (tmp_path / "source-link.txt").symlink_to(forbidden)
    protected = tmp_path / "source-protected.txt"
    protected.write_text("withheld content")
    backend = FileSources({SCOPE: tmp_path})
    backend.withheld.add((SCOPE, protected.name))
    original = Path.read_bytes

    def checked(path):
        assert path not in (forbidden, protected, tmp_path / "source-link.txt")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", checked)

    async def run():
        refs = await backend.inventory(SCOPE)
        assert len(refs) == 2 and all(not ref.eligible for ref in refs)
        assert (await backend.search(SCOPE, "content", TOOLS))["spans"] == []
    asyncio.run(run())


def test_lexical_selection_returns_offsets_not_unpresented_text_and_rechecks(tmp_path,
                                                                          monkeypatch):
    import v0214_source_binding as module
    (tmp_path / "source-01.txt").write_text("Project Orion lookup id=ZX-91. " * 100)
    backend = FileSources({SCOPE: tmp_path})
    original = module.retrieve

    async def run():
        found = await backend.search(SCOPE, "Project Orion", TOOLS)
        assert found["spans"] and all("text" not in span for span in found["spans"])
        assert found["original_question"] == "Project Orion"
        assert "lookup" in found["query"] and "days" in found["query"]

        def revoked(*args):
            result = original(*args)
            backend.withheld.add((SCOPE, "source-01.txt"))
            return result
        monkeypatch.setattr(module, "retrieve", revoked)
        assert (await backend.search(SCOPE, "Project Orion", TOOLS))["spans"] == []
    asyncio.run(run())


def test_no_memory_needed_does_not_even_resolve_an_unbound_source():
    async def run():
        backend = FileSources({})
        helper = AcquisitionHelper(backend)
        pages, info = await acquire_for_task(helper, backend, SCOPE, {"history_needed": False})
        assert pages == [] and info["mode"] == "NO_MEMORY_NEEDED" and helper.calls == {}
    asyncio.run(run())


def test_missing_source_root_is_unavailable_not_empty_inventory(tmp_path):
    async def run():
        backend = FileSources({SCOPE: tmp_path / "not-mounted"})
        helper = AcquisitionHelper(backend)
        with pytest.raises(FileNotFoundError, match="SOURCE_ROOT_UNAVAILABLE"):
            await helper.resolve_sources(SCOPE)
        page = await helper.read_source(SCOPE, SourceRef("source-01.txt", "old"))
        assert page.coverage == Coverage.UNAVAILABLE
    asyncio.run(run())


@pytest.mark.parametrize("answer", [None, 5, ["missing"], {}])
def test_clarification_boundary_rejects_non_text_without_crashing(answer):
    assert not check_delivery({"action": "clarify", "calls": [], "answer": answer},
                              TOOLS).structurally_valid


def test_current_input_null_presence_and_bool_are_not_python_equal():
    tools = [{"name": "lookup", "parameters": {"type": "object", "properties": {
        "id": {"type": ["string", "null"]}, "value": {}}, "required": []}}]
    assert not check_delivery({"action": "business", "calls": [{"name": "lookup",
        "arguments": {}}]}, tools, current_inputs={"id": None}).structurally_valid
    assert not check_delivery({"action": "business", "calls": [{"name": "lookup",
        "arguments": {"value": 1}}]}, tools, current_inputs={"value": True}).structurally_valid
    assert not check_delivery({"action": "business", "calls": [{"name": [],
        "arguments": {}}]}, tools).structurally_valid


def test_budget_real_process_resumption_and_competing_reservations(tmp_path):
    ledger = tmp_path / "cross-process.jsonl"
    code = (
        "import json,sys; from pathlib import Path; "
        "from v0214_budget import BudgetContract,DeliveryBudget; "
        "b=DeliveryBudget(Path(sys.argv[1]),BudgetContract(3,65536,4096,9000)); "
        "print(json.dumps(b.reserve(sys.argv[2],12000)))"
    )
    processes = [subprocess.Popen(  # noqa: S603 -- fixed local test interpreter/program
        [sys.executable, "-c", code, str(ledger), name], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, cwd=Path(__file__).resolve().parents[2] / "tools")
        for name in ("left", "right")]
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))
    assert sorted(results) == ["ALLOW", "UNKNOWN_USAGE_STOP"]
    budget = DeliveryBudget(ledger, BudgetContract(3, 65536, 4096, 9000))
    assert budget.allow(12000) == "UNKNOWN_USAGE_STOP"
    assert len(budget.state()[2]) == 1
    with pytest.raises(ValueError, match="CONTRACT_CHANGED"):
        DeliveryBudget(ledger, BudgetContract(4, 65536, 4096, 9000))
    winner = next(iter(budget.state()[2]))
    budget.settle(winner, 9000)
    with pytest.raises(ValueError, match="DUPLICATE_REQUEST"):
        budget.reserve(winner, 12000)
