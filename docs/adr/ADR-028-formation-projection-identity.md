# ADR-028：Formed Projection 身份、治理与渐进接入

状态：`PROPOSED / NOT APPROVED`  
日期：`2026-08-31`  
适用范围：Runtime `0.1.x EXPERIMENTAL` / Schema `0.1.x EXPERIMENTAL`

## 背景

Memory Lifecycle C2 的 sealed 三臂比较选择了 `FORMED_PLUS_RAW_CANONICAL`：Formed
表示能补回跨 episode 的状态、偏好、短期约束和事件身份证据，但 Raw Evidence 仍是唯一证据
权威。Formed artifact 是从一组 Evidence 派生的、可重建的 query-independent sidecar；它不能
成为第二套 canonical truth，也不能绕过 tenant、scope、permission、retention、revoke、as-of、
Binding 或 Sufficiency。

现有 `architecture/v1.0` 已冻结，因此本 ADR 不修改它，也不把实验结果解释为架构批准。

## 提议的持久化身份（待批准，当前不实施）

若未来批准 durable Formed projection，其逻辑主键应为：

```text
(tenant_id, project_id, subject_id,
 source_snapshot_digest, producer_identity, projection_schema_version)
```

其中：

- `project_id` 必须来自 Evidence 的不可变 permission snapshot，禁止从正文推断；
- `source_snapshot_digest` 覆盖有序 source Evidence ID、source ref、content digest 与 observed-at；
- artifact 只保存可回溯到 source Evidence 的 span/identity/state sidecar，不保存独立事实；
- `build_epoch` 只在 source snapshot 改变时递增，精确 replay 不递增；
- `source_watermark` 与 `access_snapshot_digest` 必须显式记录，不能用 projection readiness
  代替请求时治理；
- 表、worker、watermark、dead-letter、rebuild、purge 顺序和权限授权均需另行批准后实现。

在本 ADR 获批前，禁止创建上述持久化对象、默认开启产品流量或修改 frozen v1.0 架构。

## 当前允许的实验接入

本阶段只允许一个进程内、重启即空、默认关闭的 Formed sidecar，使用单一配置：

```text
MILAI_MEMORY_FORMATION_MODE = OFF | SHADOW | CANARY
default = OFF
```

- `OFF`：不构造 sidecar、不注册 observer，保持 Raw 路径行为身份；
- `SHADOW`：可构建并选择 source Evidence ID，只写无正文的诊断 trace，不改变结果；
- `CANARY`：Formed 只提供 source Evidence ID；数据库按请求时治理重新水合，通过后与 Raw
  候选并集，并完整重算 Evidence span、interpretation、Binding、RequirementState、operator 和
  Sufficiency；任何失败均回退 Raw；
- 进程重启、空 sidecar、歧义 subject、超界、构建失败或治理水合拒绝均不得阻断官方读取；
- sidecar 不调用模型、不写 canonical、不给 Reader 直接输入、不产生独立 answer authority；
- revoke 后先从 sidecar 移除 source，再允许后续选择；即使 invalidation 延迟，请求时数据库
  水合仍必须拒绝已撤销或不可读 Evidence；namespace cleanup 提交成功后立即丢弃对应进程内
  project partition。

为支持“derived ID → request-time governed Raw Evidence”边界，可增加一个通用、可回滚的
SECURITY DEFINER 精确 Evidence 水合函数。它不存储 Formed artifact，不扩大外部 API，并复用
现有 tenant session、scope、as-of、permission、retention、revoke 与 projection-version 条件。

## 官方链路与 Reader 边界

唯一被验收的调用链仍为：

```text
OpenWorker → relay/UDS → broker → milai-mcp → milai-runtime
```

MCP contract 不增加 Formed authority。Reader 只能看到 Runtime 在上述完整决策边界之后冻结的
structured result / typed operator result；确定性类型由 formatter 渲染，语义类型仍受既有
constrained-reader conformance 约束。

## 回滚与晋级条件

运行时回滚是把唯一 flag 设为 `OFF` 并重启；因为 sidecar 无持久状态、无 canonical mutation，
回滚后的语义结果必须与同请求 Raw 基线一致。数据库辅助水合函数可由 migration downgrade
精确删除，Raw Evidence 与现有 projection 不受影响。

只有在独立架构审批将本 ADR 改为 Accepted，且完成 cross-scope/revoke/permission/as-of、重建、
dead-letter、watermark、备份恢复及 rollback 证据后，才可设计 durable projection。C2/C3 的
sealed 分数本身不构成该批准。

本 ADR 不升级 Runtime/Schema 状态；继续为
`0.1.x EXPERIMENTAL / NO-GO FOR FREEZE`。
