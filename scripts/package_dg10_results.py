from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import tarfile
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from scan_ua_secrets import _secrets

ROOT = Path(__file__).resolve().parents[1]
DATE = "2026-08-22"
PACKAGE_NAME = f"DG-10-experiment-results-candidate.2-{DATE}"
DEFAULT_ARCHIVE = ROOT / "dist" / f"{PACKAGE_NAME}.tar.gz"
DEFAULT_RECEIPT = ROOT / "dist" / f"{PACKAGE_NAME}.receipt.json"
FINAL_REPORT = (
    ROOT / f"docs/reports/DG-10-final-completion-audit-candidate.2-{DATE}.json"
)
SOL_BUNDLE = (
    ROOT.parent
    / "evidence/dg10-sol-final-review/sha256-c0fc636513a423e3826c27e9029406a8c935e46ef65e40eda858f455a21301de"
)
TIER2_SAFE_ROOT = (
    ROOT.parent
    / "evidence/dg10-tier2-blinded-audit/dg10-tier2-blind-2026-08-22-2c275e5ab704"
)
TIER2_SAFE_FILES = (
    "blind-package.json",
    "conflict-adjudication-template.json",
    "independent-annotation-template.json",
    "package-index.json",
)
EXCLUDED_CLASSES = (
    ".env, credentials, tokens, DSNs, billing material, sockets and service routes",
    "repository-external raw benchmark prompts, memories, labels and model-output sidecars",
    "Tier-2 evidence-reveal-package.json and randomization-manifest.json",
    "Runtime/PostgreSQL/OpenWorker/vLLM state, images, databases and container filesystems",
    "external-provider evidence for the parked OE-F06 lane",
)


class PackageError(RuntimeError):
    pass


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _safe_relative(path: str) -> str:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        raise PackageError(f"unsafe package path: {path}")
    return parsed.as_posix()


def _add_file(
    payload: dict[str, tuple[bytes, str]],
    source: Path,
    package_path: str,
    source_class: str,
) -> None:
    if not source.is_file() or source.is_symlink():
        raise PackageError(f"missing or unsafe source: {source}")
    package_path = _safe_relative(package_path)
    if package_path in payload:
        raise PackageError(f"duplicate package path: {package_path}")
    payload[package_path] = (source.read_bytes(), source_class)


def _add_tree(
    payload: dict[str, tuple[bytes, str]],
    source: Path,
    package_prefix: str,
    source_class: str,
) -> None:
    if not source.is_dir() or source.is_symlink():
        raise PackageError(f"missing or unsafe source tree: {source}")
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise PackageError(f"source tree contains symlink: {path}")
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            _add_file(
                payload,
                path,
                f"{package_prefix.rstrip('/')}/{relative}",
                source_class,
            )


def collect_payload() -> dict[str, tuple[bytes, str]]:
    payload: dict[str, tuple[bytes, str]] = {}
    patterns = (
        ("docs/reports/DG-10-*", "repo-reports"),
        ("docs/reviews/DG-10-*", "repo-reviews"),
        ("docs/contracts/DG-10-*", "repo-contracts"),
    )
    for pattern, source_class in patterns:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                _add_file(
                    payload,
                    path,
                    f"repo/{path.relative_to(ROOT).as_posix()}",
                    source_class,
                )
    fixed_repo_files = (
        "MiLAi_真实Provider验证与MCP_Agent接入_GOALS.md",
        "codex_sol_max.md",
        "docs/adr/ADR-023-self-hosted-vllm-validation-lane.md",
        "docs/runbooks/provider-mcp-agent.md",
        "docs/reviews/prompts/dg10-independent-review.md",
        "docs/reviews/schemas/dg10-review.schema.json",
        "scripts/package_dg10_results.py",
    )
    for relative in fixed_repo_files:
        _add_file(
            payload,
            ROOT / relative,
            f"repo/{relative}",
            "repo-context",
        )
    _add_tree(
        payload,
        SOL_BUNDLE,
        "audit/frozen-sol-review-bundle",
        "frozen-sol-review-bundle",
    )
    review_output = Path("/review-output/DG10")
    _add_tree(
        payload,
        review_output,
        "audit/sol-review-output",
        "sol-review-output",
    )
    for candidate in ("candidate.1-2026-08-22", "candidate.2-2026-08-22"):
        verification = ROOT.parent / "evidence/dg10-final-verification" / candidate
        _add_tree(
            payload,
            verification,
            f"verification/{candidate}",
            "final-verification-logs",
        )
    for name in TIER2_SAFE_FILES:
        _add_file(
            payload,
            TIER2_SAFE_ROOT / name,
            f"tier2-blind-safe/{name}",
            "tier2-blind-safe-no-reveal",
        )
    if not any(path.endswith("DG-10-final-completion-audit-candidate.2-2026-08-22.json") for path in payload):
        raise PackageError("final completion report is absent from package")
    return payload


