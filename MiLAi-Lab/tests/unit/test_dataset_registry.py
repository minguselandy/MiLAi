from __future__ import annotations

import hashlib
import json
from pathlib import Path

from milai_lab.datasets.registry import load_dataset_manifest


def test_dataset_manifest_verifies_external_file(tmp_path: Path) -> None:
    dataset_root = tmp_path / "dataset"
    dataset_root.mkdir()
    payload = dataset_root / "cases.jsonl"
    payload.write_text('{"case": 1}\n', encoding="utf-8")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_id": "fixture",
                "version": "1",
                "external_root": str(dataset_root),
                "split_files": {"test": "cases.jsonl"},
                "file_sha256": {"cases.jsonl": digest},
            }
        ),
        encoding="utf-8",
    )

    manifest = load_dataset_manifest(manifest_path)

    assert manifest.verify() == []

