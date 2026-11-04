"""Group actual saved full-menu choices; reuse closed raw outcomes and execute new bindings once."""
from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path
from typing import Any

from feedback_choices import saved_decisions
from milai_lab.harness.artifact_io import read_json, write_json


def binding_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(a[k] == b[k] for k in ("kind", "target", "parameters"))


def bind_nominees(nomination: dict[str, Any], conditions: dict[str, dict[str, Any]]) -> None:
    expected = {"update0": nomination["mandatory_update0"],
                **{n["arm"]: n["checkpoint"] for n in nomination["nominees"]}}
    if set(conditions) != set(expected):
        raise ValueError("Task choices require exactly the two nominees and mandatory update0")
    common = {"task": "memory_operation", "operation_state": "shared_actions",
              "max_len": 16384, "head_max_len": 2048, "device": "cpu", "threads": 4,
              "loaded_weight_dtype": "torch.float32", "reference_compile_override": False,
              "mha_fastpath_enabled": False}
    for name, run in conditions.items():
        if Path(run["checkpoint"]).resolve() != Path(expected[name]).resolve():
            raise ValueError("Saved evaluator checkpoint differs from the E1 nomination")
        if any(run[k] != value for k, value in common.items()):
            raise ValueError("Saved evaluation differs from the declared matched input condition")


