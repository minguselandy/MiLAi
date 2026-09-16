from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import dg13u_u1_bundle as bundle

CASE_ID = "U1-SYNTHETIC"
RUN_ID = "dg13u-u1-synthetic-001"
ARTIFACT_SCHEMA = "milai.dg13u.u1-run-manifest.v1"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(autouse=True)
def _small_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle, "REQUIRED_CASE_IDS", (CASE_ID,))
    monkeypatch.setattr(
        bundle,
        "REQUIRED_ARTIFACT_SCHEMAS",
        {"manifest.json": ARTIFACT_SCHEMA},
    )


def _inputs(root: Path, *, case_id: str = CASE_ID) -> tuple[Path, Path, Path, Path]:
    run_dir = root / "run"
    run_dir.mkdir(parents=True)
    artifact_path = run_dir / "manifest.json"
    artifact_raw = _canonical(
        {
            "schema": ARTIFACT_SCHEMA,
            "run_id": RUN_ID,
            "case_id": case_id,
            "status": "PASS",
        }
    )
    artifact_path.write_bytes(artifact_raw)
    report_path = run_dir / "report.json"
    report_raw = _canonical(
        {
            "schema": bundle.REPORT_SCHEMA,
            "run_id": RUN_ID,
            "case_id": case_id,
            "status": "PASS",
            "artifacts": [
                {
                    "path": "manifest.json",
                    "sha256": _sha(artifact_raw),
                    "bytes": len(artifact_raw),
                }
            ],
        }
    )
    report_path.write_bytes(report_raw)
    aggregate_path = root / "aggregate.json"
    aggregate_path.write_bytes(
        _canonical(
            {
                "schema": bundle.AGGREGATE_SCHEMA,
                "status": "PASS",
                "product_usable": True,
                "release_label": bundle.RELEASE_LABEL,
                "release_label_earned": True,
                "matrix": {
                    "required": 1,
                    "observed": 1,
                    "missing_case_ids": [],
                    "unexpected_case_ids": [],
                    "status": "PASS",
                },
                "gates": {
                    name: {
                        "status": "PASS",
                        "intrinsic_status": "PASS",
                        "reason_code": f"SYNTHETIC_{name}",
                    }
                    for name in bundle.GATE_NAMES
                },
                "inputs": [
                    {
                        "case_id": case_id,
                        "run_id": RUN_ID,
                        "report_path": str(report_path),
                        "report_sha256": _sha(report_raw),
                    }
                ],
            }
        )
    )
    supplemental = root / "goal-objective.md"
    supplemental.write_text("Synthetic review objective without credentials.\n")
    return aggregate_path, report_path, artifact_path, supplemental


def _test_gate_receipt(root: Path) -> tuple[Path, list[Path]]:
    source_root = root / "source-root"
    sources = [
        source_root / "sources/a.py",
        source_root / "sources/config.json",
        source_root / "sources/z.txt",
    ]
    sources[0].parent.mkdir(parents=True)
    sources[0].write_text("VALUE = 1\n")
    sources[1].write_text('{"enabled":true}\n')
    sources[2].write_text("synthetic test-gate input\n")
    rows = [
        {
            "path": source.relative_to(source_root).as_posix(),
            "bytes": len(source.read_bytes()),
            "sha256": _sha(source.read_bytes()),
        }
        for source in sources
    ]
    receipt = root / "receipt.json"
    receipt.write_bytes(
        _canonical(
            {
                "schema": bundle.TEST_GATE_RECEIPT_SCHEMA,
                "status": "PASS",
                "run_id": "dg13u-u1-test-gate-synthetic",
                "execution_scope": "FIXED_UNIT_AND_OWNING_TESTS_ONLY",
                "u1_top_level_file_count": 26,
                "source_input_count": len(rows),
                "source_inputs_sha256": _sha(_canonical(rows)),
                "source_inputs": rows,
                "source_revalidation": {
                    "status": "PASS",
                    "post_source_inputs_sha256": _sha(_canonical(rows)),
                },
                "commands": [
                    {
                        "name": name,
                        "status": "PASS",
                        "file_count": file_count,
                        "attempt": 1,
                        "automatic_retries": 0,
                    }
                    for name, file_count in (
                        ("u1-top-level-26-plus-u0-support", 27),
                        ("python-client", 10),
                        ("openworker-integration", 8),
                    )
                ],
                "summary": {
                    "commands_planned": 3,
                    "commands_executed": 3,
                    "commands_passed": 3,
                    "commands_failed": 0,
                    "commands_not_executed": 0,
                    "attempts_per_command_maximum": 1,
                    "automatic_retries": 0,
                },
                "setup_error_reason": None,
                "setup_error_type_sha256": None,
                "raw_stdout_stderr_persisted": False,
                "temporary_storage": {
                    "kind": "RUN_OWNED_EPHEMERAL_ROOT",
                    "path_sha256": "a" * 64,
                    "cleanup_status": "PASS",
                    "exists_after_cleanup": False,
                },
            }
        )
    )
    return receipt, sources


