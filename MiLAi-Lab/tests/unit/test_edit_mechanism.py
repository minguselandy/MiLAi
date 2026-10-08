"""Real SQLite historical Reader states and honest diagnostic denominators."""

from __future__ import annotations

import copy
import json
from itertools import pairwise
from pathlib import Path

import httpx
import pytest
from langchain_core.embeddings import Embeddings
from langgraph.store.sqlite import SqliteStore

from milai_lab.analysis.edit_mechanism import (
    delta_judge_view,
    summarize_three_views,
    validate_delta,
)
from milai_lab.analysis.edit_views import record_index
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.harness.contextual_artifacts import RunBudget, RunLimits
from milai_lab.memory.edit_units import render_state
from milai_lab.memory.retrieval import SemanticRetriever
from milai_lab.memory.service import MemoryService
from milai_lab.methods.edit_memory import EditMemory
from milai_lab.providers.contextual_vllm import VLLMClient, VLLMConfig
from milai_lab.runners.edit_mechanism import (
    MechanismRun,
    blinded_states,
    controlled_events,
    controlled_observations,
    controls,
    full_answer_payload,
    prior_evidence,
    require_completed_external,
    require_completed_suite,
    require_frozen_candidate,
    restore_current,
    snapshots,
    summarize_controlled,
    summarize_drift,
    summarize_native,
    validate_transition,
)


def row(text: str, revision: int = 1, identity: str = "saved-record") -> dict:
    return {
        "ok": True,
        "id": identity,
        "value": {
            "revision": revision,
            "content": text,
            "scope": {},
            "basis": "user_statement",
            "method_arm": "M",
            "method_version": "actual-method",
        },
    }


