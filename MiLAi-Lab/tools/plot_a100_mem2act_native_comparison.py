"""Plot closed all400 adapted scores; never turn partial predictions into a result figure."""

import argparse
import json
import math
import time
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def build_data(protocol, comparison):
    assert comparison["passed"]
    assert comparison["status"] == (
        "BOTH_FROZEN400_NATIVE_ADAPTED_SCORES_AND_DESCRIPTIVE_PAIRED_COMPARISON"
    )
    assert comparison["released_tasks"] == 400 and comparison["common_bank_sessions"] == 429
    assert comparison["reference_lineage_components"] == 341
    assert not comparison["query_iid_or_component_independence_confidence_interval_computed"]
    rows, by_method = [], {}
    for method, label, color in [
        ("fixed", "Fixed prefix", "#737b86"),
        ("primary", "E3 seed0 / u32", "#197e78"),
    ]:
        scores = read(protocol[method + "_scores"])
        records = scores["records"]
        assert scores["positions"] == len(records) == 400
        assert len({row["qa_id"] for row in records}) == 400
        statuses = Counter(row["native_status"] for row in records)
        assert set(statuses) <= {"COMPLETED", "FAILED"}
        completed_strict = sum(row["completed_strict_call_match"] for row in records)
        strict_intent = sum(row["metrics"]["strict_call_match"] for row in records)
        for row in records:
            assert row["completed_strict_call_match"] == (
                row["native_status"] == "COMPLETED" and row["metrics"]["strict_call_match"]
            )
        values = {
            "completed_strict_call_match_rate": completed_strict / 400,
            "strict_intent_match_rate_including_failed_Host": strict_intent / 400,
            "parameter_value_F1_task_macro": (
                sum(row["metrics"]["parameter_value_f1"] for row in records) / 400
            ),
            "BLEU1_canonical_JSON_task_macro": (
                sum(row["metrics"]["bleu1_json_lexical"] for row in records) / 400
            ),
        }
        compared = comparison["methods"][method]
        assert dict(statuses) == compared["native_first_status"]
        for key, value in values.items():
            assert 0 <= value <= 1
            assert math.isclose(value, scores[key], rel_tol=0, abs_tol=1e-14)
            assert math.isclose(value, compared[key], rel_tol=0, abs_tol=1e-14)
        assert compared["provider_response_callbacks_recorded"] == compared["actual_HTTP"]
        assert compared["known_tokens_equal_all_actual_paid_owner_ancestors"]
        by_method[method] = {row["qa_id"]: row for row in records}
        rows.append(
            dict(
                method=method,
                label=label,
                color=color,
                native_status=dict(statuses),
                completed_strict=completed_strict,
                strict_intent=strict_intent,
                metrics=values,
                response_callbacks=compared["provider_response_callbacks_recorded"],
                known_generation_tokens=compared["known_Host_tokens"],
                returned_NN_decisions=compared["actual_returned_NN_predictions"],
                returned_NN_input_tokens=compared["actual_returned_NN_input_tokens"],
                prediction_child_plus_measured_parent_CPU_hours=(
                    compared["whole_child_CPU_seconds_already_paid"]
                    + compared["measured_parent_CPU_seconds_already_paid"]
                )
                / 3600,
            )
        )
    gains = losses = 0
    assert len(comparison["per_task"]) == 400
    for row in comparison["per_task"]:
        left = by_method["fixed"][row["qa_id"]]
        right = by_method["primary"][row["qa_id"]]
        assert row["fixed_completed_strict"] == left["completed_strict_call_match"]
        assert row["primary_completed_strict"] == right["completed_strict_call_match"]
        gains += right["completed_strict_call_match"] and not left["completed_strict_call_match"]
        losses += left["completed_strict_call_match"] and not right["completed_strict_call_match"]
    assert gains == comparison["paired_task_gains"] and losses == comparison["paired_task_losses"]
    return dict(
        methods=rows,
        task_gains=gains,
        task_losses=losses,
        task_ties=400 - gains - losses,
        completed_strict_difference=(gains - losses) / 400,
    )


