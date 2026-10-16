"""Run the same real Reader on frozen bounded selections, then official scoring.

Prediction reads only runtime cases and selected IDs. Answers, support flags and
answerability enter only the separate scoring phase. Missing first outputs stay
missing; no replay of an unconfirmed request and no substitution of an answer.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.runners.edit_benchmarks import BenchmarkRun
from run_bounded_reader_selection import read_rows


def reader_input(case, selected):
    candidates = {row["id"]: {key: row[key] for key in ("id", "title", "text")}
                  for row in case["candidates"]}
    # Fix final presentation order while retaining the controller's open order in its trace.
    delivered = [key for key in candidates if key in selected]
    if set(delivered) != set(selected):
        raise ValueError("Selected evidence is outside the prepared candidate pool")
    evidence = [candidates[key] for key in delivered]
    messages = [
        {"role": "system", "content": (
            "Answer the question using only the supplied documents. Return the shortest answer "
            "that resolves the question, whether these documents are sufficient, and the IDs "
            "supporting the answer. If they are insufficient, set answerable=false and answer="
            "an empty string. Insufficiency concerns this evidence, not whether the fact exists."
        )},
        {"role": "user", "content": json.dumps({"question": case["question"],
                                                    "documents": evidence}, ensure_ascii=False)},
    ]
    support = {"type": "array", "items": {"type": "string", "enum": delivered}}
    if not selected:
        support = {"type": "array", "items": {"type": "string"}, "maxItems": 0}
    schema = {"type": "object", "additionalProperties": False,
              "required": ["answer", "answerable", "support_ids"], "properties": {
                  "answer": {"type": "string"}, "answerable": {"type": "boolean"},
                  "support_ids": support}}
    return messages, {"type": "json_schema", "json_schema": {
        "name": "bounded_reader_answer", "strict": True, "schema": schema}}


def predict(protocol, output, *, preview=False):
    import jsonschema

    total_start, total_cpu = time.perf_counter(), time.process_time()
    cases = read_rows(Path(protocol["cases"]))
    # Resolve the full finite matrix before constructing any provider client.
    selections = {(case["case_id"], arm): read_json(
        Path(config["selection_root"]) / case["case_id"] / f"{config['policy']}.json")
        for case in cases for arm, config in protocol["arms"].items()}
    execution = BenchmarkRun(protocol["reader"], output)
    run = {"status": "RUNNING", "phase": "preview" if preview else "predict",
           "planned": len(selections), "completed": 0, "known_failures": 0,
           "fresh_reader_attempts": 0, "reused_reader_outputs": 0,
           "known_failed_reader_calls": 0}
    input_keys, call_costs = {}, {}
    arm_order = list(protocol["arms"])
    if "arm_order_seed" in protocol:
        random.Random(protocol["arm_order_seed"]).shuffle(arm_order)  # noqa: S311
    write_json(output / "run.json", run)
    try:
        for case_index, case in enumerate(cases):
            offset = case_index % len(arm_order) if "arm_order_seed" in protocol else 0
            for arm in arm_order[offset:] + arm_order[:offset]:
                start, cpu = time.perf_counter(), time.process_time()
                selected = selections[case["case_id"], arm]["selected_ids"]
                messages, schema = reader_input(case, selected)
                key = f"musique/{arm}/{case['case_id']}/answer"
                if protocol.get("reuse_identical_reader_inputs", False):
                    # Literal equality only. The existing provider receipt cache is authoritative.
                    identity = json.dumps([messages, schema], ensure_ascii=False, sort_keys=True)
                    if identity not in input_keys:
                        input_keys[identity] = f"musique/shared/{len(input_keys)}/answer"
                    key = input_keys[identity]
                if preview:
                    tokens = execution.input_tokens(messages, enable_thinking=True)
                    if tokens + execution.settings["model"]["max_tokens"] + 512 > 65536:
                        raise ValueError("Common Reader input exceeds declared capacity")
                    result = {"case_id": case["case_id"], "arm": arm, "input_tokens": tokens,
                              "selected_ids": selected, "model_requests": 0}
                else:
                    reused = (output / "http" / key / "response.json").exists()
                    run["reused_reader_outputs" if reused else "fresh_reader_attempts"] += 1
                    result = {"case_id": case["case_id"], "arm": arm, "selected_ids": selected,
                              "reader_call_key": key, "reused_reader_output": reused,
                              "answer": None, "failure": None}
                    try:
                        raw = execution.call(key, messages, structured=True,
                                             response_format=schema, enable_thinking=True)
                        answer = json.loads(raw)
                        jsonschema.validate(answer, schema["json_schema"]["schema"])
                        result["answer"] = answer
                    except (ValueError, jsonschema.ValidationError) as error:
                        if not (output / "http" / key / "response.json").exists():
                            raise
                        result["failure"] = {"type": type(error).__name__, "message": str(error)}
                        run["known_failures"] += 1
                        run["known_failed_reader_calls"] += not reused
                    observed_wall = time.perf_counter() - start
                    observed_cpu = time.process_time() - cpu
                    if key not in call_costs:
                        call_costs[key] = {"wall_seconds": observed_wall,
                                           "cpu_seconds": observed_cpu}
                    result.update(**call_costs[key], observed_wall_seconds=observed_wall,
                                  observed_cpu_seconds=observed_cpu,
                                  timing_scope="first-call cost; replay measured separately")
                write_json(output / "predictions" / arm / f"{case['case_id']}.json", result)
                run["completed"] += 1
                write_json(output / "run.json", run)
                print(json.dumps({"completed": run["completed"], "planned": run["planned"],
                                  "known_failures": run["known_failures"]}), flush=True)
        run["status"] = "COMPLETED"
    except BaseException as error:
        run.update(status="FAILED", error_type=type(error).__name__, error=str(error))
        raise
    finally:
        execution.close()
        run.update(actual_wall_seconds=time.perf_counter() - total_start,
                   actual_cpu_seconds=time.process_time() - total_cpu,
                   unique_reader_inputs=len(input_keys))
        write_json(output / "reader-call-costs.json", call_costs)
        write_json(output / "run.json", run)


def paragraph_keys(paragraphs, indices):
    return {(paragraphs[i]["title"], paragraphs[i]["paragraph_text"]) for i in indices}


def score(protocol, prediction_root, output):
    official = Path(protocol["official_scorer"])
    sys.path.insert(0, str(official.resolve()))
    from metrics.answer import AnswerMetric
    from metrics.support import SupportMetric

    labels = read_rows(Path(protocol["labels"]))
    groups = defaultdict(list)
    for row in labels:
        groups[row["source"]["id"]].append(row)
    paired = [rows for rows in groups.values()
              if len(rows) == 2 and {r["source"]["answerable"] for r in rows} == {False, True}]
    total_positive = sum(row["source"]["answerable"] for row in labels)
    results = {}
    for arm, config in protocol["arms"].items():
        answers, supports = AnswerMetric(), SupportMetric()
        observations, predictions = {}, {}
        positive_valid = sufficient_correct = delivered_count = pool_covered = 0
        missing = []
        for row in labels:
            cid, source = row["case_id"], row["source"]
            prediction_file = prediction_root / "predictions" / arm / f"{cid}.json"
            selected = read_json(Path(config["selection_root"]) / cid / f"{config['policy']}.json")
            mapping = row["candidate_source_indices"]
            chosen = [mapping[key] for key in selected["selected_ids"]]
            paragraphs = source["paragraphs"]
            required = paragraph_keys(paragraphs, (i for i, p in enumerate(paragraphs)
                                                   if p["is_supporting"]))
            if source["answerable"]:
                delivered_count += required <= paragraph_keys(paragraphs, chosen)
                pool_covered += required <= paragraph_keys(paragraphs, mapping.values())
            result = read_json(prediction_file) if prediction_file.exists() else {"answer": None}
            if result["answer"] is None:
                missing.append(cid)
                observations[cid] = {"missing": True}
                continue
            answer = result["answer"]
            support_indices = [paragraphs[mapping[key]]["idx"] for key in answer["support_ids"]]
            prediction = {"id": source["id"], "predicted_answer": answer["answer"],
                          "predicted_answerable": answer["answerable"],
                          "predicted_support_idxs": support_indices}
            predictions[cid] = prediction
            sufficient_correct += answer["answerable"] == source["answerable"]
            if source["answerable"]:
                positive_valid += 1
                answers(answer["answer"], [source["answer"], *source["answer_aliases"]])
                supports(support_indices, [p["idx"] for p in paragraphs if p["is_supporting"]])
            observations[cid] = {"missing": False, "prediction": prediction,
                "reference_support_delivered": required <= paragraph_keys(paragraphs, chosen)}
        valid_pairs = [pair for pair in paired
                       if all(row["case_id"] in predictions for row in pair)]
        paired_result = None
        if valid_pairs:
            paired_gold = [row["source"] for pair in valid_pairs for row in pair]
            paired_pred = [predictions[row["case_id"]] for pair in valid_pairs for row in pair]
            folder = output / arm
            for name, rows in (("paired-gold", paired_gold), ("paired-predictions", paired_pred)):
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{name}.jsonl").write_text(
                    "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            destination = folder / "native-paired-metrics.json"
            subprocess.run(  # noqa: S603 -- explicit argv for the reviewed official scorer
                [sys.executable, str(official / "evaluate_v1.0.py"),
                 str(folder / "paired-predictions.jsonl"), str(folder / "paired-gold.jsonl"),
                 "--output_filepath", str(destination)], check=True, capture_output=True, text=True)
            paired_result = read_json(destination)
        em, f1 = answers.get_metric()
        _, support_f1 = supports.get_metric()
        results[arm] = {"cases": len(labels), "missing": missing,
                        "answerable_cases": total_positive, "valid_answerable": positive_valid,
                        "answer_em_with_missing_zero": em * positive_valid / total_positive,
                        "answer_f1_with_missing_zero": f1 * positive_valid / total_positive,
                        "support_f1_with_missing_zero": (
                            support_f1 * positive_valid / total_positive),
                        "answerability_correct": sufficient_correct,
                        "reference_proof_in_pool": pool_covered,
                        "reference_proof_delivered": delivered_count,
                        "planned_pairs": len(paired), "valid_pairs": len(valid_pairs),
                        "native_metrics_valid_pairs": paired_result,
                        "observations": observations}
        results[arm]["group_answer_sufficiency_f1_with_missing_zero"] = (
            (paired_result["group_answer_sufficiency_f1"] if paired_result else 0.0)
            * len(valid_pairs) / len(paired)) if paired else None
    write_json(output / "results.json", {"arms": results,
        "scope": "Derived dev cohort, native metrics for complete pairs; missing outputs explicit. "
                 "Reference support coverage does not enumerate every semantic equivalent."})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--phase", choices=("preview", "predict", "score"), required=True)
    parser.add_argument("--predictions", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol = read_json(args.protocol)
    write_json(args.output / "protocol.json", protocol)
    if args.phase == "score":
        score(protocol, args.predictions, args.output)
    else:
        predict(protocol, args.output, preview=args.phase == "preview")


if __name__ == "__main__":
    main()
