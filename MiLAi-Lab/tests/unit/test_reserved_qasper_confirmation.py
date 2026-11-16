import copy
import json

import pytest

from prepare_reserved_qasper_confirmation import export_reserved, main


def native_paper():
    return {"title": "Study", "abstract": "Abstract", "full_text": [
        {"section_name": "Results", "paragraphs": ["Literal public result."]}],
        "figures_and_tables": [], "qas": [{"question": "  Which result?\n", "question_id": "q0",
            "answers": [{"annotation_id": "a0", "answer": {"unanswerable": False,
                "extractive_spans": [], "yes_no": None, "free_form_answer": "PRIVATE REFERENCE",
                "evidence": ["Literal public result."], "highlighted_evidence": []}}]},
            {"question": "Second question", "question_id": "q1", "answers": []}]}


def identities():
    return [{"paper_id": p, "source_group": "qasper-paper-" + p, "native_split": "test"}
            for p in ["paper-b", "paper-a"]]


def test_reserved_order_first_question_and_test_role_are_retained_without_gold_in_inputs():
    papers = {p: native_paper() for p in ["paper-a", "paper-b"]}
    histories, controls = export_reserved(papers, identities())
    assert [h["source_group"] for h in histories] == [r["source_group"] for r in identities()]
    assert all(h["split"] == "test" and len(h["requests"]) == 1 for h in histories)
    assert all(c["split"] == "test" and c["native_question_id"] == "q0" for c in controls)
    assert histories[0]["requests"][0]["retrieval_request"]["query"] == "  Which result?\n"
    assert "PRIVATE REFERENCE" not in json.dumps(histories)
    assert "PRIVATE REFERENCE" in json.dumps(controls)
    changed = copy.deepcopy(papers)
    for paper in changed.values():
        paper["qas"][0]["answers"] = []
        paper["qas"][0]["question_id"] = "different-offline-id"
    assert export_reserved(changed, identities())[0] == histories


def test_missing_reserved_question_or_changed_role_is_not_silently_replaced():
    papers = {p: native_paper() for p in ["paper-a", "paper-b"]}
    papers["paper-b"]["qas"] = []
    with pytest.raises(ValueError, match="do not replace"):
        export_reserved(papers, identities())
    wrong = identities()
    wrong[0]["native_split"] = "dev"
    with pytest.raises(ValueError, match="TEST role"):
        export_reserved(papers, wrong)


def test_unfrozen_protocol_is_rejected_before_archive_or_source_access(tmp_path, monkeypatch):
    protocol, output = tmp_path / "protocol.json", tmp_path / "output"
    protocol.write_text(json.dumps({"status": "SOURCE_IDS_ONLY"}))
    monkeypatch.setattr("sys.argv", ["export", str(protocol), str(output)])
    with pytest.raises(ValueError, match="Freeze final methods"):
        main()
    assert not output.exists()


def test_frozen_export_writes_only_test_sources_offline_controls_and_frozen_settings(
        tmp_path, monkeypatch):
    import io
    import tarfile

    def save(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value))
        return path

    archive = tmp_path / "native.tgz"
    data = json.dumps({p: native_paper() for p in ["paper-a", "paper-b"]}).encode()
    with tarfile.open(archive, "w:gz") as stream:
        info = tarfile.TarInfo("qasper-test-v0.3.json")
        info.size = len(data)
        stream.addfile(info, io.BytesIO(data))
    reserved = save("reserved.json", {"archive": str(archive), "candidate_metadata": identities()})
    groups = [r["source_group"] for r in identities()]
    subset = {"sources": 1, "indices_zero_based": [1], "source_groups": [groups[1]]}
    sampling = save("sampling.json", {"reservation": str(reserved), "source_order": groups,
        "source_count": 2, "second_Host_readout": subset, "author_review": subset})
    config = {"entrypoints": {"functional": {"frozen_fixture_setting": "unchanged"}}}
    settings = save("config.json", config)
    protocol = save("protocol.json", {"status": "FROZEN_BEFORE_CONFIRMATION_SOURCE_EXPORT",
        "methods": {m: {} for m in ["fixed", "rules", "s1", "new"]},
        "primary": ["new", "s1"], "primary_metric": "complete_supported",
        "answer_format": "answer_separate_v1", "source_count": 2,
        "host_config": str(settings), "reservation": str(reserved),
        "sampling_freeze": str(sampling)})
    output = tmp_path / "output"
    monkeypatch.setattr("sys.argv", ["export", str(protocol), str(output)])
    main()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["source_order"] == groups
    assert manifest["native_split"] == manifest["research_split"] == "test"
    assert manifest["model_calls"] == manifest["Host_calls"] == 0
    assert manifest["training_exports_written"] is False
    assert json.loads((output / "host-config.json").read_text()) == config
    assert not (output / "train.jsonl").exists()
    assert "PRIVATE REFERENCE" not in (output / "histories.json").read_text()
    assert "PRIVATE REFERENCE" in (output / "controls.jsonl").read_text()
