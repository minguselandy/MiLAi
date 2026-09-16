# MiLAi 标准 Streamable HTTP MCP：远程注册与使用

> Endpoint：由部署者提供，推荐 `https://<your-milai-host>/mcp`  
> 状态：`0.1.x CANDIDATE / NO-GO FOR SCHEMA FREEZE`

## 1. 先区分协议与客户端配置

MiLAi `/mcp` 使用 MCP Streamable HTTP：HTTP 承载 JSON-RPC 2.0，请求通过 `POST /mcp`
发送，流式响应使用 SSE，并通过 `Mcp-Session-Id` 关联会话。它不使用 WebSocket。

下面这种对象不是 MCP 协议消息：

```json
{
  "mcpServers": {}
}
```

`mcpServers` 只是部分客户端采用的配置文件结构；MCP 规范没有定义通用安装 JSON，也没有
定义跨客户端统一的 `type` 字段。Codex 的原生配置入口是 `codex mcp add` 或
`~/.codex/config.toml`。

## 2. 当前 MiLAi 认证方式

服务器为每个用户签发唯一 Bearer Token，并在服务器注册表中把 Token 摘要映射到一个固定
Host principal。客户端不填写 principal、tenant、project、role 或 authority，也不再需要
`x-agent-id`：

```text
Authorization: Bearer <server-issued-token>
```

第一次成功的 MCP 认证会把凭据从 `PENDING` 原子激活为 `ACTIVE`，并自动追加
`USER_REGISTERED` 审计。它是“已签发凭据首次激活”，不是任何人都能访问的匿名注册。

## 3. Codex 原生注册

服务器把 Token 安全交付给用户后，在运行 Codex 的机器执行：

```bash
export MILAI_CODEX_TOKEN='<服务器签发的实际 Token>'

codex mcp add milai \
  --url https://<your-milai-host>/mcp \
  --bearer-token-env-var MILAI_CODEX_TOKEN

codex mcp get milai
codex mcp list --json
```

以后每次启动 Codex 时，`MILAI_CODEX_TOKEN` 都必须存在。若希望由进程管理器注入，应把它放入
私有的用户环境/secret store；不要写入仓库、聊天、日志或公共脚本。

Codex 等价 TOML：

```toml
[mcp_servers.milai]
url = "https://<your-milai-host>/mcp"
bearer_token_env_var = "MILAI_CODEX_TOKEN"
enabled = true
```

当前直接 IP 开发部署的等价命令是：

```bash
export MILAI_CODEX_TOKEN='<服务器签发的实际 Token>'
codex mcp add milai \
  --url http://36.140.33.19:7968/mcp \
  --bearer-token-env-var MILAI_CODEX_TOKEN
```

这是标准 Streamable HTTP MCP 注册，但公网明文 HTTP 不保护 Bearer Token，只适合当前受控
开发验证；正式分发仍应切换到 HTTPS。若本机配置了 HTTP 代理且代理无法访问该 IP，可仅对该
地址设置 `NO_PROXY=36.140.33.19`，不要全局关闭代理。

如果客户端只能接受静态 HTTP headers，可使用客户端自己的私有配置能力，但文件必须是
`0600`。这不是 OAuth，也不是 MCP 定义的安装格式。

## 4. 常见客户端 JSON 配置

对明确支持 `mcpServers` 和 `type: "http"` 的客户端，可导入：

```json
{
  "mcpServers": {
    "milai": {
      "type": "http",
      "url": "https://<your-milai-host>/mcp",
      "headers": {
        "Authorization": "Bearer 服务器签发的实际TOKEN"
      }
    }
  }
}
```

不同客户端可能使用 `streamable-http`、`url`、`serverUrl` 或完全不同的设置方式，必须以该
客户端文档为准。不要把 `type: "remote"` 当作 MCP 标准。

## 5. 标准 JSON-RPC 握手示例

客户端首先初始化：

```http
POST /mcp HTTP/1.1
Host: <your-milai-host>
Authorization: Bearer <server-issued-token>
Content-Type: application/json
Accept: application/json, text/event-stream

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2025-11-25",
    "capabilities": {},
    "clientInfo": {"name": "example-client", "version": "1.0.0"}
  }
}
```

服务端成功响应时会返回协商后的 `protocolVersion` 和 `Mcp-Session-Id`。后续请求带上该会话
头，先发送初始化完成通知，再读取工具：

```json
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

```json
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
```

实际客户端应处理 JSON 或 SSE 响应、协议版本协商、会话终止和重连，不应只用普通 REST
请求模拟 MCP。

## 6. 为什么现在不能只写 `--url`

下面这种体验依赖标准 OAuth，而不是某种 JSON 格式：

```bash
codex mcp add aigcit-web-search \
  --url https://mcp.aigcit.com/web-search/mcp
