"""Reuse frozen LME ownership with one declared bridge for the corrected untouched tail."""
import copy
import importlib.util
import json
import sys
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def correction_evidence(protocol):
    correction = protocol["execution_wiring_correction"]
    reflection = read(correction["failure_reflection"])
    probe = read(correction["configuration_probe"])
    assert reflection["passed"] and probe["passed"]
    assert reflection["actual_NN_forwards"] == reflection["actual_HTTP_calls"] == 0
    assert reflection["untouched_indices"] == list(range(1, 451))
    assert probe["new_adapter_diff_is_only_complete_config_assembly"]
    assert probe["original_bound_adapter_changed"] is False
    return correction, reflection


def original_owner(protocol):
    predecessor = read(protocol["execution_wiring_correction"]["predecessor_protocol"])
    spec = importlib.util.spec_from_file_location("unchanged_lme_owner_v1", predecessor["frozen_owner_entry"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def continuation_plan(protocol, initial_name, previous_owner, serial, reflection):
    correction, failure = correction_evidence(protocol)
    base = protocol["initial_stage_plans"][initial_name]
    prior = read(previous_owner)
    prior_plan = read(prior["plan"])
    assert base["stage_kind"] in {"prediction", "scoring"}
    assert prior_plan.get("initial_stage", prior_plan["name"]) == initial_name
    assert prior["client_CPU_recorded"]
    assert all(not Path("/proc", str(prior[k])).exists() for k in ("pid", "child_pid"))
    if prior_plan["protocol"] != base["protocol"]:
        predecessor = read(correction["predecessor_protocol"])
        assert initial_name == "primary-seed0-u32-prediction451-v1" and serial == 1
        assert prior_plan == predecessor["initial_stage_plans"][initial_name]
        assert Path(previous_owner).resolve() == Path(failure["actual_owner"]).resolve()
        assert Path(reflection).resolve() == Path(correction["failure_reflection"]).resolve()
        assert read(Path(prior_plan["output"]) / "driver.json")["cases"][0] == failure["native_first_failed_case"]
    driver = read(Path(prior_plan["output"]) / "driver.json")
    assert driver["status"] == "FAILED" and len(driver["cases"]) == 451
    assert driver["schema"] == ("lme_prediction_cohort_v2" if base["stage_kind"] == "prediction" else "lme_scoring_cohort_v2")
    untouched = "NOT_RUN" if base["stage_kind"] == "prediction" else "UNSCORED_COMPLETED"
    positions = [i for i, case in enumerate(driver["cases"]) if case["status"] == untouched]
    assert positions and Path(reflection).is_file() and serial == prior_plan.get("continuation_serial", 0) + 1
    if prior_plan["protocol"] != base["protocol"]:
        assert positions == failure["untouched_indices"]
    name = f"{initial_name}-continuation-{serial:03d}"
    stage_root = Path(protocol["stage_directory"])
    plan = copy.deepcopy(base)
    plan.update(name=name, initial_stage=initial_name, previous_owner=str(Path(previous_owner).resolve()),
        continued_from=prior_plan["output"], unattempted_indices=positions,
        reflection=str(Path(reflection).resolve()), continuation_serial=serial,
        output=str(stage_root / (name + "-output")), owner=str(stage_root / (name + "-owner.json")),
        log=str(stage_root / (name + ".log")),
        budget_before_snapshot=str(stage_root / (name + "-budget-before.json")),
        client_compute_phase=base["client_compute_phase"] + f"-continuation-{serial:03d}")
    plan["argv"][plan["argv"].index(base["output"])] = plan["output"]
    if base["stage_kind"] == "prediction":
        plan["inference"] = str(stage_root / (name + "-inference.json"))
        plan["argv"][plan["argv"].index(base["inference"])] = plan["inference"]
    plan["argv"].extend(["--continue-unattempted", prior_plan["output"]])
    return plan


if __name__ == "__main__":
    protocol = read(read(sys.argv[1])["protocol"])
    correction_evidence(protocol)
    owner = original_owner(protocol)
    owner.continuation_plan = continuation_plan
    owner.main()
