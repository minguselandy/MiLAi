from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import dg10_remediation as remediation

PACKAGE = "DG-10-experiment-results-candidate.2-2026-08-22"
ARCHIVE_SHA256 = "7e1b88267d2c9cd6f819d937ddd1ed5a1f15b5cb5b38b547f8067938f7702166"
RECEIPT_SHA256 = "9452677d39c14649a42dea31c974373ffe25570ef0792b1615a4315998891c12"
DEFAULT_OUTPUT = ROOT / "docs/reports/DG-10-r0-archive-replay-candidate.4-2026-08-22.json"


class ArchiveReplayError(remediation.RemediationError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ArchiveReplayError(reason)


def _json_object(raw: bytes, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArchiveReplayError(reason) from exc
    _require(isinstance(value, dict), reason)
    return value


def _safe_member_name(name: str) -> PurePosixPath:
    parsed = PurePosixPath(name)
    _require(
        bool(parsed.parts)
        and not parsed.is_absolute()
        and ".." not in parsed.parts
        and "\\" not in name
        and parsed.parts[0] == PACKAGE,
        "candidate.2 archive member path is unsafe or outside its package root",
    )
    return parsed


def _parse_sha256sums(raw: bytes) -> dict[str, str]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ArchiveReplayError("candidate.2 SHA256SUMS is not UTF-8") from exc
    result: dict[str, str] = {}
    for line in lines:
        pieces = line.split("  ", 1)
        _require(len(pieces) == 2, "candidate.2 SHA256SUMS syntax drift")
        digest, path = pieces
        remediation._require_sha256(digest, "candidate.2 SHA256SUMS digest")
        parsed = PurePosixPath(path)
        _require(
            path not in result
            and bool(parsed.parts)
            and not parsed.is_absolute()
            and ".." not in parsed.parts,
            "candidate.2 SHA256SUMS path is unsafe or repeated",
        )
        result[path] = digest
    return result


def build_replay(*, archive_path: Path, receipt_path: Path) -> dict[str, Any]:
    archive_path = archive_path.resolve()
    receipt_path = receipt_path.resolve()
    _require(
        archive_path.is_file()
        and not archive_path.is_symlink()
        and remediation.sha256_file(archive_path) == ARCHIVE_SHA256,
        "candidate.2 archive identity drift",
    )
    _require(
        receipt_path.is_file()
        and not receipt_path.is_symlink()
        and remediation.sha256_file(receipt_path) == RECEIPT_SHA256,
        "candidate.2 archive receipt identity drift",
    )
    receipt = _json_object(receipt_path.read_bytes(), "candidate.2 archive receipt invalid")
    _require(
        receipt.get("archive_sha256") == ARCHIVE_SHA256
        and receipt.get("archive_member_count") == 201
        and receipt.get("payload_entry_count") == 198
        and receipt.get("final_decision") == "NO_GO_RELEASE_STOPPED"
        and receipt.get("archive_safety", {}).get("regular_files_only") is True,
        "candidate.2 archive receipt semantic drift",
    )

    raw_members: dict[str, bytes] = {}
    member_rows: list[dict[str, Any]] = []
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            parsed = _safe_member_name(member.name)
            _require(member.isfile() and not member.issym() and not member.islnk(), "archive member is not regular")
            relative = PurePosixPath(*parsed.parts[1:]).as_posix()
            _require(relative and relative not in raw_members, "archive member path repeats")
            handle = archive.extractfile(member)
            _require(handle is not None, "archive member cannot be read")
            raw = handle.read()
            _require(len(raw) == member.size, "archive member size drift")
            digest = hashlib.sha256(raw).hexdigest()
            raw_members[relative] = raw
            member_rows.append(
                {
                    "path": relative,
                    "size": len(raw),
                    "sha256": digest,
                    "tar_member_type": "REGULAR_FILE",
                }
            )
    _require(len(member_rows) == 201, "candidate.2 archive member denominator drift")

    manifest_raw = raw_members.get("MANIFEST.json")
    sums_raw = raw_members.get("SHA256SUMS")
    _require(manifest_raw is not None and sums_raw is not None, "archive control files absent")
    manifest = _json_object(manifest_raw, "candidate.2 payload manifest invalid")
    sums = _parse_sha256sums(sums_raw)
    _require(
        set(sums) == set(raw_members) - {"SHA256SUMS"},
        "candidate.2 SHA256SUMS membership drift",
    )
    _require(
        all(hashlib.sha256(raw_members[path]).hexdigest() == digest for path, digest in sums.items()),
        "candidate.2 SHA256SUMS content mismatch",
    )

    entries = manifest.get("entries")
    _require(isinstance(entries, list) and len(entries) == 198, "payload manifest denominator drift")
    indexed_entries: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        _require(isinstance(entry, Mapping), "payload manifest entry invalid")
        path = entry.get("path")
        _require(isinstance(path, str) and path not in indexed_entries, "payload manifest path invalid")
        indexed_entries[path] = entry
    _require(
        set(indexed_entries) == set(raw_members) - {"MANIFEST.json", "README.md", "SHA256SUMS"},
        "payload manifest membership drift",
    )
    for path, entry in indexed_entries.items():
        raw = raw_members[path]
        _require(
            entry.get("size") == len(raw)
            and entry.get("sha256") == hashlib.sha256(raw).hexdigest()
            and isinstance(entry.get("source_class"), str),
            "payload manifest entry content drift",
        )
    _require(
        manifest.get("schema") == "milai.dg10.experiment-results-package-manifest.v1"
        and manifest.get("package") == PACKAGE
        and manifest.get("payload_entry_count") == 198
        and manifest.get("credentials_or_secrets_included") is False
        and manifest.get("raw_benchmark_sidecars_included") is False
        and manifest.get("tier2_reveal_included") is False
        and manifest.get("final_decision") == "NO_GO_RELEASE_STOPPED",
        "payload manifest boundary or decision drift",
    )
    _require(
        hashlib.sha256(manifest_raw).hexdigest() == receipt.get("manifest_sha256")
        and hashlib.sha256(sums_raw).hexdigest() == receipt.get("sha256sums_sha256"),
        "archive control-file receipt binding drift",
    )

    member_rows.sort(key=lambda row: str(row["path"]))
    replay_core = {
        "archive_sha256": ARCHIVE_SHA256,
        "receipt_sha256": RECEIPT_SHA256,
        "member_count": len(member_rows),
        "payload_entry_count": len(entries),
        "member_entries_sha256": remediation.sha256_bytes(remediation.encoded_json({"members": member_rows})),
        "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "sha256sums_sha256": hashlib.sha256(sums_raw).hexdigest(),
    }
    return {
        "schema": "milai.dg10.r0-archive-replay.v1",
        "candidate_id": remediation.CANDIDATE,
        "stage_id": "DG10-R0",
        "stage_state": "AUTHOR_CANDIDATE",
        "status": "PASS_EXACT_SAFE_ARCHIVE_REPLAY_REVIEW_REQUIRED",
        "archive_path_class": "FROZEN_LOCAL_HISTORICAL_INPUT",
        "archive_safety": {
            "regular_file_count": 201,
            "unsafe_path_count": 0,
            "duplicate_path_count": 0,
            "symlink_count": 0,
            "hardlink_count": 0,
        },
        "receipt_and_control_files": replay_core,
        "members": member_rows,
        "replay_transcript_sha256": remediation.sha256_bytes(remediation.encoded_json(replay_core)),
        "historical_bytes_modified": False,
        "independent_acceptance": False,
        "model_run_authorized": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay the frozen candidate.2 DG-10 archive")
    parser.add_argument("--archive", type=Path, default=remediation.BASELINE_ARCHIVE)
    parser.add_argument("--receipt", type=Path, default=remediation.BASELINE_RECEIPT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = build_replay(archive_path=args.archive, receipt_path=args.receipt)
    remediation.atomic_write_new(args.output.resolve(), remediation.encoded_json(report))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
