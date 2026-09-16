# ADR-037：标准 HTTP MCP Bearer principal binding 与 OAuth 边界

- 状态：ACCEPTED STATIC-BEARER FALLBACK；OAuth 边界由 ADR-038 继承
- 日期：2026-09-04
- Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## 问题

ADR-036 要求客户端同时发送 Bearer Token 和私有 `x-agent-id`。该头不是 MCP 或 OAuth 身份
原语，而且通用 `mcpServers` JSON 也不是 MCP 规范定义的安装协议。把这种客户端配置称为
“标准 HTTP MCP 注册”会混淆 Streamable HTTP wire protocol、客户端配置和 OAuth onboarding。

## 决策

远程凭据改为 credential-owned principal：每个服务器签发的随机 Bearer Token 唯一映射到
注册表中的 `agent_id` 和 `principal_id`。客户端只发送标准 HTTP Bearer header：

```text
Authorization: Bearer <token>
```

`agent_id` 只在服务端签发、列举、轮换和撤销操作中使用，不发送给客户端，不作为 MCP tool
参数。Token 摘要匹配后，由服务端恢复 principal 并传播到 Working State、Proposal 和 audit。

`mcpServers` 输出保留为兼容客户端配置，transport label 改为 `http`，但文档明确它不是 MCP
协议或跨客户端标准。Codex 的原生静态凭据路径是：

```bash
codex mcp add milai --url <url> --bearer-token-env-var MILAI_CODEX_TOKEN
```

## OAuth 边界

仅 `codex mcp add ... --url ...` 的自动登录体验需要标准 OAuth discovery/authorization，不能
由 JSON 外观提供。ADR-038 已实现用户登录、Authorization Code + PKCE、动态客户端注册和
refresh/revocation provider；当前公网服务仍是非 TLS IP 地址，因此尚不宣称公网 URL-only
OAuth onboarding。

在 HTTPS 身份、Authorization Server 和受治理用户注册完成前，服务继续 fail-closed 使用
预签发 Bearer Token。不得用匿名自注册或无认证 `/mcp` 模拟 OAuth，否则任意公网访问者将
获得 `codex-full` governance/destructive capability。

## 保留的不变量

- `PENDING → ACTIVE → REVOKED` 与自动 issue/register/revoke audit 保留；
- 明文 Token 只在签发结果出现一次，注册表与审计只含安全摘要/元数据；
- principal、tenant、project、scope、role、authority 不由模型或客户端参数选择；
- 一个端点仍绑定固定 tenant/project，不宣称用户数据隔离；
- Evidence、Canonical、Working State、revocation/deletion 和 Runtime schema 不变。

## 兼容与回滚

旧客户端额外发送 `x-agent-id` 时服务端不使用该值；升级后可以直接删除该头。回滚到 ADR-036
实现将重新要求旧头，因此需同时回滚客户端配置。此变更不含数据库 migration。
