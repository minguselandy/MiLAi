"""Reconcile all D first-answer reviews, received Views, reused baseline states and family results."""
import argparse
import ast
import json
import sys
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from audit_a100_plan_d_controls import functions
from audit_a100_plan_d_existing_execution import read,replay


def anchors(row,decision,views):
    failed = decision["answer_grade"] == "F"
    messages = row["failed_last_provider_messages"] if failed else row["actual_final_provider_messages"]
    material = row["failed_last_source_material_binding"] if failed else row["actual_source_material_binding"]
    actual = []
    for mi,ei,si,quote in decision["source_anchors"]:
        assert messages[mi]["role"] == "tool"
        piece = json.loads(messages[mi]["content"])["evidence"][ei]["evidence"][si]
        assert quote in piece["content"]
        binding, = [binding for binding in material["visible_original_ranges"]
            if (binding["message_index"],binding["evidence_index"],binding["source_index"]) == (mi,ei,si)]
        assert binding["metadata_matched_source_candidates"]
        actual.append(dict(message_index=mi,evidence_index=ei,source_index=si,quote=quote,
            role=piece["role"],origin=piece["origin"],source_candidates=binding["metadata_matched_source_candidates"],
            source_groups=binding["metadata_source_groups"]))
    assert actual == decision["bound_source_anchors"]
    actual_views = []
    for mi,ei,node_id,quote in decision.get("view_anchors",[]):
        evidence = json.loads(messages[mi]["content"])["evidence"][ei]
        assert evidence["kind"] == "query_structure" and evidence["builder"] == "extractive"
        assert quote in evidence["interpretation"]["nodes"][node_id]["text"]
        occurrence, = [view for view in views if (view["case_index"],view["message_index"],view["evidence_index"])
            == (decision["index"],mi,ei)]
        node, = [node for node in occurrence["nodes"] if node["node_id"] == node_id]
        assert all(source["literal_full_body_match"] and all(source["metadata_checks"].values()) for source in node["source_bindings"])
        actual_views.append(dict(message_index=mi,evidence_index=ei,node_id=node_id,quote=quote,
            sources=[dict(source_ref=source["source_ref"],role=source["source"]["role"],source_group=source["source_group"])
                for source in node["source_bindings"]]))
    if actual_views:
        assert actual_views == decision["bound_view_anchors"]
    assert not decision.get("generated_view_anchors",[])
    assert decision["material_input_boundary"] == ("failed_last_responded_request" if failed else "completed_final_input")
    for quote in decision["answer_issue_quotes"]:
        assert quote in row["answer"]
    required = row["source_criterion"]["explicit_original_quotes_required"]
    if not required:
        assert decision["explicit_original_quote_obligation_satisfied"] is None
    elif decision["answer_grade"] == "C":
        assert decision["explicit_original_quote_obligation_satisfied"] is True
    return len(actual),len(actual_views)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output",type=Path)
    args = parser.parse_args()
    root,output = args.root.resolve(),args.output.resolve()
    output.mkdir()
    import tokenizers
    import transformers

    assert transformers.__version__ == "4.52.3" and tokenizers.__version__ == "0.21.4"
    sys.path.append("/cra/memory/mx_memory/MiLAi-worktrees/jev-read-decisions-20261016/MiLAi-Lab/artifacts/jev-reader/http-env/lib/python3.11/site-packages")
    runtime = root/"runtime-d-update32"
    sys.path[:0] = [str(runtime/"tools"),str(runtime/"src")]
    old = Path("/cra/memory/mx_memory/MiLAi-worktrees/evidence-gap-development-20261023/MiLAi-Lab/artifacts/development-training-20261102/e5-controlled-lifecycle-v1")
    current_tools = functions(runtime/"tools/summarize_original_feedback_host.py",["current_tools"],{}).current_tools
    summarize = functions(old/"close_condition.py",["summarize_position"],dict(read_json=read,Path=Path,json=json,
        Counter=Counter,current_tools=current_tools)).summarize_position
    folders = {"old8-view_cache-original-reused":old/"executions/extractive-2048"}
    folders.update({job["name"]:root/"d-update32/reviews"/job["name"] for job in read(root/"d-update32/matrix-plan.json")["jobs"]})
    methods = {}
    raw_anchor_count = view_anchor_count = received_views = 0
    for name,folder in folders.items():
        packet = read(folder/"source-review-packet-v1.json")
        decisions = read(folder/"author-decisions-v1.json")
        closeout = read(folder/("closeout-v1.json" if name == "old8-view_cache-original-reused" else "answer-review-closeout-v1.json"))
        views = read(folder/"delivered-views-v1.json")["records"]
        view_reviews = read(folder/"view-author-decisions-v1.json")
        assert [decision["index"] for decision in decisions] == list(range(len(decisions)))
        assert packet["bound_positions"] == packet["planned_positions"] == len(decisions) == closeout["planned_positions"]
        reproduced = []
        for row,decision in zip(packet["records"],decisions,strict=True):
            actual = summarize(row,decision)
            a,v = anchors(row,decision,views)
            raw_anchor_count += a
            view_anchor_count += v
            reproduced.append(actual)
        assert reproduced == closeout["records"]
        assert dict(Counter(row["answer_grade"] for row in reproduced)) == closeout["answer_grades"]
        assert dict(Counter(row["delivery_status"] for row in reproduced)) == closeout["delivery_statuses"]
        assert sum(row["complete"] for row in reproduced) == closeout["complete"]
        assert sorted(index for review in view_reviews["records"] for index in review["occurrence_records"]) == list(range(len(views)))
        fidelity_label = ("faithful_literal_quote_with_original_authority_and_time_metadata"
            if name == "old8-view_cache-original-reused" else "faithful_literal_with_original_role_and_clock_metadata")
        for review in view_reviews["records"]:
            assert review["rationale"] and review["fidelity"] == fidelity_label
            first = views[review["occurrence_records"][0]]["actual_received_view"]
            for index in review["occurrence_records"]:
                actual = views[index]["actual_received_view"]
                assert actual["ref"] == review["actual_view_ref"] and actual["revision"] == first["revision"]
                assert actual["interpretation"] == first["interpretation"]
                assert all(source["literal_full_body_match"] and all(source["metadata_checks"].values())
                    for node in views[index]["nodes"] for source in node["source_bindings"])
        received_views += len(views)
        rates = {family:sum(row["complete"] for row in reproduced if row["family"] == family)/10
            for family in dict.fromkeys(row["family"] for row in reproduced)}
        assert all(sum(row["family"] == family for row in reproduced) == 10 for family in rates)
        costs = closeout["actual_costs"]
        assert sum(row["HTTP_responses"] for row in reproduced) == costs["HTTP_responses"]
        assert sum(row["known_generation_tokens"] for row in reproduced) == costs["known_generation_tokens"]
        assert sum(row["shared_generation_calls"] for row in reproduced) == costs["shared_generation_calls"]
        methods[name] = dict(positions=len(reproduced),families=len(rates),complete=closeout["complete"],
            answer_grades=closeout["answer_grades"],material_statuses=closeout["delivery_statuses"],
            received_View_occurrences_including_historical_K=len(views),unique_actual_View_refs=len(view_reviews["records"]),
            original_View_fidelity_label_counts=dict(Counter(review["fidelity"] for review in view_reviews["records"])),
            full_existing_author_decisions_and_closed_records_literal_equal=True,all_author_anchors_issue_quotes_and_original_quote_obligations_verified=True,
            all_received_View_literal_role_revision_and_clock_bindings_verified=True,actual_costs_already_paid=costs,
            reused_original_baseline=name == "old8-view_cache-original-reused")
        print("D_FIRST_REVIEW_FULL_RECORDS_ANCHORS_AND_VIEWS_VERIFIED",name,len(reproduced),closeout["complete"],flush=True)
    assert sum(method["positions"] for method in methods.values()) == 1200
    # Original baseline was reused by D. Audit its actual immutable SDK snapshots
    # here without creating a new baseline outcome or changing original files.
    entry = root/"audit_d_closed_sdk_states.py"
    source = entry.read_text()
    changes = [("folder = root / 'd-update32/reviews' / name","folder = Path(__baseline_folder__)"),
        ("(folder / 'SDK-state-audit.json')","Path(__audit_output__)")]
    redirected = source
    for before,after in changes:
        assert redirected.count(before) == 1
        redirected = redirected.replace(before,after,1)
    restored = redirected
    for before,after in reversed(changes):
        restored = restored.replace(after,before,1)
    assert restored == source
    baseline_report = output/"old8-reused-baseline80-actual-SDK-states.json"
    sys.argv = [str(entry),"old8-view_cache-original-reused"]
    exec(compile(redirected,str(entry),"exec"),dict(__name__="__main__",__file__=str(entry),
        __baseline_folder__=str(folders["old8-view_cache-original-reused"]),__audit_output__=str(baseline_report)))
    baseline = read(baseline_report)
    assert baseline["positions"] == 80 and baseline["state_writes"] == 0
    comparison,comparison_proof = replay(root,output,"compare_d_old8.py","old8-all3",
        "root / 'd-update32/old8-family-comparison-v1.json'",root/"d-update32/old8-family-comparison-v1.json",("cpu_seconds_nested",))
    assert {name:method["complete"] for name,method in comparison["methods"].items()} == {
        "view_cache":19,"view_cache_incremental":11,"e3-aggregate-u32":19}
    summary = dict(passed=True,status="D_ALL1200_ORIGINAL_FIRST_AUTHOR_RECORDS_ANCHORS_RECEIVED_VIEWS_AND_REUSED_BASELINE_SDK_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),methods=methods,
        total_first_positions_including_reuse=1200,new_native_first_positions=1120,original_baseline_firsts_reused=80,
        all_existing_author_record_fields_literal_reproduced=True,all_primary_failure_denominators_preserved=True,
        raw_Source_anchor_occurrences_verified=raw_anchor_count,extractive_View_anchor_occurrences_verified=view_anchor_count,
        actual_received_View_occurrences_including_K_verified=received_views,
        original_baseline80_Store_Source_Saver_app_immutable_snapshots_verified=True,
        original_baseline80_Source_comparisons=baseline["original_Source_values_preserved_in_turn_comparisons"],
        original_baseline80_final_assistant_Sources=baseline["new_final_assistant_Sources"],
        baseline_SDK_observer_only_two_path_assignments_changed_and_inverse_entire_source_equal=True,
        old8_family_comparison_reproduced_except_dynamic_CPU=comparison_proof,
        old8_baseline_incremental_E3_complete=[19,11,19],new32_baseline_incremental_E3_complete=[67,65,95],
        scope="Existing implementation/Source-author judgments and their actual first answers/anchors/Views, not new independent or blind semantic review. Literal View fidelity does not certify current coverage or underlying claims. Eight exposed DEV families and32previously assigned TRAIN families stay separate. Ten requests within each family are correlated, method-specific Host histories differ, and historical K occurrences are not new evidence or cost. No new judgment/training label, replayed outcome or adoption.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,original_Source_inputs_labels_models_or_firsts_changed=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with (output/"summary.json").open("x") as stream:
        json.dump(summary,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D1200_EXISTING_FIRST_AUTHOR_RECORDS_ANCHORS_VIEWS_AND_REUSED_BASELINE80_SDK_VERIFIED",flush=True)


if __name__ == "__main__":
    main()
