"""Offline replay of the eight executed V02-12 requests; never sends completions.

Token attribution partitions the *rendered* prompt using tokenizer offsets. A token
crossing categories is counted once in boundary_residual, never in both categories.
Wire-only response_format is reported in bytes, not added to model prompt tokens.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import subprocess
import time
from collections import defaultdict
from pathlib import Path

from tokenizers import Tokenizer
from transformers import AutoTokenizer


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def wire(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def content_parts(content: str, role: str) -> list[tuple[str, int, int]]:
    """Exact character spans; JSON is scanned without reserializing source content."""
    if role != "user" or not content.startswith("{"):
        return [("host_visible_output" if role == "assistant" else "system_protocol",
                 0, len(content))]
    categories = {
        "question": "task", "source_files": "source_manifest",
        "source_view": "initial_history_view", "memory_tools": "memory_tool_definitions",
        "source_tools": "source_tool_definitions", "tool_results": "acquired_tool_results",
    }
    decoder, cursor, start, parts = json.JSONDecoder(), 1, 0, []
    while cursor < len(content):
        while content[cursor].isspace() or content[cursor] == ",":
            cursor += 1
        if content[cursor] == "}":
            break
        key, cursor = decoder.raw_decode(content, cursor)
        while content[cursor].isspace() or content[cursor] == ":":
            cursor += 1
        _, end = decoder.raw_decode(content, cursor)
        parts.append(("json_message_wrapper", start, cursor))
        parts.append((categories.get(key, "task"), cursor, end))
        start, cursor = end, end
    parts.append(("json_message_wrapper", start, len(content)))
    return parts


def attribute(rendered: str, messages: list[dict], tokenizer: Tokenizer,
              seen: set[tuple]) -> dict:
    segments, cursor = [], 0
    for index, message in enumerate(messages):
        content = message["content"].strip()
        start = rendered.index(content, cursor)
        segments.append(("role_template", cursor, start, (index, "prefix")))
        for part, (category, begin, end) in enumerate(content_parts(content, message["role"])):
            segments.append((category, start + begin, start + end, (index, category, part)))
        cursor = start + len(content)
    segments.append(("role_template", cursor, len(rendered), ("suffix",)))
    owners, table = [None] * len(rendered), defaultdict(lambda: {"tokens": 0, "bytes": 0})
    for category, begin, end, identity in segments:
        text = rendered[begin:end]
        key = (*identity, sha(text.encode()))
        repetition = "repeated" if key in seen else "first"
        seen.add(key)
        row = category, repetition
        table[row]["bytes"] += len(text.encode())
        owners[begin:end] = [row] * (end - begin)
    encoded = tokenizer.encode(rendered, add_special_tokens=False)
    for begin, end in encoded.offsets:
        rows = set(owners[begin:end])
        if len(rows) == 1 and None not in rows:
            row = rows.pop()
        else:
            repeats = {r[1] for r in rows if r is not None}
            row = "boundary_residual", repeats.pop() if len(repeats) == 1 else "mixed_boundary"
        table[row]["tokens"] += 1
    assert all(owner is not None for owner in owners)
    assert sum(row["tokens"] for row in table.values()) == len(encoded.ids)
    assert sum(row["bytes"] for row in table.values()) == len(rendered.encode())
    return {"prompt_tokens": len(encoded.ids), "rendered_bytes": len(rendered.encode()),
            "rendered_sha256": sha(rendered.encode()),
            "components": [{"category": cat, "occurrence": repeat, **value}
                           for (cat, repeat), value in sorted(table.items())]}


def advance(body: dict, visible: str, ledger: list[dict], offset: int,
            *, final: bool) -> tuple[dict, int]:
    """Reconstruct only observed output/calls; missing ledger evidence is an error."""
    action = json.loads(visible)
    if action["action"] != "tools":
        raise ValueError("NO_TOOL_CONTINUATION")
    results = []
    for call in action["calls"]:
        row = ledger[offset]
        if (row["tool"], row["arguments"]) != (call["name"], call["arguments"]):
            raise ValueError("TOOL_LEDGER_ORDER_MISMATCH")
        results.append({"name": row["tool"], "result": row["result"]})
        offset += 1
    result = copy.deepcopy(body)
    result["messages"].extend([
        {"role": "assistant", "content": visible},
        {"role": "user", "content": json.dumps({"tool_results": results}, ensure_ascii=False)},
    ])
    if final:
        result["messages"].append(
            {"role": "user", "content": "Final turn: deliver your answer now."})
    return result, offset


def export_tokenizer(container: str, root: Path) -> dict:
    """Read effective backend from the existing service environment; no model load."""
    code = (
        'import json,transformers,tokenizers,vllm; '
        'from transformers import AutoTokenizer; '
        't=AutoTokenizer.from_pretrained("/models",local_files_only=True); '
        'print(json.dumps({"backend":t.backend_tokenizer.to_str(),'
        '"template":t.chat_template,"class":type(t).__name__, '
        '"versions":{"transformers":transformers.__version__, '
        '"tokenizers":tokenizers.__version__,"vllm":vllm.__version__}}))'
    )
    result = subprocess.run(  # noqa: S603 -- explicit existing local container, read-only export
        ["/usr/bin/docker", "exec", container, "python3", "-c", code],
        capture_output=True, text=True, check=True, timeout=60)
    exported = json.loads(result.stdout)
    (root / "effective-tokenizer.json").write_text(exported.pop("backend"))
    (root / "chat_template.jinja").write_text(exported.pop("template"))
    return exported


def compact(body: dict) -> dict:
    """One H0 candidate: JSON whitespace only; every parsed field/string is retained."""
    result = copy.deepcopy(body)
    for message in result["messages"]:
        if message["role"] == "user" and message["content"].startswith("{"):
            parsed = json.loads(message["content"])
            message["content"] = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
            assert json.loads(message["content"]) == parsed
    return result


def replay_query(directory: Path, output: Path, render, tokenizer: Tokenizer) -> dict:
    output.mkdir(exist_ok=True)
    recorded = read(directory / "result.json")
    ledger = events(directory / "provider-ledger.jsonl")
    tools = events(directory / "tool-ledger.jsonl")
    reserved = [r for r in ledger if r["event"] == "RESERVED"]
    settled = {r["request_id"]: r for r in ledger if r["event"] == "SETTLED"}
    seen, rows, offset, raw, candidate_raw = set(), [], 0, 0, 0
    expected = None
    for index, reservation in enumerate(reserved):
        key = reservation["request_id"]
        path = directory / f"{key}-request.json"
        payload = path.read_bytes()
        body = json.loads(payload)
        assert sha(payload) == reservation["payload_sha256"]
        assert wire(body) == payload
        if expected is not None:
            assert wire(expected) == payload, "Historical next-payload reconstruction differs"
        observed = read(directory / f"{key}-tokenize.json")["count"]
        usage = settled[key]
        row = attribute(render(body), body["messages"], tokenizer, seen)
        assert row["prompt_tokens"] == observed == usage["input_tokens"]
        assert usage["usage"]["total_tokens"] == observed + usage["output_tokens"]
        row.update(request_id=key, payload_sha256=sha(payload), actual_sent=True,
                   wire_bytes=len(payload), output_tokens=usage["output_tokens"],
                   output_reservation=reservation["output_cap"],
                   response_format_wire_bytes=len(wire(body["response_format"])),
                   response_format_prompt_tokens=0)
        raw += observed + usage["output_tokens"]
        candidate = compact(body)
        candidate_tokens = len(tokenizer.encode(render(candidate), add_special_tokens=False).ids)
        candidate_raw += candidate_tokens + usage["output_tokens"]
        row["h0_compact_prompt_tokens"] = candidate_tokens
        rows.append(row)
        visible = (directory / f"{key}-visible.txt").read_text()
        saved_response = json.loads(read(directory / f"{key}-http.json")["body"])
        assert saved_response["choices"][0]["message"]["content"] == visible
        assert saved_response["usage"] == usage["usage"]
        if json.loads(visible)["action"] == "tools":
            expected, offset = advance(body, visible, tools, offset, final=index == 1)
        else:
            expected = None
    assert raw == recorded["accounting"]["raw_tokens"]
    assert offset == len(tools)
    result = {"query": directory.name, "status": "REPLAY_COMPLETE", "actual_requests": len(rows),
              "actual_raw_tokens": raw, "requests": rows, "acquired_tool_calls": len(tools),
              "historical_status": recorded["status"], "unsent": None}
    # A material absence is REPLAY_INCOMPLETE, never a fabricated model continuation.
    if recorded.get("reason") == "V05_FULL_RESERVATION_OVER_BUDGET":
        assert len(rows) == 2 and expected is not None
        unsent = attribute(render(expected), expected["messages"], tokenizer, seen)
        save(output / "reconstructed-unsent-request.json", expected)
        h0 = compact(expected)
        save(output / "h0-compact-unsent-request.json", h0)
        h0_tokens = len(tokenizer.encode(render(h0), add_special_tokens=False).ids)
        unsent.update(actual_sent=False, actual_usage=None, output_reservation=1024,
                      payload_sha256=sha(wire(expected)),
                      headroom=20000 - raw - unsent["prompt_tokens"] - 1024,
                      h0_prompt_tokens=h0_tokens,
                      h0_headroom_with_recorded_outputs=20000 - candidate_raw - h0_tokens - 1024,
                      candidate_label="H0_COMPACT_MECHANICAL_HEADROOM_ESTIMATE",
                      candidate_behavior="NOT_RUN_NOT_QUALITY_VERIFIED")
        assert unsent["headroom"] < 0
        result["unsent"] = unsent
    presented = sum(len(json.loads(m["content"]).get("tool_results", []))
                    for m in body["messages"] if m["role"] == "user"
                    and m["content"].startswith("{"))
    result.update(presented_tool_calls=presented, unpresented_tool_calls=len(tools) - presented)
    totals = defaultdict(lambda: {"tokens": 0, "bytes": 0})
    for row in rows:
        for component in row["components"]:
            total = totals[component["category"], component["occurrence"]]
            for metric in ("tokens", "bytes"):
                total[metric] += component[metric]
    result["query_components"] = [
        {"category": category, "occurrence": occurrence, **value}
        for (category, occurrence), value in sorted(totals.items())]
    save(output / "cost-replay.json", result)
    return result


def run(old: Path, root: Path, tokenizer_dir: Path, container: str) -> dict:
    start = time.monotonic()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    exported = (read(root / "measurement-lock.json")["effective_service_tokenizer"]
                if (root / "measurement-lock.json").exists()
                else export_tokenizer(container, root))
    tokenizer = Tokenizer.from_file(str(root / "effective-tokenizer.json"))
    renderer = AutoTokenizer.from_pretrained(tokenizer_dir, local_files_only=True)
    template = (root / "chat_template.jinja").read_text()

    def render(body):
        return renderer.apply_chat_template(body["messages"], chat_template=template,
                                            tokenize=False, add_generation_prompt=True,
                                            enable_thinking=False)

    save(root / "measurement-lock.json", {
        "effective_service_tokenizer": exported,
        "local_versions": {name: importlib.metadata.version(name)
                           for name in ("transformers", "tokenizers", "jinja2")},
        "tokenizer_sha256": sha((root / "effective-tokenizer.json").read_bytes()),
        "chat_template_sha256": sha(template.encode()),
        "local_model_files": {name: sha((tokenizer_dir / name).read_bytes())
                              for name in ("tokenizer.json", "tokenizer_config.json",
                                           "chat_template.jinja")},
        "serialization": "wire sorted compact UTF-8 JSON; message strings preserve original JSON",
        "attribution": "Rendered offsets; crossing tokens counted once in boundary_residual",
        "repetition": "Same message index/component/exact bytes in an earlier sent request",
        "response_format": ("Transport constraint excluded by historical TOKENIZE_KEYS; "
                            "agreement with all actual prompt usage required"),
        "historical_pin": {phase: read(old / phase / "implementation-pin.json")
                           for phase in ("p2-20260909", "p3-20260909")},
        "replay_code_sha256": sha(Path(__file__).read_bytes()),
        "generation_calls": 0,
    })
    results = []
    for phase in ("p2-20260909", "p3-20260909"):
        allocation = read(old / phase / "allocation.json")
        keys = allocation["queries"] if phase == "p2-20260909" else allocation["query_ids"]
        for key in keys:
            try:
                results.append(replay_query(old / phase / key, root / key, render, tokenizer))
            except (OSError, KeyError, IndexError, ValueError, AssertionError) as exc:
                results.append({"query": key, "status": "REPLAY_INCOMPLETE",
                                "error_type": type(exc).__name__, "reason": str(exc)})
    complete = all(r["status"] == "REPLAY_COMPLETE" for r in results)
    report = {"status": "P0_REPLAY_COMPLETE" if complete else "REPLAY_INCOMPLETE",
              "queries": results, "new_generations": 0, "new_raw_tokens": 0,
              "tokenize_http_calls": 0,
              "preimplementation_tokenize_diagnostics": {"calls": 1, "generation_calls": 0,
                  "query": "q002-2-01", "server_count": 6863, "naive_local_count": 6862,
                  "timing": "NOT_MEASURED", "purpose": "Identify effective tokenizer mismatch"},
              "elapsed_seconds": time.monotonic() - start,
              "candidate": "JSON whitespace only, frozen H0_COMPACT; never deployed",
              "behavioral_decomposition": "NOT_YET_RUN"}
    if complete:
        report["historical_actual_raw_tokens"] = sum(r["actual_raw_tokens"] for r in results)
        report["historical_actual_requests"] = sum(r["actual_requests"] for r in results)
        assert len(results) == 8
        assert report["historical_actual_raw_tokens"] == 69325
        assert report["historical_actual_requests"] == 10
    save(root / "result.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--tokenizer-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-container", required=True)
    args = parser.parse_args()
    report = run(args.old_root, args.root, args.tokenizer_dir, args.tokenizer_container)
    print(json.dumps({"status": report["status"], "new_generations": 0}))
