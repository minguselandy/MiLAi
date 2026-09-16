from __future__ import annotations

from scripts import package_dg10_results as package


def test_payload_contains_final_report_and_excludes_tier2_reveal() -> None:
    payload = package.collect_payload()
    assert any(
        path.endswith("DG-10-final-completion-audit-candidate.2-2026-08-22.json")
        for path in payload
    )
    assert not any("evidence-reveal" in path for path in payload)
    assert not any("randomization-manifest" in path for path in payload)
    assert not any(".env" in path for path in payload)


def test_archive_is_deterministic_and_round_trips() -> None:
    files = {
        "README.md": b"hello\n",
        "repo/report.json": b"{}\n",
    }
    first = package._archive(files)
    second = package._archive(files)
    assert first == second
    package._verify_archive(first, files)
