"""Zero-model actual-world calibration for sequential frozen external lineages."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from v0218_checker import evaluate
from v0218_world import World, digest


def financial_fixtures():
    initial = {}
    for obj, metric, basis, period, value, revision in [
        ("reported_income", "net_income", "reported", "1Q24", 13.4, "earnings-v1"),
        ("adjusted_income", "net_income", "adjusted", "1Q24", 14.0, "earnings-v1"),
        ("nii_guide", "NII_ex_Markets", "guidance", "FY24", 89.0, "guide-v1"),
        ("nii_street", "NII_ex_Markets", "consensus", "FY24", 90.68, "consensus-v1"),
        ("guide_gap", "NII_ex_Markets", "guide_minus_consensus", "FY24", -1.68, "comparison-v1"),
    ]:
        initial[obj] = {
            "metric": metric,
            "basis": basis,
            "period": period,
            "value": value,
            "unit": "BUSD",
            "basis_revision": revision,
            "status": "confirmed",
        }
    initial["guide_gap"]["direction"] = "below"
    revised = {
        "nii_street": {**initial["nii_street"], "value": 88.5, "basis_revision": "consensus-v2"},
        "guide_gap": {
            **initial["guide_gap"],
            "value": 0.5,
            "direction": "above",
            "basis_revision": "comparison-v2",
        },
    }
    pending = {
        "nii_street": {
            **initial["nii_street"],
            "value": None,
            "status": "pending",
            "basis_revision": "consensus-review-pending",
        },
        "guide_gap": {
            **initial["guide_gap"],
            "value": None,
            "status": "pending",
            "direction": "unknown",
            "basis_revision": "comparison-review-pending",
        },
    }
    return initial, revised, pending, "nii_street"


def inspection_fixtures():
    history = [
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
    initial = {
        "inspection_rows": history,
        "latest_date": "2025-10-14",
        "latest_result": "合格",
        "historical_failure": True,
        "status": "confirmed",
        "basis_revision": "inspection-v1",
    }
    revised = {
        **initial,
        "latest_date": "2026-03-18",
        "basis_revision": "inspection-v2",
        "inspection_rows": [
            *history,
            {
                "store_id": "S037",
                "store_name": "润健卡路里",
                "district": "鼓楼",
                "date": "2026-03-18",
                "result": "合格",
                "detail": "舆情复查",
            },
        ],
    }
    pending = {
        **initial,
        "latest_date": "2026-03-18",
        "latest_result": "pending",
        "status": "pending",
        "basis_revision": "inspection-review-pending",
    }
    return {"S037": initial}, {"S037": revised}, {"S037": pending}, "S037"


def newsroom_fixtures():
    initial = {}
    for field, value, source_id in [
        ("fire_start", "2026-03-18T14:28:00+08:00", "briefing-start"),
        ("alarm_received", "2026-03-18T14:35:00+08:00", "briefing-alarm"),
        ("casualty_count", 2, "health-count-1"),
        ("casualty_status", "under_observation", "health-status-1"),
    ]:
        initial[field] = {
            "incident": "park-fire",
            "field": field,
            "value": value,
            "status": "confirmed",
            "source_ids": [source_id],
            "basis_edition": 1,
        }
    revised = {
        field: {
            **initial[field],
            "value": value,
            "basis_edition": 2,
            "source_ids": [f"health-{field}-2"],
        }
        for field, value in (("casualty_count", 2), ("casualty_status", "discharged"))
    }
    pending = {
        field: {
            **row,
            "value": None,
            "status": "conflicting",
            "source_ids": [*row["source_ids"], f"health-{field}-2-conflict"],
        }
        for field, row in revised.items()
    }
    return initial, revised, pending, ["casualty_count", "casualty_status"]


def bridge_fixtures():
    initial = {
        "company": "ServiceNow",
        "period": "FY24",
        "metric": "subscription_revenue",
        "unit": "MUSD",
        "prior_low": 10555,
        "prior_high": 10575,
        "current_low": 10560,
        "current_high": 10575,
        "low_change": 5,
        "high_change": 0,
        "net_change": 2.5,
        "fx_change": -17,
        "operational_change": 19.5,
        "net_direction": "raise",
        "operational_direction": "raise",
        "status": "confirmed",
        "basis_revision": "bridge-v1",
    }
    revised = {
        **initial,
        "current_low": 10540,
        "current_high": 10560,
        "low_change": -15,
        "high_change": -15,
        "net_change": -15,
        "fx_change": -25,
        "operational_change": 10,
        "net_direction": "cut",
        "basis_revision": "bridge-v2",
    }
    pending = {
        **revised,
        "fx_change": None,
        "operational_change": None,
        "operational_direction": "unknown",
        "status": "pending_fx",
        "basis_revision": "bridge-fx-pending",
    }
    target = "FY24-subscription-bridge"
    return {target: initial}, {target: revised}, {target: pending}, target


def casework_fixtures():
    target = "MD2024-011"
    initial = {
        "case_id": target,
        "items": [
            {"item_id": code, "category": name, "amount_cny": amount, "basis": basis}
            for code, name, amount, basis in (
                ("C01", "Medical_Expenses", 86000, "receipt"),
                ("C02", "Lost_Wages", 32000, "estimate"),
                ("C03", "Nursing_Fees", 18000, "estimate"),
            )
        ],
        "provisional_subtotal_cny": 136000,
        "receipt_subtotal_cny": 86000,
        "disability_status": "unassessed",
        "disability_amount_cny": None,
        "final_compensation_cny": None,
        "settlement_authorized": False,
        "audience": "lead_lawyer",
        "application_deadline": "2024-04-10T17:00:00+08:00",
        "planned_at": "2024-04-09T10:00:00+08:00",
        "deadline_status": "confirmed",
        "basis_revision": "case-v1",
    }
    revised = {
        **initial,
        "application_deadline": "2024-03-31T17:00:00+08:00",
        "planned_at": "2024-03-28T10:00:00+08:00",
        "basis_revision": "case-v2",
    }
    pending = {
        **revised,
        "application_deadline": None,
        "planned_at": None,
        "deadline_status": "pending",
        "basis_revision": "case-deadline-pending",
    }
    return {target: initial}, {target: revised}, {target: pending}, target


def product_review_fixtures():
    import copy

    initial_features = {
        "F-201": {
            "priority": "P0",
            "version": "v2.5",
            "status": "pending development",
            "phase": "phase1",
        },
        "F-202": {
            "priority": "P0",
            "version": "v2.5",
            "status": "pending development",
            "phase": "phase1",
        },
        "F-203": {
            "priority": "P2",
            "version": "v2.6",
            "status": "pending evaluation",
            "phase": "phase2",
        },
        "F-204": {
            "priority": "P1",
            "version": "v2.4",
            "status": "needs investigation",
            "phase": "existing",
        },
    }
    initial = {
        name: {"features": copy.deepcopy(initial_features), "basis_revision": "review-v1"}
        for name in ("feature_spec", "backlog", "timeline")
    }
    initial["summary"] = {
        "counts": {"phase1": 2, "phase2": 1, "existing": 1, "pending": 0},
        "total": 4,
        "basis_revision": "review-v1",
    }
    revised, pending = copy.deepcopy(initial), copy.deepcopy(initial)
    for name in ("feature_spec", "backlog", "timeline"):
        revised[name]["features"]["F-203"] = {
            "priority": "P1",
            "version": "v2.5",
            "status": "pending development",
            "phase": "phase1",
        }
        pending[name]["features"]["F-203"] = {
            "priority": None,
            "version": None,
            "status": "needs decision",
            "phase": "pending",
        }
    revised["summary"]["counts"] = {"phase1": 3, "phase2": 0, "existing": 1, "pending": 0}
    pending["summary"]["counts"] = {"phase1": 2, "phase2": 0, "existing": 1, "pending": 1}
    for row in revised.values():
        row["basis_revision"] = "review-v2"
    for row in pending.values():
        row["basis_revision"] = "review-decision-pending"
    return initial, revised, pending, "backlog"


def research_integrity_fixtures():
    stats = {
        "seed_count": 3,
        "mean": 74.73,
        "sample_std": 0.40,
        "paper_seed": 42,
        "paper_value": 74.8,
        "best_sample_value": 75.1,
        "basis_revision": "statistics-v1",
    }
    initial = {
        "seed_statistics": stats,
        "backbone_comparison": {
            "rows": [
                {
                    "dataset": "VQA v2",
                    "metric": "Accuracy",
                    "value": 70.2,
                    "reference_value": 74.8,
                    "gap": -4.6,
                    "run_basis": "pilot",
                    "status": "confirmed",
                }
            ],
            "basis_revision": "backbone-v1",
        },
    }
    rows = [
        {
            "dataset": dataset,
            "metric": metric,
            "value": value,
            "reference_value": reference,
            "gap": gap,
            "run_basis": "tuned",
            "status": "confirmed",
        }
        for dataset, metric, value, reference, gap in (
            ("VQA v2", "Accuracy", 72.1, 74.8, -2.7),
            ("MSCOCO", "Accuracy", 70.8, 73.5, -2.7),
            ("RefCOCO", "F1", 58.9, 67.2, -8.3),
            ("SNLI-VE", "Accuracy", 75.2, 78.1, -2.9),
        )
    ]
    revised = {"backbone_comparison": {"rows": rows, "basis_revision": "backbone-v2"}}
    pending_rows = [dict(item) for item in rows]
    pending_rows[2].update(value=None, gap=None, status="pending")
    pending = {
        "backbone_comparison": {"rows": pending_rows, "basis_revision": "backbone-refcoco-pending"}
    }
    return initial, revised, pending, "backbone_comparison"


def transaction_fixtures(*, cleared=False):
    import copy

    initial = {
        "funding": {
            "transaction_id": "TX001",
            "agreed_price": 4650000,
            "down_payment": 1700000,
            "loan_amount": 3000000,
            "loan_status": "pre_approval",
            "scenario_total": 4700000,
            "gap": -50000,
            "review_ready": False,
            "signed": False,
            "basis_revision": "transaction-v1",
        },
        "disclosures": {
            "briefings": {
                "manager": {
                    "agreed_price": 4650000,
                    "buyer_budget": 1700000,
                    "seller_floor": 4600000,
                },
                "buyer": {"agreed_price": 4650000, "buyer_budget": 1700000, "gap": -50000},
                "seller": {"agreed_price": 4650000},
            },
            "basis_revision": "transaction-v1",
        },
    }
    revised, pending = copy.deepcopy(initial), copy.deepcopy(initial)
    revised["funding"].update(
        loan_amount=2800000, loan_status="formal_approval", scenario_total=4500000, gap=150000
    )
    revised["disclosures"]["briefings"]["buyer"]["gap"] = 150000
    for row in revised.values():
        row["basis_revision"] = "transaction-v2"
    pending["funding"].update(
        loan_amount=None, loan_status="unresolved", scenario_total=None, gap=None
    )
    pending["disclosures"]["briefings"]["buyer"]["gap"] = None
    for row in pending.values():
        row["basis_revision"] = "transaction-loan-pending"
    if cleared:
        revised = copy.deepcopy(initial)
        revised["funding"].update(loan_status="formal_approval", review_ready=True)
        for row in revised.values():
            row["basis_revision"] = "transaction-cleared"
    return initial, revised, pending, "funding"


def capacity_fixtures():
    import copy

    rows = [
        {
            "candidate_id": key,
            "score": score,
            "rank": rank,
            "recommendation": rec,
            "reason": reason,
            "flags": flags,
        }
        for key, score, rank, rec, reason, flags in (
            ("I01", 14.3, 1, "convert", "retained", []),
            ("I02", 12.6, 3, "convert", "retained", []),
            ("I03", 11.1, 4, "convert", "retained", ["attendance_output_mismatch"]),
            ("I04", 13.0, 2, "convert", "retained", []),
            ("I05", 8.8, 5, "reject", "below_threshold", []),
        )
    ]
    revised_rows = copy.deepcopy(rows)
    revised_rows[1].update(score=13.6, rank=2, flags=["core_business_priority"])
    revised_rows[2].update(recommendation="hold", reason="capacity")
    revised_rows[3].update(score=13.3, rank=3, flags=["public_private_support_conflict"])
    pending_rows = copy.deepcopy(revised_rows)
    for item in pending_rows[:4]:
        item.update(recommendation="hold", reason="headcount_pending")

    def pair(data, headcount, revision):
        return {
            name: {"rows": copy.deepcopy(data), "headcount": headcount, "basis_revision": revision}
            for name in ("ats", "summary")
        }

    return (
        pair(rows, 4, "capacity-v1"),
        pair(revised_rows, 3, "capacity-v2"),
        pair(pending_rows, None, "capacity-pending"),
        "summary",
    )


def execute(source: Path, output: Path, lineage: str = "research_assistant_task3") -> dict:
    output.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((source / "manifest.json").read_text())
    item = next(item for item in manifest["roots"] if item["root"] == lineage)
    key = item["root"]
    contract = source / key / "evaluation-contract.json"
    assert hashlib.sha256(contract.read_bytes()).hexdigest() == item["contract_sha256"]
    spec = json.loads(contract.read_text())
    archived = output / "executed-source"
    archived.mkdir()
    for name in (
        Path(__file__).name,
        "v0218_world.py",
        "v0218_checker.py",
        "prepare_v0218_expansion.py",
        "prepare_v0218_traceability.py",
        "prepare_v0218_news.py",
        "prepare_v0218_bridge.py",
        "prepare_v0218_casework.py",
        "prepare_v0218_product_review.py",
        "prepare_v0218_research_integrity.py",
        "prepare_v0218_transaction.py",
        "prepare_v0218_capacity.py",
    ):
        shutil.copyfile(Path(__file__).with_name(name), archived / name)
    shutil.copyfile(contract, output / "evaluation-contract.json")
    initial = {
        "deployed_version": "v2.1",
        "required_version": "v3.0",
        "deadline": "2026-03-31",
        "planned_review_at": "2026-03-30T14:00:00+08:00",
        "release_authorized": False,
        "distribution": ["advisor"],
        "basis_revision": "deployment-v1",
    }
    revised = {
        "deployed_version": "v3.0",
        "required_version": "v3.0",
        "deadline": "2026-03-28",
        "planned_review_at": "2026-03-27T10:00:00+08:00",
        "release_authorized": True,
        "distribution": ["advisor", "internal_quality"],
        "basis_revision": "deployment-v2",
    }
    pending = {
        "enterprise-midterm": {
            **revised,
            "deployed_version": None,
            "release_authorized": False,
            "basis_revision": "deployment-review-pending",
        }
    }
    initial, revised, clarification_object = (
        {"enterprise-midterm": initial},
        {"enterprise-midterm": revised},
        "enterprise-midterm",
    )
    if item["family"] == "financial_basis":
        initial, revised, pending, clarification_object = financial_fixtures()
    elif item["family"] == "inspection_traceability":
        initial, revised, pending, clarification_object = inspection_fixtures()
    elif item["family"] == "newsroom_authority":
        initial, revised, pending, clarification_object = newsroom_fixtures()
    elif item["family"] == "signed_guidance_bridge":
        initial, revised, pending, clarification_object = bridge_fixtures()
    elif item["family"] == "internal_casework":
        initial, revised, pending, clarification_object = casework_fixtures()
    elif item["family"] == "product_review_sync":
        initial, revised, pending, clarification_object = product_review_fixtures()
    elif item["family"] == "research_integrity":
        initial, revised, pending, clarification_object = research_integrity_fixtures()
    elif item["family"] == "transaction_funding_disclosure":
        initial, revised, pending, clarification_object = transaction_fixtures()
    elif item["family"] == "capacity_allocation":
        initial, revised, pending, clarification_object = capacity_fixtures()
    else:
        assert item["family"] == "release_control"
    world = World(source / key / "initial.sqlite", key).clone(output / "A.sqlite", key + "-A")

    def put(target, records, operation):
        for object_id, data in records.items():
            target.act(
                operation_id=operation + "-" + object_id,
                expected_version=target.snapshot()["version"],
                action="put_record",
                object_id=object_id,
                data=data,
            )

    put(world, initial, "scripted-initial")
    assert evaluate(world.snapshot())["status"] == "PASS"
    rows = []
    for variant in spec["variants"]:
        branch = world.clone(output / f"{variant}.sqlite", key + "-" + variant)
        branch.publish(event_id="frozen-B", current=spec["variants"][variant], task=spec["task_B"])
        before = evaluate(branch.snapshot())
        assert before["status"] == (
            "PASS" if variant in {"stable", "irrelevant", "helpful"} else "FAIL"
        )
        if variant == "superseded":
            put(branch, revised, "scripted-repair")
        elif variant == "resolved":
            assert item["family"] == "transaction_funding_disclosure"
            put(branch, transaction_fixtures(cleared=True)[1], "scripted-cleared")
        elif variant == "unresolved":
            put(branch, pending, "scripted-withhold")
            objects = (
                clarification_object
                if isinstance(clarification_object, list)
                else [clarification_object]
            )
            for object_id in objects:
                branch.act(
                    operation_id="scripted-clarify-" + object_id,
                    expected_version=branch.snapshot()["version"],
                    action="request_clarification",
                    object_id=object_id,
                    data={"question": "Please verify this object's unresolved official record."},
                )
        after = evaluate(branch.snapshot())
        assert after["status"] == "PASS"
        rows.append(
            {
                "root": key,
                "variant": variant,
                "before": before,
                "after": after,
                "final_sha256": digest(branch.snapshot()),
                "model_requests": 0,
                "execution_kind": "SCRIPTED_LOCAL_WORLD_NOT_AGENT_BEHAVIOR",
            }
        )
        (output / f"{variant}-ledger.json").write_text(json.dumps(branch.ledger(), indent=2))
        (output / f"{variant}-final.json").write_text(json.dumps(branch.snapshot(), indent=2))
    result = {
        "status": "ADDITIONAL_LINEAGE_SCRIPTED_REPLAY_PASSED_NOT_G",
        "roots": 1,
        "rows": rows,
        "model_requests": 0,
        "agent_note_writes": 0,
        "source_contract_sha256": item["contract_sha256"],
        "executed_source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in archived.iterdir()
        },
        "checker_sha256": hashlib.sha256(
            Path(__file__).with_name("v0218_checker.py").read_bytes()
        ).hexdigest(),
    }
    (output / "result.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lineage", default="research_assistant_task3")
    args = parser.parse_args()
    print(json.dumps(execute(args.root, args.output, args.lineage)))
