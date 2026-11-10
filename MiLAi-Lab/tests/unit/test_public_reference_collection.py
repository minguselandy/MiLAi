"""A family bank must not expose another native variant or invent known evidence."""

import json
from types import SimpleNamespace

from collect_public_reference_states import collect_history
from prepare_musique_operation_sources import export_family


def test_native_context_isolation_and_actual_prior_receipt(tmp_path):
    a = {
        "idx": 0,
        "title": "Alpha",
        "paragraph_text": "Alpha is connected to Beta.",
        "is_supporting": True,
    }
    b = {
        "idx": 1,
        "title": "Beta",
        "paragraph_text": "Hidden beta premise identifies Gamma.",
        "is_supporting": True,
    }
    records = [
        {
            "metadata": {"row": i},
            "source": {
                "id": "2hop-toy",
                "question": "Which Gamma follows Alpha?",
                "paragraphs": paragraphs,
                "answerable": answerable,
                "answer": "Gamma",
                "answer_aliases": [],
            },
        }
        for i, (paragraphs, answerable) in enumerate((([a, b], True), ([a], False)))
    ]
    history, controls = export_family("train-family", records)
    assert len(history["sources"]) == 2
    assert controls[1]["reference_proofs"] == []
    capacity = SimpleNamespace(
        text_tokens=len,
        tokenizer=lambda text, **_: {"offset_mapping": [(i, i + 1) for i in range(len(text))]},
    )
    rows = []
    root = tmp_path / "collection"
    report = collect_history(
        history,
        {c["request_id"]: c for c in controls},
        root,
        capacity,
        max_steps=8,
        material_tokens=8192,
        known_condition=True,
        append=rows.append,
    )
    assert len(report["requests"]) == 4
    assert all(
        r["known_reference_reads"] == (1 if r["condition"] == "known-first" else 0)
        for r in report["requests"]
    )
    missing = [r for r in rows if r["metadata"]["training_event"] == "native-row-1"]
    assert missing and all(not r["gold"] for r in missing)
    assert all("Hidden beta premise" not in json.dumps(r["state"]) for r in missing)
    assert all("is_supporting" not in json.dumps(r["state"]) for r in rows)
    for native_row in (0, 1):
        cold = json.loads((root / f"native-row-{native_row}-cold-receipt.json").read_text())
        known = json.loads((root / f"native-row-{native_row}-known-first-receipt.json").read_text())
        assert known["request"]["task_context"]["known_evidence_refs"] == [
            cold["packet"]["evidence"][0]["ref"]
        ]
    initial_known = [
        r
        for r in rows
        if r["metadata"]["condition"] == "known-first" and r["metadata"]["stage"] == "initial"
    ]
    assert all(r["state"]["task"]["known_evidence"] for r in initial_known)
    search_labels = [
        r["metadata"]["action_parameters"][key]
        for r in rows
        for key in r["gold"].get("next", {}).get("probabilities", {})
        if r["metadata"]["action_kinds"][key] == "SEARCH"
    ]
    assert search_labels and all(p["limit"] == 16 for p in search_labels)
