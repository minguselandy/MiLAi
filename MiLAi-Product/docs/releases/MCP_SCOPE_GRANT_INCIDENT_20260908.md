# MiLAi 12 项请求、8 项实际 grant 的定位记录

状态：RESOLVED_BY_INDEPENDENT_DCR_CONNECTION，真实工具发现已确认。

用户完成 milai-ordinary 独立连接、12 项授权并启动全新测试客户端，在测试进程禁用旧 milai，
实际返回 22 个工具。服务端 2026-09-08 05:44:11.652644 UTC 的对应记录确认：
granted=12、effective=12、registered=22、visible=22、filtered=[]。
证据：/opt/milai-aigcit/releases/ordinary-v1-scope-diagnostics/client-directory-confirmed.json。
这证明独立 DCR 连接与新客户端进程解决了本次工具发现问题；由于客户端注册和进程同时变化，
不进一步断言旧路径究竟是 Auth grant 沿用还是客户端缓存。无需修改 Auth 或放宽旧 token 权限。
用户的 ordinary-tools.json 位于其 Windows 工作区，本机未读取该文件；服务端记录独立核对。
新增接口的公开读写尚未测试；模型实验仍暂停，原 U5 实际 Agent 使用门没有因此完成。

按用户指出的 HTTP-AIGCIT-AUTH-01 第 8.1/8.2 节重新核对教程：资源自助登记和独立名称的
DCR 客户端迁移不需要 Auth 管理入口。再次只读确认 resource active、资源声明和登记均为
12 项且全部进入 AS metadata；无需重复写登记。此前直接要求 Auth 源码过早，先按已存在
的公开接入路径排除旧客户端 grant/缓存。
已补 examples/codex-mcp/milai-ordinary-client.toml.example，使用独立名称 milai-ordinary、
精确 resource、全部 12 个 scope，不配置共享 Bearer 或旧 client_id。现有 milai 示例中
遗留的 8 项列表也已更新；这项文档遗漏不被当作已经证实的本次 token 根因。
客户端迁移仍须在用户的 Windows 机器完成，本服务器不能代替该机器接收 loopback 回调。
同一 issuer/sub 的私有空间不依赖 client_id，因此独立客户端不会另建身份空间。

真实请求时间为 2026-09-08 05:17:31.420344 UTC。MCP 已验证签名、issuer、audience、
有效期后得到 8 个 granted scope；服务端 enabled 为 12 个，effective 为 8 个。
工具注册数 22，可见数 13，被过滤 9 个恰好依赖四个未获授的新 scope：
milai.note.read、milai.note.write、milai.note.delete、milai.evidence.read。
脱敏原始记录在 /opt/milai-aigcit/releases/ordinary-v1-scope-diagnostics/directory-observations.json。

当前公网程序为 MCP 0.1.8 / Runtime 0.1.2，ordinary-memory-v1，schema 0056。
Auth resource 登记与公开元数据已是 12 项。不能从授权 URL 的 scope 参数证明 token 的 scope。
Auth 在 101.37.208.147，MiLAi 在 36.140.33.19；本环境目前未定位到 Auth 源码或运维连接。
不将 MiLAi 新工具映射到旧 scope 来绕过用户 grant。

已向测试端请求客户端名称/版本、新授权码兑换还是 refresh/缓存，以及可见的兑换响应 scope。
同时请求 Auth 仓库/目录或已配置连接名称；不请求密码、token、授权码或 verifier。

Windows Codex 定向恢复入口：examples/codex-mcp/milai-reauthorize.ps1。
用现有已配置的服务器名称，只清除此 MCP 的客户端授权，再以 DCR 和完整 12 项 scope
发起一次新登录。登录后必须结束旧测试进程再重新连接，避免旧进程继续持有先前 token。
脚本不清理整个凭据库、不修改 URL/身份 namespace、不发业务写入；它不是已经验证成功的修复。
命令语法已核对本机 codex mcp login/logout --help；本机没有执行用户 Windows 的登录。
官方客户端文档：https://learn.chatgpt.com/zh-Hans/docs/extend/mcp。

若新授权码兑换响应为 12 项，而服务端观测仍为 8 项，查客户端使用的凭据库、显式 Bearer
覆盖和旧进程缓存。若新兑换响应即为 8 项，查 Auth 的 consent/grant 扩展是否合并四项
missing resource scopes，以及实际签发 provider 是否使用更新后的 resource 配置。
修复只能扩大本次明确请求并获准的 grant；旧 refresh token 不应自动获得新增权限。
拿到源码后针对对应实际分支修改，不依据推测编造已实施的 Auth 补丁。
