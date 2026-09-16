# MiLAi OAuth DCR MCP 部署与使用

最新接入方向（2026-09-07）：用户选择复用AIGCIT Auth，已从规划进入增量实施。请先看
[HTTP-AIGCIT-AUTH-01设计与实施规划](../goals/HTTP-AIGCIT-AUTH-01_设计与实施规划_20260907.md)。
本页以下步骤仅适用于旧的MiLAi本地授权服务器/enrollment模式，不是AIGCIT接入操作说明。
新模式不在MiLAi签发OAuth token，不使用enrollment，也不能直接复用本页的同源AS检查器。
新接入已有本地实现及独立工程验证，部署步骤见[AIGCIT运行手册](aigcit-http-mcp.md)。
尚未公网部署或验证真人登录；此次没有恢复DNS订单或切换线上服务。

历史暂停状态：等待TXT的Certbot已取消，未签发证书，HTTP临时探针已删除；以下时间线保留，
其中“等待TXT”段落已被取消记录覆盖，不应再执行或复用旧challenge。

> 代码状态：`IMPLEMENTED CANDIDATE`  
> 当前公网状态：`BLOCKED — trusted HTTPS origin unavailable`

2026-09-07后续：用户选择DNS-01，既有Certbot账户已生成验证challenge，等待域名维护者添加
`_acme-challenge.milai.aigcit.com` TXT。当前没有已签发证书；不要新建重复订单或提前确认验证。
非root独立wheel暂存包的25项本地协议检查已通过，尚未安装线上。手动DNS签发仍需要后续
续期安排，不能将一次证书申请视为自动续期已配置。详见Goal第2.55节。

