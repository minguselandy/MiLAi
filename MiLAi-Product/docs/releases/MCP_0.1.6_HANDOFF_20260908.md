# MiLA MCP 0.1.6：完整私人记忆能力

用户要求 MCP 提供全部功能。本版开放既有 codex-full 的全部 13 个工具，
按 verified scope、部署配置和本地账号策略共同决定可见性与执行权限。
新增可授权能力包括提案、审批、Evidence 撤销和私人空间清理；不是全局管理员权限。
设计与权限边界见 [ADR-050](../adr/ADR-050-full-private-mcp-capabilities.md)。

MCP 0.1.6 / client 0.1.1 / Runtime 0.1.1 配套交付。Runtime 的提案列表增加可选
project_id 过滤，在 LIMIT 前执行；MCP 只传入服务端派生的项目，仍检查返回记录。
无新增 schema migration，不改变历史事务或身份。升级顺序为 Runtime、MCP、
公网 scope 元数据／Auth resource 登记，最后由客户端重新授权。

## 验证与部署记录

实验保持暂停，仅运行工程测试；未使用模型或生产用户数据进行删除测试。
默认库配置仍为只读，完整 scope 由部署显式启用。

- MCP：`uv run --frozen ruff check src tests`、`mypy`（14 文件）通过；
  `pytest -q --tb=short` 为 273 passed / 5 skipped，18.84 秒。
  专用 PostgreSQL 下另执行两种账号模式的保存／冷恢复／CAS测试，2 项通过；
  新增完整私人生命周期在真实 Runtime、签名 OAuth fixture、加密 PERSONAL 数据模式下
  通过（该文件含目录检查共 2 passed，6.66 秒）。全部 13 工具实际执行，跨用户读取／
  审批／撤销／清理 job 拒绝，重复审批幂等；101 条外来提案不会挤掉自己的列表结果，
  清理 Alice 后 Bob 的 State 和基于自己 Evidence 的 Claim 仍可使用。
- Python client：Ruff、mypy（14 文件）通过；188 passed，1.32 秒。
- Runtime：Ruff、mypy（191 文件）通过；干净测试数据库下 1172 passed / 1 skipped，
  另将全局降级测试置于单独空数据库执行，1 passed；共 1173 passed。
  跳过项需要可选 openworker 集成。首次未配置数据库、复用测试数据导致的冲突、
  owner 测试 URL 误配均记录为失败，修正测试环境后重跑；未据此放宽产品权限。
  旧迁移测试的 head 断言从 0054 校正到实际已有的 0055；未修改已应用 migration。
- 三包均从锁文件构建。MCP/client 和 Runtime 在 `/opt/milai-aigcit/releases/full-v1/`
  的独立虚拟环境安装；依赖一致性、隔离导入、服务账号加载及候选 Runtime/MCP
  `/readyz` 检查通过。Runtime 按锁安装既有 ONNX provider 所需 embedding extra，
  继续使用现有本地模型，没有下载模型或运行模型实验。
- `sh -n tools/build_mcp_delivery.sh examples/mcp-release/install.sh`、`git diff --check` 通过。

### 线上配置修复与切换

发现原 MCP 使用 PERSONAL 分类，而后端仍为 SYNTHETIC_ONLY，实际会拒绝个人 Evidence。
现有 Blob 已配置 AES-256-GCM。核对 20 个既有文件均为加密封装，并对当前密钥进行
独立进程的密钥／密文恢复核验（合成材料、私有 0600 恢复文件），结果通过。
Runtime 全量测试同时覆盖既有加密备份／恢复及删除传播；没有用文本声明代替这些检查。
随后仅为 MCP 的 Runtime/Worker 添加 LOCAL_PERSONAL_DATA 配置和恢复确认；保持原密钥、
Blob 根、数据库、tenant、namespace、issuer 与账号绑定。没有重写既有 Blob。
该恢复核验仅证明本机恢复能力，不代表异地灾难恢复保障。

已部署 MCP 0.1.6、client 0.1.1、Runtime 0.1.1，API/Worker/MCP 三个 unit 均 active/running。
新安装目录为 `/opt/milai-aigcit/releases/full-v1/`；公网地址不变：
`https://milai.aigcit.com:7960/mcp`。健康和依赖 readiness 返回 200。
向 Auth 的 `/resources/register` 更新此唯一 resource 后，独立 `/resources/status`
核验为 active，8 个 scope 与公网 protected-resource 元数据完全相同。

旧 token 没有新增权限。客户端合并完整 scope 示例并重新登录授权后，才能看到对应工具。
未代替真实用户登录、读取私人正文或做公网破坏性烟测；全 13 工具的认证调用证据来自
隔离签名 fixture／真实 PostgreSQL，并非新一轮真实公网账号验收。
AS 的公共客户端撤销支持声明仍待补齐；原 strict OAuth readiness 问题未放宽或伪称通过。

### 运维证据及回退

脱敏服务与 scope 回执：`/opt/milai-aigcit/releases/full-v1/live-delivery-result.json`。
候选服务和密钥恢复结果在同一发布目录，恢复密钥目录仅 root 可读，不进入交付包。
原配置保存在 `/etc/milai-aigcit/backups/full-v1/`，含 mcp.env 和回退文件清单。
旧 `private-v1` 安装保留。移除本次 `zz-full-v1.conf` drop-in 并恢复 mcp.env 可退回
旧程序和 scope；重新加载／重启相关 unit，再重新登记 resource 确认 scope 一致。
个人数据现已允许保存，回退时应保留加密密钥及数据可读配置，不恢复旧 SYNTHETIC_ONLY
作为“个人数据兼容回退”；不得删除或回滚用户已提交的数据。无 schema 降级步骤。

完整交付包含 MCP/client/Runtime wheel 与源码、哈希依赖锁、可选 embedding 依赖锁、
配置示例和安装脚本。构建命令为 `sh tools/build_mcp_delivery.sh`，输出在
`integrations/mcp/dist/delivery/`，包内外 SHA-256 绑定实际文件。

保留：源码不等于部署完成；OAuth capability grant 不等于当前删除请求；
单 Host 审批不等于独立语义审查；清理回执不等于已完成物理擦除。
旧 0.1.5 包和交付记录保留，回退程序时不得回退或删除用户数据。

**Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE**。
