from __future__ import annotations

from scripts import build_dg10_tier2_blind_package as tier2


def _sidecar() -> dict[str, object]:
    return tier2._load_bound(tier2.THREE_ARM_SIDECAR, tier2.THREE_ARM_SIDECAR_SHA256)


def test_blind_package_is_deterministic_for_seed_and_contains_no_arm_mapping() -> None:
    seed = bytes.fromhex("42" * 32)
    first = tier2.build_packages(
        _sidecar(), seed=seed, run_id="test-run", created_at="test-time"
    )
    second = tier2.build_packages(
        _sidecar(), seed=seed, run_id="test-run", created_at="test-time"
    )
    assert first == second
    blind, reveal, manifest, annotation, adjudication = first
    assert blind["case_count"] == 12
    assert blind["answer_count"] == 36
    assert len(annotation["first_pass_rows"]) == 36
    assert len(adjudication["rows"]) == 36
    assert (
        manifest["seed_sha256_commitment"]
        == blind["randomization_seed_sha256_commitment"]
    )
    tier2._scan_blind_payload(blind, allow_evidence=False)
    tier2._scan_blind_payload(reveal, allow_evidence=True)
    assert "arm_identity" not in tier2._json_bytes(blind).decode()
    assert "arm_identity" not in tier2._json_bytes(reveal).decode()


def test_per_case_aliases_are_bijective() -> None:
    packages = tier2.build_packages(
        _sidecar(), seed=bytes.fromhex("24" * 32), run_id="test", created_at="test"
    )
    manifest = packages[2]
    assert len(manifest["cases"]) == 12
    for case in manifest["cases"]:
        mappings = case["answer_mapping"]
        assert {item["answer_id"] for item in mappings} == {"A", "B", "C"}
        assert {item["arm_identity"] for item in mappings} == set(tier2.ARMS)


def test_frozen_case_selection_and_input_bindings_hold() -> None:
    quality = tier2._load_bound(tier2.QUALITY_REPORT, tier2.QUALITY_REPORT_SHA256)
    report = tier2._load_bound(tier2.THREE_ARM_REPORT, tier2.THREE_ARM_REPORT_SHA256)
    tier2._validate_bound_contracts(quality, report)
    assert len(tier2.TIER2_CASES) == 12
