# MCP 0.1.7 公网切换待执行清单

当前状态：DEPLOYED_REAL_CLIENT_DIRECTORY_CONFIRMED（后续 MCP 0.1.8 诊断补丁）。
用户通过 milai-ordinary 独立 DCR 连接及全新测试进程实际发现 22 工具；服务端 UTC
05:44:11.652644 记录确认 granted/effective=12、registered/visible=22、filtered=[]。
后续详情见 MCP_SCOPE_GRANT_INCIDENT_20260908.md；新增公开读写尚未测试。
用户在审阅升级范围后明确回复“升级”，本次据此执行；模型实验仍暂停。

2026-09-08 05:08 UTC 完成：0055/0056 迁移，API/Worker/MCP 三个 unit 切换，
Runtime 0.1.2 与 Note capability/强制 RLS 核对，MCP 0.1.7 新目录启用。
公网元数据、Auth resource status 和授权服务器 metadata 的 12 个 MiLAi scope 一致；
resource active，未登录 MCP 仍为 401。Runtime /health/ready 与 MCP /readyz 均 200。
真实用户的已认证 tools/list 仍待重新授权验证，不将元数据核对冒充其 22 工具验收。

实际备份采用 PostgreSQL 多租户维护快照，保留 owner/ACL、两个实际 Blob 根和受限配置；
快照校验及 pg_restore --list 通过，未执行新的恢复演练。旧 API 28080 与主服务共享库，
备份/迁移期间短暂 SIGSTOP；确认剩余数据库会话为空闲后，在所有产品表 SHARE 锁下
导出快照及复制 Blob，finally SIGCONT 恢复。原三个 unit 与关联前端均已恢复运行。
初次备份被活跃连接保护拒绝，第二次被单租户限制拒绝；原生备份首次因旧 Blob 根为
相对路径而中止，按该进程工作目录修正后完成。失败日志及不完整副本受限保留。
没有放宽 Product 的单租户备份合同，也没有改写用户记忆或降低来源权限。

完整脱敏结果：/opt/milai-aigcit/releases/ordinary-v1/live-delivery-result.json。
配置/数据备份：/etc/milai-aigcit/backups/ordinary-v1（root 限定，含密钥，不对外交付）。
以下为切换前记录及本次获准执行的范围。

用户再次登录后仍看到相同 13 工具。只读核对确认当前运行 MCP 0.1.6 / client 0.1.1 /
Runtime 0.1.1，路径为 /opt/milai-aigcit/releases/full-v1。MCP 启动命令没有新目录参数，
资源元数据和认证服务器仅公布既有 8 个 MiLAi scope。不是客户端刷新可以解决的问题。

目标数据库只读检查为 0054_intra_source_shadow，host_note 表不存在；不能只切换 MCP。
须按现有链追加 0055_working_state_ref_capacity 和 0056_host_notes，不重排旧迁移。

准备完毕的候选在 /opt/milai-aigcit/releases/ordinary-v1：MCP/client 和 Runtime 分开安装；
Runtime 安装锁定 embedding extra 以适配现网已有 ONNX 配置，不包含或下载模型权重。
输入包 SHA-256 为 60f1f6926e720ac0fdd5b58aa815042fc334a2bf8dece80405354c196bb2ca98。
staged/ 中是三个 systemd drop-in 和只含公开 scope 名称的环境片段；尚未放入生效目录。
初装虚拟环境使用 root 私有 uv Python，服务账号检查明确失败；已使用现有
/opt/milai-aigcit/python/bin/python3.11 重新安装两个环境，不放宽 /root 权限。
服务账号的 MCP 22 工具/12 scope 导入及 Runtime/打包迁移/ONNX 导入均通过。

获准后只执行以下切换：

1. 记录旧三个 unit/config 的校验值和受限回退副本；确认目标库与角色，按现有加密恢复方式
   留存可恢复备份。备份和密钥受限保存，不进入报告。不以回滚数据库覆盖后续用户写入。
2. 在受控窗口暂止本 MCP 对应 API/Worker/Edge 写入，执行打包的 0055、0056 迁移；
   保持数据库、Blob 根、密钥、tenant、namespace、issuer、主体派生规则不变。
3. 安装 staged 中 drop-in 与 scope 文件，重载并启动这三个 unit；核对 readiness、
   实际版本、新 Runtime capability 与 schema。地址仍为 https://milai.aigcit.com:7960/mcp。
4. 核对公网 protected-resource 元数据包含原 8 项及新增 milai.note.read、milai.note.write、
   milai.note.delete、milai.evidence.read。按既有 /resources/register 更新这个唯一 resource，
   用 /resources/status 与认证元数据核对登记；不更改其他应用资源。
5. 完成后再请真实用户授权新增 scope 并刷新 tools/list。仅在授权交集完整时预期 22 工具。
   不导出其 token，不代替其批准治理/删除或改写私人记忆。先前登录不会追溯获得新 scope。

回退：恢复原 unit 配置及旧 scope，启动 full-v1 并同步资源登记；保留新数据库及记忆。
0056 非空时拒绝降级，不能用删表回退。若备份、迁移或 readiness 不满足条件，不切换流量。
旧版本无法操作 Note 是明确兼容限制。记录实际切换和失败，不把准备完成写成部署完成。

本次需要的明确授权范围为上述公网版本切换、两项迁移、四个新增 scope 及对应资源登记；
不包含模型实验、用户数据清理或额外业务写入。依据当前 Goal 的公网部署边界执行。
