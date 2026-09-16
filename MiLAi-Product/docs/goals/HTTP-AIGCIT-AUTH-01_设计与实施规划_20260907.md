---
document_id: HTTP-AIGCIT-AUTH-01
version: "0.3"
date: "2026-09-07"
status: IMPLEMENTED_CANDIDATE
scope: AUTHORIZED_INCREMENTAL_IMPLEMENTATION
authentication_direction: AIGCIT_AUTH_RESOURCE_SERVER
implementation_status: P1_P3_LOCAL_ENGINEERING_VERIFIED
public_deployment_status: AUTHENTICATED_PRIVATE_DEPLOYED_RESOURCE_ACTIVE
public_oauth_login_verified: false
candidate_resource: https://milai.aigcit.com:7960/mcp
new_model_requests_authorized: 0
new_model_requests_executed: 0
schema_status: 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE
---

# MiLAi 接入 AIGCIT Auth：OAuth 登录设计与增量实施规划

## 1. 决策与本轮边界

**用户要求修订：登录即用、各用户独立记忆。** 用户明确撤销单owner白名单产品限制，要求所有
经AIGCIT登录的用户均可保存自己的记忆。本Goal继续执行，但下文单owner/手动准入限制仅作
v0.2历史设计；新规范见[ADR-049](../adr/ADR-049-authenticated-private-memory.md)。部署显式启用
`authenticated_private`，依据受信issuer/sub和稳定部署namespace派生每用户project及principal。
无需用户提交sub或逐人批准；不能据client_id、请求字段或未核验JWT声明选择空间。
普通读取/State写入/Evidence capture均可启用；Canonical治理及破坏性工具仍不开放。
新增必验：同端点两个用户的读写/检索/引用/continuation并发隔离与冷恢复，不接管旧共享项目。
A05改为合法用户自动获得私人空间、禁用用户403；A12扩展为跨用户对象与检索隔离。
真人登录、刷新/重放/撤销仍独立验收；用户已报告外网验证通过，不再要求重复证明公网可达。

**v0.3实现与部署结果：** 私人空间模式已上线，策略v2，普通四项scope已登记active。完整MCP
263通过/4项默认跳过；新两模式真实PG2通过（包含私人空间原文检索和跨用户continuation拒绝），
旧模式真实PG另1通过；静态检查、类型检查、锁文件及打包通过。固定wheel摘要
`7e29cc4eff610632c0ed240d821a109f7572402e48abd26d84c3e017196a7c36`，新包位于
`/opt/milai-aigcit/releases/private-v1/venv`，旧安装保留。服务无需人工添加用户，客户端需授权
新增写scope。以下v0.2部署快照中的空白名单阻塞不再适用；完整真人refresh/replay/revoke及
新模式真人保存恢复尚未取得操作回执，因此不将整个Goal标记完成。

**v0.2历史部署快照（已由上述v0.3结果覆盖）：** 新DNS-01订单已成功签发
`milai.aigcit.com`可信证书（到期2026-12-06，手动续期）。独立`milai-https`容器监听7960，
代理非root、固定wheel安装的`milai-aigcit.service`至loopback7969；原7968及Runtime保持原状。
空准入名单`owners=[]`拒绝所有主体，部署暂沿用现有`milai`项目和`milai-product`任务配置，
不代表已批准新用户访问该项目。四项Runtime角色凭据单独交付，未加载数据库或旧公网凭据。
经过HTTPS CONNECT代理的独立公网出口`103.190.179.2`访问，TLS/health/ready/metadata成功、
无凭据MCP返回401。Auth真实登记返回200，另查精确resource状态为active、两个只读scope一致。
HTTPS就绪不再是阻塞；完整P4及P5/P6仍未完成：owner/sub与项目确认、真人授权、刷新/撤销、
保存恢复、受控切换及回滚验收待完成。当前Auth Discovery省略
`revocation_endpoint_auth_methods_supported`，严格预检因此BLOCKED，未将其默认算作支持none，
未修改检查器掩盖缺口。证据在Lab `artifacts/http-aigcit-auth-01/p4-https-20260907/`，
详细部署/停用/续期记录在工作区`milai-https-deployment.txt`。本轮没有模型请求。

采用与 EKDB **线上接入方式**一致的职责分工：AIGCIT Auth 负责账号、浏览器登录、用户同意和
OAuth 令牌签发；MiLAi 作为 MCP Resource Server，负责验证令牌、限定用户与项目权限，并调用
MiLAi 自有 Memory Runtime。**复用认证服务，不替换 MiLAi 记忆实现，不接入 EKDB 业务后端。**

初稿对应的用户要求为“生成设计规划文档”，当时只交付设计、只读核查和文档索引同步。不实现
代码、不安装依赖、不修改 Nginx/systemd/DNS、不注册 resource/client、不签发或撤销用户凭据，
不启动模型实验。本文件内的配置、命令和验收项均为后续安排，不能当成已上线证据。

**P0–P3历史实施快照（已由上述v0.3结果覆盖）：** 用户随后明确要求“详细阅读并执行”本文件，当时已推进
P0–P3的本地工程。上述只读限制是初稿交付历史，不再阻止本次已授权的实现。模型实验仍暂停，
未注册resource/client、未签发用户凭据、未修改共享服务。当前实现与证据范围见
[AIGCIT运行手册](../runbooks/aigcit-http-mcp.md)、[ADR-048](../adr/ADR-048-aigcit-resource-server-identity.md)
和Lab中的`studies/active/HTTP_AIGCIT_AUTH_01_IMPLEMENTATION_20260907.md`。
下文P0–P6与A01–A22仍是完整目标，不以已通过的局部工程检查缩小完成范围。

