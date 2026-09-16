# ADR-038：OAuth DCR URL-only MCP onboarding

- 状态：ACCEPTED IMPLEMENTATION / PUBLIC DEPLOYMENT BLOCKED
- 日期：2026-09-04
- Schema：`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

## 背景

AIGCIT 风格的 Codex 接入只配置 MCP URL。首次未认证请求收到 RFC 9728 Protected Resource
Metadata 地址，客户端发现 OAuth Authorization Server，再通过动态客户端注册（DCR）、
Authorization Code + S256 PKCE 和用户授权取得 Access/Refresh Token。用户不复制或管理
OAuth Token。

DCR 注册的是 Codex OAuth client，而不是资源所有者。AIGCIT 仍使用其站点账户识别最终用户。
MiLAi 没有现成账户/SSO，因此不能把 DCR 错误实现成匿名用户注册：`codex-full` 包含写入、
审核、撤销和 namespace cleanup，匿名授权会造成公网 full-control 泄露。

## 决策

MCP edge 新增持久 OAuth Authorization Server provider，与 Resource Server 同源部署：

```text
GET  /.well-known/oauth-protected-resource/mcp
GET  /.well-known/oauth-authorization-server
POST /register
GET  /authorize
POST /token
POST /revoke
GET/POST /oauth/consent
POST /mcp
```

标准链路为：

```text
Codex --url
→ 401 + resource_metadata
→ Authorization Server discovery
→ RFC 7591 DCR
→ Authorization Code + S256 PKCE + RFC 8707 resource
→ browser consent
→ Access/Refresh Token
→ authenticated Streamable HTTP MCP
```

资源所有者通过服务器预创建的一次性 enrollment code 登录 consent 页面。该 code 不是 OAuth
Access Token；它只用于一次用户授权，服务端仅存 SHA-256 摘要。未来可用企业 OIDC/SSO
替换这个登录边界，不改变 MCP/OAuth 客户端合同。

## 持久与安全合同

- OAuth client、pending authorization、authorization code、access/refresh metadata、用户与
  audit 持久化在 owner-only SQLite edge database；
- enrollment code、authorization code、access token、refresh token 只存 digest，不存明文；
- authorization code 5 分钟、access token 1 小时、refresh token 30 天；
- refresh 时旋转 access/refresh pair，旧 refresh replay 返回 `invalid_grant`；
- revoke 会撤销整个 token family；用户撤销或重新 enrollment 会同时作废该 principal 尚未
  交换的 authorization code 与全部 live token；交换时再次检查用户仍为 `ACTIVE`；
- redirect URI 只允许 HTTPS 或 loopback HTTP，拒绝 fragment/userinfo；
- discovery 必须如实公布 Codex native public client 使用的 `none` token/revocation
  endpoint authentication method；
- authorization 与 token request 都必须精确绑定 MCP resource audience；
- DCR、授权、签发、刷新、撤销、用户激活默认追加安全元数据 audit；
- static break-glass 和 ADR-037 server-issued Bearer 在迁移期可兼容，但不是 URL-only 用户路径。

## HTTPS 硬门槛

所有公网 Authorization Server endpoints 必须由可信 HTTPS origin 提供。当前
`36.140.33.19:7968` 只有明文端口映射，本机不能控制该公网地址的 80/443 challenge；
Let’s Encrypt HTTP-01 从公网访问 80 超时。因此实现已通过 loopback 协议测试，但不得把当前
HTTP 地址声明为 URL-only OAuth deployment。

上线需满足其一：

1. 给此主机分配受控域名，并把公网 80/443（或可信 HTTPS reverse proxy）路由到本机；或
2. 在现有网关配置受信任证书，将 HTTPS MCP/OAuth origin 反代到 loopback 7968 backend。

禁止以自签名证书、关闭 TLS 校验、HTTP issuer 或匿名授权绕过此门槛。

## 2026-09-07 补充：非标准 TLS 端口与代理 Host

443 不是 OAuth 的固定监听端口。受控域名可使用已映射的非标准 HTTPS 端口；当前候选为
`https://milai.aigcit.com:7960`。证书、外部可达性及真实用户授权仍须独立验收，本文不声明上线。

本地回归复现：绑定 loopback 的 MCP SDK 默认只接受 loopback Host；即使 discovery、DCR、
consent、Token 交换成功，保留公网 Host 的授权后 `/mcp` 请求仍返回 `421 Invalid Host header`。
OAuth edge 因此从**服务器已配置的 resource URL**导出精确 Host（含非默认端口）和 Origin
允许列表。网关保留匹配的公网 Host；不把外部 `Host` / `X-Forwarded-*` 用作允许列表或 issuer
来源，不关闭 DNS rebinding 防护，不允许任意域名或端口通配。OAuth 模式不接受调用方扩大
该 transport allowlist；未启用 OAuth 的既有传输路径不变。

该修复只覆盖 MCP transport 的 Host/Origin 检查，不把此检查当作用户认证、scope 或 CSRF
机制。健康检查可继续走 loopback；受认证 MCP 直连测试须发送配置中的精确 Host。
回归覆盖非默认 HTTPS origin 的完整协议链、正确 Origin，以及错误 Host/Origin/端口和伪造
转发头；这些使用临时 SQLite 和 ASGI 客户端，不是公网 TLS 或真人浏览器验收。

## Authority 与 Schema

OAuth 只确定 Host principal 和 scopes，不改变 Evidence/Canonical authority。tenant/project
继续由 server deployment 固定；DCR metadata、enrollment code 和 OAuth 请求都不能选择
Runtime role、project 或 Canonical authority。Runtime/PostgreSQL schema 无变化。

## 回滚

取消 `MILAI_OAUTH_DB` 即回到静态/服务器签发 Bearer verifier。保留 OAuth SQLite 作为审计
历史或在停服后归档。回滚不修改 Evidence、ClaimVersion、Working State 或 Runtime schema。
