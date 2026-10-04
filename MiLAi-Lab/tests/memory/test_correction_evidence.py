"""N1 synthetic integrity/packing/wire controls; no benchmark or model network."""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore
from test_v13_2_service import save

from milai_lab.contracts.correction_relation import (
    QueryView,
    SelectionPlan,
    canonical,
    text_sha256,
)
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits, http_budget_scope
from milai_lab.harness.http_ownership import PROFILE
from milai_lab.memory import service as service_module
from milai_lab.memory.service import MemoryService
from milai_lab.methods.correction_evidence import pack_complete, render_material
from milai_lab.methods.correction_reader import FrozenBankReader
from milai_lab.providers.contextual_capacity import HostCapacity
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.correction_evidence_eval import AccountedReader, run_query

CFG = "a" * 64
CUTOFF = "2026-01-02T00:00:00+00:00"
TOKENIZER = {"synthetic": "codepoint counter, no model tokenizer claim"}


@pytest.fixture(autouse=True)
def no_network_and_stable_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("N1 mechanical tests deny all sockets")

    monkeypatch.setattr(socket, "socket", denied)

    class Clock:
        @staticmethod
        def now(*args: Any, **kwargs: Any) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    monkeypatch.setattr(service_module, "datetime", Clock)


@contextmanager
def opened(root: Path) -> Iterator[MemoryService]:
    with SqliteStore.from_conn_string(str(root / "memory.sqlite")) as store:
        yield MemoryService(store, ("correction", "owner"), "owner", root / "memory.lock",
                            mutation_contract="event_bound_v1", candidate_contract="read_handle_v1")


def query(service: MemoryService, key: str = "q") -> QueryView:
    return QueryView("archive evidence", service.owner, service.namespace, CUTOFF, CFG, key)


def bank(service: MemoryService, events: list[dict[str, Any]]) -> FrozenBankReader:
    result = FrozenBankReader(service, cutoff=CUTOFF, config_sha256=CFG, token_count=len,
                              tokenizer_identity=TOKENIZER, emit=events.append)
    result.freeze_source_index()
    return result