本地工程结果：MCP完整回归258通过、3项默认跳过（两个真实PG用例及认证校准已分别显式
运行通过）；真实PG最新两用例通过，含外部身份保存/冷恢复/CAS/提交后回执丢失/跨项目引用
拒绝及旧模式生命周期。非root安装包完成两次真实进程启动，公开发现、401和Runtime不可用
503符合预期。此结果不包含公网TLS、真实Auth用户token、DCR/refresh或P6用户验收。
P4–P6仍待执行；已确认的外部依赖为证书/DNS控制渠道、准入owner/project和独立外网/Auth抓取。

本设计替代 [主 Goal 第8.0节](MILA_V02_05_端到端通用记忆开发与泛化验证_GOAL_20260906.md)
旧的“MiLAi 自建授权服务器 + enrollment code”作为后续公网登录主线。ADR-038 的既有实现及
历史记录保留，不将新方案追认为已经实施，也不自动恢复已取消的 Certbot 订单。

实施须遵循[Lean V1实施合同](../reference/MiLAi_Lean_V1_实施合同.md)的Remote Access Gate、
[ADR-037身份边界](../adr/ADR-037-standard-http-mcp-bearer-principal-binding.md)及
[ADR-038既有OAuth合同](../adr/ADR-038-oauth-dcr-url-only-mcp-onboarding.md)。身份、权限和撤销
变化先通过新的ADR；本文是提案，不修改冻结逻辑架构或将原ADR静默改成另一种语义。

当前可用交付是：**用户通过 AIGCIT 账号授权 MCP 客户端后，自动使用自己的私人记忆空间，
按实际授权 scope 读取、保存和恢复任务记忆，无需管理员逐人开通。**独立开户平台、网页控制台、
Billing、第三方 Memory 后端、Hint/图谱/Reviewer 扩张均不进入首版。

## 2. 已核查事实与待验证事项

### 2.1 AIGCIT Auth 与 EKDB

