"""Verify QR checkpoint bindings, tower updates and deployed scores on a measured TRAIN root."""

from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

import torch
from safetensors import safe_open

from milai_lab.datasets.memory_control_report import read_json, write_json
from milai_lab.datasets.memory_control_store import connect
from milai_lab.methods.qrag_dual_control import QragDualControl
from milai_lab.runners.control_policy_iteration import group_roster, read_gzip
from milai_lab.runners.qrag_milai_env import outcome_label
from milai_lab.runners.v13_phase import phase_directory, phase_unit


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--device", default="cuda")
    args = p.parse_args()
    with phase_unit(phase_directory(args.run), "qr"):
        verify(args)


def verify(args):
    cfg = read_json(args.run / "run.json")
    training = read_json(args.checkpoint / "training.json")
    snapshot = read_json(args.checkpoint / "controller.json")
    data = Path(cfg["dataset"])
    if data.is_dir():
        data = data / "memory_control.sqlite3"
    positions = defaultdict(dict)
    ledger_slots = set()
    paid = claims = unknown_requests = 0
    groups = set()
    counts = Counter()
    metrics = Counter()
    cost_sums, cost_counts = Counter(), Counter()
    probe = read_json(args.checkpoint / "score_probe.json")
    online = None
    minimum_probe_id = None
    for path in (args.run / "receipts").glob("*.json.gz"):
        match = re.fullmatch(r"step(\d+)_episode(\d+)_task(\d+)\.json\.gz", path.name)
        if match is None:
            continue
        if "through_roster_position" in training:
            if int(match[2]) > training["through_roster_position"]:
                continue
        elif int(match[1]) >= training["optimizer_updates"]:
            continue
        position, task_id = int(match[2]), int(match[3])
        r = read_gzip(path)
        if r["actual_requests"]:
            interval = range(r["ledger_before"], r["ledger_after"])
            if len(interval) != r["actual_requests"] or ledger_slots.intersection(interval):
                raise ValueError("QR receipts overlap or disagree with metered exposure")
            ledger_slots.update(interval)
        for field in (
            "reader_input_tokens",
            "reader_output_tokens",
            "reader_cached_tokens",
            "controller_gpu_ms",
            "reader_wall_ms",
            "reader_lease_wait_ms",
            "local_wall_ms",
        ):
            value = r["costs"].get(field)
            if value is not None:
                cost_sums[field] += value
                cost_counts[field] += 1
        claims += r["feedback_exposure"]
        paid += r["actual_requests"] or 0
        unknown_requests += r["actual_requests"] is None
        for t in r["transitions"]:
            assert t["action_id"] in {a["id"] for a in t["online"]["actions"]}
        counts[r["termination_reason"]] += 1
        counts["control_decisions"] += len(r["transitions"])
        positions[position][task_id] = {
            k: r[k]
            for k in (
                "grade",
                "termination_reason",
                "costs",
                "immediate_cost",
                "action_trace",
                "status",
                "receipt_id",
                "native_group_id",
            )
            if k in r
        }
        if probe:
            if r["receipt_id"] == probe["receipt_id"]:
                online = r["transitions"][probe["transition_index"]]["online"]
        elif minimum_probe_id is None or position < minimum_probe_id:
            minimum_probe_id = position
            online = r["transitions"][0]["online"]
    db = connect(data)
    try:
        for i, (source, group, primary) in enumerate(group_roster(db, cfg["seed"])):
            if i not in positions:
                if i > max(positions):
                    break
                continue
            rec = positions[i].copy()
            first = rec.pop(primary)
            other = next(iter(rec.values()), None)
            assert first["native_group_id"] == group and (
                not other or other["native_group_id"] == group
            )
            y = outcome_label(source, first, other)
            if y["quality_observed"] or y["future_cost_observed"]:
                groups.add(f"{source}/{group}")
            metrics["native_quality_observed"] += y["quality_observed"]
            metrics["future_cost_observed"] += y["future_cost_observed"]
    finally:
        db.close()
    if claims != training["calls"]:
        raise ValueError(
            f"Checkpoint exposure {training['calls']} differs from linked receipts {claims}"
        )
    if training.get("fitted_groups") and groups != set(training["fitted_groups"]):
        raise ValueError("Stored QR group bindings differ from the measured trajectories")
    if not training.get("fitted_groups"):
        # Early S0 pilot preceded compact group provenance. Reconstruct from its own receipts.
        training.update(
            fitted_groups=sorted(groups),
            observation_protocol="semantic_nav_delta_v2",
            supervision_mode="online_pqn_terminal",
            group_provenance="measured_trajectory_reconstruction",
        )
        write_json(args.checkpoint / "training.json", training)
    key = "encoder.layer.0.attention.qkv_proj.weight"
    weights = torch.load(
        args.checkpoint / "control.pt", weights_only=True, map_location="cpu", mmap=True
    )
    with safe_open(str(Path(snapshot["backbone"]) / "model.safetensors"), framework="pt") as base:
        init = base.get_tensor("new." + key).float()
    changes = {
        tower: (weights[tower + ".encoder." + key] - init).abs().max().item()
        for tower in ("state_tower", "action_tower")
    }
    if min(changes.values()) <= 0:
        raise ValueError("Both encoder towers must have changed on measured transitions")
    model = QragDualControl.load(args.checkpoint, device=args.device)
    assert online is not None
    with torch.inference_mode():
        utilities = model.net(online, cfg["utility_lambda"])
    if probe:
        assert probe["actions"] == [a["id"] for a in online["actions"]]
        torch.testing.assert_close(
            utilities.cpu(), torch.tensor(probe["saved_live_scores"]), rtol=1e-6, atol=1e-7
        )
    write_json(
        args.run / f"verified-{claims}.json",
        dict(
            checkpoint=str(args.checkpoint.resolve()),
            actual_new_requests=paid,
            unknown_request_receipts=unknown_requests,
            feedback_exposure=claims,
            completed_episodes=len(positions),
            fitted_native_groups=len(groups),
            measurements=dict(metrics),
            measured_cost_sums=dict(cost_sums),
            measured_cost_counts=dict(cost_counts),
            observed_terminations_and_steps=dict(counts),
            maximum_encoder_changes=changes,
            selected_action=online["actions"][utilities.argmax().item()]["id"],
            reloaded_score_count=len(utilities),
            comparison_to_live_scores=bool(probe),
            controller_gpu_ms=model.counters["forward_gpu_ms"],
        ),
    )


if __name__ == "__main__":
    main()
