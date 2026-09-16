import json
from pathlib import Path

import pytest

from milai_lab.methods.controlled_workspace import MemoryCard
from milai_lab.methods.evidence_utility_session import EvidenceUtilitySession, messages_digest
from milai_lab.methods.reasoning_bank import BankConfig, ExperienceBank, ReasoningBankSession

ROOT = Path(__file__).resolve().parents[2]


def session(responses, *, regime="H", protocol="O", bank=None):
    policies = {
        p.stem: p.read_text() for p in (ROOT / "configs/policies/reasoning_bank").glob("*.txt")
    }
    policies.update(
        {
            p.stem: p.read_text()
            for p in (ROOT / "configs/policies/experience_revision/v07").glob("*.txt")
        }
    )
    policies["utility_contract"] = json.dumps(
        {"feedback_regime": regime, "selector_version": "A1-v1"}
    )
    config = BankConfig(embedding_dimension=2)
    if bank is None:
        bank = ExperienceBank(
            {
                "experiment": "utility-fixture",
                "method": "MILAI_EXPERIENCE_REVISION",
                "model": "fixture",
                "domain": "fixture",
                "method_version": EvidenceUtilitySession.method_version,
                "split": "TEST",
                "protocol": protocol,
                "stream": "1",
            },
            ReasoningBankSession.contract(config, policies),
            cards={"card:1": MemoryCard("card:1", "OLD_CONDITIONAL_ADVICE", ["source:1"])},
            sources={"source:1": "Original observed episode, not the current task."},
            records=[
                {
                    "task_id": "support",
                    "query": "prior",
                    "embedding": [1.0, 0.0],
                    "handles": ["card:1"],
                }
            ],
            next_card=2,
            next_source=2,
        )
    pending = iter(responses)
    calls = []

    def generate(call):
        calls.append(call)
        return next(pending)

    value = EvidenceUtilitySession(
        bank=bank,
        config=config,
        policies=policies,
        generate=generate,
        embed=lambda texts: [[1.0, 0.0] for _ in texts],
        post_task_revision=True,
        task_costs=lambda: {"settled_requests": len(calls), "unknown_requests": 0},
    )
    return value, calls


def adopt(*refs):
    return json.dumps({"frame": {"selected_refs": list(refs)}})


def confirm(value, *, history=()):
    messages = [{"role": "system", "content": value.memory_context()}, *history]
    value.prepare_actor_input(messages)
    receipt = {
        "session": value.task_id,
        "role": "actor",
        "status": "SETTLED",
        "request_id": str(len(value.exposure_sequence) + 1),
        "payload_sha256": "a" * 64,
        "messages_sha256": messages_digest(messages),
    }
    value.confirm_actor_input(receipt)
    return messages, receipt


def revision(ref="source:3"):
    return {
        "handles": ["card:1"],
        "feedback_refs": [ref],
        "reason": "A counterexample narrows the condition",
        "proposal": {
            "expected_revisions": {"card:1": 1},
            "workspace_update": {
                "put_cards": [
                    {
                        "handle": "card:1",
                        "text": "NEW_RESTRICTED_ADVICE",
                        "source_refs": ["source:1", ref],
                    }
                ]
            },
        },
    }


def test_rejected_experience_has_no_actor_boilerplate_but_facts_and_source_access_survive():
    value, calls = session([adopt()])
    value.start(
        "task", "current request", task_facts=(("Required prior plan", "KEEP_REQUIRED_FACT"),)
    )
    messages, _ = confirm(value)
    content = messages[0]["content"]
    assert "KEEP_REQUIRED_FACT" in content
    assert "OLD_CONDITIONAL_ADVICE" not in content
    assert "card:1" not in content
    assert value.policies["revision_actor"].strip() not in content
    assert value.exposure_sequence[0]["versions"] == []
    assert "card:1" in value.read("experience:catalog")["text"]
    assert value.actor_read("card:1")["text"] == "OLD_CONDITIONAL_ADVICE"
    assert [call.role for call in calls] == ["adopt"]


