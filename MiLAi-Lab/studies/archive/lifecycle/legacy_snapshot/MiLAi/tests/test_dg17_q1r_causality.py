from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.dg14.provider import DG14ProviderError, full_provider_contract_sha256
from evals.dg17.q1r_causality import (
    CONTEXT_ARCHIVE_SCHEMA,
    POLICIES,
    Q1RCausalityError,
    audit_generation_pairs,
    build_generation_schedule,
    canonical_sha256,
    planned_stability_diagnostics,
    validate_context_archive,
)
from evals.paper.provider import prompt_contract_sha256, serialized_prompt
from scripts import run_dg17_q1r_matched as q1r_runner
from scripts.run_dg17_q1r_matched import Q1RRunError, run

CASE_ID = "case-one"
QUESTION = "What did I choose?"
QUESTION_AS_OF = "2026-08-27T00:00:00+00:00"


def _context_record(policy: str, *, content: str = "[E1] user: tea") -> dict[str, object]:
    digest = hashlib.sha256(content.encode()).hexdigest()
    mediators = {
        "memory_status": "HIT",
        "selected_source_refs": ["case-one:s0:t0"],
        "selected_order": ["E1"],
        "evidence_prose": ["user: tea"],
        "speaker_time": [{"speaker": "user", "observed_at": "2026-08-26"}],
        "scope_authority": {"authority": "INFORMATIONAL"},
        "binding_annotations": [],
        "sufficiency": {"status": "COMPLETE"},
        "derived_result": None,
        "truncation": False,
    }
    return {
        "case_id": CASE_ID,
        "token_budget": 512,
        "policy": policy,
        "context": content,
        "context_sha256": digest,
        "evidence_snapshot_digest": "",
        "context_identity": {
            "semantic_context_digest": canonical_sha256(mediators),
            "reader_context_digest": digest,
            "receipt_mapping": [
                {
                    "alias": "E1",
                    "evidence_ids": ["b3b2cdd4-c58d-4b42-af42-2430dbf8574f"],
                    "source_turn_refs": ["case-one:s0:t0"],
                    "claim_versions": [],
                    "issue_revisions": [],
                }
            ],
        },
        "semantic_mediators": mediators,
        "semantic_mediator_digest": canonical_sha256(mediators),
    }


def _archive() -> dict[str, object]:
    snapshot = {
        "case_id": CASE_ID,
        "canonical_position": 7,
        "evidence": [{"source_ref": "case-one:s0:t0", "content": "user: tea"}],
    }
    snapshot_digest = canonical_sha256(snapshot)
    records = [_context_record(policy) for policy in POLICIES]
    for record in records:
        record["evidence_snapshot_digest"] = snapshot_digest
    return {
        "schema": CONTEXT_ARCHIVE_SCHEMA,
        "status": "SUCCEEDED",
        "label_fields_available": False,
        "historical_answer_reuse": False,
        "record_count": 2,
        "snapshots": [
            {
                "case_id": CASE_ID,
                "evidence_snapshot_digest": snapshot_digest,
                "evidence_snapshot": snapshot,
            }
        ],
        "records": records,
    }


def _generation(
    context: dict[str, object],
    *,
    ordinal: int,
    answer: str = "tea",
) -> dict[str, object]:
    policy = str(context["policy"])
    prompt_digest = hashlib.sha256(
        serialized_prompt(
            question=QUESTION,
            question_as_of=QUESTION_AS_OF,
            memory_context=str(context["context"]),
        ).encode()
    ).hexdigest()
    return {
        **deepcopy(context),
        "answer": answer,
        "generation_source": "FRESH_PROVIDER_CALL",
        "automatic_retries": 0,
        "planned_window_id": "window-one",
        "call_ordinal": ordinal,
        "provider": {
            "provider_calls": 1,
            "context_truncated": False,
            "context_sha256": context["context_sha256"],
            "prompt_sha256": prompt_digest,
            "prompt_contract_sha256": prompt_contract_sha256(),
            "generation_contract_sha256": full_provider_contract_sha256(),
            "native_request_id": f"request-{policy}-{ordinal}",
            "seed": 73,
        },
    }


def test_q1r_accepts_same_snapshot_and_builds_adjacent_balanced_schedule() -> None:
    records = validate_context_archive(
        _archive(), case_ids=[CASE_ID], budgets=[512]
    )

    schedule = build_generation_schedule(
        records,
        case_ids=[CASE_ID],
        budgets=[512],
        planned_window_id="window-one",
    )

    assert len(records) == 2
    assert [row["ordinal"] for row in schedule] == [0, 1]
    assert {row["policy"] for row in schedule} == set(POLICIES)


