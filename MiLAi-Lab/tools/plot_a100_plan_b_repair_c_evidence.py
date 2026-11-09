"""Plot closed B-repair/C mechanical coverage, bounded budgets and first task results."""
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
    audit = read(args.root/"original-plan-repair66-quality-stop-v1.json")
    c8 = read(args.root/"original-plan-C8-Source-saved-choices-v1.json")
    assert audit["passed"] and c8["passed"]
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":11,"axes.spines.top":False,"axes.spines.right":False})
    fig,axes = plt.subplots(1,3,figsize=(15,6.2),gridspec_kw={"width_ratios":[.85,1.05,1.5]})
    blue,orange,gray = "#277DA8","#D97435","#E5E9ED"
    left,middle,right = axes
    left.bar([0,1],[5,5],color=blue,label="Previously executed")
    left.bar([0,1],[0,52],bottom=[5,5],color=orange,label="New missing bindings")
    left.set(xticks=[0,1],xticklabels=["Before repair","After repair"],ylim=(0,64),ylabel="Old TRAIN states with a verified Source READ",title="Actual READ execution coverage")
    left.text(0,6,"5 / 57",ha="center")
    left.text(1,58,"57 / 57",ha="center")
    handles,legend_labels = left.get_legend_handles_labels()
    fig.legend(handles,legend_labels,loc="center left",bbox_to_anchor=(.06,.205),ncol=2,frameon=False,fontsize=9)
    labels = ["New READ branches","Acquired pools","New set readouts"]
    used,ceilings = [57,18,47],[57,24,48]
    for y,(value,ceiling) in enumerate(zip(used,ceilings,strict=True)):
        middle.barh(y,1,color=gray,height=.52)
        middle.barh(y,value/ceiling,color=blue,height=.52)
        middle.text(value/ceiling-.03,y,f"{value} / {ceiling}",va="center",ha="right",color="white",fontweight="bold")
    middle.set(yticks=range(3),yticklabels=labels,xlim=(0,1.06),xticks=[0,.5,1],xticklabels=["0%","50%","100%"],title="Actual use / frozen ceiling",xlabel="Fraction of the declared budget used")
    middle.invert_yaxis()
    references = [18/52,4/8,3/7]
    candidates = [15/52,1/8,2/7]
    for index,(ref,candidate) in enumerate(zip(references,candidates,strict=True)):
        right.bar(index-.18,100*ref,width=.34,color=blue)
        right.bar(index+.18,100*candidate,width=.34,color=orange)
    for i,counts in enumerate([(18,15,52),(4,1,8),(3,2,7)]):
        a,b,n = counts
        right.text(i-.18,100*a/n+2,f"{a}/{n}",ha="center",fontsize=10)
        right.text(i+.18,100*b/n+2,f"{b}/{n}",ha="center",fontsize=10)
    right.scatter([2-.18,2+.18],[100*2/7,100*2/7],marker="_",s=260,color="black",zorder=5)
    right.set(xticks=range(3),xticklabels=["B52\nRetained / new READ","C8\nRules / saved E3","C7\nRules / E3"],ylim=(0,66),ylabel="Complete first task answers (%)",title="Conditional task results; all first failures kept")
    right.text(.02,.96,"Blue: retained or rules\nOrange: new READ or E3",transform=right.transAxes,va="top",fontsize=9)
    fig.suptitle("B-repair and C: closed execution coverage does not establish learned task benefit",fontsize=15,y=.97)
    fig.subplots_adjust(left=.06,right=.985,top=.84,bottom=.29,wspace=.53)
    fig.text(.06,.07,"C8: initial, B0, B1 and E3 each 1/8; fixed_context and rules each 4/8. C7 black marks: heading-only sensitivity, 2/7 each.\nSource-author review on exposed TRAIN; conditional supplied-request readouts. C/B families overlap; do not pool independent sample sizes.\n47/48 set readouts includes functional3 + original24 + saved6 + repair14. Source READ opening/delivery is a mechanical diagnostic.",fontsize=10,va="bottom",linespacing=1.6)
    fig.savefig(args.png,dpi=200,facecolor="white")
    fig.savefig(args.pdf,facecolor="white")
    plt.close(fig)
    manifest = dict(status="B_REPAIR_C_MECHANICAL_BUDGET_AND_CONDITIONAL_TASK_FIGURE",
        PNG=str(args.png.resolve()),PDF=str(args.pdf.resolve()),PNG_size=[3000,1240],
        PNG_visual_inspection_pending=True,PNG_actual_visual_inspection_passed=False,
        source_audits=[str((args.root/name).resolve()) for name in ("original-plan-repair66-quality-stop-v1.json","original-plan-C8-Source-saved-choices-v1.json")],
        used_budgets=dict(new_READ=[57,57],acquired_pools=[18,24],new_set_readouts=[47,48]),
        task_counts=dict(B52=dict(retained=18,new_READ=15,n=52),C8=dict(rules=4,saved_E3=1,n=8),C7=dict(rules=3,E3=2,n=7)),
        source_author_not_independent_or_blind=True,descriptive_exposed_TRAIN_only=True,
        original_Source_labels_or_firsts_changed=False,new_model_GPU_HTTP_or_original_ledger_calls=0,
        full763_line_completion_proven=False,no_sha_validation=True,goal_complete=False)
    with args.manifest.open("x") as stream:
        json.dump(manifest,stream,ensure_ascii=False,indent=2)
        stream.write("\n")
    print("B_REPAIR_C_COVERAGE_BUDGET_TASK_FIGURE_WRITTEN_VISUAL_INSPECTION_PENDING",flush=True)


if __name__ == "__main__":
    main()
