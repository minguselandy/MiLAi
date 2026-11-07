"""The three fixed reserved-query models share one explicit, nonqueued stage contract."""
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def verify_code(protocol):
    base = read(protocol["inherited_runtime_protocol"])
    for binding in base["frozen_code_bindings"]:
        assert Path(binding["frozen"]).read_bytes() == Path(binding["source"]).read_bytes()
    for binding in protocol["code_bindings"]:
        assert Path(binding["frozen"]).read_bytes() == binding["literal_utf8"].encode()


def initial_plan(protocol, method):
    prepared = read(protocol["prepared_receipt"])
    model, = [row for row in protocol["models"] if row["name"] == method]
    name = "reserved64-" + method + "-prediction-v1"
    stage = Path(protocol["stage_directory"])
    plan_path = stage / (name + "-plan.json")
    inference = stage / (name + "-inference.json")
    return {"name":name,"model":method,"protocol":protocol["protocol_file"],
        "checkpoint":model["checkpoint"],"original_selected_checkpoint":model["original_checkpoint"],
        "positions":prepared["positions"],"families":64,"public_inputs":prepared["public_inputs"],
        "output":str(stage/(name+"-output")),"owner":str(stage/(name+"-owner.json")),
        "log":str(stage/(name+".log")),"inference":str(inference),"plan_file":str(plan_path),
        "compute_phase":"milai_a100_reserved64_"+method+"_whole_child_and_parent_20261107_v1",
        "cwd":protocol["cwd"],"environment":protocol["prediction_environment"],
        "argv":[protocol["CUDA_python"],"-u",protocol["attention_wrapper"],
            protocol["SDK_bootstrap"],protocol["HTTP_site_packages"],
            protocol["inference_wrapper"],str(inference),protocol["prediction_entry"],str(plan_path)],
        "continued_from":None,"previous_owner":None,"continuation_serial":0,
        "reflection":None,"unattempted_indices":list(range(prepared["positions"])),
        "automatic_retry":False,"automatic_next_model":False}


def continuation_plan(protocol, method, previous_owner, serial, reflection):
    previous_owner = Path(previous_owner).resolve()
    owner = read(previous_owner)
    assert owner["client_CPU_recorded"] and owner["exit_code"] != 0
    assert all(not Path("/proc",str(owner[k])).exists() for k in ("pid","child_pid"))
    previous = read(owner["plan"])
    assert previous["model"] == method and previous["continuation_serial"]+1 == serial
    driver = read(Path(previous["output"])/"driver.json")
    assert driver["status"] == "FAILED_RETAINED" and len(driver["cases"]) == previous["positions"]
    assert all(case["status"] in ("COMPLETED","FAILED_FIRST_FORWARD","NOT_RUN") for case in driver["cases"])
    indices = [i for i,case in enumerate(driver["cases"]) if case["status"] == "NOT_RUN"]
    assert indices and Path(reflection).is_file()
    base = initial_plan(protocol, method)
    name = base["name"]+f"-continuation-{serial:03d}"
    stage = Path(protocol["stage_directory"])
    plan_path = stage/(name+"-plan.json")
    inference = stage/(name+"-inference.json")
    base.update(name=name,output=str(stage/(name+"-output")),owner=str(stage/(name+"-owner.json")),
        log=str(stage/(name+".log")),inference=str(inference),plan_file=str(plan_path),
        compute_phase=base["compute_phase"]+f"_continuation_{serial:03d}",
        continued_from=previous["output"],previous_owner=str(previous_owner),continuation_serial=serial,
        reflection=str(Path(reflection).resolve()),unattempted_indices=indices)
    base["argv"][-3:] = [str(inference),protocol["prediction_entry"],str(plan_path)]
    return base


def expected_plan(protocol, plan):
    if plan["continuation_serial"]:
        return continuation_plan(protocol,plan["model"],plan["previous_owner"],
            plan["continuation_serial"],plan["reflection"])
    return initial_plan(protocol,plan["model"])


def admission(protocol, plan):
    # Query qualification does not authorize a second inference/HTTP worker.
    for directory in (protocol["LME_stages"],protocol["Mem2Act_stages"]):
        for path in Path(directory).glob("*-owner.json"):
            owner = read(path)
            if Path("/proc",str(owner["pid"])).exists():
                return {"ready":False,"reason":"EXISTING_EXTERNAL_MODEL_HTTP_WORKER_LIVE","owner":str(path),"pid":owner["pid"]}
            assert owner["client_CPU_recorded"] and "exit_code" in owner
            assert not Path("/proc",str(owner["child_pid"])).exists()
    for path in Path(protocol["external_root"]).glob("*-storage-v3-owner.json"):
        owner=read(path)
        if not owner["CPU_recorded_in_original_ledger"]:
            return {"ready":False,"reason":"NAMED_STORAGE_WHOLE_CPU_NOT_YET_SETTLED","owner":str(path)}
        assert all(not Path("/proc",str(owner[k])).exists() for k in ("pid","child_pid"))
    for path in Path(protocol["stage_directory"]).glob("*-owner.json"):
        owner = read(path)
        if any(Path("/proc",str(owner[k])).exists() for k in ("pid","child_pid")):
            return {"ready":False,"reason":"EXISTING_RESERVED64_MODEL_WORKER_LIVE","owner":str(path)}
        assert owner["client_CPU_recorded"] and "exit_code" in owner
    prior_names = [m["name"] for m in protocol["models"]]
    for prior in prior_names[:prior_names.index(plan["model"])]:
        audit = Path(protocol["stage_directory"])/("reserved64-"+prior+"-full-prediction-audit-v1.json")
        if not audit.exists():
            return {"ready":False,"reason":"PRECEDING_MODEL_FULL_PREDICTION_AUDIT_PENDING","file":str(audit)}
        assert read(audit)["passed"]
    prepared = read(protocol["prepared_receipt"])
    assert prepared["families"] == 64 and prepared["positions"] == plan["positions"]
    assert prepared["all_native_candidate_titles_text_queries_purposes_literal_preserved"]
    idle = read(protocol["minimum_required_idle_settlement"])
    assert idle["generation_and_limits_unchanged"] and not idle["native_model_client_parent_or_earlier_CPU_rebilled"]
    return {"ready":True,"reason":"FIXED_MODEL_NATIVE_COHORT_AND_ACTUAL_SINGLE_WORKER_GATES_CLOSED"}
