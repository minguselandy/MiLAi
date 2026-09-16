"""Three cold paired full-history imports via pinned public APIs; no model calls."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

import run_v02_memory_flow as base
from run_v02_lme_incremental import CONFIG, DATA, STUDY
from v02_lme_capture import capture_persistent
from v02_lme_sources import capture_legacy, history_events


def normalized_evidence(response: dict[str, Any]) -> list[Any]:
    return sorted((sorted(ref.split("/session/", 1)[1]
                          for ref in item["source"]["turn_refs"]), item["text"])
                  for item in response["evidence"])


def query(environment: dict[str, str], project: str, directory: Path,
          question: str) -> dict[str, Any]:
    token, port = secrets.token_urlsafe(32), base._free_port()
    values = dict(environment)
    values.update({"MILAI_AGENT_SCOPE_JSON": json.dumps({"project_ids": [project]}),
                   "MILAI_CODEX_TOKEN": token, "MILAI_CODEX_PRINCIPAL_ID": "v02-lme-host",
                   "MILAI_CODEX_TASK_REF": project,
                   "MILAI_MCP_HTTP_PUBLIC_BASE_URL": f"http://127.0.0.1:{port}"})
    group = base.ProcessGroup(directory)
    try:
        server = group.start("observer", [str(base.MCP / ".venv/bin/milai-codex-full-mcp"),
                                          "--port", str(port)], cwd=base.MCP,
                             env=base._clean_environment(values))
        base._wait_http(f"http://127.0.0.1:{port}/readyz", server)
        return base.structured(asyncio.run(base.mcp_call(
            f"http://127.0.0.1:{port}/mcp", token, "milai_memory_resolve", {"query": question})))
    finally:
        group.stop()


def main() -> None:
    root = STUDY / "l0l1-20260905a"
    base.assert_services(root)
    identity = base.pin(CONFIG)
    target = root / "probes/capture-paired"
    target.mkdir()
    raw = (DATA / "sources/0a995998.json").read_bytes()
    source = json.loads(raw)
    values = base._load_environment(root / "runtime.env")
    order = [["legacy", "persistent"], ["persistent", "legacy"], ["legacy", "persistent"]]
    base.write_json(target / "plan.json", {
        "source_sha256": hashlib.sha256(raw).hexdigest(), "product_pin": identity,
        "order": order, "events": 484, "model_calls": 0,
        "source_preparation": "fresh branch each arm; serial imports, one worker, no source reuse",
        "cache_condition": "process/client cold; shared warm API/PG; no claim of cold database",
        "code": {p: hashlib.sha256((base.LAB / "tools" / p).read_bytes()).hexdigest()
                 for p in ["v02_lme_capture.py", "v02_lme_capture_worker.py",
                           "v02_lme_sources.py"]},
    })
    pairs = []
    for index, arms in enumerate(order, 1):
        pair = {}
        for arm in arms:
            name = f"capture-pair-{index}-{arm}"
            directory = target / name
            directory.mkdir()
            project = "v02l-" + name
            events = history_events(source, name)
            capture = capture_legacy if arm == "legacy" else capture_persistent
            try:
                timing = capture(values, project, events, directory, 300)
                response = query(values, project, directory, source["question"])
                base.write_json(directory / "query.json", response)
                receipts = [json.loads(line) for line in
                            (directory / "source-receipts.jsonl").read_text().splitlines()]
                assert all(r["canonical_mutation"] is False for r in receipts)
                assert [r["source_id"] for r in receipts] == [e["source_id"] for e in events]
                base.write_json(directory / "result.json", timing)
                pair[arm] = {"timing": timing, "query": normalized_evidence(response)}
                print(json.dumps({"branch": name, "seconds": timing["elapsed_seconds"]}),
                      flush=True)
            except Exception as exc:
                base.write_json(directory / "failure.json", {"type": type(exc).__name__,
                                                           "message": str(exc)})
                raise
        pair["same_returned_evidence"] = pair["legacy"]["query"] == pair["persistent"]["query"]
        pairs.append(pair)
        base.write_json(target / "result.json", {"status": "COMPLETE" if index == 3 else "RUNNING",
                                                "pairs": pairs, "model_calls": 0})


if __name__ == "__main__":
    main()
