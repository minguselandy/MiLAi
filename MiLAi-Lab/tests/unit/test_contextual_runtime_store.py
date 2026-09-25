from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from milai_lab.methods.contextual_memory.models import Observation
from milai_lab.methods.contextual_user_memory import ContextualMemory
from milai_lab.runners.contextual_agent_tasks import accept_observation
from milai_lab.runners.contextual_runtime_store import RuntimeIdentity, RuntimeStore
from milai_lab.runners.contextual_session import HostSession


def embed(texts: list[str]) -> list[list[float]]:
    return [[1.0, 0.0] for _ in texts]


def identity(owner: str = "owner") -> RuntimeIdentity:
    config = {
        "host": {"model": "local-host"},
        "embedding": {"model": "local-embed"},
        "embedding_dimension": 2,
        "embedding_window": {"max_tokens": 128},
        "model_identity": {"host": {"weights": "host-v1"},
                           "embedding": {"weights": "embed-v1"}},
        "state_policy": "off",
        "source_protocol": "publish-retain-project-v1",
        "actor_protocol": "trusted-actor-v1",
    }
    return RuntimeIdentity.from_config(owner, config)


def bank(contract: RuntimeIdentity) -> ContextualMemory:
    memory = ContextualMemory(
        contract.owner_id, host_id=contract.host_model, embed=embed,
        embedding_model=contract.embedding_model,
        embedding_dimension=contract.embedding_dimension,
        embedding_identity=contract.embedding_identity,
        state_policy=contract.state_policy,
    )
    memory.start_task("session-1", "First question")
    return memory


def test_live_session_roundtrip_restores_only_transcript_deliveries(tmp_path: Path) -> None:
    contract = identity()
    memory = bank(contract)
    session = HostSession("session-1", memory)
    session.maintenance = {"review": "pending", "writes": {}}
    delivered = accept_observation(
        memory, session, Observation("shown", "Shown body", "user", "fixture"),
    )
    hidden = accept_observation(
        memory, session, Observation("hidden", "Hidden body", "tool", "fixture"),
        deliver=False,
    )
    shown_ref = delivered["source_ref"]
    hidden_ref = hidden["source_ref"]
    shown_alias = delivered["material"]["materials"][0]["ref"]
    assert shown_ref in memory.seen and hidden_ref not in memory.seen
    rejected = {"status": "ERROR", "decision": "REJECTED", "operation_id": "save:fixture"}
    message = {"role": "user", "content": "json_action tool result: " + json.dumps(
        {"ok": False, "result": rejected},
    )}
    session.transcript.append(message)
    session.record_delivery(message, rejected)
    assert session.deliveries[-1][2] == {}
    session.read_cache["stale"] = 3
    with RuntimeStore(tmp_path, contract) as store:
        store.persist(memory, session, extra={"maintenance_decision": "pending"})

    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        resumed = store.restore_session(restored)
        assert resumed is not None
        assert resumed.transcript == session.transcript
        assert len(resumed.deliveries) == 1
        assert resumed.maintenance == session.maintenance
        assert store.restore_extra() == {"maintenance_decision": "pending"}
        assert resumed.read_cache == {}
        assert resumed.material_view is not None
        assert resumed.material_view.resolve_ref(shown_alias) == shown_ref
        assert shown_ref in restored.seen and hidden_ref not in restored.seen
        assert restored.visible_source_ranges[shown_ref] == {(0, len("Shown body"))}
        assert hidden_ref not in restored.visible_source_ranges
        resumed.transcript[1]["content"] = "edited"
        resumed.refresh_visibility()
        assert shown_ref not in restored.seen


def test_closed_bank_reopens_and_rejects_identity_or_second_writer(tmp_path: Path) -> None:
    contract = identity()
    memory = bank(contract)
    session = HostSession("session-1", memory)
    source = accept_observation(
        memory, session, Observation("basis", "A lasting source", "user", "fixture"),
    )["source_ref"]
    created = memory.save(
        op="CREATE", content="A lasting record", about_ref="unresolved",
        source_refs=[source], dependencies=[], certainty="explicit",
    )["record"]["ref"]
    with RuntimeStore(tmp_path, contract) as store:
        with pytest.raises(ValueError, match="RUNTIME_WRITER_ALREADY_ACTIVE"):
            with RuntimeStore(tmp_path, contract):
                pass
        session.close()
        store.persist(memory, session)
    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        assert created in restored.history or restored.resolve(created) == created
        assert source in restored.sources
        assert store.restore_session(restored) is None
        assert not restored.seen
    with pytest.raises(ValueError, match="RUNTIME_OWNER_MISMATCH"):
        with RuntimeStore(tmp_path, identity("someone-else")):
            pass
    with pytest.raises(ValueError, match="RUNTIME_IDENTITY_MISMATCH"):
        with RuntimeStore(tmp_path, replace(contract, embedding_identity="other-index")):
            pass
    with pytest.raises(ValueError, match="RUNTIME_IDENTITY_MISMATCH"):
        with RuntimeStore(tmp_path, replace(contract, write_contract="other-write")):
            pass


