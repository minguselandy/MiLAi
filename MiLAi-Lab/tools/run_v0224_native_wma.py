"""Bounded WMA QA run using the official MMFU_Single and QA prompts.

The reader consumes only exported public turns/questions. Gold is opened only
by the separate judge command. No historical Gate A replay is in this path.
"""

import argparse
import base64
import dataclasses
import hashlib
import importlib.metadata
import json
import mimetypes
import os
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
BENCH = LAB.parent / "benchmarks/v0218-pinned"
CODE = BENCH / "wma-code/WorldMemArena-15ea25b723d9c4fb35e8062037aec6a5601e4442"
DATA = BENCH / "WorldMemArena-e2148757921fc7e2d66d8ed899823b763227c341"
MANIFEST = LAB / "configs/v0224-native-wma.json"
RAW = LAB.parent / "evidence/v0224/20260913-native-wma-v1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as f:
        json.dump(value, f, indent=2, ensure_ascii=False)


def append(path, value):
    with Path(path).open("a") as f:
        f.write(json.dumps(value, ensure_ascii=False) + "\n")


def upstream():
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if str(CODE) not in sys.path:
        sys.path.insert(0, str(CODE))
    # Load real tokenizer before upstream's optional torch stubs. Otherwise its
    # import order mistakes an installed transformers package for a missing one.
    from transformers import AutoTokenizer

    tokenizer = CODE / "eval_framework/baselines/MMFU_Single/tokenizers/gpt2"
    AutoTokenizer.from_pretrained(str(tokenizer), local_files_only=True)
    from eval_framework import config

    cfg = config.load_baseline_config()
    cfg["retrieval"]["truncation_tokenizer"] = str(tokenizer)
    cfg["retrieval"]["answer_model_ctx"] = 65536
    cfg["retrieval"]["answer_model_buffer"] = 8000
    cfg["baselines"]["MMFU_Single"]["tokenizer_path"] = str(tokenizer)
    from eval_framework.memory_adapters.registry import create_memgallery_adapter

    return lambda: create_memgallery_adapter("MMFU_Single")


def prepare():
    upstream()
    from eval_framework.datasets.worldmemarena import _load_one_sample

    manifest = json.loads(MANIFEST.read_text())
    if manifest["status"] != "N0_IN_PROGRESS_NO_MODEL_OUTPUT":
        raise ValueError("PREPARATION_STATE")
    pins = {}
    code_files = json.loads((BENCH / "wma-code-files.json").read_text())["files"]
    for row in code_files:
        p = BENCH / "wma-code" / row["path"]
        if sha(p) != row["sha256"]:
            raise ValueError("PINNED_UPSTREAM_CODE_DRIFT")
        pins[str(p)] = row["sha256"]
    data_files = {
        r["path"]: r["sha256"]
        for r in json.loads((BENCH / "wma-data-files.json").read_text())["files"]
    }
    roots = []
    for relative in manifest["candidate_order"][:4]:
        p = DATA / relative
        if sha(p) != data_files[relative]:
            raise ValueError("PINNED_UPSTREAM_DATA_DRIFT")
        pins[str(p)] = data_files[relative]
        sample = _load_one_sample(p, DATA)
        sessions = [dataclasses.asdict(s) for s in sample.sessions]
        cps, gold = [], []
        for cp in sample.normalized_checkpoints:
            qs = []
            for index, q in enumerate(cp.questions):
                qid = f"{cp.checkpoint_id}:{index:02d}"
                qs.append({"id": qid, "question": q.question})
                gold.append({"id": qid, **dataclasses.asdict(q)})
            cps.append(
                {
                    "id": cp.checkpoint_id,
                    "covered_sessions": list(cp.covered_sessions),
                    "questions": qs,
                }
            )
        if len(gold) > 100 or not gold:
            raise ValueError("ROOT_QUERY_ENVELOPE")
        for session in sessions:
            for turn in session["turns"]:
                for att in turn["attachments"]:
                    if att["file_path"]:
                        image = Path(att["file_path"]).resolve()
                        key = str(image.relative_to(DATA))
                        if sha(image) != data_files[key]:
                            raise ValueError("PINNED_IMAGE_DRIFT")
                        pins[str(image)] = data_files[key]
        root = sample.sample_id
        reader = RAW / "inputs" / root / "reader.json"
        evaluator = RAW / "private-evaluator" / (root + ".json")
        write(reader, {"root": root, "sessions": sessions, "checkpoints": cps})
        write(evaluator, {"root": root, "questions": gold})
        evaluator.chmod(0o600)
        roots.append(
            {
                "root": root,
                "source": str(p),
                "reader": str(reader),
                "reader_sha256": sha(reader),
                "evaluator": str(evaluator),
                "evaluator_sha256": sha(evaluator),
                "sessions": len(sessions),
                "questions": len(gold),
                "checkpoints": len(cps),
                "exposure": "DEVELOPMENT_EXPOSED_NOT_CONFIRMATION",
            }
        )
    manifest["roots"] = roots
    manifest["upstream_files"] = pins
    manifest["runtime_packages"] = {
        d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
    }
    manifest["status"] = "N0_PREPARED_PENDING_IMPLEMENTATION_FREEZE"
    MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    print(json.dumps({"status": manifest["status"], "roots": roots, "pins": len(pins)}))


