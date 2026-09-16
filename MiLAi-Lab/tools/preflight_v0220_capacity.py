"""Zero-generation context checks of complete already-scripted Host payloads."""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

from v0213_provider import ENDPOINT, MODEL, TOKENIZE_KEYS
from v0220_evidence import read, save, seal, sha, validate


def preflight(source: Path, root: Path) -> dict:
    validate(source)
    source_result = read(source / "result.json")
    inputs = [source / "manifest.json", source / "result.json"]
    cases = []
    for row in source_result["rows"]:
        if row["cold"] != 1:
            continue
        directory = source / "cold" / row["episode_id"]
        for turn in (1, row["scripted_generations"]):
            path = directory / f"scripted-provider-{turn:02d}.json"
            inputs.append(path)
            cases.append((row["episode_id"], turn, path))
    seal(
        root,
        entries=[Path(__file__)],
        inputs=inputs,
        contract={
            "stage": "V1_CAPACITY_PREFLIGHT_NOT_MODEL_GENERATION",
            "requests": len(cases),
            "endpoint": ENDPOINT,
            "model": MODEL,
            "output_reservation": 4096,
            "source_manifest_sha256": sha(source / "manifest.json"),
        },
    )
    rows = []
    with httpx.Client(
        base_url=ENDPOINT, timeout=5, trust_env=False, follow_redirects=False
    ) as client:
        response = client.get("/v1/models")
        response.raise_for_status()
        model_list = response.json()
        save(root / "models.json", model_list)
        models = model_list["data"]
        if [m["id"] for m in models] != [MODEL]:
            raise ValueError("MODEL_IDENTITY_CHANGED")
        context = models[0]["max_model_len"]
        for index, (episode, turn, path) in enumerate(cases, 1):
            body = read(path)["body"]
            assert body["model"] == MODEL and body["max_tokens"] == 4096
            request = {k: body[k] for k in TOKENIZE_KEYS}
            save(root / f"{index:02d}-request.json", request)
            response = client.post("/tokenize", json=request)
            response.raise_for_status()
            data = response.json()
            save(root / f"{index:02d}-response.json", data)
            count = data["count"]
            row = {
                "episode": episode,
                "turn": turn,
                "prompt_tokens": count,
                "reserved_output": 4096,
                "context": context,
                "fits": count + 4096 <= context,
                "source_body_sha256": sha(path),
            }
            rows.append(row)
            print(
                f"{index}/{len(cases)} context={count}+4096/{context} fits={row['fits']}",
                flush=True,
            )
    validate(root)
    result = {
        "status": "ALL_PROSPECTIVE_INPUTS_FIT"
        if all(r["fits"] for r in rows)
        else "INPUT_CAPACITY_GAP",
        "rows": rows,
        "tokenize_calls": len(rows),
        "model_requests": 0,
        "judge_requests": 0,
        "interpretation": "Scripted first/final payload sizes only; "
        "not model efficacy or all natural continuations.",
    }
    save(root / "result.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    preflight(args.source, args.root)
