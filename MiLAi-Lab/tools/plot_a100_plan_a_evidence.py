"""Plot verified A exposure/relationship changes and first development outcomes."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab",type=Path)
    args = parser.parse_args()
    lab = args.lab.resolve()
    source = lab/"data/manifests/a100-plan-A-audit-20261109-v1.json"
    evidence = json.loads(source.read_text())
    data, evaluation = evidence["data"],evidence["evaluation"]
    assert data["pure_conditional_slots"] == 39982 and data["preserved_positive_rows"] == 20008
    native = [data["panels"][name]["coverage"]["selected_known_units"] for name in ("a0","a1")]
    stable = [data["stable_negative_pairs"][name] for name in ("a0","a1")]
    outcomes = [evaluation["task32_manual_Source_review_complete_counts"][name] for name in ("raw_delivery","initial","a0","a1")]
    assert native == [5,9540] and stable == [9968,433] and outcomes == [14,14,15,15]
    plt.rcParams.update({"font.size":10,"axes.titlesize":12,"axes.labelsize":10,
        "axes.spines.top":False,"axes.spines.right":False,"pdf.fonttype":42})
    fig,axes = plt.subplots(1,3,figsize=(15,6.2),gridspec_kw={"width_ratios":[1.35,1,1]})
    fig.subplots_adjust(left=.065,right=.985,top=.75,bottom=.29,wspace=.38)
    fig.suptitle("A seed0: changed training exposure and first development outcomes",fontsize=18,x=.065,ha="left",y=.96)
    fig.text(.065,.89,"Fixed 39,982 conditional rows | matched BF16 fits | declared u2104 | first outcomes retained",fontsize=11,color="#48535b")
    colors = {"positive":"#c5cdd3","native":"#19877b","other":"#607d98"}
    ax = axes[0]
    for index,(label,count) in enumerate(zip(["A0 legacy","A1 native-priority"],native,strict=True)):
        y = 1-index
        other = 19974-count
        ax.barh(y,20008,height=.48,color=colors["positive"],label="Positive" if index == 0 else None)
        ax.barh(y,count,left=20008,height=.48,color=colors["native"],label="Native negative" if index == 0 else None)
        ax.barh(y,other,left=20008+count,height=.48,color=colors["other"],label="Other negative" if index == 0 else None)
        ax.text(10004,y,"20,008",ha="center",va="center",fontsize=9)
        ax.text(20008+count+other/2,y,f"{other:,}",ha="center",va="center",color="white",fontsize=9)
        if count > 5:
            ax.text(20008+count/2,y,f"{count:,}",ha="center",va="center",color="white",fontsize=9)
    ax.annotate("5",xy=(20010.5,1.23),xytext=(24400,1.63),ha="center",fontsize=10,
        arrowprops={"arrowstyle":"->","color":colors["native"]},color=colors["native"])
    ax.set(yticks=[1,0],yticklabels=["A0","A1"],xlim=(0,42000),ylim=(-.6,1.95),xlabel="Selected conditional TRAIN rows")
    ax.set_title("A  Row composition at fixed budget",loc="left",pad=14)
    ax.set_xticks([0,10000,20000,30000,40000],labels=["0","10k","20k","30k","40k"])
    ax.legend(frameon=False,loc="upper center",bbox_to_anchor=(.5,-.22),fontsize=8,ncol=3,columnspacing=.9,handlelength=1.4)
    ax.grid(axis="x",alpha=.14)

    ax = axes[1]
    bars = ax.bar([0,1],stable,color=["#607d98","#19877b"],width=.58)
    for bar,value in zip(bars,stable,strict=True):
        ax.text(bar.get_x()+bar.get_width()/2,value+240,f"{value:,}",ha="center",fontsize=11)
    ax.set(xticks=[0,1],xticklabels=["A0","A1"],ylim=(0,11800),ylabel="Complete selected stable-negative pairs")
    ax.set_title("B  Relationship support also changes",loc="left",pad=14)
    ax.grid(axis="y",alpha=.14)
    ax.text(0,-.27,"80 stable-positive and 6 change pairs kept in both.\nPairs are relationships; independent sample count is unchanged.",transform=ax.transAxes,fontsize=8.5,color="#48535b",va="top")

    ax = axes[2]
    bars = ax.bar(range(4),outcomes,color=["#9da8b0","#bac3ca","#607d98","#19877b"],width=.6)
    for bar,value in zip(bars,outcomes,strict=True):
        ax.text(bar.get_x()+bar.get_width()/2,value+.7,f"{value}/32",ha="center",fontsize=10)
    ax.set(xticks=range(4),xticklabels=["Raw","Initial","A0","A1"],ylim=(0,32),ylabel="Source-reviewed complete readouts")
    ax.set_title("C  Exposed 32-family panel",loc="left",pad=14)
    ax.grid(axis="y",alpha=.14)
    ax.text(0,-.27,"A1-A0: gains 0 / losses 0 / ties 32.\nMissing state kept; later repeat excluded.",transform=ax.transAxes,fontsize=8.5,color="#48535b",va="top")
    fig.text(.065,.06,"Raw matrices and unknown masks retained. Shared-corpus development; these conditional readouts are not autonomous Host or independent-corpus confirmation.\nStable-negative support and optimizer grouping change with sampling. Evidence does not support an isolated native-negative-only effect or adoption.",fontsize=9.3,color="#48535b")
    folder = lab/"docs/figures"
    folder.mkdir(exist_ok=True)
    stem = "a100-plan-A-evidence-20261109-v1"
    png,pdf = folder/f"{stem}.png",folder/f"{stem}.pdf"
    fig.savefig(png,dpi=200,facecolor="white")
    fig.savefig(pdf,facecolor="white")
    plt.close(fig)
    result = dict(passed=True,status="A_FIXED_ROW_EXPOSURE_CHANGED_PAIR_SUPPORT_AND_FIRST_TASK_OUTCOMES_FIGURE",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),source_manifest=str(source),PNG=str(png),PDF=str(pdf),
        positive_rows_each=20008,native_negative_rows=native,other_negative_rows=[19974-value for value in native],
        stable_negative_pairs=stable,stable_positive_pairs_each=80,change_pairs_each=6,
        task32_complete=outcomes,actual_PNG_size=[3000,1240],PNG_visual_inspection_pending=True,
        complete_project_or_causal_single_factor_effect_proven=False,new_model_HTTP_or_original_ledger_calls=0,
        no_sha_validation=True,goal_complete=False)
    path = lab/"data/manifests/a100-plan-A-figure-20261109-v1.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("A_EVIDENCE_FIGURE_RENDERED",png,pdf)


if __name__ == "__main__":
    main()
