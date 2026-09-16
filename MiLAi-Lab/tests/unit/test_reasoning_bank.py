from pathlib import Path

import pytest

from milai_lab.methods.reasoning_bank import (
    BankConfig,
    ExperienceBank,
    ReasoningBankSession,
    parse_memory_items,
)

POLICY_ROOT = Path(__file__).resolve().parents[2] / "configs/policies/reasoning_bank"


def item(title="Check the observed result"):
    return (
        f"# Memory Item 1\n## Title {title}\n"
        "## Description Check the actual tool response.\n"
        "## Content Compare the result to the requested constraint before proceeding."
    )


def test_complete_lowercase_markdown_headings_preserve_original_text():
    text = item().replace("## Title", "## title").replace("## Description", "## description")
    assert parse_memory_items(text) == [text.split("\n", 1)[1]]


def fixture_session(responses, bank=None):
    config = BankConfig(embedding_dimension=2)
    policies = {path.stem: path.read_text() for path in POLICY_ROOT.glob("*.txt")}
    scope = {
        "experiment": "fixture",
        "method": "RB",
        "model": "controlled_fixture",
        "protocol": "O",
        "split": "DEV",
        "stream": "1",
    }
    if bank is None:
        bank = ExperienceBank(scope, ReasoningBankSession.contract(config, policies))
    pending = iter(responses)
    calls, encoded = [], []

    def generate(call):
        calls.append(call)
        return next(pending)

    def embed(texts):
        encoded.append(texts)
        return [[0.0, 1.0] if "blue" in text else [1.0, 0.0] for text in texts]

    session = ReasoningBankSession(
        bank=bank, config=config, policies=policies, generate=generate, embed=embed
    )
    return session, calls, encoded


def test_success_and_failure_are_both_extracted_and_indexed_by_original_query():
    session, calls, encoded = fixture_session(
        ["success", item("Red lesson"), "fail", item("Blue lesson")]
    )
    session.start("red-task", "red request")
    assert session.memory_context() == ""
    session.observe("tool", "The requested write completed")
    session.finish("Real red tool trajectory", commit=True)
    session.start("blue-task", "blue request")
    assert "Red lesson" in session.memory_context()
    session.finish("Real blue failed trajectory", commit=True)
    assert [call.role for call in calls] == ["self_judge", "extract", "self_judge", "extract"]
    assert "failed" in calls[-1].messages[0]["content"]
    assert [record["self_judgment"] for record in session.bank.records] == ["success", "fail"]
    assert [batch[0] for batch in encoded] == ["red request", "blue request"]
    assert all("trajectory" not in text for batch in encoded for text in batch)
    session.start("new-blue-task", "blue followup")
    assert "Blue lesson" in session.memory_context()
    assert "Red lesson" not in session.memory_context()


def test_frozen_task_overlay_cannot_update_the_next_test_or_its_support_bank():
    support, _, _ = fixture_session(["success", item("Support lesson")])
    support.start("support-task", "red support")
    support.finish("visible support work", commit=True)
    original = support.checkpoint()
    scope = {**support.bank.scope, "protocol": "F", "split": "TEST", "stream": "task-1"}
    bank = support.bank.fork(scope)
    test, _, _ = fixture_session(["success", item("Test-only lesson")], bank)
    test.start("test-task", "red test")
    test.finish("visible test work", commit=False)
    assert support.checkpoint() == original
    assert len(test.working.records) == 2
    assert len(test.bank.records) == 1
    next_bank = support.bank.fork({**scope, "stream": "task-2"})
    next_test, _, _ = fixture_session([], next_bank)
    next_test.start("another-test", "red other")
    assert "Test-only lesson" not in next_test.memory_context()
    with pytest.raises(ValueError, match="CROSS_EXPERIMENT_OR_METHOD"):
        support.bank.fork({**scope, "method": "another-method"})


def test_completed_bank_restore_preserves_retrieval_without_reextracting():
    session, _, _ = fixture_session(["success", item()])
    session.start("task-1", "red first")
    with pytest.raises(ValueError, match="COMPLETED_TASK_BOUNDARY"):
        session.checkpoint()
    session.finish("the visible action and result", commit=True)
    checkpoint = session.checkpoint()
    restored = ExperienceBank.restore(
        checkpoint, scope=session.bank.scope, contract=session.bank.contract
    )
    fresh, calls, _ = fixture_session([], restored)
    fresh.start("task-2", "red second")
    assert session.bank.select([1.0, 0.0], session.config) == fresh.selected
    assert not calls
    assert fresh.read("card:1")["text"] == session.bank.cards["card:1"].text
    assert (
        fresh.read(session.bank.records[0]["trace_ref"], start=7, length=9)["text"]
        == (session.bank.sources[session.bank.records[0]["trace_ref"]][7:16])
    )
    duplicate, _, _ = fixture_session([], restored)
    with pytest.raises(ValueError, match="ALREADY_ACTIVE_OR_COMMITTED"):
        duplicate.start("task-1", "red first")
    with pytest.raises(ValueError, match="BINDING_MISMATCH"):
        ExperienceBank.restore(
            checkpoint, scope={**restored.scope, "stream": "other"}, contract=restored.contract
        )


def test_invalid_extraction_keeps_the_preceding_bank_and_records_local_failure():
    session, calls, _ = fixture_session(["success", "I did not provide memory items."])
    original = session.bank.checkpoint()
    session.start("task-1", "red request")
    result = session.finish("The task was already delivered", commit=True)
    assert result["status"] == "MAINTENANCE_FAILED"
    assert session.bank.checkpoint() == original
    assert len(calls) == 2
    assert not session.active


def test_reference_top_one_trajectory_preserves_all_its_memory_items():
    output = (
        item("First lesson")
        + "\n\n"
        + item("Second lesson").replace("Memory Item 1", "Memory Item 2")
    )
    session, _, _ = fixture_session(["success", output])
    session.start("task-1", "red request")
    session.finish("real trajectory", commit=True)
    session.start("task-2", "red next")
    assert session.selected == ["card:1", "card:2"]
    assert (
        "First lesson" in session.memory_context() and "Second lesson" in session.memory_context()
    )
    assert len(parse_memory_items(output)) == 2
