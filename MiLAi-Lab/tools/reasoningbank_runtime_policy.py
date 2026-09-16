"""Declared policy variants and factual native action budgets for research runners."""

from __future__ import annotations

import json
from pathlib import Path

from milai_lab.methods.evidence_utility_session import EvidenceUtilitySession
from milai_lab.methods.experience_revision import ExperienceRevisionSession


def candidate_session_class(config: dict) -> type[ExperienceRevisionSession]:
    return (
        EvidenceUtilitySession
        if config.get("candidate_policy") == "evidence_utility"
        else ExperienceRevisionSession
    )


def action_budget(limit: int, used: int, *, unit: str, final_uses_slot: bool = True) -> dict:
    if type(limit) is not int or type(used) is not int or limit < 1 or used < 0:
        raise ValueError("INVALID_NATIVE_ACTION_BUDGET")
    return {
        "limit": limit,
        "used": used,
        "remaining": max(0, limit - used),
        "unit": unit,
        "final_uses_slot": final_uses_slot,
    }


def actor_runtime_context(lab: Path, config: dict, budget: dict) -> str:
    parts = []
    travel_policy = config.get("travel_execution_policy", "native")
    if travel_policy not in {"native", "facts_and_tools_v1"}:
        raise ValueError("UNKNOWN_TRAVEL_EXECUTION_POLICY")
    if travel_policy == "facts_and_tools_v1":
        if config.get("domain") != "travel":
            raise ValueError("TRAVEL_EXECUTION_POLICY_DOMAIN_MISMATCH")
        parts.append((lab / "configs/policies/native_travel/facts_and_tools.txt").read_text())
    if config.get("action_budget_context", False):
        parts.append("Current native action budget: " + json.dumps(budget))
        parts.append(
            "Memory/maintenance calls do not replenish native action opportunities. "
            "The native tool and final-response rules remain binding."
        )
        if budget["remaining"] == 0:
            parts.append(
                "No native opportunity remains; further commands or answers cannot be processed."
            )
    if config.get("action_aware_policy", False):
        parts.append((lab / "configs/policies/experience_revision/action_aware.txt").read_text())
    return "\n\n".join(parts)


def load_memory_policies(lab: Path, config: dict) -> dict[str, str]:
    if config["method"] == "MEMRL_LLB_PORT_v0.1":
        if config.get("feedback_regime") != "R" or config.get("domain") not in {
            "db_bench",
            "os_interaction",
        }:
            raise ValueError("MEMRL_REQUIRES_DB_OS_R")
        return {p.stem: p.read_text() for p in (lab / "configs/policies/memrl").glob("*.txt")}
    policies = {
        p.stem: p.read_text() for p in (lab / "configs/policies/reasoning_bank").glob("*.txt")
    }
    if config["method"] == "MILAI_EXPERIENCE_REVISION":
        profile = config.get("candidate_policy", "original")
        if profile not in {"original", "optimized", "evidence_utility"}:
            raise ValueError("UNKNOWN_CANDIDATE_POLICY")
        if profile == "evidence_utility":
            if not config.get("post_task_revision", False):
                raise ValueError("UTILITY_CANDIDATE_REQUIRES_POST_TASK_REVISION")
            regime = config.get("feedback_regime", "H")
            if regime not in {"H", "R"} or (config.get("domain") == "travel" and regime != "H"):
                raise ValueError("UNKNOWN_OR_UNSUPPORTED_FEEDBACK_REGIME")
            for path in (lab / "configs/policies/experience_revision/v07").glob("*.txt"):
                policies[path.stem] = path.read_text()
            policies["utility_contract"] = json.dumps(
                {"feedback_regime": regime, "selector_version": "A1-evidence-utility-v1"},
                sort_keys=True,
            )
            return policies
        if profile == "optimized":
            for key in ("consume", "revision_actor", "revision_controller"):
                policies[key] = (
                    lab / f"configs/policies/experience_revision/{key}.txt"
                ).read_text()
        if config.get("post_task_revision", False):
            for key in ("extract_success", "extract_failure"):
                policies[key] = (
                    lab / f"configs/policies/experience_revision/{key}.txt"
                ).read_text()
    return policies