def _readme(payload_count: int) -> bytes:
    text = f"""# DG-10 experiment results package

Package: `{PACKAGE_NAME}`

Final decision: **NO-GO — release stopped**.

This portable, local-only package contains {payload_count} experiment/report artifacts:

- DG-10 reports, reviews, contracts, ADR and runbook;
- the immutable Sol review bundle and schema-valid Sol output/events;
- final pytest/ruff verification logs, including the disclosed worker-environment closure failures;
- the Tier-2 blind package and annotation templates without the reveal or randomization mapping.

Start with:

1. `repo/docs/reports/DG-10-final-completion-audit-candidate.2-2026-08-22.json`
2. `repo/docs/reviews/DG-10-sol-final-audit-disposition-candidate.1-2026-08-22.json`
3. `repo/docs/contracts/DG-10-claim-matrix.yaml`
4. `repo/docs/reports/DG-10-current-byte-inventory-candidate.2.13-2026-08-22.json`

The full benchmark test was denied and not run; test labels/outputs remain reported unopened.
The package is not production acceptance, human approval, a public release, or authorization to
redistribute upstream Worker/model/dataset assets. Verify `SHA256SUMS` before use.
"""
    return text.encode()


def _manifest(payload: dict[str, tuple[bytes, str]]) -> bytes:
    class_counts = Counter(source_class for _, source_class in payload.values())
    entries = [
        {
            "path": path,
            "size": len(raw),
            "sha256": _sha256(raw),
            "source_class": source_class,
        }
        for path, (raw, source_class) in sorted(payload.items())
    ]
    value: dict[str, Any] = {
        "schema": "milai.dg10.experiment-results-package-manifest.v1",
        "date": DATE,
        "package": PACKAGE_NAME,
        "status": "PORTABLE_LOCAL_ONLY_NO_GO_RESULTS_PACKAGE",
        "final_decision": "NO_GO_RELEASE_STOPPED",
        "payload_entry_count": len(entries),
        "source_class_counts": dict(sorted(class_counts.items())),
        "excluded_classes": list(EXCLUDED_CLASSES),
        "tier2_reveal_included": False,
        "raw_benchmark_sidecars_included": False,
        "credentials_or_secrets_included": False,
        "entries": entries,
    }
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _sha256sums(files: dict[str, bytes]) -> bytes:
    return "".join(
        f"{_sha256(raw)}  {path}\n" for path, raw in sorted(files.items())
    ).encode()


def _archive(files: dict[str, bytes]) -> bytes:
    raw = io.BytesIO()
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as archive,
    ):
        for relative, data in sorted(files.items()):
            member = tarfile.TarInfo(f"{PACKAGE_NAME}/{_safe_relative(relative)}")
            member.size = len(data)
            member.mode = 0o600
            member.uid = 0
            member.gid = 0
            member.uname = "root"
            member.gname = "root"
            member.mtime = 0
            archive.addfile(member, io.BytesIO(data))
    return raw.getvalue()


def _verify_archive(raw: bytes, expected: dict[str, bytes]) -> None:
    seen: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.issym() or member.islnk():
                raise PackageError("archive contains non-regular member")
            prefix = f"{PACKAGE_NAME}/"
            if not member.name.startswith(prefix):
                raise PackageError("archive root drift")
            relative = _safe_relative(member.name.removeprefix(prefix))
            stream = archive.extractfile(member)
            if stream is None or relative in seen:
                raise PackageError("archive member extraction drift")
            seen[relative] = stream.read()
    if seen != expected:
        raise PackageError("archive byte round-trip drift")


def package(archive_path: Path, receipt_path: Path, secret_source: Path) -> dict[str, Any]:
    if archive_path.exists() or receipt_path.exists():
        raise PackageError("refusing to overwrite an existing package or receipt")
    payload = collect_payload()
    controls = {
        "README.md": _readme(len(payload)),
        "MANIFEST.json": _manifest(payload),
    }
    all_without_sums = {
        **{path: raw for path, (raw, _) in payload.items()},
        **controls,
    }
    files = {**all_without_sums, "SHA256SUMS": _sha256sums(all_without_sums)}
    secret_values = _secrets(secret_source)
    matches = [
        path for path, raw in files.items() if any(secret in raw for secret in secret_values)
    ]
    if matches:
        raise PackageError("exact secret value found in package input")
    archive_raw = _archive(files)
    _verify_archive(archive_raw, files)
    _atomic_write(archive_path, archive_raw)
    receipt = {
        "schema": "milai.dg10.experiment-results-package-receipt.v1",
        "date": DATE,
        "package": PACKAGE_NAME,
        "status": "PASS_PORTABLE_LOCAL_ONLY_NO_GO_RESULTS_PACKAGE",
        "archive_path": archive_path.relative_to(ROOT).as_posix(),
        "archive_sha256": _sha256(archive_raw),
        "archive_size": len(archive_raw),
        "archive_member_count": len(files),
        "payload_entry_count": len(payload),
        "manifest_sha256": _sha256(controls["MANIFEST.json"]),
        "sha256sums_sha256": _sha256(files["SHA256SUMS"]),
        "final_report_sha256": _sha256(FINAL_REPORT.read_bytes()),
        "secret_scan": {
            "status": "PASS",
            "exact_secret_value_count": len(secret_values),
            "matching_members": [],
        },
        "archive_safety": {
            "regular_files_only": True,
            "symlinks": 0,
            "hardlinks": 0,
            "unsafe_paths": 0,
            "round_trip_byte_validation": "PASS",
        },
        "excluded_classes": list(EXCLUDED_CLASSES),
        "distribution": "LOCAL_ONLY_NOT_PUBLIC_RELEASE",
        "final_decision": "NO_GO_RELEASE_STOPPED",
    }
    _atomic_write(
        receipt_path,
        (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description="Package DG-10 experiment results")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--secret-source", type=Path, default=ROOT / "runtime/.env")
    args = parser.parse_args()
    receipt = package(
        args.archive.resolve(), args.receipt.resolve(), args.secret_source.resolve()
    )
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
