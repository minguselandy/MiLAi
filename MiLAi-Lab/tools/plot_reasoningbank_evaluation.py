"""Export descriptive native-study figures using the external analysis environment."""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

LABELS = {
    "NATIVE_AGENT_OR_HISTORY": "Native", "OM_SYNC_PORT": "OM",
    "REASONINGBANK_BASE_PORT": "RB", "MILAI_EXPERIENCE_REVISION": "MiLAi",
}
COLORS = dict(zip(LABELS, ["#4b5563", "#b45309", "#0369a1", "#7e22ce"], strict=True))


def write_figure(figure, root, name):
    figure.savefig(root / (name + ".svg"), bbox_inches="tight")
    figure.savefig(root / (name + ".png"), dpi=180, bbox_inches="tight")
    plt.close(figure)


def plot(summary, root):
    root.mkdir(parents=True, exist_ok=True)
    arms = [a for a in summary["arms"]
            if a["condition"] == "main" and a["resource_point"] == "main"]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    panels = [("db_bench", "F"), ("db_bench", "O"), ("os_interaction", "F"),
              ("os_interaction", "O"), ("travel", "G")]
    fig, axes = plt.subplots(2, 3, figsize=(14, 8), constrained_layout=True)
    for axis, (domain, protocol) in zip(axes.flat, panels, strict=False):
        for arm in arms:
            if (arm["domain"], arm["protocol"]) != (domain, protocol):
                continue
            method = arm["method"]
            quality = arm["coverage_corrected_quality"]["ps" if domain == "travel" else "correct"]
            cost = arm["settled_tokens"] / arm["planned_sessions"]
            axis.scatter(cost, quality, color=COLORS[method], s=65)
            axis.annotate(
                f"{LABELS[method]} ({arm['terminal_units']}/{arm['planned_units']})",
                (cost, quality), xytext=(5, 5), textcoords="offset points", fontsize=8,
            )
        axis.set_title(f"{domain} / {protocol}")
        axis.set_xlabel("Settled text tokens / planned session")
        axis.set_ylabel("Person full pass (%)" if domain == "travel" else "Correct (%)")
        axis.set_ylim(-3, 103)
        axis.ticklabel_format(axis="x", style="sci", scilimits=(0, 0))
        axis.grid(alpha=.2)
    axes.flat[-1].axis("off")
    axes.flat[-1].text(0, .8,
        "Qwen3.6-35B-A3B-FP8 only\n"
        "Labels: terminal / planned units\n"
        "All maintenance included; support formation separate.\n"
        "Missing outputs remain in quality denominators.\n"
        "Unknown usage and paired intervals are in the tables.", va="top", fontsize=10)
    write_figure(fig, root, "quality-cost")

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for column, domain in enumerate(("db_bench", "os_interaction")):
        rows = {a["method"]: a["samples"] for a in arms
                if a["domain"] == domain and a["protocol"] == "O"}
        if not {"REASONINGBANK_BASE_PORT", "MILAI_EXPERIENCE_REVISION"} <= rows.keys():
            continue
        reference = {r["id"]: r for r in rows["REASONINGBANK_BASE_PORT"]}
        streams = collections.defaultdict(list)
        for row in rows["MILAI_EXPERIENCE_REVISION"]:
            streams[row["stream"]].append(row)
        for index, stream in enumerate(streams.values(), 1):
            qvalues, tvalues = [], []
            quality, tokens = 0, 0
            for row in stream:
                other = reference[row["id"]]
                quality += row["correct"] - other["correct"]
                tokens += row["model_cost"]["tokens"] - other["model_cost"]["tokens"]
                qvalues.append(quality)
                tvalues.append(tokens)
            positions = range(1, len(stream) + 1)
            axes[0, column].plot(positions, qvalues, label=f"Stream {index}")
            axes[1, column].plot(positions, tvalues, label=f"Stream {index}")
        axes[0, column].set_title(domain + ": MiLAi minus RB")
        axes[0, column].set_ylabel("Cumulative correct-task difference")
        axes[1, column].set_ylabel("Cumulative settled-token difference")
        for axis in axes[:, column]:
            axis.axhline(0, color="black", linewidth=.7)
            axis.set_xlabel("Native position within the frozen stream")
            axis.grid(alpha=.2)
            axis.legend(fontsize=8)
    write_figure(fig, root, "online-cumulative-differences")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4), constrained_layout=True)
    for arm in arms:
        if arm["domain"] != "travel":
            continue
        quality, tokens = collections.defaultdict(list), collections.defaultdict(list)
        for group in arm["samples"]:
            people = {person["position"]: person for person in group["persons"]}
            for position in range(1, group["planned_sessions"] + 1):
                quality[position].append(float(people.get(position, {}).get("full_pass", False)))
        for run in arm["runs"]:
            for path in (Path(run) / "provider").glob("*ledger*.jsonl"):
                sessions = collections.defaultdict(int)
                for line in path.read_text().splitlines():
                    event = json.loads(line)
                    if event["event"] == "SETTLED" and not event["session"].endswith(":base"):
                        sessions[event["session"]] += event["input_tokens"] + event["output_tokens"]
                for session, cost in sessions.items():
                    tokens[int(session.rsplit(":", 1)[1])].append(cost)
        method = arm["method"]
        for axis, values, scale in ((axes[0], quality, 100), (axes[1], tokens, 1)):
            positions = sorted(values)
            axis.plot(positions, [scale * sum(values[p]) / len(values[p]) for p in positions],
                      marker="o", label=LABELS[method], color=COLORS[method])
            axis.set_xlabel("Person position within group")
            axis.grid(alpha=.2)
            axis.legend()
    axes[0].set_ylabel("Person full pass (%)")
    axes[0].set_ylim(-3, 103)
    axes[1].set_ylabel("Settled tokens / attempted session")
    fig.suptitle("Travel position: descriptive, correlated within group; given-base cost separate")
    write_figure(fig, root, "travel-session-position")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plot(json.loads(args.summary.read_text()), args.output)


if __name__ == "__main__":
    main()
