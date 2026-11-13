import pytest

from summarize_fixed_source_repeats import summarize_pairs


def pair(method, family, first, second, failed=False):
    return {"method": method, "family": family, "first_native_F1": first,
        "second_native_F1": second, "first_status": "FAILED" if failed else "COMPLETED",
        "second_status": "COMPLETED", "exact_answer_field": False,
        "exact_full_response": False,
        "first_source_status": "execution_failed" if failed else "unknown",
        "second_source_status": "unknown"}


def test_second_success_does_not_replace_failed_first_or_double_sources():
    rows = [pair("a", "f1", 0, 1, True), pair("a", "f2", 1, 0),
            pair("b", "f1", 1, 0), pair("b", "f2", 1, 1)]
    result = summarize_pairs(rows, ("a", "b"), 0)
    assert result["methods"]["a"]["sources"] == 2
    assert result["methods"]["a"]["first_native_F1"] == .5
    assert result["methods"]["a"]["second_native_F1"] == .5
    assert result["methods"]["a"]["both_completed"] == 1
    assert result["primary_same_subset"]["first_difference"]["source_mean"] == -.5
    assert result["primary_same_subset"]["second_difference"]["source_mean"] == 0
    assert result["primary_same_subset"]["second_minus_first_contrast"]["source_mean"] == .5


def test_missing_or_duplicate_method_source_cannot_change_the_paired_sample():
    a, b = pair("a", "f1", 0, 1), pair("b", "f2", 1, 0)
    with pytest.raises(ValueError, match="same preselected"):
        summarize_pairs([a, b], ("a", "b"), 0)
    with pytest.raises(ValueError, match="Repeated"):
        summarize_pairs([a, a, b], ("a", "b"), 0)


def test_closed_artifacts_keep_exact_wire_and_do_not_salvage_failed_first(tmp_path, monkeypatch):
    import json

    from summarize_fixed_source_repeats import main

    def save(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return str(path)

    sampling = tmp_path / "sampling.json"
    save(sampling, {"source_order": ["f1", "f2"],
                    "second_Host_readout": {"source_groups": ["f1"]}})
    protocol = tmp_path / "protocol.json"
    save(protocol, {"sampling_freeze": str(sampling), "methods": {"a": {}, "b": {}},
                    "primary": ["a", "b"]})
    owner = {"status": "COMPLETED_CONFIRMATION_FIRSTS_AND_SECOND_READOUTS_AUTHOR_COST_PENDING",
             "first_bound": {}, "repeat_bound": {}, "first_native": {}, "repeat_native": {}}
    for stage in ["first", "repeat"]:
        reviewed = tmp_path / (stage + "-reviewed")
        save(reviewed / "reviews.json", {"records": []})
        owner[stage + "_reviewed"] = str(reviewed)
    for method in ["a", "b"]:
        first_readouts = tmp_path / method / "first-readouts"
        for stage in ["first", "repeat"]:
            root = tmp_path / method / stage
            prepared = root / "prepared"
            save(prepared / "run.json", {"repeat_preparation": stage == "repeat",
                 "original_firsts": str(first_readouts), "sampling": str(sampling)})
            save(root / "manifest.json", {"source_split": "test", "prepared": str(prepared),
                                          "readouts": str(first_readouts)})
            cases, scores = [], {}
            for family in (["f1", "f2"] if stage == "first" else ["f1"]):
                action = {"id": "handoff", "kind": "HANDOFF", "parameters": {}}
                wire = {"model": "same-model", "messages": [{"role": "user", "content": family}]}
                request = save(root / (family + "-request.json"), wire)
                failed = method == "a" and stage == "first" and family == "f1"
                record = {"request": request, "answer": None if failed else "Answer"}
                readout = save(root / (family + "-readout.json"), record)
                cases.append({"family": family, "event_id": family + "/q/step2", "question": family,
                    "native_control": {"native_question_id": family + "-q", "split": "test"},
                    "branches": [{"action": action, "readout": readout,
                        "readout_status": "FAILED" if failed else "COMPLETED",
                        "answer": record["answer"],
                        "answer_fields": None if failed else {"answer": "Answer"}}]})
                scores[family] = 0 if failed else 1
            save(root / "review-inputs.json", cases)
            owner[stage + "_bound"][method] = str(root)
            owner[stage + "_native"][method] = save(root / "native.json", {
                "compiled": str(root), "metrics": {"collector_actual": {"source_means": scores}}})
    owner_path = tmp_path / "owner.json"
    save(owner_path, owner)
    output = tmp_path / "result"
    monkeypatch.setattr("sys.argv", ["summary", str(protocol), str(owner_path), str(output)])
    main()
    result = json.loads((output / "summary.json").read_text())
    assert result["methods"]["a"]["first_native_F1"] == 0
    assert result["methods"]["a"]["second_native_F1"] == 1
    assert result["methods"]["a"]["both_completed"] == 0
    assert len(result["positions"]) == 2
    changed = tmp_path / "a/repeat/f1-request.json"
    save(changed, {"messages": ["changed"]})
    monkeypatch.setattr("sys.argv", ["summary", str(protocol), str(owner_path),
                                    str(tmp_path / "invalid")])
    with pytest.raises(ValueError, match="exact first input"):
        main()
