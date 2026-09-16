"""Independent row-history fixtures for the original inspection-traceability lineage."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from prepare_v0218_traceability import inspection_traceability
from v0218_checker import evaluate
from v0218_world import World


def native_history():
    return [
        {
            "store_id": "S037",
            "store_name": "润健卡路里",
            "district": "鼓楼",
            "date": day,
            "result": result,
            "detail": detail,
        }
        for day, result, detail in [
            ("2025-07-08", "不合格", "大肠杆菌超标"),
            ("2025-08-05", "合格", "复查合格"),
            ("2025-10-14", "合格", "例行检查"),
        ]
    ]


def record():
    return {
        "inspection_rows": native_history(),
        "latest_date": "2025-10-14",
        "latest_result": "合格",
        "historical_failure": True,
        "status": "confirmed",
        "basis_revision": "inspection-v1",
    }


def put(world, row, operation):
    world.act(
        operation_id=operation,
        expected_version=world.snapshot()["version"],
        action="put_record",
        object_id="S037",
        data=row,
    )


def populated(tmp_path):
    source = [
        *native_history(),
        {
            "store_id": "other",
            "store_name": "Other",
            "district": "Other",
            "date": "2026-01-01",
            "result": "合格",
            "detail": "Other",
        },
    ]
    spec = inspection_traceability(source)
    world = World.create(tmp_path / "world.sqlite", "inspection", spec["public"])
    put(world, record(), "initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    return world, spec


def test_reinspection_updates_latest_but_does_not_erase_historical_failure(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="reinspection", current=spec["variants"]["superseded"])
    assert evaluate(world.snapshot())["status"] == "FAIL"
    row = record()
    row["inspection_rows"].append(
        {
            "store_id": "S037",
            "store_name": "润健卡路里",
            "district": "鼓楼",
            "date": "2026-03-18",
            "result": "合格",
            "detail": "舆情复查",
        }
    )
    row.update(latest_date="2026-03-18", basis_revision="inspection-v2")
    put(world, row, "refresh")
    assert evaluate(World(world.path, "inspection").snapshot())["status"] == "PASS"
    row["historical_failure"] = False
    put(world, row, "overcorrect")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_foreign_store_updates_and_row_order_do_not_require_changes(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="other-store", current=spec["variants"]["irrelevant"])
    assert evaluate(world.snapshot())["status"] == "PASS"
    row = record()
    row["inspection_rows"].reverse()
    put(world, row, "permutation")
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "field,value",
    [
        ("latest_date", "2025-07-08"),
        ("latest_date", "2025/10/14"),
        ("latest_date", 20251014),
        ("latest_result", "不合格"),
        ("latest_result", "not 合格"),
        ("latest_result", ["合格", "不合格"]),
        ("historical_failure", False),
        ("historical_failure", "true"),
        ("historical_failure", 1),
        ("status", "pending"),
        ("basis_revision", "inspection-v0"),
        ("inspection_rows", []),
        ("inspection_rows", "export complete"),
    ],
)
def test_wrong_current_historical_types_and_false_export_claims_fail(tmp_path, field, value):
    world, _ = populated(tmp_path)
    row = record()
    row[field] = value
    put(world, row, "bad")
    assert evaluate(world.snapshot())["status"] == "FAIL"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "foreign", "negated", "wrong_column"])
def test_complete_export_means_exact_rows_not_date_keyword_matches(tmp_path, mutation):
    world, _ = populated(tmp_path)
    row = record()
    if mutation == "missing":
        row["inspection_rows"].pop(0)
    elif mutation == "duplicate":
        row["inspection_rows"][0] = copy.deepcopy(row["inspection_rows"][1])
    elif mutation == "foreign":
        row["inspection_rows"][0]["store_id"] = "other-store"
    elif mutation == "negated":
        row["inspection_rows"][0]["result"] = "并非不合格"
    else:
        row["inspection_rows"][0]["checked_by"] = "invented"
    put(world, row, "bad-export")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_pending_latest_requires_real_request_and_no_unverified_pass(tmp_path):
    world, spec = populated(tmp_path)
    world.publish(event_id="pending", current=spec["variants"]["unresolved"])
    row = {
        **record(),
        "latest_date": "2026-03-18",
        "latest_result": "pending",
        "status": "pending",
        "basis_revision": "inspection-review-pending",
    }
    put(world, row, "withhold")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    world.act(
        operation_id="clarify",
        expected_version=world.snapshot()["version"],
        action="request_clarification",
        object_id="S037",
        data={"question": "Please confirm the 2026-03-18 re-inspection result for S037."},
    )
    assert evaluate(world.snapshot())["status"] == "PASS"
    row["latest_result"] = "合格"
    put(world, row, "unsupported")
    assert evaluate(world.snapshot())["status"] == "FAIL"


def test_missing_fields_and_snapshot_object_forgery_fail(tmp_path):
    world, _ = populated(tmp_path)
    for field in record():
        state = world.snapshot()
        del state["records"]["S037"][field]
        assert evaluate(state)["status"] == "FAIL"
    state = world.snapshot()
    state["records"]["S037"]["object_id"] = "another"
    assert evaluate(state)["status"] == "FAIL"


def helpful_world(tmp_path):
    spec = inspection_traceability(native_history(), include_helpful=True)
    world = World.create(tmp_path / "helpful.sqlite", "helpful", spec["public"])
    put(world, record(), "initial")
    world.publish(event_id="display-only", current=spec["variants"]["helpful"])
    return world


def archive(state):
    return next(
        item["content"] for item in state["history"] if item.get("kind") == "prior_public_record"
    )


def test_helpful_hides_old_rows_but_preserves_public_history_and_valid_export(tmp_path):
    world = helpful_world(tmp_path)
    state = world.snapshot()
    assert len(state["current"]["inspections"]) == 1
    assert state["current"]["inspections"][0]["result"] == "合格"
    assert archive(state)["inspections"] == native_history()
    assert "history" in state["current"]["history_access"]
    assert evaluate(state)["status"] == "PASS"
    # Exact same ordinary sources and work products survive independent cold clones.
    for arm in ("N0", "N1"):
        branch = world.clone(tmp_path / f"{arm}.sqlite", arm)
        assert branch.snapshot()["history"] == state["history"]
        assert branch.snapshot()["records"] == state["records"]
        assert evaluate(branch.snapshot())["status"] == "PASS"


def test_helpful_latest_only_export_fails_and_normal_history_repairs_it(tmp_path):
    world = helpful_world(tmp_path)
    truncated = record()
    truncated["inspection_rows"] = world.snapshot()["current"]["inspections"]
    truncated["historical_failure"] = False
    put(world, truncated, "bad-latest-only")
    assert evaluate(world.snapshot())["status"] == "FAIL"
    restored = record()
    restored["inspection_rows"] = archive(world.snapshot())["inspections"]
    put(world, restored, "normal-history-repair")
    assert evaluate(world.snapshot())["status"] == "PASS"


@pytest.mark.parametrize(
    "mutation", ["missing", "hash", "archive", "projection", "revision", "pending"]
)
def test_helpful_archive_is_authoritative_not_agent_assertion(tmp_path, mutation):
    state = helpful_world(tmp_path).snapshot()
    if mutation == "missing":
        state["history"] = []
    elif mutation == "hash":
        state["current"]["archive_content_sha256"] = "0" * 64
    elif mutation == "archive":
        archive(state)["inspections"][0]["result"] = "合格"
    elif mutation == "projection":
        state["current"]["inspections"][0]["date"] = "2026-01-01"
    elif mutation == "revision":
        state["current"]["store_revisions"]["S037"] = "changed"
    else:
        state["current"]["pending_inspections"]["S037"] = {"date": "2026-01-01"}
    assert evaluate(state)["status"] == "FAIL"
