"""Verify whole Small source projection and every image, without any QA generation."""

from __future__ import annotations

import argparse
import json
import re
import struct
import zlib
from pathlib import Path

from check_v0210_control import LAB, verify_baseline, write
from milai_lab.methods.state_control import digest


def verify_png(raw: bytes) -> tuple[int, int]:
    """Validate original PNG framing, checksums and compressed pixel stream, without edits."""
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("PNG_SIGNATURE")
    offset, compressed, dimensions = 8, bytearray(), None
    while offset < len(raw):
        size = struct.unpack(">I", raw[offset:offset + 4])[0]
        kind = raw[offset + 4:offset + 8]
        body = raw[offset + 8:offset + 8 + size]
        checksum = struct.unpack(">I", raw[offset + 8 + size:offset + 12 + size])[0]
        if zlib.crc32(kind + body) != checksum:
            raise ValueError("PNG_CHECKSUM")
        if kind == b"IHDR":
            dimensions = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            compressed.extend(body)
        offset += size + 12
        if kind == b"IEND":
            break
    if dimensions is None or min(dimensions) < 1 or not zlib.decompress(compressed):
        raise ValueError("PNG_PIXEL_STREAM")
    return dimensions


def check(root: Path) -> dict:
    mapping = json.loads((root / "evaluation/source-map.json").read_text())
    data = LAB.parent / "benchmarks/LongMemEval-V2/data/longmemeval-v2"
    identity = re.compile(rb'^\s*\{\s*"id"\s*:\s*"([^"\\]+)"')
    verified = 0
    source_fields = ("state_index", "step", "url", "action", "thought", "accessibility_tree")
    for raw in (data / "trajectories.jsonl").open("rb"):
        match = identity.search(raw)
        if not match or match[1].decode() not in mapping:
            continue
        record = json.loads(raw)
        provenance = mapping[record["id"]]
        assert digest(raw) == provenance["original_record_sha256"]
        assert len(record["states"]) == len(provenance["states"])
        for original, ref in zip(record["states"], provenance["states"], strict=True):
            path = root / "sources" / provenance["domain"] / ref["file"]
            restored = json.loads(path.read_text())
            assert all(restored[key] == original[key] for key in source_fields)
            assert all(restored[key] == record[key] for key in ("goal", "outcome", "start_url"))
            assert restored["trajectory"] == provenance["neutral"]
            assert original["screenshot"] == ref["original_image"]
            assert set(restored) == {*source_fields, "goal", "outcome", "start_url",
                                     "trajectory", "screenshot"}
            verified += 1
    domains = {r["domain"] for r in mapping.values()}
    images, text_files = 0, 0
    for domain in domains:
        source_root = root / "sources" / domain
        for relative, expected in json.loads((source_root / "text-index.json").read_text()).items():
            assert digest((source_root / relative).read_bytes()) == expected
            text_files += 1
        for relative, receipt in json.loads((source_root / "image-index.json").read_text()).items():
            path = source_root / relative
            assert digest(path.read_bytes()) == receipt["sha256"]
            verify_png(path.read_bytes())
            images += 1
    exported = json.loads((root / "source-export-result.json").read_text())
    assert verified == text_files == exported["states"]
    assert images == exported["image_count"] and not exported["missing_images"]
    baseline = json.loads((LAB / "configs/v0210-control-e1.json").read_text())
    pin = verify_baseline(baseline)
    result = {"status": "FULL_SOURCE_AND_IMAGE_BYTES_VERIFIED_NOT_BEHAVIORAL_BACKEND_FIT",
              "trajectories": len(mapping), "state_bodies_unchanged": verified,
              "images_verified": images, "label_fields_copied": 0,
              "product_artifact_pin": pin, "product_service_access": False,
              "online_retrieval_and_write_isolation": "NOT_RUN_PENDING_EXPOSURE_QUALIFICATION",
              "image_generation_compatibility": "NOT_RUN_NO_QUALIFIED_FIRST_WAVE_CASE",
              "model_requests": 0}
    write(root / "source-fidelity.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.root.resolve())))
