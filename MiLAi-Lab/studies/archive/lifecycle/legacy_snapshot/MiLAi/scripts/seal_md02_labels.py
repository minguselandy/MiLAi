#!/usr/bin/env python3
"""Seal MD-02 development, validation, freshness, and protocol identities."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from milai.domain.requirement_state import canonical_sha256

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "evals/md02/fixtures"
REPAIR = FIXTURE_DIR / "boundary-repair-dev.v0.1.json"
SEALED = FIXTURE_DIR / "shadow-validation.v0.1.json"
FRESHNESS = FIXTURE_DIR / "freshness-contract.v0.1.json"
RUN_ID = "md02-boundary-product-shadow-20260830-001"
OUTPUT_DIR = ROOT / "var/md02" / RUN_ID
RUN_LOCK = OUTPUT_DIR / "run-lock.json"

EVALUATOR = ROOT / "evals/md02/boundary_shadow_effect.py"
BOUNDARY_V02 = ROOT / "runtime/src/milai/application/semantic_episode_boundary_v02.py"
SHADOW_HOOK = ROOT / "runtime/src/milai/application/semantic_episode_shadow.py"
V01_BUILDER = ROOT / "runtime/src/milai/application/memory_formation.py"
PREDECESSOR = ROOT / "var/mf02/mf02-semantic-episode-four-arm-20260830-001/terminal.json"


def _repair_specs() -> list[dict[str, Any]]:
    return [
        _split_spec(
            "repair-copper-garden",
            "COPPER_GARDEN",
            "The copper watering can is beside my herb garden.",
            "Is the copper watering can still by the garden?",
            "The Copper release checklist needs a security review.",
            "That software checklist is due before Friday.",
            "What needs a security review before Friday?",
        ),
        _split_spec(
            "repair-lotus-camera",
            "LOTUS_CAMERA",
            "My Lotus camera received a replacement lens yesterday.",
            "Did the Lotus camera focus correctly afterward?",
            "The Lotus payroll worksheet is ready for approval.",
            "Finance will approve that worksheet tomorrow.",
            "Which worksheet is ready for approval?",
        ),
        _split_spec(
            "repair-juniper-coat",
            "JUNIPER_COAT",
            "My Juniper coat came back from the tailor.",
            "Does the Juniper coat fit better now?",
            "The Juniper backup job failed during verification.",
            "That backup will run again tonight.",
            "What failed during verification?",
        ),
        _split_spec(
            "repair-ruby-market",
            "RUBY_MARKET",
            "The Ruby market sells the tea I like.",
            "Did the Ruby market restock that tea?",
            "The Ruby parser benchmark finished this morning.",
            "Its benchmark report is stored locally.",
            "What finished this morning?",
        ),
        _continuation_spec(
            "repair-piano-tone",
            "QUESTION_FOCUS_CONTINUATION",
            "A technician adjusted my old piano yesterday.",
            "Does the middle register sound stable now?",
            "The middle register sounds steady during scales.",
            "My grocery delivery arrives at six.",
            "How does the middle register sound now?",
        ),
        _continuation_spec(
            "repair-bicycle-brake",
            "QUESTION_FOCUS_CONTINUATION",
            "The bicycle came back from its annual service.",
            "Does the rear brake still squeal on descents?",
            "The rear brake is silent even downhill.",
            "I booked a haircut for Sunday.",
            "What happened to the rear brake noise?",
        ),
        _continuation_spec(
            "repair-correction-residence",
            "CORRECTION_CONTINUATION",
            "I told the club that I moved to Suzhou.",
            "Should I update your residence note?",
            "Correction: I did not move to Suzhou; I still live in Wuxi.",
            "My keyboard needs a replacement cable.",
            "Where do I actually live?",
        ),
        _session_spec(
            "repair-session-orchid",
            "SESSION_BOUNDARY",
            "My orchid opened its first flower today.",
            "What color is the orchid flower?",
            "The deployment window starts at midnight.",
            "That release requires two approvals.",
            "When does the deployment window start?",
        ),
    ]


def _sealed_specs() -> list[dict[str, Any]]:
    over_merge = [
        (
            "sealed-cedar-clinic-trail",
            "The Cedar clinic scheduled my eye exam for Monday.",
            "Did the Cedar clinic confirm the appointment time?",
            "The Cedar hiking trail reopened after bridge repairs.",
            "That trail is now open from sunrise to dusk.",
            "Which hiking trail reopened after repairs?",
        ),
        (
            "sealed-atlas-bicycle-budget",
            "My Atlas bicycle received a new chain this week.",
            "Does the Atlas bicycle ride smoothly now?",
            "The Atlas budget spreadsheet is ready for review.",
            "The finance team will review that sheet tomorrow.",
            "Which budget spreadsheet is ready for review?",
        ),
        (
            "sealed-basil-garden-paint",
            "I planted basil in the balcony garden box.",
            "Is the basil growing well in that garden box?",
            "The basil-colored paint sample arrived for the kitchen.",
            "That sample looks too dark beside the cabinets.",
            "What paint sample arrived for the kitchen?",
        ),
        (
            "sealed-mira-violin-server",
            "Mira teaches my violin lesson every Thursday.",
            "Which piece did Mira assign for violin practice?",
            "Mira is the codename for our server migration.",
            "That migration begins after the nightly backup.",
            "What is the codename for the server migration?",
        ),
        (
            "sealed-orion-flight-projector",
            "The Orion flight departs at six tomorrow morning.",
            "Did Orion send a gate number for the flight?",
            "The Orion projector in the conference room stopped working.",
            "Facilities will replace that projector next week.",
            "Which projector stopped working?",
        ),
        (
            "sealed-amber-mug-dashboard",
            "My amber mug cracked beside the handle.",
            "Can the amber mug still hold hot tea safely?",
            "Amber status on the build dashboard means a warning.",
            "That warning appears when coverage drops below target.",
            "What does amber status mean on the dashboard?",
        ),
        (
            "sealed-harbor-dentist-library",
            "The Harbor dentist moved my cleaning to Wednesday.",
            "Did the Harbor dentist explain the schedule change?",
            "The Harbor branch of the library extended weekend hours.",
            "That branch now closes at eight on Saturday.",
            "Which library branch extended weekend hours?",
        ),
        (
            "sealed-nimbus-jacket-deploy",
            "My Nimbus jacket is being repaired at the zipper.",
            "When will the Nimbus jacket repair be finished?",
            "The Nimbus deployment passed its database migration check.",
            "That deployment can proceed to staging tonight.",
            "Which deployment passed the migration check?",
        ),
        (
            "sealed-maple-bakery-dataset",
            "The Maple bakery made the cake for our picnic.",
            "Did the Maple bakery include the lemon filling?",
            "The Maple dataset completed its checksum audit.",
            "That dataset has no missing archive files.",
            "Which dataset completed its checksum audit?",
        ),
        (
            "sealed-phoenix-gym-ticket",
            "I renewed my Phoenix gym membership for six months.",
            "Does the Phoenix gym membership include swimming classes?",
            "The Phoenix incident ticket is waiting for an owner.",
            "That ticket concerns a failed cache purge.",
            "Which incident ticket is waiting for an owner?",
        ),
        (
            "sealed-delta-train-report",
            "The Delta train arrives at the central station at nine.",
            "Is the Delta train usually punctual at that station?",
            "The Delta table in my report compares four methods.",
            "That table belongs in the results appendix.",
            "Which table compares four methods?",
        ),
        (
            "sealed-echo-headphones-script",
            "My Echo headphones now have fresh ear cushions.",
            "Do the Echo headphones feel more comfortable now?",
            "The Echo command in the maintenance script prints the run ID.",
            "That command executes before artifact validation.",
            "What does the Echo command print?",
        ),
    ]
    continuation = [
        (
            "sealed-piano-register",
            "A technician tuned my upright piano on Saturday.",
            "Did the middle register stop wavering during scales?",
            "The middle register sounds steady throughout every scale.",
            "My neighbor adopted a grey kitten yesterday.",
            "How does the middle register sound now?",
        ),
        (
            "sealed-cycle-rear-brake",
            "My touring cycle returned from the repair shop.",
            "Does the rear brake still squeal on steep descents?",
            "The rear brake stays silent even while going downhill.",
            "I ordered new curtains for the study.",
            "What happened to the rear brake noise?",
        ),
        (
            "sealed-soup-broth",
            "I changed the recipe for tonight's tomato soup.",
            "Is the broth less salty after the recipe change?",
            "The broth tastes balanced and mild this evening.",
            "My bus pass expires at the end of September.",
            "How does the broth taste after the change?",
        ),
        (
            "sealed-language-exercises",
            "I completed another lesson in my language course.",
            "Can you follow the spoken exercises more easily now?",
            "The spoken exercises feel much clearer and slower.",
            "The hallway lamp needs a brighter bulb.",
            "How do the spoken exercises feel now?",
        ),
        (
            "sealed-dog-night-cough",
            "The veterinarian changed my dog's medicine last week.",
            "Has the nighttime coughing stopped since the change?",
            "The nighttime coughing has disappeared completely.",
            "I reserved a table for my cousin's birthday.",
            "What happened to the nighttime coughing?",
        ),
        (
            "sealed-plant-new-leaves",
            "I moved the houseplant away from the cold window.",
            "Are the new leaves staying upright in that location?",
            "The new leaves remain firm and vertical all day.",
            "My passport renewal appointment is next Tuesday.",
            "How are the new leaves doing?",
        ),
    ]
    mixed = [
        _continuation_spec(
            "sealed-correction-portland",
            "MIXED_CORRECTION",
            "I said that my conference is in Portland, Maine.",
            "Should I save Portland, Maine as the venue?",
            "Correction: I meant Portland, Oregon for the conference.",
            "My desk chair delivery was delayed.",
            "Which Portland hosts the conference?",
        ),
        _continuation_spec(
            "sealed-correction-pickup",
            "MIXED_CORRECTION",
            "I planned to collect the parcel on Friday.",
            "Is Friday still the parcel pickup day?",
            "Actually, I meant Saturday for the parcel collection.",
            "The freezer thermometer needs a new battery.",
            "When will I collect the parcel?",
        ),
        _continuation_spec(
            "sealed-assistant-bridge-humidity",
            "MIXED_ASSISTANT_BRIDGE",
            "I moved the fern into the bathroom yesterday.",
            "Are the leaf tips improving with the higher humidity?",
            "The leaf tips look green instead of dry now.",
            "My tax folder is stored in the blue cabinet.",
            "How do the leaf tips look now?",
        ),
        _continuation_spec(
            "sealed-long-gap-oven",
            "MIXED_LONG_GAP_CONTINUATION",
            "A technician recalibrated my oven this morning.",
            "Does the internal thermometer reach the selected temperature?",
            "The internal thermometer now matches the selected temperature.",
            "I joined a weekend drawing workshop.",
            "Does the oven thermometer match the setting?",
            offsets=(0, 1, 24 * 60 + 1, 24 * 60 + 2),
        ),
        _session_spec(
            "sealed-session-river",
            "MIXED_SESSION_BOUNDARY",
            "The river path near my home reopened this morning.",
            "Is the river path open to bicycles again?",
            "The payroll export finished without warnings.",
            "That export contains all twelve departments.",
            "What finished without warnings?",
        ),
        _split_spec(
            "sealed-explicit-shift-pottery",
            "MIXED_EXPLICIT_SHIFT",
            "My reading group chose a history book for September.",
            "When will the reading group discuss that book?",
            "Changing topic, I enrolled in a pottery workshop.",
            "That workshop begins on the first Sunday.",
            "What workshop did I enroll in?",
            second_reason="EXPLICIT_TOPIC_SHIFT",
        ),
    ]
    return [
        *[
            _split_spec(
                case_id,
                "OVER_MERGE_PRESSURE",
                first,
                bridge,
                second,
                followup,
                query,
            )
            for case_id, first, bridge, second, followup, query in over_merge
        ],
        *[
            _continuation_spec(
                case_id,
                "CONTINUATION_PRESSURE",
                first,
                bridge,
                continuation_text,
                new_topic,
                query,
            )
            for case_id, first, bridge, continuation_text, new_topic, query in continuation
        ],
        *mixed,
    ]


def _base_spec(
    case_id: str,
    family: str,
    texts: tuple[str, str, str, str],
    episodes: list[dict[str, Any]],
    query: str,
    *,
    sessions: tuple[str, str, str, str] = ("s1", "s1", "s1", "s1"),
    offsets: tuple[int, int, int, int] = (0, 1, 2, 3),
) -> dict[str, Any]:
    return {
        "conversation_id": case_id,
        "families": [family],
        "texts": texts,
        "sessions": sessions,
        "offsets": offsets,
        "expected_episodes": episodes,
        "query": query,
    }


def _split_spec(
    case_id: str,
    family: str,
    first: str,
    bridge: str,
    second: str,
    followup: str,
    query: str,
    *,
    second_reason: str = "SEMANTIC_TOPIC_SHIFT",
) -> dict[str, Any]:
    return _base_spec(
        case_id,
        family,
        (first, bridge, second, followup),
        [
            {"turn_indexes": [0, 1], "boundary_reason": "CONVERSATION_START"},
            {"turn_indexes": [2, 3], "boundary_reason": second_reason},
        ],
        query,
    )


def _continuation_spec(
    case_id: str,
    family: str,
    first: str,
    bridge: str,
    continuation: str,
    new_topic: str,
    query: str,
    *,
    offsets: tuple[int, int, int, int] = (0, 1, 2, 3),
) -> dict[str, Any]:
    return _base_spec(
        case_id,
        family,
        (first, bridge, continuation, new_topic),
        [
            {"turn_indexes": [0, 1, 2], "boundary_reason": "CONVERSATION_START"},
            {"turn_indexes": [3], "boundary_reason": "SEMANTIC_TOPIC_SHIFT"},
        ],
        query,
        offsets=offsets,
    )


def _session_spec(
    case_id: str,
    family: str,
    first: str,
    bridge: str,
    second: str,
    followup: str,
    query: str,
) -> dict[str, Any]:
    return _base_spec(
        case_id,
        family,
        (first, bridge, second, followup),
        [
            {"turn_indexes": [0, 1], "boundary_reason": "CONVERSATION_START"},
            {"turn_indexes": [2, 3], "boundary_reason": "SESSION_CHANGE"},
        ],
        query,
        sessions=("s1", "s1", "s2", "s2"),
    )


def _fixture(specs: list[dict[str, Any]], *, split: str) -> dict[str, Any]:
    start = datetime(2026, 8, 1, 8, tzinfo=UTC)
    conversations: list[dict[str, Any]] = []
    for ordinal, spec in enumerate(specs, start=1):
        prefix = f"{'rd' if split == 'boundary-repair-dev' else 'sv'}{ordinal:02d}"
        turns = []
        for index, (text, session, offset) in enumerate(
            zip(spec["texts"], spec["sessions"], spec["offsets"], strict=True)
        ):
            evidence_id = f"{prefix}-t{index}"
            turns.append(
                {
                    "evidence_id": evidence_id,
                    "source_ref": f"memory://md02/{split}/{prefix}/turn/{index}",
                    "session_id": f"{prefix}-{session}",
                    "subject_id": f"{prefix}-{session}",
                    "speaker": "assistant" if index in {1, 3} else "user",
                    "speaker_source": "STRUCTURED_TURN_METADATA",
                    "observed_at": (
                        start + timedelta(days=ordinal, minutes=int(offset))
                    ).isoformat(),
                    "captured_at": (
                        start + timedelta(days=ordinal, minutes=int(offset), seconds=1)
                    ).isoformat(),
                    "content": text,
                    "content_hash": canonical_sha256(text),
                    "permission_snapshot": {"readable": True},
                    "retention_state": "READABLE",
                    "revoked_at": None,
                    "kind": "EVIDENCE_OBSERVATION",
                }
            )
        conversations.append(
            {
                "conversation_id": spec["conversation_id"],
                "counterexample_families": spec["families"],
                "turns": turns,
                "expected_episodes": spec["expected_episodes"],
                "memory_probes": [
                    {
                        "probe_id": f"{prefix}-p0",
                        "query_text": spec["query"],
                        "required_support_evidence_ids": [f"{prefix}-t2"],
                        "distractor_evidence_ids": [f"{prefix}-t0"],
                    }
                ],
            }
        )
    return {
        "schema": "milai.md02.boundary-shadow-validation.v0.1",
        "split": split,
        "formal_holdout": False,
        "annotation_policy": (
            "VISIBLE_GENERALIZED_REPAIR"
            if split == "boundary-repair-dev"
            else "SCORER_ONLY_AFTER_PREDICTION_SEAL"
        ),
        "conversations": conversations,
    }


def _freshness_contract() -> dict[str, Any]:
    return {
        "schema": "milai.md02.freshness-contract.v0.1",
        "formal_holdout": False,
        "scenarios": [
            {
                "scenario": "UNCHANGED_SNAPSHOT",
                "expected_freshness_status": "CURRENT",
                "expected_disposition": "OBSERVED",
                "raw_fallback_expected": False,
            },
            {
                "scenario": "APPENDED_EVIDENCE",
                "expected_freshness_status": "STALE",
                "expected_disposition": "STALE_REJECTED",
                "raw_fallback_expected": True,
            },
            {
                "scenario": "REVOKED_EVIDENCE",
                "expected_freshness_status": "INELIGIBLE",
                "expected_disposition": "PERMISSION_REJECTED",
                "raw_fallback_expected": True,
            },
            {
                "scenario": "PERMISSION_REMOVED",
                "expected_freshness_status": "INELIGIBLE",
                "expected_disposition": "PERMISSION_REJECTED",
                "raw_fallback_expected": True,
            },
            {
                "scenario": "RETENTION_UNREADABLE",
                "expected_freshness_status": "INELIGIBLE",
                "expected_disposition": "PERMISSION_REJECTED",
                "raw_fallback_expected": True,
            },
            {
                "scenario": "FORMATION_FAILURE_RAW_FALLBACK",
                "expected_freshness_status": "INELIGIBLE",
                "expected_disposition": "RAW_FALLBACK",
                "raw_fallback_expected": True,
            },
        ],
    }


def _identity(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _summary(fixture: dict[str, Any], path: Path) -> dict[str, Any]:
    conversations = fixture["conversations"]
    families = Counter(
        family for conversation in conversations for family in conversation["counterexample_families"]
    )
    return {
        **_identity(path),
        "conversation_count": len(conversations),
        "turn_count": sum(len(item["turns"]) for item in conversations),
        "probe_count": sum(len(item["memory_probes"]) for item in conversations),
        "episode_count": sum(len(item["expected_episodes"]) for item in conversations),
        "family_counts": dict(sorted(families.items())),
        "formal_holdout": False,
    }


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)


def main() -> None:
    for path in (REPAIR, SEALED, FRESHNESS, RUN_LOCK):
        if path.exists():
            raise RuntimeError(f"MD02_SEAL_TARGET_EXISTS:{path}")
    if any(path.exists() for path in (EVALUATOR, BOUNDARY_V02, SHADOW_HOOK)):
        raise RuntimeError("MD02_TREATMENT_OR_SCORER_PRESENT_BEFORE_LABEL_SEAL")
    predecessor = json.loads(PREDECESSOR.read_text(encoding="utf-8"))
    if predecessor.get("status") != "PASS_MF02_SEMANTIC_EPISODE_GENERALIZATION":
        raise RuntimeError("MD02_PREDECESSOR_NOT_PASS")

    repair = _fixture(_repair_specs(), split="boundary-repair-dev")
    sealed = _fixture(_sealed_specs(), split="shadow-validation")
    freshness = _freshness_contract()
    _write_exclusive(REPAIR, repair)
    _write_exclusive(SEALED, sealed)
    _write_exclusive(FRESHNESS, freshness)

    run_lock: dict[str, Any] = {
        "schema": "milai.md02.run-lock.v0.1",
        "run_id": RUN_ID,
        "sealed_at": datetime.now(UTC).isoformat(),
        "execution_authority": "USER_EXPLICIT_20260830_MD02_EXECUTE",
        "predecessor_terminal": _identity(PREDECESSOR),
        "fixtures": {
            "boundary_repair_dev": _summary(repair, REPAIR),
            "shadow_validation": _summary(sealed, SEALED),
            "freshness_contract": _identity(FRESHNESS),
        },
        "frozen_v01_builder": _identity(V01_BUILDER),
        "official_read_path": [
            _identity(ROOT / "runtime/src/milai/application/acquisition.py"),
            _identity(ROOT / "runtime/src/milai/application/evidence_acquisition.py"),
            _identity(ROOT / "runtime/src/milai/application/query_planner.py"),
            _identity(ROOT / "runtime/src/milai/application/memory_context.py"),
        ],
        "scorer_present_at_label_seal": False,
        "boundary_v02_present_at_label_seal": False,
        "shadow_hook_present_at_label_seal": False,
        "protocol": {
            "boundary_effect_attempts": 1,
            "shadow_effect_attempts": 1,
            "bootstrap": {
                "seed": 20260830,
                "resamples": 2000,
                "confidence": 0.95,
                "unit": "conversation",
            },
            "raw_turn_ceilings": list(range(1, 9)),
            "official_ranking": "milai.application.acquisition.rank_evidence_turns",
            "formation_build_query_independent": True,
            "shadow_reuses_official_anchors": True,
            "additional_shadow_acquisition_calls": 0,
            "sealed_labels_visible_after_prediction_seal_only": True,
            "mf02_historical_replay_in_main_denominator": False,
        },
        "thresholds": {
            "over_merge_pair_rate_absolute_reduction_min": 0.05,
            "over_merge_pair_rate_delta_bootstrap_lower_gt": 0.0,
            "over_split_pair_rate_increase_max": 0.02,
            "episode_pairwise_f1_delta_min": -0.02,
            "support_closure_auc_delta_min": -0.02,
            "baseline_behavior_identity_rate": 1.0,
            "shadow_build_success_rate": 1.0,
            "shadow_deterministic_replay_rate": 1.0,
            "fresh_bundle_acceptance_rate": 1.0,
            "stale_bundle_rejection_rate": 1.0,
            "ineligible_bundle_rejection_rate": 1.0,
            "revoked_evidence_leak_rate": 0.0,
            "permission_leak_rate": 0.0,
            "raw_fallback_rate": 1.0,
            "additional_official_acquisition_calls": 0,
            "additional_reader_provider_model_calls": 0,
            "canonical_mutations": 0,
            "database_writes": 0,
        },
        "scope": {
            "gpu_hours": 0,
            "formal_holdout_used": False,
            "experimental_feature_flags_default": "OFF",
            "public_mcp_changed": False,
            "schema_changed": False,
            "database_accessed": False,
            "canonical": False,
        },
    }
    run_lock["run_lock_digest"] = canonical_sha256(run_lock)
    _write_exclusive(RUN_LOCK, run_lock)
    print(
        json.dumps(
            {
                "run_id": RUN_ID,
                "run_lock_digest": run_lock["run_lock_digest"],
                "repair": run_lock["fixtures"]["boundary_repair_dev"],
                "sealed": run_lock["fixtures"]["shadow_validation"],
                "freshness": run_lock["fixtures"]["freshness_contract"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
