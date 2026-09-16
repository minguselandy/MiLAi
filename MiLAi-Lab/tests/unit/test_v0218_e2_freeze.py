"""E2 admission preserves sealed complete E1 attempts, accounting and cleanup."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import run_v0218_e2 as control
from run_v0218 import sha


@pytest.fixture
def prior(tmp_path, monkeypatch):
    archive = tmp_path / "executed-source"
    archive.mkdir()
    (archive / "fixture.py").write_text("# frozen\n")
    (tmp_path / "fixture.json").write_text("{}")
    manifest = {
        "stage": "E1_OPEN_DISCOVERY_V1",
        "episodes": [{}] * 14,
        "implementation": {"tools/fixture.py": sha(archive / "fixture.py")},
        "input_files": {"fixture.json": sha(tmp_path / "fixture.json")},
    }
    cost = {"requests": 1, "raw_tokens": 2, "pending": 0, "violations": 0}
    result = {
        "status": "DISCOVERY_EXECUTED_REQUIRES_AUDIT",
        "rows": [{}] * 14,
        "cost": cost,
        "cleanup": {"api_stopped": True, "compose_stop_returncode": 0},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    (tmp_path / "manifest-sha256.json").write_text(
        json.dumps({"sha256": sha(tmp_path / "manifest.json")})
    )
    (tmp_path / "result.json").write_text(json.dumps(result))
    audit = {
        "cost": cost,
        "manifest_sha256": sha(tmp_path / "manifest.json"),
        "result_sha256": sha(tmp_path / "result.json"),
    }
    (tmp_path / "discovery-audit-v1.json").write_text(json.dumps(audit))
    monkeypatch.setattr(control, "costs", lambda _: cost)
    return {
        "path": str(tmp_path),
        "result_sha256": sha(tmp_path / "result.json"),
        "audit_sha256": sha(tmp_path / "discovery-audit-v1.json"),
    }


def test_complete_sealed_prior_passes(prior):
    assert control.verify_prior(prior)["stage"] == "E1_OPEN_DISCOVERY_V1"


@pytest.mark.parametrize(
    "fault",
    [
        "data",
        "code",
        "manifest",
        "audit_hash",
        "result_hash",
        "status",
        "partial",
        "cleanup",
        "pending",
        "audit_cost",
    ],
)
def test_prior_tampering_or_incomplete_run_rejected(prior, fault):
    root = Path(prior["path"])
    result = control.read(root / "result.json")
    audit = control.read(root / "discovery-audit-v1.json")
    if fault == "data":
        (root / "fixture.json").write_text('{"changed":true}')
    elif fault == "code":
        (root / "executed-source/fixture.py").write_text("changed")
    elif fault == "manifest":
        (root / "manifest.json").write_text("{}")
    elif fault == "audit_hash":
        prior["audit_sha256"] = "incorrect"
    elif fault == "result_hash":
        prior["result_sha256"] = "incorrect"
    else:
        if fault == "status":
            result["status"] = "DISCOVERY_STOPPED_PRESERVED"
        elif fault == "partial":
            result["rows"].pop()
        elif fault == "cleanup":
            result["cleanup"]["api_stopped"] = False
        elif fault == "pending":
            result["cost"]["pending"] = 1
        else:
            audit["cost"] = {}
        (root / "result.json").write_text(json.dumps(result))
        prior["result_sha256"] = sha(root / "result.json")
        audit["result_sha256"] = prior["result_sha256"]
        (root / "discovery-audit-v1.json").write_text(json.dumps(audit))
        prior["audit_sha256"] = sha(root / "discovery-audit-v1.json")
    with pytest.raises(AssertionError):
        control.verify_prior(prior)
