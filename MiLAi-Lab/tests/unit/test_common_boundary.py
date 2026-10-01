"""Pure public contracts; no retrieval or business values inferred."""

from __future__ import annotations

import json
from typing import Any

import pytest

from milai_lab.contracts.common_boundary import bounded_view, digest, profiles, validate


@pytest.mark.parametrize(
    "key,value",
    [
        ("common_read_profile", None),
        ("common_read_profile", True),
        ("common_formation_profile", "unknown"),
        ("common_host_profile", {}),
        ("common_semantic_fallback", 1),
    ],
)
def test_unknown_profile_rejected(key: str, value: Any) -> None:
    with pytest.raises(ValueError, match="PROFILE_INVALID"):
        profiles({key: value})


def test_legacy_default_exact_empty_validation() -> None:
    assert validate({}, "B2") == {}
    assert set(profiles({}).values()) == {"legacy"}


@pytest.mark.parametrize("arm", ["B2", "B6", "mem0_trace_equal", "field_grounded"])
def test_explicit_shared_contract(arm: str) -> None:
    settings = {
        "common_read_profile": "bounded_public_v1",
        "generation_admission_profile": "durable_shared_v1",
        "memory_mutation_contract": "event_bound_v1",
        "memory_reader_policy": "bounded_evidence_v1",
        "controls": {"material_max_tokens": 2048, "raw_rag": {"top_k": 6}},
    }
    assert validate(settings, arm) == {"common_read_profile": "bounded_public_v1"}
    with pytest.raises(ValueError, match="SHARED_ADMISSION"):
        validate({**settings, "generation_admission_profile": "legacy"}, arm)


def test_fallback_requires_closed_not_extra_repairs() -> None:
    settings = {
        "common_semantic_fallback": "single_summary_v1",
        "generation_admission_profile": "durable_shared_v1",
        "memory_mutation_contract": "event_bound_v1",
    }
    with pytest.raises(ValueError, match="SUMMARY_CLOSED"):
        validate(settings, "B6")
    settings["common_formation_profile"] = "closed_host_v1"
    assert validate(settings, "B6")
    with pytest.raises(ValueError, match="REPAIR_DISABLED"):
        validate({**settings, "memory_writer_repairs": 1}, "B6")


@pytest.mark.parametrize("field", ["memory", "content"])
def test_exact_native_dto_prefix_order_metadata_and_omission(field: str) -> None:
    rows = [
        {
            "id": str(i),
            field: "中文Ω x " * 600,
            "user_id": "native:alice",
            "hash": str(i),
            "metadata": {"literal": [True, None, 1]},
        }
        for i in range(8)
    ]
    originals = json.loads(json.dumps(rows))
    result = bounded_view(
        rows,
        binding={"owner": "alice"},
        token_count=len,
        query_kind="ordinary_public",
        max_tokens=2048,
    )
    packet = result["packet"]
    assert result["snapshot_rows"] == originals == rows
    assert result["material_tokens"] <= 2048
    assert [row["id"] for row in packet["selected"]] == [str(i) for i in range(6)]
    delivered = {entry["dto"]["id"]: entry for entry in packet["items"]}
    assert len(delivered) <= 6 and set(delivered) | set(packet["omitted_ids"]) == set(
        map(str, range(8))
    )
    for row in originals:
        if row["id"] in delivered:
            entry = delivered[row["id"]]
            assert entry["dto_sha256"] == digest(row)
            assert row[field].startswith(entry["dto"][field])
            assert entry["dto"]["metadata"] == row["metadata"]
            assert entry["dto"]["hash"] == row["hash"]
            assert entry["dto"]["user_id"] == row["user_id"]


def test_metadata_infeasibility_is_explicit() -> None:
    with pytest.raises(ValueError, match="METADATA_EXCEEDS"):
        bounded_view(
            [{"id": "x", "memory": "y"}],
            binding={"owner": "x" * 5000},
            token_count=len,
            query_kind="ordinary_public",
        )
    with pytest.raises(ValueError, match="DUPLICATED"):
        bounded_view([{"id": "x"}, {"id": "x"}], binding={}, token_count=len, query_kind="explicit")