def test_post_task_revision_does_not_receive_prior_result_and_survives_restore():
    value, calls = session(
        [adopt("card:1"), "success", json.dumps({"new_memory": "", "revision": revision()})],
        regime="R",
    )
    value.start("task", "current")
    confirm(value)
    assert value.observe("tool", "A real counterexample") == "source:3"
    value.seal_result("native-session.json", True)
    value.finish("actual visible work", commit=True)
    state = value.bank.utility_state
    assert state["tasks"]["task"]["exposures"][0]["versions"] == [
        {"memory_ref": "card:1", "revision": 1}
    ]
    assert state["versions"]["card:1@2"]["predecessor"] == "card:1@1"
    assert state["tasks"]["task"]["costs"]["settled_requests"] == 3
    extraction = json.loads(calls[-1].messages[-1]["content"])
    assert extraction["original_experience_sources"]["source:1"].startswith(
        "Original observed episode"
    )
    assert "native_result" not in extraction
    restored = ExperienceBank.restore(
        value.checkpoint(), scope=value.bank.scope, contract=value.bank.contract
    )
    tampered = value.checkpoint()
    tampered["cards"]["card:1"]["text"] = "changed without a new version"
    with pytest.raises(ValueError, match="VERSION_CONTENT_CHANGED"):
        ExperienceBank.restore(tampered, scope=value.bank.scope, contract=value.bank.contract)
    next_task, _ = session(
        [adopt("card:1"), "fail", '{"new_memory":""}'], regime="R", bank=restored
    )
    next_task.start("later", "later query")
    messages, _ = confirm(next_task)
    assert "NEW_RESTRICTED_ADVICE" in messages[0]["content"]
    view = next_task._utility().selection_view({"card:1": 2})
    assert not view["recent_related_sequences"][0]["contains_current_versions"]
    next_task.seal_result("later-native-session.json", False)
    next_task.finish("later observed work", commit=True)
    assert restored.utility_state["tasks"]["later"]["native_result"] is False
    assert restored.utility_state["tasks"]["task"]["exposures"][0]["versions"][0]["revision"] == 1
    with pytest.raises(ValueError, match="ALREADY_ACTIVE_OR_COMMITTED"):
        next_task.start("later", "repeat after recovery")


def test_hidden_feedback_is_not_filled_with_self_judgment_and_frozen_state_is_exact():
    value, _ = session([adopt("card:1"), "success", '{"new_memory":""}'], protocol="F")
    before = value.bank.checkpoint()
    value.start("task", "current")
    confirm(value)
    with pytest.raises(ValueError, match="NOT_ALLOWED"):
        value.seal_result("scored.json", True)
    value.seal_result("scored.json")
    value.finish("visible work", commit=False)
    assert value.bank.checkpoint() == before
    row = value.working.utility_state["tasks"]["task"]
    assert row["native_result"] is None
    assert row["signal"] == "visible_evidence_only"
    frozen_r, _ = session([adopt()], regime="R", protocol="F")
    frozen_r.start("frozen-r", "current")
    with pytest.raises(ValueError, match="NOT_ALLOWED"):
        frozen_r.seal_result("scored.json", False)


def test_old_page_and_new_body_in_same_actual_request_preserve_both_versions():
    update = revision()
    value, _ = session(
        [adopt("card:1"), json.dumps(update["proposal"]), "fail", '{"new_memory":""}']
    )
    value.start("task", "current")
    confirm(value)
    page = value.actor_read("card:1")
    history = [
        {"role": "user", "content": "Memory receipt: " + json.dumps(page, ensure_ascii=False)}
    ]
    confirm(value, history=history)
    ref = value.observe("tool", "The condition differs")
    value.request_revision(
        {"handles": ["card:1"], "feedback_refs": [ref], "reason": "Observed difference"}
    )
    confirm(value, history=history)
    assert value.exposure_sequence[-1]["versions"] == [
        {"memory_ref": "card:1", "revision": 1},
        {"memory_ref": "card:1", "revision": 2},
    ]
    value.seal_result("result.json")
    value.finish("visible work", commit=True)
    assert value.bank.utility_state["tasks"]["task"]["attribution"] == "ordered_sequence_only"


def test_assembly_or_unsettled_call_is_not_exposure_and_receipt_cannot_be_reused():
    value, _ = session([adopt("card:1")])
    value.start("task", "current")
    value.memory_context()
    assert value.exposure_sequence == []
    with pytest.raises(ValueError, match="RECEIPT"):
        value.confirm_actor_input()
    messages, receipt = confirm(value)
    with pytest.raises(ValueError, match="RECEIPT"):
        value.confirm_actor_input(receipt)
    value.prepare_actor_input(messages)
    with pytest.raises(ValueError, match="CONFIRMED_ACTOR"):
        value.confirm_actor_input({**receipt, "request_id": "pending", "status": "UNKNOWN"})
    assert len(value.exposure_sequence) == 1


def test_failed_extraction_retains_use_costs_and_completed_position():
    value, _ = session([adopt("card:1"), "fail", "invalid JSON"])
    value.start("task", "current")
    confirm(value)
    value.seal_result("result.json")
    result = value.finish("visible work", commit=True)
    assert result["status"] == "MAINTENANCE_FAILED"
    assert "task" in value.bank.completed_tasks
    assert value.bank.utility_state["tasks"]["task"]["costs"]["settled_requests"] == 3
    assert value.bank.cards["card:1"].revision == 1
