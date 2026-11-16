"""Score literal closed Reader or autonomous Host answers with official QASPER functions."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from milai_lab.harness.artifact_io import read_json, write_json


def read_answers(cases: list[dict[str, Any]], paths: dict[str, str | None]
                 ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if set(paths) != {case["family"] for case in cases}:
        raise ValueError("Keep every declared QASPER source position, including missing readouts")
    predictions, receipts = {}, []
    for case in cases:
        family, question_id = case["family"], case["native_control"]["native_question_id"]
        record: dict[str, Any] = {"family": family, "question_id": question_id,
                                  "readout": paths[family], "status": "MISSING_READOUT"}
        receipts.append(record)
        path = paths[family]
        if path is None:
            continue
        readout = read_json(Path(path))
        if readout["status"] not in {"COMPLETED", "FAILED", "NOT_EXECUTED"}:
            raise ValueError("QASPER agreement requires terminal first-attempt readouts")
        call = read_json(Path(readout["captured_call"]) / "call.json")
        request = case["request"]
        if (call["public_message"]["content"] != request["content"]
                or call["public_message"]["message_id"] != request["id"]
                or call["bank"] != case["history"] + "-" + request["id"]):
            raise ValueError("Reader answer does not belong to the declared paper question")
        record["status"] = readout["status"]
        if readout["status"] == "COMPLETED":
            # Preserve the complete answer, including qualifications and citations.
            predictions[question_id] = {"answer": readout["answer"], "evidence": []}
    return predictions, receipts


def read_host_answers(cases: list[dict[str, Any]], paths: dict[str, str | None]
                      ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Bind independent native paper questions; failed/synthetic deliveries stay missing."""
    if set(paths) != {case['family'] for case in cases}:
        raise ValueError('Keep every declared QASPER position, including missing Host results')
    predictions, receipts = {}, []
    for case in cases:
        family = case['family']
        question_id = case['native_control']['native_question_id']
        path = paths[family]
        record: dict[str, Any] = {'family': family, 'question_id': question_id,
            'result': path, 'status': 'MISSING_HOST_RESULT'}
        receipts.append(record)
        if path is None:
            continue
        result = read_json(Path(path))
        if ('given_retrieval_request' in result or result.get('host_request_generated') is False):
            raise ValueError('Given requests/conditional readouts are not autonomous Host answers')
        if result['status'] not in {'COMPLETED', 'FAILED', 'BUDGET_EXHAUSTED', 'NOT_EXECUTED'}:
            raise ValueError('QASPER agreement requires terminal first-attempt Host results')
        request = case['request']
        if (result['content'] != request['content'] or result['message_id'] != request['id']
                or result['bank'] != case['history'] + '-' + request['id']):
            raise ValueError('Host answer does not belong to the declared paper question')
        record['status'] = result['status']
        if 'failure_delivery' in result:
            record['status'] = 'FAILURE_DELIVERY'
        elif result['status'] == 'COMPLETED':
            predictions[question_id] = {'answer': result['final_answer'], 'evidence': []}
    return predictions, receipts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("references", type=Path,
                        help="Fixed scoring-only cases with native controls")
    parser.add_argument("readouts", type=Path,
                        help="JSON condition -> family -> readout path or null")
    parser.add_argument("official_evaluator", type=Path,
                        help="Inspected scripts/evaluator.py from allenai/qasper-led-baseline")
    parser.add_argument("output", type=Path)
    parser.add_argument('--source-kind', choices=('given-readout', 'autonomous-host'),
                        default='given-readout', help='Explicit actual result format; no inference')
    args = parser.parse_args()
    start = time.process_time()
    cases = read_json(args.references)["cases"]
    data = {case["family"]: {"qas": [{
        "question_id": case["native_control"]["native_question_id"],
        "answers": case["native_control"]["annotations"]}]} for case in cases}
    inputs = args.output.parent / (args.output.stem + "-official-inputs")
    inputs.mkdir(parents=True, exist_ok=False)
    gold_path = inputs / "gold.json"
    write_json(gold_path, data)
    conditions = {}
    for index, (name, paths) in enumerate(read_json(args.readouts).items()):
        loader = read_host_answers if args.source_kind == 'autonomous-host' else read_answers
        predictions, receipts = loader(cases, paths)
        predicted_path = inputs / f"condition-{index}.jsonl"
        with predicted_path.open("w") as stream:
            for question_id, prediction in predictions.items():
                stream.write(json.dumps({"question_id": question_id,
                    "predicted_answer": prediction["answer"], "predicted_evidence": []},
                    ensure_ascii=False) + "\n")
        completed = subprocess.run(  # noqa: S603 -- explicit inspected evaluator, argv only
            [sys.executable, str(args.official_evaluator.resolve()),
            "--gold", str(gold_path.resolve()), "--predictions", str(predicted_path.resolve())],
            check=True, capture_output=True, text=True)
        scores = json.loads(completed.stdout)
        write_json(inputs / f"condition-{index}-official-output.json", scores)
        completed_key = ('completed_host_answers' if args.source_kind == 'autonomous-host'
                         else 'completed_readouts')
        conditions[name] = {"planned_questions": len(cases),
            completed_key: len(predictions), "Answer F1": scores["Answer F1"],
            "Answer F1 by type": scores["Answer F1 by type"],
            "Missing predictions": scores["Missing predictions"], "receipts": receipts,
            "official_predictions": str(predicted_path.resolve())}
    write_json(args.output, {
        "status": ("LITERAL_AUTONOMOUS_HOST_NATIVE_ANSWER_AGREEMENT;NOT_AUTHOR_TASK_SUCCESS"
                   if args.source_kind == 'autonomous-host' else
                   "LITERAL_READER_NATIVE_ANSWER_AGREEMENT;NOT_AUTHOR_TASK_SUCCESS"),
        "source_kind": args.source_kind,
        "references": str(args.references.resolve()), "readouts": str(args.readouts.resolve()),
        "official_evaluator": str(args.official_evaluator.resolve()),
        "official_source": "https://github.com/allenai/qasper-led-baseline/blob/main/"
                           "scripts/evaluator.py",
        "conditions": conditions, "model_calls": 0, "ledger_recorded": False,
        "native_type_summary_scope": "Official by-type means use the best-F1 reference type "
            "for present predictions and exclude missing predictions; only the total uses "
            "the complete fixed denominator.",
        "cpu_seconds_pending": time.process_time()-start, "no_sha_validation": True,
        "scope": "Official answer functions applied to literal complete answer strings "
            "and all native annotation alternatives. No answer extraction, unanswerable rewrite "
            "or failure repair. Missing/failed/synthetic deliveries score zero in the denominator. "
            "Evidence F1 is not reported: bounded Source ranges are not native whole-paragraph "
            "evidence predictions. This selected development panel with a different Reader is "
            "not the full native benchmark. Reference conflicts, grounded completeness and "
            "author judgments remain separate from token overlap."})


if __name__ == "__main__":
    main()