def _rewrite_test_gate_receipt(
    receipt: Path, mutation: str, sources: list[Path]
) -> None:
    document = json.loads(receipt.read_text())
    rows = document["source_inputs"]
    if mutation == "schema":
        document["schema"] = "milai.dg13u.u1-test-gate-receipt.v0"
    elif mutation == "scope":
        document["execution_scope"] = "UNFROZEN_TESTS"
    elif mutation == "status":
        document["status"] = "FAIL"
    elif mutation == "suite-count":
        document["commands"].pop()
    elif mutation == "suite-name":
        document["commands"][0]["name"] = "u1-top-level"
    elif mutation == "suite-status":
        document["commands"][0]["status"] = "FAIL"
    elif mutation == "attempt":
        document["commands"][0]["attempt"] = 2
    elif mutation == "retry":
        document["commands"][0]["automatic_retries"] = 1
    elif mutation == "summary-count":
        document["summary"]["commands_passed"] = 2
    elif mutation == "source-count":
        document["source_input_count"] += 1
    elif mutation == "source-hash":
        rows[0]["sha256"] = "b" * 64
        document["source_inputs_sha256"] = _sha(_canonical(rows))
    elif mutation == "aggregate-hash":
        document["source_inputs_sha256"] = "b" * 64
    elif mutation == "revalidation-status":
        document["source_revalidation"]["status"] = "FAIL"
    elif mutation == "revalidation-hash":
        document["source_revalidation"]["post_source_inputs_sha256"] = "b" * 64
    elif mutation == "source-order":
        rows.reverse()
        document["source_inputs_sha256"] = _sha(_canonical(rows))
    elif mutation == "duplicate-source":
        rows[1] = dict(rows[0])
        document["source_inputs_sha256"] = _sha(_canonical(rows))
    elif mutation == "uppercase-hash":
        rows[0]["sha256"] = rows[0]["sha256"].upper()
        document["source_inputs_sha256"] = _sha(_canonical(rows))
    elif mutation == "source-bytes":
        rows[0]["bytes"] += 1
        document["source_inputs_sha256"] = _sha(_canonical(rows))
    elif mutation == "cleanup-status":
        document["temporary_storage"]["cleanup_status"] = "FAIL"
    elif mutation == "cleanup-present":
        document["temporary_storage"]["exists_after_cleanup"] = True
    elif mutation == "missing-source":
        sources.pop()
    else:  # pragma: no cover - test table exhaustiveness
        raise AssertionError(mutation)
    if mutation in {
        "source-hash",
        "source-order",
        "duplicate-source",
        "uppercase-hash",
        "source-bytes",
    }:
        document["source_revalidation"]["post_source_inputs_sha256"] = document[
            "source_inputs_sha256"
        ]
    receipt.write_bytes(_canonical(document))


def _append_indexed_artifact(
    aggregate: Path,
    report: Path,
    relative_path: str,
    document: dict[str, object],
) -> Path:
    artifact = report.parent / relative_path
    raw = _canonical(document)
    artifact.write_bytes(raw)
    report_document = json.loads(report.read_text())
    report_document["artifacts"].append(
        {
            "path": relative_path,
            "sha256": _sha(raw),
            "bytes": len(raw),
        }
    )
    report.write_bytes(_canonical(report_document))
    aggregate_document = json.loads(aggregate.read_text())
    aggregate_document["inputs"][0]["report_sha256"] = _sha(report.read_bytes())
    aggregate.write_bytes(_canonical(aggregate_document))
    return artifact


