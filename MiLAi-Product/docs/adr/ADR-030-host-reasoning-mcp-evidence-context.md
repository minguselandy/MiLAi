# ADR-030：Codex Streamable HTTP MCP Evidence Context

状态：`ACCEPTED FOR PRODUCT-08`  
日期：`2026-09-03`  
适用范围：Codex → Streamable HTTP MCP `agent-memory`；Runtime/Schema 保持
`0.1.x CANDIDATE/EXPERIMENTAL`

## 背景

Codex 已拥有理解问题、工具循环和最终回答能力。让 MiLAi 在正常 MCP 读取路径
再次运行 Reader、EvidenceLedger 或生成式 `COMPLETE`，会重复推理职责，并把 retrieval、证据消费
和回答错误重新混在一起。现有 OpenWorker `reader-lite` 又依赖 `access-outcome-v0.1`，不能被一次
未经验证的替换破坏。

## 决定

新增兼容隔离的 `agent-memory` profile，并将 P08 产品 transport 固定为：

```text
Codex → authenticated Streamable HTTP → /mcp → milai-mcp → Runtime
```

stdio 仅保留 OpenWorker 兼容、SDK 单测和本地协议调试，不计入 P08 产品验收。模型参数只有：

```text
query
previous_context_id（可选、不透明）
```

入站 Bearer credential 绑定 server-owned principal 和非空项目 scope；Runtime credential 与入站
credential 分离。身份、scope、authority、consistency 和预算由服务环境与启动参数绑定。该 profile 的
`milai_memory_resolve` 把现有 Runtime outcome 渲染为 `memory-evidence-context-v1`，只暴露：

```text
retrieval_status
context_id
有证明的 snapshot
有证明的 continuation
Reader-visible Evidence units
machine-readable warnings
requested/resolved budget profile
```

它不暴露 score、QueryIR、Binding、Sufficiency、Reader 草稿或最终答案。Runtime 的 `PARTIAL` 不被
翻译为答案语义不完整；只要存在合法可见证据且没有确定性 retrieval degradation，facade 即报告
`HIT`。`continuation: null` 表示 Runtime 没有给出 continuation assertion，不代表 frontier 已耗尽。

`reader-lite` 保留 stdio 原协议供 OpenWorker 兼容。正常 Codex HTTP path 的
`ModelBackend=none`。`/healthz` 只证明进程存活，`/readyz` 证明 Runtime capabilities 可访问，
`/mcp` 必须通过 Bearer 验证。

预算名称统一为：

```text
MCP_INTERACTIVE_STANDARD_V01
MCP_INTERACTIVE_WIDE_V01
MCP_RESEARCH_V01
```

旧 `OPENWORKER_USABILITY_WIDE_V01/V02` 仅为 deprecated alias，解析后的 canonical name 可见。

## 后果

- Host 负责普通回答 sufficiency、residual query 和最终答案。
- MiLAi 继续负责 scope、撤销、时间有效性、canonical currentness、routing、dedup 和审计。
- MCP Interactive 只保证 memory 可调用，不保证 Codex 必然调用；强保证部署使用 Host-prefetch。
- 本决定不改 Runtime API、数据库 Schema、Canonical writer 或权限语义。
- P08 的 Host 验收仅使用 Codex；Claude Code 只保留未来兼容示例，不是 PASS 前置条件。
- 旧 Product-08 Context 修复候选和 ADR-029 保留为 default-OFF 历史输入，不再拥有 P08 执行名称。

HTTP facade 回滚只需停止常驻服务；stdio `reader-lite` 兼容路径、Runtime 与数据库均无需迁移。
