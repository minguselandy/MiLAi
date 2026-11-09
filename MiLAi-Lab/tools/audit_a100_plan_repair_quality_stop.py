"""Reconcile original repair judgments, unknown masks, paired statistics and bounded stop."""
import argparse
import json
import math
import random
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def direction(left,right,known=True,material=False):
    if not known or left in ("failed","unknown") or right in ("failed","unknown"):
        return "unknown"
    rank = {"insufficient":0,"sufficient":1} if material else {"incorrect":0,"incomplete":1,"qualified":2,"complete":3}
    return "left" if rank[left] > rank[right] else "right" if rank[left] < rank[right] else "tie"


def paired(values,families):
    assert len(values) == len(set(families))
    differences = [float(left)-float(right) for left,right in values]
    rng = random.Random(0)
    draws = sorted(sum(rng.choices(differences,k=len(values)))/len(values) for _ in range(20000))
    return dict(families=len(values),gains=sum(left and not right for left,right in values),
        losses=sum(right and not left for left,right in values),
        difference_percentage_points=100*sum(differences)/len(values),
        family_bootstrap_95_percent_interval_pp=[100*draws[499],100*draws[19499]],draws=20000,seed=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    packet = read(root/"b-c-repair-quality-review-input-v1.json")
    reproduced = read(root/"original-plan-repair66-review-input-replay-v1.json")
    assert packet == reproduced
    notes = read(root/"b-c-repair-quality-review-all66-notes-v1.json")["records"]
    decisions = read(root/"b-c-repair-source-author-decisions-v1.json")
    summary = read(root/"b-c-repair-quality-closeout-v1.json")
    old = Path("/cra/memory/mx_memory/MiLAi-worktrees/evidence-gap-development-20261023/MiLAi-Lab/artifacts/development-training-20261102")
    retained = {value["readout"]:value
        for name in ("e3-origin-compiler-v1/pilot-reviews-v1.json","e3-remaining48-reached-branches-v1/reviews-v1.json")
        for record in read(old/name)["records"] for value in record["outcomes"].values()}
    assert [record["index"] for record in decisions] == list(range(66))
    assert len(notes) == len(packet["records"]) == 66
    unknown_pairs = []
    for actual,note,decision in zip(packet["records"],notes,decisions,strict=True):
        for field in ("index","component","component_index","family"):
            assert decision[field] == actual[field]
        assert decision["rationale"] == note["rationale"] and note["whole_new_answer_and_packet_read"]
        assert decision["actual_answer_and_packet_whole_read"] and decision["source_author_not_independent_or_blind"]
        assert decision["new_training_label_exported"] is False
        assert (decision["answer_status"] == "failed") == (actual["actual_new_readout_status"] == "FAILED")
        assert decision["complete"] == (decision["answer_status"] == "complete")
        assert actual["new_quality_labels"] is None and actual["comparison_quality_labels"] is None
        assert decision["task_guide_reference_status"] == actual["source_grounded_task_guide"]["reference_status"]
        if actual["component"] == "B52":
            previous = actual["actual_retained_comparison"]
            original = retained[previous["origin"]["readout"]]
            assert decision["retained_original_judgment"] == original
            assert original["action"] == previous["action"]
            assert (original["answer_status"] == "failed") == (previous["readout_status"] == "FAILED")
            comparison = dict(answer=direction(decision["answer_status"],original["answer_status"],known=decision["answer_quality_known"]),
                delivery=direction(decision["material_status"],original["material_status"],material=True))
            assert comparison == decision["comparison_quality_before_resource_tiebreak"]
            if comparison["answer"] == "unknown":
                unknown_pairs.append(actual["index"])
    b,c = decisions[:52],decisions[52:]
    assert b[2]["material_status"] == "unknown" and b[2]["answer_quality_known"] is False
    assert len(unknown_pairs) == 6
    for records,part in ((b,summary["B52"]),(c,summary["C7"])):
        assert dict(Counter(record["answer_status"] for record in records)) == part["answer_statuses"]
        assert dict(Counter(record["material_status"] for record in records)) == part["material_statuses"]
    for name in ("answer","delivery"):
        assert dict(Counter(row["comparison_quality_before_resource_tiebreak"][name] for row in b)) == summary["B52"][name+"_quality_comparisons"]
    bstats = paired([(row["complete"],row["retained_original_judgment"]["complete"]) for row in b],
        [row["family"] for row in b])
    for key,value in bstats.items():
        assert value == summary["B52"]["complete_success_comparison_new_minus_retained"][key]
    cpairs = []
    for index in range(7):
        rules,e3 = [row for row in c if row["state_index"] == index]
        assert rules["method"] == "rules" and e3["method"] == "e3-aggregate-u32" and rules["family"] == e3["family"]
        cpairs.append(dict(state_index=index,family=rules["family"],left="rules",right="e3-aggregate-u32",
            answer=direction(rules["answer_status"],e3["answer_status"]),
            delivery=direction(rules["material_status"],e3["material_status"],material=True),
            rules_complete=rules["complete"],E3_complete=e3["complete"]))
    assert cpairs == summary["C7"]["pairs"]
    cstats = paired([(row["E3_complete"],row["rules_complete"]) for row in cpairs],[row["family"] for row in cpairs])
    for key,value in cstats.items():
        assert value == summary["C7"]["complete_success_E3_minus_rules"][key]
    sensitivity = summary["C7"]["heading_only_sensitivity"]
    heading = decisions[sensitivity["case_index"]]
    assert heading["index"] == 62 and heading["method"] == "rules" and heading["complete"]
    assert sum(row["complete"] for row in c if row["method"] == "rules")-1 == sensitivity["stricter_no_heading_credit_rules_complete"] == 2
    assert sum(row["complete"] for row in c if row["method"] == "e3-aggregate-u32") == sensitivity["E3_complete"] == 2

    coverage = read(root/"b-repair-binding-coverage-v1.json")
    frozen_read = read(root/"b-repair-remaining-observed-READ-bindings-v1.json")
    nomination = read(root/"b-repair-read52-nomination-proof-v1.json")["records"]
    executed = read(root/"b-repair-read52-full-binding-v1.json")["records"]
    covered_before = {row["capture"] for row in coverage["states"] if row["observed_Source_READ_bindings_executed"]}
    repaired = set()
    for reserved,nominated,actual in zip(frozen_read["bindings"],nomination,executed,strict=True):
        assert reserved["capture"] == nominated["capture"] and reserved["action"] == actual["action"]
        assert reserved["family"] == actual["family"]
        repaired.add(reserved["capture"])
    all57 = {row["capture"] for row in coverage["states"]}
    assert len(repaired) == 52 and len(covered_before) == 5 and not repaired & covered_before
    assert repaired | covered_before == all57 and len(all57) == 57
    assert coverage["new_READ_branch_ceiling"]["functional_actual_READs"]+len(repaired) == 57

    pools = read(root/"c-repair-acquired-pool-reservation-v1.json")
    functional = read(root/"b-functional8-actual-nominations.json")
    c8 = read(root/"c-handoff8-selection.json")["selected"]
    prior_pools = {row["capture"] for row in functional if row["action"]["kind"] == "HANDOFF"}|{row["capture"] for row in c8}
    c7plan = read(root/"c-repair7-native-v1/execution-plan-v1.json")
    new_pools = {row["capture"] for row in pools["selected"]}
    assert len(prior_pools) == pools["existing_unique_acquired_states"] == 11
    assert len(new_pools) == 7 and not new_pools & prior_pools and len(new_pools|prior_pools) == 18 <= 24
    assert {row["original_capture"] for row in c7plan["states"]} == new_pools
    assert pools["breakdown"] == {"functional_HANDOFF":3,"C8_original_HTTP":24,"C8_saved_new_HTTP":6}
    assert sum(pools["breakdown"].values())+14 == pools["maximum_total_new_acquired_readouts"] == 47 <= 48
    owners = [read(root/"b-repair-read52-owner-v1.json"),read(root/"c-repair7-native-v1/owner-v1.json")]
    for owner in owners:
        assert owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        assert not Path("/proc",str(owner["child_pid"])).exists()
        assert math.isclose(sum(owner["already_recorded_native_CPU"].values())+owner["client_CPU_residual"],owner["whole_child_CPU_seconds"],abs_tol=1e-8)
        assert owner["new_unknown_usage"] == {"generation":0,"embedding":0}
    closed = read(root/"b-c-repair-full-closeout-v1.json")
    assert sum(owner["actual_new_HTTP"] for owner in owners) == closed["actual_new_Host_HTTP_already_paid"] == 66
    assert sum(owner["actual_known_generation_tokens"] for owner in owners) == closed["actual_known_Host_tokens_already_paid"] == 253042
    assert closed["new_fits"] == closed["new_training_rows"] == 0 and closed["menu_expansion"] is False
    assert closed["whole_children_CPU_seconds_already_paid"] == sum(owner["whole_child_CPU_seconds"] for owner in owners)
    assert closed["parent_CPU_seconds_measured_through_billing_already_paid"] == sum(owner["parent_CPU_seconds_measured_through_billing"] for owner in owners)
    out = dict(passed=True,status="ORIGINAL_B_REPAIR_C_SOURCE_AUTHOR_JUDGMENTS_UNKNOWN_MASKS_EARLIEST_RESULTS_STATISTICS_BUDGET_AND_STOP_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),whole66_actual_answers_packets_Source_guides_reproduced_literal_equal=True,
        original52_retained_judgments_entire_literal_preserved=True,source_author_not_independent_or_blind=True,
        original57_states=57,original_source_families=56,observed_Source_READ_states_before_repair=5,
        new52_all_missing_original_before_states_repaired=True,observed_Source_READ_states_after_repair=57,
        new_READ_budget=dict(functional5=5,remaining52=52,total57=57,ceiling57=57),
        B52_answer_statuses=summary["B52"]["answer_statuses"],B52_material_statuses=summary["B52"]["material_statuses"],
        B52_complete_new=15,B52_complete_retained=18,B52_answer_directions=summary["B52"]["answer_quality_comparisons"],
        B52_unknown_answer_pair_indices=unknown_pairs,B52_paired_complete_statistics=bstats,
        C7_complete=dict(rules=3,E3=2,denominator=7),C7_paired_complete_statistics=cstats,
        C7_heading_only_sensitivity=sensitivity,C_acquired_pool_budget=dict(prior11=11,new7=7,total18=18,ceiling24=24),
        C_readout_budget=dict(functional3=3,original24=24,saved6=6,new14=14,total47=47,ceiling48=48),
        B52_and_C7_original_native_HTTP_already_paid=66,B52_and_C7_original_known_Host_tokens_already_paid=253042,
        original_whole_child_CPU_seconds_already_paid=closed["whole_children_CPU_seconds_already_paid"],
        original_measured_parent_CPU_seconds_already_paid=closed["parent_CPU_seconds_measured_through_billing_already_paid"],
        native_NN_load_whole_parent_not_double_added=True,new_fit_menu_expansion_quota_fill_or_adoption=False,
        scope="Actual exposed TRAIN Source-author review reconciliation and descriptive family bootstrap. Failures remain complete-success denominator failures while answer-comparison unknowns remain unknown. C/B families overlap;66 is a count of new branch results, not independent confirmation tasks.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        original_inputs_labels_or_first_results_changed=False,full763_line_completion_proven=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,goal_complete=False)
    with args.output.open("x") as stream:
        json.dump(out,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("B57_READ_C18POOLS_47READOUTS_SOURCE_AUTHOR_QUALITY_AND_STOP_VERIFIED",flush=True)


if __name__ == "__main__":
    main()
