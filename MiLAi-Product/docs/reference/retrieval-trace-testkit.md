# Retrieval trace 比较口径

`milai-retrieval-trace-testkit` 通过 stdin 接收公开 request-v0.1；仅用于隔离环境的信息性读取，
无生成模型调用，不改变检索策略或 Canonical。一次调用执行 normal/baseline/traced 三次读取。
正常 resolve 可能保存非 Canonical continuation 根记录，不能把该观测称为数据库零写入。

默认 `comparison_semantics_version="v0.1"` 保留历史响应摘要算法。显式选择 `"v0.2"` 时，
返回 report-v0.2，并保留 `legacy_response_semantic_digests`。旧 Product-10/X1 摘要和结果
不得按 v0.2 重新解释。

v0.2 对独立首轮读取的 context/root ID 作有限规范化，前提是：同次 receipt 对应；持久化
记录由当前 tenant/actor 拥有；root、predecessor、generation 正确；query/request（含 scope、
reference time、预算等）与来源 snapshot 一致；selected Evidence 及 continuation assertion
与记录一致。新增验证只有只读 repository GET，不进入原取证通路，也不替代 observer/repository 门。

Evidence/turn 身份、顺序、正文摘要、frontier 能力、数量、失效、重放和降级继续比较；v0.2
额外比较 receipt 非局部字段。错误绑定直接拒绝，不删除 continuation 整块。
`local_identity_bindings` 提供受控身份摘要与绑定验证，原根记录保留在隔离实例中。

拒绝 `TRACING_BEHAVIOR_CHANGED` 时，`response_field_diff` 最多各 32 个路径，只包含
值类型、基数和摘要及截断标志。它不输出正文。来源/READY 在三次读取期间变化仍会拒绝。

2026-09-06 验证：D1 OFF 控制、D1 ON 计数/普通/更新锚点、空来源，以及真实 PG 的
错误 query/scope/predecessor 和实际新增 READY 来源负控。工程可观测性通过不代表问答效果提升。
实验记录在 Lab 的 MILA-V02-03；公网未部署本次变更。

Schema 保持 `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。回退比较口径用显式 v0.1，
不回退共享数据库或 State head。
