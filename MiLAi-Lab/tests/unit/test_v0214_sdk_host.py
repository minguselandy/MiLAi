"""The successor Host explicitly loads a wheel-pinned SDK, never a Lab package dependency."""

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from run_v0214_e2e import reconcile_presentation
from v0214_host_runtime import source_runtime
from v0214_source_binding import FileSources


def test_lab_runtime_remains_default():
    api, receipt = source_runtime({})
    assert api.__name__ == "milai_lab.methods.host_acquisition"
    assert receipt == {"implementation": "LAB"}


def test_unknown_runtime_is_not_silently_replaced():
    with pytest.raises(ValueError, match="UNKNOWN_HOST_ACQUISITION_IMPLEMENTATION"):
        source_runtime({"host_acquisition": {"implementation": "unrecognized"}})


def test_changed_wheel_rejected_before_import(tmp_path):
    wheel = tmp_path / "changed.whl"
    wheel.write_bytes(b"changed")
    with pytest.raises(ValueError, match="SDK_WHEEL_CHANGED"):
        source_runtime({"host_acquisition": {"implementation": "CLIENT_SDK",
            "wheel": str(wheel), "wheel_sha256": "not-the-actual-digest"}})


def test_installed_sdk_repeated_contention_and_transport_receipts(tmp_path):
    pytest.importorskip("milai_client.host_acquisition", reason="optional Host SDK wheel")
    config = json.loads((Path(__file__).resolve().parents[2] /
        "configs/v0214-sdk-host-development.json").read_text())
    api, receipt = source_runtime(config)
    assert receipt["version"] == "0.1.4"
    assert receipt["matching_python_files"] > 1
    assert api.AcquisitionHelper.__module__ == "milai_client.host_acquisition"
    scope = api.Binding("principal", "project", "task")
    for index in range(3):
        (tmp_path / f"source-{index}.txt").write_text(f"Authorized source {index}.")
    backend = FileSources({scope: tmp_path}, source_api=api)
    helper = api.AcquisitionHelper(backend, max_parallel_source_reads=1)
    # Actual contention binds the semaphore. Reusing a new asyncio.run loop on the
    # next round would raise RuntimeError; one Host Runner supports both rounds.
    with asyncio.Runner() as loop:
        refs = loop.run(helper.resolve_sources(scope))
        assert all(type(ref) is api.SourceRef for ref in refs)
        for _ in range(2):
            pages = loop.run(helper.read_many(scope, refs))
            assert all(type(page) is api.SourcePage and page.text for page in pages)
        request_ids = [page.request_id for page in pages]
        visible = loop.run(helper.presentation(scope, request_ids, "model-request"))
        assert helper.presented == []
        (tmp_path / "provider-ledger.jsonl").write_text(json.dumps({
            "event": "RESERVED", "request_id": "model-request"}) + "\n")
        (tmp_path / "model-request-request.json").write_text(json.dumps({"messages": [{
            "role": "user", "content": json.dumps({
                "source_pages": [asdict(page) for page in visible]})}]}))
        reconcile_presentation(tmp_path, helper)
        assert helper.presented == []
        (tmp_path / "model-request-http.json").write_text("{}")
        reconcile_presentation(tmp_path, helper)
        assert helper.presented == [("model-request", rid) for rid in request_ids]
        backend.withheld.add((scope, refs[0].source_id))
        withdrawn = loop.run(helper.presentation(scope, request_ids, "next-request"))
        assert withdrawn[0].coverage == api.Coverage.WITHHELD
        assert withdrawn[0].text == ""
        with pytest.raises(PermissionError, match="CROSS_TASK_PRESENTATION"):
            loop.run(helper.presentation(api.Binding("p", "j", "other"),
                                         request_ids, "other-request"))
