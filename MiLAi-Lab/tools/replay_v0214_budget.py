"""Zero-generation reserve counterfactual using V0213's reconciled V0212 requests."""

import argparse
from pathlib import Path

from replay_v0213_cost import read, save, sha
from v0214_budget import BudgetContract, DeliveryBudget


def replay(previous: Path, root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False)
    report = {"status": "D3_ZERO_GENERATION_RESERVE_REPLAY", "queries": [],
              "new_generations": 0, "new_raw_tokens": 0,
              "historical_only_raw_cap": 20000, "new_execution_raw_cap": None,
              "frozen_final_reserve": 9216,
              "reserve_basis": "Original max prompt 8192 + output 1024, not a future answer",
              "behavioral_accuracy": "NOT_RUN_NOT_INFERRED"}
    for key in ("q002-2", "q004-2"):
        path = previous / key / "cost-replay.json"
        old = read(path)
        budget = DeliveryBudget(root / key / "ledger.jsonl",
                                BudgetContract(3, 9216, 1024, 9216, 20000))
        rows = []
        for number, request in enumerate(old["requests"], start=1):
            upper = request["prompt_tokens"] + request["output_reservation"]
            decision = budget.reserve(str(number), upper)
            rows.append({"historical_request": number, "input_upper": upper,
                         "nonfinal_decision": decision,
                         "final_at_same_input": budget.allow(upper, final=True)
                         if decision != "ALLOW" else "NOT_NEEDED"})
            if decision != "ALLOW":
                break
            budget.settle(str(number), request["prompt_tokens"] + request["output_tokens"])
        report["queries"].append({"key": key, "old_replay_sha256": sha(path.read_bytes()),
                                  "steps": rows, "original_unsent_headroom": old["unsent"][
                                      "headroom"], "components": old["query_components"]})
    save(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(replay(args.previous, args.root)["status"])
