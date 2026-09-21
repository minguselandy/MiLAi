from __future__ import annotations

import json
from pathlib import Path

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
    assert len({dependency.path for dependency in dependencies}) == 10
    assert len(dependencies) == 18
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