def _append_binary_indexed_artifact(
    aggregate: Path,
    report: Path,
    relative_path: str,
    raw: bytes,
) -> Path:
    artifact = report.parent / relative_path
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(raw)
    report_document = json.loads(report.read_text())
    report_document["artifacts"].append(
        {
            "path": relative_path,
            "sha256": _sha(raw),
            "bytes": len(raw),
        }
    )
    report.write_bytes(_canonical(report_document))
    aggregate_document = json.loads(aggregate.read_text())
    aggregate_document["inputs"][0]["report_sha256"] = _sha(report.read_bytes())
    aggregate.write_bytes(_canonical(aggregate_document))
    return artifact


def _zip_bytes(
    members: list[tuple[str, bytes, int]],
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw, mode in members:
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            archive.writestr(info, raw)
    return output.getvalue()


def _tar_gz_bytes(
    members: list[tuple[str, bytes, int, bytes | None]],
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, raw, mode, link_target in members:
            info = tarfile.TarInfo(name)
            info.mode = mode
            if link_target is None:
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            else:
                info.type = tarfile.SYMTYPE
                info.linkname = link_target.decode()
                archive.addfile(info)
    return output.getvalue()


def test_packages_explicit_bound_inputs_as_atomic_private_directory(
    tmp_path: Path,
) -> None:
    aggregate, report, artifact, supplemental = _inputs(tmp_path / "inputs")
    first = tmp_path / "bundle-a"
    second = tmp_path / "bundle-b"

    first_result = bundle.package_bundle(
        aggregate,
        [report],
        [artifact, supplemental],
        first,
    )
    second_result = bundle.package_bundle(
        aggregate,
        [report],
        [supplemental, artifact],
        second,
    )

    assert first_result["manifest_sha256"] == second_result["manifest_sha256"]
    assert (first / "manifest.json").read_bytes() == (
        second / "manifest.json"
    ).read_bytes()
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["schema"] == bundle.BUNDLE_SCHEMA
    assert manifest["status"] == "PASS"
    assert manifest["gates"] == {name: "PASS" for name in bundle.GATE_NAMES}
    assert manifest["input_mode"] == "EXPLICIT_PATHS_ONLY_NO_DISCOVERY"
    assert manifest["counts"] == {
        "aggregate": 1,
        "reports": 1,
        "run_artifacts": 1,
        "supplemental_artifacts": 1,
    }
    assert manifest["entries_sha256"] == _sha(_canonical(manifest["files"]))
    assert stat.S_IMODE(first.stat().st_mode) == 0o555
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o444
        for path in first.rglob("*")
        if path.is_file()
    )
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o555
        for path in first.rglob("*")
        if path.is_dir()
    )
    assert (first / "aggregate/aggregate.json").read_bytes() == aggregate.read_bytes()
    assert (
        first / f"reports/{CASE_ID}--{RUN_ID}.json"
    ).read_bytes() == report.read_bytes()


def test_test_gate_receipt_closes_over_explicit_source_inputs(
    tmp_path: Path,
) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    receipt, sources = _test_gate_receipt(tmp_path / "test-gate")
    output = tmp_path / "bundle"

    bundle.package_bundle(
        aggregate,
        [report],
        [artifact, receipt, *sources],
        output,
    )

    manifest = json.loads((output / "manifest.json").read_text())
    source_entries = {
        row["path"]: row
        for row in manifest["files"]
        if row["source_kind"] == "TEST_GATE_SOURCE"
    }
    assert set(source_entries) == {
        "test-gate-sources/sources/a.py",
        "test-gate-sources/sources/config.json",
        "test-gate-sources/sources/z.txt",
    }
    for source in sources:
        logical_path = f"test-gate-sources/sources/{source.name}"
        assert (output / logical_path).read_bytes() == source.read_bytes()
        assert source_entries[logical_path]["sha256"] == _sha(source.read_bytes())
        assert source_entries[logical_path]["bytes"] == len(source.read_bytes())


@pytest.mark.parametrize(
    "mutation",
    (
        "schema",
        "scope",
        "status",
        "suite-count",
        "suite-name",
        "suite-status",
        "attempt",
        "retry",
        "summary-count",
        "source-count",
        "source-hash",
        "aggregate-hash",
        "revalidation-status",
        "revalidation-hash",
        "source-order",
        "duplicate-source",
        "uppercase-hash",
        "source-bytes",
        "cleanup-status",
        "cleanup-present",
        "missing-source",
    ),
)
def test_test_gate_receipt_tampering_fails_closed(
    tmp_path: Path, mutation: str
) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    receipt, sources = _test_gate_receipt(tmp_path / "test-gate")
    _rewrite_test_gate_receipt(receipt, mutation, sources)

    with pytest.raises(bundle.BundleError):
        bundle.package_bundle(
            aggregate,
            [report],
            [artifact, receipt, *sources],
            tmp_path / "bundle",
        )