@pytest.mark.parametrize(
    "opaque_value",
    (
        "b3b2cdd4-c58d-4b42-af42-2430dbf8574f",
        "span:72b7beb9306ec552d63c257e710599772ae8df81c3f234278b3f0889539b9122",
        "case-one:s0:t0",
    ),
)
def test_q1r_rejects_opaque_reader_identity_before_provider(
    opaque_value: str,
) -> None:
    archive = _archive()
    raw_records = archive["records"]
    assert isinstance(raw_records, list)
    for raw in raw_records:
        assert isinstance(raw, dict)
        raw["context"] = f"[E1] user: tea {opaque_value}"
        digest = hashlib.sha256(str(raw["context"]).encode()).hexdigest()
        raw["context_sha256"] = digest
        identity = raw["context_identity"]
        assert isinstance(identity, dict)
        identity["reader_context_digest"] = digest

    with pytest.raises(Q1RCausalityError, match="opaque|provenance"):
        validate_context_archive(archive, case_ids=[CASE_ID], budgets=[512])


def test_q1r_same_semantics_requires_identical_reader_and_prompt_bytes() -> None:
    archive = _archive()
    records = validate_context_archive(
        archive, case_ids=[CASE_ID], budgets=[512]
    )
    generations = [
        _generation(records[0], ordinal=0),
        _generation(records[1], ordinal=1),
    ]

    audits = audit_generation_pairs(
        generations,
        questions={CASE_ID: (QUESTION, QUESTION_AS_OF)},
        budgets=[512],
    )

    assert audits == [
        {
            "case_id": CASE_ID,
            "token_budget": 512,
            "evidence_snapshot_digest": records[0]["evidence_snapshot_digest"],
            "semantic_context_equal": True,
            "reader_context_equal": True,
            "exact_prompt_equal": True,
            "answer_equal": True,
            "mediator_diff_paths": [],
            "unexplained_mediator_diff_paths": [],
            "invariant_failures": [],
            "quality_attribution": "CAUSALLY_VALID",
        }
    ]


def test_q1r_excludes_unexplained_reader_byte_drift_from_causal_claim() -> None:
    archive = _archive()
    raw_records = archive["records"]
    assert isinstance(raw_records, list)
    right = raw_records[1]
    assert isinstance(right, dict)
    right["context"] = "[E1] user: tea "
    digest = hashlib.sha256(str(right["context"]).encode()).hexdigest()
    right["context_sha256"] = digest
    identity = right["context_identity"]
    assert isinstance(identity, dict)
    identity["reader_context_digest"] = digest
    records = validate_context_archive(
        archive, case_ids=[CASE_ID], budgets=[512]
    )
    generations = [
        _generation(records[0], ordinal=0),
        _generation(records[1], ordinal=1),
    ]

    audit = audit_generation_pairs(
        generations,
        questions={CASE_ID: (QUESTION, QUESTION_AS_OF)},
        budgets=[512],
    )[0]

    assert "UNEXPLAINED_READER_CONTEXT_DIFF" in audit["invariant_failures"]
    assert audit["quality_attribution"] == (
        "CONFOUNDED / EXCLUDED FROM CAUSAL CLAIM"
    )


def test_q1r_accepts_allowlisted_policy_mediator_change() -> None:
    archive = _archive()
    raw_records = archive["records"]
    assert isinstance(raw_records, list)
    right = raw_records[1]
    assert isinstance(right, dict)
    mediators = right["semantic_mediators"]
    assert isinstance(mediators, dict)
    mediators["selected_source_refs"] = ["case-one:s0:t0", "case-one:s1:t0"]
    right["semantic_mediator_digest"] = canonical_sha256(mediators)
    identity = right["context_identity"]
    assert isinstance(identity, dict)
    identity["semantic_context_digest"] = canonical_sha256(mediators)
    right["context"] = "[E1] user: tea\n[E2] user: coffee"
    digest = hashlib.sha256(str(right["context"]).encode()).hexdigest()
    right["context_sha256"] = digest
    identity["reader_context_digest"] = digest
    records = validate_context_archive(
        archive, case_ids=[CASE_ID], budgets=[512]
    )

    audit = audit_generation_pairs(
        [
            _generation(records[0], ordinal=0),
            _generation(records[1], ordinal=1),
        ],
        questions={CASE_ID: (QUESTION, QUESTION_AS_OF)},
        budgets=[512],
    )[0]

    assert audit["mediator_diff_paths"] == ["selected_source_refs[1]"]
    assert audit["quality_attribution"] == "CAUSALLY_VALID"


def test_q1r_rejects_historical_answer_reuse_before_pair_audit() -> None:
    records = validate_context_archive(
        _archive(), case_ids=[CASE_ID], budgets=[512]
    )
    generations = [
        _generation(records[0], ordinal=0),
        _generation(records[1], ordinal=1),
    ]
    generations[0]["generation_source"] = "HISTORICAL_RECEIPT"

    with pytest.raises(Q1RCausalityError, match="historical answer reuse"):
        audit_generation_pairs(
            generations,
            questions={CASE_ID: (QUESTION, QUESTION_AS_OF)},
            budgets=[512],
        )


