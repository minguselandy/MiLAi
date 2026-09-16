from __future__ import annotations

import json
from pathlib import Path

import pytest

from milai.config import SettingsError, load_settings
from milai.operations.import_dry_run import dry_run_import


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    return load_settings(
        {
            "MILAI_DATABASE_URL": "postgresql://milai_api:secret@127.0.0.1:15432/milai",
            "MILAI_STEWARD_DATABASE_URL": "postgresql://milai_steward:secret@127.0.0.1:15432/milai",
            "MILAI_BLOB_ROOT": str(tmp_path / "blobs"),
            "MILAI_TENANT_ID": "11111111-1111-4111-8111-111111111111",
            "MILAI_LOCAL_ACTOR_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            "MILAI_API_TOKEN": "legacy-token-with-at-least-32-characters",
            "MILAI_CAUSAL_TOKEN_SECRET": "causal-secret-with-at-least-32-characters",
        }
    )


def test_mem0_dry_run_reports_hashes_and_quarantine_without_content_or_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mem0.json"
    source.write_text(
        json.dumps(
            [
                {
                    "id": "m1",
                    "memory": "synthetic preference",
                    "created_at": "2026-08-17T00:00:00Z",
                    "user_id": "user-1",
                    "tenant_id": "tenant-map-1",
                    "permission_snapshot": {"authorized": True, "basis": "synthetic"},
                    "retention_state": "READABLE",
                },
                {"id": "m2", "memory": "unproven record"},
            ]
        ),
        encoding="utf-8",
    )
    report = tmp_path / "dry-run.json"
    result = dry_run_import(
        _settings(tmp_path),
        source="mem0-json-v1",
        input_path=source,
        report_path=report,
    )
    value = json.loads(report.read_text())
    assert result["status"] == "DRY_RUN_COMPLETE_NO_WRITES"
    assert result["accepted"] == 1
    assert result["quarantined"] == 1
    assert value["data_gate"]["execution_authorized"] is False
    assert value["accepted_records"][0]["canonical_claim_created"] is False
    assert "synthetic preference" not in report.read_text()
    assert report.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SettingsError, match="never overwrites"):
        dry_run_import(
            _settings(tmp_path),
            source="mem0-json-v1",
            input_path=source,
            report_path=report,
        )
