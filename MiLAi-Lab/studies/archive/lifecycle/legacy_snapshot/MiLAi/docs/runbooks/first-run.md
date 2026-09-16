# MiLAi 首次启动 Runbook

> 适用：`0.1.x EXPERIMENTAL` Runtime、`CANDIDATE` Implementation。  
> 数据边界：首次启动固定为 `SYNTHETIC_ONLY`；本文不批准真实个人数据、远程访问或 Schema freeze。

## 1. 前置条件

目标机器需要 Python 3.11/3.12、`uv`、Docker + Compose、PostgreSQL 16 client 和可用的本地端口。
从 `runtime/` 执行：

```bash
uv sync --frozen --dev --extra embedding
uv run milai-ops init
uv run milai-ops doctor --json
```

`init` 以 `0600`、排他创建 `.env`，不会覆盖旧文件，不会输出 secret。Doctor 的
`BLOCKED` 必须先修复；它逐层检查 OS/架构、Python/uv lock、Docker/Compose、配置、loopback、
五个数据库角色、对象所有权、pgvector、Alembic head、Blob 权限、Worker lag/dead-letter、
PostgreSQL 备份客户端、API 与 Agent 合同兼容和数据/加密 Gate。

## 2. 启动

后台 profile：

```bash
uv run milai-ops start --background
uv run milai-ops status --json
```

前台开发 profile：

```bash
uv run milai-ops start
```

启动顺序固定为：PostgreSQL 可用 → Alembic head → API role check → Worker preflight → Worker →
API ready → 隔离 synthetic smoke。API/Worker 子进程环境不含 Migration Owner、Audit URL 或 owner
password。若配置的 PostgreSQL 已由同一台机器的受信 profile 提供，状态报告
`postgres_mode=ADOPTED`；干净环境则由 Compose 启动并报告 `MANAGED`。

重复执行后台启动返回 `ALREADY_RUNNING`，不会重建数据库、覆盖 `.env` 或删除 volume。前台模式
收到 Ctrl-C/SIGINT 后正常停止 API/Worker；日志保持正文脱敏。

## 3. 独立 Smoke 的安全边界

也可单独执行：

```bash
uv run milai-ops smoke-test
```

Smoke 每次创建唯一的 `milai_smoke_*` 数据库、临时 AES-256-GCM Blob 根和 synthetic tenant，
并用 submitter/reviewer/operator/reader 四类 token 完成：

```text
health → Evidence → pending Proposal → no Claim before review
→ explicit test review → Worker → L0/L1 → ContextCapsule → RetrievalTrace
→ revoke → stale projection rejected/abstained → purge/deletion status
```

结束时先正常停止临时 API，再验证数据库 owner 精确为 `milai_owner` 且连接数为 0，之后才删除该
数据库；它不会 terminate 未知连接。Blob 只删除 Python 创建并持有的精确临时目录。0600 报告写入
`runtime/var/reports/smoke-<run-id>.json`。任何清理验证失败都返回 `BLOCKED` 并保留目标供诊断。

## 4. Agent 接入配置

```bash
uv run milai-ops agent-config --transport stdio --profile reader
```

输出只含绝对 MCP package 路径和 `${MILAI_AGENT_READER_TOKEN}` 引用，不含 token 值。将环境变量
引用交给宿主的 secret store；不要复制 `.env` 内容进 prompt、tool result 或项目配置。

## 5. 停止与数据保留

```bash
uv run milai-ops stop
```

只停止 state 文件中 PID + process-start marker 精确匹配的 API/Worker。`MANAGED` PostgreSQL 一并
停止，`ADOPTED` PostgreSQL 不由本命令处理；两种情况均保留 volume，且没有删除 volume 的快捷命令。

## 6. 判定

首次使用只有同时满足以下条件才是 Developer Ready 候选：

- doctor 无 `BLOCKED`；
- `status` 的 live 与 ready 分别成功；
- 隔离 smoke 全链和清理均 PASS；
- `.env`、state、log、smoke report 权限符合手册；
- banner 仍为 `SYNTHETIC_ONLY / CANDIDATE / NO-GO FOR SCHEMA FREEZE`。

这不等于 Agent Integration Beta、Local Private Beta 或 Production。
