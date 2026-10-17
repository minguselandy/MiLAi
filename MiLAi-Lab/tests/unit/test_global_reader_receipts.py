"""Shared responses cost once per method; unknown usage never becomes free work."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from export_global_reader_responses import export_closed_cases
from milai_lab.harness.artifact_io import write_json
from review_global_reader_results import (
    collect,
    proof_delivery,
    standalone_reader_cost,
    usage_totals,
)
from run_musique_reader import reader_input


def test_shared_reader_positions_and_unknown_receipts_remain_separate():
    receipts = {
        "shared": {"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}},
        "unknown": {"usage": None},
    }
    results = [
        {"reader_call_key": "shared", "wall_seconds": 2.0},
        {"reader_call_key": "shared", "wall_seconds": 2.0},
        {"reader_call_key": "unknown", "wall_seconds": 3.0},
    ]
    actual = usage_totals(list(receipts.values()))
    standalone = standalone_reader_cost(results, receipts)
    assert actual["responses"] == standalone["unique_calls"] == 2
    assert standalone["positions"] == 3
    assert standalone["usage"]["known_total_tokens"] == 15
    assert standalone["usage"]["unknown_total_tokens_responses"] == 1
    assert standalone["gross_position_usage"]["known_total_tokens"] == 30
    assert standalone["first_call_wall_seconds"] == 5


def test_partial_usage_does_not_invent_generated_token_count():
    summary = usage_totals([{"usage": {"total_tokens": 20}}])
    assert summary["known_total_tokens"] == 20
    assert summary["unknown_completion_tokens_responses"] == 1
    assert "known_completion_tokens" not in summary
    embedding = usage_totals(
        [{"usage": {"prompt_tokens": 20, "total_tokens": 20}}], generated=False
    )
    assert embedding == {"responses": 1, "known_prompt_tokens": 20, "known_total_tokens": 20}


def test_proof_delivery_respects_alternatives_and_does_not_grade_ambiguous_pool():
    supported = {"disposition": "supported", "complete_proofs": [[1], [2, 3]]}
    assert proof_delivery(supported, {1}) is True
    assert proof_delivery(supported, {2}) is False
    assert proof_delivery(supported, {2, 3}) is True
    assert proof_delivery({"disposition": "masked", "complete_proofs": []}, {1}) is None
    assert (
        proof_delivery({"disposition": "pool_insufficient", "complete_proofs": []}, set()) is None
    )


@pytest.mark.local_artifacts
def test_closed_matrix_audit_keeps_shared_calls_source_review_and_unknown_cost(tmp_path):
    official = os.environ.get("MILAI_MUSIQUE_OFFICIAL")
    if not official:
        pytest.skip("requires downloaded official MuSiQue metrics")
    root = tmp_path / "run"
    root.mkdir()
    cases, labels, reviews = [], [], []
    for i, text in enumerate(("The color is blue.", "Only size is documented.")):
        case = {
            "case_id": str(i),
            "question": f"What is item{i}'s color?",
            "candidates": [{"id": "p0", "title": "item", "text": text}],
        }
        cases.append(case)
        labels.append(
            {
                "case_id": str(i),
                "family": str(i),
                "source_row": i,
                "candidate_source_indices": {"p0": 0},
                "source": {"answerable": i == 0, "answer": "blue", "answer_aliases": []},
            }
        )
        reviews.append(
            {
                "source_row": i,
                "disposition": "supported" if i == 0 else "pool_insufficient",
                "complete_proofs": [[0]] if i == 0 else [],
            }
        )
        messages, schema = reader_input(case, ["p0"])
        key = f"musique/shared/{i}/answer"
        answer = {
            "answer": "blue" if i == 0 else "",
            "answerable": i == 0,
            "support_ids": ["p0"] if i == 0 else [],
        }
        write_json(
            root / "reader/http" / key / "request.json",
            {"messages": messages, "response_format": schema},
        )
        write_json(
            root / "reader/http" / key / "response.json",
            {
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
                if i == 0
                else None,
            },
        )
        for arm in ("bm25_k4", "dense_k4", "full20", "model_k4"):
            write_json(
                root / "selections" / arm / str(i) / "k4.json",
                {"selected_ids": ["p0"], "decision_calls": 0, "stop_reason": "fixed_k"},
            )
            write_json(
                root / "reader/predictions" / arm / f"{i}.json",
                {"reader_call_key": key, "answer": answer, "failure": None, "wall_seconds": 2.0},
            )
    for name, rows in (("cases", cases), ("labels", labels)):
        (root / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    write_json(root / "reviews.json", {"cases": reviews})
    write_json(root / "retrieval.json", [])
    arms = {
        arm: {"selection_root": str(root / "selections" / arm), "policy": "k4"}
        for arm in ("bm25_k4", "dense_k4", "full20", "model_k4")
    }
    model = {"name": "model", "backend": "native", "selector_backend": "laya"}
    phases = [
        ("probe_root", "probe-", "reader_invariance_probe_v1"),
        ("selection_root", "select-", "bounded_reader_selection_laya"),
        ("fixed4_root", "fixed4-", "reader_ce_fixed4_extension_v1"),
    ]
    for field, stage, phase in phases:
        model[field] = str(root / field)
        cost = {"wall_seconds": 2.0, "cpu_seconds": 1.0, "runs": 1}
        write_json(root / field / "compute.json", cost)
        write_json(root / f"{stage}model-budget-before.json", {"compute": {}})
        write_json(root / f"{stage}model-budget-after.json", {"compute": {phase: cost}})
    write_json(
        root / "protocol.json",
        {
            "cases": str(root / "cases.jsonl"),
            "labels": str(root / "labels.jsonl"),
            "source_review": str(root / "reviews.json"),
            "common_retrieval_costs": str(root / "retrieval.json"),
            "official_scorer": official,
            "arms": arms,
            "models": [model],
        },
    )
    write_json(root / "reader/run.json", {"status": "COMPLETED"})
    write_json(root / "score/results.json", {"arms": {arm: {} for arm in arms}})
    empty = {"known_tokens": 0, "charged_tokens": 0, "unknown_usage": 0}
    start = {"generation_requests": 0, "generation": empty, "embedding": empty}
    end = {
        "generation_requests": 2,
        "generation": {"known_tokens": 15, "charged_tokens": 115, "unknown_usage": 1},
        "embedding": empty,
    }
    write_json(root / "reader/accounting-start.json", start)
    write_json(root / "reader/accounting-end.json", end)
    write_json(root / "selections/dense/accounting-start.json", start)
    write_json(root / "selections/dense/accounting-end.json", start)
    write_json(root / "selections/dense/compute.json", {"wall_seconds": 0.0})
    pending = root / "reader/predictions/model_k4/1.json"
    saved = pending.read_text()
    pending.unlink()
    stream = tmp_path / "stream"
    first = export_closed_cases(root, stream)
    assert first["completed_cases"] == 1
    initial_view = (stream / "00-0.txt").read_text()
    pending.write_text(saved)
    second = export_closed_cases(root, stream)
    assert second["completed_cases"] == 2
    assert (stream / "00-0.txt").read_text() == initial_view
    assert first["catalog"][0]["response_ids"] == second["catalog"][0]["response_ids"]
    report = collect(root, tmp_path / "review")
    assert report["unique_responses_for_review"] == 2
    assert report["method_positions"] == 8
    assert report["actual_reader_usage"]["unknown_total_tokens_responses"] == 1
    assert report["reader_ledger_audit"]["generation"]["charged_tokens"] == 115
    assert report["reader_ledger_audit"]["known_token_difference"] == 0
    assert report["reader_unknown_usage_difference"] == 0
    assert all(a["matches"] for a in report["local_ledger_audits"]["model"].values())
    assert (
        report["arms"]["model_k4"]["source_delivery"][0]["known_reviewed_proof_delivered"] is True
    )
    assert report["arms"]["model_k4"]["source_delivery"][0]["answer_semantics"].startswith(
        "PENDING"
    )
    views = "".join(p.read_text() for p in (tmp_path / "review/review-views").glob("*.txt"))
    assert all(arm not in views for arm in arms)
