# MiLAi 本地 Runtime Runbook

> `0.1.x EXPERIMENTAL / CANDIDATE / NO-GO FOR SCHEMA FREEZE`

## 前置条件

- Docker Engine 与 Compose v2；
- `uv`；
- 可用的 Python 3.11；
- 仅在本机 loopback 暴露数据库和 API。

## 首次启动

在 `MiLAi/runtime/` 中：

```bash
uv sync --frozen --dev --extra embedding
uv run milai-ops init
# init 使用 O_EXCL 创建 0600 .env，不覆盖现有配置，并生成彼此独立的 secret。
set -a
. ./.env
set +a

uv run milai-ops start --background
uv run milai-ops doctor --json
uv run milai-ops status --json
```

若同机已有实例，用 `milai-ops init --postgres-port 25432 --api-port 28080` 选择独立端口；
`doctor --json`、`status --json` 和隔离全链 `smoke-test` 提供稳定机器可读结果。Smoke 使用专用
临时数据库、Blob 根和 synthetic tenant，不得指向当前工作数据库。

API 默认监听 `127.0.0.1:18080`：

```bash
curl --fail http://127.0.0.1:18080/health/live
curl --fail http://127.0.0.1:18080/health/ready
```

本地控制台位于 `http://127.0.0.1:18080/`。备份/恢复与 projection/purge 恢复分别见
`backup-restore.md`、`projection-and-purge-recovery.md`。

控制台中的 action-sensitive Chat 会把 action JSON 规范化为 `action_digest`，再摄取一条绑定
tenant、query、active goal、scope、authority 与 action digest 的短时 `USER_CONFIRMATION`
Evidence，并把其 ID 与 nonce 交给 Chat；只输入 `CONFIRM_ACTION` 文本或重放其他请求的
confirmation 都不会绕过确认门。Episode capture 只接受
当前 tenant 中真实存在的 Evidence/ChatTurn/ContextCapsule 引用，Settlement 只能走 Steward
procedure，并且不会自动创建 ClaimVersion。

正式候选接口使用 `/v1/memory/query`、`/v1/system/watermarks`、
`/v1/system/degraded-routes` 与 `/v1/deletions/{id}`。兼容 alias 不应写入新的客户端。

## 验证

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest -m "not integration"
uv run pytest -m integration
```

完整验收还要求在专用数据库执行全量 `uv run pytest`；其中包含从空库前向迁移到 head、
0013↔0014 历史字段兼容、真实角色/RLS、并发 CAS、备份恢复与故障路径。当前候选 head 为
`0027_embedding_identity`。0015 之后包含有审计历史的 forward-only migration；运维脚本应始终
使用 `alembic upgrade head`，不要硬编码 revision 或尝试破坏性 downgrade。Corrected 0024 会离线
锁定治理/provenance 表，证明 populated candidate.1 creation/transition、Proposal support grounding 与
actual DeletionRequest-backed TX-05，回填 history，并把精确非法 transition/rejected relation 分别移入
immutable ledger。任何 unknown/conflicting fresh input 都整体回滚到 0023。0025 对已经执行
candidate.3 0024 的开发库重复 durable proof；失败保持 0024。两条路径都要求 DeletionRequest、
Evidence revoke、idempotency、OperationalEvent 与 revoke/purge Outbox 的事务时间精确相等。0026
只重新认证已经执行 candidate.4 0025 的开发库；失败保持 0025 且不创建新 authority。三类失败都
必须先人工审计或从验证过的备份恢复，不能伪造 DeletionRequest/Alembic head 后继续服务。0027
把 provider/model/dimension/normalization/code version 的摘要作为 projection version；切换模型后
必须显式重建 vector projection，查询不会读取其他 identity 的分数。

Integration tests 只允许使用专用本地开发数据库。不要把生产或已有个人数据库 URL 放入
`MILAI_TEST_*` 环境变量。

## 停止

前台 profile 使用 Ctrl-C；后台 profile 使用：

```bash
uv run milai-ops stop
```

该命令只停止受 state 文件精确约束的进程并保留开发 volume。删除 volume 会永久删除本地开发数据库，只能在明确确认其不含
需要保留的数据后手动执行；本文不把 destructive 命令作为常规步骤。

## 常见故障

- 配置错误：进程在启动前返回字段名，不打印 secret 值；
- 数据库不可用：readiness 返回 `CANONICAL_UNAVAILABLE`，liveness 仍可用于诊断进程；
- 初始化角色缺失：确认使用全新的专用 volume，或按后续 role-rotation runbook 修复；
- 角色错配或提升：API/Steward/Worker 会核验精确 `session_user/current_user`、cluster attributes
  与 MiLAi ownership，并在服务或 lease 启动前拒绝；
- 因果令牌失败：确认只通过 `/v1/causal-tokens` 为本 tenant 的真实 Outbox ID 签发；不要把
  server-only causal secret 交给客户端；
- Migration 失败：停止 API/worker，保存错误和 revision；不要手工篡改 Alembic version；
- Projection/dead-letter：保持 Gate fail-closed，按 runbook 显式 retry 或重建 derived store；
- Blob 故障：Evidence identity 保留，正文/pointer recovery 拒绝返回；
- Embedding 故障：L0 与 FTS 可继续，响应显式标记 vector degraded；
- AF-09 独立评审未通过：允许继续 synthetic experimental 开发，但禁止声称 Schema frozen；
- ADR-012 encryption/key gate 未实现：禁止导入真实个人数据。
