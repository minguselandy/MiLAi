"""Actual full-menu decisions and observed branch quality, without new model calls."""
from __future__ import annotations

import copy
import math
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, read_jsonl
from milai_lab.memory.literal_projection import expand_observation_state, observation_object
from milai_lab.methods.laya_memory_policy import payload_actions, project_operation_payload
from milai_lab.methods.memory_control import (
    FixedContextMemoryPolicy,
    FixedMemoryPolicy,
    MemoryAction,
    MemoryControlState,
    RulesMemoryPolicy,
)
from milai_lab.methods.memory_control_learning import decision_example


def full_menu_choice(actions: list[dict[str, Any]], logits: dict[str, float]) -> str:
    keys: list[str] = [action["id"] for action in actions]
    if set(keys) != set(logits) or not all(math.isfinite(x) for x in logits.values()):
        raise ValueError("Decision scores must cover the complete actual menu with finite logits")
    return max(keys, key=lambda key: logits[key])


def baseline_choice(call: dict[str, Any], policy: str, reads: int) -> str:
    controllers: dict[
        str, type[FixedContextMemoryPolicy | FixedMemoryPolicy | RulesMemoryPolicy]
    ] = {"raw_context": FixedContextMemoryPolicy, "raw_delivery": FixedContextMemoryPolicy,
         "fixed_prefix": FixedMemoryPolicy, "rules": RulesMemoryPolicy}
    controller = controllers[policy]
    offered = [MemoryAction(**a) for a in call["initial_actions"]
               if policy != "raw_delivery" or a["kind"] == "HANDOFF"]
    choice: str = controller(reads=reads).choose(
        MemoryControlState(**copy.deepcopy(call["initial_observation"])),
        offered)
    return choice


