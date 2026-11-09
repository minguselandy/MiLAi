"""Plot closed development, confirmation and native conditional panels separately."""

import argparse
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def read(path):
    return json.loads(Path(path).read_text())


def build_panels(root, lab):
    dev_source = root / "task-dev64/source-author-reviews.json"
    seed_source = root / "e3-retained-replication/source-author-reviews.json"
    dev = read(dev_source)["cases"]
    seeds = read(seed_source)["cases"]
    selection = read(root / "task-dev64-development-selection.json")
    seed_closeout = read(root / "e3-retained-replication/answer-review-closeout.json")
    assert len(dev) == len(seeds) == 64
    assert [row["family"] for row in dev] == [row["family"] for row in seeds]
    dev_methods = [
        ("fixed-prefix", "Fixed prefix", dev, "#737b86"),
        ("incumbent-delivery-u16", "Initial E1", dev, "#a2a9b1"),
        ("b0-u33", "B0", dev, "#4a6f91"),
        ("b1-u33", "B1", dev, "#7a9bb8"),
        ("e3-aggregate-u32", "E3 seed0", dev, "#197e78"),
        ("e3-aggregate-seed1-u32", "E3 seed1", seeds, "#4a9d8f"),
        ("e3-aggregate-seed2-u32", "E3 seed2", seeds, "#83b8a8"),
    ]
    dev_rows = []
    for method, label, records, color in dev_methods:
        counts = Counter(row["reviews"][method]["answer_grade"] for row in records)
        count = counts["C"]
        expected = (
            selection["complete"][method]
            if records is dev
            else seed_closeout["methods"][method]["complete_full64"]
        )
        assert count == expected and sum(counts.values()) == 64
        dev_rows.append(dict(method=method, label=label, count=count, denominator=64,
                             percent=100 * count / 64, color=color))

    confirmation_path = lab / "data/manifests/a100-confirmation256-quality-results-20261107-v1.json"
    confirmation = read(confirmation_path)
    confirmation_rows = []
    confirmation_sources = []
    for method, label, color in [(m, label, color) for m, label, _, color in dev_methods
                                  if m == "fixed-prefix" or m.startswith("e3-")]:
        entry = confirmation["methods"][method]
        path = Path(entry["whole_manual_review"])
        records = read(path)["records"]
        counts = Counter(row["quality"] for row in records)
        assert len(records) == 256 and len({row["family"] for row in records}) == 256
        assert counts["C"] == entry["main_C"] and dict(counts) == {
            key: value for key, value in entry["quality_counts"].items() if value
        }
        confirmation_sources.append(str(path))
        confirmation_rows.append(dict(method=method, label=label, count=counts["C"],
                                      denominator=256, percent=100 * counts["C"] / 256,
                                      color=color))

    update_path = lab / "data/manifests/a100-D-new32-Source-View-operation-synthesis-20261107-v1.json"
    update = read(update_path)
    wire_source = lab / "data/manifests/a100-plan-D-audit-20261109-v1.json"
    wires = read(wire_source)["initial_Provider_wire_correction"]
    assert wires["passed"]
    assert wires["all_three_method_pairs_new32_first_Provider_wires_equal64_of64"]
    assert wires["first_tool_argument_batches_equal_zero_in_all_pairs"]
    update_rows = []
    update_sources = [str(wire_source)]
    for method, label, color in [("view_cache", "View cache", "#737b86"),
                                  ("view_cache_incremental", "Cache + incremental", "#7a9bb8"),
                                  ("e3-aggregate-u32", "E3 seed0", "#197e78")]:
        entry = update["methods"][method]
        path = Path(entry["review"])
        records = read(path)["records"]
        counts = Counter(row["answer_grade"] for row in records)
        family_sizes = Counter(row["family"] for row in records)
        assert len(records) == 320 and len(family_sizes) == 32
        assert set(family_sizes.values()) == {10} and counts["C"] == entry["complete"]
        update_sources.append(str(path))
        update_rows.append(dict(method=method, label=label, count=counts["C"],
                               denominator=320, percent=100 * counts["C"] / 320,
                               color=color))

    native_path = lab / "data/manifests/a100-reserved64-native-results-20261107-v1.json"
    native = read(native_path)
    native_rows = []
    for method, label, color in [("initial", "Initial E1", "#a2a9b1"),
                                  ("a0", "A0 legacy", "#4a6f91"),
                                  ("a1", "A1 native priority", "#197e78")]:
        entry = native["methods"][method]["family_balanced"]
        values = list(entry["by_family"].values())
        assert len(values) == entry["families"] == 64
        assert abs(sum(values) / 64 - entry["family_macro_balanced_accuracy"]) < 1e-14
        native_rows.append(dict(method=method, label=label,
                               percent=100 * entry["family_macro_balanced_accuracy"], color=color))
    constants = {method: 100 * native["methods"][method]["family_balanced"]["family_macro_balanced_accuracy"]
                 for method in ["constant-satisfies", "constant-does_not_satisfy"]}
    assert set(constants.values()) == {50.0}

    return [
        dict(id="development64", title="A  Exposed autonomous development", subtitle="64 source families | task C / 64",
             metric="implementation-assistant Source-reviewed complete task success", rows=dev_rows,
             sources=[str(dev_source), str(seed_source)],
             scope="Exposed DEVELOPMENT; different training recipes and u32/u33 checkpoints. No cross-stage causal contrast."),
        dict(id="confirmation256", title="B  Frozen autonomous confirmation", subtitle="256 source families | task C / 256",
             metric="implementation-assistant Source-reviewed complete task success", rows=confirmation_rows,
             sources=[str(confirmation_path), *confirmation_sources],
             scope="Fixed seed0 is primary; all three saved fits shown. Reviewer is the implementation assistant, not independent or blind. Native DEV185/TRAIN71 differs from the research role."),
        dict(id="update32", title="C  Update trajectories: development", subtitle="32 families x 10 requests | task C / 320",
             metric="implementation-assistant Source-reviewed complete task success", rows=update_rows,
             sources=[str(update_path), *update_sources],
             scope="32 clusters, not 320 independent sources. All three method pairs have equal first Provider request dicts for all64 requests; retrieval arguments and later trajectories differ and Host generation RNG is unmatched. E3 received no View in this panel."),
        dict(id="reserved64", title="D  Reserved native conditional queries", subtitle="64 query families | native balanced accuracy",
             metric="native family macro balanced accuracy", rows=native_rows,
             sources=[str(native_path)], constant_reference_percent=constants,
             scope="Shared corpus, not independent Source histories or Host success. 4066 known cells, 267 unjudged; no judged change pairs. No new fit or reselection."),
    ]