def test_q1r_predeclares_three_repeats_without_replacing_primary_result() -> None:
    records = validate_context_archive(
        _archive(), case_ids=[CASE_ID], budgets=[512]
    )
    generations = [
        _generation(records[0], ordinal=0, answer="tea"),
        _generation(records[1], ordinal=1, answer="coffee"),
    ]
    for row in generations:
        row["answer_score"] = {"exact_match": 0}
    audits = audit_generation_pairs(
        generations,
        questions={CASE_ID: (QUESTION, QUESTION_AS_OF)},
        budgets=[512],
    )

    diagnostics = planned_stability_diagnostics(
        generations,
        audits,
        previously_correct_2048=frozenset(),
    )

    assert len(diagnostics) == 1
    assert diagnostics[0]["policies"] == sorted(POLICIES)
    assert all(row["independent_repeats_planned"] == 3 for row in diagnostics)
    assert all(row["automatic_retry"] is False for row in diagnostics)
    assert all(row["primary_result_replacement_allowed"] is False for row in diagnostics)


def test_q1r_rejects_snapshot_digest_not_bound_to_snapshot_content() -> None:
    archive = _archive()
    snapshots = archive["snapshots"]
    assert isinstance(snapshots, list)
    snapshot = snapshots[0]
    assert isinstance(snapshot, dict)
    snapshot["evidence_snapshot_digest"] = "0" * 64

    with pytest.raises(Q1RCausalityError, match="snapshot digest"):
        validate_context_archive(archive, case_ids=[CASE_ID], budgets=[512])


def test_q1r_runner_rejects_unsealed_archive_before_output_or_provider(
    tmp_path: Path,
) -> None:
    context_archive = tmp_path / "contexts.json"
    payload = json.dumps(
        {
            "schema": CONTEXT_ARCHIVE_SCHEMA,
            "status": "SUCCEEDED",
            "label_fields_available": False,
            "historical_answer_reuse": True,
        },
        sort_keys=True,
    ).encode()
    context_archive.write_bytes(payload)
    output = tmp_path / "must-not-exist"

    with pytest.raises(Q1RRunError, match="failed preflight"):
        run(
            run_id="must-not-run",
            output_root=output,
            context_archive=context_archive,
            context_archive_sha256=hashlib.sha256(payload).hexdigest(),
            reader_url="http://127.0.0.1:1",
        )

    assert not output.exists()


def test_q1r_runner_seals_progress_and_failure_before_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context_archive = tmp_path / "contexts.json"
    payload = json.dumps(_archive(), sort_keys=True).encode()
    context_archive.write_bytes(payload)
    output = tmp_path / "failed-run"
    context = _context_record(POLICIES[0])
    scheduled = {
        "ordinal": 0,
        "planned_window_id": "failed-run",
        "case_id": CASE_ID,
        "token_budget": 512,
        "policy": POLICIES[0],
    }

    class FailingProvider:
        def __init__(self, _reader_url: str) -> None:
            pass

        def answer(self, **_kwargs: object) -> None:
            raise DG14ProviderError("strict answer content is not JSON")

    monkeypatch.setattr(
        q1r_runner,
        "load_public_dev_cases",
        lambda: (
            [
                SimpleNamespace(
                    case_id=CASE_ID,
                    question=QUESTION,
                    question_at=QUESTION_AS_OF,
                )
            ],
            {"classification": "TEST"},
        ),
    )
    monkeypatch.setattr(
        q1r_runner,
        "validate_context_archive",
        lambda *_args, **_kwargs: [context],
    )
    monkeypatch.setattr(
        q1r_runner,
        "build_generation_schedule",
        lambda *_args, **_kwargs: [scheduled],
    )
    monkeypatch.setattr(q1r_runner, "MatchedVllmProvider", FailingProvider)

    with pytest.raises(Q1RRunError, match="sealed failure receipt"):
        run(
            run_id="failed-run",
            output_root=output,
            context_archive=context_archive,
            context_archive_sha256=hashlib.sha256(payload).hexdigest(),
            reader_url="http://127.0.0.1:7860",
        )

    failure = json.loads((output / "failure-receipt.json").read_text())
    progress = json.loads((output / "progress.json").read_text())
    assert failure["status"] == "FAILED_NOT_SCOREABLE"
    assert failure["labels_loaded"] is False
    assert failure["completed_call_count"] == 0
    assert failure["failed_call"] == scheduled
    assert progress["status"] == "FAILED_NOT_SCOREABLE"
    assert progress["records"] == []
    assert not (output / "generations.json").exists()
