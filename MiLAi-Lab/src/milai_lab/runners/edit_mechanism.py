"""Native diagnostics, complete-answer audits and controlled source histories.

Native diagnostics never edit the original banks; historical snapshots are loaded
after the paired development arms complete. Controlled histories delegate actual
formation to the unchanged benchmark Writer, without reviews/questions as input.
Reader probes use the existing MemoryService and unchanged benchmark Reader.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from langgraph.store.sqlite import SqliteStore
from pydantic import BaseModel, ValidationError

from milai_lab.analysis.edit_mechanism import (
    ANSWER_PROMPT,
    DELTA_PROMPT,
    TRANSITION_PROMPT,
    VARIANTS,
    AnswerAssessment,
    DeltaAssessment,
    TransitionAssessment,
    blinded_states,
    controls,
    delta_judge_view,
    summarize_controlled,
    summarize_drift,
    summarize_native,
    summarize_three_views,
    validate_delta,
    validate_transition,
)
from milai_lab.analysis.edit_results import ratio, receipt_effect, scoring_terminal
from milai_lab.datasets.edit_benchmarks import (
    ObservedSession,
    longmemeval_cases,
    longmemeval_history,
)
from milai_lab.harness.artifact_io import read_json, write_json
from milai_lab.memory.edit_units import render_state
from milai_lab.memory.functional_state import body_text
from milai_lab.memory.service import MemoryService
from milai_lab.runners.edit_benchmarks import BenchmarkRun, parse_object

T = TypeVar("T", bound=BaseModel)


def require_completed_suite(root: Path, arms: list[str], *, v2: bool = False) -> None:
    for arm in arms:
        terminal = scoring_terminal(root / arm)
        if not terminal.exists() or read_json(terminal)["status"] != "COMPLETED_EXPERIMENT_PHASE":
            raise ValueError("Complete every paired development arm before mechanism scoring")
        if v2 and read_json(root / arm / "actual-config.json").get(
            "interface_version", "v1"
        ) == "v1":
            raise ValueError("v2 assessment requires each arm's own v2 cohort")


def require_completed_external(root: Path, arms: list[str]) -> None:
    for arm in arms:
        terminal = scoring_terminal(root / arm)
        if not terminal.exists() or read_json(terminal)["status"] != "COMPLETED_EXTERNAL_PHASE":
            raise ValueError("Complete every external arm before the full-answer audit")


def full_answer_payload(case: dict[str, Any], hypothesis: str) -> dict[str, Any]:
    """Evaluator-only original complete histories; no selected evidence substitute."""
    if not isinstance(hypothesis, str):
        raise ValueError("Full-answer audit requires a complete textual answer")
    history = longmemeval_history(case)
    return {
        "question": case["question"],
        "question_date": case["question_date"],
        "reference_answer": case["answer"],
        "answer": hypothesis,
        "full_observed_history": [
            {"session_id": s.session_id, "date": s.date, "dialogue": s.turns} for s in history
        ],
        "full_history_sessions": len(history),
        "source_condition": "full original history, chronological; no method identity",
    }


def controlled_events(case: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    if variant not in case["variants"]:
        raise ValueError("Unregistered controlled variant")
    events = list(case["events"])
    if variant == "en_independent_swap":
        pair = case.get("independent_order_pair", [])
        if len(pair) != 2 or pair[0] == pair[1] or not case.get("independence_rationale"):
            raise ValueError("An order swap requires a declared independent pair")
        ids = [event["event_id"] for event in events]
        first, second = (ids.index(identity) for identity in pair)
        if first == 0 or abs(first - second) != 1:
            raise ValueError("Only the declared adjacent independent updates can be swapped")
        events[first], events[second] = events[second], events[first]
    return events


def controlled_observations(case: dict[str, Any], variant: str) -> tuple[ObservedSession, ...]:
    """Writer input contains only actually observed authored speech, roles and dates."""
    wording = "en" if variant == "en_independent_swap" else variant
    return tuple(
        ObservedSession(
            session_id=f"controlled:{case['source_cluster']}:{variant}:{event['event_id']}",
            date=f"2030-01-{step + 1:02d}",
            turns=tuple(
                {
                    "role": turn["role"],
                    "content": turn["content"],
                    "timestamp": f"2030-01-{step + 1:02d}",
                }
                for turn in event["wordings"][wording]
            ),
        )
        for step, event in enumerate(controlled_events(case, variant))
    )


def observed_timestamp_lookup(
    history: tuple[ObservedSession, ...],
) -> Callable[[dict[str, Any]], str | None]:
    dates = {s.session_id: s.date for s in history}
    return lambda source: dates.get(source["session"])


def require_frozen_candidate(settings: dict[str, Any], candidate: Path) -> None:
    frozen = read_json(candidate)
    if frozen.get("status") != "FROZEN_CANDIDATE":
        raise ValueError("Fix the final candidate before confirmation and sensitivity runs")
    if frozen.get("method_version") != settings["method_version"]:
        raise ValueError("Sensitivity configuration differs from the frozen candidate version")
    if frozen.get("config_version") != settings["config_version"]:
        raise ValueError("Sensitivity Writer configuration differs from the frozen candidate")


def snapshots(
    root: Path, arm: str, owner: str, session: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    folder = root / arm / "maintenance" / "halumem" / owner / str(session)
    if not (folder / "complete.json").exists():
        raise ValueError("Actual source opportunity has not completed")
    complete = read_json(folder / "complete.json")
    recipe_batches = complete.get("batches")
    if recipe_batches is not None:
        if not recipe_batches:
            raise ValueError("Actual before/after transition snapshot missing")
        before = read_json(folder / "batch-0-before.json")
        after = read_json(folder / f"batch-{len(recipe_batches) - 1}-after.json")
        receipts = complete["receipts"]
        batch_count = len(recipe_batches)
        writer_failures = sum(
            any(gap.get("phase") in {"locate", "edit", "edit_pending"}
                for gap in batch["unprocessed"])
            for batch in recipe_batches
        )
    else:
        batches = sorted(path for path in folder.glob("batch-*") if path.is_dir())
        if not batches or any(not (b / "after.json").exists() for b in batches):
            raise ValueError("Actual before/after transition snapshot missing")
        before = read_json(batches[0] / "before.json")
        after = read_json(batches[-1] / "after.json")
        receipts = [r for b in batches for r in read_json(b / "complete.json")["receipts"]]
        batch_count = len(batches)
        writer_failures = sum((b / "writer-failure.json").exists() for b in batches)
    effects = [receipt_effect(receipt) for receipt in receipts]
    return (
        before,
        after,
        {
            "actual_source_batches": batch_count,
            "proposals": len(receipts),
            "committed_receipts": effects.count("committed"),
            "original_commits_confirmed_by_replay": effects.count("replayed_commit"),
            "accepted_no_change_receipts": effects.count("no_change"),
            "rejected_receipts": effects.count("rejected"),
            "other_or_unconfirmed_receipts": effects.count("other_or_unconfirmed"),
            "writer_failures": writer_failures,
            **({"incomplete_maintenance_batches": sum(
                batch["status"] != "completed" for batch in recipe_batches
            )} if recipe_batches is not None else {}),
            "after_record_count": len(after),
        },
    )


def prior_evidence(
    root: Path, arm: str, owner: str, before: list[dict[str, Any]], *,
    record_names: dict[str, str] | None = None, label_prefix: str = "old_source",
) -> list[Any]:
    """Fetch only ranges cited by the actual OLD state, never future-bank records."""
    config = read_json(root / arm / "actual-config.json")
    bank = root / arm / "banks" / owner
    with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
        service = MemoryService(
            store, ("edit", (root / arm).name, config["arm"], owner), owner, bank / "memory.lock"
        )
        result = grounded_ranges(
            service,
            before,
            timestamp_lookup=lambda source: original_timestamp(root, arm, owner, source),
            bind_records=config.get("interface_version", "v1") != "v1",
            record_names=record_names, label_prefix=label_prefix,
        )
    return result


def original_timestamp(root: Path, arm: str, owner: str, source: dict[str, Any]) -> str | None:
    """Use the captured original time, or its saved delivery in historical runs."""
    if source.get("occurred_at") is not None:
        return str(source["occurred_at"])
    prefix = "halumem:" + owner + ":session:"
    if not source["session"].startswith(prefix):
        return None
    ordinal = int(source["session"][len(prefix) :])
    folder = root / arm / "maintenance" / "halumem" / owner / str(ordinal)
    dates = {
        item["timestamp"]
        for path in folder.glob("batch-*/delivery.json")
        for item in read_json(path)["sources"]
        if item["source_ref"] == source["event_id"]
    }
    if len(dates) > 1:
        raise ValueError("Original source timestamp differs across actual delivered ranges")
    return next(iter(dates), None)


def grounded_ranges(
    service: MemoryService,
    before: list[dict[str, Any]],
    *,
    timestamp_lookup: Callable[[dict[str, Any]], str | None] | None = None,
    bind_records: bool = False,
    record_names: dict[str, str] | None = None,
    label_prefix: str = "old_source",
) -> list[Any]:
    """Deliver only evidence already cited by the actual state, with opaque labels."""
    result: list[Any] = []
    seen: dict[tuple[Any, ...], int] = {}
    names = record_names or {
        key: f"record_{i}" for i, key in enumerate(dict.fromkeys(row["id"] for row in before))
    }
    for row in before:
        if not row.get("ok"):
            continue
        state = row["value"].get("edit_state") or {}
        units = {u["unit_id"]: u for u in state.get("units", [])}
        for item in [*state.get("units", []), *state.get("relations", [])]:
            binding = {"record_id": names[row["id"]]}
            if "text" in item:
                binding.update({"text": item["text"], "role": item["role"]})
            else:
                binding.update({
                    "relation_type": item["relation_type"],
                    "source_text": units[item["source_unit"]]["text"],
                    "target_text": units[item["target_unit"]]["text"],
                })
            for ref in item.get("evidence_refs", []):
                identity = tuple(ref[k] for k in ("source_ref", "source_revision", "start", "end"))
                if identity in seen:
                    if bind_records and binding not in result[seen[identity]]["cited_by"]:
                        result[seen[identity]]["cited_by"].append(copy.deepcopy(binding))
                    continue
                seen[identity] = len(result)
                source = service.source(ref["source_ref"])
                body = body_text(source) if source is not None else ""
                if (
                    source is None or source["source_revision"] != ref["source_revision"]
                    or not 0 <= ref["start"] < ref["end"] <= len(body)
                ):
                    result.append(
                        {
                            "source_id": label_prefix + "_" + str(len(result)),
                            "status": "UNKNOWN",
                            "body_delivered": False,
                            "reason": "actual old-state source binding unavailable",
                        }
                    )
                    if bind_records:
                        result[-1]["cited_by"] = [copy.deepcopy(binding)]
                    continue
                result.append(
                    {
                        "source_id": label_prefix + "_" + str(len(result)),
                        "source_revision": ref["source_revision"],
                        "start": ref["start"],
                        "end": ref["end"],
                        "role": source["role"],
                        "original_timestamp": timestamp_lookup(source)
                        if timestamp_lookup
                        else None,
                        "text": body[ref["start"] : ref["end"]],
                    }
                )
                if bind_records:
                    result[-1]["cited_by"] = [copy.deepcopy(binding)]
    return result


def restore_current(
    service: MemoryService, rows: list[dict[str, Any]], *,
    original_ids: dict[str, str] | None = None,
) -> None:
    """Materialize exact own-formed current values solely for historical Reader probes."""
    restored = {}
    for row in rows:
        if not row.get("ok"):
            continue
        value = copy.deepcopy(row["value"])
        if original_ids is None:
            raw = {
                "content": value["content"],
                "_v13_1": {
                    "revision": value["revision"],
                    "current": value,
                    "history": [value],
                    "proposals": {},
                    "owner": service.owner,
                },
            }
        else:
            item = service.store.get(service.namespace, original_ids[row["id"]])
            if item is None:
                raise ValueError("Historical Reader record missing from its actual bank")
            raw = copy.deepcopy(item.value)
            metadata = raw["_v13_1"]
            if value not in metadata["history"]:
                raise ValueError("Historical Reader value differs from its actual saved revision")
            metadata["history"] = [
                version for version in metadata["history"]
                if version["revision"] <= value["revision"]
            ]
            metadata["current"] = value
            metadata["revision"] = value["revision"]
            metadata["proposals"] = {
                key: proposal for key, proposal in metadata["proposals"].items()
                if proposal["receipt"].get("revision", 0) <= value["revision"]
            }
            raw["content"] = value["content"]
        restored[row["id"]] = raw
    # Capture original rows before deleting: RetainAll explicitly copies an old
    # version under a control ID, while its original record may be absent now.
    old = {item.key for item in service.store.search(service.namespace, limit=100000)}
    for key in old - restored.keys():
        service.store.delete(service.namespace, key)
    for identity, raw in restored.items():
        service.store.put(service.namespace, identity, raw, index=False)
    if original_ids is not None:
        revisions = {identity: raw["_v13_1"]["revision"] for identity, raw in restored.items()}
        # Grants for future or absent records belong to the original trajectory,
        # not this independent Reader state. Preserve actual past grants.
        for candidate in service._rows(service.candidates_namespace):
            bound = candidate["value"]
            if bound["record_id"] not in revisions or (
                bound["revision"] > revisions[bound["record_id"]]
            ):
                service.store.delete(service.candidates_namespace, candidate["id"])


class MechanismRun(BenchmarkRun):
    def assess(
        self, key: str, prompt: str, payload: dict[str, Any], schema: type[T]
    ) -> dict[str, Any]:
        try:
            output_schema = schema.model_json_schema()
            response = self.call(
                key,
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {**payload, "response_schema": output_schema},
                            ensure_ascii=False,
                        ),
                    },
                ],
                structured=True,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": output_schema},
                } if self.settings.get("interface_version", "v1") != "v1" else None,
            )
            judgment = schema.model_validate(parse_object(response))
            return {"status": "VALID", "judgment": judgment.model_dump()}
        except (ValueError, ValidationError) as error:
            return {
                "status": "INVALID_FIRST_ATTEMPT",
                "error_type": type(error).__name__,
                "error": str(error),
                "additional_attempts": 0,
            }

    def probe(
        self, owner: str, state: list[dict[str, Any]], question: str, date: str, key: str, *,
        source_bank: Path | None = None, source_namespace: tuple[str, ...] | None = None,
        retained_ids: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        bank = self.root / "reader-state" / key
        bank.mkdir(parents=True, exist_ok=True)
        try:
            if source_bank is not None:
                if source_namespace is None:
                    raise ValueError("Historical Reader requires its original bank namespace")
                # Issued fragments bind the original logical bank. A read-only
                # backup preserves that qualification without issuing new evidence.
                with (
                    sqlite3.connect(
                        source_bank.resolve().as_uri() + "?mode=ro", uri=True
                    ) as source,
                    sqlite3.connect(bank / "memory.sqlite") as destination,
                ):
                    source.backup(destination)
            with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                service = MemoryService(
                    store, source_namespace or ("edit", "mechanism", owner),
                    owner, bank / "memory.lock",
                    semantic_retriever=self._semantic_retriever(),
                    memory_profile=self.settings.get("memory_profile", "ordinary"),
                    memory_ranking=self.settings.get("memory_ranking", "dense"),
                )
                restore_current(service, state, original_ids={
                    row["id"]: (retained_ids or {}).get(row["id"], row["id"])
                    for row in state if row.get("ok")
                } if source_bank is not None else None)
                answer = self.answer(service, question, date, key + "/reader")
            return {"status": "ANSWERED", "answer": answer}
        except ValueError as error:
            return {
                "status": "FAILED_FIRST_ATTEMPT",
                "error_type": type(error).__name__,
                "error": str(error),
                "answer": None,
                "additional_attempts": 0,
            }

    def run_native(self, suite: Path, selection: Path, review: Path) -> dict[str, Any]:
        arms = self.settings["mechanism"]["arms"]
        v2 = self.settings.get("interface_version", "v1") != "v1"
        require_completed_suite(suite, arms, v2=v2)
        selected, labels = read_json(selection), read_json(review)
        cases = selected["selected"]
        if len(cases) != len(labels["reviews"]) or labels["selection_count"] != len(cases):
            raise ValueError("Source selection and semantic review disagree")
        results = []
        for index, (case, label) in enumerate(zip(cases, labels["reviews"], strict=True)):
            if any(case[k] != label[k] for k in ("uuid", "session", "memory_ordinal")):
                raise ValueError("Source review identity mismatch")
            for arm in arms:
                before, after, availability = snapshots(suite, arm, case["uuid"], case["session"])
                old_sources = prior_evidence(suite, arm, case["uuid"], before)
                actual_config = read_json(suite / arm / "actual-config.json")
                for variant in VARIANTS:
                    key = f"native/{index:03d}/{arm}/{variant}"
                    done = self.root / key / "complete.json"
                    if done.exists():
                        saved = read_json(done)
                        if (
                            v2 and saved.get("r4_protocol_version")
                            != "milai-edit-r4-three-views-v2"
                        ):
                            raise ValueError("Existing native checkpoint has another protocol")
                        results.append(saved)
                        continue
                    state = controls(before, after, variant)
                    first, second = blinded_states(before, state, renderer=render_state)
                    source_review = {
                        k: label[k]
                        for k in (
                            "classification",
                            "source_supported_requirement",
                            "guard_against_unsupported_change",
                            "cancellation",
                            "uncertainty",
                        )
                    }
                    source_review["role_conflict"] = label.get("role_conflict")
                    payload = {
                        "observed_dialogue": case["observed_dialogue"],
                        "source_review": source_review,
                        "prior_source_ranges": old_sources,
                        "before": first,
                        "after": second,
                    }
                    transition = self.assess(
                        key + "/transition-judge", TRANSITION_PROMPT, payload, TransitionAssessment
                    )
                    transition = validate_transition(
                        transition, first, second, cancellation=label["cancellation"],
                        prior_sources=old_sources if v2 else None,
                    )
                    supplemental = {}
                    if v2 and variant == "Actual":
                        location = (
                            suite / arm / "maintenance/halumem" / case["uuid"]
                            / str(case["session"])
                        )
                        receipts = read_json(location / "complete.json")["receipts"]
                        delta = delta_judge_view(before, state, receipts)
                        aliases = {
                            row["id"]: view["record_id"]
                            for row, view in zip(
                                [r for r in [*before, *state] if r.get("ok")],
                                [*first, *second], strict=True,
                            )
                        }
                        affected = {d["record_id"] for d in delta["net_session_delta"]}
                        cited_after = prior_evidence(
                            suite, arm, case["uuid"],
                            [r for r in state if r.get("ok") and aliases[r["id"]] in affected],
                            record_names=aliases, label_prefix="delta_cited_source",
                        )
                        delta_assessment = (
                            self.assess(
                                key + "/delta-judge", DELTA_PROMPT,
                                {"observed_dialogue": case["observed_dialogue"],
                                 "source_review": source_review, "delta_view": delta,
                                 "prior_source_ranges": old_sources,
                                 "actual_after_cited_ranges": cited_after},
                                DeltaAssessment,
                            ) if delta["has_evaluable_delta"] else
                            {"status": "NO_EVALUABLE_DELTA", "additional_model_calls": 0}
                        )
                        supplemental = {
                            "delta_view": delta,
                            "delta_assessment": validate_delta(delta_assessment, delta),
                            "actual_after_cited_ranges": cited_after,
                        }
                    probe = self.probe(
                        case["uuid"], state, label["diagnostic_question"], case["date"], key,
                        source_bank=suite / arm / "banks" / case["uuid"] / "memory.sqlite",
                        source_namespace=("edit", arm, actual_config["arm"], case["uuid"]),
                        retained_ids={
                            "retained:" + row["id"] + ":revision:" + str(row["value"]["revision"]):
                            row["id"] for row in before if row.get("ok")
                        } if variant == "RetainAll" else None,
                    )
                    answer = (
                        self.assess(
                            key + "/answer-judge",
                            ANSWER_PROMPT,
                            {
                                "question": label["diagnostic_question"],
                                "question_date": case["date"],
                                "observed_dialogue": case["observed_dialogue"],
                                "source_review": source_review,
                                "prior_source_ranges": old_sources,
                                "answer": probe["answer"],
                            },
                            AnswerAssessment,
                        )
                        if probe["status"] == "ANSWERED"
                        else {"status": "ANSWER_UNAVAILABLE"}
                    )
                    result = {
                        "selection_index": index,
                        "uuid": case["uuid"],
                        "session": case["session"],
                        "memory_ordinal": case["memory_ordinal"],
                        "arm": arm,
                        "variant": variant,
                        "classification": label["classification"],
                        "cancellation_opportunity": label["cancellation"],
                        "availability": availability,
                        "before_actual_record_count": len(before),
                        "after_control_record_count": len(state),
                        "transition": transition,
                        "reader_probe": probe,
                        "answer_assessment": answer,
                        "gold_initialization": False,
                        "additional_editor_calls": 0,
                        **supplemental,
                    }
                    if v2:
                        result["r4_protocol_version"] = "milai-edit-r4-three-views-v2"
                    write_json(done, result)
                    results.append(result)
        report = summarize_native(results, arms)
        write_json(self.root / "native-mechanism-results.json", report)
        if v2:
            author_scores = {}
            for arm in arms:
                original = read_json(suite / arm / "halumem-official-results.json")
                author_scores[arm] = {
                    "official_score": original["overall_score"],
                    "supplemental_denominators": original["supplemental_denominators"],
                }
            tables = summarize_three_views(
                results, arms, report["metrics"], author_scores,
            )
            write_json(self.root / "r4-three-view-results.json", tables)
        return report

    def run_long_audit(self, suite: Path, manifest: Path) -> dict[str, Any]:
        arms = self.settings["answer_audit"]["arms"]
        require_completed_external(suite, arms)
        selected = read_json(manifest)["complete_answer_audit"]
        cases = longmemeval_cases(Path(self.settings["longmemeval"]["path"]), selected)
        outputs = {}
        for arm in arms:
            config = read_json(suite / arm / "actual-config.json")
            if not set(selected) <= set(config["longmemeval"]["questions"]):
                raise ValueError("Preselected audit question was not part of the external run")
            outputs[arm] = {
                r["question_id"]: r for r in read_json(suite / arm / "longmemeval-predictions.json")
            }
            if not set(selected) <= outputs[arm].keys():
                raise ValueError("Complete original external hypotheses unavailable")
        rows = []
        for case in cases:
            for arm in arms:
                key = f"full-answer/{case['question_id']}/{arm}"
                done = self.root / key / "complete.json"
                if done.exists():
                    rows.append(read_json(done))
                    continue
                prediction = outputs[arm][case["question_id"]]
                payload = full_answer_payload(case, prediction["hypothesis"])
                assessment = self.assess(key + "/judge", ANSWER_PROMPT, payload, AnswerAssessment)
                row = {
                    "question_id": case["question_id"],
                    "question_type": case["question_type"],
                    "arm": arm,
                    "original_hypothesis": prediction["hypothesis"],
                    "official_label_unchanged": prediction["autoeval_label"],
                    "full_history_sessions": payload["full_history_sessions"],
                    "assessment": assessment,
                    "additional_reader_or_editor_calls": 0,
                }
                write_json(done, row)
                rows.append(row)
        report: dict[str, Any] = {
            "status": "COMPLETED_FULL_ANSWER_AUDIT",
            "preselected_questions": len(selected),
            "source_clusters": 1,
            "interval": None,
            "judge": "Qwen3.6 only, not independent",
            "method_score_replacement": False,
            "metrics": {},
            "records": rows,
        }
        for arm in arms:
            chosen = [r for r in rows if r["arm"] == arm]
            valid = [r for r in chosen if r["assessment"]["status"] == "VALID"]
            report["metrics"][arm] = {
                "opportunities": len(chosen),
                "valid_judgments": len(valid),
                "full_answer_supported_all": ratio(
                    sum(r["assessment"]["judgment"]["complete_and_supported"] for r in valid),
                    len(chosen),
                ),
                "full_answer_correct_and_supported_all": ratio(
                    sum(
                        r["assessment"]["judgment"]["requirement_correct"]
                        and r["assessment"]["judgment"]["complete_and_supported"]
                        for r in valid
                    ),
                    len(chosen),
                ),
                "unsupported_explanation_answers_valid": sum(
                    bool(r["assessment"]["judgment"]["unsupported_explanations"]) for r in valid
                ),
                "conflicting_answers_valid": sum(
                    bool(r["assessment"]["judgment"]["current_conflicts"]) for r in valid
                ),
            }
        write_json(self.root / "full-answer-audit-results.json", report)
        return report

    def run_drift(self, suite: Path) -> dict[str, Any]:
        arms = self.settings["drift"]["arms"]
        require_completed_suite(
            suite, arms, v2=self.settings.get("interface_version", "v1") != "v1"
        )
        rows = []
        for arm in arms:
            config = read_json(suite / arm / "actual-config.json")
            for owner in config["halumem"]["users"]:
                order = read_json(suite / arm / "banks" / owner / "session-order.json")
                for step, ordinal in enumerate(order["original_ordinals"]):
                    key = f"drift/{arm}/{owner}/{ordinal}"
                    done = self.root / key / "complete.json"
                    if done.exists():
                        rows.append(read_json(done))
                        continue
                    maintenance = suite / arm / "maintenance" / "halumem" / owner / str(ordinal)
                    if config.get("maintenance_recipe"):
                        complete = read_json(maintenance / "complete.json")
                        source_refs = list(dict.fromkeys(
                            ref for batch in complete["batches"] for ref in batch["source_refs"]
                        ))
                        empty_source = not source_refs
                    else:
                        coverage = read_json(maintenance / "source-coverage.json")
                        source_refs = coverage["source_refs"]
                        empty_source = coverage["original_characters"] == 0
                    if empty_source:
                        row = {
                            "arm": arm,
                            "uuid": owner,
                            "session": ordinal,
                            "chronological_step": step,
                            "transition": {"status": "UNAVAILABLE_EMPTY_SOURCE"},
                        }
                    else:
                        before, after, availability = snapshots(suite, arm, owner, ordinal)
                        old_sources = prior_evidence(suite, arm, owner, before)
                        bank = suite / arm / "banks" / owner
                        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                            service = MemoryService(
                                store,
                                ("edit", arm, config["arm"], owner),
                                owner,
                                bank / "memory.lock",
                            )
                            new_sources = []
                            for i, ref in enumerate(source_refs):
                                source = service.source(ref)
                                if source is None:
                                    raise ValueError("Actual native source unavailable")
                                new_sources.append(
                                    {
                                        "source_id": "new_source_" + str(i),
                                        "role": source["role"],
                                        "content": body_text(source),
                                        "original_timestamp": original_timestamp(
                                            suite, arm, owner, source
                                        ),
                                    }
                                )
                        first, second = blinded_states(before, after, renderer=render_state)
                        transition = self.assess(
                            key + "/transition-judge",
                            TRANSITION_PROMPT,
                            {
                                "observed_dialogue": new_sources,
                                "source_review": {
                                    "classification": "continuous_native_maintenance",
                                    "source_supported_requirement": (
                                        "Apply durable information or changes actually "
                                        "supported by the new dialogue, preserve still-valid "
                                        "prior meaning and appropriate uncertainty. A request "
                                        "alone is not an actual business outcome. "
                                        "No ideal old state is supplied."
                                    ),
                                    "cancellation": False,
                                    "limit": (
                                        "Cancellation is separately scored by the fixed E2 review."
                                    ),
                                },
                                "prior_source_ranges": old_sources,
                                "before": first,
                                "after": second,
                            },
                            TransitionAssessment,
                        )
                        transition = validate_transition(
                            transition, first, second, cancellation=False,
                            prior_sources=old_sources if self.settings.get(
                                "interface_version", "v1"
                            ) != "v1" else None,
                        )
                        row = {
                            "arm": arm,
                            "uuid": owner,
                            "session": ordinal,
                            "chronological_step": step,
                            "availability": availability,
                            "transition": transition,
                        }
                    checkpoint = read_json(
                        suite
                        / arm
                        / "evaluation"
                        / "halumem"
                        / owner
                        / str(ordinal)
                        / "complete.json"
                    )
                    row["official_session_counts"] = checkpoint["counts"]
                    row["official_session_records"] = checkpoint["records"]
                    row["additional_editor_calls"] = 0
                    write_json(done, row)
                    rows.append(row)
        report = summarize_drift(rows)
        write_json(self.root / "continuous-drift-results.json", report)
        return report

    def run_controlled(self, manifest_path: Path) -> dict[str, Any]:
        manifest = read_json(manifest_path)
        arms = self.settings["controlled"]["arms"]
        rows = []
        base_settings = self.settings
        try:
            for case in manifest["cases"]:
                owner = case["source_cluster"]
                for variant in case["variants"]:
                    events = controlled_events(case, variant)
                    history = controlled_observations(case, variant)
                    wording = "en" if variant == "en_independent_swap" else variant
                    for arm in arms:
                        self.settings = {**base_settings, "arm": arm}
                        bank = self.root / "banks" / owner / variant / arm
                        bank.mkdir(parents=True, exist_ok=True)
                        with SqliteStore.from_conn_string(str(bank / "memory.sqlite")) as store:
                            service = MemoryService(
                                store,
                                ("edit", "controlled", variant, arm, owner),
                                owner,
                                bank / "memory.lock",
                                mutation_contract="event_bound_v1",
                                candidate_contract="read_handle_v1",
                                semantic_retriever=self._semantic_retriever(),
                                memory_profile=self.settings.get("memory_profile", "ordinary"),
                                memory_ranking=self.settings.get("memory_ranking", "dense"),
                            )
                            for step, (event, observed) in enumerate(
                                zip(events, history, strict=True)
                            ):
                                key = f"controlled/{owner}/{variant}/{arm}/step-{step}"
                                done = self.root / key / "complete.json"
                                if done.exists():
                                    rows.append(read_json(done))
                                    continue
                                before_path = self.root / key / "before.json"
                                if not before_path.exists():
                                    write_json(before_path, service.records())
                                self.maintain(service, observed, key)
                                after_path = self.root / key / "after.json"
                                if not after_path.exists():
                                    write_json(after_path, service.records())
                                before, after = read_json(before_path), read_json(after_path)
                                first, second = blinded_states(before, after, renderer=render_state)
                                prefix = [
                                    {"date": s.date, "dialogue": s.turns}
                                    for s in history[: step + 1]
                                ]
                                payload = {
                                    "observed_dialogue": observed.turns,
                                    "full_observed_prefix": prefix,
                                    "source_review": event["review"],
                                    "prior_source_ranges": grounded_ranges(
                                        service,
                                        before,
                                        timestamp_lookup=observed_timestamp_lookup(
                                            history[: step + 1]
                                        ),
                                        bind_records=self.settings.get(
                                            "interface_version", "v1"
                                        ) != "v1",
                                    ),
                                    "before": first,
                                    "after": second,
                                }
                                transition = self.assess(
                                    key + "/transition-judge",
                                    TRANSITION_PROMPT,
                                    payload,
                                    TransitionAssessment,
                                )
                                transition = validate_transition(
                                    transition,
                                    first,
                                    second,
                                    cancellation=event["review"]["cancellation"],
                                    prior_sources=payload["prior_source_ranges"]
                                    if self.settings.get("interface_version", "v1") != "v1"
                                    else None,
                                )
                                question = event["diagnostic_questions"][wording]
                                probe = self.probe(
                                    owner, after, question, observed.date, key,
                                    source_bank=bank / "memory.sqlite",
                                    source_namespace=service.namespace,
                                )
                                answer = (
                                    self.assess(
                                        key + "/answer-judge",
                                        ANSWER_PROMPT,
                                        {
                                            "question": question,
                                            "observed_dialogue": prefix,
                                            "source_review": event["review"],
                                            "answer": probe["answer"],
                                        },
                                        AnswerAssessment,
                                    )
                                    if probe["status"] == "ANSWERED"
                                    else {"status": "ANSWER_UNAVAILABLE"}
                                )
                                receipts = read_json(
                                    self.root / "maintenance" / key / "complete.json"
                                )["receipts"]
                                row = {
                                    "source_cluster": owner,
                                    "variant": variant,
                                    "arm": arm,
                                    "chronological_step": step,
                                    "event_id": event["event_id"],
                                    "classification": event["review"]["classification"],
                                    "cancellation_opportunity": event["review"]["cancellation"],
                                    "before_record_count": len(before),
                                    "after_record_count": len(after),
                                    "receipts": receipts,
                                    "transition": transition,
                                    "reader_probe": probe,
                                    "answer_assessment": answer,
                                    "gold_initialization": False,
                                    "review_used_by_editor": False,
                                }
                                write_json(done, row)
                                rows.append(row)
        finally:
            self.settings = base_settings
        report = summarize_controlled(rows, arms)
        write_json(self.root / "controlled-sensitivity-results.json", report)
        return report


def run_mechanism(
    settings_path: Path, suite: Path, selection: Path, review: Path, output: Path
) -> dict[str, Any]:
    settings = read_json(settings_path)
    require_completed_suite(suite, settings["mechanism"]["arms"])
    execution = MechanismRun(settings, output)
    try:
        result = execution.run_native(suite, selection, review)
        write_json(output / "terminal.json", {"status": result["status"]})
        return result
    except Exception as error:
        write_json(
            output / "terminal.json",
            {"status": "FAILED", "error_type": type(error).__name__, "error": str(error)},
        )
        raise
    finally:
        execution.close()


def run_answer_audit(settings_path: Path, suite: Path, manifest: Path, output: Path) -> None:
    settings = read_json(settings_path)
    require_completed_external(suite, settings["answer_audit"]["arms"])
    execution = MechanismRun(settings, output)
    try:
        result = execution.run_long_audit(suite, manifest)
        write_json(output / "terminal.json", {"status": result["status"]})
    except Exception as error:
        write_json(
            output / "terminal.json",
            {"status": "FAILED", "error_type": type(error).__name__, "error": str(error)},
        )
        raise
    finally:
        execution.close()


def run_drift(settings_path: Path, suite: Path, output: Path) -> None:
    settings = read_json(settings_path)
    require_completed_suite(suite, settings["drift"]["arms"])
    execution = MechanismRun(settings, output)
    try:
        result = execution.run_drift(suite)
        write_json(output / "terminal.json", {"status": result["status"]})
    except Exception as error:
        write_json(
            output / "terminal.json",
            {"status": "FAILED", "error_type": type(error).__name__, "error": str(error)},
        )
        raise
    finally:
        execution.close()


def run_controlled(
    settings_path: Path, suite: Path, candidate: Path, manifest: Path, output: Path
) -> None:
    settings = read_json(settings_path)
    require_completed_suite(suite, settings["controlled"]["arms"])
    require_frozen_candidate(settings, candidate)
    execution = MechanismRun(settings, output)
    try:
        result = execution.run_controlled(manifest)
        write_json(output / "terminal.json", {"status": result["status"]})
    except Exception as error:
        write_json(
            output / "terminal.json",
            {"status": "FAILED", "error_type": type(error).__name__, "error": str(error)},
        )
        raise
    finally:
        execution.close()