def render(panels, prefix):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.titlesize": 12, "pdf.fonttype": 42})
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    fig.subplots_adjust(left=.16, right=.97, top=.82, bottom=.14, wspace=.65, hspace=.65)
    fig.suptitle("Closed internal results: development signals and fixed evaluations", x=.5, y=.97, fontsize=17)
    fig.text(.5, .925, "Separate panels retain their own populations, metrics and exposure limits.",
             ha="center", color="#4b5563", fontsize=11)
    for ax, panel in zip(axes.flat, panels):
        rows = panel["rows"]
        positions = list(range(len(rows)))
        bars = ax.barh(positions, [row["percent"] for row in rows],
                       color=[row["color"] for row in rows], height=.62)
        ax.set_yticks(positions, [row["label"] for row in rows])
        ax.invert_yaxis()
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])
        ax.grid(axis="x", alpha=.15)
        ax.set_axisbelow(True)
        ax.tick_params(axis="both", length=0)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#d1d5db")
        ax.set_title(panel["title"], loc="left", pad=40, fontweight="bold")
        ax.text(0, 1.06, panel["subtitle"], transform=ax.transAxes, fontsize=10, color="#4b5563")
        for bar, row in zip(bars, rows):
            label = (f"{row['count']}/{row['denominator']}  ({row['percent']:.1f}%)"
                     if "count" in row else f"{row['percent']:.2f}%")
            ax.text(row["percent"] + 1.7, bar.get_y() + bar.get_height() / 2,
                    label, va="center", fontsize=9)
        if "constant_reference_percent" in panel:
            ax.axvline(50, color="#8a8f98", linestyle="--", linewidth=1.1, zorder=0)
            ax.text(.50, -.20, "Both constant predictions: 50%", transform=ax.transAxes,
                    ha="center", fontsize=9, color="#656b75")
    fig.text(.03, .065, "Task C labels: Source-guided review by the implementation assistant; not blind or independent human evaluation.",
             fontsize=10, color="#4b5563")
    fig.text(.03, .035, "No pooled score, cross-panel significance test or winner selection. LME is closed; Mem2Act and final project costs remain open.",
             fontsize=10, color="#4b5563")
    fig.savefig(prefix.with_suffix(".png"), dpi=180)
    fig.savefig(prefix.with_suffix(".pdf"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_root", type=Path)
    parser.add_argument("summary", type=Path)
    parser.add_argument("figure_prefix", type=Path)
    args = parser.parse_args()
    lab = Path(__file__).resolve().parents[1]
    panels = build_panels(args.artifact_root.resolve(), lab)
    summary = dict(status="CLOSED_INTERNAL_PANELS_RECONCILED_WITH_ORIGINAL_EXISTING_REVIEWS",
                   panels=panels, label_provenance="This execution assistant, acting as the implementation author; no independent human or blind review evidence.",
                   existing_labels_first_results_or_masks_changed=False,
                   pooled_score_or_cross_panel_causal_comparison=False,
                   external_full_results_or_final_project_costs_closed=False,
                   model_HTTP_or_ledger_calls=0, no_sha_validation=True, goal_complete=False)
    with args.summary.open("x") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    render(panels, args.figure_prefix)
    print(summary["status"], "4 panels; PNG/PDF written")


if __name__ == "__main__":
    main()