def decision_actions(
    call: dict[str, Any], logits: dict[str, float], baseline: str,
    alternatives: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Argmax, simple policy, optional declared alternative; identical bindings execute once."""
    actual = {a["id"]: a for a in call["initial_actions"]}
    selected: list[dict[str, Any]] = []
    for key in [full_menu_choice(call["initial_actions"], logits), baseline, *alternatives]:
        action = actual[key]
        if not any(all(action[k] == prior[k] for k in ("kind", "target", "parameters"))
                   for prior in selected):
            selected.append(copy.deepcopy(action))
    if len(selected) > 3:
        raise ValueError("Current-decision sampling admits at most three distinct bindings")
    return selected


def parameter_stratum(action: dict[str, Any]) -> str:
    """Describe offered parameter types, without task/source identity or outcomes."""
    parameters = action['parameters']
    if action['kind'] == 'READ' and 'observed_source' in parameters:
        granularity = 'full' if action['id'].startswith('source_full_') else 'range'
        return 'READ.observed_source.' + granularity
    return action['kind'] + '.' + ','.join(sorted(parameters))


def coverage_alternative(call: dict[str, Any], excluded: Sequence[dict[str, Any]],
                         coverage: Counter[str], seed: int) -> dict[str, Any] | None:
    """Nominate an undercovered legal READ/delivery binding from visible state only."""
    state = call['initial_observation']
    material = bool(state['visible_evidence'] or state.get('observed_evidence')
                    or state.get('retrieved_scopes'))
    candidates = []
    for action in call['initial_actions']:
        params = action['parameters']
        if (action['kind'] not in {'READ', 'HANDOFF'} or params.get('observe_only')
                or 'source_observation_cursor' in params
                or (action['kind'] == 'HANDOFF' and not material)):
            continue
        if any(all(action[k] == prior[k] for k in ('kind', 'target', 'parameters'))
               for prior in excluded):
            continue
        candidates.append(action)
    if not candidates:
        return None
    minimum = min(coverage[parameter_stratum(action)] for action in candidates)
    return copy.deepcopy(random.Random(seed).choice(  # noqa: S311 -- declared collection seed
        [a for a in candidates if coverage[parameter_stratum(a)] == minimum]))


def saved_decisions(evaluation: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Read the existing evaluator's literal inputs/outputs, bound to original raw captures."""
    run = read_json(evaluation / "run.json")
    rows = read_jsonl(Path(run["data"]))
    if run["status"] != "COMPLETED" or run["completed_states"] != len(rows):
        raise ValueError("Decision nomination needs a closed saved-model evaluation")
    decisions = {}
    for index, row in enumerate(rows):
        metadata = row["metadata"]
        # Current exports separate capture ID/path; earlier exports stored the path as capture.
        capture = metadata.get("path", metadata.get("capture"))
        if capture is None:
            continue  # Operation-retention rows have no replayable capture.
        call = read_json(Path(capture) / "call.json")
        actions = [asdict(a) for a in payload_actions(row)]
        before = expand_observation_state(observation_object(row["state"]))
        before.pop("action_bindings", None)  # Compared separately as executable bindings below.
        if before != call["initial_observation"] or actions != call["initial_actions"]:
            raise ValueError("Saved raw input is not the same captured observation and full menu")
        projected = project_operation_payload(row, run["operation_state"])
        actual = read_json(evaluation / "calls" / str(index) / "input.json")
        if actual != {k: projected[k] for k in ("state", "questions")}:
            raise ValueError("Saved prediction used different literal model inputs")
        prediction = read_json(evaluation / "calls" / str(index) / "output.json")
        choice = full_menu_choice(actions, prediction["logits"])
        if choice != prediction["choice"]:
            raise ValueError("Saved choice differs from full-menu argmax in offered order")
        key = str(Path(capture).resolve())
        if key in decisions:
            raise ValueError("One capture has multiple predictions in the nominated evaluation")
        decisions[key] = {"row": row, "call": call, "prediction": prediction,
                          "evaluation_index": index}
    return run, decisions


def captured_decisions(collection: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Reuse closed learned-policy scores from actual control traces, without another forward."""
    driver = read_json(collection / "driver.json")
    if driver["status"] in {"RUNNING", "LAUNCHING"}:
        raise ValueError("Finish the actual collection before nominating recorded decisions")
    histories = read_json(collection / "fixture.json")["histories"]
    banks = {(h["id"] if h.get("continuous") and not q.get("independent")
              else h["id"] + "-" + q["id"]):
             h for h in histories for q in h["requests"]}
    decisions: dict[str, dict[str, Any]] = {}
    traces: dict[Path, list[dict[str, Any]]] = {}
    model_conditions: set[tuple[str, str]] = set()
    unscored = []
    for path in sorted((collection / "frozen-retrieval-calls").glob("**/call.json")):
        call = read_json(path)
        if call["status"] not in {"ORIGINAL_COMPLETED", "ORIGINAL_FAILED"}:
            unscored.append({"capture": str(path.parent), "reason": "capture_not_closed"})
            continue
        if call["initial_observation"] is None or not call["initial_actions"]:
            unscored.append({"capture": str(path.parent), "reason": "no_actual_menu"})
            continue
        settings = read_json(Path(call["source_root"]) / "input-freeze.json")["config"]
        control = settings["memory_control"]
        if control["policy"] not in {"laya", "linear"}:
            unscored.append({"capture": str(path.parent), "reason": "not_a_finite_learned_policy"})
            continue
        projection = control.get("state_projection", "full")
        model_conditions.add((control["checkpoint"], projection))
        history = banks[call["bank"]]
        step = call.get("control_step", 0)
        row = decision_example({"before": call["initial_observation"],
            "actions": call["initial_actions"]}, {"family": history["source_group"],
            "split": history["split"], "capture": str(path.parent.resolve()),
            "event_id": f"{collection.resolve()}/{call['call_id']}/step-{step}",
            "row": len(decisions), "state_id": len(decisions)})
        projected = project_operation_payload(row, projection)
        expected = {key: projected[key] for key in ("state", "questions")}
        trace = Path(call["source_root"]) / call["host_prefix_trace"]
        if trace not in traces:
            traces[trace] = read_jsonl(trace)
        matches = [(i, e) for i, e in enumerate(traces[trace])
                   if e.get("event") == "memory_control_model_result" and e["input"] == expected]
        if not matches:
            unscored.append({"capture": str(path.parent), "reason": "no_recorded_full_menu_score"})
            continue
        if len(matches) != 1:
            raise ValueError("One actual state has ambiguous recorded model scores")
        index, event = matches[0]
        prediction = event["result"]
        choice = full_menu_choice(call["initial_actions"], prediction["logits"])
        initial = Path(call["initial_capture"]) if "initial_capture" in call else path.parent
        original = read_json(initial / "call.json")
        selected = [e for e in original["control_events"]
                    if e["phase"] == "decision_output" and e["step"] == step]
        if (len(selected) != 1 or selected[0]["selected"] != prediction["choice"]
                or choice != prediction["choice"]
                or selected[0]["before"] != call["initial_observation"]
                or selected[0]["actions"] != call["initial_actions"]):
            raise ValueError("Recorded full-menu score differs from the action actually chosen")
        decisions[str(path.parent.resolve())] = {
            "row": row, "call": call, "prediction": prediction,
            "prediction_location": {"trace": str(trace), "event_index": index},
            "evaluation_index": None}
    if len(model_conditions) != 1:
        raise ValueError("Recorded decisions require one declared checkpoint and input projection")
    checkpoint, projection = next(iter(model_conditions))
    return {"checkpoint": checkpoint, "operation_state": projection,
            "score_origin": "actual_closed_policy_trace", "unscored": unscored}, decisions


def relative_quality(row: dict[str, Any], choice: str, baseline: str, target: str,
                     executed: set[str]) -> str:
    if choice not in executed or baseline not in executed:
        return "unknown"
    if choice == baseline:
        return "same_binding"  # Identical decision is not a new known quality judgment.
    for pair in row["feedback"]["comparisons"]:
        if {pair["left"], pair["right"]} == {choice, baseline}:
            label = pair["basis"]["quality_before_resource_tiebreak"][target]
            if label in {"tie", "unknown"}:
                return str(label)
            return "win" if pair[label] == choice else "loss"
    return "unknown"


def summarize_choices(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep unknown in coverage; signed preferences are not task-success percentage points."""
    result: dict[str, Any] = {"states": len(records), "targets": {}}
    for target in ("answer", "delivery"):
        comparisons = {}
        for choice in ("full_menu", "executed_submenu", "fixed_type_order"):
            counts = Counter(r["quality_vs_baseline"][target][choice] for r in records)
            families: dict[str, list[int]] = defaultdict(list)
            for record in records:
                label = record["quality_vs_baseline"][target][choice]
                if label in {"win", "tie", "loss"}:
                    families[record["family"]].append({"win": 1, "tie": 0, "loss": -1}[label])
            comparisons[choice] = {
                "counts": dict(counts), "known_states": sum(map(len, families.values())),
                "families_with_known_comparison": len(families),
                "conditional_family_macro_signed_preference": (
                    sum(sum(v) / len(v) for v in families.values()) / len(families)
                    if families else None),
            }
        result["targets"][target] = {"comparisons": comparisons,
            "observed_improvement_space": dict(Counter(
                r["observed_improvement_space"][target] for r in records))}
    result["coverage"] = {key: sum(bool(r[key]) for r in records) for key in (
        "full_menu_executed", "baseline_executed", "full_menu_readout_completed")}
    return result