本次读取了 [Auth 文档中心](https://auth.aigcit.com/docs)、
[网页登录指南](https://auth.aigcit.com/docs/login-quickstart)、
[MCP 接入指南](https://auth.aigcit.com/docs/resource-server-quickstart) 和
[完整参考](https://auth.aigcit.com/docs/reference)，并只读查询公开元数据。观察日期为2026-09-07；
执行时仍须重新核对运行态，文档快照不等于长期配置保证。

| 项目 | 观察结果 | 结论边界 |
|---|---|---|
| Auth issuer | `https://auth.aigcit.com` | 使用独立授权服务，不要求在 MiLAi 主机再部署 Auth |
| EKDB resource 状态 | `https://zhishi.aigcit.com/mcp`，`active=true`，`kb.read kb.upload` | 证明登记已生效，不代替实际登录/工具验收 |
| EKDB Protected Resource Metadata | 只声明上述 Auth issuer | 本地示例 `dual` 不能被当作线上生效值 |
| EKDB 网页配置接口 | `oidc=true`；两种密码兼容入口也报告开启 | OIDC 存在，不代表只有一种登录方式 |
| Auth Discovery | 有 DCR、S256、JWKS；业务 access token 使用 ES256 | 不复用 EKDB 的本地 HS256 密钥或 OAuth SQLite |
| MiLAi 候选 resource | 状态接口返回404、`status=unknown`、`active=false` | 尚未登记；不说明登记请求一定能成功 |

公开核验入口：[EKDB resource 状态](https://auth.aigcit.com/resources/status?resource=https%3A%2F%2Fzhishi.aigcit.com%2Fmcp)、
[EKDB MCP 元数据](https://zhishi.aigcit.com/.well-known/oauth-protected-resource/mcp)、
[EKDB 登录配置](https://zhishi.aigcit.com/api/auth/oidc/enabled)、
[Auth Discovery](https://auth.aigcit.com/.well-known/openid-configuration)、
[MiLAi 候选 resource 状态](https://auth.aigcit.com/resources/status?resource=https%3A%2F%2Fmilai.aigcit.com%3A7960%2Fmcp)。

借鉴 EKDB 的 issuer/JWKS、PKCE、资源 audience、请求身份与数据库权限分工；不照搬其密码转发
登录、前端存储令牌或缺少逐工具 scope 检查的本地代码路径。后者是本地源码发现，未用线上
缺权限令牌验证，不能直接报告为线上漏洞。

### 2.2 MiLAi 当前代码起点

| 已有代码 | 可复用部分 | 必须调整的部分 |
|---|---|---|
| [http_transport.py](../../integrations/mcp/src/milai_mcp/http_transport.py) | 固定 resource、scope digest、标准 Bearer、HTTPS origin 校验 | 当前 binding 同时要求静态 secret；`required_scopes` 和 `access_token()` 默认使用整个 profile 的 scope，不能原样用于外部 JWT |
| [server.py](../../integrations/mcp/src/milai_mcp/server.py) | MCP SDK、请求 ContextVar 且 finally reset、四角色 Runtime 客户端、13工具 | HTTP 入口选择外部 verifier；逐工具权限；不能在 HTTP 身份缺失时回退到默认 Host |
| [oauth_provider.py](../../integrations/mcp/src/milai_mcp/oauth_provider.py) | 保留为原有本地模式与历史回归 | AIGCIT 模式不安装其 consent/DCR/token 路由，不把 enrollment 当 AIGCIT 登录 |
| [deployment_readiness.py](../../integrations/mcp/src/milai_mcp/deployment_readiness.py) | 系统 TLS 信任、拒绝重定向、有界响应、无凭据检查 | 当前强制 AS 与 MCP 同源，且写死 `/register` 等路径；外部 AS 必须独立发现和核验 |
| [7960 Nginx 模板](../../examples/codex-mcp/milai-oauth-7960.nginx.conf.example) | TLS入口、精确Host、无缓冲MCP代理 | 当前模板面向本地AS；外部模式应采用独立模板，不代理或伪造Auth登录/签发端点 |

原有测试成绩只属于各自交付范围，本文件不将其标记为 AIGCIT 接入 PASS。初稿核查未运行产品
测试；后续本地实现的直接测试已执行，范围与结果见第1节及独立实施记录。
底层 Evidence、Working State、Canonical、CAS、撤销和 PostgreSQL 权限仍遵循既有合同。

### 2.3 网络现状与证据强度

2026-09-07 15:08 +08:00 本机监听检查：`7960/7966/7969` 空闲；`7968` 是共享 MiLAi MCP，
监听 `0.0.0.0`；Runtime 在 `127.0.0.1:28180`；没有443监听。7961–7965及7967的既有监听不属于本任务。
用户已明确无法开放公网443，本设计不再把开放443列为必需条件。

预期路径 `/etc/letsencrypt/live/milai.aigcit.com/fullchain.pem` 与 `privkey.pem` 本次均不存在。
此前 DNS-01 订单已取消、未签发证书；历史同机公网域名回环探针不是独立外网 TLS 证明。
Auth 状态接口能接受候选 URI 的查询，也**不证明其注册抓取器允许7960或能连接本机**。

## 3. 目标架构与两种登录的区分

```text
MCP 客户端 ── HTTPS ──> MiLAi :7960 /mcp
     │                    │ 未认证：401 + resource_metadata
     │                    └─> 公开资源元数据声明 AIGCIT issuer
     ├─ 浏览器 ──────────> auth.aigcit.com：登录、同意、签发
     └─ 带 access token ─> MiLAi：验签 → 本地准入 → tool scope → 项目边界
                                                │
                              127.0.0.1:7968 MCP → 127.0.0.1:28180 Runtime
```

### 3.1 首版仅实现 MCP OAuth 接入

MCP 客户端负责 discovery、客户端注册、PKCE、浏览器回调、令牌保存和刷新。MiLAi 是资源服务器，
**无需为了 MCP 登录再建设网页登录页、OIDC callback 或应用 session**；也不需要给 MiLAi MCP
预先填写 EKDB 的 `OIDC_CLIENT_ID`。用户密码只交给 Auth，不经过 MiLAi。

DCR 创建 OAuth client，不创建 MiLAi 用户或项目权限；Auth 的用户同意也不能将普通账号变成
MiLAi 管理员。业务请求携带绑定 MiLAi resource 的 token，不能混入网页登录用的身份 token。

### 3.2 网页 OIDC 是后续独立增量

若以后确实建设 MiLAi 管理界面，再为该网页注册独立 client 与精确 HTTPS callback，采用
`openid profile` 登录和自己的安全 session。它与 MCP 的业务 resource/scopes 分开，不复用
EKDB client ID，不把应用 session cookie 当成 MCP Bearer。本阶段不实现此路径。

## 4. 对外协议与配置合同

### 4.1 固定地址

| 项目 | 本阶段候选值 |
|---|---|
| Public origin | `https://milai.aigcit.com:7960` |
| MCP resource / token audience | `https://milai.aigcit.com:7960/mcp` |
| Protected Resource Metadata | `https://milai.aigcit.com:7960/.well-known/oauth-protected-resource/mcp` |
| Authorization issuer | `https://auth.aigcit.com` |
| AS metadata | `https://auth.aigcit.com/.well-known/oauth-authorization-server` |
| JWKS | 由受信任issuer的Discovery确认，当前为 `https://auth.aigcit.com/.well-known/jwks.json` |

MCP端点与resource首版使用同一个精确地址，不增加共享网关路径别名。非默认端口不可丢失；
禁止前缀audience匹配、把HTTP7968作为备用audience、自动跟随重定向改变issuer/resource。

MiLAi 只需公开 `/mcp`、资源元数据及脱敏 `/healthz`、`/readyz`。AIGCIT模式不在MiLAi发布
本地AS discovery、`/register`、`/authorize`、`/token`、`/revoke`、`/oauth/consent`，也不将
这些路径反代成Auth的镜像。AS地址从已验证的外部Discovery取得，不能沿用同源路径拼接。

首版目标资源元数据（下面scope为拟议名称，登记前必须验证Auth的命名规则）：

```json
{
  "resource": "https://milai.aigcit.com:7960/mcp",
  "authorization_servers": ["https://auth.aigcit.com"],
  "scopes_supported": [
    "milai.memory.read", "milai.state.read",
    "milai.state.write", "milai.evidence.capture"
  ],
  "bearer_methods_supported": ["header"]
}
```

上述是完成普通读取/检查点保存增量后的目标。初次只读pilot只发布前两个scope；未实现、未启用的
治理能力不得先放入元数据。客户端可能请求全部公布scope，元数据不是任意扩权的展示清单。

### 4.2 外部认证配置（本地CLI已实现，尚未公网部署）

```dotenv
MILAI_MCP_AUTH_MODE=aigcit
MILAI_MCP_HTTP_PUBLIC_BASE_URL=https://milai.aigcit.com:7960
MILAI_AIGCIT_ISSUER=https://auth.aigcit.com
MILAI_AIGCIT_BINDINGS_FILE=/etc/milai-aigcit/bindings.json
```

实现时明确三种模式：`legacy`、`local-oauth`、`aigcit`。未配置新字段的旧部署沿用现有兼容规则；
新AIGCIT部署必须显式选模式。AIGCIT模式混入 `MILAI_OAUTH_DB`、旧远程注册表或公网静态
Bearer配置时启动报错，不自动串联verifier，也不保留“JWT失败就试旧密钥”的公网后门。

将固定资源/项目绑定与静态凭据校验解耦，避免为满足当前32字符校验生成一个无用途的secret。
可信principal来自第5节映射，不继续要求一个全用户共享的 `MILAI_CODEX_PRINCIPAL_ID`。
仍保留部署固定scope及必要的Runtime角色凭据；不得加载包含数据库密码的整个Runtime `.env`。
上述字段已由本地CLI配置测试确认；部署示例还包含默认只读的
`MILAI_AIGCIT_ENABLED_SCOPES`。本地实现不代表这些字段已写入线上或已对真实用户生效。

## 5. 身份、项目与逐工具权限

### 5.1 首版一端点、一项目、一个明确准入的owner

请求身份链为：已验证 `(issuer, sub)` → 服务端准入记录 → 稳定内部principal → 固定tenant/project。
`client_id`记录OAuth客户端，不能作为用户ID、worker委托证明或项目选择依据。当前Auth不提供
可信worker委托身份，本阶段不引入token exchange或从header自报worker身份。[Auth参考](https://auth.aigcit.com/docs/reference)

准入文件是MiLAi自己的最小部署授权配置，不是新账号系统。包含配置版本、issuer、已核验sub、
内部principal、固定项目标识、允许scope集合和enabled状态；不包含token、密码或client secret。
从认证上下文或受信任运维渠道确认sub，不把未验签JWT解析结果或模型自报ID作为授权依据。

- 有效Auth token但未准入：明确403；不自动创建用户、绑定现有owner或开放项目。
- tenant由Runtime凭据绑定，project与scope由部署配置限定；准入文件与之不符则拒绝启动/请求。
- 首版不宣称多人私有Memory：同项目Canonical/Evidence现有可见性并非按sub自动分区。
- 两个测试主体只用于隔离负向验证；多人真实开通需另过共享与隔离门，不能仅往允许列表追加UID。
- 同一sub换客户端或刷新token，内部principal不变；client_id、jti、kid和令牌字节不得进入State主键。
- AIGCIT映射到旧principal须有明确owner确认和审计；默认不重绑旧用户数据。保持历史State、
  proposal和操作回执，不把身份映射变化造成的新命名空间误报为“旧记忆丢失”。

准入文件由部署维护者原子更新：专用目录`root:milai-mcp`、0750，文件同属组、0640，MCP账户
仅可读、不能自行改授权；不为此放宽其他秘密文件或现有目录的权限。私钥和Runtime凭据仍按
独立0600/受控credential交付。每个受保护请求核验当前策略版本；文件缺失/损坏/无法读取时
拒绝受保护操作，不无限期使用旧的准入快照。

### 5.2 权限必须取交集

```text
实际可执行能力
  = token实际授予scope ∩ 本地主体允许scope ∩ 部署已启用能力 ∩ Runtime现有权限
```

scope映射由服务器维护，不能把 `HttpPrincipalBinding.access_token()` 的全profile scope
复制给任意外部JWT。JWT中自报的tenant/project/role/内部scope digest等字段不参与可信绑定。
分别保留已验证原始scope与有效权限供脱敏审计，不伪造客户端被授予更多scope。

13个现有codex-full工具的拟议映射如下；外部OAuth名字与现有Runtime capability分离，不修改
Runtime capability命名或Schema。

| 现有工具 | 必需外部scope | 首版策略 |
|---|---|---|
| `milai_memory_resolve`、`milai_memory_get` | `milai.memory.read` | 启用，仍检查来源与项目资格 |
| `milai_working_state_get` | `milai.state.read` | 启用，principal与可信任务绑定 |
| `milai_working_state_update` | `milai.state.write` | 工程门通过后启用；版本/CAS/幂等不变 |
| `milai_evidence_capture` | `milai.evidence.capture` | 工程门通过后启用；不等于Canonical批准 |
| `milai_proposal_create` | `milai.proposal.create` | 默认不发布；单独批准治理扩展后启用 |
| `milai_proposals_list`、`milai_proposal_get` | `milai.memory.read` | 首版不发布治理工具；未来仍限定project |
| `milai_memory_review` | `milai.proposal.review` | 默认关闭；scope和confirmation都不能替代当前治理授权 |
| `milai_evidence_revoke` | `milai.evidence.revoke` | 默认关闭；启用时保留显式撤销语义 |
| `milai_deletion_status_get` | `milai.memory.read` | 首版不发布；未来仍需精确对象资格检查 |
| `milai_namespace_cleanup_submit`、`milai_namespace_cleanup_status` | `milai.operations.admin` | 默认关闭，不随登录授予 |

工具清单由部署启用项与当前请求权限决定，不能修改全局 `hidden_tools` 造成并发串权。
隐藏工具不是权限控制：直接调用隐藏/未授权tool也必须在业务handler和Runtime调用之前拒绝。
未知tool按协议拒绝；新增已注册tool如果没有显式scope映射，构建检查失败，不能默认放行。

HTTP身份丢失必须fail closed；仅保留明确的stdio/embedded本地路径兼容。不能因为SDK或线程
上下文未传到handler，就回退成默认owner。对旧协议会话和当前SDK支持路径都验证每请求身份，
不能把MCP Session ID、Cookie、连接复用或首次initialize结果当作持续授权。

## 6. JWT、JWKS、撤销与故障语义

### 6.1 验证边界

复用成熟JWT密码库，不自行实现椭圆曲线签名。运行包显式声明所用依赖并更新锁，不能只依赖
SDK间接安装。实现范围仅在MiLAi MCP integration；不导入EKDB代码包。

- 只允许ES256业务access token，核验`typ=at+jwt`并按固定可信JWKS选kid；拒绝HS256、none、
  未知算法、身份token和私钥材料。此token类型要求需与真实Auth签发样本一起验收。
- issuer与配置精确匹配，aud为当前精确resource字符串；身份token、EKDB token、错误端口或
  路径、缺aud均拒绝。首版不放宽为前缀或多audience别名。
- 要求合理类型且未过期的exp、非空sub/client_id；验证适用的nbf/iat时间约束，使用显式小幅
  时钟容差。scope按空格解析；缺scope不会获得默认scope。
- 忽略token头中的jku/x5u等外部取钥地址；未知issuer不能触发联网。JWKS端点由受信配置确认，
  不接受请求提供URL，不跟随跨域/降级重定向，不关闭证书校验。
- 业务身份只来自验证结果与本地策略。ContextVar设定后必须finally reset，异步、线程池、
  取消、错误和长连接都不能残留上一主体的身份。

### 6.2 默认低延迟路径

暖缓存验签不调用Auth、不请求userinfo、不启动模型；只在受控JWKS刷新时访问网络。
采用共享异步HTTP连接和有限缓存：初始候选JWKS TTL为600秒、未知kid刷新冷却30秒、网络超时
3秒、响应上限256KiB；按issuer合并并发刷新，限制未知kid负缓存条数。不用全局锁串行化
所有Memory读取，不对每个随机kid单独放行一次网络请求。这些是待校准边界，不是已达SLO。

缓存策略必须定义删除key的生效上界：刷新后从JWKS移除的key不再接受；缓存超出允许期限且
刷新失败时拒绝，不能无限期使用历史key。仍在有效缓存期内的合法key可以按策略验签，
但该可用性取舍不等于全局账号撤销立即同步。

### 6.3 不混淆三类撤销

| 操作 | 必须如实表达的效果 |
|---|---|
| Auth登出浏览器会话 | 不等于撤销已签发的MCP access/refresh token；客户端也须清理自己的登录态 |
| Auth撤销应用连接/refresh family | 不承诺已有自包含access token立即失效；当前文档寿命为900秒，执行时以真实exp/签发配置核验 |
| MiLAi禁用本地主体或收窄权限 | 在策略更新确认后的新请求上拒绝，不等待JWT自然过期；既有MCP连接也不能绕过 |

本地即时准入撤销是公网门槛，不能沿用本地opaque token测试来证明外部JWT撤销即时性。
普通读取已送到客户端的内容无法追回；已进入Runtime事务的操作按现有事务结果收尾，不承诺
事后回滚。高风险能力本版默认关闭；未来开放时需明确策略检查与提交之间的并发撤权边界。
若要求Auth中心撤权在所有资源服务器即时生效，须另行获得可靠推送/在线状态协议与验证，
不能假设当前已有可用的introspection接口。[撤销边界参考](https://auth.aigcit.com/docs/reference)

### 6.4 对外错误

| 情况 | 响应与行为 |
|---|---|
| 无Bearer、坏签名、错iss/aud、过期 | 401，保留正确的 `WWW-Authenticate` 发现入口 |
| 有效身份但未准入/本地禁用 | 403，固定安全错误码，不泄漏其他用户或项目 |
| 缺tool scope | 优先403 `insufficient_scope`；SDK已发送200时返回明确MCP错误，handler执行次数必须为0 |
| JWKS或准入策略无法可靠取得 | 有界503/明确认证依赖不可用；不降级匿名、静态token或默认owner |
| Runtime不可用 | 就绪降级及正常业务失败语义；不伪装为没有记忆 |

不在错误正文或日志记录Bearer、密码、授权码、refresh token、Cookie、完整请求query或记忆正文。
审计记录request ID、内部principal、client ID、策略版本、tool、scope判定、Runtime操作ID和
固定reason code；不能将外部Auth token转发给Runtime，Runtime仍使用专用角色凭据。

## 7. 当前网络下的部署方案

### 7.1 首选：7960可信HTTPS，7968收敛到loopback

域名仍用 `milai.aigcit.com`；本机Nginx在7960终止TLS，代理到 `127.0.0.1:7968`，Runtime
保持 `127.0.0.1:28180`。不抢占其他进程，不把既有MCP临时改成匿名服务。

证书采用已有可信域名证书或DNS-01；后者不依赖公网80/443，但需要DNS维护权限及可执行的
续期方案。历史订单已取消，实施时新建challenge，不能复用旧TXT值。仅由证书受控路径加载
私钥；未取得证书前不安装引用不存在证书的Nginx站点。[DNS-01说明](https://letsencrypt.org/docs/challenge-types/)

同机反代必须保持固定公网Host（含7960）及真实Origin，移除不可信转发身份头；MCP关闭缓存、
响应缓冲和透明重试，保留必要认证/协议头。复用现有Host安全修复，但要将其从“本地OAuth
provider启用”条件解耦，使外部verifier模式同样生效；不能顺便安装本地token endpoint中间件。

生产部署使用非root账户、不可写安装包、专用凭据和备份目录。切换前保存精确unit/drop-in/
代理文件和包摘要；不复制或回滚整个开发工作区。已有明文使用过的凭据按限定对象轮换。

### 7.2 必须有两个外部视角

1. 真实客户端网络：DNS、TLS链/域名/有效期、7960连通、资源元数据与MCP挑战正确。
2. Auth服务器的resource登记抓取：确实读到相同元数据并激活相同URI/scopes。

同机回环、GET状态查询接受URI、AS可从本机访问，均不能替代这两项。特别核验Auth对非默认
端口的URI规则、SSRF抓取策略及出站限制；未获证明前登记为待验证依赖，而非“必然可注册”。

### 7.3 只有证据阻塞首选时才采用网关备选

若客户端或Auth侧确实不能访问7960，可由已有443公网网关承载专用受控MiLAi域名，并经安全
隧道/私网路由到本机。需要网关owner提供权限与隔离；不自行使用Auth/EKDB主机，不借其证书，
不把公网明文HTTP回源当安全隧道。新origin会改变audience、注册与客户端配置，须整体重验。
本设计不要求现在开放本机443，也不在文档阶段操作网关。

## 8. 资源登记、客户端登录与迁移

### 8.1 登记顺序

先部署正确元数据并完成可信HTTPS预检，再向Auth登记**MiLAi自己的resource**，最后查询精确
状态确认 `active=true` 和实际scope集合。Auth的自助登记范围、元数据自证及权限名称规则以
运行时为准；不要复用EKDB resource/scopes，也不要通过修改Auth全局配置绕过校验。

以下是**实施阶段才允许执行的写操作示意，本轮未执行**：

```bash
curl --fail-with-body https://auth.aigcit.com/resources/register \
  -H 'Content-Type: application/json' \
  --data '{"resource":"https://milai.aigcit.com:7960/mcp"}'
```

登记响应和GET `/resources/status`分别留存脱敏结果；不能把HTTP200单独视为active。
登记资源不创建用户授权，DCR也不授予项目权限。调整scope需要先实现和验收，再更新元数据与
登记；旧token不自动获得新scope，新请求仍受本地当前策略约束。

### 8.2 用户侧目标体验

HTTPS、登记、准入及安全门通过后，在**用户自己的客户端机器**添加独立名称，避免覆盖现有
`milai`配置；不填写共享Bearer或EKDB client ID：

```bash
codex mcp add milai-aigcit --url https://milai.aigcit.com:7960/mcp \
  --oauth-resource https://milai.aigcit.com:7960/mcp
codex mcp login milai-aigcit --oauth-client-registration dcr
```

第二条只在添加后未完成登录时执行。浏览器应进入 `auth.aigcit.com`，核对MiLAi资源与实际
权限后同意，客户端保存和刷新token。首轮用已支持的DCR验证；CIMD不作为必须开发的前置。
回调监听在客户端机器，通常是loopback临时端口，不需要MiLAi服务器开放443。远程SSH运行CLI
而浏览器在本机时，须明确固定监听端口与SSH转发，不能将远端localhost当作用户机器。
这些步骤依据 [OpenAI Codex MCP文档](https://learn.chatgpt.com/zh-Hans/docs/extend/mcp)，并核对了
本机 `codex mcp add/login --help`；本轮未执行add/login，不更改用户客户端配置。

### 8.3 与旧模式隔离迁移

旧的static/registered bearer与本地OAuth保留为独立、明确选定的兼容模式；AIGCIT公网端点不
同时接受这些凭据。测试阶段采用隔离端口/配置/合成项目，完成后在维护窗口切换既有入口。
旧OAuth数据库、身份映射和Memory数据保留；不自动转换旧token或猜测旧owner对应哪个AIGCIT sub。

## 9. 增量开发安排与停止条件

时间是单人专注工程估算，不是完成承诺；DNS/网关权限、真实用户同意的等待单列。不使用模型
实验来验OAuth，不因为缺证书停止可独立进行的本地安全工程。

| 阶段 | 交付内容 | 最小出口证据 | 预计工程量 |
|---|---|---|---|
| P0 基线与合同 | pin当前包；确认owner/sub获取方式、项目、拟议scope、外部端口规则；新建拟议ADR并审定权限变化 | 模式/身份/撤销决策及测试映射明确；无线上修改 | 0.5天 |
| P1 外部认证最小切片 | 显式auth mode、受信issuer、异步有界JWKS、ES256 verifier、本地准入、独立AS元数据 | 离线合法/非法JWT和公开发现测试通过；未准入主体拒绝 | 0.5–1天 |
| P2 逐工具授权与连续性 | scope交集、HTTP身份fail closed、工具映射、并发身份、State与幂等稳定绑定 | 有效低权限token能读而不能写；伪造/未授权handler和Runtime调用均为0 | 0.5–1天 |
| P3 真实Runtime与可部署包 | 独立PG项目生命周期、准入撤销、缓存/故障检查、locked包门、非root安装验证 | 真实PG测试与新进程恢复通过，旧模式回归通过；代码候选可交付 | 0.5–1天 |
| P4 HTTPS与Auth登记 | 新外部AS代理模板、证书/续期、外部客户端预检、资源登记与状态核验 | 独立外网TLS通过；Auth资源active，issuer/aud/scopes一致 | 0.5天＋外部等待 |
| P5 真实用户只读pilot | 专用测试主体/客户端；真人DCR登录、首次只读、刷新及负向验收 | 登录与read-only tool成功；测试令牌不泄漏，未测项不计PASS | 0.5天 |
| P6 普通保存与正式交付 | 启用获准的State写入/Evidence capture；保存—退出—恢复；受控切换、回滚演练与用户验收 | 回执/CAS/恢复正确，本地撤权新请求拒绝，真实使用主体成功 | 0.5天 |

P1–P3可在网络交付等待期间推进；P5必须在P2/P3/P4通过后进行。P6不自动开启review/revoke/
namespace cleanup；完整治理工具如需公网启用，另经当前授权和对应直接测试，不以首版登录
成功顺带放行。初版约3.5–5个工程日，按实际缺陷调整，不为满足估算减少安全出口。

## 10. 文件级改造清单（原计划；本地实现见第1节）

| 位置 | 最小计划改动 |
|---|---|
| `integrations/mcp/src/milai_mcp/aigcit_auth.py`（拟新增） | issuer/claim校验、JWKS缓存、外部TokenVerifier；安全错误与审计 |
| `integrations/mcp/src/milai_mcp/auth_policy.py`（拟新增） | owner准入、稳定principal、有效scope、逐tool映射；只读原子策略加载 |
| `http_transport.py` | 分离资源描述与静态secret；真实granted scopes；外部AS AuthSettings |
| `server.py` | 模式装配、请求级权限门、HTTP缺身份拒绝、Host防护解耦、按请求目录过滤 |
| `deployment_readiness.py` | 增加外部AS检查分支，分开TLS/配置/登记/登录状态；旧本地模式不误报 |
| `pyproject.toml` / `uv.lock` | 显式JWT依赖与锁；不顺带升级MCP协议版本或重写传输 |
| `tests/test_aigcit_auth.py`等（拟新增） | 下节完整负向矩阵、并发、过期与缓存失效、入口配置测试 |
| 现有真实PG MCP测试 | 新身份到公开Runtime链路、跨scope拒绝、State/幂等/CAS连续性 |
| `examples/codex-mcp/` | 独立AIGCIT env/service/Nginx示例，不覆盖现有本地OAuth示例 |
| `docs/adr/`、contracts、runbooks | 新身份/权限/撤销ADR与验收合同；明确旧模式适用范围及新部署步骤 |

上述新增模块是代码组织建议，不要求为每项机制拆一个服务。首版不修改Runtime或Canonical
Schema；若实现发现必须变更Runtime授权语义，先补ADR和真实PG设计，不能在适配层绕过。
源码与测试不引用Lab、EKDB或其他第三方Memory包。执行证据与Goal历史产物放Lab，不混入产品包。

## 11. 验收矩阵

初稿所有行均为 `NOT_RUN`。当前本地证据与剩余范围见实施记录的逐项审计；下表保留完整验收
要求。mock/ASGI、loopback、真实PG、外网、真人登录分别报告，不混成一个PASS。

| ID | 必须验证 | 判据 |
|---|---|---|
| A01 | 无token、仅Cookie、伪造x-agent-id | 401，正确发现头；没有业务调用 |
| A02 | none/HS256、坏签名、未知kid、错误issuer | 拒绝；不按token内URL取钥 |
| A03 | 错aud、缺aud、EKDB token、网页登录token、错误端口/路径 | 拒绝；不宽松匹配 |
| A04 | exp/nbf/iat、缺sub/client_id及错误类型 | 按合同拒绝；只允许冻结的时钟容差 |
| A05 | 合法Auth主体首次访问、禁用主体 | authenticated_private模式自动绑定私人空间，无需owner名单；禁用主体403；未获scope的操作仍拒绝 |
| A06 | 合法只读token与缺单一scope的token | 可读；写/治理不执行，Runtime调用计数为0 |
| A07 | tool映射与目录 | 新tool无映射失败；目录过滤与直接调用权限一致 |
| A08 | 并发两个主体、取消/异常/线程池 | 身份/结果不串；ContextVar正确释放 |
| A09 | 旧协议Session ID复用、长连接后撤权 | 每次调用重验身份/策略；不能借会话绕过 |
| A10 | 相同sub跨客户端与token轮换 | State、操作幂等身份稳定，不误建空命名空间 |
| A11 | 旧principal迁移与错误owner映射 | 未授权迁移拒绝；旧State/数据原样保留 |
| A12 | JWT伪造tenant/project/role、跨用户对象ID、来源检索及continuation | 不改变可信绑定；同端点两用户独立读写，相同来源名及operation_id不串数据；真实PG拒绝跨用户访问 |
| A13 | 状态保存、并发CAS、响应未知、冷进程恢复 | 公开回执/版本正确；不丢写、不盲重试、不把UNKNOWN当失败 |
| A14 | 本地禁用/收窄权限及损坏准入文件 | 更新确认后的新请求拒绝；不可用时fail closed |
| A15 | JWKS轮换/删除key/过期缓存/随机kid洪泛 | 新key可受控刷新；无无限旧key、无请求放大/全局读锁 |
| A16 | Auth不可用、TLS错证书、重定向与超大JWKS | 超时/响应有界；不关闭证书校验，不降级认证 |
| A17 | 精确Host/Origin、错误7960端口、伪造转发头 | 合法公网代理成功；错误输入拒绝；不关闭rebinding防护 |
| A18 | 无凭据preflight及Auth状态 | 元数据公开JSON；外部AS issuer正确；登记active前不宣称可登录 |
| A19 | 非root包、进程重启、密钥/日志检查 | 不依赖/root开发环境；不泄漏JWT/refresh/数据库凭据 |
| A20 | 真实用户DCR→浏览器→token→只读工具 | 全链完成；由实际用户同意，不代替用户操作；无授权码/token进报告 |
| A21 | 真实refresh、旧refresh重放、Auth撤销连接 | 按当前Auth合同测，包括宽限窗；记录剩余JWT窗口，不假称即时撤销 |
| A22 | 测试与真实主体分别收尾、回滚 | 只撤销本次测试连接；真实使用账号不得被清理脚本误撤 |

A02–A17以离线签名测试密钥、临时策略文件和独立Runtime/PG为主，不拿生产token构造测试库。
A20–A22需要真实测试主体与明确同意，使用本次专用resource/client/connection；错误aud令牌
只能在自有合格测试资源取得，不盗用EKDB或其他用户凭据。工具负向断言包含“handler未执行”，
仅HTTP状态正确而产生了写入也算失败。

以下命令已在本地实施阶段执行，具体输出、默认跳过项及其单独执行结果见第1节和实施记录；
它们不证明公网部署或真人登录：

```bash
cd /cra/memory/mx_memory/MiLAi-Product/integrations/mcp
uv lock --check
uv run --frozen ruff check src tests
uv run --frozen mypy
uv run --frozen pytest -q
uv build
```

按实际新增测试先跑最小集，再扩大；真实PG不得被可选skip替代。外网preflight必须保留
`mutating_requests=0`；登录与登记单独记为有副作用阶段。默认不直接下载执行远程conformance
脚本；如采用官方示例，先读源码、固定摘要、限定测试账号与副作用，再执行。

性能只测认证新增开销：暖缓存单次与8并发的P50/P95/P99、冷JWKS耗时、网络请求次数、超时率。
暖路径远程Auth请求数为0；不通过增加模型调用或全局排队换取登录成功。数值SLO先基于本机
校准，不复用Memory检索P95、厂商数字或单用户结果作为认证容量保证。

## 12. 状态、回滚与交付声明

| 交付状态 | 必须成立 | 不能声称 |
|---|---|---|
| `DESIGN_READY` | 本设计与入口链接完整 | 实现、部署、登录已完成 |
| `IMPLEMENTED_CANDIDATE` | P1–P3及直接测试通过 | 公网可达、Auth登记或真人登录通过 |
| `PUBLIC_PREFLIGHT_READY` | P4通过，资源active且准入已配置 | 用户已经授权、刷新/恢复已经验证 |
| `LOGIN_VERIFIED_READ_ONLY` | P5与必要负向门通过 | 普通写回或治理已可用 |
| `COMPLETED_AUTH_PILOT` | P6、最终用户验收与限定回滚证据 | 任意用户自助开通、多租户私有性、完整治理或产品production ready |

没有证书记 `TLS_CERT_PENDING`，外网/AS抓取失败记 `PUBLIC_ROUTE_OR_AUTH_FETCH_PENDING`，
缺用户同意记 `USER_CONSENT_PENDING`；保留已完成工程证据，不把缺外部权限误写成代码失败。
这些是文档交付状态，不自动创建或暂停产品的运行Goal。

回滚按精确文件/安装包/配置版本执行；保留数据、OAuth历史、注册回执及审计。优先停用候选
入口并保持现有受保护服务，不把候选HTTPS降级为公开HTTP、不重开失效密钥、不回滚用户
业务写入。已登记resource如需停用走有权限的管理路径；无权时由owner处理，不能假装删除成功。
只清理本次临时监听与测试主体，不能停止共享Runtime、vLLM、其他端口或其他Auth连接。

对产品影响：仅新增外部身份验证与细粒度入口授权，Memory正文、Evidence/Canonical authority、
Runtime CAS和数据库角色分工不变；没有Schema迁移。仍为 **Implementation CANDIDATE，
Schema 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE**。

初稿交付为设计、索引同步及只读核查；后续已完成P1–P3本地实现与直接验证，仍未运行模型、
注册、真人登录、生产凭据变更或线上部署。恢复时从当前P4–P6剩余项继续，先核实证书、准入
身份和外部可达性，不重复P0/P1开发，不从旧enrollment签发或已取消的DNS订单继续。