def test_action_intent_and_turn_ids_survive_restart_without_replay(tmp_path: Path) -> None:
    contract = identity()
    memory = bank(contract)
    session = HostSession("session-1", memory)
    session.turn_id = "turn-1"
    input_hash = hashlib.sha256(b"First question").hexdigest()
    with RuntimeStore(tmp_path, contract) as store:
        turn = store.reserve_turn(
            session.session_id, "turn-1", input_sha256=input_hash,
            memory=memory, session=session,
        )
        assert turn["status"] == "new" and turn["turn_index"] == 1
        call_id = store.call_id(session.session_id, "turn-1", 0)
        assert store.begin_action(
            call_id, "send_message", {"body": "hello"},
            memory=memory, session=session,
        )["may_execute"]
    with RuntimeStore(tmp_path, contract) as store:
        restored = store.restore_memory(embed)
        assert restored is not None
        resumed = store.restore_session(restored)
        assert resumed is not None
        assert store.reserve_turn(
            resumed.session_id, "turn-1", input_sha256=input_hash,
            memory=restored, session=resumed,
        )["turn_index"] == 1
        assert store.call_id(resumed.session_id, "turn-1", 0) == call_id
        assert store.begin_action(
            call_id, "send_message", {"body": "hello"},
            memory=restored, session=resumed,
        ) == {"status": "unknown", "may_execute": False, "result": None}
        assert store.pending_actions()[0]["status"] == "unknown"
        assert store.actions_for_turn("session-1", "turn-1")[0]["result"] is None
        with pytest.raises(ValueError, match="RUNTIME_TURN_INPUT_CHANGED"):
            store.reserve_turn(
                resumed.session_id, "turn-1", input_sha256="0" * 64,
                memory=restored, session=resumed,
            )
        store.finish_action(
            call_id, {"status": "succeeded", "output": "sent"},
            memory=restored, session=resumed,
        )
        assert store.pending_actions() == []
        assert store.actions_for_turn("session-1", "turn-1")[0]["result"]["output"] == "sent"
        store.complete_turn(
            resumed.session_id, "turn-1", {"status": "complete", "answer": "done"},
            memory=restored, session=resumed,
        )
    with RuntimeStore(tmp_path, contract) as store:
        assert store.pending_actions() == []
        assert store.completed_turn("session-1", "turn-1") == {
            "status": "complete", "answer": "done",
        }
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["actions"][call_id]["result"]["output"] == "sent"


def test_unknown_settled_action_requires_explicit_reconciliation(tmp_path: Path) -> None:
    contract = identity()
    memory = bank(contract)
    session = HostSession("session-1", memory)
    session.turn_id = "turn-1"
    call_id = RuntimeStore.call_id(session.session_id, session.turn_id, 0)
    with RuntimeStore(tmp_path, contract) as store:
        store.begin_action(
            call_id, "send_message", {"body": "hello"}, memory=memory, session=session,
        )
        store.finish_action(
            call_id, {"status": "unknown", "output": "timeout"}, memory=memory, session=session,
        )
        pending = store.pending_actions()
        assert len(pending) == 1
        assert pending[0]["state"] == "settled"
        assert pending[0]["result"]["output"] == "timeout"
        assert store.actions_for_turn("session-1", "turn-1")[0]["result"]["output"] == "timeout"
        with pytest.raises(ValueError, match="RUNTIME_RECONCILIATION_EVIDENCE_REQUIRED"):
            store.reconcile_action(call_id, {"status": "succeeded"}, evidence={})
        with pytest.raises(ValueError, match="RUNTIME_RECONCILIATION_NOT_DETERMINATE"):
            store.reconcile_action(call_id, {"status": "unknown"}, evidence={"query": "timeout"})
        recorded = store.reconcile_action(
            call_id, {"status": "succeeded", "output": "sent"},
            evidence={"method": "get_message", "message_id": "m1"},
        )
        assert recorded["result"]["status"] == "unknown"
        assert recorded["reconciliation"]["result"]["status"] == "succeeded"
        assert store.pending_actions() == []
    with RuntimeStore(tmp_path, contract) as store:
        assert (
            store.actions_for_turn("session-1", "turn-1")[0]["reconciliation"]
            == recorded["reconciliation"]
        )
