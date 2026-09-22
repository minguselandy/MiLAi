import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "tools/prepare_utility_first_batch.py"
spec = importlib.util.spec_from_file_location("prepare_utility_first_batch", MODULE_PATH)
assert spec is not None and spec.loader is not None
prepare_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare_module)


def fixture_manifest(monkeypatch, *, missing=False):
    rows = [{"id": str(i), "cluster": str(i)} for i in range(16)]
    partitions = {"DEV": rows[:8], "VALID": rows[8:]}
    metadata = {"domains": {d: {"partitions": partitions} for d in ("db_bench", "os_interaction")}}
    monkeypatch.setattr(prepare_module, "sha", lambda p: prepare_module.SPLIT_SHA)
    monkeypatch.setattr(prepare_module.json, "loads", lambda s: metadata)
    monkeypatch.setattr(Path, "read_text", lambda self: "not task content")
    monkeypatch.setattr(Path, "is_file", lambda self: not missing)


def test_schedule_is_fixed_independent_and_counterbalanced(monkeypatch):
    fixture_manifest(monkeypatch)
    value = prepare_module.prepare()
    assert not value["method_admission"]["ready"]
    assert len(value["schedule"]) == 32
    for domain in value["domains"]:
        cases = [x for x in value["schedule"] if x["domain"] == domain]
        assert len({x["task_id"] for x in cases}) == 12
        assert len({x["cluster"] for x in value["domains"][domain]}) == 12
        original = {x["position"]: x for x in cases if not x["repeat"]}
        repeats = [x for x in cases if x["repeat"]]
        assert [x["position"] for x in repeats] == [0, 3, 6, 9]
        for row in repeats:
            assert row["arms"] == original[row["position"]]["arms"][::-1]
    assert value["usage_at_schedule_freeze"]["first_request_at"] is None


def test_missing_exposure_does_not_expand_into_protected_pool(monkeypatch):
    fixture_manifest(monkeypatch, missing=True)
    with pytest.raises(ValueError, match="INSUFFICIENT_EXPOSED"):
        prepare_module.prepare()


def test_split_identity_is_checked_before_selection(monkeypatch):
    monkeypatch.setattr(prepare_module, "sha", lambda p: "changed")
    with pytest.raises(ValueError, match="FROZEN_SPLIT_CHANGED"):
        prepare_module.prepare()
