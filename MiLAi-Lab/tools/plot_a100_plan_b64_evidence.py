"""Plot B64 before-cost supervision, postfit answer directions and autonomous development."""
import argparse
import json
from datetime import datetime,timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab",type=Path)
    args = parser.parse_args()
    lab = args.lab.resolve()
    source = lab/"data/manifests/a100-plan-B64-audit-20261109-v1.json"
    evidence = json.loads(source.read_text())
    delivery = evidence["training"]["new_delivery_counts"]
    answer = {name:row["answer_counts"] for name,row in evidence["postfit_panel_summary"].items()}
    assert delivery == {"b0":{"tie":117,"left":5,"right":4,"unknown":2},"b1":{"tie":103,"left":2,"right":21,"unknown":2}}
    assert answer == {"b0":{"T":85,"R":12,"U":12,"L":19},"b1":{"T":72,"R":32,"U":14,"L":10}}
    counts = evidence["evaluation"]["autonomous64_first_outcome_source_review_counts"]
    methods = ["fixed-prefix","incumbent-delivery-u16","b0-u33","b1-u33","e3-aggregate-u32"]
    values = [counts[name] for name in methods]
    assert values == [25,25,33,32,40]
    plt.rcParams.update({"font.size":10,"axes.titlesize":12,"axes.labelsize":10,
        "axes.spines.top":False,"axes.spines.right":False,"pdf.fonttype":42})
    fig,axes = plt.subplots(1,3,figsize=(15,6.2),gridspec_kw={"width_ratios":[1,1,1.2]})
    fig.subplots_adjust(left=.065,right=.985,top=.75,bottom=.36,wspace=.38)
    fig.suptitle("B64: material supervision, later answer diagnosis and first Host outcomes",fontsize=18,x=.065,ha="left",y=.96)
    fig.text(.065,.89,"128 matched states | one shared baseline | 384 original binding outcomes | no label backfill",fontsize=11,color="#48535b")
    left_color,right_color = "#19877b","#607d98"
    for ax,kind,title in ((axes[0],"delivery","A  Actual material supervision"),(axes[1],"answer","B  Postfit-only answer diagnosis")):
        for index,name in enumerate(("b0","b1")):
            y = 1-index
            row = delivery[name] if kind == "delivery" else answer[name]
            left,right,tie,unknown = (row[key] for key in (("left","right","tie","unknown") if kind == "delivery" else ("L","R","T","U")))
            ax.barh(y,-right,height=.42,color=right_color,label="Baseline better" if index == 0 else None)
            ax.barh(y,left,height=.42,color=left_color,label="Left better" if index == 0 else None)
            ax.text(-right-.9,y,str(right),ha="right",va="center",fontsize=11,color=right_color)
            ax.text(left+.9,y,str(left),ha="left",va="center",fontsize=11,color=left_color)
            ax.text(0,y+.35,f"tie {tie}; unknown {unknown}",ha="center",fontsize=9,color="#48535b")
        ax.axvline(0,color="#9ca7af",linewidth=.8)
        ax.set(xlim=(-40,40),ylim=(-.5,1.75),yticks=[1,0],yticklabels=["B0","B1"],xlabel="Paired directional counts (128 states each)")
        ax.set_xticks([-40,-20,0,20,40],labels=["40","20","0","20","40"])
        ax.set_title(title,loc="left",pad=14)
        ax.grid(axis="x",alpha=.14)
        ax.legend(frameon=False,loc="upper center",bbox_to_anchor=(.5,-.22),ncol=2,fontsize=8,columnspacing=.9,handlelength=1.4)
    axes[0].text(0,-.44,"New answer targets stayed unknown in both fits.",transform=axes[0].transAxes,fontsize=8.6,color="#48535b",va="top")
    axes[1].text(0,-.44,"Source-author first answers; not new training labels.",transform=axes[1].transAxes,fontsize=8.6,color="#48535b",va="top")
    ax = axes[2]
    bars = ax.bar(range(5),values,color=["#8d9aa5","#b9c3ca","#607d98","#19877b","#c6a96b"],width=.65)
    for bar,value in zip(bars,values,strict=True):
        ax.text(bar.get_x()+bar.get_width()/2,value+1.3,f"{value}/64",ha="center",fontsize=9)
    ax.set(xticks=range(5),xticklabels=["Fixed","Initial","B0","B1","E3 ref."],ylim=(0,64),ylabel="Source-reviewed complete first Host trajectories")
    ax.set_title("C  Autonomous DEV64 selection",loc="left",pad=14)
    ax.grid(axis="y",alpha=.14)
    ax.text(0,-.25,"B1-B0: -1.56 pp; gains 12 / losses 13 / ties 39.\nFamily bootstrap 95%: [-17.19, +14.06] pp.\nDevelopment selection; no adoption.",transform=ax.transAxes,fontsize=8.6,color="#48535b",va="top")
    fig.text(.065,.055,"Left = argmax for B0; coverage alternative for B1. Shared baseline executed once. Different full bindings remain distinct even when literal packets match.\nSource-author judgments, exposed development and first stochastic outcomes. Material tiers do not establish Host success, collector efficiency or independent confirmation.",fontsize=9.2,color="#48535b")
    folder = lab/"docs/figures"
    folder.mkdir(exist_ok=True)
    stem = "a100-plan-B64-evidence-20261109-v1"
    png,pdf = folder/f"{stem}.png",folder/f"{stem}.pdf"
    fig.savefig(png,dpi=200,facecolor="white")
    fig.savefig(pdf,facecolor="white")
    plt.close(fig)
    result = dict(passed=True,status="B64_ACTUAL_DELIVERY_POSTFIT_ANSWER_AND_AUTONOMOUS_DEV64_FIGURE",
        timestamp_utc=datetime.now(timezone.utc).isoformat(),source_manifest=str(source),PNG=str(png),PDF=str(pdf),
        actual_PNG_size=[3000,1240],delivery_counts=delivery,postfit_answer_counts=answer,DEV64_complete=values,
        B1_minus_B0=evidence["evaluation"]["B1_minus_B0_autonomous64"],PNG_visual_inspection_pending=True,
        scope="Source-author labels and exposed selection. Postfit answer directions not in actual closed fit supervision.",
        new_model_or_original_ledger_calls=0,no_sha_validation=True,goal_complete=False)
    path = lab/"data/manifests/a100-plan-B64-figure-20261109-v1.json"
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("B64_EVIDENCE_FIGURE_RENDERED",png,pdf)


if __name__ == "__main__":
    main()
