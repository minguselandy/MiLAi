"""Read existing native WMA artifacts; never call a model, Product or evaluator."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
DEFAULT_RAW = LAB.parent / "evidence/v0224/20260913-native-wma-v1"
TOKENS = ("prompt_tokens", "completion_tokens", "total_tokens")


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def rows(path):
    if not path.exists():
        return []
    result = []
    for line in path.read_text().splitlines():
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            # A running writer or failed append remains explicit partial evidence.
            result.append({"status": "PARTIAL_JSON_LINE"})
    return result


def sha(path):
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def average(values):
    values = [x for x in values if type(x) in (int, float)]
    return sum(values) / len(values) if values else None


def provider_cost(directory):
    generations = [read(p) for p in sorted(directory.glob("generation-*.json"))]
    blocked = read(directory / "blocked.json", {})
    aggregate = read(directory / "aggregate.json", {})
    summed = {k: sum(row.get("usage", {}).get(k, 0) for row in generations) for k in TOKENS}
    cumulative = blocked.get("known_usage", aggregate.get("known_usage", aggregate.get("usage")))
    known = summed if cumulative is None else cumulative
    issues = []
    if not all(type(known.get(k)) is int and known[k] >= summed[k] for k in TOKENS):
        issues.append("CUMULATIVE_USAGE_INCONSISTENT_WITH_GENERATION_RECORDS")
    requests = sorted(directory.glob("http-*.request.json"))
    completions = unobserved = 0
    elapsed = 0.0
    for path in requests:
        stem = path.name.removesuffix(".request.json")
        meta = read(directory / (stem + ".response-meta.json"))
        error = read(directory / (stem + ".error.json"))
        if meta is not None:
            endpoint = meta.get("endpoint")
        else:
            # Only missing-response attempts need their (possibly multimodal) payload parsed.
            payload = read(path, {})
            endpoint = "/v1/chat/completions" if "max_tokens" in payload else "/tokenize"
        completions += endpoint == "/v1/chat/completions"
        unobserved += meta is None and error is None
        timing = meta if meta is not None else error or {}
        if type(timing.get("elapsed_seconds")) in (int, float):
            elapsed += timing["elapsed_seconds"]
    unknown = bool(blocked.get("unresolved_usage")) or (
        completions > len(generations) and cumulative is None
    )
    unknown = unknown or unobserved > 0 or bool(issues)
    return {
        "directory": str(directory),
        "http_attempts": len(requests),
        "generation_attempts": max(completions, blocked.get("generation_attempts", 0)),
        "recorded_generations": len(generations),
        "known_usage": known,
        "usage_basis": "blocked cumulative known_usage"
        if "known_usage" in blocked
        else "aggregate cumulative"
        if cumulative is not None
        else "sum successful generation records",
        "unknown_usage": unknown,
        "unobserved_http_attempts": unobserved,
        "http_elapsed_seconds": elapsed,
        "blocked": bool(blocked),
        "failure": blocked.get("message"),
        "issues": issues,
    }


def note_cost(path):
    records = rows(path)
    intents = [r for r in records if r.get("event") == "HTTP_INTENT"]
    observed = [r for r in records if r.get("event") == "HTTP_OBSERVED"]
    counts = {
        "ADD": 0,
        "GET": 0,
        "OPERATION_GET": 0,
        "initialize": 0,
        "initialized": 0,
        "DELETE": 0,
    }
    names = {
        "milai_note_add": "ADD",
        "milai_note_get": "GET",
        "milai_note_operation_get": "OPERATION_GET",
    }
    for row in intents:
        body = row.get("body") or {}
        method = body.get("method")
        if row["method"] == "DELETE":
            counts["DELETE"] += 1
        elif method == "initialize":
            counts["initialize"] += 1
        elif method == "notifications/initialized":
            counts["initialized"] += 1
        elif method == "tools/call":
            key = names.get(body.get("params", {}).get("name"))
            if key:
                counts[key] += 1
    return {
        **counts,
        "http_attempts": len(intents),
        "http_observed": len(observed),
        "unobserved_http_attempts": len(intents) - len(observed),
        "errors": sum("exception_type" in r or r.get("status", 0) >= 400 for r in observed),
        "elapsed_seconds": sum(r.get("elapsed_ns", 0) for r in observed) / 1e9,
    }


def total_provider(costs):
    return {
        "http_attempts": sum(c["http_attempts"] for c in costs),
        "generation_attempts": sum(c["generation_attempts"] for c in costs),
        "known_usage": {k: sum(c["known_usage"].get(k, 0) for c in costs) for k in TOKENS},
        "unknown_usage": any(c["unknown_usage"] for c in costs),
        "unknown_provider_directories": [c["directory"] for c in costs if c["unknown_usage"]],
        "http_elapsed_seconds": sum(c["http_elapsed_seconds"] for c in costs),
    }


def stage_matches(row, root, arm):
    label = row["stage"].removesuffix("-v4").removesuffix("-v3").removesuffix("-v2")
    return (row.get("root") == root and row.get("arm") == arm) or label.endswith(
        "-" + root + "-" + arm
    )


def build(raw, manifest):
    revision = manifest.get("execution_revision", "v1")
    if revision not in ("v1", "v2", "v3", "v4"):
        raise ValueError("UNSUPPORTED_REPORT_EXECUTION_REVISION")
    terminal_path = raw / (
        f"batch-terminal-{revision}.json" if revision != "v1" else "batch-terminal.json"
    )
    terminal = read(terminal_path)
    decision = read(
        raw / (f"review-decision-{revision}.json" if revision != "v1" else "review-decision.json")
    )
    summary, pairs, all_costs = [], [], []
    primary_costs, review_costs = [], []
    stage_rows = [read(p) for p in sorted((raw / "stages").glob("*/terminal.json"))]
    for spec in manifest["roots"]:
        root = spec["root"]
        expected = spec["questions"]
        public = read(Path(spec["reader"]), {})
        expected_ids = [q["id"] for cp in public.get("checkpoints", []) for q in cp["questions"]]
        answer_maps, score_maps = {}, {}
        for arm in ("B_native", "M_note", "R_review"):
            directory = raw / "runs" / root / arm
            answers, scores = rows(directory / "answers.jsonl"), rows(directory / "scores.jsonl")
            answer_maps[arm] = {r["id"]: r for r in answers if "id" in r}
            score_maps[arm] = {
                r["id"]: r for r in scores if "id" in r and r.get("status") == "SCORED"
            }
            scored = list(score_maps[arm].values())
            labels = [r["answer_judge"]["evaluation_result"] for r in scored]
            evidences = [r["evidence_judge"] for r in scored if r.get("evidence_judge") is not None]
            denominator = sum(e["total"] for e in evidences)
            grade_terminal = {}
            for version in range(int(revision[1:]), 0, -1):
                suffix = f"-v{version}" if version > 1 else ""
                grade_path = directory / f"judge-terminal{suffix}.json"
                if grade_path.exists():
                    grade_terminal = read(grade_path)
                    break
            answer_terminal = read(directory / "terminal.json", {})
            stages = [r for r in stage_rows if stage_matches(r, root, arm)]
            if arm == "R_review" and not directory.exists():
                status = (
                    "NOT_TRIGGERED_ZERO_USED"
                    if decision is not None and root not in decision["roots"]
                    else "TRIGGER_UNDECIDED"
                )
                expected_arm = 0 if status == "NOT_TRIGGERED_ZERO_USED" else expected
            else:
                complete_ids = (
                    len(answers) == expected
                    and set(answer_maps[arm]) == set(expected_ids)
                    and len(scored) == expected
                    and {r["id"] for r in scored} == set(expected_ids)
                )
                status = (
                    "COMPLETE"
                    if complete_ids and grade_terminal.get("status") == "JUDGE_COMPLETE"
                    else (
                        grade_terminal.get("status")
                        or answer_terminal.get("status")
                        or "NOT_STARTED"
                    )
                )
                expected_arm = expected
            costs = [provider_cost(directory / "provider")] + [
                provider_cost(p) for p in sorted(directory.glob("judge-provider*")) if p.is_dir()
            ]
            all_costs.extend(costs)
            (review_costs if arm == "R_review" else primary_costs).extend(costs)
            cost = total_provider(costs)
            row = {
                "root": root,
                "arm": arm,
                "expected": expected_arm,
                "native_questions": expected,
                "answers": len(answer_maps[arm]),
                "score_records": len(scores),
                "scored": len(scored),
                "Correct": labels.count("Correct"),
                "Hallucination": labels.count("Hallucination"),
                "Omission": labels.count("Omission"),
                "JudgeInvalid": len(
                    {
                        r["id"]
                        for r in scores
                        if r.get("status") == "JUDGE_INVALID" and r.get("id") not in score_maps[arm]
                    }
                ),
                "historical_judge_invalid_records": sum(
                    r.get("status") == "JUDGE_INVALID" for r in scores
                ),
                "answer_f1": average([r.get("answer_f1") for r in scored]),
                "answer_bleu1": average([r.get("answer_bleu1") for r in scored]),
                "text_evidence_covered": sum(e["covered_count"] for e in evidences),
                "text_evidence_total": denominator,
                "text_evidence_coverage": sum(e["covered_count"] for e in evidences) / denominator
                if denominator
                else None,
                "evidence_na_questions": len(scored) - len(evidences),
                "status": status,
                "stage_elapsed_seconds": sum(r["elapsed_seconds"] for r in stages),
                "stage_terminals": stages,
                **cost,
                "provider_details": costs,
                "note": note_cost(directory / "note-http/mcp-http.jsonl"),
            }
            if row["status"] != "COMPLETE" and any(c["blocked"] for c in costs):
                row["status"] = "PROVIDER_BLOCKED"
            row.update(cost["known_usage"])
            row["note_ADD"] = row["note"]["ADD"]
            row["note_GET"] = row["note"]["GET"]
            row["note_http_attempts"] = row["note"]["http_attempts"]
            summary.append(row)
        for qid in expected_ids:
            b, m = (answer_maps[a].get(qid) for a in ("B_native", "M_note"))
            item = {
                "root": root,
                "qid": qid,
                "both_answers_present": b is not None and m is not None,
            }
            if b is not None and m is not None:
                item["answer_utf8_equal"] = b["answer"].encode() == m["answer"].encode()
                fields = ("question", "retrieval", "images")
                item["retrieval_input_json_equal"] = json.dumps(
                    {k: b[k] for k in fields}, ensure_ascii=False, sort_keys=True
                ) == json.dumps({k: m[k] for k in fields}, ensure_ascii=False, sort_keys=True)
                # Frozen provider emits tokenize then completion for every successful answer.
                hashes = []
                for arm in ("B_native", "M_note"):
                    ordered = list(answer_maps[arm])
                    ordinal = ordered.index(qid) + 1
                    hashes.append(
                        sha(
                            raw
                            / "runs"
                            / root
                            / arm
                            / "provider"
                            / f"http-{2 * ordinal:04d}.request.json"
                        )
                    )
                item["completion_request_sha256"] = dict(
                    zip(("B_native", "M_note"), hashes, strict=True)
                )
                item["request_bytes_sha_equal"] = None if None in hashes else hashes[0] == hashes[1]
            reviewed = answer_maps["R_review"].get(qid)
            review_score = score_maps["R_review"].get(qid, {})
            item["review_label"] = review_score.get("answer_judge", {}).get("evaluation_result")
            item["review_answer_equal_to_baseline"] = (
                reviewed["answer"].encode() == b["answer"].encode()
                if reviewed is not None and b is not None
                else None
            )
            pairs.append(item)
    calibration = provider_cost(raw / "judge-calibration/provider")
    all_costs.append(calibration)
    note_paths = sorted(raw.glob("runs/*/*/note-http/mcp-http.jsonl"))
    isolation_paths = sorted((raw / "service/isolation").glob("**/mcp-http.jsonl"))
    identity = read(raw / "identity-http.json", [])
    full = (
        terminal is not None
        and terminal.get("status") == "NATIVE_BATCH_COMPLETE"
        and all(r["status"] in ("COMPLETE", "NOT_TRIGGERED_ZERO_USED") for r in summary)
    )
    comparable = [p for p in pairs if p["both_answers_present"]]
    same = bool(comparable) and all(p.get("answer_utf8_equal") for p in comparable)
    full = full and not any(c["unknown_usage"] for c in all_costs)
    identical_requests = (
        len(comparable) == len(pairs)
        and bool(pairs)
        and all(p.get("request_bytes_sha_equal") is True for p in comparable)
    )
    different_requests = any(p.get("request_bytes_sha_equal") is False for p in comparable)
    by_question = {(p["root"], p["qid"]): p for p in pairs}
    review_resolves = bool(
        decision and decision.get("triggered") and decision.get("signals")
    ) and all(
        (
            by_question.get((signal["root"], signal["id"]), {}).get("review_label") == "Correct"
            or by_question.get((signal["root"], signal["id"]), {}).get(
                "review_answer_equal_to_baseline"
            )
            is True
        )
        for signal in decision["signals"]
    )
    recommendation = (
        "PARTIAL_FAILURE_OR_RUNNING"
        if not full
        else "KEEP_SIMPLE"
        if same or identical_requests or review_resolves
        else "LIMITED_DEVELOPMENT_SIGNAL"
        if different_requests
        else "INPUT_COMPARISON_INCOMPLETE"
    )
    interpretation = (
        "仍在运行或有失败, 不作 Memory 效果结论。"
        if not full
        else "完整配对实际请求字节摘要全部相同; 即使答案不同也只是同输入生成差异, 不能归因 Note。"
        if identical_requests
        else "R_review 已对所有冻结触发题修复为 Correct 或恢复 B 答案; KEEP_SIMPLE, 不作机制归因。"
        if review_resolves
        else "完整配对答案相同, 未显示 Note 质量增益。"
        if same
        else "存在实际输入差异, 仅保留有限开发信号, 不作机制或因果结论。"
        if different_requests
        else "请求输入比较不完整, 暂不作效果解释。"
    )
    failures = [r for r in stage_rows if r.get("exit_code") != 0 or r.get("timed_out")]
    preserved = [
        str(p.relative_to(raw))
        for p in raw.rglob("*")
        if p.is_file()
        and not any(
            x in p.parts for x in ("venv", "secrets", "private-evaluator", "runs", "inputs")
        )
        and any(
            w in p.name.lower() for w in ("error", "failure", "stderr", "terminal", "lifecycle")
        )
    ]
    return {
        "status": "FINAL" if terminal is not None else "RUNNING_PREVIEW",
        "batch_terminal": terminal,
        "batch_terminal_path": str(terminal_path),
        "execution_revision": revision,
        "historical_batch_terminal_v1": read(raw / "batch-terminal.json")
        if revision != "v1"
        else None,
        "historical_batch_terminals": {
            p.name: read(p) for p in raw.glob("batch-terminal*.json") if p != terminal_path
        },
        "stage_terminals": stage_rows,
        "recommendation": recommendation,
        "interpretation": interpretation,
        "identical_completion_requests": identical_requests,
        "review_resolves_all_trigger_signals": review_resolves,
        "independent_root_denominator": len(manifest["roots"]),
        "primary_question_opportunities": sum(r["questions"] for r in manifest["roots"]) * 2,
        "summary": summary,
        "qid_pair_comparisons": pairs,
        "review_decision": decision,
        "costs": {
            "primary": total_provider(primary_costs),
            "conditional_review": total_provider(review_costs),
            "judge_calibration": calibration,
            "judge_calibration_expected_generations": 8,
            "frozen_allocation_caps": manifest.get("allocations", {}),
            "conditional_review_questions_activated": (
                sum(s["questions"] for s in manifest["roots"] if s["root"] in decision["roots"])
                if decision is not None
                else None
            ),
            "all_provider": total_provider(all_costs),
            "identity_http_attempts": len(identity),
            "identity_http_expected": 2,
            "identity_http_elapsed_seconds": sum(x.get("seconds", 0) for x in identity),
            "note_primary": {str(p.relative_to(raw)): note_cost(p) for p in note_paths},
            "note_isolation": {str(p.relative_to(raw)): note_cost(p) for p in isolation_paths},
            "note_isolation_terminal": read(raw / "service/isolation/terminal.json"),
            "service_lifecycle": {
                str(p.relative_to(raw)): read(p)
                for p in (raw / "service").glob("**/*terminal.json")
            },
            "product_internal_http": "UNMEASURED_NOT_ZERO",
            "installation_and_start_failures_retained": preserved,
        },
        "failure_layers": failures,
        "limitations": [
            "Four development-exposed native roots, not 440 independent subjects; no confirmation claim.",  # noqa: E501
            "Same local model vLLM Judge; native QA F1/BLEU1; evidence only text, absent evidence is N/A.",  # noqa: E501
            "M_note is HARNESS_INGESTED ordinary Note readback; no autonomous saving or cold recovery.",  # noqa: E501
            "No mechanism, memory causality or action conclusions. Conditional R is diagnostic only.",  # noqa: E501
            "Reused valid Judge records form composed-version evidence, not one batch or transport.",  # noqa: E501
            "Provider and external MCP attempts counted separately; Product internal HTTP is unmeasured.",  # noqa: E501
            "Stage elapsed is complete observed child lifecycle; no CPU efficiency pass/fail criterion.",  # noqa: E501
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--manifest", type=Path, default=LAB / "configs/v0224-native-wma.json")
    parser.add_argument("--output-suffix", default="")
    args = parser.parse_args()
    suffix = args.output_suffix
    if suffix and (not suffix.replace("-", "").replace("_", "").isalnum()):
        raise ValueError("SAFE_OUTPUT_SUFFIX_REQUIRED")
    result = build(args.raw_root, read(args.manifest))
    if not suffix and result["batch_terminal"] is None:
        raise ValueError("FINAL_REPORT_REQUIRES_ACTUAL_BATCH_TERMINAL")
    result["manifest_sha256"] = sha(args.manifest)
    result["report_source_sha256"] = sha(Path(__file__))
    tag = "-" + suffix if suffix else ""
    json_path = args.raw_root / f"final-results{tag}.json"
    csv_path = args.raw_root / f"final-results{tag}.csv"
    md_path = LAB / "studies/active" / f"MILA_V0224_NATIVE_WMA_RESULTS_20260913{tag}.md"
    for path in (json_path, csv_path, md_path):
        if path.exists():
            raise FileExistsError(path)
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    fields = [
        "root",
        "arm",
        "expected",
        "answers",
        "scored",
        "Correct",
        "Hallucination",
        "Omission",
        "JudgeInvalid",
        "historical_judge_invalid_records",
        "answer_f1",
        "answer_bleu1",
        "text_evidence_coverage",
        "status",
        "http_attempts",
        "generation_attempts",
        "stage_elapsed_seconds",
        "unknown_usage",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "note_ADD",
        "note_GET",
        "note_http_attempts",
    ]
    with csv_path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["summary"])
    lines = [
        f"# 原生 WMA 开发结果 {suffix}",
        "",
        f"状态:{result['status']};结论:{result['recommendation']}。独立根分母 {result['independent_root_denominator']}。",  # noqa: E501
        "",
        "| 根 | arm | expected/answers/scored | Correct/Hallucination/Omission/Invalid | F1 | BLEU1 | 文本证据覆盖 | 状态 |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|",
    ]

    def fmt(value):
        return "N/A" if value is None else f"{value:.4f}"

    for r in result["summary"]:
        lines.append(
            f"| {r['root']} | {r['arm']} | {r['expected']}/{r['answers']}/{r['scored']} | "
            f"{r['Correct']}/{r['Hallucination']}/{r['Omission']}/{r['JudgeInvalid']} | "
            f"{fmt(r['answer_f1'])} | {fmt(r['answer_bleu1'])} | {fmt(r['text_evidence_coverage'])} | {r['status']} |"  # noqa: E501
        )
    lines += [
        "",
        result["interpretation"],
        "",
        "## 成本与失败",
        "",
        "| 根 | arm | HTTP/生成 | prompt/completion/total tokens | 秒 | "
        "Note ADD/GET/HTTP | unknown |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["summary"]:
        usage = row["known_usage"]
        note = row["note"]
        lines.append(
            f"| {row['root']} | {row['arm']} | {row['http_attempts']}/{row['generation_attempts']} | "  # noqa: E501
            f"{usage['prompt_tokens']}/{usage['completion_tokens']}/{usage['total_tokens']} | "
            f"{row['stage_elapsed_seconds']:.2f} | {note['ADD']}/{note['GET']}/{note['http_attempts']} | "  # noqa: E501
            f"{row['unknown_usage']} |"
        )
    costs = result["costs"]
    total, calibration = costs["all_provider"], costs["judge_calibration"]
    isolation_http = sum(row["http_attempts"] for row in costs["note_isolation"].values())
    note_http = sum(row["http_attempts"] for row in costs["note_primary"].values())
    lines += [
        "",
        f"Provider 总计 {total['http_attempts']} HTTP attempts / {total['generation_attempts']} generations; "  # noqa: E501
        f"已知 tokens {total['known_usage']}; unknown={total['unknown_usage']}。",
        f"其中 Judge 校准 {calibration['generation_attempts']}/8 calls, "
        f"{calibration['http_attempts']} HTTP; identity {costs['identity_http_attempts']}/2 HTTP。",
        f"Note 主实验 {note_http} HTTP; 服务主体隔离 {isolation_http} HTTP。"
        "包含握手与 DELETE; Product 内部 HTTP 未计量, 不是零。",
    ]
    failed = result["failure_layers"]
    if failed:
        first = min(
            failed,
            key=lambda row: (
                (args.raw_root / "stages" / row["stage"] / "terminal.json").stat().st_mtime_ns
            ),
        )
        stage_path = args.raw_root / "stages" / first["stage"]
        details = [
            c["failure"]
            for row in result["summary"]
            if stage_matches(first, row["root"], row["arm"])
            for c in row["provider_details"]
            if c.get("failure")
        ]
        lines += [
            "",
            f"最早失败层: {first['stage']}, exit={first['exit_code']}, "
            f"timeout={first.get('timed_out')}; {details or '详见原始 stderr'}。"
            f"[终态]({stage_path / 'terminal.json'}) / [原始错误]({stage_path / 'stderr'})。",
        ]
    elif result["batch_terminal"]:
        lines += [
            "",
            f"Batch 终态: {result['batch_terminal']['status']}; "
            f"[实际记录]({args.raw_root / 'batch-terminal.json'})。",
        ]
    else:
        lines += ["", "Batch 仍在运行, 尚无最终终态。"]
    lines += [
        "",
        "安装、依赖和服务启动的历史失败与详细费用完整保留在 JSON 的 costs 中。",
        "",
        "## 解释边界",
        "",
    ]
    lines += ["- " + text for text in result["limitations"]]
    lines += [
        "",
        f"逐 qid 的输入/答案字节一致性与完整阶段成本见 [JSON]({json_path});[CSV]({csv_path})。",
    ]
    md_path.write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "json": str(json_path),
                "csv": str(csv_path),
                "markdown": str(md_path),
            }
        )
    )


if __name__ == "__main__":
    main()