def metric_panel(ax, methods, fields, labels, counts=False):
    for index, row in enumerate(methods):
        positions = [number + (index - 0.5) * 0.28 for number in range(len(fields))]
        values = [100 * row["metrics"][field] for field in fields]
        bars = ax.barh(positions, values, height=0.25, color=row["color"], label=row["label"])
        for bar, value, field in zip(bars, values, fields, strict=True):
            prefix = (
                (
                    str(
                        row["completed_strict"]
                        if field.startswith("completed")
                        else row["strict_intent"]
                    )
                    + "/400  "
                )
                if counts
                else ""
            )
            inside = value >= 40
            ax.text(
                value - 1 if inside else value + 1,
                bar.get_y() + bar.get_height() / 2,
                prefix + f"{value:.2f}%",
                ha="right" if inside else "left",
                va="center",
                color="white" if inside else "#374151",
                fontsize=9,
            )
    ax.set_yticks(range(len(fields)), labels)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])
    ax.grid(axis="x", alpha=0.15)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.spines[["top", "right", "left"]].set_visible(False)


def render(data, prefix):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "pdf.fonttype": 42})
    figure, axes = plt.subplots(2, 2, figsize=(15, 10))
    figure.subplots_adjust(left=0.18, right=0.97, top=0.81, bottom=0.20, wspace=0.65, hspace=0.75)
    figure.suptitle("Mem2Act: all400 first outcomes per method", y=0.97, fontsize=18)
    figure.text(
        0.5,
        0.93,
        "MiLAi-adapted metrics; one public common bank; no business execution",
        ha="center",
        fontsize=11,
        color="#4b5563",
    )
    methods = data["methods"]
    metric_panel(
        axes[0, 0],
        methods,
        ["completed_strict_call_match_rate", "strict_intent_match_rate_including_failed_Host"],
        ["COMPLETED + strict intent", "Strict intent, any Host status"],
        counts=True,
    )
    axes[0, 0].set_title(
        "A  Completed calls and proposed intents", loc="left", pad=25, fontweight="bold"
    )
    axes[0, 0].legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=2, frameon=False)
    ax = axes[0, 1]
    for index, row in enumerate(methods):
        start = 0
        for status, color in [("COMPLETED", "#6b9483"), ("FAILED", "#bd7960")]:
            count = row["native_status"].get(status, 0)
            width = 100 * count / 400
            ax.barh(
                index,
                width,
                left=start,
                height=0.45,
                color=color,
                label=status if index == 0 else None,
            )
            if count:
                ax.text(
                    start + width / 2, index, str(count), ha="center", va="center", color="white"
                )
            start += width
    ax.set_yticks([0, 1], [row["label"] for row in methods])
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100], ["0", "25", "50", "75", "100%"])
    ax.tick_params(length=0)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.set_title("B  Native execution status / 400", loc="left", pad=25, fontweight="bold")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.20), ncol=2, frameon=False)
    metric_panel(
        axes[1, 0],
        methods,
        ["parameter_value_F1_task_macro", "BLEU1_canonical_JSON_task_macro"],
        ["Parameter-value F1", "Canonical-JSON BLEU1"],
    )
    axes[1, 0].set_title(
        "C  Adapted task-macro overlap / all400", loc="left", pad=25, fontweight="bold"
    )
    ax = axes[1, 1]
    ax.axis("off")
    ax.set_title("D  Actual prediction work only", loc="left", pad=25, fontweight="bold")
    fields = [
        ("Response callbacks", "response_callbacks"),
        ("Known generation tokens", "known_generation_tokens"),
        ("Returned NN decisions", "returned_NN_decisions"),
        ("Returned NN input tokens", "returned_NN_input_tokens"),
        ("Child + parent CPU h", "prediction_child_plus_measured_parent_CPU_hours"),
    ]
    cells = [
        [
            label,
            *[f"{row[key]:.3f}" if key.endswith("hours") else f"{row[key]:,}" for row in methods],
        ]
        for label, key in fields
    ]
    table = ax.table(
        cellText=cells,
        colLabels=["", "Fixed", "Primary"],
        cellLoc="right",
        colWidths=[0.53, 0.235, 0.235],
        bbox=[0, 0.18, 1, 0.80],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    for (row_index, column), cell in table.get_celld().items():
        cell.set_edgecolor("#e5e7eb")
        if row_index == 0:
            cell.set_facecolor("#f3f4f6")
        if column == 0:
            cell.set_text_props(ha="left")
    ax.text(
        0,
        -0.04,
        "Known error/partial responses are included.\n"
        "CPU includes native/load; no second addition.",
        transform=ax.transAxes,
        fontsize=9,
        color="#4b5563",
    )
    figure.text(
        0.04,
        0.105,
        f"Completed-strict task pairs: gains {data['task_gains']}, "
        f"losses {data['task_losses']}, ties {data['task_ties']}; "
        f"primary minus fixed {100 * data['completed_strict_difference']:+.2f}pp (descriptive).",
        fontsize=10,
        color="#4b5563",
    )
    figure.text(
        0.04,
        0.073,
        "400 tasks share429 sessions /16843 turns;341 reference components "
        "do not establish independent experiments. No IID/component CI.",
        fontsize=9,
        color="#4b5563",
    )
    figure.text(
        0.04,
        0.041,
        "Not paper TA/F1/BLEU or a leaderboard. Native completion is not intent "
        "correctness. Preparation, scoring, archives and final project costs are separate.",
        fontsize=9,
        color="#4b5563",
    )
    figure.text(
        0.04,
        0.013,
        "Prediction jobs include capture/replay overheads. Response callbacks differ from budget "
        "admissions. GPU busy time and money are unmeasured.",
        fontsize=8,
        color="#4b5563",
    )
    figure.savefig(prefix.with_suffix(".png"), dpi=180)
    figure.savefig(prefix.with_suffix(".pdf"))
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("comparison", type=Path)
    parser.add_argument("summary", type=Path)
    parser.add_argument("figure_prefix", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    protocol = read(args.protocol)
    gates = [Path(path) for path in protocol["archive_required_gates"]]
    pending = [str(path) for path in [*gates, args.comparison] if not path.exists()]
    if args.preflight_only:
        report = dict(
            status="MEM2ACT_FIGURE_PREFLIGHT_ONLY_NO_METRICS_OR_FIGURES_GENERATED",
            pending_actual_required_gates=pending,
            actual_all800_metric_rows_validated=False,
            actual_figure_generated=False,
        )
    else:
        assert not pending, pending
        assert all(read(path)["passed"] for path in gates)
        data = build_data(protocol, read(args.comparison))
        assert not any(
            args.figure_prefix.with_suffix(suffix).exists() for suffix in [".png", ".pdf"]
        )
        render(data, args.figure_prefix)
        report = dict(
            status="BOTH400_NATIVE_ADAPTED_METRICS_RECONCILED_AND_FIGURED",
            data=data,
            actual_all800_metric_rows_validated=True,
            actual_figure_generated=True,
            PNG=str(args.figure_prefix.with_suffix(".png")),
            PDF=str(args.figure_prefix.with_suffix(".pdf")),
        )
    report.update(
        passed=True,
        timestamp_epoch_seconds=time.time(),
        protocol=str(args.protocol.resolve()),
        comparison=str(args.comparison.resolve()),
        native_first_outcomes_scores_or_source_labels_changed=False,
        new_model_tokenizer_GPU_HTTP_business_or_original_ledger_calls=0,
        paper_TA_or_independent_user_CI_or_final_project_cost_claimed=False,
        no_sha_validation=True,
        goal_complete=False,
    )
    with args.summary.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(report["status"], flush=True)


if __name__ == "__main__":
    main()
