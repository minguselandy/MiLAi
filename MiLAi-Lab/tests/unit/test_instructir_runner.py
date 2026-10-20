"""Real independent source copies and lossless closed-case archives; no model requests."""
import json
import tarfile
import time
from pathlib import Path

import httpx
import pytest

from milai_lab.datasets.instructir import corpus_sources
from milai_lab.runners.functional import frozen, prepare
from milai_lab.runners.instructir import archive_query, project_query_result, run_given_queries
from milai_lab.runners.retrieval_histories import prepare_history_bank


def source_bank_at(tmp_path):
    from test_given_retrieval import prepared_given

    prepared_given(tmp_path)
    bank = tmp_path / "source-bank"
    bank.mkdir()
    template = bank / "template"
    prepare(template, tmp_path / "settings.json", source_version="synthetic-source-bank")
    setup = prepare_history_bank(template, bank="corpus", owner="alice", history={
        "source_group": "synthetic-public-corpus", "sources": corpus_sources([
            {"_id": "doc-A", "title": "Cedar code", "text": "The code is 4312."},
            {"_id": "doc-B", "title": "Birch colour", "text": "The colour is blue."}])})
    (bank / "preparation.json").write_text(json.dumps({"status": "COMPLETE_SOURCE_STORE",
        "bank": "corpus", "owner": "alice", "source_documents": 2}))
    (bank / "source-map.json").write_text(json.dumps({
        row["receipt"]["source_ref"]: row["original_event_id"] for row in setup["sources"]}))
    return bank


def test_each_query_has_only_initial_corpus_and_its_own_query(tmp_path, monkeypatch):
    from test_given_retrieval import no_http

    bank = source_bank_at(tmp_path)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    # The method config can differ while the source namespace/IDs remain identical.
    config = json.loads((tmp_path / "settings.json").read_text())
    config["config_version"] = "new-method-on-same-sources"
    method = tmp_path / "method.json"
    method.write_text(json.dumps(config))
    queries = [{"_id": "q1", "text": "Quote the literal code[SEP]Cedar code"},
               {"_id": "q2", "text": "Quote the colour[SEP]Birch colour"}]
    output = tmp_path / "evaluation"
    driver = run_given_queries(method, queries, bank, output, source_version="synthetic-method")
    assert driver["status"] == "COMPLETED"
    assert len(driver["completed"]) == 2 and not driver["qrels_loaded"]
    assert frozen(output / "template")["run_id"] == frozen(bank / "template")["run_id"]
    assert frozen(output / "template")["config_version"] == "new-method-on-same-sources"
    assert frozen(bank / "template")["config_version"] != "new-method-on-same-sources"
    assert not list((output / "working").iterdir())
    mapping = json.loads((bank / "source-map.json").read_text())
    for i, row in enumerate(queries):
        extracted = tmp_path / f"extract-{i}"
        with tarfile.open(output / "cases" / f"{i:05d}.tar.gz") as archive:
            archive.extractall(extracted, filter="data")
        root = extracted / "case"
        result_file = next(root.glob("banks/*/*-result.json"))
        result = json.loads(result_file.read_text())
        assert len(result["sources"]) == 3
        queries_in_store = [s for s in result["sources"] if s["role"] == "user"]
        assert len(queries_in_store) == 1
        assert queries_in_store[0]["content"] == row["text"].split("[SEP]")[1]
        assert set(mapping) <= {s["event_id"] for s in result["sources"]}
        projected = project_query_result(root, result, mapping)
        assert projected["ranking"] == driver["completed"][i]["ranking"]
    compute = json.loads((output / "orchestration-compute.json").read_text())
    assert not compute["ledger_recorded"] and compute["cpu_seconds"] > 0
    ledger = json.loads(Path(frozen(output / "template")["config"]["budget_path"]).read_text())
    assert ledger["generation_requests"] == 0


def test_archive_keeps_exact_file_bytes_and_stops_before_removal_if_destination_exists(tmp_path):
    root = tmp_path / "working"
    root.mkdir()
    originals = {"raw.bin": bytes(range(256)), "result.json": '{"text":"甲🙂"}\n'.encode()}
    for name, body in originals.items():
        (root / name).write_bytes(body)
    archive_path = tmp_path / "closed.tar.gz"
    report = archive_query(root, archive_path)
    assert report["files"] == 2 and not root.exists()
    with tarfile.open(archive_path) as archive:
        assert {Path(m.name).name: archive.extractfile(m).read()
                for m in archive.getmembers() if m.isfile()} == originals
    root.mkdir()
    (root / "another.txt").write_text("still present")
    with pytest.raises(FileExistsError):
        archive_query(root, archive_path)
    assert (root / "another.txt").read_text() == "still present"


def test_unexpected_first_failure_is_retained_and_later_queries_do_not_run(tmp_path, monkeypatch):
    from test_given_retrieval import no_http

    import milai_lab.runners.instructir as runner

    bank = source_bank_at(tmp_path)
    monkeypatch.setattr(httpx.Client, "send", no_http)
    original = runner.message
    calls = []

    def fail_after_real_execution(*args, **kwargs):
        calls.append(kwargs["message_id"])
        result = original(*args, **kwargs)
        return {**result, "status": "FAILED", "error_category": "synthetic",
                "error_type": "SyntheticFailure", "error": "first_synthetic_failure"}

    monkeypatch.setattr(runner, "message", fail_after_real_execution)
    output = tmp_path / "failed-evaluation"
    with pytest.raises(RuntimeError, match="First failed query retained"):
        runner.run_given_queries(tmp_path / "settings.json", [
            {"_id": "first", "text": "instruction[SEP]Cedar code"},
            {"_id": "untouched", "text": "instruction[SEP]Birch colour"}],
            bank, output, source_version="synthetic-failure")
    assert calls == ["first"]
    driver = json.loads((output / "driver.json").read_text())
    assert driver["status"] == "FAILED" and len(driver["completed"]) == 1
    assert driver["completed"][0]["ranking"] == {}
    assert (output / "cases/00000.tar.gz").exists()
    assert not (output / "cases/00001.tar.gz").exists()


def test_interrupted_query_cpu_is_measured_even_without_a_returned_result(tmp_path, monkeypatch):
    import milai_lab.runners.instructir as runner

    bank = source_bank_at(tmp_path)

    def interrupted(*args, **kwargs):
        start = time.process_time()
        while time.process_time() - start < .02:
            sum(i * i for i in range(1000))
        raise KeyboardInterrupt("synthetic interruption")

    monkeypatch.setattr(runner, "message", interrupted)
    output = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        runner.run_given_queries(tmp_path / "settings.json", [
            {"_id": "q", "text": "instruction[SEP]query"}],
            bank, output, source_version="synthetic-interruption")
    driver = json.loads((output / "driver.json").read_text())
    compute = json.loads((output / "orchestration-compute.json").read_text())
    assert driver["error_type"] == "KeyboardInterrupt"
    assert driver["active"]["query_cpu_seconds_nested"] >= .02
    assert compute["query_cpu_seconds_not_in_nested_ledger_phases"] >= .02
    assert (output / "working/00000").exists()
