from __future__ import annotations

import importlib.util
import json
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _module():
    path = TOOLS / "seal_product10_membership.py"
    spec = importlib.util.spec_from_file_location("seal_product10_membership", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_membership_is_label_free_and_preserves_case_order() -> None:
    module = _module()
    root = Path(__file__).resolve().parents[2]
    payload = module.build_membership(
        root / "data/labels/product10-instance-groups.jsonl"
    )

    assert payload["case_count"] == 24
    assert payload["instance_identity_fields_present"] is False
    assert payload["answer_material_present"] is False
    assert [row["case_id"] for row in payload["cases"]] == payload["case_ids"]
    forbidden = {
        "instance_groups",
        "acceptable_evidence_ids",
        "acceptable_turn_refs",
        "answer",
        "reference_answer",
    }
    encoded = json.dumps(payload, sort_keys=True)
    assert all(f'"{key}"' not in encoded for key in forbidden)
