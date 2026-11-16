"""Explicit query probes stay auditable without crowding out domain observations."""
import json

import httpx
import pytest
from langgraph.store.sqlite import SqliteStore
from test_given_retrieval import no_http, prepared_given

from milai_lab.memory.service import MemoryService
from milai_lab.methods.evidence_control import EvidenceOperations
from milai_lab.methods.memory_control import MemoryControlState
from milai_lab.methods.query_structure import build_query_structure, cached_structure
from milai_lab.runners.functional import message


@pytest.mark.parametrize("policy", ["fixed_context", "view_cache"])
@pytest.mark.parametrize("source_session", ["reference", "evaluation"])
def test_repeated_probe_exclusion_keeps_real_questions_assertions_and_source_records(
    tmp_path, monkeypatch, policy, source_session,
):
    root = prepared_given(tmp_path, policy={"policy": policy, "view_builder": "extractive",
        "view_policy": "version_cache", "exclude_given_requests": True,
        "max_control_steps": 8, "reads": 4})
    monkeypatch.setattr(httpx.Client, "send", no_http)
    fact = "My reported Cedar code is 4312. I move on Tuesday; how should I pack?"
    proposal = "I could ask about changing the code, but I have not changed it."
    question = "Has my code already changed to 6754?"
    initial = [{"session_id": source_session, "event_key": "m0", "role": "user", "content": fact},
               {"session_id": source_session, "event_key": "m1", "role": "assistant",
                "content": proposal}]
    arrival = {"session_id": source_session, "event_key": "m2", "role": "user", "content": question}
    query = "What Cedar code and move day are reported, and has a code change been confirmed?"
    for index in range(6):
        result = message(root, bank="sequence", owner="alice", session="evaluation",
            message_id=f"p{index}", content=query, given_retrieval_request={"query": query},
            incoming_sources=initial if index == 0 else [arrival] if index == 3 else [])
        assert result["status"] == "COMPLETED", result.get("error")
    evidence = result["retrieval_result"]["evidence"]
    rendered = json.dumps(evidence, ensure_ascii=False)
    assert all(body in rendered for body in [fact, proposal, question])
    assert query not in rendered and "given_retrieval_request" not in rendered
    assert len(result["sources"]) == 9  # All three originals and six supplied queries retained.
    assert sum(s.get("capture_context") == "given_retrieval_request"
               for s in result["sources"]) == 6
    assert all(any(s["content"] == body for s in result["sources"])
               for body in [fact, proposal, question])
    assert result["budget_after"]["generation_requests"] == 0


def test_changed_source_scope_rebuilds_old_probe_view_and_binds_checkpoint_condition(tmp_path):
    with SqliteStore.from_conn_string(str(tmp_path / "bank.sqlite")) as store:
        service = MemoryService(store, ("probe-scope", "alice"), "alice", tmp_path / "lock",
                                functional_contract="functional_v1")
        domain = service.capture_user("reference", "fact", "The Cedar code is 4312.")["source_ref"]
        probe = service.capture_user("evaluation", "query", "Which code?",
                                     capture_context="given_retrieval_request")["source_ref"]
        old, _ = build_query_structure(service, "Cedar code?", "", [domain, probe],
            policy="version_cache", builder="extractive", call=no_http)
        assert probe in {x["source_ref"] for x in old["source_bindings"].values()}
        state = MemoryControlState(task={"request": "Cedar code?", "query_time": ""})
        options = {"load_pool": lambda: [], "refresh_call": no_http, "fits": lambda _: True,
                   "excluded_source_refs": (probe,), "view_builder": "extractive",
                   "view_policy": "version_cache"}
        operations = EvidenceOperations(service, state, **options, exclude_given_requests=True)
        assert not operations.views
        action = next(a for a in operations.actions(state) if a.kind == "REFRESH_VIEW")
        operations.execute(action, state)
        current = cached_structure(service)
        assert {x["source_ref"] for x in current["source_bindings"].values()} == {domain}
        assert service.source(probe)["content"] == "Which code?"
        checkpoint = operations.checkpoint()
        assert checkpoint["configuration"]["exclude_given_requests"] is True
        with pytest.raises(ValueError, match="CONTROL_CHECKPOINT_CONFIGURATION_CHANGED"):
            EvidenceOperations(service, state, **options, checkpoint=checkpoint)
        restored = EvidenceOperations(service, state, **options, exclude_given_requests=True,
                                      checkpoint=checkpoint)
        assert restored.checkpoint() == checkpoint
