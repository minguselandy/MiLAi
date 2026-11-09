"""Render native LME missing-outcome bounds, conditional pairs and measured costs."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lab", type=Path)
    args = parser.parse_args()
    lab = args.lab.resolve()
    source = lab / "data/manifests/a100-lme-native-comparison-20261109-v1.json"
    data = json.loads(source.read_text())
    methods = ["fixed", "primary"]
    labels = ["Fixed prefix", "E3 seed0/u32"]
    colors = ["#687b90", "#177f79"]
    overall = data["overall"]
    assert data["positions"] == 451 and overall["common_scored"]["count"] == 369
    plt.rcParams.update({"font.size": 11, "axes.titlesize": 13, "axes.labelsize": 11,
        "axes.spines.top": False, "axes.spines.right": False, "pdf.fonttype": 42})
    fig, axs = plt.subplots(2, 2, figsize=(14, 10))
    fig.subplots_adjust(left=.09, right=.98, top=.85, bottom=.18, wspace=.30, hspace=.64)
    fig.suptitle("LongMemEval Small development: native first outcomes", fontsize=19, x=.09, ha="left", y=.965)
    fig.text(.09, .925, "451 planned queries per method | preselected checkpoint | separate Reader / native Judge", fontsize=12, color="#48535b")
    ax = axs[0, 0]
    bounds = [overall["own_all_planned_bounds"][method] for method in methods]
    for index, ((low, high), color) in enumerate(zip(bounds, colors, strict=True)):
        ax.hlines(index, 100*low, 100*high, colors=color, linewidth=7)
        ax.vlines([100*low, 100*high], index-.11, index+.11, colors=color, linewidth=2)
        ax.text((low+high)*50, index+.24, f"{low*100:.2f}% to {high*100:.2f}%", ha="center", color=color)
    ax.set(yticks=[0, 1], yticklabels=labels, xlim=(0, 35), ylim=(-.5, 1.65), xlabel="All-planned native accuracy (%)")
    ax.set_title("A  Missing-outcome bounds, all 451", loc="left", pad=14)
    ax.grid(axis="x", alpha=.18)
    ax.text(0, -.30, "50 unscored per method; complete-cohort point metrics unavailable.\nIntervals show missing-result bounds, not confidence intervals.", transform=ax.transAxes, fontsize=9.2, color="#48535b", va="top")

    ax = axs[0, 1]
    common = overall["common_scored"]
    counts = [common["fixed_correct"], common["primary_correct"]]
    bars = ax.barh([0, 1], [100*count/369 for count in counts], color=colors, height=.48)
    for bar, count in zip(bars, counts, strict=True):
        ax.text(bar.get_width()+.5, bar.get_y()+bar.get_height()/2, f"{count}/369", va="center")
    ax.set(yticks=[0, 1], yticklabels=labels, xlim=(0, 28), ylim=(-.5, 1.5), xlabel="Accuracy among jointly scored queries (%)")
    ax.set_title("B  Paired common-scored subset", loc="left", pad=14)
    ax.grid(axis="x", alpha=.18)
    ax.text(0, -.30, f"E3 gains {common['gains']} / losses {common['losses']} / ties {common['ties']}; difference {common['primary_minus_fixed']*100:+.2f} pp.\nConditional on both completing; shared histories, no independent Source CI.", transform=ax.transAxes, fontsize=9.2, color="#48535b", va="top")

    ax = axs[1, 0]
    categories = ["READ selected", "opened return", "budget refusal"]
    read_values = [[data["methods"][method]["selected_action_counts"]["READ"],
        data["methods"][method]["operation_kind_status_counts"]["READ:opened"],
        data["methods"][method]["operation_kind_status_counts"].get("READ:material_budget_exhausted", 0)] for method in methods]
    x = np.arange(3)
    for index, (numbers, label, color) in enumerate(zip(read_values, labels, colors, strict=True)):
        bars = ax.bar(x+(index-.5)*.35, numbers, width=.35, color=color, label=label)
        for bar, number in zip(bars, numbers, strict=True):
            ax.text(bar.get_x()+bar.get_width()/2, number+55, str(number), ha="center", fontsize=9)
    ax.set(xticks=x, xticklabels=categories, ylim=(0, 3500), ylabel="Actual first-trajectory count")
    ax.set_title("C  READ selections and actual returns", loc="left", pad=14)
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    ax.grid(axis="y", alpha=.18)
    ax.text(0, -.25, "E3 also has 22 observed returns. Interrupted row9 ends in SEARCH.\n449 complete E3 packets contain 1,885 original_source items.", transform=ax.transAxes, fontsize=9.2, color="#48535b", va="top")

    ax = axs[1, 1]
    ax.axis("off")
    table_data = []
    cpu_hours = {}
    for method in methods:
        cpu_hours[method] = sum(data["methods"][method]["owner_totals"][stage]["whole_child_plus_measured_parent_CPU_seconds"] for stage in ("prediction", "scoring")) / 3600
    rows = ["Known HTTP tokens (M)", "Whole client CPU (h)", "Local NN calls", "Local NN input tokens (M)", "Model loads"]
    for index, label in enumerate(rows):
        numbers = []
        for method in methods:
            entry = data["methods"][method]
            values = [f"{entry['total_known_Reader_Judge_tokens']/1e6:.3f}", f"{cpu_hours[method]:.3f}",
                f"{entry['actual_NN_forwards']:,}", f"{entry['local_NN_input_tokens']/1e6:.3f}", str(entry["local_model_loads"])]
            numbers.append(values[index])
        table_data.append([label, *numbers])
    table = ax.table(cellText=table_data, colLabels=["Measured quantity", *labels], colWidths=[.53, .23, .24],
        cellLoc="left", loc="upper left", bbox=[0, .24, 1, .76])
    table.auto_set_font_size(False)
    table.set_fontsize(9.5)
    for (row, col), cell in table.get_celld().items():
        cell.set_edgecolor("#d7dde0")
        if row == 0:
            cell.set_facecolor("#eef2f4")
            cell.set_text_props(weight="bold")
    ax.set_title("D  Prediction + scoring invocation costs", loc="left", pad=14)
    ax.text(0, .10, "CPU includes copy/capture/IO; nested CPU counted once.\nSetup, audits, storage/archive, training and unmetered author work excluded.\nGPU reservation intervals include waits; Host GPU busy time unmeasured.", transform=ax.transAxes, fontsize=9.2, color="#48535b", va="top")
    fig.text(.09, .045, "Known Small development exposure; shared histories. First failures remain unscored. Source/input audit does not certify QA.\nPrimary physical step snapshots1-9 were never generated; raw evidence and metadata correction are disclosed in the report.", fontsize=10, color="#48535b")
    figures = lab / "docs/figures"
    figures.mkdir(exist_ok=True)
    stem = "a100-lme-native-comparison-20261109-v1"
    png, pdf = figures / (stem + ".png"), figures / (stem + ".pdf")
    fig.savefig(png, dpi=200, facecolor="white")
    fig.savefig(pdf, facecolor="white")
    plt.close(fig)
    manifest = dict(passed=True, status="NATIVE_LME_BOUNDS_COMMON_SUBSET_OPERATIONS_AND_INVOCATION_COST_FIGURE",
        timestamp_utc=datetime.now(timezone.utc).isoformat(), source=str(source), png=str(png), pdf=str(pdf),
        all_planned_missing_bounds=overall["own_all_planned_bounds"], common_scored=common,
        READ_selected_opened_refused_by_method=dict(zip(methods, read_values, strict=True)),
        invocation_CPU_hours_by_method=cpu_hours, table_cells=table_data,
        confidence_intervals_or_full_cohort_point_estimates_invented=False,
        all_project_costs_complete=False, PNG_visual_inspection_pending=True, layout_revision=2,
        new_model_Reader_Judge_or_HTTP_calls=0, ledger_opened_or_written=False,
        no_sha_validation=True, goal_complete=False)
    output = lab / "data/manifests/a100-lme-native-figure-20261109-v1.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print("LME_NATIVE_FIGURE_RENDERED", png, pdf)


if __name__ == "__main__":
    main()