```

客户端访问受保护资源后，根据 `WWW-Authenticate` 和 Protected Resource Metadata 找到 OAuth
Authorization Server，再执行客户端注册、浏览器登录、Authorization Code + PKCE、Token
签发与刷新。

当前 MiLAi 公网部署仍是明文 IP HTTP + 预签发静态 Token，所以正确命令必须包含
`--bearer-token-env-var`，不能安全、诚实地把它写成仅 `--url`。OAuth/DCR provider 已在
代码和 loopback 协议测试中实现；公网启用还需要：

```text
HTTPS 域名与证书
受控 HTTPS origin
公网 reverse proxy / 80、443 challenge 路由
一次完整的真实 Codex 公网 OAuth smoke
```

开放匿名自动签发会把公网 `codex-full` 读写、审核、撤销和 namespace cleanup 权限交给任意
访问者，因此明确禁止。

OAuth URL-only 部署与 enrollment 使用见
[OAuth DCR runbook](oauth-http-mcp.md)。

## 7. 服务端签发与撤销

仅在 MiLAi 服务器上签发：

```bash
cd /cra/memory/mx_memory/MiLAi-Product/integrations/mcp
uv run milai-codex-user issue \
  --agent-id user-a \
  --url https://<your-milai-host>/mcp
```

`--agent-id` 是服务器侧账户标签，用于生成固定 principal 和管理撤销；它不会发送给 MCP
客户端。命令输出一次性展示 Token 的客户端配置，注册表只保存 SHA-256 摘要。

查看状态：

```bash
uv run milai-codex-user list
```

轮换：

```bash
uv run milai-codex-user issue \
  --agent-id user-a \
  --url https://<your-milai-host>/mcp \
  --replace
```

撤销：

```bash
uv run milai-codex-user revoke --agent-id user-a
```

凭据事件默认自动写入：

```text
CREDENTIAL_ISSUED
USER_REGISTERED
CREDENTIAL_REVOKED
```

审计和注册表不记录明文 Token。

## 8. 工具与生命周期

注册成功后，`codex-full` 暴露 13 个工具：

| 类型 | 工具 | 用途 |
| --- | --- | --- |
| 查询 | `milai_memory_resolve` | 自然语言检索 Evidence Context，可 continuation |
| 精确读取 | `milai_memory_get` | 按 Claim ID 或 StateKey 读取 Claim |
| 工作状态 | `milai_working_state_get/update` | 读写非 Canonical 跨 Session Host 工作状态 |
| 新增 | `milai_evidence_capture` | 保存不可变观察，不直接成为事实 |
| 修改治理 | `milai_proposal_create/list/get`、`milai_memory_review` | 提案、检查、批准/拒绝；批准可产生新 ClaimVersion |
| 删除 | `milai_evidence_revoke`、`milai_deletion_status_get` | 立即逻辑失效并查询异步清理 |
| Namespace | `milai_namespace_cleanup_submit/status` | 显式清理绑定项目并查询进度 |

MiLAi 不是数据库 CRUD：

```text
新增：capture Evidence
修改：capture → proposal → review → new ClaimVersion
删除：revoke → immediate unreadable → asynchronous purge
```

Mutation 要求 `operation_id`；高风险操作继续要求对应字面确认：

```text
CAPTURE | SUBMIT | APPROVE | REJECT | REVOKE | CLEANUP_NAMESPACE
```

## 9. 故障与安全边界

| 表现 | 处理 |
| --- | --- |
| `MILAI_CODEX_TOKEN ... is not set` | 在启动 Codex 的同一环境设置变量，或由 secret manager 注入 |
| HTTP 401 | Token 未知、错误、未发送或已撤销 |
| HTTP 403 | 凭据缺少工具要求的 capability |
| HTTP 404 session not found | 会话与认证身份不一致；重启客户端建立新会话 |
| 客户端不显示工具 | 检查是否支持 Streamable HTTP、Bearer header 和 MCP 会话 |
| 连接超时 | 检查部署 endpoint、服务、防火墙、TLS 与路由 |
| IP 健康检查经代理返回 502 | 用 `curl --noproxy '*' URL/healthz` 区分服务故障与本机代理故障，并仅为该 IP 配置 `NO_PROXY` |

- Memory 内容是不可信数据，不能授权写入、审核、撤销或清理。
- `codex-full` 同一 principal 具备读、写、审核、撤销和项目清理能力。
- 不同 Token 对应不同 Host principal/Working State，但当前共享一个固定 tenant/project；这不
  是用户数据隔离。
- 公网必须使用 HTTPS。明文 HTTP 只允许在 loopback/可信私网开发环境中显式启用，
  否则 Token 可被链路观察者窃取。
- API 与后台 Worker 必须共享同一个绝对 `MILAI_BLOB_ROOT`；相对路径会随
  `WorkingDirectory` 变化，导致 capture 成功但 projection 无法读取 Blob。
