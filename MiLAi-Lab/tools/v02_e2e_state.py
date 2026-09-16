"""Opaque layered-memory adapter over public State calls; no model or private Product imports."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from v02_deadline import DeadlineExpired
from v02_local_provider import LocalGateError
from v02_read_file import read_page

PublicCall = Callable[[str, dict[str, Any]], dict[str, Any]]
DEFAULT_FIELD = "milai_lab_local_layered_v1"
_WRITE_REJECTIONS = frozenset({
    "STALE_WORKING_STATE", "OPERATION_CONFLICT", "EVIDENCE_REFERENCE_INVALID",
    "HOST_WORKING_STATE_SCOPE_DENIED",
})


def _write_rejection(receipt: dict[str, Any]) -> str | None:
    """Read the public error position, never codes quoted elsewhere in the receipt."""
    if "code" in receipt:
        code = receipt["code"]
        return code if isinstance(code, str) and code in _WRITE_REJECTIONS else None
    content = receipt.get("content")
    if isinstance(content, list):
        if len(content) != 1 or not isinstance(content[0], dict):
            return None
        block = content[0]
        if block.get("type") != "text":
            return None
        content = block.get("text")
    if not isinstance(content, str):
        return None
    # Preserve the pinned MCP transport's wrapper and the server's bare ToolError form.
    message = content.removeprefix("Error executing tool milai_working_state_update: ")
    code = message.partition(":")[0]
    return code if code in _WRITE_REJECTIONS else None


class FileDisclosure:
    """Host-owned provenance map; model content cannot grant file disclosure permission."""

    def __init__(
        self,
        project: str,
        file_refs: dict[str, list[str]],
        metadata: Callable[[str], dict[str, Any]],
        context_refs: list[str] | None = None,
    ):
        self.project, self.file_refs, self.metadata = project, copy.deepcopy(file_refs), metadata
        self.context_refs = set(context_refs or [])

    def check_refs(self, refs: list[str] | set[str]) -> None:
        for ref in refs:
            try:
                record = self.metadata(ref)
                permission = record["permission_snapshot"]
                allowed = (
                    record.get("evidence_id") == ref
                    and not record.get("revoked_at")
                    and record.get("retention_state") == "READABLE"
                    and permission.get("readable") is True
                    and self.project in permission.get("project_ids", [])
                )
            except Exception as exc:
                raise LocalGateError("FILE_DISCLOSURE_UNKNOWN") from exc
            if not allowed:
                raise LocalGateError("FILE_DISCLOSURE_DENIED")

    def read(self, path: str) -> None:
        if path not in self.file_refs:
            raise LocalGateError("FILE_PROVENANCE_NOT_DECLARED")
        self.check_refs(self.file_refs[path])
        self.context_refs.update(self.file_refs[path])

    def before_request(self) -> None:
        # Do not resend old conversation content after a declared dependency is revoked.
        self.check_refs(self.context_refs)

    def acquired(self, response: dict[str, Any], *, tool_name: str | None = None) -> None:
        """Track published provenance fields, never UUID-looking text in memory content."""
        refs: set[str] = set()
        if response.get("schema_version") == "memory-evidence-context-v1":
            for item in response.get("evidence", []):
                refs.update(item.get("evidence_ids", []))
        elif response.get("schema_version") == "memory-state-view-v0.1":
            refs.update(response.get("evidence_refs", []))
        elif response.get("schema_version") == "host-cognitive-state-v1":

            def visit(value: Any) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key == "evidence_refs":
                            refs.update(child)
                        elif key == "evidence_id":
                            refs.add(child)
                        else:
                            visit(child)
                elif isinstance(value, list):
                    for child in value:
                        visit(child)

            visit(response.get("payload", {}))
        elif not response.get("mcp_error"):
            # These pinned tools return untagged records. Only their published
            # provenance positions count; arbitrary text/patch keys do not.
            if tool_name == "milai_evidence_capture" and response.get("evidence_id"):
                refs.add(response["evidence_id"])
            elif tool_name in {"milai_proposal_get", "milai_proposals_list"}:
                records = (
                    response.get("proposals", [])
                    if tool_name == "milai_proposals_list" else [response]
                )
                for record in records:
                    refs.update(record.get("supporting_evidence_refs", []))
                    refs.update(record.get("contradicting_evidence_refs", []))
        self.check_refs(refs)
        self.context_refs.update(refs)

    def created(self, path: str) -> None:
        self.file_refs[path] = sorted(self.context_refs)

    def visible(self, files: dict[str, str]) -> dict[str, str]:
        visible = {}
        for path, version in files.items():
            if path not in self.file_refs:
                continue
            try:
                self.check_refs(self.file_refs[path])
            except LocalGateError:
                continue
            visible[path] = version
        return visible


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def remap_declared_refs(payload: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
    """Rebind only published reference fields; opaque text is never string-replaced."""

    def visit(value: Any) -> Any:
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, child in value.items():
                if key == "evidence_id":
                    result[key] = mapping[child]
                elif key == "evidence_refs":
                    result[key] = [mapping[ref] for ref in child]
                else:
                    result[key] = visit(child)
            return result
        if isinstance(value, list):
            return [visit(child) for child in value]
        return copy.deepcopy(value)

    return cast(dict[str, Any], visit(payload))


def file_path(workspace: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise LocalGateError("DETAIL_OUTSIDE_SNAPSHOT")
    target = workspace.resolve()
    for part in path.parts:
        target /= part
        if target.is_symlink():
            raise LocalGateError("SYMLINK_NOT_ALLOWED")
    if not target.is_file():
        raise LocalGateError("FILE_UNAVAILABLE")
    return target


def usable_head(head: dict[str, Any]) -> None:
    if (
        head.get("status") not in {"ABSENT", "ACTIVE"}
        or head.get("warnings")
        or head.get("authority") != "HOST_WORKING"
        or head.get("scope") != "TASK"
        or head.get("schema_version") != "host-cognitive-state-v1"
        or not isinstance(head.get("payload"), dict)
        or type(head.get("version")) is not int
    ):
        raise LocalGateError("RESTORE_NOT_USABLE")
    if head["status"] == "ABSENT":
        if head["version"] != 0 or head.get("state_id") is not None or head["payload"]:
            raise LocalGateError("INVALID_ABSENT_STATE")
    elif head["version"] < 1 or not head.get("state_id") or not head.get("state_version_id"):
        raise LocalGateError("INVALID_ACTIVE_STATE")


def candidate(
    workspace: Path,
    config: dict[str, Any],
    source_versions: dict[str, str],
    evidence_refs: list[str],
) -> dict[str, Any]:
    l1 = file_path(workspace, config["l1_path"])
    detail = file_path(workspace, config["l2_path"])
    raw = l1.read_bytes()
    if len(raw) > config.get("l1_max_bytes", 4096):
        raise LocalGateError("L1_TOO_LARGE_NO_REWRITE")
    if not raw.strip() or not detail.stat().st_size:
        raise LocalGateError("NO_LAYERED_OPPORTUNITY")
    text = raw.decode("utf-8")
    format_name = config.get("l1_format", "text")
    if format_name not in {"text", "json"}:
        raise LocalGateError("UNSUPPORTED_DECLARED_FORMAT")
    value = json.loads(text) if format_name == "json" else text
    # JSON validity is mechanical, not an interpretation of domain fields.
    json.dumps(value, allow_nan=False)
    return {
        "owner": config["experiment_id"],
        "l1": value,
        "l1_format": format_name,
        "l1_source_sha256": hashlib.sha256(raw).hexdigest(),
        "l2": {"path": config["l2_path"], "sha256": digest(detail)},
        "source_versions": copy.deepcopy(source_versions),
        "evidence_refs": sorted(set(evidence_refs)),
    }


def save_layers(
    call: PublicCall,
    workspace: Path,
    config: dict[str, Any],
    source_versions: dict[str, str],
    operation_id: str,
    evidence_refs: list[str] | None = None,
) -> dict[str, Any]:
    """One write at most; operation proof never inferred from a later head's content."""
    result: dict[str, Any] = {
        "selection_reason": "UNDETERMINED",
        "model_requests": 0,
        "operation": {"attempted": False, "outcome": "NOT_ATTEMPTED", "id": operation_id},
        "head_observation": {"outcome": "NOT_OBSERVED"},
        "comparison_opportunity": False,
    }
    try:
        before = call("milai_working_state_get", {"scope": "TASK"})
        result["before"] = before
        usable_head(before)
        layer = candidate(workspace, config, source_versions, evidence_refs or [])
        field = config.get("state_field", DEFAULT_FIELD)
        existing = before["payload"].get(field)
        if field in before["payload"] and (
            not isinstance(existing, dict) or existing.get("owner") != layer["owner"]
        ):
            raise LocalGateError("MANAGED_FIELD_OWNERSHIP_UNKNOWN")
        if existing == layer:
            result.update(
                selection_reason="NO_CHANGE", payload=before["payload"], comparison_opportunity=True
            )
            result["head_observation"] = {
                "outcome": "OBSERVED",
                "value": before,
                "matches_candidate": True,
            }
            return result
        payload = {**copy.deepcopy(before["payload"]), field: layer}
        request = {
            "scope": "TASK",
            "state_id": before.get("state_id"),
            "expected_version": before["version"],
            "payload": payload,
            "operation_id": operation_id,
        }
        result.update(
            selection_reason="WRITE",
            request=request,
            payload=payload,
            detail_observation=layer["l2"],
        )
        if digest(file_path(workspace, layer["l2"]["path"])) != layer["l2"]["sha256"]:
            raise LocalGateError("DETAIL_VERSION_UNAVAILABLE")
        operation = result["operation"]
        operation.update(attempted=True, outcome="UNKNOWN")
        try:
            receipt = call("milai_working_state_update", request)
            operation["receipt"] = receipt
            # The synchronous public response is correlated with this exact request.
            # Persisted state_version_id identifies the committed version, even if head advances.
            if (
                not receipt.get("mcp_error")
                and receipt.get("state_version_id")
                and receipt.get("state_id")
                and receipt.get("payload") == payload
                and receipt.get("version") == before["version"] + 1
                and (before.get("state_id") is None or receipt["state_id"] == before["state_id"])
            ):
                operation.update(
                    outcome="CONFIRMED",
                    version_id=receipt["state_version_id"],
                    state_id=receipt["state_id"],
                )
            elif receipt.get("mcp_error"):
                # Only published deterministic rejection codes prove noncommit.
                code = _write_rejection(receipt)
                if code:
                    operation.update(outcome="REJECTED", reason=code)
        except Exception as exc:
            operation["error_type"] = type(exc).__name__
        try:
            head = call("milai_working_state_get", {"scope": "TASK"})
            observation = {
                "outcome": "OBSERVED",
                "value": head,
                "matches_candidate": head.get("payload") == payload,
                "same_committed_version": operation.get("version_id") is not None
                and head.get("state_version_id") == operation["version_id"],
            }
            result["head_observation"] = observation
            usable_head(head)
            result["comparison_opportunity"] = bool(
                operation["outcome"] == "CONFIRMED"
                and observation["same_committed_version"]
                and observation["matches_candidate"]
            )
        except Exception as exc:
            result["head_observation"]["error_type"] = type(exc).__name__
            if result["head_observation"]["outcome"] == "NOT_OBSERVED":
                result["head_observation"]["outcome"] = "UNKNOWN"
    except DeadlineExpired:
        # Preserve known progress on cancellation. No GET or retry may follow the deadline.
        result["cancelled"] = True
        result["selection_reason"] = "SESSION_DEADLINE"
    except (OSError, ValueError, LocalGateError) as exc:
        result["selection_reason"] = (
            str(exc) if isinstance(exc, LocalGateError) else type(exc).__name__
        )
    except Exception as exc:
        result["selection_reason"] = "START_HEAD_UNKNOWN"
        result["error_type"] = type(exc).__name__
    return result


