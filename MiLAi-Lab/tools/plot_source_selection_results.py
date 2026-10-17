"""Export common-dev learning and all-seed actual-QA figures from closed reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("learning", type=Path)
    parser.add_argument("qa", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    learning = json.loads(args.learning.read_text())
    qa = json.loads(args.qa.read_text())
    if learning["status"] != "ALL_SIX_FIXED_UPDATE_LEARNING_DIAGNOSTICS_CLOSED":
        raise ValueError("Use the closed six-job learning matrix")
    if qa["status"] != "BOTH_SOURCE_SELECTION_COHORTS_ALL_SEEDS_REVIEWED_AND_SUMMARIZED":
        raise ValueError("Use both completed QA reviews")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    args.output.mkdir(parents=True, exist_ok=True)
    colors = {"reference": "#3469a0", "source": "#bd6028", "prior128": "#477b5f"}
    markers = ["o", "s", "^"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True)
    for ax, labels, title in zip(axes, ("source", "reference"),
                               ("Source labels", "Native-reference labels"), strict=True):
        for job in learning["jobs"]:
            condition, seed = job["condition"], job["seed"]
            steps = sorted(map(int, job["dev"]))
            counts = [job["dev"][str(step)][labels]["counts"] for step in steps]
            ax.plot(steps, [100 * c["accepted"] / c["labelled"] for c in counts],
                    color=colors[condition], marker=markers[seed], linewidth=1.2, alpha=.8,
                    label=f"{condition}, seed {seed}")
        sample = learning["jobs"][0]["dev"]["0"][labels]["counts"]
        ax.axhline(100 * sample["bm25_next_accepted"] / sample["labelled"],
                   color="#666666", linestyle="--", label="BM25 next")
        ax.set(title=f"{title}: {sample['labelled']} labelled dev states",
               xlabel="Optimizer updates", xticks=[0, 94, 188], ylim=(0, 100))
        ax.grid(axis="y", alpha=.2)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("Accepted decisions (%)")
    handles, names = axes[0].get_legend_handles_labels()
    fig.legend(handles, names, ncol=4, loc="lower center", fontsize=8, frameon=False)
    fig.suptitle("Fixed-update learning on common development inputs")
    fig.text(.5, .115, "Pre-save FP32 diagnostics. Masks differ by label scheme; "
             "prefix acceptance is not actual-policy QA.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .15, 1, .94))
    for suffix in ("png", "pdf"):
        fig.savefig(args.output / f"learning.{suffix}", dpi=180)
    plt.close(fig)

    controls = [("bm25_k4", "BM25 fixed4", ":"), ("dense_k4", "Dense fixed4", "--"),
                ("full_pool", "Full pool", "-.")]
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), sharey=True)
    for column, cohort in enumerate(("dev", "reserved")):
        arms = qa[cohort]["arms"]
        for row_index, disposition in enumerate(("supported", "pool_insufficient")):
            ax = axes[row_index, column]
            for name, label, style in controls:
                stats = arms[name]["all"]["source_strata"][disposition]
                ax.axhline(100 * stats["task_pass"] / stats["cases"], color="#666666",
                           linestyle=style, linewidth=1.1, label=label)
            for index, condition in enumerate(("reference", "source", "prior128")):
                for seed in range(3):
                    stats = arms[f"{condition}_seed{seed}"]["all"]["source_strata"][disposition]
                    ax.scatter(index + (seed - 1) * .16,
                               100 * stats["task_pass"] / stats["cases"],
                               color=colors[condition], marker=markers[seed], s=45,
                               label=f"Seed {seed}" if index == 0 else None)
            base = arms["base_zero"]["all"]["source_strata"][disposition]
            ax.scatter(3, 100 * base["task_pass"] / base["cases"], color="#222222", marker="D")
            ax.set(title=f"{cohort.capitalize()} / {disposition}: n={base['cases']}",
                   xticks=range(4), xticklabels=["Reference", "Source", "Prior128", "BASE"],
                   ylim=(-4, 104), xlim=(-.5, 3.5))
            ax.grid(axis="y", alpha=.2)
            ax.spines[["top", "right"]].set_visible(False)
    axes[0, 0].set_ylabel("Grounded, cited answer with valid contract (%)")
    axes[1, 0].set_ylabel("Correct source-insufficiency abstention (%)")
    handles, names = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, names, ncol=6, loc="lower center", fontsize=8, frameon=False)
    fig.suptitle("Actual fixed4 QA: every frozen seed and strong retrieval controls")
    fig.text(.5, .065, "Conditional assistant source review; qualified supported cases included. "
             "Unqualified subsets, masked cases and family intervals are reported separately.",
             ha="center", fontsize=8)
    fig.text(.5, .042, "Dots are training seeds, not confidence intervals. "
             "Full pool has a different read budget. No best-seed selection.",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .095, 1, .95))
    for suffix in ("png", "pdf"):
        fig.savefig(args.output / f"actual-qa.{suffix}", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
