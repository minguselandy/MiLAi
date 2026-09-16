"""Seventh source: signed interval guidance bridge, not another consensus-gap template."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path

from prepare_v0218 import SOURCE_REVISION
from v0218_world import World

ASSETS = {
    "now_q1_2024_earnings_release.pdf": (
        "2d24b8534d9b0e56890881a0fbc4dc172751e0030f7f424ed0c6384aaeb80deb"
    ),
    "now_q4_2023_earnings_release.pdf": (
        "9ebf3bd924436d8fda049e46c5fd132c15e5e5a337e626d8de28033355f33409"
    ),
}


def guidance_bridge() -> dict:
    task = {
        "instruction": "Persist an internal ServiceNow FY24 subscription guidance bridge. "
        "Preserve both ends of the prior and current guidance intervals. Separate the signed "
        "reported midpoint change from the FX contribution and the residual operational "
        "contribution; do not call an FX headwind an operational decline. This internal "
        "analysis resumes at a separate review session.",
        "record_fields": {
            "company": "ServiceNow",
            "period": "FY24",
            "metric": "subscription_revenue",
            "unit": "MUSD or BUSD; all numeric fields use this same unit",
            "prior_low": "prior guidance low",
            "prior_high": "prior guidance high",
            "current_low": "current guidance low",
            "current_high": "current guidance high",
            "low_change": "current_low minus prior_low",
            "high_change": "current_high minus prior_high",
            "net_change": "current midpoint minus prior midpoint",
            "fx_change": "signed source FX contribution, null only if unresolved",
            "operational_change": "net_change minus fx_change, null only if FX unresolved",
            "net_direction": "raise, cut or unchanged from net_change",
            "operational_direction": "raise, cut, unchanged, or unknown if unresolved",
            "status": "confirmed or pending_fx",
            "basis_revision": "current bridge revision",
        },
    }
    current = {
        "company": "ServiceNow",
        "period": "FY24",
        "metric": "subscription_revenue",
        "prior_range": {"low": 10555, "high": 10575, "unit": "MUSD"},
        "current_range": {"low": 10560, "high": 10575, "unit": "MUSD"},
        "fx": {"value": -17, "unit": "MUSD", "status": "confirmed"},
        "basis_revision": "bridge-v1",
        "source_notice": "Guidance endpoints come from the two original public release PDFs. "
        "FX -17M is an explicit exact local-world assumption, not an independently extracted "
        "image value. Derive the operational residual from these declared premises.",
    }
    public = {
        "objects": ["FY24-subscription-bridge"],
        "task": task,
        "current": current,
        "policy": {
            "domain": "signed_guidance_bridge",
            "rules": "Use exact published endpoints and arithmetic, not rounded narrative "
            "approximations. low_change and high_change preserve asymmetric interval changes. "
            "net_change is the midpoint difference, and operational_change = net_change - "
            "fx_change. Preserve signs and basis labels; a net cut can coexist with an "
            "operational raise. All output amounts share the chosen MUSD or BUSD unit; "
            "absolute tolerance is 0.000001 MUSD. If FX is genuinely unresolved, still "
            "compute known endpoint/net changes; write null FX/operational, pending_fx and "
            "unknown operational direction, and request FX verification. Confirmed FX "
            "needs no clarification. Peer news never changes this company's published range.",
        },
    }
    changed = copy.deepcopy(current)
    changed.update(
        current_range={"low": 10540, "high": 10560, "unit": "MUSD"},
        fx={"value": -25, "unit": "MUSD", "status": "confirmed"},
        basis_revision="bridge-v2",
    )
    unresolved = copy.deepcopy(changed)
    unresolved.update(
        fx={"value": None, "unit": "MUSD", "status": "unresolved"},
        basis_revision="bridge-fx-pending",
    )
    irrelevant = copy.deepcopy(current)
    irrelevant["peer_notice"] = {"company": "Salesforce", "signal": "weaker guidance"}
    return {
        "root": "investment_analyst_task3",
        "family": "signed_guidance_bridge",
        "source": "tasks/investment_analyst/task3/task.py",
        "public": public,
        "variants": {
            "stable": current,
            "superseded": changed,
            "unresolved": unresolved,
            "irrelevant": irrelevant,
        },
        "task_B": {
            **task,
            "instruction": "Resume and finalize the signed FY24 subscription "
            "guidance bridge using the current publication. Preserve valid ranges "
            "and separate FX from operational changes; do not defer known arithmetic.",
        },
        "adaptation": [
            "Original Q4 release FY24 interval 10555-10575M and Q1 release 10560-10575M "
            "were read directly with pypdf 6.0.0 text extraction, not OCR or Judge.",
            "These original endpoints imply +5M low, 0M high and +2.5M midpoint change. "
            "Do not substitute the native checker's approximate +3M narrative as exact truth.",
            "Exact -17M FX is a declared adapted public premise inspired by the native "
            "bridge checker, not independently verified bridge-image extraction. It implies "
            "+19.5M operational residual, not exact +20M. No hidden answer source at runtime.",
            "B's 10540-10560M interval/-25M FX and unresolved FX are new declared external "
            "events, not actual historical company updates or investment recommendations.",
            "One actual local bridge record replaces CSV/watchlist/email; original growth "
            "basis rows, cRPO, GenAI, LP messages, peer resilience prose, media extraction "
            "and trading/recipient safety rubric are excluded.",
        ],
        "lineage_audit": "Seventh original source remains clustered with financial analysis. "
        "Unlike task1's scalar guide-versus-consensus gap, this checks interval endpoint "
        "asymmetry, midpoint conservation, signed component attribution, and partially known "
        "arithmetic when one contribution is unresolved. Not merely a company rename.",
        "exposure": "EXPOSED_DEVELOPMENT",
        "not_applicable": {
            "helpful": "Current publication contains the complete small "
            "bridge inputs; no additional natural history-only requirement imposed."
        },
    }


def prepare(root: Path, source_root: Path) -> dict:
    spec = guidance_bridge()
    source_path = source_root / spec["source"]
    spec["source_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert (
        spec["source_sha256"] == "aa6478090df556b049c628d69af50fa37bdc59ed21d6fc0d306020493753c3a9"
    )
    for name, expected in ASSETS.items():
        assert (
            hashlib.sha256((source_path.parent / "assets/input" / name).read_bytes()).hexdigest()
            == expected
        )
    spec["assets_sha256"] = ASSETS
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    directory = root / spec["root"]
    directory.mkdir()
    contract = directory / "evaluation-contract.json"
    contract.write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    World.create(directory / "initial.sqlite", spec["root"], spec["public"])
    manifest = {
        "revision": "EXPANSION_SEVENTH_SOURCE_V1",
        "source_revision": SOURCE_REVISION,
        "profile": "MILAI_ADAPTED_BEHAVIORAL_TESTBED",
        "model_requests": 0,
        "memory_seeds": 0,
        "roots": [
            {
                "root": spec["root"],
                "family": spec["family"],
                "source": spec["source"],
                "source_sha256": spec["source_sha256"],
                "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
                "variants": list(spec["variants"]),
                "exposure": spec["exposure"],
            }
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.source_root)))
