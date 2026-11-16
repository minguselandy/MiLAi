from __future__ import annotations

import json
from pathlib import Path

import pytest

from milai_lab.tools_boundary import verify_tools_boundary

LAB = Path(__file__).parents[2]


def _inventory(
    path: Path,
    *,
    public_modules: list[str] | None = None,
    grandfathered: list[dict[str, str]] | None = None,
    dependencies: list[dict[str, object]] | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "milai.lab.tools-product-dependencies.v1",
                "product_import_roots": [
                    "milai",
                    "milai_client",
                    "milai_mcp",
                    "milai_openworker_mcp",
                ],
                "public_modules": public_modules or [],
                "testkit_prefixes": ["milai.testkit"],
                "grandfathered_private_imports": grandfathered or [],
                "dependencies": dependencies or [],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_active_tools_match_the_classified_product_dependency_inventory() -> None:
    findings, dependencies = verify_tools_boundary(
        LAB / "tools", LAB / "docs" / "tools-product-dependencies.json"
    )

    assert findings == ()
    assert len({dependency.path for dependency in dependencies}) == 11
    assert len(dependencies) == 20
    assert sum(
        dependency.classification == "LEGACY_PRIVATE" for dependency in dependencies
    ) == 6


def test_grandfathered_private_import_is_exact_to_path_and_module(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "legacy.py").write_text("import milai_mcp.server\n", encoding="utf-8")
    (tools / "new.py").write_text("import milai_mcp.server\n", encoding="utf-8")
    inventory = _inventory(
        tmp_path / "inventory.json",
        grandfathered=[
            {
                "path": "tools/legacy.py",
                "module": "milai_mcp.server",
                "reason": "existing dependency",
            }
        ],
        dependencies=[
            {
                "path": "tools/legacy.py",
                "module": "milai_mcp.server",
                "classification": "LEGACY_PRIVATE",
                "lines": [1],
            }
        ],
    )

    findings, _ = verify_tools_boundary(tools, inventory)

    assert [(finding.path, finding.code) for finding in findings] == [
        ("tools/new.py", "NEW_PRIVATE_PRODUCT_IMPORT")
    ]


def test_public_root_does_not_authorize_private_submodules(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "new.py").write_text("import milai_client.client\n", encoding="utf-8")
    inventory = _inventory(
        tmp_path / "inventory.json", public_modules=["milai_client"]
    )

    findings, _ = verify_tools_boundary(tools, inventory)

    assert [finding.code for finding in findings] == ["NEW_PRIVATE_PRODUCT_IMPORT"]


def test_dynamic_product_import_is_scanned(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "dynamic.py").write_text(
        'import importlib\nimportlib.import_module("milai_mcp.server")\n',
        encoding="utf-8",
    )
    inventory = _inventory(tmp_path / "inventory.json")

    findings, _ = verify_tools_boundary(tools, inventory)

    assert len(findings) == 1
    assert findings[0].code == "NEW_PRIVATE_PRODUCT_IMPORT"
    assert "milai_mcp.server" in findings[0].detail


def test_inventory_line_identity_must_be_refreshed_after_source_drift(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "public.py").write_text("\nimport milai_client\n", encoding="utf-8")
    inventory = _inventory(
        tmp_path / "inventory.json",
        public_modules=["milai_client"],
        dependencies=[
            {
                "path": "tools/public.py",
                "module": "milai_client",
                "classification": "PUBLIC",
                "lines": [1],
            }
        ],
    )

    findings, _ = verify_tools_boundary(tools, inventory)

    assert [finding.code for finding in findings] == [
        "TOOLS_PRODUCT_INVENTORY_DRIFT"
    ]


@pytest.mark.parametrize(
    "filename", ["own_a100_lme_execution_v2.py", "own_a100_lme_observation_v3.py"]
)
def test_frozen_lme_loader_review_does_not_authorize_other_paths_or_private_imports(
    tmp_path: Path, filename: str
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    path = tools / filename
    original = (LAB / "tools" / filename).read_text()
    inventory = _inventory(tmp_path / "inventory.json")
    path.write_text(original)
    assert verify_tools_boundary(tools, inventory)[0] == ()

    path.write_text(original.replace('"frozen_owner_entry"', '"unreviewed_entry"'))
    findings, _ = verify_tools_boundary(tools, inventory)
    assert findings and all(f.code == "UNRESOLVED_TOOL_IMPORT" for f in findings)

    path.write_text(original + "\nimport milai.private_runtime\n")
    findings, _ = verify_tools_boundary(tools, inventory)
    assert [f.code for f in findings] == ["NEW_PRIVATE_PRODUCT_IMPORT"]


def test_frozen_lme_observer_does_not_authorize_an_extra_dynamic_loader_call(
    tmp_path: Path,
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    filename = "own_a100_lme_observation_v3.py"
    original = (LAB / "tools" / filename).read_text()
    (tools / filename).write_text(original + '\nload_entry("unreviewed", other_path)\n')
    findings, _ = verify_tools_boundary(tools, _inventory(tmp_path / "inventory.json"))
    assert findings and all(f.code == "UNRESOLVED_TOOL_IMPORT" for f in findings)


def test_frozen_lme_observer_rejects_repointed_predecessor(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    filename = "own_a100_lme_observation_v3.py"
    original = (LAB / "tools" / filename).read_text()
    (tools / filename).write_text(original.replace(
        'predecessor = read(correction["predecessor_protocol"])',
        'predecessor = read(other_protocol)',
    ))
    findings, _ = verify_tools_boundary(tools, _inventory(tmp_path / "inventory.json"))
    assert findings and all(f.code == "UNRESOLVED_TOOL_IMPORT" for f in findings)
