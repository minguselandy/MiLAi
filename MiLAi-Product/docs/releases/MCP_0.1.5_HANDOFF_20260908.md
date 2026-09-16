# MiLA MCP 0.1.5 交付记录

2026-09-08：用户要求暂停实验，优先封装 MiLA Product 并交付 MCP。

交付入口：`examples/mcp-release/README.md`。
构建命令：`sh tools/build_mcp_delivery.sh`。
输出：`integrations/mcp/dist/delivery/milai-mcp-delivery-0.1.5.tar.gz` 及外部 SHA-256。
包内 `SHA256SUMS` 标识每个实际交付文件，包括 MCP/client wheel、源码包和依赖锁。
构建不依赖 Lab，不包含运行数据、凭据或实验材料。

现有公网地址为 https://milai.aigcit.com:7960/mcp，AIGCIT OAuth 登录已由用户报告
外网验证通过。私人模式由 namespace/issuer/sub 派生身份与项目，不要求手工逐人录入。
账号需要有效授权和工具所需 scope；治理和破坏性操作不向普通私人模式开放。

本次将当前 Product 的 MCP 接口封装为独立可安装交付物，补充用户入口和安装脚本。
0.1.5 还包含此前开发的可选 Host HTTP 预取接口；它只接受已有普通 bearer，
不接管 OAuth 获取或刷新。模型的自主记忆调用可靠性仍未通过完整实验验证。

## 验证记录

在各自包目录执行：

```bash
uv run --frozen ruff check src tests
uv run --frozen mypy
uv run --frozen pytest -q
uv build
```

- MCP：Ruff、mypy（14 个源文件）、构建通过；272 passed / 4 skipped，18.73 秒。
  4 项真实 PostgreSQL 测试未开启专用数据库环境，未计为通过。
- Python client：Ruff、mypy（14 个源文件）、构建通过；188 passed，1.37 秒。
- 两包 `uv lock --check` 通过；交付脚本在 Product 内独立构建成功。
- 解压到新的 `/tmp/milai-delivery-check.CDAkHM`，运行包内 `install.sh`：
  文件校验通过，按哈希安装 31 个第三方依赖和 2 个本地 wheel，`uv pip check` 通过。
  `milai-codex-full-mcp --help` 成功；用 Python `-I` 确认模块来自新环境的 site-packages，
  版本为 milai-mcp 0.1.5 / milai-client 0.1.0 / mcp 2.0.0，公开 bootstrap 接口可导入。
- `sh -n tools/build_mcp_delivery.sh examples/mcp-release/install.sh` 和 `git diff --check` 通过。
- 公网服务 `milai-aigcit.service` 为 active/running。使用系统 TLS 校验、无凭据且绕过
  本机代理检查域名端口：`/healthz` 200、protected-resource 元数据 200、MCP initialize 401；
  本机指定 127.0.0.1 且保留域名 TLS 校验的健康检查也为 200。这不是新的外部客户端登录实测。
- 完整 `milai-oauth-readiness --base-url https://milai.aigcit.com:7960
  --external-issuer https://auth.aigcit.com` 保持 BLOCKED：AS 元数据未声明
  `revocation_endpoint_auth_methods_supported` 包含 `none`。未降低检查标准。
  默认代理路径曾发生 TLS EOF，绕过代理后可达；该失败不解释成公网服务停机。

仅执行工程检查、隔离安装烟测及无凭据服务检查；未启动模型实验、写入公网测试记忆
或撤销真实用户连接。OAuth 刷新/撤销实测、完整模型闭环及生产就绪性不在此次通过范围。

## 部署及回退边界

本次没有切换线上版本、重启公网服务或修改认证配置。线上仍使用原已安装发布目录，
不能由新构建的 0.1.5 包推出线上版本已经一致。安装脚本不自动启动服务。
服务依赖单独的 MiLA Runtime / PostgreSQL；交付包不自带数据库或生产密钥。

封装变更无 API/schema/权限/Canonical 语义改动，无新增 migration。
回退只切换程序环境，保留持久数据。Runtime 全量与真实 PG 测试未因封装而重跑；
涉及这些语义的后续改动仍须独立验证。

MILA-V02-06 处于 PAUSED_BY_USER：R2/R3、容量及完整公网续做链尚未完成，
不声明全部开发 Goal 或端到端通用性通过。现有研究证据保留在 Lab。

**Schema 0.1.x EXPERIMENTAL / Implementation CANDIDATE / NO-GO FOR SCHEMA FREEZE**。
