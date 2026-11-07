"""Audit actual fixed-model outputs, then score unchanged native masks after all three close."""
import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from analyze_conditional_unit_fit import family_balanced_accuracy
from evaluate_bounded_laya import score_applicability_predictions
from milai_lab.datasets.conditional_applicability import OPTIONS, score_condition_pairs
from retrieval_mixture import project_applicability_row
from reserved64_protocol_common_v1 import read, verify_code


def jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def audit(protocol, owner_path):
    owner=read(owner_path);plan=read(owner["plan"])
    assert owner["client_CPU_recorded"] and owner["whole_prediction_coverage"]
    assert all(not Path("/proc",str(owner[k])).exists() for k in ("pid","child_pid"))
    prepared=read(protocol["prepared_receipt"])
    public=jsonl(prepared["public_inputs"]);matrix=jsonl(prepared["offline_matrix"])
    driver=read(Path(plan["output"])/"driver.json")
    assert len(public)==len(matrix)==len(driver["cases"])==plan["positions"]
    inherited=[];cursor=owner
    while read(cursor["plan"])["previous_owner"] is not None:
        prior=read(read(cursor["plan"])["previous_owner"])
        assert prior["client_CPU_recorded"]
        assert all(not Path("/proc",str(prior[k])).exists() for k in ("pid","child_pid"))
        old=read(Path(read(prior["plan"])["output"])/"driver.json")
        for i,row in enumerate(old["cases"]):
            if row["status"]!="NOT_RUN":assert row==driver["cases"][i]
        inherited.append(prior["plan"]);cursor=prior
    records=[]
    for index,(item,source,case) in enumerate(zip(public,matrix,driver["cases"],strict=True)):
        assert item["index"]==case["index"]==index and item["family"]==case["family"]==source["metadata"]["family"]
        expected=project_applicability_row(source,protocol["operation_state"])
        assert item["payload"]=={k:expected[k] for k in ("state","questions")}
        assert read(case["input"])==item["payload"]
        assert case["status"] in ("COMPLETED","FAILED_FIRST_FORWARD")
        record={"index":index,"family":case["family"],"native_status":case["status"],"whole_input_literal_equal":True,
            "native_input":case["input"],"native_output":case["output"]}
        if case["status"]=="COMPLETED":
            result=read(case["output"])
            criteria=item["payload"]["questions"]["applicability"]["criteria"]
            assert list(result["logits"])==list(result["probabilities"])==list(criteria)
            assert all(math.isfinite(v) for field in ("logits","probabilities") for v in result[field].values())
            assert result["choice"]==max(result["probabilities"],key=result["probabilities"].get)
            assert not result["truncated"] and 0<result["input_tokens"]<=16384
            record.update(choice=result["choice"],input_tokens=result["input_tokens"],truncated=False,
                          preparation_seconds=result["preparation_seconds"],inference_seconds=result["inference_seconds"],
                          native_CPU_seconds_nested=result["cpu_seconds"])
        else:
            assert not case["raw_model_return_captured"] and not Path(case["output"]).exists()
            record.update(choice=None,error_type=case["error_type"],error=case["error"],first_failure_retained=True)
        records.append(record)
    inference=read(plan["inference"])
    assert inference["status"] in ("COMPLETED","FAILED_RETAINED")
    assert len(inference["model_loads"])==1 and inference["model_loads"][0]["status"]=="VERIFIED"
    target=Path(protocol["stage_directory"])/("reserved64-"+plan["model"]+"-full-prediction-audit-v1.json")
    result={"passed":True,"status":"FULL_NATIVE_CELL_FIRST_PREDICTIONS_AUDITED_WITH_FAILURES_RETAINED",
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),"model":plan["model"],"actual_owner":str(Path(owner_path).resolve()),
        "positions":len(records),"families":64,"records":records,"native_statuses":dict(Counter(r["native_status"] for r in records)),
        "all_model_inputs_literal_equal_original_native_projection":True,"all_complete_heads_finite_ordered_argmax_untruncated":True,
        "all_inherited_first_record_dicts_literal_equal":True,"prior_segments":inherited,
        "actual_CPU_paid_and_processes_absent":True,"model_HTTP_calls":0,"ledger_opened_or_written":False,"no_sha_validation":True}
    with target.open("x") as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print("RESERVED64_FULL_NATIVE_PREDICTION_AUDIT_PASSED",plan["model"],len(records),result["native_statuses"])


def pair_metrics(matrix,pairs,predictions):
    # The unchanged native scorer requires legal choices everywhere. This explicit
    # extension keeps known failed pairs incorrect, and unknown pairs unjudged.
    choices={row["metadata"]["event_id"]:predicted["choice"] for row,predicted in zip(matrix,predictions,strict=True)}
    reports={}
    for kind in ("change","stable","unknown"):
        selected=[p for p in pairs if p["kind"]==kind]
        by_query=defaultdict(list);changes=0;valid_pairs=0;failed_pairs=0
        for pair in selected:
            left,right=choices[pair["left_event"]],choices[pair["right_event"]]
            complete=left in OPTIONS and right in OPTIONS
            valid_pairs+=int(complete);failed_pairs+=int(not complete)
            changes+=int(complete and left!=right)
            if kind!="unknown":
                correct=complete and left==OPTIONS[0 if pair["left_label"] else 1] and right==OPTIONS[0 if pair["right_label"] else 1]
                by_query[pair["family"],pair["query_unit"]].append(int(correct))
        by_family=defaultdict(list)
        for (family,_),values in by_query.items():by_family[family].append(sum(values)/len(values))
        means={family:sum(values)/len(values) for family,values in by_family.items()}
        reports[kind]={"pairs":len(selected),"query_units_with_judged_pairs":len(by_query),
            "families_with_judged_pairs":len(means),"by_family_joint_accuracy":means,
            "family_macro_query_pair_joint_accuracy":sum(means.values())/len(means) if means else None,
            "prediction_change_rate":changes/len(selected) if selected and not failed_pairs else None,
            "pairs_with_two_valid_outputs":valid_pairs,"pairs_with_first_failure":failed_pairs,
            "completed_pair_prediction_change_rate":changes/valid_pairs if valid_pairs else None}
    if all(p["choice"] in OPTIONS for p in predictions):
        native=score_condition_pairs(matrix,pairs,predictions)
        for kind in reports:
            assert {k:reports[kind][k] for k in native["strata"][kind]}==native["strata"][kind]
    return {"strata":reports,"known_pair_denominators_not_dropped_for_failed_first_outputs":True,
        "unknown_pairs_no_accuracy_credit_or_negative_gold":True,
        "scope":"Native query->family joint scoring; pair prediction-change undefined when missing either output. Exact unchanged native result when every first output is valid. Not FollowIR p-MRR, retrieval ranking, factuality or Host success."}