def matched_closed_bindings(
    panel: dict[str, Any], outcomes: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Load first outcomes from the same captured states and declared two-step continuation."""
    states = {str(Path(p['capture']).resolve()): p for p in panel['positions']
              if p['status'] == 'ACTUAL_PRE_HANDOFF_EXPORTED'}
    known: dict[str, list[dict[str, Any]]] = {}
    for record in read_json(outcomes)['records']:
        capture = str(Path(record['capture']).resolve())
        if capture not in states or record['family'] != states[capture]['family']:
            raise ValueError('Closed branch belongs to another captured state or source family')
        call = read_json(Path(capture) / 'call.json')
        replay = read_json(Path(record['case']) / 'replay.json')
        readout = read_json(Path(record['readout']))
        action = record['first_action']
        if (replay['status'] != 'COMPLETED'
                or Path(replay['captured_call']).resolve() != Path(capture)
                or replay['source_version'] != call['source_version']['git_commit']
                or replay['policy'] != {'policy': 'fixed_context', 'reads': 4}
                or replay['intervention'] != {'first_action': action, 'continuation_steps': 2}
                or action not in call['initial_actions']
                or not replay['result']['frozen_initial_observation_and_actions_equal']
                or not replay['result']['frozen_request_and_allowance_equal']):
            raise ValueError('Closed branch changed its before, full action or continuation')
        if (readout['status'] not in {'COMPLETED', 'FAILED'}
                or readout['status'] != record['status']
                or readout.get('answer') != record['answer']
                or readout['source_version'] != replay['source_version']
                or Path(readout['captured_call']).resolve() != Path(capture)
                or Path(readout['branch_result']).resolve()
                != (Path(record['case']) / 'replay.json').resolve()
                or readout['readout_origin'] != 'actual_same_before_branch'):
            raise ValueError('Closed Reader outcome no longer binds the actual matched branch')
        baseline_path = Path(states[capture]['baseline_readout']['result'])
        old_wire = read_json(baseline_path.parent / 'request.json')
        branch_wire = read_json(Path(record['readout']).parent / 'request.json')
        old_body = json.loads(old_wire['messages'][1]['content'])
        branch_body = json.loads(branch_wire['messages'][1]['content'])
        if list(old_body) != list(branch_body):
            raise ValueError('Closed branch changed the declared Reader presentation')
        old_body.pop('memory')
        branch_body.pop('memory')
        old_wire['messages'][1]['content'] = json.dumps(old_body, ensure_ascii=False)
        branch_wire['messages'][1]['content'] = json.dumps(branch_body, ensure_ascii=False)
        if old_wire != branch_wire:
            raise ValueError('Closed branch changed the Reader condition outside its packet')
        bindings = known.setdefault(capture, [])
        if any(binding_equal(row['action'], action) for row in bindings):
            raise ValueError('One matched binding cannot select among multiple Reader outcomes')
        bindings.append({'action': copy.deepcopy(action), 'origin': 'closed_matched_branch',
            'readout': {'status': readout['status'], 'result': record['readout'],
                        'answer': readout.get('answer'), 'error': readout.get('error')},
            'source_outcomes': str(outcomes.resolve()), 'source_case': record['case'],
            'models': []})
    return known


def group_choices(panel: dict[str, Any], decisions: dict[str, dict[str, dict[str, Any]]],
                  closed_bindings: dict[str, list[dict[str, Any]]] | None = None,
                  ) -> dict[str, Any]:
    positions, jobs = [], []
    for position in panel["positions"]:
        record = {**position, "model_choices": {}}
        positions.append(record)
        if position["status"] != "ACTUAL_PRE_HANDOFF_EXPORTED":
            record["model_choices"] = {name: {"status": "NO_REACHED_STATE"} for name in decisions}
            continue
        capture = str(Path(position["capture"]).resolve())
        call = read_json(Path(capture) / "call.json")
        bindings = [{"action": position["baseline_action"], "origin": "closed_raw_collection",
                     "readout": position["baseline_readout"], "models": []}]
        for known in (closed_bindings or {}).get(capture, []):
            if any(binding_equal(known['action'], row['action']) for row in bindings):
                raise ValueError('Known branches duplicate an already bound first outcome')
            bindings.append(copy.deepcopy(known))
        for name, scores in decisions.items():
            actual = scores[capture]
            if actual["call"] != call:
                raise ValueError("Saved choice no longer refers to the fixed actual before")
            choice = actual["prediction"]["choice"]
            action, = [a for a in call["initial_actions"] if a["id"] == choice]
            index = next((i for i, item in enumerate(bindings)
                          if binding_equal(item["action"], action)), None)
            if index is None:
                index = len(bindings)
                job_id = f"state-{position['evaluation_index']:03d}-binding-{index:02d}"
                bindings.append({"action": action, "origin": "unexecuted", "job_id": job_id,
                                 "models": []})
                jobs.append({"name": job_id, "capture": capture, "policy": {
                    "policy": "fixed_context", "reads": 4}, "intervention": {
                    "first_action": action, "continuation_steps": 2}})
            bindings[index]["models"].append(name)
            status = {'closed_raw_collection': 'REUSED_CLOSED_RAW_OUTCOME',
                      'closed_matched_branch': 'REUSED_CLOSED_MATCHED_BRANCH_OUTCOME',
                      'unexecuted': 'PENDING_EXECUTION'}[bindings[index]['origin']]
            record["model_choices"][name] = {"action": action, "binding_index": index,
                                           "status": status}
        record["bindings"] = bindings
    return {"positions": positions, "jobs": jobs}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("panel", type=Path)
    parser.add_argument("nomination", type=Path)
    parser.add_argument("evaluations", type=Path,
                        help="JSON update0/nominee-arm -> closed evaluator directory")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    start = time.process_time()
    panel = read_json(args.panel)
    evaluations = read_json(args.evaluations)
    conditions, decisions = {}, {}
    for name, path in evaluations.items():
        conditions[name], decisions[name] = saved_decisions(Path(path))
    bind_nominees(read_json(args.nomination), conditions)
    expected = {str(Path(p["capture"]).resolve()) for p in panel["positions"]
                if p["status"] == "ACTUAL_PRE_HANDOFF_EXPORTED"}
    if any(set(scores) != expected for scores in decisions.values()):
        raise ValueError("Every nominated model and update0 must cover the same reached dev states")
    result = group_choices(panel, decisions)
    args.output.mkdir(parents=True, exist_ok=False)
    captures = args.output / "captures"
    captures.mkdir()
    aliases = {path: f"state-{i:03d}" for i, path in enumerate(sorted(expected))}
    for path, alias in aliases.items():
        (captures / alias).symlink_to(path, target_is_directory=True)
    policies = [{**job, "capture": aliases[job["capture"]]} for job in result["jobs"]]
    write_json(args.output / "policies.json", policies)
    write_json(args.output / "choices.json", {
        "status": "SAVED_CHOICES_BOUND;NEW_BINDINGS_NOT_EXECUTED",
        "panel": str(args.panel.resolve()), "nomination": str(args.nomination.resolve()),
        "model_conditions": conditions, "planned_positions": panel["planned_positions"],
        "positions": result["positions"], "new_distinct_bindings": len(policies),
        "model_calls": 0, "ledger_recorded": False, "no_sha_validation": True,
        "cpu_seconds_pending": time.process_time()-start,
        "scope": "Complete original offered-menu choices, including acquisition actions. Reuse "
            "a closed raw outcome when the full binding matches, retaining failures. "
            "Other identical bindings across nominees execute once. Missing states remain in the "
            "planned denominator. New bindings use fixed continuation2 capped by actual remaining "
            "allowance; neither pending choices nor same-kind actions borrow an outcome."})
    print(json.dumps({"planned_positions": panel["planned_positions"],
                      "new_bindings": len(policies)}))


if __name__ == "__main__":
    main()
