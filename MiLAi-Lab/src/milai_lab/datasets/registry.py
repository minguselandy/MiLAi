from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_id: str
    version: str
    external_root: str
    split_files: dict[str, str]
    file_sha256: dict[str, str]

    def verify(self, *, root_override: Path | None = None) -> list[str]:
        root = root_override or Path(self.external_root).expanduser()
        errors: list[str] = []
        for split, relative in sorted(self.split_files.items()):
            target = root / relative
            if not target.is_file():
                errors.append(f"{split}: missing {target}")
                continue
            expected = self.file_sha256.get(relative)
            if expected and _sha256_file(target) != expected:
                errors.append(f"{split}: digest mismatch for {target}")
        return errors


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset_manifest(path: Path) -> DatasetManifest:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("unsupported dataset manifest schema")
    return DatasetManifest(
        dataset_id=str(raw["dataset_id"]),
        version=str(raw["version"]),
        external_root=str(raw["external_root"]),
        split_files={str(key): str(value) for key, value in raw["split_files"].items()},
        file_sha256={str(key): str(value) for key, value in raw.get("file_sha256", {}).items()},
    )

