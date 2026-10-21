"""Export audited operation curves as PNG/SVG; no model or project imports required."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--saved-results", type=Path)
    parser.add_argument("--baseline-summary", type=Path)
    args = parser.parse_args()
    started, cpu = time.perf_counter(), time.process_time()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    analysis = json.loads(args.analysis.read_text())
    saved = json.loads(args.saved_results.read_text()) if args.saved_results else None
    points = analysis["curve"]
    updates = [p["update"] for p in points]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.4), layout="constrained")
    for split, color in (("train", "#2166ac"), ("dev", "#b2182b")):
        axes[0].plot(updates, [p[split]["family_macro_acceptance"] for p in points],
                     "o-", color=color, label=f"In-memory GPU {split}")
    if args.baseline_summary:
        baselines = json.loads(args.baseline_summary.read_text())["baselines"]
        for name, score in baselines.items():
            axes[0].axhline(score["family_macro_acceptance"], linewidth=.8, linestyle=":",
                            label=f"Recorded-state {name}")
    axes[1].plot(updates, [p["train_dev_family_gap"] for p in points], "o-",
                 color="#2166ac", label="In-memory GPU train minus dev")
    axes[1].axhline(0, color="grey", linewidth=.8)
    for name, color in (("answer", "#762a83"), ("delivery", "#1b7837")):
        values = [p.get("feedback-dev", {}).get(name, {}).get(
            "family_macro_state_pair_accuracy") for p in points]
        if any(value is not None for value in values):
            axes[2].plot(updates, values, "o-", color=color, label=f"In-memory GPU {name}")
    if saved:
        saved_points = saved["curve"]
        saved_updates = [p["update"] for p in saved_points]
        axes[0].plot(saved_updates, [p["dev"]["family_macro_acceptance"] for p in saved_points],
                     "s--", color="#ef8a62", label="Saved CPU dev")
        selected = saved["deployment_selection"]
        axes[0].scatter([selected["update"]], [selected["metric"]], marker="*", s=180,
                        color="black", zorder=5, label="Saved CPU selected")
        if "selected_train_dev_family_gap" in saved:
            axes[1].scatter([selected["update"]], [saved["selected_train_dev_family_gap"]],
                            marker="*", s=160, color="#ef8a62", label="Saved CPU selected gap")
        for name, color in (("answer", "#762a83"), ("delivery", "#1b7837")):
            values = [p["feedback-dev"].get(name, {}).get("family_macro_state_pair_accuracy")
                      for p in saved_points]
            if any(value is not None for value in values):
                axes[2].plot(saved_updates, values, "s--", color=color, label=f"Saved CPU {name}")
    titles = ("Operation acceptance", "Matching train/dev gap", "Secondary feedback preferences")
    for axis, title in zip(axes, titles, strict=True):
        axis.set_title(title)
        axis.set_xlabel("Optimizer updates")
        axis.grid(alpha=.2)
        handles, labels = axis.get_legend_handles_labels()
        if handles:
            axis.legend(handles, labels, fontsize=7, loc="best")
    axes[0].set_ylabel("Source-family macro acceptance")
    axes[0].set_ylim(0, 1)
    axes[1].set_ylabel("Source-family macro difference")
    axes[2].set_ylabel("Family macro of state pair accuracy")
    axes[2].set_ylim(0, 1)
    subtitle = "Static reviewed preferences; not Host success. "
    subtitle += ("Saved CPU selection shown separately." if saved
                 else "Saved-model evaluation pending; no deployment selection.")
    fig.suptitle(args.title + "\n" + subtitle, fontsize=12)
    args.output.mkdir(parents=True, exist_ok=False)
    for extension in ("png", "svg"):
        fig.savefig(args.output / f"curve.{extension}", dpi=180)
    plt.close(fig)
    report = {"analysis": str(args.analysis),
        "saved_results": str(args.saved_results) if args.saved_results else None,
        "baseline_summary": str(args.baseline_summary) if args.baseline_summary else None,
        "title": args.title, "model_calls": 0, "no_sha_validation": True,
        "ledger_recorded": False,
        "compute": {"cpu_seconds": time.process_time()-cpu,
                    "wall_seconds": time.perf_counter()-started}}
    (args.output / "plot.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
