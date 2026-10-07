"""Actual shared-maintenance and model-delivery receipts for registered requests.

No model execution, task registry or business executor lives here. The ordinary
Host owns those boundaries; receipt provenance does not certify semantic coverage.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any

from langchain_core.runnables import RunnableConfig

from milai_lab.application.recovery import UnknownModelRequest, UnknownSemanticCommit
from milai_lab.providers.request_pipeline import DeliveryObserver, PreparedRequest

PROGRESS_PREFIX = "Registered application request progress: "


def _result_refs(
    service: Any, requirements: dict[str, Any], source_refs: list[str],
) -> list[str]:
    refs = []
    for ref in source_refs:
        source = service.source(ref)
        if source is None or source["role"] != "tool":
            continue
        try:
            actual = json.loads(source["content"])
        except (TypeError, ValueError):
            continue
        if isinstance(actual, dict) and all(
            actual.get(field) == value for step in requirements["steps"]
            for field, value in step["completed"].items()
        ):
            refs.append(ref)
    return refs


def scoped_memory_receipt(
    service: Any, requirements: dict[str, Any], batches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read commits tied to a real Tool source containing the requested result.

    A current User save instruction, another target's commit, a raw capture or an
    empty proposal cannot stand in for this target's saved result. Source matching
    and a successful commit remain necessary conditions, not a semantic judgment.
    """
    relevant = [(ref, batch) for batch in batches for ref in
                _result_refs(service, requirements, batch.get("source_refs", []))]
    refs = {ref for ref, _ in relevant}
    commits = []
    seen = set()
    receipts = [r for _, b in relevant for r in b.get("receipts", [])]
    for receipt in receipts:
        if not (receipt.get("ok") and receipt.get("effect") == "memory_only" and (
            receipt.get("status") == "committed" or receipt.get("original_status") == "committed"
        )):
            continue
        identity = (receipt.get("id"), receipt.get("revision"))
        if identity in seen or not identity[0]:
            continue
        record = service.read(*identity)
        value = record.get("value") or {}
        if record.get("ok") and refs.intersection(
            value.get("source_refs", [value.get("source_ref")])
        ):
            seen.add(identity)
            commits.append(receipt)
    if any(b.get("phase", "").endswith("_pending") for _, b in relevant):
        raise UnknownModelRequest("HOST_RESULT_MAINTENANCE_MODEL_OUTCOME_UNKNOWN")
    if any(b.get("phase") == "commit" for _, b in relevant):
        raise UnknownSemanticCommit("HOST_RESULT_MAINTENANCE_COMMIT_OUTCOME_UNKNOWN")
    complete_batches = bool(relevant) and all(
        b.get("status") == "completed" and not b.get("unprocessed") for _, b in relevant)
    committed = bool(commits) and complete_batches
    return {
        "ok": committed, "status": "committed" if committed else
        "partial_commit" if commits else "result_save_unconfirmed",
        "effect": "memory_only" if commits else "none",
        "receipts": commits, "source_refs": sorted(refs),
        "maintenance_request_ids": list(dict.fromkeys(b["request_id"] for _, b in relevant)),
        "semantic_coverage": "unchecked",
    }


