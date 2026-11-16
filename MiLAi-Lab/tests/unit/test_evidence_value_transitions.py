"""Observed complements, equivalent ranges and disputed training labels."""

import json
from pathlib import Path

import pytest


@pytest.fixture
def prepared_outcomes(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    from prepare_evidence_value_transitions import prepare

    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    pool = []
    for source in ("a", "b", "a", "noise"):
        spans = [{"source_ref": source, "source_revision": 1, "start": 0, "end": 10}]
        pool.append(
            {
                "kind": "original_source",
                "index_text": "Actual candidate " + source,
                "source_ranges": spans,
                "context_source_ranges": spans,
            }
        )
    source, execution = tmp_path / "source", tmp_path / "execution"
    write(source / "native/longmemeval/q/answer/retrieval.json", {"materials": pool})
    write(execution / "protocol.json", {"question_id": "q", "source_run": str(source)})
    specifications = [
        ("empty", [], False),
        ("a", [0], False),
        ("b", [1], False),
        ("both", [0, 1], True),
        ("alias", [2, 1], True),
        ("noise", [0, 1, 3], True),
    ]
    outcomes, reviews = [], {}
    for name, indices, correct in specifications:
        intervals = [[pool[i]["source_ranges"][0]["source_ref"], 1, 0, 10] for i in indices]
        outcomes.append(
            {
                "condition": name,
                "indices": indices,
                "expand_context": indices,
                "source_intervals": intervals,
                "correct": correct,
            }
        )
        reviews[name] = {"correct": correct, "note": "REVIEW_ONLY"}
        payload = {
            "question": "Combine the two observations",
            "date": "2030-01-01",
            "memories": [{"label": f"e{i}", "content": "Saved body"} for i in indices],
        }
        write(
            execution / f"http/longmemeval/q:{name}/answer/request.json",
            {
                "messages": [
                    {"role": "system", "content": "Read"},
                    {"role": "user", "content": json.dumps(payload)},
                ],
                "prompt_tokens": 100 + 10 * len(indices),
            },
        )
    write(execution / "results.json", {"status": "COMPLETED", "results": outcomes})
    reviews["noise"]["correct"] = False
    return prepare, execution, reviews


def test_complement_return_is_separate_from_immediate_gain(prepared_outcomes):
    prepare, execution, reviews = prepared_outcomes
    data = prepare(execution, reviews)
    edges = {(e["before_condition"], e["after_condition"]): e for e in data["transitions"]}
    assert edges["empty", "a"]["observed_gain"] == 0
    assert edges["empty", "a"]["observed_two_open_return_gain"] == 1
    assert edges["a", "both"]["observed_gain"] == 1
    assert edges["empty", "both"]["opens"] == 2
    assert edges["both", "noise"]["observed_gain"] is None
    assert edges["both", "noise"]["observed_two_open_return_gain"] is None
    assert ("both", "alias") not in edges
    assert data["equivalent_evidence"] == [
        {"conditions": ["both", "alias"], "observed_return_disagreement": False}
    ]
    for row in [*data["states"], *data["transitions"]]:
        inputs = json.dumps(row["model_input"])
        assert "REVIEW_ONLY" not in inputs and "correct" not in inputs
        assert "observed_gain" not in inputs


def test_equivalent_evidence_disagreement_is_not_resolved_by_picking_a_response(prepared_outcomes):
    prepare, execution, reviews = prepared_outcomes
    path = execution / "results.json"
    results = json.loads(path.read_text())
    next(r for r in results["results"] if r["condition"] == "alias")["correct"] = False
    path.write_text(json.dumps(results))
    reviews["alias"]["correct"] = False
    data = prepare(execution, reviews)
    assert data["equivalent_evidence"][0]["observed_return_disagreement"]
    states = {s["condition"]: s for s in data["states"]}
    assert states["both"]["official_correct"] is True
    assert states["alias"]["official_correct"] is False
    assert states["both"]["observed_return"] is None
    assert states["alias"]["observed_return"] is None


def test_contiguous_slices_are_equivalent_but_source_revisions_are_distinct(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "tools"))
    from prepare_evidence_value_transitions import contains, coverage

    sliced = coverage([("source", 1, 0, 3), ("source", 1, 3, 10)])
    assert sliced == coverage([("source", 1, 0, 10)])
    assert not contains(sliced, coverage([("source", 2, 0, 10)]))
    assert not contains(sliced, coverage([("other", 1, 0, 10)]))
