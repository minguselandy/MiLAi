"""Core-only source-registration and CI ownership checks; no optional SDK imports."""

from __future__ import annotations

import copy
import json
import runpy
import shutil
import tomllib
from pathlib import Path
from typing import Any

import pytest

from milai_lab.application import APPLICATION_SOURCE_FILES
from milai_lab.harness.source_identity import (
    CANONICAL_PACKAGE_SOURCE_FILES,
    REQUEST_SOURCE_FILES,
)

LAB = Path(__file__).resolve().parents[2]
CHECKER = runpy.run_path(str(LAB / "tools/check_verification_matrix.py"))


def _inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        json.loads((LAB / "configs/lab-verification-matrix.json").read_text()),
        tomllib.loads((LAB / "pyproject.toml").read_text()),
    )


def test_canonical_packages_equal_explicit_source_registration() -> None:
    for package, registered in {
        **CANONICAL_PACKAGE_SOURCE_FILES,
        "application": APPLICATION_SOURCE_FILES,
    }.items():
        actual = {
            str(path.relative_to(LAB)) for path in (LAB / "src/milai_lab" / package).rglob("*.py")
        }
        assert actual == set(registered)
        assert len(registered) == len(set(registered))
    assert len(REQUEST_SOURCE_FILES) == len(set(REQUEST_SOURCE_FILES))
    assert set().union(*map(set, CANONICAL_PACKAGE_SOURCE_FILES.values())) <= set(
        REQUEST_SOURCE_FILES
    )


def test_every_active_source_has_an_owner_and_an_executed_strict_ci_group() -> None:
    matrix, config = _inputs()
    coverage = CHECKER["verify_source_ownership"](matrix, LAB, config)
    assert len(coverage) == len(list((LAB / "src/milai_lab").rglob("*.py")))
    by_path = {row["path"]: row for row in coverage}
    assert "Core" in by_path["src/milai_lab/application/world.py"]["ci_groups"]
    assert "External" in by_path["src/milai_lab/integrations/memory/mem0.py"]["ci_groups"]


@pytest.mark.parametrize(
    "fault", ["owner", "group", "owner_label", "strict", "requirement", "package"]
)
def test_missing_or_fabricated_source_ownership_is_rejected(fault: str) -> None:
    matrix, config = _inputs()
    if fault == "owner":
        matrix["source_owners"] = [
            row for row in matrix["source_owners"] if row["prefix"] != "src/milai_lab/contracts/"
        ]
    elif fault == "group":
        next(row for row in matrix["source_owners"] if row["prefix"] == "src/milai_lab/contracts/")[
            "ci_groups"
        ] = []
    elif fault == "owner_label":
        next(row for row in matrix["source_owners"] if row["prefix"] == "src/milai_lab/contracts/")[
            "owner"
        ] = "runners"
    elif fault == "strict":
        config["tool"]["mypy"]["strict"] = False
    elif fault == "requirement":
        matrix["strict_required"].pop()
    else:
        matrix["canonical_packages"].remove("providers")
    with pytest.raises(ValueError, match="LAB_VERIFICATION_"):
        CHECKER["verify_source_ownership"](matrix, LAB, config)


def test_missing_source_registration_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix, config = _inputs()
    packages = copy.deepcopy(CANONICAL_PACKAGE_SOURCE_FILES)
    packages["providers"] = packages["providers"][:-1]
    monkeypatch.setitem(
        CHECKER["verify_source_ownership"].__globals__, "CANONICAL_PACKAGE_SOURCE_FILES", packages
    )
    with pytest.raises(ValueError, match="SOURCE_REGISTRATION_DRIFT:providers"):
        CHECKER["verify_source_ownership"](matrix, LAB, config)


def test_new_unregistered_implementation_is_rejected(tmp_path: Path) -> None:
    matrix, config = _inputs()
    shutil.copytree(
        LAB / "src/milai_lab",
        tmp_path / "src/milai_lab",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (tmp_path / "src/milai_lab/memory/unregistered.py").write_text('"""New source."""\n')
    with pytest.raises(ValueError, match="SOURCE_REGISTRATION_DRIFT:memory"):
        CHECKER["verify_source_ownership"](matrix, tmp_path, config)
