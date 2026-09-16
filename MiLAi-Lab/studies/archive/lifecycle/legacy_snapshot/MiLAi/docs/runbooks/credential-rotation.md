# MiLAi 凭据与密钥轮换 Runbook

> 状态：`0.1.x EXPERIMENTAL / CANDIDATE`。  
> 原则：不在命令行参数、shell history、日志、prompt、tool result 或 review 记录中暴露 secret。

## 1. 当前支持边界

| 类别 | 当前受控路径 | 恢复边界 |
|---|---|---|
| Blob KEK | `milai-ops rotate-blob-key` | 每个 envelope 可重入；旧 KEK 保留至验证/备份完成 |
| Agent/API bearer | `milai-ops rotate-local-credentials` | 内部生成、不回显；重启后旧 token 必须 401 |
| PostgreSQL role password | 同一 stop-the-world command | 五个 exact role 全部重连，旧口令全部拒绝 |
| causal secret | 同一 stop-the-world command | 旧 causal token 立即失效；不迁移旧 token |

单项、计划内 Blob KEK 轮换继续使用 `rotate-blob-key`。秘密疑似进入日志、包、备份或其他非预期
位置时，必须视为整组暴露并使用 `rotate-local-credentials`，不能只删除泄露副本。

## 2. 轮换前检查

```bash
cd runtime
uv run milai-ops doctor --json
uv run milai-ops stop
```

数据库必须在 API/worker 停止期间保持 loopback 可用。`ADOPTED` 模式的 `stop` 已满足；若是
`MANAGED` 模式，`stop` 会停止 PostgreSQL，随后只启动 PostgreSQL 服务而不要启动 API/worker：

```bash
docker compose --env-file .env up --detach --wait postgres
```

泄露事件不得复制或保留旧 `.env`。常规计划轮换若需要恢复材料，必须保存在仓库外的受控 secret
manager，不能放入 `docs/`、`runtime/var/reports/`、构建产物或聊天记录。

## 3. Blob KEK

新 KEK 必须通过临时进程环境注入，不作为参数传递：

```bash
export MILAI_NEW_BLOB_KEK_B64='<32-byte-key-as-base64-from-a-secret-manager>'
uv run milai-ops rotate-blob-key \
  --new-key-reference local-kek-v2 \
  --new-kek-env MILAI_NEW_BLOB_KEK_B64 \
  --confirm ROTATE_BLOB_KEY
unset MILAI_NEW_BLOB_KEK_B64
```

命令逐个 envelope 原子替换；同一新 key reference 的重放只验证、不重复改写。成功后通过私有编辑
通道同步 `.env` 的 `MILAI_BLOB_KEK_B64` 与 `MILAI_BLOB_KEY_REFERENCE`，启动并执行 doctor、
isolated smoke、加密备份与恢复演练。旧 KEK 只在新备份恢复证据被接受后离线过期。

## 4. 泄露后的整组轮换

在 Runtime/API/worker 已停止而 PostgreSQL 可连接时执行：

```bash
uv run milai-ops rotate-local-credentials \
  --env-file .env \
  --confirm ROTATE_EXPOSED_LOCAL_CREDENTIALS
```

命令内部生成五个数据库密码、API/causal/四个 Agent token 和新 Blob KEK；逐项替换 DSN，使用
Migration Owner 事务更新精确角色，以 0600 临时文件原子替换 `.env`，验证新角色与旧口令失效，且
只返回不含秘密的状态。普通异常会回滚数据库事务、`.env` 与 Blob envelope；成功后不保留旧
`.env`。本步骤不能由 Agent/MCP tool、模型或 unattended hook 触发。

## 5. 轮换后验收

```bash
uv run milai-ops start --background
uv run milai-ops doctor --json
uv run milai-ops status --json
uv run milai-ops smoke-test
```

另外确认旧 Agent token 返回认证失败、API/Worker 环境没有 owner/audit credential、备份可用新 KEK
恢复且旧 KEK 按策略失效。若轮换源于泄露，不得继续保留含旧 secret 或旧 `.env` 的 sdist、日志、
报告或备份。真实个人数据 Gate 仍需独立 privacy/security review 和用户批准；凭据轮换成功本身
不会把 `SYNTHETIC_ONLY` 升级为 `LOCAL_PERSONAL_DATA`。
