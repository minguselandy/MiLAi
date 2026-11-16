"""Plot the saved paired-result JSON; requires Matplotlib in the plotting environment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    import matplotlib  # type: ignore[import-not-found]

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # type: ignore[import-not-found]

    summary = json.loads(args.summary.read_text())
    arms = ["plain", "delta"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    bottom = [0, 0]
    for stage, color in (("maintenance", "#496a81"), ("reader", "#75a3a3"), ("judge", "#c7b299")):
        values = [summary["conditions"][arm]["costs"]["stages"][stage]["known_tokens"] / 1000
                  for arm in arms]
        axes[0].bar(arms, values, bottom=bottom, label=stage, color=color, width=0.6)
        bottom = [left + right for left, right in zip(bottom, values, strict=True)]
    axes[0].set(ylabel="Generation tokens (thousands)", title="Complete generation cost")
    axes[0].legend(frameon=False)
    bottom = [0, 0]
    for label, color in (("Correct", "#75a3a3"), ("invalid", "#c7b299"), ("Omission", "#aa6d68")):
        values = [summary["conditions"][arm]["first_qa"]["labels"].get(label, 0) for arm in arms]
        axes[1].bar(arms, values, bottom=bottom, label=label, color=color, width=0.6)
        bottom = [left + right for left, right in zip(bottom, values, strict=True)]
    opportunities = max(summary["conditions"][arm]["first_qa"]["opportunities"] for arm in arms)
    axes[1].set(ylabel="Question opportunities", title="Unchanged first Judge labels",
                ylim=(0, opportunities + 4))
    axes[1].legend(frameon=False, loc="upper center", ncol=3, fontsize=8)
    for ax in axes:
        ax.spines[["top", "right"]].set_visible(False)
    paired = summary["exploratory_paired_qa"]
    low, high = paired["percentile_95_interval"]
    fig.suptitle("Compact delta vs ordinary local updates — exploratory development batch")
    fig.text(0.5, 0.08, f"{paired['clusters']} exposed chains; paired Correct-rate difference "
             f"{paired['mean_difference']:.1%}, "
             f"cluster bootstrap 95% interval [{low:.1%}, {high:.1%}].",
             ha="center", fontsize=9)
    embedding_tokens = [summary["conditions"][arm]["costs"]["stages"]["embedding"]["known_tokens"]
                        for arm in arms]
    embedding = " / ".join(f"{arm} {tokens:,}"
                            for arm, tokens in zip(arms, embedding_tokens, strict=True))
    fig.text(0.5, 0.035, "Source/reference ambiguities retained. "
             "Raw-source QA is not state success. "
             f"Embedding: {embedding} tokens.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.13, 1, 0.94))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output)
    plt.close(fig)


if __name__ == "__main__":
    main()
