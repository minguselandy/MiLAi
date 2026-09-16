from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "tools/run_product05_openworker_lme.py"
    spec = importlib.util.spec_from_file_location("product05_openworker_lme", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_literal_answer_match_accepts_only_the_whole_answer() -> None:
    module = _module()

    assert module._literal_answer_match("  Lavender   Gin Fizz ", "lavender gin fizz")
    assert not module._literal_answer_match(
        "The answer is $350,000; another record says $400,000.",
        "$400,000",
    )


def test_literal_answer_match_accepts_one_complete_reference_variant() -> None:
    module = _module()

    assert module._literal_answer_match("three weeks", ["3 weeks", "three weeks"])
    assert not module._literal_answer_match("about three weeks ago", ["3 weeks", "three weeks"])


def test_sampling_configuration_requires_fixed_answer_sampling(tmp_path: Path) -> None:
    module = _module()
    config = tmp_path / "opencode.json"
    config.write_text(
        json.dumps(
            {
                "agent": {"build": {"temperature": 0, "top_p": 1}},
                "provider": {
                    "openworker": {"models": {module.MODEL: {"temperature": True}}}
                },
            }
        ),
        encoding="utf-8",
    )

    assert module._sampling_configuration(config) == {"temperature": 0, "top_p": 1}

    config.write_text(
        json.dumps(
            {
                "agent": {"build": {"temperature": 0.55, "top_p": 1}},
                "provider": {
                    "openworker": {"models": {module.MODEL: {"temperature": True}}}
                },
            }
        ),
        encoding="utf-8",
    )
    try:
        module._sampling_configuration(config)
    except module.Product05RunError as exc:
        assert "temperature=0" in str(exc)
    else:
        raise AssertionError("non-deterministic answer sampling was accepted")


def test_retrieval_metrics_measure_required_session_coverage_after_selection() -> None:
    module = _module()
    record = {
        "question_id": "case-1",
        "haystack_session_ids": ["answer-a", "distractor", "answer-b"],
        "haystack_sessions": [
            [{"role": "user", "content": "answer A"}],
            [{"role": "user", "content": "distractor"}],
            [{"role": "user", "content": "answer B"}],
        ],
        "answer_session_ids": ["answer-a", "answer-b"],
    }
    instances = module.source_session_instance_keys(record["haystack_session_ids"])
    receipts = [
        {
            "evidence_id": f"evidence-{index}",
            "source_ref": (
                f"lme://{module._sha256_text('case-1')[:12]}/"
                f"{module._sha256_text(instance)[:20]}/turn/0"
            ),
        }
        for index, instance in enumerate(instances)
    ]
    labels = {
        "negative_without_answer_turn": False,
        "selections": [
            {
                "source_session_id": "answer-a",
                "session_ordinal": 0,
                "turn_ordinal": 0,
                "speaker": "user",
                "source_text_sha256": module._sha256_text("answer A"),
            },
            {
                "source_session_id": "answer-b",
                "session_ordinal": 2,
                "turn_ordinal": 0,
                "speaker": "user",
                "source_text_sha256": module._sha256_text("answer B"),
            },
        ],
    }

    partial = module._retrieval_metrics(record, receipts, ["evidence-0"], labels)
    complete = module._retrieval_metrics(
        record, receipts, ["evidence-0", "evidence-2"], labels
    )

    assert partial == {
        "gold_session_count": 2,
        "reader_visible_gold_session_count": 1,
        "any_gold_session_recall": True,
        "reader_visible_answer_session_coverage": 0.5,
        "required_evidence_group_count": 2,
        "reader_visible_evidence_group_count": 1,
        "all_required_evidence_group_recall": False,
        "reader_visible_evidence_group_coverage": 0.5,
    }
    assert complete["all_required_evidence_group_recall"] is True
    assert complete["reader_visible_evidence_group_coverage"] == 1.0


def test_retrieval_metrics_do_not_confuse_session_recall_with_answer_turn() -> None:
    module = _module()
    record = {
        "question_id": "case-1",
        "haystack_session_ids": ["answer-a"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "answer-bearing turn"},
                {"role": "assistant", "content": "response"},
                {"role": "user", "content": "neighbor"},
            ]
        ],
        "answer_session_ids": ["answer-a"],
    }
    instance = module.source_session_instance_keys(record["haystack_session_ids"])[0]
    prefix = (
        f"lme://{module._sha256_text('case-1')[:12]}/"
        f"{module._sha256_text(instance)[:20]}/turn/"
    )
    receipts = [{"evidence_id": "neighbor", "source_ref": prefix + "2"}]
    labels = {
        "negative_without_answer_turn": False,
        "selections": [
            {
                "source_session_id": "answer-a",
                "session_ordinal": 0,
                "turn_ordinal": 0,
                "speaker": "user",
                "source_text_sha256": module._sha256_text("answer-bearing turn"),
            }
        ],
    }

    metrics = module._retrieval_metrics(record, receipts, ["neighbor"], labels)

    assert metrics["any_gold_session_recall"] is True
    assert metrics["reader_visible_answer_session_coverage"] == 1.0
    assert metrics["all_required_evidence_group_recall"] is False
    assert metrics["reader_visible_evidence_group_coverage"] == 0.0


def test_numeric_reference_parses_scalar_strings_but_not_phone_numbers() -> None:
    module = _module()

    assert module._numeric_reference("$3,750").value == 3750
    assert module._numeric_reference("856").value == 856
    assert module._numeric_reference("3 weeks ago").unit == "week"
    assert module._numeric_reference("30 minutes").value == 30
    assert module._numeric_reference("+49 (0) 62 32 / 14 23 - 0") is None


def test_numeric_match_rejects_missing_total_and_obsolete_currency_value() -> None:
    module = _module()
    total = module._numeric_reference("$3,750")
    pages = module._numeric_reference("856")
    current = module._numeric_reference("$400,000")
    assert total is not None and pages is not None and current is not None

    assert not module._numeric_answer_match(
        "Raised $1,000, $2,000, and $250. Total: $3,250.", total
    )
    assert module._numeric_answer_match(
        "Raised $1,000, $2,000, $500, and $250. Total: $3,750.", total
    )
    assert not module._numeric_answer_match(
        "January had 341 pages and March had 440 pages.", pages
    )
    assert not module._numeric_answer_match(
        "You were pre-approved for $350,000. Note: a later record says $400,000.",
        current,
    )
    assert module._numeric_answer_match(
        "You were pre-approved for $400,000; the obsolete value was $350,000.",
        current,
    )


def test_abstention_match_accepts_explicit_insufficiency_not_bare_guess() -> None:
    module = _module()

    assert module._abstention_answer_match(
        "The memory says I have worked for 9 years, but it does not contain "
        "the Google start date, so I cannot determine the requested interval."
    )
    assert module._abstention_answer_match(
        "The governed memory does not contain any information about a hamster."
    )
    assert module._abstention_answer_match(
        "The provided memory does not contain any records of baking egg tarts."
    )
    assert not module._abstention_answer_match("You worked for 9 years.")
