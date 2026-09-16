# MCP 0.1.8：工具目录权限诊断

当前交付状态：REAL_CLIENT_DIRECTORY_CONFIRMED。用户使用独立 DCR 连接 milai-ordinary，
明确授权 12 项并重启测试进程后，实际发现 22 工具。服务端 UTC 05:44:11.652644 核对
granted/effective 均为 12、registered/visible 均为 22、无过滤项。详见
MCP_SCOPE_GRANT_INCIDENT_20260908.md。新增公开接口读写尚未测试，模型实验仍暂停。
以下保留故障定位及补丁过程。

用户明确申请 12 个 scope 后仍只看到 13 个工具，但新版采集/提案 schema 已出现。
当前公网进程确认 ordinary-memory-v1 已启用、服务端允许 12 个 scope、authenticated_private
模式正常。原审计只记录 tools/call，不能从过去的 tools/list 确认实际 token grant。
根因尚未确认，不能把用户已声明申请 12 项直接当作实际获授 12 项。

本版在现有 tools/list 过滤边界记录 tool_directory_authorization：
已验证 token 的 granted_scopes、服务端 enabled_scopes、当前 effective_scopes，
以及注册、可见、被过滤的工具名称。无 token、subject、client_id、参数或正文。
不增加 MCP 工具，不修改 scope 交集、身份绑定或任何业务读写语义。

复用原脱敏审计测试，增加实际列表结果与诊断一致性及隐私断言。
Ruff、mypy（16 文件）通过；相邻 HTTP/auth/catalog 23 项通过（1.69s）。
测试断言首次误插入另一个测试，Ruff 拒绝；已移动到原审计测试后重跑通过。
构建 wheel/sdist，按原锁定依赖及 client 0.1.2 在独立服务环境安装；
服务账号入口检查通过，已切换公网 MCP 至 0.1.8，/readyz 为 200。
Runtime 0.1.2、数据库 0056 和认证登记保持。

目录 /opt/milai-aigcit/releases/ordinary-v1-scope-diagnostics 保存本版包和安装日志。
仅新增 milai-aigcit.service 的 zz-ordinary-v2-scope-diagnostics.conf drop-in。
回退时移除该 drop-in、daemon-reload 并重启本 MCP，即回到已保留的 0.1.7。
不需要数据库回退或重新登记 scope。

用户用现有授权重新连接/刷新 tools/list 后，检查 journal 中该事件：
若 granted 缺新增 scope，继续查授权签发；若 granted 完整但 effective 缺项，查本地授权；
若 effective 完整但 registered 不全，查装配；若 visible 为 22 但客户端为 13，查传输/客户端缓存。
这些是诊断分支，不是事先假定的根因。当前不要求用户再次登录或提供 token。

上线后收到一次真实 tools/list 请求，脱敏证据已保存至
/opt/milai-aigcit/releases/ordinary-v1-scope-diagnostics/directory-observations.json。
已验证 token 的 granted_scopes 为旧 8 项，enabled_scopes 为 12 项，effective_scopes 为 8 项；
registered_tools 为 22 项，visible_tools 为 13 项。缺失 grant 恰为 milai.note.read/write/delete
及 milai.evidence.read，对应被过滤的 9 个新增工具。由此确认本次列表变少是权限交集结果，
不是新工具未注册，也不是 enabled scope 漏配置。
尚未区分 Auth 在新授权中沿用旧 grant，还是客户端实际发送旧 access/refresh-token 派生结果；
需要与该次授权码兑换/客户端选择的脱敏 scope 和时间对应，不能仅凭授权 URL 推断签发结果。

模型实验仍暂停。Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE /
NO-GO FOR SCHEMA FREEZE。
