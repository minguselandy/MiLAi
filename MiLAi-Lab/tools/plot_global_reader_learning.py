"""Standalone reference-learning figure from the closed twelve-job matrix.

Uses the system plotting environment; no model, provider or experiment ledger is
loaded. The plotted FP32 fit diagnostics remain distinct from checkpoint reload
and actual-policy QA.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("output", type=Path, help="Output path prefix for PNG and PDF")
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    if report["status"] != "CLOSED_TRAINING_MATRIX":
        raise ValueError("Plot only the complete declared matrix")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    jobs = {(j["job"]["cohort"], j["job"]["backend"], j["job"]["seed"]): j
            for j in report["jobs"]}
    cohorts = ("families32", "families128")
    colors = {"native": "#2866a3", "linear": "#c16b21"}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.7))
    for backend, color in colors.items():
        for split, style in (("train", "-"), ("dev", "--")):
            values = [[jobs[c, backend, seed]["splits"][split]["reference"][
                "family_macro_acceptance"] for c in cohorts] for seed in range(3)]
            for seed_values in values:
                axes[0].plot([0, 1], seed_values, style, color=color, alpha=.24, linewidth=1)
            axes[0].plot([0, 1], [mean(v[i] for v in values) for i in range(2)], style,
                         color=color, marker="o", linewidth=2.4, label=f"{backend} {split}")
        ranks = [[jobs[c, backend, seed]["splits"]["dev"]["counts"]["best_open_accepted"]
                  / jobs[c, backend, seed]["splits"]["dev"]["counts"]["complement_states"]
                  for c in cohorts] for seed in range(3)]
        for values in ranks:
            axes[1].plot([0, 1], values, color=color, alpha=.35, linewidth=1, marker=".")
        axes[1].plot([0, 1], [mean(v[i] for v in ranks) for i in range(2)], color=color,
                     marker="o", linewidth=2.4, label=backend)
        for seed in range(3):
            strata = jobs["families128", backend, seed]["splits"]["dev"]["reference"]["strata"]
            values = [strata[k]["accepted"] / strata[k]["labelled"]
                      for k in ("reference_proof_complete", "official_unanswerable_pool")]
            offset = (-.08 if backend == "native" else .08) + (seed - 1) * .025
            axes[2].plot([offset, 1 + offset], values, color=color, alpha=.6, marker="o",
                         linewidth=.9, label=backend if seed == 0 else None)
    sample = jobs["families128", "native", 0]["splits"]["dev"]["counts"]
    bm25 = sample["bm25_next_accepted"] / sample["complement_states"]
    baseline_label = f"BM25 next ({sample['bm25_next_accepted']}/{sample['complement_states']})"
    axes[1].axhline(bm25, color="#4a4a4a", linestyle=":", linewidth=2,
                   label=baseline_label)
    axes[0].set_title("Family-macro acceptance")
    axes[1].set_title("Dev best open, ignoring STOP")
    axes[2].set_title("Dev STOP recalls: 128 families")
    for ax in axes[:2]:
        ax.set_xticks([0, 1], ["32", "128"])
        ax.set_xlim(-.12, 1.12)
        ax.set_xlabel("Training families")
    axes[2].set_xticks([0, 1], ["Sufficient\n17 states", "Exhausted\n34 states"])
    axes[2].set_xlim(-.25, 1.25)
    for ax in axes:
        ax.set_ylim(-.03, 1.03)
        ax.set_ylabel("Fraction accepted / recalled")
        ax.grid(axis="y", alpha=.2)
        ax.spines[["right", "top"]].set_visible(False)
        ax.legend(fontsize=8, loc="upper left")
    fig.suptitle("Reference-supervised reader learning diagnostics", fontsize=14)
    fig.text(.5, .045, "Three fixed training seeds. Thin lines: individual seeds; bold: mean. "
             "Dev: 17 families / 168 related states.", ha="center", fontsize=9)
    fig.text(.5, .012, "FP32 in-training evaluation, fixed epoch 2; 38 vs 154 updates. "
             "Checkpoint reload, source semantics and end-to-end QA are separate evaluations.",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .09, 1, .94))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output.with_suffix(".png"), dpi=180)
    fig.savefig(args.output.with_suffix(".pdf"))
    plt.close(fig)


if __name__ == "__main__":
    main()
