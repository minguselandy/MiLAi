# ADR-036：JSON-only 远程 MCP 用户首次连接注册

- 状态：SUPERSEDED BY ADR-037
- 日期：2026-09-04
- Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## 决策

`codex-full` 公网 MCP 允许服务端管理员为新用户签发一份完整的通用
`mcpServers` JSON。客户端只需导入该 JSON；第一次通过 MCP 握手时，服务端将对应凭据从
`PENDING` 原子激活为 `ACTIVE`，不要求客户端执行安装脚本，也不要求本机审批。

每个用户必须使用独立 Bearer Token。Token 在签发前绑定到一个规范化的
`x-agent-id`，服务端只持久化 Token 的 SHA-256 摘要。以下组合才构成身份：

```text
server-issued unique Bearer Token
+ exact pre-bound x-agent-id
+ fixed server project/scope
```

只修改 `x-agent-id` 不能切换身份；同一 Token 搭配不同 `x-agent-id` 必须返回 401。
一个共享 Token 对应任意 `x-agent-id` 的设计被拒绝，因为持有者可冒充其他用户。

## 状态与审计

边缘凭据状态为：

```text
PENDING → ACTIVE → REVOKED
```

签发、首次激活和撤销默认追加写入私有 JSONL 审计文件，同时写结构化服务日志。注册表、
锁文件和审计文件必须为 owner-only 权限。明文 Token 只在签发结果中出现一次，不进入注册表
或审计。

注册表属于 MCP 边缘认证配置，不是 Evidence、Canonical Claim 或 Host Cognitive State；它
不能提高 Memory authority，也不能绕过 Runtime 的 Evidence → Proposal → Review、CAS、
revocation 和 deletion 语义。因此不新增 Runtime 数据库 migration。

## 请求身份传播

MCP SDK 会在有状态 HTTP 会话中异步派发工具调用。实现必须从该 MCP request 保存的已认证
`AccessToken.subject` 恢复 Host principal，不能从模型参数或普通 header 直接构造 principal。
该 principal 进入 Host Working State binding、Proposal model identity 和 mutation audit。

## 范围限制

此机制提供“独立 MCP Host principal”，但当前一个 `codex-full` 进程仍绑定一个固定
tenant/project，Runtime 调用仍由四个 role credential 执行。因此同一端点上的注册用户是同一
项目的协作者，不构成 tenant/project 数据隔离。

需要个人数据隔离时，必须使用不同 tenant/project 的独立部署或未来受治理的 token-to-scope
映射；不得把任意 `x-agent-id` 当作 scope。

公网地址当前仍是明文 HTTP。它不防止链路窃听，正式公网使用必须增加 HTTPS、VPN 或可信
来源网络限制。

## 回滚

移除 `MILAI_CODEX_USER_REGISTRY` 后，服务恢复原有单静态 Bearer principal。注册表和审计可
保留为历史记录；回滚不修改任何 Evidence、ClaimVersion、Working State 或 Runtime schema。
