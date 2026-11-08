"""Reuse original ownership with the exact stopped v2-to-v3 untouched-tail bridge."""
import copy
import importlib.util
import json
import sys
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def load_entry(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def correction_evidence(protocol):
    correction = protocol["observation_wiring_correction"]
    reflection = read(correction["failure_reflection"])
    probe = read(correction["observer_composition_probe"])
    recovered = read(correction["retained_rows_Source_SDK_Reader_audit"])
    assert reflection["passed"] and probe["passed"] and recovered["passed"]
    assert reflection["next_only_native_NOT_RUN_indices"] == list(range(10,451))
    assert reflection["actual_NN_forwards"] == recovered["actual_NN_forwards"] == 68
    assert probe["verifier_before_recorder_failure_propagation_proven"]
    assert probe["actual_functional_assignment_AST_executed_unchanged"]
    assert recovered["all9_complete_original_Source_values_roles_clocks_and_preexisting_Store_state_preserved"]
    assert recovered["actual_native_SDK_entire_delivered_contexts_equal"] == recovered["actual_complete_Reader_requests_literal_equal"] == 8
    assert recovered["physical_step_Store_Saver_byte_snapshots_available"] is False
    assert recovered["reconstructed_state_relabelled_as_actual_capture"] is False
    return correction,reflection


def original_owner(protocol):
    original = read(protocol["execution_wiring_correction"]["predecessor_protocol"])
    return load_entry("unchanged_lme_owner_v1_for_v3",original["frozen_owner_entry"])


def continuation_plan(protocol,initial_name,previous_owner,serial,reflection):
    correction,failure = correction_evidence(protocol)
    base = protocol["initial_stage_plans"][initial_name]
    prior = read(previous_owner)
    prior_plan = read(prior["plan"])
    assert base["stage_kind"] in {"prediction","scoring"}
    assert prior_plan.get("initial_stage",prior_plan["name"]) == initial_name
    assert prior["client_CPU_recorded"]
    assert all(not Path("/proc",str(prior[k])).exists() for k in ("pid","child_pid"))
    driver = read(Path(prior_plan["output"])/"driver.json")
    bridge = prior_plan["protocol"] != base["protocol"]
    if bridge:
        predecessor = read(correction["predecessor_protocol"])
        assert initial_name == "primary-seed0-u32-prediction451-v1" and serial == 2
        assert prior_plan["protocol"] == correction["predecessor_protocol"]
        previous_entry = load_entry("unchanged_lme_owner_v2_for_bridge_validation",predecessor["frozen_owner_entry"])
        expected = previous_entry.continuation_plan(predecessor,initial_name,prior_plan["previous_owner"],
            prior_plan["continuation_serial"],prior_plan["reflection"])
        assert prior_plan == expected
        assert Path(previous_owner).resolve() == Path(failure["actual_owner"]).resolve()
        assert Path(reflection).resolve() == Path(correction["failure_reflection"]).resolve()
        assert driver["cases"][:10] == failure["retained_first_case_records"]
    assert driver["status"] == "FAILED" and len(driver["cases"]) == 451
    assert driver["schema"] == ("lme_prediction_cohort_v2" if base["stage_kind"]=="prediction" else "lme_scoring_cohort_v2")
    untouched = "NOT_RUN" if base["stage_kind"]=="prediction" else "UNSCORED_COMPLETED"
    positions = [i for i,c in enumerate(driver["cases"]) if c["status"]==untouched]
    assert positions and Path(reflection).is_file() and serial == prior_plan.get("continuation_serial",0)+1
    if bridge:
        assert positions == failure["next_only_native_NOT_RUN_indices"]
    name = f"{initial_name}-continuation-{serial:03d}"
    stage_root = Path(protocol["stage_directory"])
    plan = copy.deepcopy(base)
    plan.update(name=name,initial_stage=initial_name,previous_owner=str(Path(previous_owner).resolve()),
        continued_from=prior_plan["output"],unattempted_indices=positions,
        reflection=str(Path(reflection).resolve()),continuation_serial=serial,
        output=str(stage_root/(name+"-output")),owner=str(stage_root/(name+"-owner.json")),
        log=str(stage_root/(name+".log")),budget_before_snapshot=str(stage_root/(name+"-budget-before.json")),
        client_compute_phase=base["client_compute_phase"]+f"-continuation-{serial:03d}")
    plan["argv"][plan["argv"].index(base["output"])] = plan["output"]
    if base["stage_kind"]=="prediction":
        plan["inference"] = str(stage_root/(name+"-inference.json"))
        plan["argv"][plan["argv"].index(base["inference"])] = plan["inference"]
    plan["argv"].extend(["--continue-unattempted",prior_plan["output"]])
    return plan


if __name__ == "__main__":
    protocol = read(read(sys.argv[1])["protocol"])
    correction_evidence(protocol)
    owner = original_owner(protocol)
    owner.continuation_plan = continuation_plan
    owner.main()
