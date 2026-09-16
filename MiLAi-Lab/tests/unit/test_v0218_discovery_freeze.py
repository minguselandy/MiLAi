"""A discovery batch cannot bypass settled, frozen and cleaned baseline evidence."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0218_discovery as discovery
from run_v0218 import sha


@pytest.fixture
def source(tmp_path, monkeypatch):
    archive = tmp_path / "executed-source"
    archive.mkdir()
    code = archive / "fixture.py"
    code.write_text("# immutable fixture\n")
    data = tmp_path / "fixture.json"
    data.write_text("{}")
    manifest = {
        "implementation": {"tools/fixture.py": sha(code)},
        "input_files": {"fixture.json": sha(data)},
    }
    cost = {"requests": 1, "raw_tokens": 2, "pending": 0, "violations": 0}
    result = {
        "status": "E0_EXECUTED_REQUIRES_CHAIN_AND_BEHAVIOR_AUDIT",
        "cost": cost,
        "cleanup": {"api_stopped": True, "compose_stop_returncode": 0},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "manifest-sha256.json").write_text(
        json.dumps({"sha256": sha(tmp_path / "manifest.json")})
    )
    (tmp_path / "result.json").write_text(json.dumps(result))
    (tmp_path / "baseline-audit-v1.json").write_text(json.dumps({"cost": cost}))
    monkeypatch.setattr(discovery, "costs", lambda _: cost)
    return tmp_path


def test_source_accepts_only_hash_bound_settled_evidence(source):
    assert discovery.verify_source(source)["input_files"]["fixture.json"] == sha(
        source / "fixture.json"
    )


@pytest.mark.parametrize(
    "fault", ["source", "code", "manifest", "status", "cleanup", "cost", "audit"]
)
def test_source_rejects_forged_or_unsettled_prior(source, fault):
    result = discovery.read(source / "result.json")
    if fault == "source":
        (source / "fixture.json").write_text('{"changed": true}')
    elif fault == "code":
        (source / "executed-source/fixture.py").write_text("changed")
    elif fault == "manifest":
        (source / "manifest.json").write_text("{}")
    elif fault == "status":
        result["status"] = "E0_STOPPED_PRESERVED"
    elif fault == "cleanup":
        result["cleanup"]["api_stopped"] = False
    elif fault == "cost":
        result["cost"]["pending"] = 1
    else:
        (source / "baseline-audit-v1.json").write_text('{"cost": {}}')
    (source / "result.json").write_text(json.dumps(result))
    with pytest.raises(AssertionError):
        discovery.verify_source(source)