def assemble_layers(
    head: dict[str, Any], workspace: Path, arm: str, config: dict[str, Any], files: dict[str, str]
) -> dict[str, Any]:
    usable_head(head)
    if arm not in {"G", "A", "B"}:
        raise LocalGateError("UNKNOWN_ARM")
    value: dict[str, Any] = {
        "status": head["status"],
        "version": head["version"],
        "payload": {},
        "workspace_files": files,
    }
    if head["status"] == "ACTIVE":
        field = config.get("state_field", DEFAULT_FIELD)
        layer = head["payload"].get(field)
        if not isinstance(layer, dict) or layer.get("owner") != config["experiment_id"]:
            raise LocalGateError("LAYER_LAYOUT_NOT_CONFIGURED")
        detail = layer["l2"]
        if detail["path"] not in files:
            raise LocalGateError("DETAIL_OUTSIDE_SNAPSHOT")
        path = file_path(workspace, detail["path"])
        if digest(path) != detail["sha256"]:
            raise LocalGateError("DETAIL_VERSION_UNAVAILABLE")
        # Preserve all State on disk/server, but present only the explicitly mapped layer.
        value["payload"] = {field: copy.deepcopy(layer)}
        if arm == "A":
            page = read_page(
                workspace, detail["path"], 0, config["prefetch_max_bytes"], detail["sha256"]
            )
            if page["truncated"]:
                raise LocalGateError("DETAIL_PREFETCH_TOO_LARGE_NO_TRUNCATION")
            value["prefetched_detail"] = page
    size = len(json.dumps(value, ensure_ascii=False).encode())
    if size > config.get("bootstrap_max_bytes", 16384):
        raise LocalGateError("BOOTSTRAP_TOO_LARGE_NO_TRUNCATION")
    return value
