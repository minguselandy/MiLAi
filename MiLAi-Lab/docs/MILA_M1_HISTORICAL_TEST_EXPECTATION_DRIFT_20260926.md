# 旧 M1 测试期望漂移

按 [v19 修复文档 §16](v19修复.md) 单独处理 `test_pending_protocol_or_unresolved_business_action[invalid_task_ended]` 的异常层级期望，和 freshness 方法的成败分开记录、分开提交。

已封存 v18 提交 `90ac0b35e95b0371106cb05fb66b1f933af7f432` 的 `m1_action_schema()` 在 calls 分支已排除 `clear_reason=task_ended`。adapter 会先执行 schema validate，拒绝该组合并抛出 `IncompleteChatResponse("JSON_ACTION_SCHEMA_INVALID")`，不会到达 controller 后续的 `DecisionDeltaError("DECISION_TASK_ENDED_WITH_CALLS")`。旧测试期待后者，因而与当时源码行为不一致。

此次只对该分支的预期异常类型和错误代码对齐，保留 invalid_clear 与 unresolved 的原语义、错误记录和零副作用断言；不更改 M1 schema、controller 或业务行为，不用 xfail/skip 隐藏失败。旧 v18/v19 的结果和17通过/1失败历史回执保持原样。

独立窄验证 `uv run --no-sync pytest -q 'tests/unit/test_milai_m1_v18.py::test_pending_protocol_or_unresolved_business_action[invalid_task_ended]'` 已通过（1 passed）；含该组的受影响25条测试也通过。确切回执由本轮 source-verification 记录。该修复不是 Notice/Quarantine/Refresh 获得效果的原因。
