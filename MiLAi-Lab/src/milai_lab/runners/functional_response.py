"""Receipt-owned presentation for the two public functional business workflows.

No model claims, evaluator state or database-only facts enter these answers.
Historical facts come only from already delivered original tool fragments. This
renderer reports listed observations/effects, not semantic task completion.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

_TOOLS = {
    "reserve_and_label": "预订并制作标签", "complete_label": "补办标签",
    "get_reservation": "实时查询预订", "create_or_update_draft": "保存文档草稿",
    "approve_document_version": "批准文档", "publish_approved_document": "发布文档到本地沙箱",
    "get_document_status": "实时查询文档",
}
_STATUS = {
    "found": "已查到", "not_found": "未查到对象", "label_created": "标签已创建",
    "reserved_label_failed": "预订成功, 标签制作失败",
    "label_service_unavailable": "标签服务不可用", "draft_created": "草稿已创建",
    "draft_updated": "草稿已更新", "draft_unchanged": "草稿无需变更",
    "document_approved": "文档已批准", "document_published": "文档已发布到本地沙箱",
    "publish_service_unavailable": "发布服务不可用", "created": "已创建",
    "not_created": "未创建", "approved": "已批准", "invalidated": "原批准已失效",
    "not_approved": "未批准", "published": "已发布到本地沙箱",
    "not_published": "当前版本未发布", "committed": "已提交",
    "not_committed": "未提交", "no_change": "已有记录, 无需变更",
    "unknown": "未知", "partial": "部分完成", "confirmed": "已确认发生",
    "none": "没有产生新效果", "observed": "仅查询观察",
    "no_effect": "没有产生新效果", "completed": "列出的操作已完成",
    "not_executed": "未执行新的业务操作",
    "not_requested": "本轮未要求办理", "visibility_revoked": "可见性已撤销",
}
_FIELDS = {
    "item_key": "物品", "quantity": "数量", "reservation_id": "预订编号",
    "destination": "目的地配置", "packing": "包装配置", "label_status": "标签",
    "title": "文档标题", "document_version": "文档版本", "content": "文档正文",
    "approval_status": "当前版本批准状态", "publication_status": "当前版本发布状态",
    "audience": "沙箱发布对象",
    "attempted_audience": "本次尝试的沙箱受众 (不代表已发布)",
}
_MEMORY_READS = {"search_memory", "read_memory", "read_history", "read_page"}


def _text(value: Any) -> str:
    # Quote data, including embedded newlines, so it cannot introduce a new
    # renderer-authored claim or Markdown heading/table row.
    return json.dumps(value, ensure_ascii=False).replace("|", "\\|")


def _receipt_lines(receipt: dict[str, Any]) -> list[str]:
    lines = ["结果: " + _STATUS.get(str(receipt.get("status")), _text(receipt.get("status")))]
    for key, label in _FIELDS.items():
        if key in receipt:
            value = receipt[key]
            lines.append(label + ": " + (_STATUS.get(value, _text(value))
                         if key.endswith("_status") and isinstance(value, str) else _text(value)))
    if receipt.get("reason"):
        reason = str(receipt["reason"])
        lines.append("原因: " + _STATUS.get(reason, _text(reason)))
    # These are actual public document history entries, not hidden world state.
    for publication in receipt.get("publications", []):
        if isinstance(publication, dict):
            lines.append("历史沙箱发布: " + _text({k: publication[k] for k in (
                "document_version", "audience") if k in publication}))
    history = receipt.get("operation_history", {})
    for prior in history.get("items", []):
        if prior.get("same_public_message"):
            continue
        name = _TOOLS.get(prior.get("operation"), str(prior.get("operation")))
        effect = _STATUS.get(prior.get("effect"), str(prior.get("effect")))
        result = prior.get("result_status")
        status = _STATUS.get(result, _text(result)) if result else "原回执未知"
        lines.append("先前操作回执: " + name + " / " + status + " / " + effect)
    if history.get("omitted_earlier_count"):
        lines.append("更早操作回执未列出数量: " + str(history["omitted_earlier_count"]))
    return lines


def _saved_content_lines(messages: list[Any], material: dict[str, Any]) -> list[str]:
    """Quote already delivered, visibility-filtered record parts without new reads."""
    calls: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    omitted_record_body = False
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if isinstance(call_id, str):
                    calls[call_id] = call["name"]
        elif isinstance(message, ToolMessage):
            name = calls.pop(message.tool_call_id, None)
            if name not in _MEMORY_READS or name != message.name or message.status == "error":
                continue
            try:
                packet = json.loads(str(message.content))
            except ValueError:
                continue
            if (isinstance(packet, dict) and packet.get("schema") == "functional_material_v1"
                    and packet.get("ok") is not False):
                items.extend(packet.get("items", []))
                omitted_record_body |= any(
                    unit.get("type") == "record"
                    and unit.get("reason") == "unit_exceeds_material_limit"
                    and unit.get("snapshot_body_delivered") is False
                    for unit in packet.get("skipped_units", [])
                )
    if material.get("schema") == "functional_material_v1":
        items.extend(material.get("items", []))
        omitted_record_body |= any(
            unit.get("type") == "record"
            and unit.get("snapshot_body_delivered") is False
            for unit in material.get("skipped_units", [])
        )
    lines = []
    seen = set()
    remaining = 1000
    for unit in items:
        if (unit.get("type") != "record" or not unit.get("content")
                or unit.get("status") == "visibility_revoked"
                or unit.get("source_visibility") == "visibility_revoked"):
            continue
        identity = (unit["record_id"], unit["revision"],
                    unit.get("edit_unit", {}).get("unit_id"), tuple(unit.get("content_range", [])))
        if identity in seen:
            continue
        seen.add(identity)
        content = unit["content"]
        excerpt = content[:remaining]
        version = str(unit["revision"])
        if unit.get("version_view") == "historical_exact_revision":
            version += ", 历史版本"
        if unit.get("retracted"):
            version += ", 已撤销"
        lines.append("已读取的保存内容 (版本 " + version + "): " + _text(excerpt)
                     + (" (引用已截断)" if len(excerpt) < len(content) else ""))
        remaining -= len(excerpt)
        if remaining == 0:
            break
    if omitted_record_body:
        lines.append("部分保存内容因读取材料额度未送达; 未读到不表示未保存。")
    return lines


def business_response(
    messages: list[Any], effects: dict[str, Any], material: dict[str, Any],
    *, execution_stop: dict[str, Any] | None = None,
    current_mode: dict[str, Any] | None = None,
    include_business: bool = True,
    include_memory_feedback: bool = True,
) -> AIMessage:
    """Use matched delivered receipts and current-message journal identities only."""
    business = effects["business"]
    authorized = {row["receipt_ref"]: row for row in [
        *business["operations"], *business["observations"]]}
    calls: dict[str, str] = {}
    receipts: list[tuple[str, dict[str, Any]]] = []
    source_refs: set[str] = set()
    targets: set[tuple[str, str]] = set()
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if isinstance(call_id, str):
                    calls[call_id] = call["name"]
        elif isinstance(message, ToolMessage):
            name = calls.pop(message.tool_call_id, None)
            authority = authorized.get(message.tool_call_id, {})
            if name not in _TOOLS or name != message.name or authority.get("tool") != name:
                continue
            try:
                body = json.loads(str(message.content))
            except ValueError:
                continue
            receipt = body.get("receipt") if isinstance(body, dict) else None
            if not isinstance(receipt, dict):
                continue
            receipts.append((name, receipt))
            source_refs.add(body.get("source_ref", ""))
            targets.update((k, receipt[k]) for k in ("item_key", "title")
                           if isinstance(receipt.get(k), str))
    paragraphs = (["本轮业务结果: " + _STATUS.get(business["status"], business["status"]) +
                   "。以下仅报告已核实的操作和查询, 不代表未列出的请求也已完成。"]
                  if include_business else [])
    for name, receipt in receipts:
        paragraphs.append(_TOOLS[name] + ": \n\n" + "\n".join(
            "- " + line for line in _receipt_lines(receipt)))
    if include_business and not receipts:
        paragraphs.append("本轮未取得新的业务回执。")
    historical = set()
    for unit in material.get("items", []):
        ref = unit.get("source_ref")
        if (unit.get("type") != "fragment" or unit.get("role") != "tool"
                or unit.get("origin") not in _TOOLS or ref in source_refs or ref in historical
                or unit.get("status") == "visibility_revoked"
                or unit.get("source_visibility") == "visibility_revoked"):
            continue
        try:
            old = json.loads(unit.get("content", ""))
        except (ValueError, TypeError):
            continue
        if not isinstance(old, dict) or not any(old.get(k) == value for k, value in targets):
            continue
        historical.add(ref)
        paragraphs.append("历史原始回执 (不代表当前状态): \n\n" + "\n".join(
            "- " + line for line in _receipt_lines(old)))
    if not include_memory_feedback:
        return AIMessage(content="\n\n".join(paragraphs))
    saved_content = _saved_content_lines(messages, material)
    paragraphs.extend(saved_content)
    if saved_content and not effects.get("application_requests"):
        paragraphs.append("原请求是否已全部完成尚未核对。")
    semantic = effects["semantic_memory"]
    paragraphs.append("本轮语义记忆: " + _STATUS.get(semantic["status"], semantic["status"])
                      + "。这里只报告列出的回执, 不确认全部请求或语义覆盖。")
    if current_mode is not None:
        allowed = current_mode["allow_memory_maintenance"]
        paragraphs.append("本轮保存许可: " + ("当前允许记忆维护" if allowed
                                               else "当前未获允许") + "。")
        if allowed and semantic["status"] in {"not_committed", "partial", "unknown"}:
            if semantic["operations"]:
                paragraphs.append("本轮已尝试记忆维护; 列出的未提交或未知结果不能确认保存成功。")
            else:
                paragraphs.append("本轮没有可确认的记忆维护尝试回执, 尚不能确认保存完成。")
    for operation in semantic["operations"]:
        paragraphs.append("记忆操作: " + _text({k: operation[k] for k in (
            "tool", "id", "revision", "status") if k in operation}))
    for request in effects.get("application_requests", []):
        labels = {
            "completed": "完成", "pending_host_execution": "仍有待办",
            "observed_only": "只查询", "not_authorized_current_request": "当前未获允许",
            "current_state_changed": "当前状态已变化", "business_unknown": "效果待查询",
            "partial": "部分完成", "incomplete": "尚未完成",
            "attempted": "已尝试", "outcome_unknown": "效果未知",
            "observation_unknown": "查询结果未知", "not_needed": "无需办理",
            "access_revoked": "访问已撤销",
            "not_evaluated": "尚未核对",
            "missing_observed_arguments": "尚缺办理参数",
            "business_phase_already_attempted_this_turn": "已尝试该步骤",
            "pending": "尚未确认", "committed": "提交已确认", "failed": "未确认成功",
            "not_requested": "未要求", "delivered": "Host已收到进度",
            "semantic_unknown": "提交结果未知", "model_unknown": "模型响应未知",
            "visibility_revoked": "可见性已撤销",
        }
        business_status = request["business"]["status"]
        execution_status = request["business"]["execution"]["status"]
        memory_status = request["memory"]["status"]
        permission = request["memory"].get("current_permission")
        if current_mode is not None:
            permission = ("当前允许记忆维护" if current_mode["allow_memory_maintenance"]
                          else "not_authorized_current_request")
        feedback_status = request["feedback"]["status"]
        paragraphs.append("原请求进度: 业务" + labels.get(business_status, business_status)
            + "; 本次执行" + labels.get(execution_status, execution_status)
            + "; 实际结果保存" + labels.get(memory_status, memory_status)
            + ("; 保存许可" + labels.get(permission, permission) if permission else "")
            + "; 反馈" + labels.get(feedback_status, feedback_status)
            + "。回执进度与语义正确性分别记录。")
    for number, operation in enumerate(effects.get("visibility", {}).get("operations", []), 1):
        attempt_label = "遗忘尝试 " + str(number) + ": "
        if operation["status"] == "visibility_revoked":
            paragraphs.append(attempt_label + "已按实际回执撤销所选记忆及来源的可见性。" +
                "范围: " + _text(operation.get("scope")) +
                "; 数量: " + _text(operation.get("scope_counts", {})) +
                "。未执行物理擦除, 备份和实验审计轨迹仍保留。未选择的独立副本不在本次确认范围内。")
        else:
            paragraphs.append(attempt_label + _STATUS.get(operation["status"],
                              _text(operation["status"])) +
                              "; 此次尝试未确认撤销效果, 其他尝试的结果分别列出。")
    raw = effects["raw_event"]
    if raw["status"] == "stored":
        paragraphs.append(
            "本轮原始消息曾记录, 当前可见性已撤销。原始消息记录与语义记忆提交分别计数。"
            if raw.get("source_visibility") == "visibility_revoked" else
            "本轮原始消息已记录。原始消息记录与语义记忆提交分别计数。"
        )
    elif raw["status"] == "visibility_revoked":
        paragraphs.append("本轮原始消息的可见性已撤销; 本轮无法据此确认语义保存内容。")
    if execution_stop:
        paragraphs.append("执行已停止: 追加读取额度已用完; 未继续办理剩余工作。已确认的效果保留。")
    return AIMessage(content="\n\n".join(paragraphs))


def unattempted_continuations(
    messages: list[Any], effects: dict[str, Any], allowed: list[str],
) -> list[dict[str, Any]]:
    """Identify literal missing stages from paired current public queries only.

    This is feedback material, not authorization or proof an action is required.
    Any current attempt, including none/unknown, prevents a retry suggestion.
    """
    business = effects["business"]
    authorities = {r["receipt_ref"]: r for r in [
        *business["operations"], *business["observations"]]}
    calls: dict[str, str] = {}
    attempted: set[tuple[str, str]] = set()
    observed: dict[tuple[str, str], dict[str, Any]] = {}
    target_fields = {"complete_label": "reservation_id", "publish_approved_document": "title"}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                call_id = call.get("id")
                if not isinstance(call_id, str):
                    continue
                calls[call_id] = call["name"]
                name, args = call["name"], call["args"]
                if (name in target_fields and authorities.get(call["id"], {}).get("tool") == name
                        and isinstance(args.get(target_fields[name]), str)):
                    attempted.add((name, args[target_fields[name]]))
        elif isinstance(message, ToolMessage):
            query_name = calls.get(message.tool_call_id)
            authority = authorities.get(message.tool_call_id, {})
            if (query_name != message.name
                    or query_name not in {"get_reservation", "get_document_status"}
                    or authority.get("tool") != query_name or not authority.get("executed")
                    or authority.get("execution_receipt_status") != "complete"):
                continue
            try:
                receipt = json.loads(str(message.content)).get("receipt")
            except (ValueError, AttributeError):
                continue
            if not isinstance(receipt, dict) or receipt.get("status") != "found":
                continue
            operation = ("complete_label" if query_name == "get_reservation"
                         else "publish_approved_document")
            key = target_fields[operation]
            if isinstance(receipt.get(key), str):
                observed[(operation, receipt[key])] = {
                    "receipt": receipt, "query_receipt_ref": message.tool_call_id}
    result = []
    for (operation, target), observation in observed.items():
        receipt = observation["receipt"]
        missing = (receipt.get("label_status") == "not_created" if operation == "complete_label"
                   else receipt.get("approval_status") == "approved"
                   and receipt.get("publication_status") == "not_published")
        if operation in allowed and (operation, target) not in attempted and missing:
            result.append({"operation": operation, "target_field": target_fields[operation],
                           "target": target, "query_receipt_ref": observation["query_receipt_ref"],
                           "interpretation": "observed_missing_stage_not_action_authorization"})
    return result