def reconcile_shared_result(
    memory: Any, row: dict[str, Any], operation_id: str,
    config: RunnableConfig, current_binding: dict[str, Any], model_call: Any,
) -> dict[str, Any] | None:
    """Inspect original maintenance operation IDs; never redispatch an unknown model call."""
    attempt = next(a for a in row["request_progress"]["memory"]["attempts"]
                   if a["operation_id"] == operation_id)
    original = attempt.get("binding")
    if not original:
        return None
    service = memory.service
    if service.source(original["source_ref"]) is None:
        return None
    original_config = {**config, "configurable": {**config["configurable"],
        "v13_session": original["session"], "v13_turn_id": original["turn_id"],
        "v13_config_version": original["config_version"]}}
    results = []
    service.bind_public_turn(original["session"], original["turn_id"], original["source_ref"],
                             config_version=original["config_version"], phase="resume")
    try:
        for prior in original.get("maintenance", []):
            if not _result_refs(service, row["requirements"], prior.get("source_refs", [])):
                continue
            saved = service.store.get((*service.namespace, "edit_maintenance"),
                json.dumps([original["session"], prior["request_id"]], ensure_ascii=False))
            if saved is None:
                return None
            binding = saved.value["binding"]
            ranges = [{k: s[k] for k in ("source_ref", "start", "end")}
                      for s in binding["sources"]]
            if any(service.source(s["source_ref"]) is None for s in ranges):
                return None
            delivery = memory.writer.prepare(
                list(dict.fromkeys(s["source_ref"] for s in ranges)), "",
                selected_records=[], source_ranges=ranges, redelivered_ranges=[])
            result = memory.maintain_delivery(
                original_config, delivery, request_id=prior["request_id"],
                prior_request_id=prior["request_id"], date=saved.value["date"],
                recipe=binding["recipe"], model_call=model_call, allowed=True, execute=False,
                selected_record_ids=binding.get("selected_record_ids"))
            if result["status"] != "completed":
                return None
            results.append(result)
    finally:
        service.bind_public_turn(current_binding["session"], current_binding["turn_id"],
            current_binding["source_ref"], config_version=current_binding["config_version"],
            phase="resume")
    receipt = scoped_memory_receipt(service, row["requirements"], results)
    return receipt if receipt["ok"] else None


class RequestProgressDelivery:
    """Retain an actual provider response to a request-progress frame.

    A later Host checkpoint must contain that response before it acknowledges
    feedback. A local report file alone never establishes delivery to the Host.
    """

    def __init__(self, inner: DeliveryObserver, tracker: Any) -> None:
        self.inner, self.tracker = inner, tracker

    def request_scope(
        self, request: PreparedRequest, request_index: int,
    ) -> AbstractContextManager[Any]:
        return self.inner.request_scope(request, request_index)

    def record_delivery(
        self, request: PreparedRequest, receipt: dict[str, Any], request_index: int,
    ) -> None:
        self.inner.record_delivery(request, receipt, request_index)
        choices = receipt.get("choices", [])
        if not (receipt.get("id") and len(choices) == 1
                and choices[0].get("finish_reason") in {"stop", "tool_calls"}
                and choices[0].get("message", {}).get("role") == "assistant"):
            return
        for message in request.messages:
            if message.get("role") != "system" or not isinstance(message.get("content"), str):
                continue
            for line in message["content"].splitlines():
                if not line.startswith(PROGRESS_PREFIX):
                    continue
                frame = json.loads(line[len(PROGRESS_PREFIX):])
                for key, row in self.tracker.rows():
                    delivered = next((r for r in frame if
                                      r["request_id"] == row["identity"]["call_id"]), None)
                    if delivered is None:
                        continue
                    self.tracker.app.progress.record(key,
                        "request_progress_delivery:" + receipt["id"], {
                            "provider_response_id": receipt["id"],
                            "basis": {name: delivered[name]["status"]
                                      for name in ("business", "memory")},
                            "receipt_kind": "provider_response_to_progress_frame",
                        })

    def after_delivery(self, request: PreparedRequest, request_index: int) -> None:
        self.inner.after_delivery(request, request_index)


def checkpointed_feedback(
    row: dict[str, Any], result: dict[str, Any], messages: list[Any],
) -> dict[str, Any]:
    """Acknowledge the actual Host response checkpoint, without claiming user receipt."""
    ids = {m.id for m in messages if getattr(m, "type", None) == "ai" and m.id}
    basis = {name: result[name]["status"] for name in ("business", "memory")}
    delivered = [r for key, r in row.items() if key.startswith("request_progress_delivery:")
                 and r["provider_response_id"] in ids and r["basis"] == basis]
    return {
        "ok": bool(delivered), "host_seen": bool(delivered),
        "status": "checkpointed" if delivered else "not_checkpointed",
        "receipt_kind": "host_response_checkpoint", "user_seen": "unchecked",
        "provider_response_ids": [r["provider_response_id"] for r in delivered],
    }
