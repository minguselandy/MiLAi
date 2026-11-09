"""Audit frozen D source-only timelines, separate factors, actual configs and View mechanism."""
import argparse
import json
import re
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

from audit_a100_plan_d_existing_execution import read,replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("output_folder",type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    folder = root/"d-update32"
    output = args.output_folder.resolve()
    output.mkdir()
    protocol = read(folder/"protocol-before-body-projection.json")
    reservation = read(folder/"source-reservation.json")
    projected = read(folder/"native-source-dialogues.json")
    contracts = read(folder/"source-author-contracts.json")
    histories = read(folder/"new32-histories.json")["histories"]
    requirements = read(folder/"new32-source-requirements.json")
    preservation = read(folder/"new32-source-preservation.json")
    assert len(reservation["selected"]) == len(projected["records"]) == len(contracts["records"]) == 32
    assert len(histories) == 64 and len(requirements["records"]) == 320
    assert not requirements["records_passed_to_Host"] and not contracts["native_metadata_labels_used"]
    assert contracts["prior_source_contracts_reused"] == 29
    assert contracts["new_full_dialogue_reviews"] == ["memops_A02","memops_C02","memops_D02"]
    source_map,contract_map = {},{}
    for selected,projection,contract in zip(reservation["selected"],projected["records"],contracts["records"],strict=True):
        assert selected["family"] == projection["family"] == contract["family"]
        assert selected["split"] == projection["split"] == "train" and selected["family"] not in reservation["old8"]
        native = read(selected["source_path"])
        literal = [dict(session_id=f"source-session-{segment['segment_index']}",event_key=f"s{segment['segment_index']}t{index}",
            role=turn["role"],content=turn["content"],occurred_at=None)
            for segment in sorted(native["conversations"],key=lambda item:item["segment_index"])
            for index,turn in enumerate(segment["dialogue"],1)]
        assert literal == projection["sources"] and all(source["role"] in ("user","assistant") for source in literal)
        assert Path(contract["source_file"]) == Path(projection["source_file"]) == Path(selected["source_path"])
        assert contract["contract"]["file"] == Path(selected["source_path"]).name
        if projection["prior_contract"] is not None:
            assert contract["contract"] == projection["prior_contract"]
        assert contract["independent_or_blinded"] is False
        source_map[selected["family"]] = literal
        contract_map[selected["family"]] = contract["contract"]
    requirement_map = {(row["history"],row["request"]):row for row in requirements["records"]}
    assert len(requirement_map) == 320
    quote = " Quote the specific statements in my reports supporting your conclusions, and keep those quotations distinct from your interpretation."
    stages = ["initial","same-sources","additional-arrival","intermediate-arrivals","final-arrivals"]
    note = preservation["source_note"]
    source_values = native_values = quote_requests = witnesses = 0
    for history in histories:
        family = history["source_group"]
        assert history["split"] == "train" and history["continuous"] and history["sources"] == []
        assert set(history) == {"id","source_group","split","continuous","sources","requests"}
        assert [request["id"] for request in history["requests"]] == stages
        form = "originals" if history["id"].endswith("-originals") else "content"
        source = source_map[family]
        positions = {item["event_key"]:tuple(map(int,re.fullmatch(r"s(\d+)t(\d+)",item["event_key"]).groups())) for item in source}
        by_key = {item["event_key"]:item for item in source}
        contract = contract_map[family]
        cuts = contract["cuts"]
        assert len(cuts) == 3
        accumulated,previous = [],(0,0)
        for index,request in enumerate(history["requests"]):
            assert set(request) == {"id","content","incoming_sources"}
            cut_index = 0 if index < 3 else index-2
            cut = cuts[cut_index]
            through = tuple(cut["through"])
            assert by_key[f"s{through[0]}t{through[1]}"]["role"] == "user"
            if index == 1:
                expected = []
            elif index == 2:
                expected = [note]
            else:
                assert through > previous
                expected = [item for item in source if previous < positions[item["event_key"]] <= through]
                previous = through
            assert request["incoming_sources"] == expected
            accumulated.extend(expected)
            asks_quotes = form == "originals" and index > 0
            assert request["content"] == contract["query"]+(quote if asks_quotes else "")
            row = requirement_map[history["id"],request["id"]]
            assert row["public_task"] == request["content"] and row["family"] == family
            assert row["native_through"] == list(through) and row["required_answer_scope"] == cut["answer"]
            assert row["bounds"] == contract["qualification"] and row["support_sets"] == cut["support_sets"]
            assert row["explicit_original_quotes_required"] == asks_quotes
            assert row["actual_exogenous_sources"] == len(accumulated)
            assert row["native_source_prefix"] == sum(item["event_key"] != note["event_key"] for item in accumulated)
            expected_witnesses = {key:by_key[key] for support in cut["support_sets"] for key in support}
            assert row["witnesses"] == expected_witnesses
            for key,item in expected_witnesses.items():
                assert item in accumulated and item["role"] == "user" and positions[key] <= through
            witnesses += len(expected_witnesses)
            quote_requests += asks_quotes
            if index == 2:
                first = requirement_map[history["id"],"initial"]
                assert row["required_answer_scope"] == first["required_answer_scope"] and row["support_sets"] == first["support_sets"]
        final = [item for item in source if positions[item["event_key"]] <= tuple(cuts[-1]["through"])]
        assert [item for item in accumulated if item["event_key"] != note["event_key"]] == final
        source_values += len(accumulated)
        native_values += len(final)
    assert quote_requests == 128 and native_values//2 == preservation["native_sources_distinct_across_families"]
    matrix = read(folder/"matrix-plan.json")
    actual_jobs = []
    for job in matrix["jobs"]:
        config = read(job["config"])["entrypoints"]["functional"]
        assert config == read(folder/"config-validation"/job["name"]/"input-freeze.json")["config"]
        assert config["host"] == protocol["common_configuration"]["host"]
        assert config["ordinary_material_tokens"] == protocol["return_tokens"] == 2048
        assert config["max_calls_per_message"] == protocol["shared_calls_per_message"] == 24
        control = config["memory_control"]
        assert control["policy"] == job["policy"] and control["view_builder"] == "extractive" and control["delivery_selection"]
        if job["policy"] == "view_cache_incremental":
            assert control["incremental_reads"] == 1
        owner = read(folder/(job["name"]+"-owner.json"))
        assert owner["job"] == job and owner["exit_code"] == 0 and owner["client_CPU_recorded"]
        driver = read(Path(job["output"])/"driver.json")
        selected_histories = [history for history in read(job["histories"])["histories"] if history["split"] == job["split"]]
        expected = [(history["id"],request["id"]) for history in selected_histories for request in history["requests"]]
        assert expected == [(row["history"],row["request"]) for row in driver["completed"]]
        assert len(expected) == driver["planned_positions"] == job["positions"]
        assert driver["continue_host_history"] and not driver["given_requests"] and not driver["native_probe"]
        actual_jobs.append(dict(name=job["name"],policy=job["policy"],positions=job["positions"],
            actual_frozen_config_literal_equal=True,autonomous_continuous_Host_all_first_positions_verified=True))
    mechanism,mechanism_proof = replay(root,output,"close_d_incremental_mechanism.py","new32-incremental-mechanism",
        "folder / 'actual-use-View-mechanism-closeout-v1.json'",
        folder/"reviews/new32-view_cache_incremental/actual-use-View-mechanism-closeout-v1.json")
    assert len(mechanism["actual_USE_VIEW"]) == 3
    assert all(row["additional_READ_after_USE_VIEW"] == 0 and row["new_events"] == 0 for row in mechanism["actual_USE_VIEW"])
    summary = dict(passed=True,status="D32_NATIVE_SOURCE_ONLY_TIMELINES_THREE_FACTORS_ACTUAL_CONFIGS_AND_INCREMENTAL_USE_MECHANISM_RECONCILED",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),families=32,split="train",source_author_prior_contracts=29,new_source_author_full_dialogue_contracts=3,
        native_source_dialogue_objects_literal_reprojected=sum(len(value) for value in source_map.values()),
        native_Source_prefix_values_in_two_flows=native_values,all_final_exogenous_values_in_two_flows=source_values,
        no_future_support_user_cuts_role_body_null_unknown_clock_verified=True,
        actual_support_witness_occurrences_bound=witnesses,streams=64,requests_per_stream=5,positions_per_method=320,
        public_quote_requests=128,Host_history_fields_contain_no_expected_answer_operation_or_scoring_labels=True,
        actual_config_and_autonomous_execution_jobs=actual_jobs,
        separate_factor_positions_per_method=dict(initial=64,no_new_exogenous_Source=64,
            one_constructed_task_irrelevant_Source=64,native_intermediate_arrivals=64,native_final_arrivals=64),
        task_irrelevant_Source_is_one_constructed_cable_note_not_history_scale_curve=True,
        same_sources_means_exogenous_only_endogenous_Host_history_can_change=True,
        native_middle_arrivals_not_all_task_irrelevant=True,natural_target_irrelevant_middle_family=preservation["natural_middle_target_irrelevant"],
        incremental_USE_VIEW_mechanism_original_report_literal_reproduced=True,incremental_USE_VIEW_mechanism_proof=mechanism_proof,
        all3_USE_VIEW_initial_no_new_pending_events_no_supplemental_READ=True,
        known_View_K_and_old_output_controls_require_separate_actual_evidence=True,
        old8_original_baseline_reuse_not_claimed_as_new_firsts=True,
        source_author_not_independent_or_blind=True,
        scope="Dsource-only TRAIN projection and author support/prefix/config/actual-first-execution reconciliation. Three factors have distinct actual schedule positions; the single irrelevant arrival does not establish an irrelevant-history scaling curve, and relevant arrivals include additions/corrections/status/scope rather than universal value flips. Autonomous endogenous histories and requests can diverge. This proves neither View+incremental task benefit, independent semantic truth, controls closure nor full original plan completion.",
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,original_Source_inputs_labels_or_firsts_changed=False,
        CPU_pending_actual_idle138=True,no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with (output/"summary.json").open("x") as stream:
        json.dump(summary,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D32_SOURCE_ONLY_PREFIXES_CONFIGS_FACTORS_AND_USE_VIEW_MECHANISM_VERIFIED",summary["separate_factor_positions_per_method"],flush=True)


if __name__ == "__main__":
    main()
