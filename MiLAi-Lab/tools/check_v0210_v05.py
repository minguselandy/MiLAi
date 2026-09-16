"""V0.5 zero-generation static plan, R0 and independent dynamic-entry preparation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from check_v0210_control import LAB, tokenize, verify_baseline, write
from milai_lab.methods.correctable_control import (
    DynamicEntry,
    static_batch_reservation,
    static_plan,
    static_request,
)
from milai_lab.methods.state_control import Case, ControlStop, Material, digest


def run(root: Path, *, loopback: bool) -> dict:
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    start = time.monotonic()
    events: list[dict] = []
    result = {"status": "STARTED", "goal_version": "0.5", "actual_generations": 0,
              "H1": "NOT_RUN_UNDER_V05", "H2": "NOT_RUN_UNDER_V05", "H3": "NOT_RUN_UNDER_V05"}
    try:
        config_path = LAB / "configs/v0210-v05-static.json"
        config = json.loads(config_path.read_text())
        plan = static_plan(oracle_registered=config["oracle"] is not None)
        if len(plan) != config["batch_request_limit"] or config["new_generations_authorized"] != 0:
            raise ControlStop("V05_ALLOCATION_MISMATCH")
        case = Case(config["scope"], config["task"], tuple(config["history"]),
                    tuple(config["observations"]), tuple(
                        Material(s["id"], s["version"], config["scope"], s["text"])
                        for s in config["sources"]))
        (root / "host").mkdir()
        (root / "evaluation").mkdir()
        write(root / "config.json", config)
        requests = {}
        for allocation in plan:
            control = "" if allocation.condition == "R0" else "FIXED_DOUBLE_" + allocation.condition
            item = static_request(case, allocation, scope=case.scope, eligible=lambda _: True,
                                  control=control, oracle=config["oracle"], seed=config["seed"])
            requests[allocation.key] = item
            (root / "host" / f"{allocation.key}.json").write_bytes(item.body)
        common = [json.loads(item.body)["messages"][:2] for item in requests.values()]
        assert all(value == common[0] for value in common)
        rubric = LAB / "data/manifests/v0210-v05-static-rubric.json"
        (root / "evaluation/rubric.json").write_bytes(rubric.read_bytes())
        entry_path = LAB / "data/manifests/v0210-v05-dynamic-entry.json"
        entry = json.loads(entry_path.read_text())
        dynamic = DynamicEntry(
            entry["failure_id"], entry["source_id"], entry["origin"], entry["layer"],
            entry["observed_failure"], entry["minimum_intervention"], entry["contrast"],
            entry["prediction"],
        )
        dynamic.check()
        write(root / "dynamic-entry.json", entry)
        result["dynamic_entry"] = {"failure_id": dynamic.failure_id,
                                   "attribution": dynamic.attribution,
                                   "h1_positive_required": False,
                                   "execution_ready": False}
        if loopback:
            observed = tokenize(requests, events=events)
            result["tokenizer"] = observed
            result["static_batch_upper_bound_with_doubles"] = static_batch_reservation(
                plan, observed["prompt_tokens"], raw_limit=config["batch_raw_limit"])
        result["plan"] = [allocation.key for allocation in plan]
        result["actual_controls_need_retokenization"] = True
        result["generation_compatibility"] = "NOT_PROVEN_BY_E0"
        result["material_presentation_equal"] = True
        result["product_artifact"] = verify_baseline(json.loads(
            (LAB / "configs/v0210-control-e1.json").read_text()))
        paths = [Path(__file__).resolve(), config_path, rubric, entry_path,
                 LAB / "src/milai_lab/methods/correctable_control.py",
                 LAB / "src/milai_lab/methods/state_control.py",
                 LAB / "tools/check_v0210_control.py",
                 LAB / "tests/unit/test_correctable_control.py"]
        result["implementation_pin"] = {
            str(p.relative_to(LAB)): digest(p.read_bytes()) for p in paths
        }
        result["status"] = "V05_STATIC_PLAN_PREFLIGHT_COMPLETE_DYNAMIC_ENGINEERING_PENDING"
    except Exception as exc:
        result.update(status="STOPPED", reason=str(exc))
        raise
    finally:
        result["http_events"] = events
        result["preparation_seconds"] = time.monotonic() - start
        write(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tokenize-loopback", action="store_true")
    args = parser.parse_args()
    report = run(args.root.resolve(), loopback=args.tokenize_loopback)
    print(json.dumps({"status": report["status"], "actual_generations": 0}))
