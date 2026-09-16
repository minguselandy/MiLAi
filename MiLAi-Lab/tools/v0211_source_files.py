"""Ordinary read-only files/search/images for a single complete Small source domain."""

from __future__ import annotations

import argparse
import base64
import json
import time
from pathlib import Path

from check_v0210_control import write
from check_v0211_source_fidelity import verify_png
from milai_lab.methods.state_control import digest
from v02_read_file import read_page
from v02_search_files import search_files


class SourceFiles:
    """Only frozen domain source files are addressable; evaluation files are absent."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        self.text = json.loads((self.root / "text-index.json").read_text())
        self.images = json.loads((self.root / "image-index.json").read_text())

    def listing(self) -> dict:
        return {"text_files": sorted(self.text), "images": sorted(self.images)}

    def read(self, path: str, offset: int = 0, limit: int = 4096) -> dict:
        return read_page(self.root, path, offset, limit, self.text[path])

    def search(self, queries: list[str], offset: int = 0) -> dict:
        return search_files(self.root, self.text, queries, offset)

    def image(self, path: str) -> dict:
        expected = self.images[path]
        target = self.root / path
        if target.is_symlink() or not target.resolve().is_relative_to(self.root):
            raise ValueError("IMAGE_OUTSIDE_SOURCE_ROOT")
        raw = target.read_bytes()
        if digest(raw) != expected["sha256"]:
            raise ValueError("SOURCE_CHANGED")
        # Exact original pixels; callers must include this actual block in model input.
        return {"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(raw).decode("ascii")}}


def check(root: Path, output: Path) -> dict:
    results = {}
    for domain in ("web", "enterprise"):
        source = SourceFiles(root / "sources" / domain)
        started = time.monotonic()
        # Lexicographic first source, independent of questions/answers/support annotations.
        path = sorted(source.text)[0]
        pages, recovered, offset = 0, bytearray(), 0
        while True:
            page = source.read(path, offset, 1024)
            recovered.extend(page["text"].encode())
            pages += 1
            if page["next"] is None:
                break
            offset = page["next"]["offset"]
        assert digest(recovered) == source.text[path]
        assert pages > 1
        record = json.loads(recovered)
        image_path = record["screenshot"]
        block = source.image(image_path)
        image_bytes = base64.b64decode(block["image_url"]["url"].split(",", 1)[1])
        assert digest(image_bytes) == source.images[image_path]["sha256"]
        dimensions = verify_png(image_bytes)
        found = source.search(["accessibility_tree"])
        assert found["hits"] and all(row["path"] in source.text for row in found["hits"])
        denied = []
        for forbidden in ("../../evaluation/evaluation_contract.json", "text-index.json"):
            try:
                source.read(forbidden)
            except KeyError:
                denied.append(forbidden)
        assert len(denied) == 2
        results[domain] = {
            "available_text_files": len(source.text), "available_images": len(source.images),
            "read_path": path, "pages": pages, "recovered_bytes": len(recovered),
            "full_read_sha256": digest(recovered), "literal_search_hits": len(found["hits"]),
            "image_path": image_path, "image_sha256": digest(image_bytes),
            "image_dimensions": dimensions, "original_image_block_round_trip": "PASS",
            "evaluation_path_access": "DENIED", "seconds": time.monotonic() - started,
        }
    result = {"status": "PASS", "domains": results, "benchmark_generations": 0,
              "model_requests": 0, "actual_model_image_presentation": "NOT_RUN",
              "retrieval_kind": "LITERAL_FILE_SEARCH_NO_MODEL_OR_GOLD_ROUTING",
              "shared_source_writes": 0, "product_ingest": False}
    write(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.root.resolve(), args.output.resolve())))
