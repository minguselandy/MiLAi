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
}
_FIELDS = {
    "item_key": "物品", "quantity": "数量", "reservation_id": "预订编号",
    "destination": "目的地配置", "packing": "包装配置", "label_status": "标签",
    "title": "文档标题", "document_version": "文档版本", "content": "文档正文",
    "approval_status": "当前版本批准状态", "publication_status": "当前版本发布状态",
    "audience": "沙箱发布对象",
    "attempted_audience": "本次尝试的沙箱受众 (不代表已发布)",
}


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


def business_response(
    messages: list[Any], effects: dict[str, Any], material: dict[str, Any],
    *, execution_stop: dict[str, Any] | None = None,
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
    paragraphs = ["本轮业务结果: " + _STATUS.get(business["status"], business["status"]) +
                  "。以下仅报告已核实的操作和查询, 不代表未列出的请求也已完成。"]
    for name, receipt in receipts:
        paragraphs.append(_TOOLS[name] + ": \n\n" + "\n".join(
            "- " + line for line in _receipt_lines(receipt)))
    if not receipts:
        paragraphs.append("本轮没有可交付的业务结果回执; 不能确认所请求的业务已完成。")
    historical = set()
    for unit in material.get("items", []):
        ref = unit.get("source_ref")
        if (unit.get("type") != "fragment" or unit.get("role") != "tool"
                or unit.get("origin") not in _TOOLS or ref in source_refs or ref in historical):
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
    semantic = effects["semantic_memory"]
    paragraphs.append("本轮语义记忆: " + _STATUS.get(semantic["status"], semantic["status"]) + "。")
    for operation in semantic["operations"]:
        paragraphs.append("记忆操作: " + _text({k: operation[k] for k in (
            "tool", "id", "revision", "status") if k in operation}))
    if effects["raw_event"]["status"] == "stored":
        paragraphs.append("本轮原始消息已记录。原始消息记录与语义记忆提交分别计数。")
    if execution_stop:
        paragraphs.append("执行已停止: 追加读取额度已用完; 未继续办理剩余工作。已确认的效果保留。")
    return AIMessage(content="\n\n".join(paragraphs))
