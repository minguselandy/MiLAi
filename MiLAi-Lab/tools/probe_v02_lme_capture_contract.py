"""Real PostgreSQL-backed public capture replay and refusal probes; no model calls."""

from __future__ import annotations

import json

import run_v02_memory_flow as base
from run_product09_codex_lifecycle import _http_json
from run_v02_lme_incremental import CONFIG, DATA, STUDY
from v02_lme_capture import capture_persistent
from v02_lme_sources import history_events


def main() -> None:
    root = STUDY / "l0l1-20260905a"
    base.assert_services(root)
    base.pin(CONFIG)
    values = base._load_environment(root / "runtime.env")
    target = root / "probes/capture-contract"
    target.mkdir()
    source = base.read_json(DATA / "sources/0a995998.json")
    branch = "capture-pair-1-persistent"
    events = history_events(source, branch)
    old = json.loads((root / "probes/capture-paired" / branch /
                      "source-receipts.jsonl").read_text().splitlines()[0])
    replay = target / "replay"
    replay.mkdir()
    timing = capture_persistent(values, "v02l-" + branch, events[:1], replay, 30)
    new = json.loads((replay / "source-receipts.jsonl").read_text())
    assert new["receipt"]["evidence_id"] == old["receipt"]["evidence_id"]
    assert new["receipt"]["outbox_id"] == old["receipt"]["outbox_id"]
    assert new["operation_id"] == old["operation_id"]
    outcomes = {"idempotent_public_replay": True, "replay_timing": timing}
    for name, extra in [
        ("reader_token", {"MILAI_AGENT_SUBMITTER_TOKEN": values["MILAI_AGENT_READER_TOKEN"]}),
        ("unsupported_journal", {"MILAI_HOST_EVENT_JOURNAL": "SHADOW"}),
    ]:
        directory = target / name
        directory.mkdir()
        try:
            capture_persistent({**values, **extra}, "v02l-capture-contract-" + name,
                               history_events(source, "refusal-" + name)[:1], directory, 30)
        except RuntimeError:
            lines = (directory / "source-receipts.jsonl").read_text().splitlines()
            if name == "reader_token":
                refusal = json.loads(lines[0])
                assert refusal["status"] == "REJECTED"
                assert refusal["error"]["status_code"] == 403
                outcomes[name] = refusal
            else:
                assert not lines
                outcomes[name] = "REFUSED_BEFORE_CAPTURE"
        else:
            raise AssertionError("Expected refusal")
    status, result = _http_json(
        "GET", values["MILAI_BASE_URL"] + "/v1/evidence/" + old["receipt"]["evidence_id"],
        token=values["MILAI_AGENT_READER_TOKEN"], timeout=15,
    )
    base.write_json(target / "public-metadata.json", {"http_status": status, "response": result})
    outcomes["metadata_read_status"] = status
    outcomes["model_calls"] = 0
    base.write_json(target / "result.json", outcomes)
    print(json.dumps({"idempotent": True, "reader_write": "403", "journal": "REFUSED",
                      "metadata_status": status}))


if __name__ == "__main__":
    main()