def test_packages_real_binary_wheel_and_nested_wheel_tar_gz(
    tmp_path: Path,
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    wheel_raw = _zip_bytes(
        [
            ("synthetic/__init__.py", b"VALUE = 1\n", 0o644),
            ("synthetic/native-extension.so", b"\x7fELF\x00\xff\x01binary", 0o644),
            (
                "synthetic-1.0.dist-info/METADATA",
                b"Metadata-Version: 2.3\nName: synthetic\nVersion: 1.0\n",
                0o664,
            ),
        ]
    )
    tar_raw = _tar_gz_bytes(
        [
            ("synthetic-1.0/README.md", b"Synthetic source archive.\n", 0o644, None),
            ("synthetic-1.0/wheelhouse/synthetic.whl", wheel_raw, 0o644, None),
        ]
    )
    wheel = _append_binary_indexed_artifact(
        aggregate, report, "packages/synthetic.whl", wheel_raw
    )
    source = _append_binary_indexed_artifact(
        aggregate, report, "packages/synthetic.tar.gz", tar_raw
    )

    result = bundle.package_bundle(
        aggregate,
        [report],
        [manifest, wheel, source],
        tmp_path / "bundle",
    )

    bundled_manifest = json.loads((tmp_path / "bundle/manifest.json").read_text())
    assert result["status"] == "PASS"
    assert bundled_manifest["secret_scan"]["archive_members_scanned"] >= 7
    assert bundled_manifest["secret_scan"]["archive_uncompressed_bytes"] > len(
        wheel_raw
    )
    assert (
        tmp_path / "bundle/runs" / f"{CASE_ID}--{RUN_ID}" / "packages/synthetic.whl"
    ).read_bytes() == wheel_raw
    assert (
        tmp_path / "bundle/runs" / f"{CASE_ID}--{RUN_ID}" / "packages/synthetic.tar.gz"
    ).read_bytes() == tar_raw


def test_archive_source_placeholders_and_opaque_native_bytes_are_not_credentials(
    tmp_path: Path,
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    wheel_raw = _zip_bytes(
        [
            (
                "synthetic/test_fixture.py",
                (
                    b'AUTH = "Authorization: Bearer do-not-store"\n'
                    b'READER = "reader-token"\n'
                ),
                0o644,
            ),
            (
                "synthetic/config.json",
                _canonical(
                    {
                        "apiKey": "${OPENWORKER_KEY}",
                        "properties": {"password": {"type": "string"}},
                    }
                ),
                0o644,
            ),
            (
                "synthetic/native-extension.so",
                b"\x7fELF\x00\xffsk_abcdefghijklmnopqrst\x00",
                0o644,
            ),
        ]
    )
    wheel = _append_binary_indexed_artifact(
        aggregate, report, "packages/synthetic.whl", wheel_raw
    )

    result = bundle.package_bundle(
        aggregate,
        [report],
        [manifest, wheel],
        tmp_path / "bundle",
    )

    assert result["status"] == "PASS"


@pytest.mark.parametrize(
    "member_raw",
    [
        b"Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345\n",
        (
            b"-----BEGIN PRIVATE KEY-----\n"
            + b"QUFB" * 12
            + b"\n-----END PRIVATE KEY-----\n"
        ),
    ],
)
def test_rejects_obvious_credential_in_archive_text_member(
    tmp_path: Path, member_raw: bytes
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    raw = _zip_bytes([("synthetic/credential.txt", member_raw, 0o644)])
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.whl", raw
    )

    with pytest.raises(bundle.BundleError, match="SECRET_LIKE_CONTENT"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


def test_rejects_private_key_block_in_opaque_binary_member(tmp_path: Path) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    private_key = (
        b"\xff\x00-----BEGIN PRIVATE KEY-----\n"
        + b"QUFB" * 12
        + b"\n-----END PRIVATE KEY-----\n"
    )
    raw = _zip_bytes([("synthetic/native.so", private_key, 0o644)])
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.whl", raw
    )

    with pytest.raises(bundle.BundleError, match="SECRET_LIKE_CONTENT"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


@pytest.mark.parametrize(
    ("name", "raw"),
    [("invalid.whl", b"not a zip"), ("invalid.tar.gz", b"not a tar")],
)
def test_rejects_malformed_archive(tmp_path: Path, name: str, raw: bytes) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    archive = _append_binary_indexed_artifact(
        aggregate, report, f"packages/{name}", raw
    )

    with pytest.raises(bundle.BundleError, match="archive content is invalid"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


def test_rejects_duplicate_archive_member_path(tmp_path: Path) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive_file:
        archive_file.writestr("synthetic/value.txt", b"first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive_file.writestr("synthetic/value.txt", b"second")
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.whl", output.getvalue()
    )

    with pytest.raises(bundle.BundleError, match="duplicate archive member path"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


@pytest.mark.parametrize("archive_kind", ["wheel", "tar"])
def test_rejects_archive_member_path_escape(tmp_path: Path, archive_kind: str) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    if archive_kind == "wheel":
        raw = _zip_bytes([("../outside.txt", b"escape", 0o644)])
        name = "unsafe.whl"
    else:
        raw = _tar_gz_bytes([("../outside.txt", b"escape", 0o644, None)])
        name = "unsafe.tar.gz"
    archive = _append_binary_indexed_artifact(
        aggregate, report, f"packages/{name}", raw
    )

    with pytest.raises(bundle.BundleError, match="archive member path"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


@pytest.mark.parametrize("archive_kind", ["wheel", "tar"])
def test_rejects_archive_symlink_member(tmp_path: Path, archive_kind: str) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    if archive_kind == "wheel":
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive_file:
            info = zipfile.ZipInfo("synthetic/link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive_file.writestr(info, b"../../outside")
        raw = output.getvalue()
        name = "unsafe.whl"
    else:
        raw = _tar_gz_bytes([("synthetic/link", b"", 0o777, b"../../outside")])
        name = "unsafe.tar.gz"
    archive = _append_binary_indexed_artifact(
        aggregate, report, f"packages/{name}", raw
    )

    with pytest.raises(bundle.BundleError, match="archive member type"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


def test_rejects_secret_in_nested_wheel_member(tmp_path: Path) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    nested = _zip_bytes(
        [
            (
                "synthetic/settings.json",
                b'{"access_token":"raw-private-token-value"}\n',
                0o644,
            )
        ]
    )
    raw = _tar_gz_bytes(
        [("synthetic-1.0/wheelhouse/synthetic.whl", nested, 0o644, None)]
    )
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.tar.gz", raw
    )

    with pytest.raises(bundle.BundleError, match="SECRET_LIKE_CONTENT"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


def test_rejects_archive_member_over_size_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    monkeypatch.setattr(bundle, "_MAX_ARCHIVE_MEMBER_BYTES", 8)
    raw = _zip_bytes([("synthetic/large.bin", b"123456789", 0o644)])
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.whl", raw
    )

    with pytest.raises(bundle.BundleError, match="archive member size"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


def test_rejects_archive_member_count_over_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    monkeypatch.setattr(bundle, "_MAX_ARCHIVE_MEMBERS", 1)
    raw = _zip_bytes(
        [("synthetic/one.txt", b"one", 0o644), ("synthetic/two.txt", b"two", 0o644)]
    )
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.whl", raw
    )

    with pytest.raises(bundle.BundleError, match="archive member count"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


def test_rejects_archive_total_uncompressed_size_over_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    monkeypatch.setattr(bundle, "_MAX_ARCHIVE_UNCOMPRESSED_BYTES", 5)
    raw = _zip_bytes(
        [("synthetic/one.txt", b"one", 0o644), ("synthetic/two.txt", b"two", 0o644)]
    )
    archive = _append_binary_indexed_artifact(
        aggregate, report, "packages/unsafe.whl", raw
    )

    with pytest.raises(bundle.BundleError, match="archive uncompressed size"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


@pytest.mark.parametrize("archive_kind", ["wheel", "tar"])
@pytest.mark.parametrize("mode", [0o666, 0o4644])
def test_rejects_unsafe_archive_member_mode(
    tmp_path: Path, archive_kind: str, mode: int
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    if archive_kind == "wheel":
        raw = _zip_bytes([("synthetic/unsafe.py", b"VALUE = 1\n", mode)])
        name = "unsafe.whl"
    else:
        raw = _tar_gz_bytes([("synthetic/unsafe.py", b"VALUE = 1\n", mode, None)])
        name = "unsafe.tar.gz"
    archive = _append_binary_indexed_artifact(
        aggregate, report, f"packages/{name}", raw
    )

    with pytest.raises(bundle.BundleError, match="archive member mode"):
        bundle.package_bundle(
            aggregate, [report], [manifest, archive], tmp_path / "bundle"
        )


@pytest.mark.parametrize("gate", bundle.GATE_NAMES)
def test_rejects_each_nonpass_gate_before_output(tmp_path: Path, gate: str) -> None:
    aggregate, report, artifact, supplemental = _inputs(tmp_path / "inputs")
    document = json.loads(aggregate.read_text())
    document["gates"][gate]["status"] = "FAIL"
    aggregate.write_bytes(_canonical(document))
    output = tmp_path / "bundle"

    with pytest.raises(bundle.BundleError, match=f"{gate} must be PASS"):
        bundle.package_bundle(aggregate, [report], [artifact, supplemental], output)

    assert not output.exists()


@pytest.mark.parametrize("drift", ["sha256", "bytes", "schema"])
def test_rejects_artifact_binding_drift(tmp_path: Path, drift: str) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    if drift == "schema":
        document = json.loads(artifact.read_text())
        document["schema"] = "milai.wrong.v1"
        artifact.write_bytes(_canonical(document))
        report_document = json.loads(report.read_text())
        report_document["artifacts"][0]["sha256"] = _sha(artifact.read_bytes())
        report_document["artifacts"][0]["bytes"] = artifact.stat().st_size
        report.write_bytes(_canonical(report_document))
        aggregate_document = json.loads(aggregate.read_text())
        aggregate_document["inputs"][0]["report_sha256"] = _sha(report.read_bytes())
        aggregate.write_bytes(_canonical(aggregate_document))
    else:
        document = json.loads(report.read_text())
        document["artifacts"][0][drift] = (
            "0" * 64 if drift == "sha256" else document["artifacts"][0][drift] + 1
        )
        report.write_bytes(_canonical(document))
        aggregate_document = json.loads(aggregate.read_text())
        aggregate_document["inputs"][0]["report_sha256"] = _sha(report.read_bytes())
        aggregate.write_bytes(_canonical(aggregate_document))

    with pytest.raises(bundle.BundleError, match=drift.upper()):
        bundle.package_bundle(aggregate, [report], [artifact], tmp_path / "bundle")


def test_rejects_missing_indexed_artifact(tmp_path: Path) -> None:
    aggregate, report, _artifact, _supplemental = _inputs(tmp_path / "inputs")
    with pytest.raises(bundle.BundleError, match="explicit artifact set is incomplete"):
        bundle.package_bundle(aggregate, [report], [], tmp_path / "bundle")


def test_recovery_plan_uses_aggregate_schema_and_run_identity_exemption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    recovery_schema = "milai.dg13u.u1-recovery-resource-plan.v1"
    monkeypatch.setattr(
        bundle,
        "REQUIRED_ARTIFACT_SCHEMAS",
        {
            "manifest.json": ARTIFACT_SCHEMA,
            "recovery-resource-plan.json": recovery_schema,
        },
    )
    recovery = _append_indexed_artifact(
        aggregate,
        report,
        "recovery-resource-plan.json",
        {
            "schema": recovery_schema,
            "run_id": RUN_ID,
            "resources": [],
        },
    )

    result = bundle.package_bundle(
        aggregate,
        [report],
        [manifest, recovery],
        tmp_path / "bundle",
    )

    assert result["status"] == "PASS"


def test_recovery_plan_still_rejects_wrong_run_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, manifest, _supplemental = _inputs(tmp_path / "inputs")
    recovery_schema = "milai.dg13u.u1-recovery-resource-plan.v1"
    monkeypatch.setattr(
        bundle,
        "REQUIRED_ARTIFACT_SCHEMAS",
        {
            "manifest.json": ARTIFACT_SCHEMA,
            "recovery-resource-plan.json": recovery_schema,
        },
    )
    recovery = _append_indexed_artifact(
        aggregate,
        report,
        "recovery-resource-plan.json",
        {
            "schema": recovery_schema,
            "run_id": "dg13u-u1-wrong-run-001",
            "resources": [],
        },
    )

    with pytest.raises(bundle.BundleError, match="identity binding mismatch"):
        bundle.package_bundle(
            aggregate,
            [report],
            [manifest, recovery],
            tmp_path / "bundle",
        )


@pytest.mark.parametrize(
    "case_id",
    [
        "U1-PROVIDER-DOWN",
        "U1-PROVIDER-MALFORMED",
        "U1-PROVIDER-TIMEOUT",
    ],
)
def test_accepts_expected_provider_fault_typed_error_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case_id: str
) -> None:
    monkeypatch.setattr(bundle, "REQUIRED_CASE_IDS", (case_id,))
    aggregate, report, manifest, _supplemental = _inputs(
        tmp_path / "inputs", case_id=case_id
    )
    diagnostic = _append_indexed_artifact(
        aggregate,
        report,
        "smoke-command-diagnostic.json",
        {
            "schema": "milai.dg13u.u1-smoke-command-diagnostic.v1",
            "run_id": RUN_ID,
            "case_id": case_id,
            "stage": "OPENCODE_RUN",
            "status": "FAIL",
            "reason_code": "OPENCODE_TYPED_ERROR",
            "exit_code": 0,
            "typed_error_count": 1,
        },
    )

    result = bundle.package_bundle(
        aggregate,
        [report],
        [manifest, diagnostic],
        tmp_path / "bundle",
    )

    assert result["status"] == "PASS"


@pytest.mark.parametrize(
    ("case_id", "typed_error_count", "reason_code"),
    [
        pytest.param(CASE_ID, 1, "OPENCODE_TYPED_ERROR", id="non-provider-case"),
        pytest.param(
            "U1-PROVIDER-DOWN", 0, "OPENCODE_TYPED_ERROR", id="missing-typed-error"
        ),
        pytest.param(
            "U1-PROVIDER-DOWN", True, "OPENCODE_TYPED_ERROR", id="boolean-count"
        ),
        pytest.param(
            "U1-PROVIDER-TIMEOUT", 1, "OPENCODE_EXIT_NONZERO", id="wrong-reason"
        ),
    ],
)
def test_rejects_non_expected_failed_smoke_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case_id: str,
    typed_error_count: int,
    reason_code: str,
) -> None:
    monkeypatch.setattr(bundle, "REQUIRED_CASE_IDS", (case_id,))
    aggregate, report, manifest, _supplemental = _inputs(
        tmp_path / "inputs", case_id=case_id
    )
    diagnostic = _append_indexed_artifact(
        aggregate,
        report,
        "smoke-command-diagnostic.json",
        {
            "schema": "milai.dg13u.u1-smoke-command-diagnostic.v1",
            "run_id": RUN_ID,
            "case_id": case_id,
            "stage": "OPENCODE_RUN",
            "status": "FAIL",
            "reason_code": reason_code,
            "exit_code": 0,
            "typed_error_count": typed_error_count,
        },
    )

    with pytest.raises(bundle.BundleError, match="status binding mismatch"):
        bundle.package_bundle(
            aggregate,
            [report],
            [manifest, diagnostic],
            tmp_path / "bundle",
        )


def test_rejects_aggregate_report_path_binding_drift(tmp_path: Path) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    document = json.loads(aggregate.read_text())
    document["inputs"][0]["report_path"] = str(tmp_path / "different-report.json")
    aggregate.write_bytes(_canonical(document))

    with pytest.raises(bundle.BundleError, match="report path binding mismatch"):
        bundle.package_bundle(aggregate, [report], [artifact], tmp_path / "bundle")


def test_rejects_report_artifact_path_escape_even_when_file_is_explicit(
    tmp_path: Path,
) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    outside = report.parent.parent / "outside.json"
    artifact.rename(outside)
    report_document = json.loads(report.read_text())
    report_document["artifacts"][0]["path"] = "../outside.json"
    report_document["artifacts"][0]["sha256"] = _sha(outside.read_bytes())
    report.write_bytes(_canonical(report_document))
    aggregate_document = json.loads(aggregate.read_text())
    aggregate_document["inputs"][0]["report_sha256"] = _sha(report.read_bytes())
    aggregate.write_bytes(_canonical(aggregate_document))

    with pytest.raises(bundle.BundleError, match="path escapes its report directory"):
        bundle.package_bundle(aggregate, [report], [outside], tmp_path / "bundle")


def test_rejects_report_identity_that_could_escape_bundle_path(tmp_path: Path) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    report_document = json.loads(report.read_text())
    report_document["run_id"] = "../escaped"
    report.write_bytes(_canonical(report_document))
    aggregate_document = json.loads(aggregate.read_text())
    aggregate_document["inputs"][0]["run_id"] = "../escaped"
    aggregate_document["inputs"][0]["report_sha256"] = _sha(report.read_bytes())
    aggregate.write_bytes(_canonical(aggregate_document))

    with pytest.raises(bundle.BundleError, match="not bundle-path safe"):
        bundle.package_bundle(aggregate, [report], [artifact], tmp_path / "bundle")


def test_rejects_symlink_without_following_it(tmp_path: Path) -> None:
    aggregate, report, artifact, supplemental = _inputs(tmp_path / "inputs")
    link = tmp_path / "linked-goal.md"
    link.symlink_to(supplemental)

    with pytest.raises(bundle.BundleError, match="symlink"):
        bundle.package_bundle(
            aggregate, [report], [artifact, link], tmp_path / "bundle"
        )


@pytest.mark.parametrize(
    "secret",
    [
        '{"schema":"synthetic.v1","access_token":"raw-private-token"}\n',
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345\n",
        "-----BEGIN PRIVATE KEY-----\nnot-a-real-key\n",
    ],
)
def test_secret_like_supplemental_content_fails_closed(
    tmp_path: Path, secret: str
) -> None:
    aggregate, report, artifact, supplemental = _inputs(tmp_path / "inputs")
    supplemental.write_text(secret)

    with pytest.raises(bundle.BundleError, match="SECRET_LIKE_CONTENT"):
        bundle.package_bundle(
            aggregate, [report], [artifact, supplemental], tmp_path / "bundle"
        )


def test_existing_output_is_preserved(tmp_path: Path) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"
    output.mkdir()
    sentinel = output / "sentinel"
    sentinel.write_text("preserve")

    with pytest.raises(FileExistsError):
        bundle.package_bundle(aggregate, [report], [artifact], output)

    assert sentinel.read_text() == "preserve"


def test_interrupted_publish_leaves_no_partial_output_or_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"
    real_write = bundle._write_private
    calls = 0

    def fail_second_write(path: Path, raw: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic publish interruption")
        real_write(path, raw)

    monkeypatch.setattr(bundle, "_write_private", fail_second_write)
    with pytest.raises(OSError, match="synthetic publish interruption"):
        bundle.package_bundle(aggregate, [report], [artifact], output)

    assert not output.exists()
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".bundle.")]


def test_publish_failure_after_read_only_seal_restores_staging_for_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"

    def fail_rename(source: Path, target: Path) -> None:
        assert target == output
        assert stat.S_IMODE(source.stat().st_mode) == 0o555
        assert stat.S_IMODE((source / "manifest.json").stat().st_mode) == 0o444
        raise OSError("synthetic rename interruption")

    monkeypatch.setattr(bundle.os, "rename", fail_rename)
    with pytest.raises(OSError, match="synthetic rename interruption"):
        bundle.package_bundle(aggregate, [report], [artifact], output)

    assert not output.exists()
    assert not [path for path in tmp_path.iterdir() if path.name.startswith(".bundle.")]


def test_packager_never_uses_workspace_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    aggregate, report, artifact, _supplemental = _inputs(tmp_path / "inputs")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("workspace discovery is forbidden")

    monkeypatch.setattr(Path, "glob", forbidden)
    monkeypatch.setattr(Path, "rglob", forbidden)
    result = bundle.package_bundle(aggregate, [report], [artifact], tmp_path / "bundle")
    assert result["status"] == "PASS"


def test_cli_help_lists_only_explicit_inputs() -> None:
    script = Path(__file__).parents[1] / "scripts/dg13u_u1_bundle.py"
    help_result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert help_result.returncode == 0
    assert "--aggregate" in help_result.stdout
    assert "--report" in help_result.stdout
    assert "--artifact" in help_result.stdout
    assert "--output-dir" in help_result.stdout
