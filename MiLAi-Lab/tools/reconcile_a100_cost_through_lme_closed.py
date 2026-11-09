"""Reconcile a saved pre-Mem2Act snapshot with all closed LME, storage and idle costs."""
import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def close(left, right):
    assert math.isclose(left, right, rel_tol=0, abs_tol=1e-7), (left, right)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root))
    from offline_time_receipts import read_timer

    external = root / "external-own-policy-v1"
    previous_path = root / "known-paid-cost-cutoff-before-LME007-v1.json"
    previous = read(previous_path)
    before_path = Path(previous["closed_ledger_snapshot"])
    before = read(before_path)
    mem_plan = read(external / "stages-mem2act-v1/fixed-prefix-prediction400-v1-plan.json")
    protocol = read(mem_plan["protocol"])
    after_path = Path(mem_plan["budget_before_snapshot"])
    assert after_path.resolve() != Path(protocol["original_ledger"]).resolve()
    assert before_path.resolve() != Path(protocol["original_ledger"]).resolve()
    after = read(after_path)
    assert mem_plan["client_compute_phase"] not in after["compute"]
    assert before["limits"] == after["limits"] and before["embedding"] == after["embedding"]
    assert set(before["compute"]) <= set(after["compute"])
    added = {key:value for key,value in after["compute"].items() if key not in before["compute"]}
    changed = {key for key in before["compute"] if before["compute"][key] != after["compute"][key]}
    assert changed == {"dynamic_memory_laya", "dynamic_memory_laya_load"}
    assert all("a100" in key.lower() and value["runs"] == 1 for key,value in added.items())
    generic = {key:{field:after["compute"][key][field]-before["compute"][key][field]
        for field in after["compute"][key]} for key in sorted(changed)}
    generic_cpu = sum(value["cpu_seconds"] for value in generic.values())
    assert generic["dynamic_memory_laya"]["forwards"] == 3594
    assert generic["dynamic_memory_laya"]["input_tokens"] == 25070604
    assert generic["dynamic_memory_laya_load"]["loads"] == 51

    native, new_native = [], []
    for path in sorted((external / "stages-lme-v1").glob("*-owner.json")):
        owner = read(path)
        plan = read(owner["plan"])
        assert owner["client_CPU_recorded"] and "exit_code" in owner
        assert all(not Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
        phase = owner["client_compute_phase"]
        paid = after["compute"][phase]
        assert paid["runs"] == 1
        assert paid["cpu_seconds"] == owner["client_CPU_residual"]+owner["parent_CPU_seconds_through_billing"]
        close(owner["client_CPU_residual"]+sum(owner["already_recorded_native_CPU"].values()), owner["whole_child_CPU_seconds"])
        assert owner["new_unknown_usage"] == {"generation":0,"embedding":0}
        row = dict(owner=str(path), phase=phase, stage_kind=plan["stage_kind"], name=plan["name"],
            actual_exit_code=owner["exit_code"], native_CPU_components=owner["already_recorded_native_CPU"],
            already_recorded_native_CPU=sum(owner["already_recorded_native_CPU"].values()),
            named_client_residual_plus_parent_CPU=paid["cpu_seconds"],
            whole_child_plus_measured_parent_CPU=owner["whole_child_CPU_seconds"]+owner["parent_CPU_seconds_through_billing"],
            shared_generation_admissions=owner["shared_generation_admissions"], known_generation_tokens=owner["known_generation_tokens"],
            included_in_previous_cutoff=phase in before["compute"])
        native.append(row)
        if phase not in before["compute"]:
            new_native.append(row)
    assert len(native) == 106 and len(new_native) == 99
    assert len({row["phase"] for row in native}) == len(native)
    native_generic = Counter()
    for row in new_native:
        native_generic.update(row["native_CPU_components"])
    assert set(native_generic) == changed
    for key in changed:
        close(native_generic[key], generic[key]["cpu_seconds"])
    close(sum(row["whole_child_plus_measured_parent_CPU"] for row in new_native),
        sum(row["named_client_residual_plus_parent_CPU"] for row in new_native)+generic_cpu)
    assert sum(row["shared_generation_admissions"] for row in native) == 1164
    assert sum(row["known_generation_tokens"] for row in native) == 6111718
    generation = {key:after["generation"][key]-before["generation"][key] for key in before["generation"]}
    assert generation["known_tokens"] == generation["charged_tokens"] == sum(row["known_generation_tokens"] for row in new_native)
    assert generation["unknown_usage"] == 0
    reservations = after["generation_requests"]-before["generation_requests"]
    assert reservations == sum(row["shared_generation_admissions"] for row in new_native)

    storage_by_phase = {}
    for path in external.glob("*-storage-v3-owner.json"):
        owner = read(path)
        assert owner["CPU_recorded_in_original_ledger"] and "exit_code" in owner
        assert all(not Path("/proc", str(owner[key])).exists() for key in ("pid", "child_pid"))
        phase = owner["cost_phase"]
        assert phase not in storage_by_phase
        storage_by_phase[phase] = (path, owner)
    prior_timers = set()
    for version in range(1,37):
        receipt = read(root / f"idle-cost-settlement-v{version}.json")
        prior_timers.update(str(Path(command["path"]).resolve()) for command in receipt["new_commands" if version == 1 else "commands"])
    idle_rows, storage_rows, commands = [], [], []
    seen_timers = set(prior_timers)
    for version in range(37,138):
        receipt_path = root / f"idle-cost-settlement-v{version}.json"
        receipt = read(receipt_path)
        assert receipt["generation_and_limits_unchanged"] and not receipt["native_model_client_parent_or_earlier_CPU_rebilled"]
        phase = receipt["phase"]
        assert phase in added and after["compute"][phase]["runs"] == 1
        assert after["compute"][phase]["cpu_seconds"] == receipt["CPU_seconds"]
        close(sum(command["CPU_seconds"] for command in receipt["commands"]), receipt["CPU_seconds"])
        for command in receipt["commands"]:
            path = str(Path(command["path"]).resolve())
            assert path not in seen_timers
            seen_timers.add(path)
            actual = read_timer(path)
            assert actual == command and actual["known_exit_code"] is not None
            commands.append(dict(actual_idle=version, **actual))
        idle_rows.append(dict(version=version, receipt=str(receipt_path), phase=phase,
            CPU_seconds=receipt["CPU_seconds"], closed_commands=len(receipt["commands"])))
        if "separate_storage_phase" in receipt:
            phase = receipt["separate_storage_phase"]
            assert phase in added
            path, owner = storage_by_phase[phase]
            cpu = owner["whole_child_CPU_seconds"]+owner["parent_CPU_seconds_through_receipt"]
            assert cpu == receipt["separate_storage_CPU_seconds"] == after["compute"][phase]["cpu_seconds"]
            assert after["compute"][phase]["runs"] == 1
            assert Path(owner["actual_CPU_settlement_receipt"]).resolve() == receipt_path.resolve()
            storage_rows.append(dict(phase=phase, owner=str(path), actual_idle=version,
                actual_exit_code=owner["exit_code"], whole_child_plus_measured_parent_CPU=cpu,
                native_or_model_HTTP_calls=owner["model_HTTP_calls"]))
    assert len(idle_rows) == 101 and len(storage_rows) == 95
    groups = {
        "native_LME_client_residual_plus_measured_parent": [row["phase"] for row in new_native],
        "ordinary_offline_closed_GNU_timers": [row["phase"] for row in idle_rows],
        "separate_whole_storage_client_and_measured_parent": [row["phase"] for row in storage_rows],
    }
    all_phases = [phase for phases in groups.values() for phase in phases]
    assert len(all_phases) == len(set(all_phases)) == len(added) == 295
    assert set(all_phases) == set(added)
    new_named_cpu = sum(value["cpu_seconds"] for value in added.values())
    new_total = new_named_cpu+generic_cpu
    group_cpu = {name:sum(added[phase]["cpu_seconds"] for phase in phases) for name,phases in groups.items()}
    close(new_named_cpu, sum(group_cpu.values()))
    close(new_total, sum(row["whole_child_plus_measured_parent_CPU"] for row in new_native)
        +sum(row["CPU_seconds"] for row in idle_rows)+sum(row["whole_child_plus_measured_parent_CPU"] for row in storage_rows))
    named = {key:value for key,value in after["compute"].items() if "a100" in key.lower()}
    assert len(named) == previous["named_current_goal_phase_count"]+len(added) == 418
    debt = previous["excluded_carried_v79_debt_CPU"]
    named_goal_cpu = sum(value["cpu_seconds"] for value in named.values())-debt
    generic_goal_cpu = previous["generic_native_CPU_total"]+generic_cpu
    known_goal_cpu = named_goal_cpu+generic_goal_cpu
    close(known_goal_cpu, previous["known_new_goal_CPU_paid_through_cutoff"]+new_total)
    earliest = read(previous["earliest_new_functional_budget_source"])["budget_before"]
    assert earliest["ledger_revision"] == previous["earliest_functional_ledger_revision"]
    assert {key for key in earliest["compute"] if "a100" in key.lower()} == {
        "milai_a100_p0_bf16_reload_20261104", "milai_a100_p0_bf16_seed0_20261104",
        "milai_a100_p0_float32_reload_20261104", "milai_a100_p0_float32_seed0_20261104"}
    previous_generic = {key:values.get("cpu_seconds",0)-earliest["compute"].get(key,{}).get("cpu_seconds",0)
        for key,values in before["compute"].items()
        if "a100" not in key.lower() and values.get("cpu_seconds",0) != earliest["compute"].get(key,{}).get("cpu_seconds",0)}
    assert set(previous_generic) == changed
    assert sum(previous_generic.values()) == previous["generic_native_CPU_total"]
    previous_edges = previous["all_generic_delta_attribution_edges"]
    assert len({edge["source"] for edge in previous_edges}) == 20
    for edge in previous_edges:
        evidence = read(edge["source"])
        if "native_CPU_by_phase" in edge:
            assert evidence["already_recorded_native_CPU"] == edge["native_CPU_by_phase"]
            assert sum(evidence["already_recorded_native_CPU"].values()) == edge["generic_native_CPU_seconds"]
        elif Path(edge["source"]).name == "c-handoff8-quality-review.json":
            legacy = read(root.parent.parent / "data/manifests/a100-development-progress-20261106-v30.json")
            assert legacy["cost"]["C_native_CPU_already_recorded"] == edge["generic_native_CPU_seconds"]
        else:
            assert Path(edge["source"]).name in {"known-View-control-closeout-v1.json", "old-output-control-closeout-v1.json"}
            assert evidence["native_local_and_load_CPU_seconds_already_paid"] == edge["generic_native_CPU_seconds"]
    assert sum(edge["generic_native_CPU_seconds"] for edge in previous_edges) == sum(previous_generic.values())
    known_host = after["generation"]["known_tokens"]-earliest["generation"]["known_tokens"]
    assert known_host == previous["known_Host_generation_tokens_since_first_functional_request"]+generation["known_tokens"]
    assert known_host == after["generation"]["charged_tokens"]-earliest["generation"]["charged_tokens"]
    assert after["generation"]["unknown_usage"] == earliest["generation"]["unknown_usage"]
    assert after["embedding"] == earliest["embedding"] and after["limits"] == earliest["limits"]
    for path in protocol["prior_external_stage_closures"]:
        closure = read(path)
        assert closure["passed"] and closure["positions"] == 451
    assert len(protocol["prior_external_stage_closures"]) == 6
    output = dict(status="KNOWN_PAID_GOAL_COST_THROUGH_ALL_SIX_LME_CLOSURES_AND_IDLE137_BEFORE_MEM2ACT",
        timestamp_utc=datetime.now(timezone.utc).isoformat(), previous_exact_cutoff=str(previous_path),
        previous_snapshot=str(before_path), closed_snapshot=str(after_path),
        cutoff="Immediately before frozen Mem2Act fixed400 child launch; all LME native stages and idle137 closed. No current ledger read.",
        previous_known_paid_goal_CPU_seconds=previous["known_new_goal_CPU_paid_through_cutoff"],
        previous_cutoff_all20_generic_native_attribution_edges_reread_from_actual_sources=True,
        new_named_phases=295, named_phase_count_through_cutoff=418, excluded_carried_old_debt_CPU_seconds=debt,
        new_named_CPU_seconds=new_named_cpu, new_generic_native_CPU_seconds=generic_cpu,
        new_whole_CPU_seconds=new_total, named_goal_CPU_seconds=named_goal_cpu,
        generic_goal_CPU_seconds=generic_goal_cpu, known_paid_goal_CPU_seconds=known_goal_cpu,
        known_paid_goal_CPU_hours=known_goal_cpu/3600, mutually_exclusive_new_named_CPU_by_group=group_cpu,
        new_native_LME_whole_child_and_parent_CPU_seconds=sum(row["whole_child_plus_measured_parent_CPU"] for row in new_native),
        old_cutoff_native_LME_segments_excluded_from_delta=len(native)-len(new_native),
        all_closed_native_LME_client_phases=106, newly_closed_native_LME_client_phases=99,
        all_closed_LME_native_HTTP=1164, all_closed_LME_native_known_tokens=6111718,
        new_Host_known_generation_tokens=generation["known_tokens"], new_generation_reservation_counter=reservations,
        known_Host_generation_tokens_since_first_functional_request=known_host,
        generation_reservation_counter_since_first_functional_request=after["generation_requests"]-earliest["generation_requests"],
        reservation_counter_scope="Original RunBudget reserve count. This LME delta independently equals actual owner admissions; do not rename all historical reserves as HTTP or local NN calls.",
        generic_native_field_deltas=generic, all_generic_CPU_delta_explained_by_closed_native_owners=True,
        all295_added_compute_phases_explained_once=True, ordinary_idle_settlements=101,
        separate_storage_phases=95, closed_ordinary_GNU_timers=len(commands),
        retained_failed_GNU_timers=sum(command["known_exit_code"] != 0 for command in commands),
        no_ordinary_timer_paid_twice_across_cutoff=True, all_source_timers_literal_equal_actual_closed_files=True,
        new_unknown_generation_usage=0, legacy_unknown_generation_retained=after["generation"]["unknown_usage"],
        embedding_state_literal_unchanged=True, legacy_unknown_embedding_retained=after["embedding"]["unknown_usage"],
        limits_literal_unchanged=True, all_six_LME_canonical_closures_closed=True,
        named_phase_groups=groups, added_named_compute_records=added, native_owners=native,
        newly_closed_native_owners=new_native, idle_receipts=idle_rows, separate_storage_owners=storage_rows,
        ordinary_timer_receipts=commands,
        exclusions="Current Mem2Act fixed400/primary400 and post137 ordinary timers remain outside this snapshot, including v175/v176 and actual failed-row Source audit/v2 observation freeze. Unmetered author/launcher/inspection/cleanup CPU remains unknown_not_zero; lost old-output parent/cleanup remains unknown, not upgraded from the199.51 child lower bound. Historical base model/data amortization, HostGPU0/1 busy time and monetary cost unmeasured or separate. This is a known-paid cutoff, not complete true project cost or a second operational ledger.",
        new_charge_reset_refund_or_operational_ledger=False, new_model_HTTP_or_business_calls=0,
        original_live_ledger_opened_or_written=False, no_sha_validation=True, goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(output, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("LME_CLOSED_EXACT_PAID_CUTOFF", "295phases=99native+101idle+95storage;CPU", known_goal_cpu,
        "hours", known_goal_cpu/3600, "Hostknown", known_host, "newgeneric", generic_cpu, "newwhole", new_total)


if __name__ == "__main__":
    main()
