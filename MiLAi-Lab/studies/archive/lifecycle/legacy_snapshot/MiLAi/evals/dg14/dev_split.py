"""Source-ID-only DG-14 public/deidentified development split builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from evals.dg14.benchmark import OPENED_DEV_CASE_IDS, ROOT, _atomic_json

FULL_LABEL_FREE_INPUTS = ROOT / "var/dg11/paper/freeze/longmemeval-full-inputs.json"
FORMAL_SOURCE_ID_MANIFESTS = (
    ROOT / "var/dg11/splits/v1/paper-test-v1/source-ids.json",
    ROOT / "var/dg11/splits/v1/generalization-v2/source-ids.json",
)
FORMAL_CONSUMPTION_PATHS = (
    ROOT / "var/dg11/splits/v1/paper-test-v1/consumption.json",
    ROOT / "var/dg11/splits/v1/generalization-v2/consumption.json",
)
DEFAULT_SPLIT_PATH = ROOT / "var/dg14/splits/public-deidentified-dev-v1/source-ids.json"
SELECTION_SALT = "milai-dg14-public-deidentified-dev-v1"


class DG14DevSplitError(RuntimeError):
    """The source-ID-only development split contract failed."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DG14DevSplitError(f"invalid source-ID manifest: {path}") from exc
    if not isinstance(value, dict):
        raise DG14DevSplitError(f"source-ID manifest is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_ids(value: dict[str, Any], path: Path) -> tuple[str, ...]:
    raw = value.get("source_ids")
    if (
        not isinstance(raw, list)
        or not raw
        or not all(isinstance(item, str) and item for item in raw)
        or len(set(raw)) != len(raw)
    ):
        raise DG14DevSplitError(f"source-ID set drifted: {path}")
    return tuple(raw)


def _identity_digest(values: tuple[str, ...]) -> str:
    encoded = json.dumps(
        list(values), ensure_ascii=False, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_public_dev_split(
    *, output_path: Path = DEFAULT_SPLIT_PATH, case_count: int = 50
) -> dict[str, Any]:
    """Select a deterministic dev split after excluding formal source IDs only."""

    if case_count <= 0:
        raise ValueError("development split case_count must be positive")
    full = _read_json(FULL_LABEL_FREE_INPUTS)
    if (
        full.get("schema") != "milai.dg11.paper-longmemeval-inputs.v1"
        or full.get("forbidden_label_fields_present") is not False
        or full.get("label_fields_accessed") is not False
        or full.get("paper_labels_opened") is not False
        or full.get("partition") != "LME-FULL-500-CHARACTERIZATION"
    ):
        raise DG14DevSplitError("full label-free source archive drifted")
    full_ids = _source_ids(full, FULL_LABEL_FREE_INPUTS)
    excluded: set[str] = set()
    exclusion_sources: list[dict[str, object]] = []
    for path in FORMAL_SOURCE_ID_MANIFESTS:
        values = _source_ids(_read_json(path), path)
        excluded.update(values)
        exclusion_sources.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": _sha256(path),
                "source_id_count": len(values),
            }
        )
    candidate_ids = tuple(source_id for source_id in full_ids if source_id not in excluded)
    if len(candidate_ids) < case_count:
        raise DG14DevSplitError("formal exclusions leave too few development cases")
    selected = tuple(
        sorted(
            candidate_ids,
            key=lambda source_id: hashlib.sha256(
                f"{SELECTION_SALT}\0{source_id}".encode()
            ).hexdigest(),
        )[:case_count]
    )
    if set(selected).intersection(excluded):
        raise DG14DevSplitError("formal source ID entered the development split")
    if any(path.exists() for path in FORMAL_CONSUMPTION_PATHS):
        raise DG14DevSplitError("formal holdout consumption exists at a bound path")
    result: dict[str, Any] = {
        "case_count": len(selected),
        "classification": "DEIDENTIFIED_PUBLIC_DEV_SOURCE_IDS",
        "excluded_formal_source_id_count": len(excluded),
        "excluded_formal_source_ids_sha256": _identity_digest(tuple(sorted(excluded))),
        "exclusion_sources": exclusion_sources,
        "formal_holdout_consumed": False,
        "formal_source_id_overlap": [],
        "full_label_free_input": {
            "path": str(FULL_LABEL_FREE_INPUTS.relative_to(ROOT)),
            "sha256": _sha256(FULL_LABEL_FREE_INPUTS),
            "source_id_count": len(full_ids),
        },
        "opened_smoke_overlap": [
            source_id for source_id in selected if source_id in OPENED_DEV_CASE_IDS
        ],
        "schema": "milai.dg14.public-deidentified-dev-split.v1",
        "selection_policy": {
            "kind": "SHA256_LOWEST_AFTER_SOURCE_ID_EXCLUSION",
            "salt": SELECTION_SALT,
        },
        "source_ids": list(selected),
        "source_ids_sha256": _identity_digest(selected),
        "status": "NOT_FORMALLY_EVALUATED",
    }
    _atomic_json(output_path, result)
    return result
