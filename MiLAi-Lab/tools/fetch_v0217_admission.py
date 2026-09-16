"""Bounded public artifact fetch; stores bytes/hash, never imports external task code."""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PINS = {
    "wma": ("UCSB-AI/WorldMemArena", "15ea25b723d9c4fb35e8062037aec6a5601e4442"),
    "supersede": ("Vrin-cloud/supersede", "677993d3713c265329ac935262d3c08cbfa4cd63"),
    "clawmark": ("evolvent-ai/ClawMark", "d1b641b3171e584e69a3763c269069f32a13b574"),
}


def fetch(root: Path, key: str, url: str, *, limit: int = 4_000_000) -> dict:
    target = root / key
    if target.exists():
        raise ValueError("PRESERVE_ARTIFACT_USE_EXISTING_BYTES_OR_NEW_PATH")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not url.startswith("https://"):
        raise ValueError("HTTPS_ARTIFACT_ONLY")
    request = urllib.request.Request(  # noqa: S310 -- HTTPS checked above
        url, headers={"User-Agent": "MiLAi-Lab-admission-readonly"})
    try:
        with urllib.request.urlopen(request, timeout=35) as response:  # noqa: S310
            raw = response.read(limit + 1)
            if len(raw) > limit:
                raise ValueError("BOUNDED_DOWNLOAD_LIMIT")
            receipt = {"url": url, "resolved_url": response.url, "status": response.status,
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "path": key}
        target.write_bytes(raw)
    except Exception as exc:
        receipt = {"url": url, "path": key, "status": "FETCH_FAILED", "reason": str(exc)}
    ledger = root / "fetch-ledger.jsonl"
    with ledger.open("a") as stream:
        stream.write(json.dumps(receipt) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--trees", action="store_true")
    parser.add_argument("--candidate", choices=list(PINS))
    parser.add_argument("--paths", nargs="*")
    parser.add_argument("--url")
    parser.add_argument("--output")
    parser.add_argument("--claw-screen", action="store_true")
    args = parser.parse_args()
    args.root.mkdir(parents=True, exist_ok=True)
    if args.claw_screen:
        tree = json.loads((args.root / "clawmark/tree.json").read_text())
        paths = [x["path"] for x in tree["tree"] if x["path"].endswith("/task.py")]
        ordered = sorted(paths, key=lambda path: hashlib.sha256(
            ("217:" + path).encode()).hexdigest())
        pool = {"seed_rule": "sha256('217:' + path) ascending", "universe": ordered,
            "screen_limit": 12, "stop": "12 screened or two distinct-family isolated fixtures",
            "eligibility": "Readable reviewed task code; fixture callable with isolated local "
                "filesystem or deterministic stub; no external account, full assets or model",
            "scope": "Fixture admission only, not full-task eligibility or behavior score",
            "selected_for_static_screen": ordered[:12], "model_requests": 0}
        (args.root / "clawmark/frozen-pool.json").write_text(json.dumps(pool, indent=2))
        repo, revision = PINS["clawmark"]
        def obtain(path):
            return fetch(args.root, "clawmark/" + path,
                         f"https://raw.githubusercontent.com/{repo}/{revision}/{path}")
        with ThreadPoolExecutor(max_workers=4) as workers:
            for receipt in workers.map(obtain, ordered[:12]):
                print(json.dumps(receipt), flush=True)
    elif args.trees:
        for name, (repo, revision) in PINS.items():
            print(json.dumps(fetch(args.root, name + "/tree.json",
                f"https://api.github.com/repos/{repo}/git/trees/{revision}?recursive=1")))
    elif args.url:
        print(json.dumps(fetch(args.root, args.output, args.url)))
    else:
        repo, revision = PINS[args.candidate]
        for path in args.paths:
            print(json.dumps(fetch(args.root, args.candidate + "/" + path,
                f"https://raw.githubusercontent.com/{repo}/{revision}/{path}")))
