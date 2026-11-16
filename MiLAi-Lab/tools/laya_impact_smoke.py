"""Real HTTP smoke for open Laya; makes a decision but never writes memory.

Run from MiLAi-Lab: PYTHONPATH=src python tools/laya_impact_smoke.py
"""
from __future__ import annotations

import json
import os

import httpx

from milai_lab.methods.laya_impact import LayaImpactClient


def main() -> None:
    endpoint = os.getenv("LAYA_BASE_URL", "http://127.0.0.1:8000")
    with httpx.Client(timeout=120.0) as client:
        health = client.get(endpoint.rstrip("/") + "/health").json()
        controller = LayaImpactClient(
            base_url=endpoint,
            api_key=os.getenv("LAYA_API_KEY"),
            model=os.getenv("LAYA_IMPACT_MODEL", "multilingual"),
            http_client=client,
        )
        aliases = ["u1", "u2", "u3"]
        schema = {
            "type": "object",
            "properties": {
                "roots": {"type": "array", "items": {"enum": aliases, "type": "string"}},
                "preserve": {"type": "array", "items": {"enum": aliases, "type": "string"}},
            },
            "required": ["roots", "preserve"],
        }
        messages = [
            {"role": "system", "content": "Find affected memory units."},
            {"role": "user", "content": json.dumps({
                "observed_date": "2026-10-16",
                "delivery": {
                    "current_event": "Project A contact changes to Zhao; B unchanged.",
                    "old_units": {
                        "u1": "Project A contact Li",
                        "u2": "Project B contact Wang",
                        "u3": "External email requires approval",
                    },
                },
                "response_schema": schema,
            })},
        ]
        selection = controller.decide("impact", messages, schema)
        print(json.dumps({
            "health": health, "selection": selection,
            "provider_receipt": controller.receipts[-1],
        }, ensure_ascii=False, indent=2))
        print("This is model output, not verified correctness or a memory commit.")


if __name__ == "__main__":
    main()
