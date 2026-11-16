"""Plot every frozen training seed against the same three QA controls.

Standalone system plotting environment; only completed cohort summaries are read.
Source judgments are conditional development-assistant review, not independent gold.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path, help="Output path prefix for PNG and PDF")
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if report["status"] != "BOTH_COHORTS_ALL_MODELS_DESCRIPTIVELY_SUMMARIZED":
        raise ValueError("Plot only the complete two-cohort review")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = [
        (size, head, policy)
        for size in (32, 128)
        for head in ("native", "linear")
        for policy in ("k4", "adaptive")
    ]
    colors = ("#2866a3", "#c16b21", "#3b8768")
    markers = ("o", "^", "s")
    controls = (
        ("bm25_k4", "BM25 fixed 4", ":", "#858585"),
        ("dense_k4", "Dense fixed 4", "--", "#525252"),
        ("full20", "All 20 documents", "-.", "#222222"),
    )
    fig, axes = plt.subplots(1, 2, figsize=(15, 5.8), sharey=True)
    for ax, cohort, title in zip(
        axes, ("dev", "reserved"), ("Development", "Reserved"), strict=True
    ):
        arms = report[cohort]["arms"]
        denominator = arms["full20"]["all"]["source_strata"]["supported"]["cases"]
        for name, label, style, color in controls:
            stats = arms[name]["all"]["source_strata"]["supported"]
            ax.axhline(
                100 * stats["task_pass"] / stats["cases"], color=color, linestyle=style,
                linewidth=1.4, label=label, zorder=1,
            )
        for index, (size, head, policy) in enumerate(groups):
            for seed in range(3):
                name = f"families{size}-{seed}-{head}_{policy}"
                stats = arms[name]["all"]["source_strata"]["supported"]
                ax.scatter(
                    index + (seed - 1) * .16, 100 * stats["task_pass"] / stats["cases"],
                    color=colors[seed], marker=markers[seed], s=42,
                    label=f"Training seed {seed}" if index == 0 else None, zorder=3,
                )
        ax.set_title(f"{title}: {denominator} source-supported cases")
        ax.set_xticks(
            range(len(groups)),
            [f"{size}\n{head}\n{'fixed 4' if policy == 'k4' else policy}"
             for size, head, policy in groups],
            fontsize=8,
        )
        ax.set_xlim(-.5, len(groups) - .5)
        ax.set_ylim(-4, 104)
        ax.set_yticks(range(0, 101, 20))
        ax.axvline(3.5, color="#dddddd", linewidth=.8)
        ax.set_xlabel("Training families / classification head / selection policy")
        ax.grid(axis="y", alpha=.16)
        ax.spines[["right", "top"]].set_visible(False)
    axes[0].set_ylabel("Grounded, cited task answers with valid output (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, .09),
               ncol=6, fontsize=8, frameon=False)
    fig.suptitle("Actual-policy QA on source-supported cases", fontsize=14)
    fig.text(.5, .055, "All three fixed training seeds are shown; dots are not confidence "
             "intervals. Known failures remain failures. No seed or policy was selected.",
             ha="center", fontsize=8)
    fig.text(.5, .025, "Conditional on predeclared source interpretations and assistant review. "
             "Insufficient/ambiguous cases, native scores and full costs are reported separately.",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .18, 1, .93))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output.with_suffix(".png"), dpi=180)
    fig.savefig(args.output.with_suffix(".pdf"))
    plt.close(fig)


if __name__ == "__main__":
    main()
