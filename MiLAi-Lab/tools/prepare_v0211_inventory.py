"""Metadata-only inventory; preserve old protected partitions and all target positions."""

# ruff: noqa: S607 -- fixed read-only Git invocation

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import httpx

from check_v0210_control import LAB, write
from export_v02_lme_sources import object_spans

BENCH = LAB.parent / "benchmarks"
META = re.compile(rb'(?<!\\)"(id|question_id|domain|environment|question_type|image)"'
                  rb'\s*:\s*("(?:[^"\\]|\\.)*"|null)')


def metadata(raw: bytes) -> dict:
    return {key.decode(): json.loads(value) for key, value in META.findall(raw)}


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def inventory(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    config = LAB / "configs/v0211-external-diagnostic.json"
    write(root / "allocation.json", json.loads(config.read_text()))
    pins = {}
    for name, repo in [("V1", "LongMemEval"), ("V2", "LongMemEval-V2")]:
        source = BENCH / repo
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source,
                                capture_output=True, text=True, check=True).stdout.strip()
        pins[name] = {"code_commit": commit, "code_license_sha256": sha(source / "LICENSE"),
                      "readme_sha256": sha(source / "README.md")}
    v1path = BENCH / "LongMemEval/data/longmemeval_oracle.json"
    raw = v1path.read_bytes()
    v1 = [metadata(raw[a:b]) for a, b in object_spans(raw)]
    write(root / "v1-metadata.json", v1)
    pins["V1"]["oracle_sha256"] = sha(v1path)
    v2root = BENCH / "LongMemEval-V2/data/longmemeval-v2"
    v2 = [metadata(line) for line in (v2root / "questions.jsonl").read_bytes().splitlines() if line]
    write(root / "v2-metadata.json", v2)
    checksums = {line.split(maxsplit=1)[1]: line.split(maxsplit=1)[0]
                 for line in (v2root / "checksums.sha256").read_text().splitlines()}
    for name in ["questions.jsonl", "trajectories.jsonl", "haystacks/lme_v2_small.json",
                 "LICENSE", "SCHEMA.md", "DATA_CARD.md"]:
        observed = sha(v2root / name)
        assert observed == checksums[name], name
        pins["V2"][name] = {"sha256": observed, "bytes": (v2root / name).stat().st_size}
    with httpx.Client(timeout=20) as remote:
        for name, repo in [("V1", "longmemeval-cleaned"), ("V2", "longmemeval-v2")]:
            response = remote.get("https://huggingface.co/api/datasets/xiaowu0162/" + repo)
            response.raise_for_status()
            info = response.json()
            pins[name]["remote_dataset_revision"] = info["sha"]
            pins[name]["remote_card"] = info.get("cardData")
            if name == "V2":
                response = remote.get("https://huggingface.co/datasets/xiaowu0162/longmemeval-v2/"
                                      f"resolve/{info['sha']}/checksums.sha256",
                                      follow_redirects=True)
                response.raise_for_status()
                remote_sums = {line.split(maxsplit=1)[1]: line.split(maxsplit=1)[0]
                               for line in response.text.splitlines()}
                for filename in ("questions.jsonl", "trajectories.jsonl",
                                 "haystacks/lme_v2_small.json"):
                    assert remote_sums[filename] == pins[name][filename]["sha256"]
                (root / "remote-v2-checksums.sha256").write_text(response.text)
    with httpx.Client(timeout=5, trust_env=False) as local:
        response = local.get("http://127.0.0.1:7860/v1/models")
        response.raise_for_status()
        write(root / "model-discovery.json", response.json())
    model_path = Path("/cra/qwen36-35B/config.json")
    model_config = json.loads(model_path.read_text())
    write(root / "model-capability.json", {
        "config_sha256": sha(model_path), "architectures": model_config["architectures"],
        "vision_config_present": "vision_config" in model_config,
        "generation_compatibility": "NOT_YET_OBSERVED_NO_PROBE_ALLOCATED"})
    write(root / "dataset-pins.json", pins)
    result = {"status": "METADATA_INVENTORY_COMPLETE_EXPOSURE_AND_BACKEND_PENDING",
              "V1_count": len(v1), "V2_count": len(v2), "model_generations": 0,
              "question_answer_history_bodies_exposed_to_host_or_reviewer": False,
              "note": "Only metadata JSON tokens decoded; corpus bytes hashed/structurally scanned"}
    write(root / "inventory-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inventory(args.root.resolve())))