2026-09-07更新：443不可用，候选入口改为`https://milai.aigcit.com:7960/mcp`。本机7960、
7966、7969均空闲，三个端口的临时nonce探针经公网域名回到本机均通过，随后关闭；尚未完成
独立外网TLS验证。7968仍是原HTTP服务，OAuth AS discovery为404，未切换或签发公网用户。
当前需要可信域名证书及私钥文件路径，或DNS-01验证控制；不再要求开放443。执行记录见
[Goal第2.54节](../goals/MILA_V02_05_端到端通用记忆开发与泛化验证_GOAL_20260906.md#254-2026-09-07非443入口核验与oauth代理修复)。

以下2026-09-04数据是历史起点，不代表本次已重做对应检查：

2026-09-04 18:29 +08:00 的只读复核显示：Runtime 仍只监听 `127.0.0.1:28180`，现有 MCP
仍监听 `0.0.0.0:7968` 且 `/healthz` 为 200，本机没有 443 listener，现有 7968 服务的 OAuth
Authorization Server discovery 为 404。现有服务没有被本 runbook 或仓库示例修改。

## 用户侧最终体验

HTTPS 部署完成后，用户不配置、不复制 OAuth Token：

```bash
codex mcp add milai --url https://<受控域名>/mcp
```

当前 Codex 默认把无显式 Bearer 的 Streamable HTTP server 作为 OAuth server；首次添加会按
`AUTO` 策略执行 discovery，找不到 CIMD client 时使用服务端公布的 DCR endpoint 注册 Codex
OAuth client，并打开浏览器授权页。用户输入服务器管理员分配的一次性 enrollment code，检查
`codex-full` scopes 后点击 Approve。Access/Refresh Token 由 Codex 保存和刷新，不显示给用户。

若 `mcp add` 后没有立即打开登录：

```bash
codex mcp login milai --oauth-client-registration dcr
```

也可以在添加时强制本次登录只使用 DCR：

```bash
codex mcp add milai \
  --url https://<受控域名>/mcp \
  --oauth-client-registration dcr
```

这里的浏览器 Approve 是 OAuth 用户授权，不是“本机安装审批”；不需要在 MCP 服务器机器上
确认。DCR 自动注册的是 Codex client，enrollment code 才把这次授权绑定到已获准的 MiLAi
用户。

这与 AIGCIT 的机制同类，但用户身份来源不同：AIGCIT 使用其站点账户，当前 MiLAi candidate
使用一次性 enrollment code。

## 服务端配置

```bash
export MILAI_MCP_HTTP_PUBLIC_BASE_URL='https://<受控域名>'
export MILAI_OAUTH_DB='/var/lib/milai-mcp/oauth.sqlite3'
```

以上使用 gateway 的标准 HTTPS 443 端口；只有 gateway 确实在非标准 TLS 端口监听时，才在
用户 URL、public base URL 和 readiness 参数中一致加入该端口。backend 的 loopback `7968`
不是默认公网 HTTPS 端口。

本次不使用443，目标配置（尚未写入线上环境）为：

```text
MILAI_MCP_HTTP_PUBLIC_BASE_URL=https://milai.aigcit.com:7960
MILAI_OAUTH_DB=/var/lib/milai-mcp/oauth.sqlite3
```

使用[7960 Nginx候选模板](../../examples/codex-mcp/milai-oauth-7960.nginx.conf.example)时，
证书必须覆盖`milai.aigcit.com`且被用户客户端信任；模板中的证书路径为待填部署约定，并非
本机已存在文件。不能用临时或自签名证书冒充公网就绪；未取得证书前不要安装或reload模板。
无80/443可用时，采用已有有效证书或DNS-01，续期也必须安排相同可用的验证路径。

模板包含完整OAuth/MCP路由、精确公网Host、认证路径有界限流和无缓冲SSE；保持Origin原值，
不信任客户端转发头。请求访问日志不记录query/body/headers，错误日志可能包含query，须限定
文件读取权限与保留期，不把原始认证日志放入Git或交付报告。速率和body大小是候选配置，
不是已经完成压测的容量承诺；切换前以实际证书和后端执行`nginx -t`及外网readiness。

MiLAi OAuth edge已补齐精确Host/Origin允许列表，支持loopback后端接收保留公网Host的请求，
不会通过关闭DNS rebinding防护解决421。只把7960映射到现有明文7968不能提供HTTPS或OAuth。

继续配置既有 `codex-full` 固定 project/scope、break-glass inbound secret 和四个 Runtime role
credential。OAuth database 父目录必须为 `0700`，文件自动创建为 `0600`。

systemd 模板使用无特权 `milai-mcp` system account，从 root-owned `0600` 的
`/etc/milai/codex-full-mcp.env` 读取
`MILAI_AGENT_READER_TOKEN`、`MILAI_AGENT_SUBMITTER_TOKEN`、`MILAI_AGENT_REVIEWER_TOKEN` 与
`MILAI_AGENT_OPERATOR_TOKEN` 四个 Runtime API Bearer。禁止把 `runtime/.env` 直接载入 MCP
进程；该文件还包含 PostgreSQL role URL，而 MCP 不需要也不应获得数据库凭据。
Inbound break-glass token 保持在 root-owned `0600` 的
`/etc/milai/codex-full-public.token`，由 systemd `LoadCredential` 以只读凭据传给该账户。

安装 unit 前，必须先从已验证的 wheel 及 lock 创建 root-owned、非可写的
`/opt/milai/mcp-venv`，并创建 `milai-mcp` system account。不得让公网进程使用开发 checkout
的 `.venv`；当 uv 管理的 Python 解释器位于 `/root` 下时，这会迫使服务以 root
运行，也使部署依赖开发者 home。

`MILAI_MCP_HTTP_PUBLIC_BASE_URL` 必须是 origin，不能包含 path、query、fragment 或 userinfo。
启用 `MILAI_OAUTH_DB` 时，非 loopback HTTP origin 会在创建 OAuth database 前被拒绝；
`http://127.0.0.1:<port>` 仍可用于本地开发和协议测试。`https://36.140.33.19` 可以作为
origin，但公网证书必须包含该 literal IP 的有效 IP SAN，并由 Codex 所在机器信任的公开
信任链签发。否则应使用证书覆盖的受控 DNS 名称。

仓库中的
[`milai-codex-full-public.service.example`](../../examples/codex-mcp/milai-codex-full-public.service.example)
是尚未安装的 cutover 模板：它把 HTTP backend 收敛到 `127.0.0.1:7968`，通过 systemd
`StateDirectory` 提供 owner-only OAuth 持久目录，以无特权账户运行，并把外部身份固定为 HTTPS
origin。只有当
TLS gateway 与 backend 在同一主机时才能直接使用该 loopback 绑定；异机 gateway 需要网关
owner 提供受限的私网路由与源限制，不能把示例改回无保护的公网 backend 后直接发布。

启动后必须可读：

```text
https://<受控域名>/.well-known/oauth-protected-resource/mcp
https://<受控域名>/.well-known/oauth-authorization-server
```

Authorization Server metadata 必须公开 `/register`、`/authorize`、`/token`、`/revoke`，并声明
`code_challenge_methods_supported: ["S256"]`；`token_endpoint_auth_methods_supported` 和
`revocation_endpoint_auth_methods_supported` 必须包含 Codex native public client 使用的
`none`。

## Gateway owner 路由合同

公网 gateway 必须在同一个可信 HTTPS origin 原样转发以下 surface，不能只代理 `/mcp`：

```text
/mcp                                             MCP POST/GET/DELETE + SSE
/.well-known/oauth-protected-resource/mcp        RFC 9728 discovery
/.well-known/oauth-authorization-server          RFC 8414 discovery
/register                                        DCR
/authorize
/token
/revoke
/oauth/consent
/healthz
/readyz
```

不得改写 path、OAuth `Location` 或 `WWW-Authenticate`。必须保留 `Authorization`、`Accept`、
`Content-Type`、`Mcp-Session-Id` 和 `Last-Event-ID` 等请求/响应头；对 `/mcp` 关闭响应缓冲并
允许长连接 SSE。公网 80 只能用于受控 ACME challenge 或重定向到 HTTPS，不能承载 OAuth
Token、enrollment code 或 MCP Bearer。Gateway 应对 `/register`、`/authorize`、`/token`、
`/oauth/consent` 配置容量/速率保护；应用内的 client capacity 不是 Internet DoS 防护。

如果 gateway 与 MCP 不在同一主机，backend 路由和防火墙源限制也属于 gateway/network
owner 的责任。不要把 Runtime `28180` 暴露给 gateway 或公网。

## 无凭据公网 preflight

TLS 与 OAuth 配置启用后，从真实外部 client 网络执行：

```bash
cd /cra/memory/mx_memory/MiLAi-Product/integrations/mcp
uv run milai-oauth-readiness --base-url https://36.140.33.19
```

若使用 DNS，把参数替换为同一个 `MILAI_MCP_HTTP_PUBLIC_BASE_URL`。该命令使用系统 trust
store，不能跳过 certificate/hostname 校验；它检查 `/healthz`、`/readyz`、两份 discovery
metadata、精确 issuer/resource/endpoint、S256 和 unauthenticated `/mcp` challenge。它不执行
DCR、不创建 authorization request、不签发 Token、不调用 authenticated MCP tool，报告中的
`mutating_requests` 必须为 `0`。任何 `BLOCKED` 都不能当作上线成功。

## 创建用户 enrollment

服务器管理员执行：

```bash
cd /cra/memory/mx_memory/MiLAi-Product/integrations/mcp
uv run milai-oauth-user issue --agent-id user-a
```

通过安全通道把一次性 `enrollment_code` 交给用户。它只用于浏览器授权，不是 MCP/OAuth
Access Token。首次成功授权后状态变为 `ACTIVE`，同一个 code 不可再次使用。

查看：

```bash
uv run milai-oauth-user list
```

重新 enrollment（同时撤销旧 token）：

```bash
uv run milai-oauth-user issue --agent-id user-a --replace
```

撤销用户和全部 live OAuth token：

```bash
uv run milai-oauth-user revoke --agent-id user-a
```

## 标准请求链

```text
1. POST /mcp without token
2. 401 WWW-Authenticate: Bearer resource_metadata="..."
3. GET Protected Resource Metadata
4. GET Authorization Server Metadata
5. POST /register                         DCR creates Codex client
6. GET /authorize                        resource + state + S256 challenge
7. GET/POST /oauth/consent               real user approves
8. redirect to exact registered callback authorization code
9. POST /token                           verifier + resource
10. POST /mcp Authorization: Bearer ...  initialize/tools/list/call
11. POST /token grant_type=refresh_token rotating pair
```

DCR 只创建 client，不创建资源所有者。禁止删除第 7 步或把任意 DCR client 当成 MiLAi user。

## 2026-09-04历史部署阻塞

当前公开地址 `http://36.140.33.19:7968/mcp` 是明文端口映射。本机只有私网地址，无法控制
`36.140.33.19` 的公网 80/443；Let’s Encrypt 对 `36-140-33-19.nip.io` 的 HTTP-01 验证从公网
访问 80 超时。因此当前不能向用户发布仅 URL 的 OAuth 命令。

当前 host 虽有本地 Nginx port 80 listener，但公网 port 80 返回 gateway error，公网 443 TLS
握手也未成功；这不构成 certificate challenge 或 HTTPS MCP 所有权。解除阻塞需要云网关完成
以下一项：

- 将一个受控域名的 HTTPS 反向代理到本机 MCP backend；或
- 把公网 80/443 路由到本机并允许 ACME 验证，再由本机 Nginx 提供 TLS。

拿到可信 HTTPS origin 后，把 origin 写入 `MILAI_MCP_HTTP_PUBLIC_BASE_URL`，启用
`MILAI_OAUTH_DB`，重启服务并执行完整公网 Codex OAuth smoke。不得使用自签名证书、跳过
校验、明文 OAuth 或匿名 consent。

## 当前非443切换顺序（尚未执行）

1. 取得覆盖域名的可信证书，确认7960从独立外网可达；在7960配置TLS和到MCP backend的完整
   route surface，先验证候选配置，不再尝试开放443；
2. credential/service owner 轮换所有曾通过明文 7968 使用的 static/legacy Bearer，再启用 HTTPS
   public base URL 与 OAuth database；已有 Token 不能因“尚未观察到泄露”而视为安全；
3. 重启 MCP 后从外网运行 `milai-oauth-readiness`，结果必须为 `READY`；
4. 创建一个测试 enrollment，完成真实 Codex DCR/login、13-tool catalog、refresh 与 revoke
   smoke；
5. 以上全部通过后才发布 URL-only 用户命令。

本次仓库准备没有执行上述 gateway、credential、service 或 OAuth database 操作。回滚 OAuth
时同时移除 `MILAI_OAUTH_DB` 并恢复相匹配的 public-base/static-Bearer 配置；保留 SQLite 作
审计归档。启用 OAuth 却把 public base 改回非 loopback HTTP 会按设计拒绝启动。

HTTPS与服务切换完成后，在用户自己的Codex客户端执行以下命令；**当前URL仍未上线**。
使用新名称避免覆盖既有`milai`条目；若添加时已经完成授权，无需重复登录。

```bash
codex mcp add milai-oauth --url https://milai.aigcit.com:7960/mcp
codex mcp login milai-oauth --oauth-client-registration dcr
```

命令已核对[官方Codex MCP说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)及本地
`codex mcp login --help`。回调在运行Codex的客户端侧，不是要求MCP服务器再开放一个回调端口。
真实用户consent不可由服务测试替代；当前仅本地协议验证通过，公网readiness为BLOCKED。
