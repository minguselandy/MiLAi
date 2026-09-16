"""Query-blind complete Small source export; no summaries, embeddings or answer selection."""

from __future__ import annotations

import argparse
import json
import re
import tarfile
import time
from pathlib import Path

from check_v0210_control import LAB, write
from milai_lab.methods.state_control import canonical, digest
from prepare_v0211_inventory import sha
from v02_local_provider import append_event


def prepare(root: Path) -> dict:
    started = time.monotonic()
    data = LAB.parent / "benchmarks/LongMemEval-V2/data/longmemeval-v2"
    config = json.loads((root / "allocation.json").read_text())
    limit = config["resources"]
    # Only frozen metadata supplies membership; no future question/answer is read here.
    candidates = json.loads((root / "candidate-manifest.json").read_text())
    haystacks = json.loads((data / "haystacks/lme_v2_small.json").read_text())
    domains = {}
    for slot in candidates["slots"]:
        if slot.get("metadata"):
            domain = slot["metadata"]["domain"]
            ids = haystacks[slot["question_id"]]
            assert len(ids) == 100
            if domain in domains:
                assert domains[domain] == ids
            domains[domain] = ids
    mapping = {identity: (domain, f"source-{i:03d}")
               for domain, ids in domains.items() for i, identity in enumerate(ids)}
    for domain in domains:
        (root / "sources" / domain / "text").mkdir(parents=True, mode=0o700)
        (root / "sources" / domain / "images").mkdir(mode=0o700)
    index, source_map, images = {d: {} for d in domains}, {}, {}
    text_bytes = 0
    identity_re = re.compile(rb'^\s*\{\s*"id"\s*:\s*"([^"\\]+)"')
    for raw in (data / "trajectories.jsonl").open("rb"):
        match = identity_re.search(raw)
        if match is None or match[1].decode() not in mapping:
            continue
        record = json.loads(raw)
        original = record["id"]
        domain, neutral = mapping[original]
        source_map[original] = {"domain": domain, "neutral": neutral,
                                "original_record_sha256": digest(raw), "states": []}
        for ordinal, state in enumerate(record["states"]):
            image_id = f"{neutral}-state-{ordinal:04d}"
            name = image_id + ".json"
            image_path = "images/" + image_id + ".png" if state.get("screenshot") else None
            clean = {"trajectory": neutral, "goal": record["goal"], "outcome": record["outcome"],
                     "start_url": record["start_url"], "state_index": state["state_index"],
                     "step": state["step"], "url": state["url"], "action": state["action"],
                     "thought": state["thought"], "accessibility_tree": state["accessibility_tree"],
                     "screenshot": image_path}
            encoded = (canonical(clean) + "\n").encode()
            text_bytes += len(encoded)
            if text_bytes > limit["max_source_text_bytes"]:
                raise RuntimeError("SOURCE_EXPORT_RESOURCE_LIMIT")
            (root / "sources" / domain / "text" / name).write_bytes(encoded)
            index[domain]["text/" + name] = digest(encoded)
            source_map[original]["states"].append({"ordinal": ordinal, "file": "text/" + name,
                                                 "original_image": state.get("screenshot")})
            if image_path:
                source = Path(state["screenshot"])
                images[(source.parent.name, source.name)] = (domain, image_path)
        append_event(root / "ingest-ledger.jsonl", {"actor": "LAB_HARNESS",
            "classification": "HARNESS_INGEST", "operation_id": "source-export-" + original,
            "haystack": domain, "source_id": neutral, "states": len(record["states"]),
            "source_bytes": len(raw), "model_calls": 0, "future_query_read": False})
    assert set(source_map) == set(mapping)
    write(root / "evaluation/source-map.json", source_map)
    for domain in domains:
        write(root / "sources" / domain / "text-index.json", index[domain])
    image_receipts, archives, extracted = {}, {}, 0
    for path in sorted((data / "trajectory_screenshots").glob("*.tar.gz")):
        archives[path.name] = {"bytes": path.stat().st_size, "sha256": sha(path)}
        with tarfile.open(path, mode="r|gz") as archive:
            for member in archive:
                if time.monotonic() - started > limit["max_ingest_seconds"]:
                    raise RuntimeError("SOURCE_EXPORT_TIME_LIMIT")
                identity = (Path(member.name).parent.name, Path(member.name).name)
                if not member.isfile() or identity not in images:
                    continue
                domain, destination = images[identity]
                extracted += member.size
                if extracted > limit["max_extracted_image_bytes"]:
                    raise RuntimeError("IMAGE_EXPORT_RESOURCE_LIMIT")
                stream = archive.extractfile(member)
                assert stream is not None
                raw = stream.read()
                (root / "sources" / domain / destination).write_bytes(raw)
                image_receipts[domain + "/" + destination] = {"sha256": digest(raw),
                    "bytes": len(raw), "archive": path.name, "member": member.name}
    missing = ["/".join(value) for value in images.values()
               if "/".join(value) not in image_receipts]
    for domain in domains:
        write(root / "sources" / domain / "image-index.json", {
            name[len(domain) + 1:]: value for name, value in image_receipts.items()
            if name.startswith(domain + "/")})
    result = {"status": "COMPLETE_SOURCE_EXPORT" if not missing else "MISSING_IMAGES",
              "trajectories": len(source_map), "states": sum(map(len, index.values())),
              "text_bytes": text_bytes, "image_bytes": extracted,
              "image_count": len(image_receipts), "missing_images": missing,
              "archive_reads": archives, "seconds": time.monotonic() - started,
              "model_calls": 0, "agent_memory_mutations": 0,
              "ingest_representation": "NORMAL_SOURCE_FILES_NOT_PRODUCT_NOTE_OR_EVIDENCE",
              "future_query_or_gold_read": False, "domains": list(domains)}
    write(root / "source-export-result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root.resolve())))