def check_manifest(expected):
    if sha(MANIFEST) != expected:
        raise ValueError("FROZEN_MANIFEST_CHANGED")
    m = json.loads(MANIFEST.read_text())
    if m["status"] != "NATIVE_WMA_FROZEN_FOR_EXECUTION":
        raise ValueError("MANIFEST_NOT_FROZEN_FOR_EXECUTION")
    for path, expected_sha in m["local_sources"].items():
        if sha(path) != expected_sha:
            raise ValueError("LOCAL_SOURCE_DRIFT")
    return m


def make_messages(retrieval, question):
    from eval_framework.cli import _ANSWER_SYSTEM_PROMPT, _ANSWER_USER_TEMPLATE

    context = "\n".join(f"[{x.rank}] {x.text}" for x in retrieval.items[:10])
    user = _ANSWER_USER_TEMPLATE.format(
        context=context or "No retrieved memories.", question=question
    )
    image_paths = []
    for item in retrieval.items[:10]:
        if item.image_path and item.image_path not in image_paths:
            image_paths.append(item.image_path)
        if len(image_paths) >= 5:
            break
    content = [{"type": "text", "text": user}]
    images = []
    total_bytes = 0
    for name in image_paths:
        path = Path(name).resolve()
        path.relative_to(DATA)
        raw = path.read_bytes()
        if total_bytes + len(raw) > 45 * 1024 * 1024:
            continue  # Exact official answer-stage payload cap.
        total_bytes += len(raw)
        mime = mimetypes.guess_type(str(path))[0] or "image/png"
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64," + base64.b64encode(raw).decode()},
            }
        )
        images.append({"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
    return [
        {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
        {"role": "user", "content": content if images else user},
    ], images


def answer(m, root, arm):
    from eval_framework.cli import _parse_answer_json
    from eval_framework.datasets.schemas import normalize_turn

    from v0224_native_wma_provider import NativeProvider

    if arm == "R_review":
        return review(m, root)
    factory = upstream()
    spec = next(r for r in m["roots"] if r["root"] == root)
    if sha(spec["reader"]) != spec["reader_sha256"]:
        raise ValueError("READER_INPUT_DRIFT")
    public = json.loads(Path(spec["reader"]).read_text())
    directory = RAW / "runs" / root / arm
    directory.mkdir(parents=True, exist_ok=False)
    provider = NativeProvider(
        directory / "provider",
        max_generations=spec["questions"],
        max_http=2 * spec["questions"],
        request_seconds=m["request_seconds"],
    )
    archive = None
    mcp = None
    if arm == "M_note":
        from v0224_native_wma_mcp import NoteMCP
        from v0224_native_wma_note import NoteArchive

        index = [s["root"] for s in m["roots"]].index(root) + 1
        mcp = NoteMCP(
            RAW / "service" / "secrets" / f"root-{index:02d}.json",
            directory / "note-http",
            max_http=spec["note_http_cap"],
        )
        archive = NoteArchive(root, mcp.call, lambda row: append(directory / "notes.jsonl", row))
    adapter = factory()
    adapter.reset()
    order = {s["session_id"]: i for i, s in enumerate(public["sessions"])}
    completed = set()
    rows = []
    try:
        for session in public["sessions"]:
            sid = session["session_id"]
            if archive:
                archive.append_session(sid, session["turns"])
            else:
                for turn in session["turns"]:
                    adapter.ingest_turn(normalize_turn(turn))
                adapter.end_session(sid)
            completed.add(sid)
            for cp in public["checkpoints"]:
                covered = cp["covered_sessions"]
                if not covered or not set(covered) <= completed:
                    continue
                if max(covered, key=order.__getitem__) != sid:
                    continue
                if archive:
                    adapter = factory()
                    adapter.reset()
                    last_sid = None
                    for turn in archive.records_for_checkpoint(cp["id"]):
                        if last_sid and last_sid != turn["session_id"]:
                            adapter.end_session(last_sid)
                        adapter.ingest_turn(normalize_turn(turn))
                        last_sid = turn["session_id"]
                    if last_sid:
                        adapter.end_session(last_sid)
                for q in cp["questions"]:
                    retrieval = adapter.retrieve(q["question"], 10)
                    messages, images = make_messages(retrieval, q["question"])
                    result = provider.generate("answer", messages, max_tokens=1024)
                    value = _parse_answer_json(result["text"])
                    row = {
                        "root": root,
                        "arm": arm,
                        "id": q["id"],
                        "question": q["question"],
                        "checkpoint": cp["id"],
                        "completed_sessions": sorted(completed, key=order.__getitem__),
                        "retrieval": dataclasses.asdict(retrieval),
                        "images": images,
                        "answer": value,
                        "generation": result,
                        "protocol_valid": result["finish_reason"] == "stop",
                    }
                    append(directory / "answers.jsonl", row)
                    rows.append(row)
                    print(
                        json.dumps(
                            {
                                "root": root,
                                "arm": arm,
                                "completed": len(rows),
                                "total": spec["questions"],
                            }
                        ),
                        flush=True,
                    )
                    if not row["protocol_valid"]:
                        raise ValueError("ANSWER_FINISH_INVALID_NO_RETRY")
        if len(rows) != spec["questions"]:
            raise ValueError("INCOMPLETE_NATIVE_QUESTIONS")
        if mcp:
            mcp.close()
            mcp = None
        provider.close()
        write(
            directory / "terminal.json",
            {
                "status": "ANSWER_COMPLETE",
                "questions": len(rows),
                "sessions": len(completed),
                "pid": os.getpid(),
            },
        )
    except Exception as exc:
        write(
            directory / "terminal.json",
            {
                "status": "ANSWER_FAILED",
                "questions": len(rows),
                "exception": type(exc).__name__,
                "reason": str(exc),
            },
        )
        raise
    finally:
        provider.close()
        if mcp:
            mcp.close()


def review(m, root):
    from eval_framework.cli import _parse_answer_json
    from eval_framework.datasets.schemas import RetrievalItem, RetrievalRecord

    from v0224_native_wma_provider import NativeProvider

    revision = m.get("execution_revision", "v1")
    suffix = "" if revision == "v1" else "-" + revision
    eligible = json.loads((RAW / ("review-decision" + suffix + ".json")).read_text())["roots"]
    if root not in eligible:
        raise ValueError("REVIEW_TRIGGER_REQUIRED")
    source = RAW / "runs" / root / "M_note"
    if json.loads((source / "terminal.json").read_text())["status"] != "ANSWER_COMPLETE":
        raise ValueError("REVIEW_REQUIRES_COMPLETE_M_NOTE")
    spec = next(r for r in m["roots"] if r["root"] == root)
    directory = RAW / "runs" / root / "R_review"
    directory.mkdir(parents=True, exist_ok=False)
    provider = NativeProvider(
        directory / "provider",
        max_generations=spec["questions"],
        max_http=2 * spec["questions"],
        request_seconds=m["request_seconds"],
    )
    rows = []
    try:
        for line in (source / "answers.jsonl").read_text().splitlines():
            prior = json.loads(line)
            retrieval = dict(prior["retrieval"])
            retrieval["items"] = [RetrievalItem(**r) for r in retrieval["items"]]
            messages, images = make_messages(RetrievalRecord(**retrieval), prior["question"])
            messages.extend(
                [
                    {"role": "assistant", "content": prior["generation"]["text"]},
                    {"role": "user", "content": m["review_prompt"]},
                ]
            )
            result = provider.generate("ordinary_review", messages, max_tokens=1024)
            row = {
                **prior,
                "arm": "R_review",
                "reviewed_answer": prior["answer"],
                "answer": _parse_answer_json(result["text"]),
                "generation": result,
                "protocol_valid": result["finish_reason"] == "stop",
                "images": images,
                "source_answer_sha256": sha(source / "answers.jsonl"),
            }
            append(directory / "answers.jsonl", row)
            rows.append(row)
            if not row["protocol_valid"]:
                raise ValueError("REVIEW_FINISH_INVALID_NO_RETRY")
        if len(rows) != spec["questions"]:
            raise ValueError("INCOMPLETE_REVIEW")
        write(
            directory / "terminal.json",
            {
                "status": "ANSWER_COMPLETE",
                "questions": len(rows),
                "sessions": spec["sessions"],
                "pid": os.getpid(),
            },
        )
    finally:
        provider.close()


def judge_output_regex(expected_total=None):
    # Each unit is one legal unescaped JSON character or one complete JSON escape.
    # No optional whitespace exists between fields; the rationale itself is bounded.
    unit = r'(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))'
    prefix = r'\{"reasoning":"' + unit + r"{0,1024}"
    if expected_total is None:
        return prefix + r'","evaluation_result":"(?:Correct|Hallucination|Omission)"\}'
    if type(expected_total) is not int or expected_total < 0:
        raise ValueError("invalid expected evidence total")
    count = "(?:" + "|".join(str(i) for i in range(expected_total + 1)) + ")"
    return prefix + r'","covered_count":' + count + r',"total":' + str(expected_total) + r"\}"


def judge_one(provider, q, answer_text, retrieval_text, max_tokens=1024, structured=False):
    from eval_framework.judges.prompts import EVIDENCE_BATCH_PROMPT, QA_EVALUATION_PROMPT

    from v0224_native_wma_provider import parse_evidence, parse_judge

    points = q["gold_evidence_contents"]
    prompt = QA_EVALUATION_PROMPT.format(
        question=q["question"],
        reference_answer=q["gold_answer"],
        key_memory_points="\n".join(points) if points else "No evidence available.",
        response=answer_text,
    )
    options = {}
    if structured:
        options["structured_outputs"] = {"regex": judge_output_regex()}
    result = provider.generate(
        "judge_answer", [{"role": "user", "content": prompt}], max_tokens=max_tokens, **options
    )
    label = parse_judge(result["text"], result["finish_reason"])
    evidence = None
    evidence_call = None
    if points and retrieval_text.strip():
        prompt = EVIDENCE_BATCH_PROMPT.format(
            retrieved_memories=retrieval_text,
            gold_evidence_points="\n".join(f"[{i + 1}] {p}" for i, p in enumerate(points)),
        )
        options = {}
        if structured:
            options["structured_outputs"] = {"regex": judge_output_regex(len(points))}
        evidence_call = provider.generate(
            "judge_evidence",
            [{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            **options,
        )
        evidence = parse_evidence(
            evidence_call["text"], evidence_call["finish_reason"], len(points)
        )
    return {
        "answer_judge": label,
        "answer_call": result,
        "evidence_judge": evidence,
        "evidence_call": evidence_call,
    }


def judge(m, root, arm):
    from eval_framework.evaluators.qa import _answer_bleu1, _answer_f1

    from v0224_native_wma_provider import NativeProvider

    spec = next(r for r in m["roots"] if r["root"] == root)
    if sha(spec["evaluator"]) != spec["evaluator_sha256"]:
        raise ValueError("EVALUATOR_INPUT_DRIFT")
    gold = {q["id"]: q for q in json.loads(Path(spec["evaluator"]).read_text())["questions"]}
    directory = RAW / "runs" / root / arm
    terminal = json.loads((directory / "terminal.json").read_text())
    if terminal["status"] != "ANSWER_COMPLETE":
        raise ValueError("COMPLETE_ANSWER_UNIT_REQUIRED")
    revision = m.get("execution_revision", "v1")
    suffix = "" if revision == "v1" else "-" + revision
    existing = []
    score_file = directory / "scores.jsonl"
    if score_file.exists():
        reuse = m["score_reuse"][root + "/" + arm]
        if sha(score_file) != reuse["sha256"]:
            raise ValueError("REUSED_SCORE_PREFIX_DRIFT")
        existing = [json.loads(x) for x in score_file.read_text().splitlines()]
    valid_ids = {r["id"] for r in existing if r["status"] == "SCORED"}
    pending = spec["questions"] - len(valid_ids)
    if pending <= 0:
        raise ValueError("NO_UNSCORED_QUESTIONS_TO_REVISE")
    provider = NativeProvider(
        directory / ("judge-provider" + suffix),
        max_generations=2 * pending,
        max_http=4 * pending,
        request_seconds=m["request_seconds"],
    )
    rows = []
    consecutive_errors = 0
    for line in (directory / "answers.jsonl").read_text().splitlines():
        row = json.loads(line)
        if row["id"] in valid_ids:
            continue
        q = gold[row["id"]]
        if q["question"] != row["question"]:
            raise ValueError("QUESTION_ALIGNMENT")
        text = "\n".join(f"[{x['rank']}] {x['text']}" for x in row["retrieval"]["items"])
        try:
            graded = judge_one(
                provider,
                q,
                row["answer"],
                text,
                max_tokens=m.get("judge_max_tokens", 1024),
                structured=m.get("judge_structured_outputs", False),
            )
            value = {
                "id": row["id"],
                "status": "SCORED",
                **graded,
                "answer_f1": _answer_f1(row["answer"], q["gold_answer"]),
                "answer_bleu1": _answer_bleu1(row["answer"], q["gold_answer"]),
            }
            consecutive_errors = 0
        except ValueError as exc:
            if provider.blocked:
                provider.close()
                raise
            value = {"id": row["id"], "status": "JUDGE_INVALID", "reason": str(exc)}
            consecutive_errors += 1
        value["execution_revision"] = revision
        append(directory / "scores.jsonl", value)
        rows.append(value)
        print(
            json.dumps({"root": root, "arm": arm, "graded": len(rows), "status": value["status"]}),
            flush=True,
        )
        if consecutive_errors >= 2:
            break
    provider.close()
    valid = len(valid_ids) + sum(r["status"] == "SCORED" for r in rows)
    write(
        directory / ("judge-terminal" + suffix + ".json"),
        {
            "status": "JUDGE_COMPLETE" if valid == spec["questions"] else "JUDGE_PARTIAL",
            "attempted_questions": len(rows),
            "reused_valid_questions": len(valid_ids),
            "historical_invalid_attempts": sum(r["status"] != "SCORED" for r in existing),
            "valid_questions": valid,
            "pid": os.getpid(),
        },
    )


def calibrate(m):
    from v0224_native_wma_provider import NativeProvider

    directory = RAW / "judge-calibration"
    directory.mkdir(exist_ok=False)
    provider = NativeProvider(
        directory / "provider", max_generations=8, max_http=16, request_seconds=m["request_seconds"]
    )
    cases = [
        ("会议在哪天?", "会议在周二。", "周二开会。", "Correct"),
        ("会议在哪天?", "会议在周二。", "周三开会。", "Hallucination"),
        ("林是否批准申请?", "林没有批准申请。", "林批准了申请。", "Hallucination"),
        ("会议何时在哪里?", "周二在 A 室开会。", "周二开会。", "Omission"),
    ]
    result = []
    for question, gold, answer_text, expected in cases:
        value = judge_one(
            provider,
            {"question": question, "gold_answer": gold, "gold_evidence_contents": [gold]},
            answer_text,
            gold,
        )
        passed = (
            value["answer_judge"]["evaluation_result"] == expected
            and value["evidence_judge"]["covered_count"] == 1
        )
        result.append({"expected": expected, "passed": passed, **value})
        append(directory / "cases.jsonl", result[-1])
    provider.close()
    status = (
        "JUDGE_CALIBRATION_PASS" if all(x["passed"] for x in result) else "JUDGE_CALIBRATION_FAILED"
    )
    write(directory / "terminal.json", {"status": status, "cases": len(result)})
    print(status)
    if status != "JUDGE_CALIBRATION_PASS":
        raise ValueError(status)


def isolate(m):
    import uuid

    from v0224_native_wma_mcp import NoteMCP

    directory = RAW / "service/isolation"
    directory.mkdir(parents=True, exist_ok=False)
    clients, receipts = [], []
    try:
        for index, spec in enumerate(m["roots"], 1):
            client = NoteMCP(
                RAW / "service/secrets" / f"root-{index:02d}.json",
                directory / f"root-{index:02d}",
                max_http=7,
            )
            clients.append(client)
            operation_id = uuid.uuid4().hex
            content = "Independent principal isolation fixture " + spec["root"]
            try:
                receipt = client.call(
                    "milai_note_add",
                    {"operation_id": operation_id, "content": content, "format": "text"},
                )
            except BaseException:
                client.call("milai_note_operation_get", {"operation_id": operation_id})
                raise
            if (
                receipt.get("commit_status") != "COMMITTED"
                or receipt.get("durable") is not True
                or receipt.get("version") != 1
                or receipt.get("content_digest")
                != "sha256:" + hashlib.sha256(content.encode()).hexdigest()
            ):
                raise ValueError("ISOLATION_FIXTURE_COMMIT_INVALID")
            page = client.call("milai_note_get", {"memory_id": receipt["memory_id"]})
            if page.get("content") != content:
                raise ValueError("ISOLATION_FIXTURE_OWN_READ_FAILED")
            receipts.append(receipt)
        for index, client in enumerate(clients):
            try:
                client.call(
                    "milai_note_get",
                    {"memory_id": receipts[(index + 1) % len(clients)]["memory_id"]},
                )
            except ValueError as exc:
                path = directory / f"root-{index + 1:02d}" / "mcp-http.jsonl"
                rows = [json.loads(x) for x in path.read_text().splitlines()]
                observed = next(x for x in reversed(rows) if x["event"] == "HTTP_OBSERVED")
                if str(exc) != "PUBLIC_NOTE_TOOL_ERROR" or "NOTE_NOT_FOUND" not in observed["body"]:
                    raise ValueError("ISOLATION_UNEXPECTED_ERROR") from exc
            else:
                raise ValueError("CROSS_PRINCIPAL_NOTE_VISIBLE")
        for client in clients:
            client.close()
        write(
            directory / "terminal.json",
            {
                "status": "PASS",
                "principals": 4,
                "own_reads": 4,
                "denied_cross_reads": 4,
                "writes": 4,
                "http_requests": sum(c.http_requests for c in clients),
            },
        )
    finally:
        for client in clients:
            client.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["prepare", "calibrate", "isolate", "answer", "judge"])
    p.add_argument("--manifest-sha256")
    p.add_argument("--root")
    p.add_argument("--arm", choices=["B_native", "M_note", "R_review"])
    a = p.parse_args()
    started = time.monotonic()
    upstream()
    if a.command == "prepare":
        prepare()
        return
    m = check_manifest(a.manifest_sha256)
    if a.command == "isolate":
        isolate(m)
    elif a.command == "calibrate":
        calibrate(m)
    elif a.command == "answer":
        answer(m, a.root, a.arm)
    else:
        judge(m, a.root, a.arm)
    print(
        json.dumps(
            {
                "command": a.command,
                "status": "EXIT_PASS",
                "elapsed_seconds": time.monotonic() - started,
                "pid": os.getpid(),
            }
        )
    )


if __name__ == "__main__":
    main()