def test_source_views_unicode_json_cutoff_and_no_query_capture(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    with opened(tmp_path) as service:
        text = "archive evidence: 中文 e\u0301 😀\n原始完整正文"
        ref = service.capture_user("history", "one", text)["source_ref"]
        data = {"label": "archive evidence", "version": 2, "flag": False}
        other = service.capture_user("history", "two", data)["source_ref"]
        future = service.capture_user("history", "future", "archive evidence future")["source_ref"]
        row = dict(service.source(future))
        row["observed_at"] = "2026-01-03T00:00:00+00:00"
        service.store.put(service.sources_namespace, future, row, index=False)
        adapter = bank(service, events)
        initial = service.sources()
        calls = []

        def reader(q: QueryView, material: str, receipt: Any) -> dict[str, Any]:
            calls.append((q, material, receipt))
            assert {item["content"] for item in json.loads(material)["sources"]} == {
                text, canonical(data)}
            return {"raw_answer": "unchanged test response"}

        result = run_query(adapter, query(service), reader, evidence_budget=4000)
        assert len(calls) == 1 and service.sources() == initial
        assert result["accounted_provider_path"] is False
        delivered = {row["source_ref"]: row for row in result["delivery"]["delivered"]}
        assert delivered[ref]["end"] == len(text)
        assert delivered[ref]["content_sha256"] == text_sha256(text)
        assert set(delivered) == {ref, other} and future not in delivered
        pool = next(e for e in events if e["event"] == "correction_candidate_pool")
        assert all("content" not in c for c in pool["snapshot"]["candidates"])
        assert next(e for e in events if e["event"] == "correction_source_index")[
            "excluded_after_cutoff"] == [future]
        assert events[-2]["event"] == "correction_readonly_assertion" and events[-2]["unchanged"]
        with pytest.raises(TypeError):
            QueryView(**{**asdict(query(service)), "gold_answer": "forbidden"})


def test_complete_packer_skips_large_unit_keeps_later_full_unit(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        service.capture_user("history", "huge", "archive evidence " * 400)
        service.capture_user("history", "small", "archive evidence short 😀")
        adapter = bank(service, [])
        snapshot = adapter.retrieve(query(service))
        # Packing diagnostic: force large-first order without making ranking claims.
        candidates = tuple(sorted(snapshot.candidates, key=lambda c: -c.codepoints))
        snapshot = replace(snapshot, candidates=candidates)
        units = []
        for candidate in candidates:
            source = service.source(candidate.source_ref)
            units.append({"source_ref": candidate.source_ref, "role": candidate.role,
                          "observed_at": candidate.observed_at,
                          "range": [0, candidate.codepoints], "content": source["content"]})
        budget = len(render_material([units[1]]))
        plan = SelectionPlan(snapshot.snapshot_sha256, tuple(c.source_ref for c in candidates),
                             (), budget, 0)
        material, receipt = pack_complete(snapshot, plan, units, token_count=len)
        assert json.loads(material)["sources"] == [units[1]]
        assert receipt.material_tokens == budget
        assert receipt.omitted_ids == (candidates[0].source_ref,)
        assert receipt.read_ids == plan.selected_ids
        units[1]["content"] += "tamper"
        with pytest.raises(ValueError, match="SELECTED_BODY_CHANGED"):
            pack_complete(snapshot, plan, units, token_count=len)
        with pytest.raises(ValueError, match="METADATA_EXCEEDS"):
            run_query(adapter, query(service), lambda *_: {}, evidence_budget=1)


def test_owner_config_snapshot_source_and_version_guards_reopen(tmp_path: Path) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user("s1", "event", "archive evidence original")["source_ref"]
        service.bind_source_boundary("s1", "event", [ref])
        saved = save(service, "archive evidence semantic", "save")
        assert saved["ok"]
        adapter = bank(service, [])
        snapshot = adapter.retrieve(query(service))
        assert adapter.read_selected(snapshot, [ref])[0]["content"] == "archive evidence original"
        for bad in (replace(query(service), config_sha256="b" * 64),
                    replace(query(service), owner="other", bank=("correction", "other")),
                    replace(query(service), cutoff="2026-01-01T00:00:00+00:00")):
            with pytest.raises(ValueError, match="QUERY_BINDING_CHANGED"):
                adapter.retrieve(bad)
        forged = replace(snapshot, index_sha256="f" * 64)
        with pytest.raises(ValueError, match="SNAPSHOT_NOT_ISSUED"):
            adapter.read_selected(forged, [ref])
        with pytest.raises(ValueError, match="UNSELECTED_SOURCE_READ"):
            adapter.read_selected(snapshot, ["src-not-in-pool"])
    with opened(tmp_path) as service:
        adapter = bank(service, [])
        assert adapter.retrieve(query(service)) == snapshot
        assert adapter.read_selected(snapshot, [ref])
        item = service.store.get(service.namespace, saved["id"])
        value = json.loads(canonical(item.value))
        value["_v13_1"]["history"][0]["content"] = "changed historic bytes"
        service.store.put(service.namespace, saved["id"], value, index=False)
        with pytest.raises(ValueError, match="VERSION_BINDING_CHANGED"):
            adapter.read_selected(snapshot, [ref])
        with pytest.raises(ValueError, match="FROZEN_BANK_CHANGED"):
            run_query(adapter, query(service), lambda *_: {})


def test_finally_proves_readonly_on_reader_error_and_rejects_mutation(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []
    with opened(tmp_path) as service:
        service.capture_user("history", "one", "archive evidence")
        adapter = bank(service, events)

        def broken(*args: Any) -> dict[str, Any]:
            raise RuntimeError("synthetic reader failure")

        with pytest.raises(RuntimeError, match="synthetic reader"):
            run_query(adapter, query(service), broken)
        assert events[-1]["event"] == "correction_readonly_assertion" and events[-1]["unchanged"]

        def mutation(*args: Any) -> dict[str, Any]:
            service.capture_user("forbidden", "later", "accidental write")
            raise RuntimeError("error after mutation")

        with pytest.raises(ValueError, match="READONLY_FACT_MUTATION") as caught:
            run_query(adapter, query(service), mutation)
        assert isinstance(caught.value.__context__, RuntimeError)
        assert events[-1]["unchanged"] is False


@pytest.mark.parametrize("fault", ["event_id", "role", "object_ref", "body_hash"])
def test_corrupt_pre_freeze_source_identity_is_rejected(tmp_path: Path, fault: str) -> None:
    with opened(tmp_path) as service:
        ref = service.capture_user("history", "event", "archive evidence")["source_ref"]
        source = dict(service.source(ref))
        source.update({
            "event_id": {"event_id": "unrelated-event-id"},
            "role": {"role": "tool"},
            "object_ref": {"object_ref": {"owner": "other"}},
            "body_hash": {"content_sha256": "f" * 64},
        }[fault])
        service.store.put(service.sources_namespace, ref, source, index=False)
        with pytest.raises(ValueError, match=r"SOURCE_.*INVALID|SOURCE_INTEGRITY_FAILED"):
            bank(service, [])


class SyntheticCapacity:
    enable_thinking = False
    identity = TOKENIZER
    text_tokens = staticmethod(len)

    def check(self, messages: Any, output_tokens: int, tools: Any = None) -> dict[str, int]:
        assert not tools
        return {"prompt_tokens": len(canonical(messages)), "safety_tokens": 0,
                "output_reserve_tokens": output_tokens}


@pytest.mark.parametrize("outcome", ["success", "unknown", "budget"])
def test_actual_provider_wire_owned_ledger_single_admission_and_unknown_cost(
    tmp_path: Path, outcome: str,
) -> None:
    events: list[dict[str, Any]] = []
    config = VLLMConfig("http://synthetic.invalid/v1", "synthetic-reader", max_tokens=20,
                        enable_thinking=False)
    ledger = tmp_path / "budget.json"
    limits = RunLimits(generation_requests=0 if outcome == "budget" else 4,
                       generation_tokens=100_000)
    budget = RunBudget(limits, ledger)
    budget._persist()
    settings = {"budget_path": str(ledger), "http_ownership_profile": PROFILE,
                "http_ownership_domain": {"deployment_id": "mechanical-test",
                                          "clients": [asdict(config)]}}
    requests = []

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        assert "tools" not in body
        if outcome == "unknown":
            raise httpx.ReadTimeout("synthetic unknown", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "raw answer"}}],
                                        "usage": {"total_tokens": 12, "prompt_tokens": 10,
                                                  "completion_tokens": 2}})

    with opened(tmp_path) as service:
        source = service.capture_user("history", "one", "archive evidence 中文😀")["source_ref"]
        adapter = bank(service, events)
        with http_budget_scope(settings, limits) as owned:
            with VLLMClient(config, budget=owned, capacity=cast(HostCapacity, SyntheticCapacity()),
                            emit=events.append, transport=httpx.MockTransport(transport)) as client:
                reader = AccountedReader(client, admission_path=tmp_path / "admission.json",
                                         reader_system_prompt="Read only the supplied sources.",
                                         config_sha256=CFG)
                if outcome == "success":
                    prompt = reader.system_prompt
                    reader.system_prompt += " changed after dispatch freeze"
                    with pytest.raises(ValueError, match="READER_BINDING_CHANGED"):
                        run_query(adapter, query(service), reader)
                    assert not requests and not (tmp_path / "admission.json").exists()
                    reader.system_prompt = prompt
                if outcome == "success":
                    result = run_query(adapter, query(service), reader)
                    assert result["reader"]["provider_response"]["choices"][0]["message"][
                        "content"] == "raw answer"
                    assert result["accounted_provider_path"] is True  # mock transport, no model
                    wire = requests[0]["messages"][1]["content"]
                    assert result["delivery"]["material_sha256"] == text_sha256(wire)
                    assert json.loads(wire)["sources"][0]["source_ref"] == source
                else:
                    with pytest.raises(Exception, match=r"synthetic unknown|budget"):
                        run_query(adapter, query(service), reader)
                with pytest.raises(ValueError, match="ALREADY_STARTED"):
                    run_query(adapter, query(service), reader)
        state = json.loads(ledger.read_text())
        assert len(requests) == (0 if outcome == "budget" else 1)
        assert state["generation_requests"] == len(requests)
        assert state["generation"]["unknown_usage"] == (1 if outcome == "unknown" else 0)
        if outcome == "unknown":
            assert state["generation"]["charged_tokens"] > 0
        assertions = [e for e in events if e["event"] == "correction_readonly_assertion"]
        assert len(assertions) == (3 if outcome == "success" else 2)
        assert all(e["unchanged"] for e in assertions)
