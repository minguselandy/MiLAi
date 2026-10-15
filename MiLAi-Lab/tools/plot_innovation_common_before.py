"""Plot actual stage costs from the two reviewed common-before diagnostic summaries."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt


def main() -> None:
    lab = Path(__file__).resolve().parents[1]
    manifests = lab / "data/manifests"
    conditions = [
        json.loads((manifests / f"innovation-v4-common-before-{name}-summary.json").read_text())
        for name in ("v1", "short-v1")
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True, layout="constrained")
    for axis, condition, title in zip(axes, conditions, [
        "Maintenance: 8,192 / thinking on", "Maintenance: 2,048 / thinking off"
    ], strict=True):
        maintenance, reader = [], []
        for role in ("plain", "candidate", "delta"):
            row = condition["arms"][role]
            stages = row.get("stages", row.get("costs", {}).get("stages"))
            field = "total_tokens" if "stages" in row else "known_tokens"
            maintenance.append(sum(stages.get(stage, {}).get(field, 0)
                                   for stage in ("impact", "maintenance")) / 1000)
            reader.append(stages["reader"][field] / 1000)
        axis.bar(range(3), maintenance, label="Maintenance + Impact", color="#416986")
        axis.bar(range(3), reader, bottom=maintenance, label="Common Reader", color="#d9a45f")
        for x, (left, right) in enumerate(zip(maintenance, reader, strict=True)):
            axis.text(x, left + right + 0.45, f"{left + right:.1f}k", ha="center", fontsize=9)
        axis.set_xticks(range(3), ["Plain", "Full", "Delta"])
        axis.set_title(title, fontsize=11)
        axis.spines[["top", "right"]].set_visible(False)
        axis.set_ylim(0, 35)
    axes[0].set_ylabel("Generation tokens (thousands)")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("One actual initial state; cost order changes with generation settings",
                 fontsize=12)
    fig.supxlabel("Shared formation: 5,282 tokens, paid once. Reader: 8,192 / thinking on.\n"
                  "Exploratory one-history diagnostic; short-setting state faults in all arms.",
                  fontsize=8)
    output = lab / "docs/figures/innovation-v4-common-before.svg"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output)
    output.write_text("\n".join(line.rstrip() for line in output.read_text().splitlines()) + "\n")
    plt.close(fig)
    print(output)


if __name__ == "__main__":
    main()