def score(protocol):
    prepared=read(protocol["prepared_receipt"]);matrix=jsonl(prepared["offline_matrix"]);pairs=jsonl(prepared["offline_pairs"])
    families=[row["source_group"] for row in protocol["reserved64_metadata"]]
    assert len(set(families))==64
    support=defaultdict(set)
    for row in matrix:
        target=row["gold"].get("applicability",{}).get("probabilities",{})
        if target:support[row["metadata"]["family"]].add(max(target,key=target.get))
    balanced_defined=all(support[f]==set(OPTIONS) for f in families)
    methods={};audits={};predictions={}
    for model in protocol["models"]:
        name=model["name"];path=Path(protocol["stage_directory"])/("reserved64-"+name+"-full-prediction-audit-v1.json")
        checked=read(path);assert checked["passed"] and checked["positions"]==len(matrix)
        owner=read(checked["actual_owner"]);assert owner["client_CPU_recorded"]
        assert all(not Path("/proc",str(owner[k])).exists() for k in ("pid","child_pid"))
        audits[name]=str(path)
        predictions[name]=[{"choice":r["choice"] if r["native_status"]=="COMPLETED" else "__RETAINED_FIRST_FORWARD_FAILURE__"} for r in checked["records"]]
    # Both constants are prespecified diagnostic references, with no model calls.
    for label in OPTIONS:predictions["constant-"+label]=[{"choice":label} for _ in matrix]
    for name,values in predictions.items():
        methods[name]={"native_applicability":score_applicability_predictions(matrix,values),
            "family_balanced":family_balanced_accuracy(matrix,values) if balanced_defined else None,
            "native_pair_joint":pair_metrics(matrix,pairs,values),
            "model_failures":sum(p["choice"] not in OPTIONS for p in values)}
    comparisons={}
    if balanced_defined:
        labels=[("a0","a1"),("initial","a0"),("initial","a1")]
        differences=np.array([[methods[b]["family_balanced"]["by_family"][f]-methods[a]["family_balanced"]["by_family"][f]
            for a,b in labels] for f in families])
        draws=np.random.default_rng(0).integers(0,64,size=(20000,64))
        boots=differences[draws].mean(axis=1);bounds=np.percentile(boots,[2.5,97.5],axis=0)
        for j,(a,b) in enumerate(labels):
            values=differences[:,j]
            comparisons[b+"-minus-"+a]={"reference":a,"candidate":b,"difference_pp":float(100*values.mean()),
                "CI95_pp":[float(100*bounds[0,j]),float(100*bounds[1,j])],
                "higher_query_families":int((values>0).sum()),"lower_query_families":int((values<0).sum()),
                "tied_query_families":int((values==0).sum()),"family_differences":dict(zip(families,values.tolist(),strict=True))}
    result={"status":"ALL3_FIXED_SAVED_MODELS_NATIVE_RESERVED_QUERY_METRICS_CLOSED",
        "timestamp_utc":datetime.now(timezone.utc).isoformat(),"protocol":protocol["protocol_file"],
        "query_families":64,"matrix_positions_each":len(matrix),"native_counts":prepared["counts"],
        "model_audits":audits,"methods":methods,"primary_comparison":"a1-minus-a0 family_macro_balanced_accuracy",
        "original_balanced_metric_defined_all64_families":balanced_defined,
        "missing_balanced_support_families":[f for f in families if support[f]!=set(OPTIONS)],
        "comparisons":comparisons,"bootstrap":{"draws":20000,"seed":0,"unit":"fixed shared-corpus query family","common_draws":True,"interval":"two-sided unadjusted percentile95"},
        "scoring_failure_placeholder":"Only an invalid metric sentinel, never a fabricated model output or negative gold; known cells/pairs first failures remain incorrect, unknown masks untouched.",
        "scope":protocol["metric_scope"],"native_labels_or_masks_changed":False,"new_fits_or_checkpoint_selection":False,
        "adopted":False,"model_HTTP_calls":0,"ledger_opened_or_written":False,"no_sha_validation":True,"goal_complete":False}
    target=Path(protocol["score_closeout"])
    with target.open("x") as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print("RESERVED64_ALL3_NATIVE_METRICS_CLOSED balanced64",balanced_defined,"primary",comparisons.get("a1-minus-a0"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol",type=Path)
    parser.add_argument("mode",choices=("audit","score"))
    parser.add_argument("--owner",type=Path)
    args=parser.parse_args();protocol=read(args.protocol);verify_code(protocol)
    if args.mode=="audit":
        assert args.owner is not None
        audit(protocol,args.owner)
    else:
        assert args.owner is None
        score(protocol)


if __name__=="__main__":main()
