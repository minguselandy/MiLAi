# ADR-029：Informational Context Admission 与 Additive Recall

状态：`ACCEPTED AS DEFAULT-OFF PRODUCT-08 CANDIDATE`  
日期：`2026-09-03`  
适用范围：Runtime `0.1.x CANDIDATE` / Schema `0.1.x EXPERIMENTAL`

## 背景

Product-07 表明读取链路存在职责错位：QueryIR/Binding 在候选发现之后继续充当普通
informational recall 的 Reader admission 门槛，可能把已通过治理检查的候选全部删除；与此同时，
所谓 union 路径并未执行 Dense，RecallWorkspace 只能重排剩余候选，无法恢复已删除 Evidence。

`Raw Evidence` 仍只是 observation，不是 accepted truth。但“是否允许 Reader 查看一条治理合格的
observation”和“该 observation 是否足以完成 COUNT/SUM/时态等 operator”是两个不同决定。

## 决定

增加两个互相独立、默认关闭的候选开关：

```text
MILAI_RETRIEVAL_ADDITIVE_UNION_V0_2_ENABLED=false
MILAI_READER_INFORMATIONAL_SOFT_ADMISSION_V0_2_ENABLED=false
```

Additive union V0.2 保留原始 query 的全局 FTS backbone，并把 requirement-local FTS 与显式可用的
Raw Evidence Dense 作为有界增量通道。融合只使用通道内 rank 和稳定 Evidence identity；每个
requirement 只有一个保留机会，QueryIR 不得取消全局 backbone，也不得取得 admission authority。
Dense 未配置、projection 不完整或 disposition 非 `EXECUTED` 时必须显式暴露，不能把该运行称为
FTS+Dense。

Informational soft admission 只影响 Reader presentation：对已通过 tenant、principal、scope、
permission、retention、revocation 和 as-of 检查的 `EVIDENCE_OBSERVATION`，即使 Binding/Sufficiency
尚未接受或错误压缩了 task type，也允许其进入预算化 Context。Binding、EvidenceSet、operator
validation 和 `COMPLETE` 所有权保持不变；严格 derived result 仍只能消费
`ACCEPTED_BINDING_ONLY` operands。

以下边界继续 fail closed，soft admission 不得绕过：

- `ACTION_SAFE` 或任何非 `INFORMATIONAL` authority；
- access denied、Canonical unavailable、no candidate；
- open issue / contested memory；
- 除 Context budget 外的 degraded governance/infrastructure 状态；
- tenant、scope、permission、retention、revocation 或 as-of 拒绝。

RecallWorkspace 不参与该候选路径。配置层拒绝它与任一 Product-08 开关组合，且断言任何 workspace
处理前后的候选 identity set 完全相同。

## 可观测性与 Testkit

Context trace 记录 acquisition boundary 前后 Evidence ID、source turn ref、逐项保留/删除原因及
content/governance/envelope digest，不复制 Evidence 正文。新增独立发布的只读
`milai-context-testkit`：一次 live acquisition 生成进程内 frozen snapshot，再以零 repository、
embedding、vector、Provider 或 Canonical mutation 调用重放 C/X/Y。该 Testkit 不是 Runtime API，
不能被普通产品请求调用，也不能把原始 Evidence 文本写入报告。

## 兼容、回滚与晋级

本变更没有数据库 migration、公共 MCP/API 字段、permission、Canonical procedure 或 state identity
变化。回滚只需保持两个开关为 `false` 并重启；默认路径与 Product-07 terminal 时一致。

候选只能在固定 acquisition snapshot、真实 Dense execution 和 Context-only evidence-group gate
全部通过后进入后续 Reader 验证。打开开发集、单元测试或代码存在均不构成默认启用依据；正式
holdout 仍需单独授权。

本 ADR 不升级 Runtime/Schema 状态；Schema 继续为
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。
