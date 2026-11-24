"""Common TRAIN-only cost normalization for QR and the interaction controller."""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile
from typing import Any

HOST_COST_STATISTIC = "median_host_terminal_prompt_tokens"
_FIELDS = (
    "statistic",
    "scale",
    "dataset_run_id",
    "split_role",
    "reader_requests",
    "group_count",
    "observed_states",
    "groups_per_source",
    "seed",
    "memory_budget_tokens",
    "max_operations",
    "continuation_policy",
    "observation",
    "reader_model",
    "sha_validation",
)
_ROW = ("source", "native_group", "task_id", "prompt_tokens", "termination", "status")


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read(path: Path) -> tuple[dict[str, Any], dict[tuple[str, str | int], tuple[Any, ...]]]:
    path = path.resolve(strict=True)
    with path.open() as stream:
        report = json.load(stream)
    if not isinstance(report, dict) or not set((*_FIELDS, "rows")) <= report.keys():
        raise ValueError("Incomplete Host cost-scale report")
    if (
        report["statistic"] != HOST_COST_STATISTIC
        or report["split_role"] != "train"
        or not _integer(report["reader_requests"])
        or report["reader_requests"] != 0
        or report["sha_validation"] is not False
    ):
        raise ValueError("Cost-scale calibration requires zero Reader requests on TRAIN")
    if any(
        not _integer(report[k]) or report[k] < 1
        for k in (
            "group_count",
            "observed_states",
            "groups_per_source",
            "memory_budget_tokens",
            "max_operations",
        )
    ):
        raise ValueError("Invalid Host scale population or environment")
    if not _integer(report["seed"]) or any(
        not isinstance(report[k], str) or not report[k]
        for k in ("dataset_run_id", "continuation_policy", "observation", "reader_model")
    ):
        raise ValueError("Incomplete Host scale protocol identity")
    if not isinstance(report["rows"], list):
        raise ValueError("Host scale requires individual group observations")
    rows = {}
    counts: Counter[str] = Counter()
    tasks = set()
    tokens = []
    measured_sources = set()
    for row in report["rows"]:
        if not isinstance(row, dict) or set(row) != set(_ROW):
            raise ValueError("Unexpected Host scale row fields")
        source, group, tid, n, termination, status = (row[k] for k in _ROW)
        if any(
            not isinstance(v, str) or not v for v in (source, group, termination, status)
        ) or not _integer(tid):
            raise ValueError("Invalid Host group, task or terminal identity")
        key = (source, group)
        if key in rows or (source, tid) in tasks:
            raise ValueError("Duplicate native group or task in Host scale calibration")
        if n is not None:
            if not _integer(n) or n < 1 or status != "ready":
                raise ValueError("Measured Host tokens require a ready terminal request")
            measured_sources.add(source)
            tokens.append(n)
        rows[key] = (tid, n, termination, status)
        tasks.add((source, tid))
        counts[source] += 1
    if (
        len(rows) != report["group_count"]
        or len(tokens) != report["observed_states"]
        or measured_sources != set(counts)
        or max(counts.values(), default=0) > report["groups_per_source"]
    ):
        raise ValueError("Host scale inventory disagrees with its measurements")
    scale = report["scale"]
    if (
        (not isinstance(scale, int | float) or isinstance(scale, bool))
        or not math.isfinite(scale)
        or not tokens
        or scale != median(tokens)
    ):
        raise ValueError("Host scale differs from the measured median terminal prompt size")
    identity = {k: report[k] for k in _FIELDS}
    identity["report"] = str(path)
    return identity, rows


def _compact(rows: dict) -> list:
    order = sorted(rows, key=lambda k: (k[0], type(k[1]).__name__, str(k[1])))
    return [[*key, *rows[key]] for key in order]


def _witness_path(path: Path) -> Path:
    return path.with_name(path.stem + ".witness.json")


def publish_host_cost_scale_witness(path: Path | str) -> Path:
    """Publish one compact semantic witness beside the primary report, without replacement."""
    identity, rows = _read(Path(path))
    destination = _witness_path(Path(identity["report"]))
    contents = dict(protocol={k: identity[k] for k in _FIELDS}, groups=_compact(rows))
    if not destination.exists():
        with NamedTemporaryFile(mode="w", dir=destination.parent, delete=False) as tmp:
            os.fchmod(tmp.fileno(), Path(identity["report"]).stat().st_mode & 0o666)
            json.dump(contents, tmp, separators=(",", ":"), allow_nan=False)
        try:
            try:
                os.link(tmp.name, destination)
            except FileExistsError:
                pass
        finally:
            Path(tmp.name).unlink()
    if json.loads(destination.read_text()) != contents:
        raise ValueError("Existing frozen Host scale witness differs")
    return destination


def _verified_groups(identity: dict[str, Any]) -> list:
    if (
        not isinstance(identity, dict)
        or identity.get("statistic") != HOST_COST_STATISTIC
        or "report" not in identity
    ):
        raise ValueError("Expected a frozen Host cost-scale report")
    source = Path(identity["report"])
    witness = identity.get("witness_file")
    if witness is None and "groups" not in identity:
        # Pre-witness QR registrations stored path, size and mtime. The shared
        # immutable witness attests their original rows after host restoration.
        witness = _witness_path(source)
    if witness is None:
        groups = identity["groups"]
    else:
        record = json.loads(Path(witness).read_text())
        if record["protocol"] != {k: identity[k] for k in _FIELDS}:
            raise ValueError("Frozen Host witness and fit protocol differ")
        groups = record["groups"]
    if source.is_file():
        current, rows = _read(source)
        if any(current[k] != identity[k] for k in _FIELDS) or _compact(rows) != groups:
            raise ValueError("Recorded Host scale data changed")
    return groups


def load_host_cost_scale(
    path: Path | str, *, dataset_run_id: str | None = None, budget: int | None = None
) -> tuple[float, dict[str, Any]]:
    identity, rows = _read(Path(path))
    if dataset_run_id is not None and identity["dataset_run_id"] != dataset_run_id:
        raise ValueError("Cost scale belongs to a different dataset run")
    if budget is not None and identity["memory_budget_tokens"] != budget:
        raise ValueError("Cost scale belongs to a different material budget")
    witness = _witness_path(Path(identity["report"]))
    groups = _compact(rows)
    if witness.exists():
        record = json.loads(witness.read_text())
        if record != {"protocol": {k: identity[k] for k in _FIELDS}, "groups": groups}:
            raise ValueError("Host report and frozen semantic witness disagree")
        identity["witness_file"] = str(witness)
    else:
        identity["groups"] = groups
    return float(identity["scale"]), identity


def require_same_host_cost_scale(
    parent_identity: dict[str, Any], candidate_identity: dict[str, Any]
) -> None:
    """Compare actual protocol and samples, independent of formatting, path or mtime."""
    original = _verified_groups(parent_identity)
    if parent_identity == candidate_identity:
        return
    candidate = _verified_groups(candidate_identity)
    if any(parent_identity[k] != candidate_identity[k] for k in _FIELDS) or original != candidate:
        raise ValueError("Calibration protocol or source/group/task/token measurements differ")
