"""Plot D task results, actual View availability and the separate old-output control."""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read(path):
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("png",type=Path)
    parser.add_argument("pdf",type=Path)
    parser.add_argument("manifest",type=Path)
    args = parser.parse_args()
    root = args.root
    execution = read(root/"original-plan-D-existing-execution-v4/summary.json")
    quality = read(root/"original-plan-D-quality-and-baseline80-v2/summary.json")
    controls = read(root/"original-plan-D-control-closeouts-v3/summary.json")
    assert execution["passed"] and quality["passed"] and controls["passed"]
    names = ["view_cache","view_cache_incremental","e3-aggregate-u32"]
    labels = ["Cache","Incremental","E3"]
    complete = [quality["methods"]["new32-"+name]["complete"] for name in names]
    offered = [execution["actual_offered_kind_occurrences"]["new32-"+name]["REFRESH_VIEW"] for name in names]
    selected = [execution["actual_selected_kind_occurrences"]["new32-"+name].get("REFRESH_VIEW",0) for name in names]
    table = controls["old_output_by_method_condition"]
    searchable = [next(row["complete_successes"] for row in table if row["method"] == name and row["condition"] == "prior_Host_output_searchable") for name in names]
    excluded = [next(row["complete_successes"] for row in table if row["method"] == name and row["condition"] == "prior_Host_output_excluded") for name in names]
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"axes.spines.top":False,"axes.spines.right":False})
    fig,axes = plt.subplots(1,3,figsize=(15,6.2))
    blue,orange,gray = "#277DA8","#D97435","#DCE3E9"
    axes[0].bar(range(3),[100*count/320 for count in complete],color=[blue,blue,orange])
    for index,count in enumerate(complete):
        axes[0].text(index,100*count/320+1,f"{count}/320",ha="center")
    axes[0].set(xticks=range(3),xticklabels=labels,ylim=(0,36),ylabel="Complete first task answers (%)",title="New32 autonomous development")
    axes[0].text(.02,.96,"32 TRAIN families; 10 correlated requests each",transform=axes[0].transAxes,fontsize=9,va="top")
    axes[1].bar(range(3),offered,color=gray,label="Offered")
    axes[1].bar(range(3),selected,color=orange,label="Selected")
    for index,(a,b) in enumerate(zip(selected,offered,strict=True)):
        axes[1].text(index,b+18,f"{a} / {b}",ha="center")
    axes[1].set(xticks=range(3),xticklabels=labels,ylim=(0,1020),ylabel="Decision occurrences",title="REFRESH_VIEW selected / offered")
    axes[1].text(.02,.96,"Received View refs: 42 / 25 / 0\nE3 USE_VIEW was absent from its own menus",transform=axes[1].transAxes,fontsize=9,va="top")
    for index,(on,off) in enumerate(zip(searchable,excluded,strict=True)):
        axes[2].bar(index-.18,on,width=.34,color=blue)
        axes[2].bar(index+.18,off,width=.34,color=orange)
        axes[2].text(index-.18,on+.13,f"{on}/7",ha="center",fontsize=10)
        axes[2].text(index+.18,off+.13,f"{off}/7",ha="center",fontsize=10)
    axes[2].set(xticks=range(3),xticklabels=labels,ylim=(0,8),yticks=range(8),ylabel="Complete first task answers",title="Old-output acquisition control")
    axes[2].text(.02,.96,"Blue: searchable; orange: excluded\n7 exposed TRAIN families; Host RNG unmatched",transform=axes[2].transAxes,fontsize=9,va="top")
    fig.suptitle("D: task results, actual View decisions and conditional output acquisition are separate",fontsize=15,y=.97)
    fig.subplots_adjust(left=.06,right=.985,top=.82,bottom=.30,wspace=.35)
    fig.legend(*axes[1].get_legend_handles_labels(),loc="center left",bbox_to_anchor=(.365,.205),ncol=2,frameon=False,fontsize=9)
    fig.text(.06,.07,"Known-View control: 0/9 complete; one first template rejection was never dispatched and is not a policy-attributable loss.\nAll first failures remain: old-output includes two unchanged full-input capacity failures; existing Host knowledge stays common in both conditions.\nSource-author review is not independent/blind. New32 results are conditional/descriptive; zero View receipt does not establish learned View reuse.",fontsize=10,linespacing=1.6,va="bottom")
    fig.savefig(args.png,dpi=200,facecolor="white")
    fig.savefig(args.pdf,facecolor="white")
    plt.close(fig)
    manifest = dict(status="D_DEVELOPMENT_ACTUAL_VIEW_DECISIONS_AND_SEPARATE_OLD_OUTPUT_FIRST_CONTROL_FIGURE",
        PNG=str(args.png.resolve()),PDF=str(args.pdf.resolve()),PNG_size=[3000,1240],
        new32_complete=complete,new32_denominator_each=320,REFRESH_VIEW_offered=offered,REFRESH_VIEW_selected=selected,
        old_output_complete_searchable=searchable,old_output_complete_excluded=excluded,old_output_denominator_each=7,
        known_View_complete=0,known_View_denominator=9,
        source_author_not_independent_or_blind=True,original_firsts_and_failures_retained=True,
        PNG_actual_visual_inspection_passed=False,PNG_visual_inspection_pending=True,
        new_model_tokenizer_GPU_HTTP_or_original_ledger_calls=0,no_sha_validation=True,full763_line_completion_proven=False,goal_complete=False)
    with args.manifest.open("x") as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("D_DEVELOPMENT_VIEW_DECISION_AND_OLD_OUTPUT_FIGURE_WRITTEN_VISUAL_CHECK_PENDING",flush=True)


if __name__ == "__main__":
    main()