def test_controls_retain_actual_revisions_without_ideal_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = [row("Current rule: twice weekly, holidays paused.")]
    after = [row("Current rule: once weekly, holidays paused.", 2)]
    original = copy.deepcopy((before, after))
    assert controls(before, after, "NeverWrite") == before
    retained = controls(before, after, "RetainAll")
    assert len(retained) == 2 and retained[1]["value"] == before[0]["value"]
    assert controls([], after, "NeverWrite") == []
    assert controls(before, before, "RetainAll") == before
    with SqliteStore.from_conn_string(str(tmp_path / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("edit", "diagnostic", "alice"), "alice", tmp_path / "memory.lock"
        )
        restore_current(service, retained)
        found = service.search("weekly", limit=10, include_raw=False)["records"]
        assert {r["value"]["content"] for r in found} == {r["value"]["content"] for r in retained}
        assert service.sources() == []
        restore_current(service, after)
        assert len(service.records()) == 1
        assert service.read("saved-record")["value"] == after[0]["value"]
    class LocalEmbeddings(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if "once weekly" in text else [0.0, 1.0] for text in texts]

        def embed_query(self, text: str) -> list[float]:
            return [1.0, 0.0]

    run = MechanismRun.__new__(MechanismRun)
    run.root = tmp_path / "assessment"
    run.settings = {"retrieval_limit": 10}
    ordinary_answer = run.answer
    probes = []
    requests = []

    def inspect_answer(service, question, date, key):
        probes.append(service)
        if run.settings.get("memory_profile") == "unified_v1":
            assert service.memory_profile == "unified_v1" and service.memory_ranking == "dense"
            assert isinstance(service.semantic_retriever, SemanticRetriever)
            assert service.semantic_retriever.embeddings is run.retrieval_embeddings
        else:
            assert service.memory_profile == "ordinary" and service.semantic_retriever is None
        return ordinary_answer(service, question, date, key)

    def answer_call(key, messages, **kwargs):
        requests.append(messages)
        return "Once weekly; holidays paused."

    monkeypatch.setattr(run, "answer", inspect_answer)
    monkeypatch.setattr(run, "call", answer_call)
    assert run.probe("alice", retained, "weekly", "2030-01-01", "ordinary")["status"] == (
        "ANSWERED"
    )
    run.retrieval_embeddings = LocalEmbeddings()
    run.settings.update(memory_profile="unified_v1", memory_ranking="dense", embedding_dimension=2)
    assert run.probe("alice", retained, "weekly", "2030-01-01", "configured")["status"] == (
        "ANSWERED"
    )
    material = read_json(run.root / "http/configured/reader/retrieval.json")
    assert [memory["content"] for memory in material] == [
        after[0]["value"]["content"], before[0]["value"]["content"],
    ]
    assert all("record_id" in memory for memory in material)
    assert len(probes) == len(requests) == 2
    assert (before, after) == original


def test_blinding_preserves_same_record_and_changed_revision() -> None:
    before, after = blinded_states(
        [row("Old")], [row("New", 2), row("Additional", identity="next")]
    )
    assert before[0]["record_id"] == after[0]["record_id"]
    assert before[0]["revision"] == 1 and after[0]["revision"] == 2
    assert "method_arm" not in str(before) and "method_version" not in str(after)
    assert after[1]["record_id"] != after[0]["record_id"]


def test_conditioned_blinding_renames_only_structural_labels() -> None:
    state = {
        "representation": "conditioned_v1",
        "units": [
            {"unit_id": "internal:M:condition", "role": "condition", "text": "Weekdays"},
            {"unit_id": "internal:M:claim", "role": "content", "text": "Keep literal u7"},
        ],
        "relations": [{"relation_type": "modifies", "source_unit": "internal:M:condition",
                       "target_unit": "internal:M:claim"}],
    }
    original = row(render_state(state))
    original["value"]["edit_state"] = state
    preserved = copy.deepcopy(original)
    before, after = blinded_states([original], [original], renderer=render_state)
    assert before == after and "internal:M:" not in str(before)
    assert "Keep literal u7" in before[0]["content"]
    assert "Applies under: Weekdays" in before[0]["content"]
    assert original == preserved


def test_delta_relation_removal_preserves_context_without_persistent_ids() -> None:
    state = {
        "representation": "conditioned_v1",
        "units": [
            {"unit_id": "internal:B2:condition", "role": "condition", "text": "Weekdays"},
            {"unit_id": "internal:B2:claim", "role": "content", "text": "Twice weekly"},
        ],
        "relations": [{"relation_type": "modifies", "source_unit": "internal:B2:condition",
                       "target_unit": "internal:B2:claim"}],
    }
    before = row(render_state(state))
    before["value"]["edit_state"] = state
    after = copy.deepcopy(before)
    after["value"]["revision"] = 2
    after["value"]["edit_state"]["relations"] = []
    after["value"]["content"] = render_state(after["value"]["edit_state"])
    view = delta_judge_view([before], [after], [{"ok": True, "id": before["id"]}])
    assert view["has_evaluable_delta"] and "internal:B2:" not in str(view)
    delta = view["net_session_delta"][0]
    assert delta["new_or_changed_units"] == []
    assert {u["text"] for u in delta["necessary_current_context"]} == {
        "Weekdays", "Twice weekly",
    }
    judgment = {"status": "VALID", "judgment": {
        "changes_supported": True,
        "unsupported_changes": [{"record_id": "unavailable", "claim": "Rule",
                                 "reason": "No actual target"}],
        "grounding_unknown": [], "reason": "Unsupported",
    }}
    assert validate_delta(judgment, view)["status"] == "INVALID_FIRST_ATTEMPT"


def test_missing_actual_old_bodies_cannot_be_scored_as_valid_prior_claims() -> None:
    before, after = blinded_states([row("Old")], [row("New", 2)])
    judgment = {"status": "VALID", "judgment": {
        "valid_prior_claims": 1, "damaged_valid_prior_claims": [],
        "unsupported_additions": [], "prior_grounding_unknown": [],
        "cancellation_succeeded": None,
    }}
    assert validate_transition(
        judgment, before, after, cancellation=False, prior_sources=[]
    )["status"] == "INVALID_FIRST_ATTEMPT"
    judgment["judgment"].update(valid_prior_claims=0, prior_grounding_unknown=["record_0"])
    assert validate_transition(
        judgment, before, after, cancellation=False, prior_sources=[]
    )["status"] == "VALID"


def test_three_tables_keep_unassessed_and_no_delta_in_fixed_opportunities() -> None:
    rows = [
        {"arm": "B1", "variant": "Actual", "delta_view": {"has_evaluable_delta": changed},
         "delta_assessment": {"status": status, "judgment": {
             "changes_supported": True, "unsupported_changes": [], "grounding_unknown": []}}}
        for changed, status in [(True, "VALID"), (True, "INVALID_FIRST_ATTEMPT"),
                                (False, "NO_EVALUABLE_DELTA")]
    ]
    author = {"B1": {"official_score": {"recall(all)": 0.2}}}
    state = {"B1/Actual": {"opportunities": 3, "non_target_damage_rate_valid_grounded": None}}
    report = summarize_three_views(rows, ["B1"], state, author)
    delta = report["delta_source_faithfulness_table"]["B1"]
    assert delta["fixed_native_opportunities"] == 3
    assert delta["text_or_scope_delta_opportunities"] == 2
    assert delta["supported_delta_all_fixed_opportunities"] == 1 / 3
    assert delta["without_evaluable_delta"] == 1
    assert delta["unavailable_or_invalid_changed_delta"] == 1
    assert report["official_extracted_compat_table"] == author
    assert report["state_after_native_table"]["B1"] == state["B1/Actual"]
    assert not report["author_score_replaced"] and report["extra_state_judge_calls"] == 0


@pytest.mark.parametrize("artifact_layout", ["legacy", "recipe"])
def test_actual_four_arm_native_delta_state_pipeline_is_read_only_and_accounted(
    tmp_path: Path, artifact_layout: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthetic engineering fixture; no actual model or scientific score proof."""
    suite = tmp_path / "suite"
    original = {}
    original_banks = {}
    arms = ["B0", "B1", "B2", "M"]
    for arm in arms:
        root = suite / arm
        bank = root / "banks/alice"
        bank.mkdir(parents=True)
        write_json(root / "actual-config.json", {
            "arm": arm, "interface_version": "I2", "halumem": {"users": ["alice"]},
            **({"maintenance_recipe": "extract_then_edit"} if artifact_layout == "recipe" else {}),
        })
        terminal = "terminal-score.json" if artifact_layout == "recipe" else "terminal.json"
        write_json(root / terminal, {"status": "COMPLETED_EXPERIMENT_PHASE"})
        write_json(bank / "session-order.json", {"original_ordinals": [0, 1]})
        write_json(root / "halumem-official-results.json", {
            "overall_score": {"author_fixture": arm}, "supplemental_denominators": {},
        })
        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
            service = MemoryService(
                store, ("edit", arm, arm, "alice"), "alice", bank / "memory.lock",
                mutation_contract="event_bound_v1", candidate_contract="read_handle_v1",
            )
            method = EditMemory(service, arm, interface_version="I2")
            for step, text in enumerate([
                "Twice weekly; holidays paused.", "Once weekly; holidays paused.",
                "FUTURE_MUST_NOT_ENTER_NATIVE_JUDGE weekly.",
            ]):
                session = f"halumem:alice:session:{step}"
                captured = service.capture_user(
                    session, "actual-user", text,
                    occurred_at=f"2030-01-0{step + 1}" if artifact_layout == "recipe" else None,
                )
                service.bind_source_boundary(session, "boundary", [captured["source_ref"]])
                before = copy.deepcopy(service.records())
                delivery = method.prepare([captured["source_ref"]], "weekly")
                delivery["sources"][0]["timestamp"] = f"2030-01-0{step + 1}"
                view = method.writer_view(delivery)
                if not step:
                    proposal = {"action": "create", "units": [{"text": text, "evidence": ["e1"]}]}
                elif arm in {"B0", "B2"}:
                    proposal = {"action": "rewrite", "target": "r1",
                                "units": [{"text": text, "evidence": ["e1"]}]}
                else:
                    proposal = {"action": "edit", "target": "r1", "edits": [
                        {"operation": "replace", "target_unit": "u1",
                         "text": text, "evidence": ["e1"]},
                    ]}
                receipt = method.apply(
                    session, f"actual:{step}", method.decode_proposal(proposal, view["mapping"])
                )
                assert receipt["ok"]
                if step == 2:
                    future_record = method.apply(session, "future-only", method.decode_proposal(
                        {"action": "create", "units": [{"text": text, "evidence": ["e1"]}]},
                        view["mapping"],
                    ))
                    assert future_record["ok"]
                    continue
                folder = root / "maintenance/halumem/alice" / str(step)
                if artifact_layout == "recipe":
                    write_json(folder / "complete.json", {"receipts": [receipt], "batches": [{
                        "receipts": [receipt], "source_refs": [captured["source_ref"]],
                        "unprocessed": [], "status": "completed",
                    }]})
                    write_json(folder / "batch-0-before.json", before)
                    write_json(folder / "batch-0-after.json", service.records())
                else:
                    write_json(folder / "complete.json", {"receipts": [receipt]})
                    write_json(folder / "batch-0000/complete.json", {"receipts": [receipt]})
                    write_json(folder / "batch-0000/before.json", before)
                    write_json(folder / "batch-0000/after.json", service.records())
                    write_json(folder / "batch-0000/delivery.json", delivery)
                    write_json(folder / "source-coverage.json", {
                        "original_characters": len(text), "source_refs": [captured["source_ref"]],
                    })
                write_json(root / "evaluation/halumem/alice" / str(step) / "complete.json", {
                    "counts": {"formed_sessions": 1}, "records": {},
                })
            original[arm] = copy.deepcopy(service.records())
            original_banks[arm] = {
                (item.namespace, item.key): copy.deepcopy(item.value)
                for item in store.search((), limit=100000)
            }
    case = {"uuid": "alice", "session": 1, "memory_ordinal": 0,
            "date": "2030-01-02", "observed_dialogue": [
                {"role": "user", "content": "Once weekly; holidays paused."},
            ]}
    label = {**case, "classification": "ordinary_update",
             "source_supported_requirement": "Once weekly while holidays remain paused.",
             "guard_against_unsupported_change": "Keep the holiday qualification.",
             "cancellation": False, "uncertainty": "none",
             "diagnostic_question": "What is the current schedule?"}
    selection, review = tmp_path / "selection.json", tmp_path / "review.json"
    write_json(selection, {"selected": [case]})
    write_json(review, {"selection_count": 1, "reviews": [label]})
    requests = []

    def provider(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        payload = json.loads(body["messages"][-1]["content"])
        properties = payload.get("response_schema", {}).get("properties", {})
        if "changes_supported" in properties:
            output = {"changes_supported": True, "unsupported_changes": [],
                      "grounding_unknown": [], "reason": "Synthetic response"}
        elif "initial_target_present" in properties:
            contents = [r["content"] for r in payload["after"]]
            conflict = any("Twice weekly" in t for t in contents) and any(
                "Once weekly" in t for t in contents
            )
            satisfied = any("Once weekly" in t for t in contents) and not conflict
            output = {"initial_target_present": True, "new_requirement_satisfied": satisfied,
                      "valid_prior_claims": 1, "damaged_valid_prior_claims": [],
                      "unsupported_additions": [], "prior_grounding_unknown": [],
                      "current_conflicts": ["Both current values"] if conflict else [],
                      "cancellation_succeeded": None, "reason": "Synthetic response"}
        elif "complete_and_supported" in properties:
            output = {"requirement_correct": True, "complete_and_supported": True,
                      "unsupported_explanations": [], "current_conflicts": [],
                      "reason": "Synthetic response"}
        else:
            output = "Once weekly; holidays paused."
        content = output if isinstance(output, str) else json.dumps(output)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop",
            "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    class Tokenizer:
        def apply_chat_template(self, messages, **kwargs):
            return [1] * sum(len(m["content"]) for m in messages)

    run = MechanismRun.__new__(MechanismRun)
    run.root = tmp_path / "assessment"
    run.settings = {"mechanism": {"arms": arms}, "drift": {"arms": arms},
                    "interface_version": "I2",
                    "model": {"max_tokens": 100}, "context_tokens": 65536, "retrieval_limit": 10}
    if artifact_layout == "recipe":
        class LocalEmbeddings(Embeddings):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                assert "FUTURE_MUST_NOT_ENTER_NATIVE_JUDGE" not in str(texts)
                return [[1.0, 0.0] if "Once weekly" in text else [0.0, 1.0] for text in texts]

            def embed_query(self, text: str) -> list[float]:
                return [1.0, 0.0]

        run.retrieval_embeddings = LocalEmbeddings()
        run.settings.update(memory_profile="unified_v1", memory_ranking="dense",
                            embedding_dimension=2, maintenance_recipe="extract_then_edit")
    original_answer = run.answer
    probe_inputs = []

    def inspect_answer(service, question, date, key):
        arm, variant = key.split("/")[2:4]
        assert service.namespace == ("edit", arm, arm, "alice")
        assert service.source_backlinks == "disabled"
        before, after, _ = snapshots(suite, arm, "alice", 1)
        expected = controls(before, after, variant)
        assert record_index(service.records()) == record_index(expected)
        revisions = {r["id"]: r["value"]["revision"] for r in expected}
        for record in expected:
            metadata = service.store.get(service.namespace, record["id"]).value["_v13_1"]
            assert all(v["revision"] <= record["value"]["revision"] for v in metadata["history"])
            assert service.read(record["id"], record["value"]["revision"] + 1)["ok"] is False
        for candidate in service._rows(service.candidates_namespace):
            bound = candidate["value"]
            assert bound["record_id"] in revisions
            assert bound["revision"] <= revisions[bound["record_id"]]
            assert service.candidate(candidate["id"]) is not None
        original_search = service.search

        def search(*args, **kwargs):
            assert kwargs["include_raw"] is False
            material = original_search(*args, **kwargs)
            assert material["raw_events"] == []
            return material

        monkeypatch.setattr(service, "search", search)
        answer = original_answer(service, question, date, key)
        material = read_json(run.root / "http" / key / "retrieval.json")
        if artifact_layout == "recipe":
            assert {m["record_id"] for m in material} == set(revisions)
            assert {m["content"] for m in material} == {
                r["value"]["content"] for r in expected
            }
            if variant == "NeverWrite":
                assert "Once weekly" not in str(material)
            elif arm in {"B1", "M"}:
                current = next(m for m in material if m["revision"] == 2)
                assert current["revision_evidence"][0]["content"] == (
                    "Once weekly; holidays paused."
                )
                assert current["revision_evidence"][0]["role"] == "user"
                assert current["revision_evidence"][0]["source_revision"] == 1
        probe_inputs.append(material)
        return answer

    monkeypatch.setattr(run, "answer", inspect_answer)
    run.tokenizer = Tokenizer()
    run.budget = RunBudget(RunLimits(), tmp_path / "budget.json")
    run.client = VLLMClient(VLLMConfig("http://synthetic/v1", "test", max_tokens=100),
                            transport=httpx.MockTransport(provider), budget=run.budget)
    try:
        result = run.run_native(suite, selection, review)
        assert result["metrics"]["M/Actual"]["opportunities"] == 1
        assert len(probe_inputs) == 12
        assert len(requests) == 40
        count = run.budget.state["generation_requests"]
        run.run_native(suite, selection, review)
        assert run.budget.state["generation_requests"] == count
        drift = run.run_drift(suite)
        assert len(drift["trajectories"]) == len(arms)
        assert len(requests) == 48
        for request in requests[-8:]:
            payload = json.loads(request["messages"][-1]["content"])
            assert len(payload["observed_dialogue"]) == 1
            assert payload["observed_dialogue"][0]["original_timestamp"] in {
                "2030-01-01", "2030-01-02",
            }
        assert "FUTURE_MUST_NOT_ENTER_NATIVE_JUDGE" not in json.dumps(requests)
        for request in requests:
            if "response_schema" in json.loads(request["messages"][-1]["content"]):
                assert request["response_format"]["type"] == "json_schema"
        tables = read_json(run.root / "r4-three-view-results.json")
        for arm in arms:
            assert tables["delta_source_faithfulness_table"][arm]["valid_delta_judgments"] == 1
            assert tables["official_extracted_compat_table"][arm]["official_score"] == {
                "author_fixture": arm,
            }
            bank = suite / arm / "banks/alice"
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = MemoryService(store, ("edit", arm, arm, "alice"), "alice",
                                        bank / "memory.lock")
                assert record_index(service.records()) == record_index(original[arm])
                assert {
                    (item.namespace, item.key): item.value
                    for item in store.search((), limit=100000)
                } == original_banks[arm]
        if artifact_layout == "recipe":
            run.settings["controlled"] = {"arms": ["M"]}
            manifest = tmp_path / "controlled.json"
            write_json(manifest, {"cases": [{
                "source_cluster": "controlled-alice", "variants": ["en"], "events": [{
                    "event_id": str(step), "review": label,
                    "wordings": {"en": [{"role": "user", "content": text}]},
                    "diagnostic_questions": {"en": label["diagnostic_question"]},
                } for step, text in enumerate([
                    "Twice weekly; holidays paused.", "Once weekly; holidays paused.",
                ])],
            }]})

            def maintain_observed(service, observed, key):
                assert service.namespace == ("edit", "controlled", "en", "M", "controlled-alice")
                assert service.memory_profile == "unified_v1" and service.memory_ranking == "dense"
                assert service.semantic_retriever.embeddings is run.retrieval_embeddings
                captured = service.capture_user(
                    observed.session_id, "user", observed.turns[0]["content"],
                    occurred_at=observed.date,
                )
                service.bind_source_boundary(observed.session_id, "user", [captured["source_ref"]])
                method = EditMemory(service, "M", interface_version="I2")
                delivery = method.prepare([captured["source_ref"]], "weekly")
                view = method.writer_view(delivery)
                unit = {"text": observed.turns[0]["content"], "evidence": ["e1"]}
                proposal = {"action": "edit", "target": "r1", "edits": [{
                    "operation": "replace", "target_unit": "u1", **unit,
                }]} if key.endswith("step-1") else {"action": "create", "units": [unit]}
                receipt = method.apply(
                    observed.session_id, key, method.decode_proposal(proposal, view["mapping"]),
                )
                assert receipt["ok"]
                write_json(
                    run.root / "maintenance" / key / "complete.json", {"receipts": [receipt]},
                )

            monkeypatch.setattr(run, "maintain", maintain_observed)
            monkeypatch.setattr(run, "answer", original_answer)
            controlled = run.run_controlled(manifest)
            assert len(controlled["records"]) == 2
            assert all(r["reader_probe"]["status"] == "ANSWERED" for r in controlled["records"])
            current = read_json(run.root / (
                "http/controlled/controlled-alice/en/M/step-1/reader/retrieval.json"
            ))[0]
            assert current["revision_evidence"][0]["content"] == "Once weekly; holidays paused."
            assert current["revision_evidence"][0]["role"] == "user"
            checkpoints = {
                path: path.read_bytes() for path in (
                    run.root / "controlled/controlled-alice/en/M"
                ).glob("step-*/complete.json")
            }
            count = run.budget.state["generation_requests"]
            run.run_controlled(manifest)
            assert run.budget.state["generation_requests"] == count == 54
            assert all(path.read_bytes() == saved for path, saved in checkpoints.items())
            assert "FUTURE_MUST_NOT_ENTER_NATIVE_JUDGE" not in json.dumps(requests)
    finally:
        run.client.close()


def test_snapshot_availability_does_not_count_no_change_or_unknown_as_committed(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "B1" / "maintenance" / "halumem" / "alice" / "0"
    write_json(folder / "complete.json", {"source_batches": 1})
    write_json(folder / "batch-0000" / "before.json", [row("Old")])
    write_json(folder / "batch-0000" / "after.json", [row("New", 2)])
    write_json(
        folder / "batch-0000" / "complete.json",
        {
            "receipts": [
                {"ok": True, "status": "committed"},
                {"ok": True, "status": "no_change"},
                {
                    "ok": True,
                    "status": "no_change",
                    "replayed": True,
                    "original_status": "committed",
                },
                {"ok": False, "status": "rejected"},
                {"status": "unknown"},
            ],
        },
    )
    before, after, availability = snapshots(tmp_path, "B1", "alice", 0)
    assert before == [row("Old")] and after == [row("New", 2)]
    assert availability["proposals"] == 5
    assert availability["committed_receipts"] == 1
    assert availability["accepted_no_change_receipts"] == 1
    assert availability["original_commits_confirmed_by_replay"] == 1
    assert availability["rejected_receipts"] == 1
    assert availability["other_or_unconfirmed_receipts"] == 1


def test_prior_grounding_fetches_only_actual_old_ranges_without_future_or_arm_labels(
    tmp_path: Path,
) -> None:
    bank = tmp_path / "B0" / "banks" / "alice"
    bank.mkdir(parents=True)
    write_json(tmp_path / "B0" / "actual-config.json", {"arm": "B0"})
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store,
            ("edit", "B0", "B0", "alice"),
            "alice",
            bank / "memory.lock",
            mutation_contract="event_bound_v1",
        )
        source = service.capture_user(
            "halumem:alice:session:0", "old-message", "Twice weekly; holidays paused."
        )
        service.bind_source_boundary(
            "halumem:alice:session:0", "old-message", [source["source_ref"]]
        )
        method = EditMemory(service, "B0")
        evidence = method.prepare([source["source_ref"]], "weekly")["sources"][0]["evidence_id"]
        saved = method.apply(
            "halumem:alice:session:0",
            "save",
            {
                "action": "create",
                "units": [
                    {
                        "text": "Twice weekly; holidays paused.",
                        "role": "content",
                        "evidence": [evidence],
                    }
                ],
            },
        )
        assert saved["ok"]
        before = service.records()
        write_json(
            tmp_path / "B0/maintenance/halumem/alice/0/batch-0000/delivery.json",
            {"sources": [{"source_ref": source["source_ref"], "timestamp": "2030-01-01"}]},
        )
        service.capture_user("future-session", "future-message", "FUTURE_MUST_NOT_ENTER_DIAGNOSTIC")
    grounded = prior_evidence(tmp_path, "B0", "alice", before)
    assert len(grounded) == 1 and grounded[0]["text"] == "Twice weekly; holidays paused."
    assert grounded[0]["role"] == "user" and grounded[0]["source_revision"] == 1
    assert grounded[0]["original_timestamp"] == "2030-01-01"
    assert "FUTURE_MUST_NOT_ENTER_DIAGNOSTIC" not in str(grounded)
    assert "B0" not in str(grounded) and "evidence_id" not in str(grounded)


def test_unconfirmed_paired_arm_and_incomplete_transition_are_not_scored(tmp_path: Path) -> None:
    write_json(tmp_path / "B0" / "terminal.json", {"status": "COMPLETED_EXPERIMENT_PHASE"})
    with pytest.raises(ValueError, match="paired development arm"):
        require_completed_suite(tmp_path, ["B0", "M"])
    folder = tmp_path / "B0" / "maintenance" / "halumem" / "alice" / "3"
    write_json(folder / "complete.json", {"source_batches": 1})
    write_json(folder / "batch-0000" / "before.json", [row("Old")])
    with pytest.raises(ValueError, match="snapshot missing"):
        snapshots(tmp_path, "B0", "alice", 3)
    write_json(folder / "batch-0000" / "after.json", [row("New", 2)])
    write_json(
        folder / "batch-0000" / "complete.json", {"receipts": [{"ok": False, "status": "rejected"}]}
    )
    first, second, availability = snapshots(tmp_path, "B0", "alice", 3)
    assert first[0]["value"]["revision"] == 1
    assert second[0]["value"]["revision"] == 2
    assert availability["rejected_receipts"] == 1


def test_failed_judgments_stay_in_all_opportunities_and_users_are_paired() -> None:
    records = []
    for arm in ["B1", "M"]:
        for variant in ["Actual", "NeverWrite", "RetainAll"]:
            for owner in ["alice", "bob"]:
                valid = owner == "alice"
                judgment = {
                    "new_requirement_satisfied": arm == "M",
                    "initial_target_present": False,
                    "valid_prior_claims": 1,
                    "damaged_valid_prior_claims": [],
                    "unsupported_additions": [],
                    "prior_grounding_unknown": [],
                    "current_conflicts": ["Two incompatible current values"],
                    "cancellation_succeeded": arm == "M",
                }
                records.append(
                    {
                        "uuid": owner,
                        "arm": arm,
                        "variant": variant,
                        "cancellation_opportunity": True,
                        "transition": {
                            "status": "VALID" if valid else "INVALID_FIRST_ATTEMPT",
                            "judgment": judgment,
                        },
                        "answer_assessment": {"status": "ANSWER_UNAVAILABLE"},
                    }
                )
    report = summarize_native(records, ["B1", "M"])
    m = report["metrics"]["M/Actual"]
    assert m["opportunities"] == 2 and m["valid_transition_judgments"] == 1
    assert m["requirement_satisfied_all"] == 0.5
    assert m["requirement_satisfied_valid"] == 1
    assert m["full_answer_supported_all"] == 0
    assert m["initial_target_present"] == 0
    assert m["valid_prior_grounding_opportunities"] == 1
    assert m["current_conflict_opportunities_valid"] == 1
    assert m["cancellation_opportunities"] == 2
    assert m["scored_cancellation_opportunities"] == 1
    assert m["cancellation_succeeded_all"] == 0.5
    paired = report["paired_requirement_effects"]["B1:M"]
    assert paired["users"] == 2 and paired["difference_second_minus_first"] == 0.5
    collateral = report["paired_mechanism_effects"]["B1:M"]["non_target_damage_valid_grounded"]
    assert collateral["paired_users"] == ["alice"]
    assert collateral["unscored_users"] == ["bob"]
    assert collateral["effect"]["users"] == 1 and collateral["lower_is_better"]
    assert m["non_target_damage_rate_valid_grounded"] == 0
    assert m["unsupported_addition_rate_valid"] == 0


def test_full_answer_audit_keeps_every_original_session_and_exact_answer(tmp_path: Path) -> None:
    original = {
        "question": "What is my current rule?",
        "question_date": "2030/03/03",
        "answer": "Once weekly",
        "haystack_session_ids": ["later", "earlier", "unrelated"],
        "haystack_dates": ["2030/02/01", "2030/01/01", "2030/01/15"],
        "haystack_sessions": [
            [{"role": "user", "content": "Change to once weekly", "has_answer": True}],
            [{"role": "user", "content": "Twice weekly", "has_answer": False}],
            [{"role": "assistant", "content": "Unrelated old discussion", "has_answer": False}],
        ],
        "answer_session_ids": ["later"],
    }
    payload = full_answer_payload(original, "Once weekly. An unsupported cause.")
    with pytest.raises(ValueError, match="requires a complete textual answer"):
        full_answer_payload(original, None)  # type: ignore[arg-type]
    assert payload["answer"] == "Once weekly. An unsupported cause."
    assert payload["full_history_sessions"] == 3
    assert [r["session_id"] for r in payload["full_observed_history"]] == [
        "earlier",
        "unrelated",
        "later",
    ]
    assert "has_answer" not in str(payload) and "answer_session_ids" not in payload
    write_json(tmp_path / "M" / "terminal.json", {"status": "COMPLETED_EXPERIMENT_PHASE"})
    with pytest.raises(ValueError, match="external arm"):
        require_completed_external(tmp_path, ["M"])
    (tmp_path / "M/terminal.json").unlink()
    write_json(tmp_path / "M/terminal-predict.json", {"status": "PREDICTIONS_SAVED"})
    with pytest.raises(ValueError, match="external arm"):
        require_completed_external(tmp_path, ["M"])
    with pytest.raises(ValueError, match="development arm"):
        require_completed_suite(tmp_path, ["M"])
    write_json(tmp_path / "M/terminal-score.json", {"status": "COMPLETED_EXTERNAL_PHASE"})
    require_completed_external(tmp_path, ["M"])


def test_recipe_snapshot_keeps_failed_batch_and_numeric_last_state(tmp_path: Path) -> None:
    folder = tmp_path / "M/maintenance/halumem/alice/0"
    batches = [{"status": "completed", "unprocessed": []} for _ in range(11)]
    batches[3] = {"status": "incomplete", "unprocessed": [{
        "phase": "edit", "reason": "EDIT_MAINTENANCE_REQUEST_EXCEEDS_CAPACITY",
    }]}
    write_json(folder / "complete.json", {"batches": batches, "receipts": []})
    write_json(folder / "batch-0-before.json", [row("Initial")])
    write_json(folder / "batch-9-after.json", [row("Earlier")])
    write_json(folder / "batch-10-after.json", [row("Actual final")])
    before, after, availability = snapshots(tmp_path, "M", "alice", 0)
    assert before == [row("Initial")] and after == [row("Actual final")]
    assert availability["actual_source_batches"] == 11
    assert availability["incomplete_maintenance_batches"] == availability["writer_failures"] == 1
    assert availability["committed_receipts"] == 0


def test_continuous_damage_reports_invalid_gaps_and_original_chronology() -> None:
    assessment = {
        "status": "VALID",
        "judgment": {
            "damaged_valid_prior_claims": [{"record_id": "record_0", "claim": "Paused holidays"}],
            "unsupported_additions": [],
            "current_conflicts": [],
            "cancellation_succeeded": None,
        },
    }
    assert (
        validate_transition(assessment, [], [{"record_id": "record_0"}], cancellation=False)[
            "status"
        ]
        == "INVALID_FIRST_ATTEMPT"
    )
    records = [
        {
            "arm": "M",
            "uuid": "alice",
            "chronological_step": 1,
            "session": 61,
            "transition": {"status": "INVALID_FIRST_ATTEMPT"},
        },
        {
            "arm": "M",
            "uuid": "alice",
            "chronological_step": 0,
            "session": 62,
            "transition": assessment,
        },
    ]
    result = summarize_drift(records)["trajectories"]["M/alice"]
    assert [r["session"] for r in result] == [62, 61]
    assert result[-1]["cumulative_damage_events"] == 1
    assert result[-1]["cumulative_valid_judgments"] == 1
    assert result[-1]["unscored_steps_to_date"] == 1
    assert result[-1]["current_conflicts"] is None


def test_controlled_formation_inputs_exclude_reviews_questions_and_future_events() -> None:
    manifest = Path(__file__).parents[2] / "data/manifests/milai-edit-controlled-dialogues-v1.json"
    cases = json.loads(manifest.read_text())["cases"]
    for case in cases:
        for variant in case["variants"]:
            observed = controlled_observations(case, variant)
            assert len(observed) == 5
            assert all(s.date < t.date for s, t in pairwise(observed))
            assert "source_supported_requirement" not in str(observed)
            assert "diagnostic_questions" not in str(observed)
            assert len(observed[0].turns) == 1
    independent = cases[2]
    ordinary = controlled_events(independent, "en")
    swapped = controlled_events(independent, "en_independent_swap")
    assert [r["event_id"] for r in swapped] == [
        "formation",
        "cancel_salmon",
        "salary_raise",
        "retirement_uncertain",
        "unconfirmed_assistant",
    ]
    assert {r["event_id"] for r in ordinary} == {r["event_id"] for r in swapped}
    assert controlled_observations(independent, "en")[-1].turns[0]["role"] == "assistant"
    invalid = {**independent, "independent_order_pair": ["formation", "salary_raise"]}
    with pytest.raises(ValueError, match="adjacent independent updates"):
        controlled_events(invalid, "en_independent_swap")


def test_unfrozen_candidate_and_invalid_controlled_answers_are_not_successes(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.json"
    write_json(candidate, {"status": "PREPARED"})
    with pytest.raises(ValueError, match="Fix the final candidate"):
        require_frozen_candidate({"method_version": "v1"}, candidate)
    rows = [
        {
            "source_cluster": "story",
            "variant": "en",
            "arm": "M",
            "chronological_step": 1,
            "classification": "scope_override",
            "cancellation_opportunity": True,
            "transition": {"status": "INVALID_FIRST_ATTEMPT"},
            "answer_assessment": {"status": "ANSWER_UNAVAILABLE"},
        }
    ]
    metrics = summarize_controlled(rows, ["M"])["metrics"]["M"]
    assert metrics["opportunities"] == 1 and metrics["valid_transition_judgments"] == 0
    assert metrics["scope_transition_and_full_answer_correct_all"] == 0
    assert metrics["cancellation_succeeded_all"] == 0
    assert metrics["full_answer_supported_all"] == 0


def test_supported_answer_without_the_required_result_is_not_scope_success() -> None:
    rows = [
        {
            "source_cluster": "story",
            "variant": "en",
            "arm": "M",
            "chronological_step": 1,
            "classification": "scope_override",
            "cancellation_opportunity": False,
            "transition": {
                "status": "VALID",
                "judgment": {
                    "new_requirement_satisfied": True,
                    "damaged_valid_prior_claims": [],
                    "unsupported_additions": [],
                },
            },
            "answer_assessment": {
                "status": "VALID",
                "judgment": {
                    "requirement_correct": False,
                    "complete_and_supported": True,
                },
            },
        }
    ]
    metrics = summarize_controlled(rows, ["M"])["metrics"]["M"]
    assert metrics["full_answer_supported_all"] == 1
    assert metrics["full_answer_correct_and_supported_all"] == 0
    assert metrics["scope_transition_and_full_answer_correct_all"] == 0
