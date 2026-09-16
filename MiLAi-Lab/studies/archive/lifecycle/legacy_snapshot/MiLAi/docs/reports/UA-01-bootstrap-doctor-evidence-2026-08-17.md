# UA-01 Bootstrap、Doctor 与隔离 Smoke 证据

> 日期：2026-08-17  
> 范围：UA-01 / UG-01 的本地可重复启动切片  
> 判定：`PROVEN`（仅 Developer Ready；仍是 SYNTHETIC development preview）

## 实现

- `milai-ops doctor --json`：`milai.doctor.v1`，逐层检查 platform、Python/uv lock、
  Docker/Compose、0600 env、strict settings、loopback、Blob 0700、五个精确角色/ownership、
  Alembic head、pgvector、Worker watermark/lease/dead-letter、pg_dump/server major、API ready、
  `agent.v1` compatibility、SDK/MCP package locks 和 data/crypto gate。
- `milai-ops start [--background] [--compose-project ...]`：数据库 → migration → API role check →
  Worker preflight → Worker → API → isolated smoke；支持 `MANAGED` 与 `ADOPTED` PostgreSQL。
- `milai-ops stop`：PID + `/proc` start marker 精确停止；managed PostgreSQL 才由 profile 停止；
  volume 永远保留。
- `milai-ops smoke-test`：新建唯一 `milai_smoke_*` 数据库、临时加密 Blob、synthetic tenant 和
  独立 HTTP API 子进程；四个 capability profile 完成治理、检索、Context、撤销和删除全链。
- `agent-config` 使用 MCP package 绝对路径和环境变量引用，不输出 token。
- 新增 `first-run.md` 与 `credential-rotation.md`；非 KEK credential 轮换仍诚实标为维护窗口流程，
  不宣称单命令无停机事务。

## 动态证据

### Clean managed profile

使用新 0600 env、空命名 Compose project `milai-ua-clean-test`、独立端口 26432/29080：

```text
init                                      INITIALIZED / SYNTHETIC_ONLY
start --background                       RUNNING / postgres_mode=MANAGED
doctor --json                             17 PASS / 0 WARN / 0 BLOCKED
status --json                             live=ok / ready=ready / agent.v1
isolated smoke                            9/9 steps PASS
stop                                      API, Worker, PostgreSQL STOPPED
volume                                    PRESERVED
```

对应 smoke report：
`runtime/var/reports/smoke-f1531aa90193484aa581176b7c9684dc.json`。

Doctor 实际证明：PostgreSQL 16、pgvector 0.8.2、head `0027_embedding_identity`，五个 login role
用户名精确匹配；只有 `milai_owner` 拥有 MiLAi 对象，API/Steward/Worker/Audit 均无 superuser、
createdb、createrole、bypass RLS 或 MiLAi ownership；三 projection lag=0、dead-letter=0、
expired lease=0；pg_dump/server major 均为 16。

### Smoke chain 与清理

```text
health
ingest_synthetic_evidence
pending_proposal_without_claim
explicit_test_steward_review
worker_projection
l0_l1_recall
context_and_trace
revoke_and_stale_abstention
deletion_status
```

最终 database cleanup：owner=`milai_owner`、connections_before_drop=0；临时 Blob 精确目录已移除；
report mode=0600。没有残留 `milai_smoke_*` 数据库。

### 进程与重复启动

- 第二次后台启动返回 `ALREADY_RUNNING`；
- state、API log、Worker log 均为 0600；
- `/proc/<pid>/environ` 复核 API/Worker 均不含 Migration Owner URL、owner password 或 Audit URL；
- 前台 profile 收到 SIGINT 后 state 与两个进程均清理，PostgreSQL volume 保留；
- managed stop 后容器为 stopped，`milai-ua-clean-test_milai_postgres_data` 仍存在；
- 已存在但密码不匹配的旧 Compose volume 被准确拒绝，未删除、未覆盖。

## 静态门禁

```text
Ruff affected operations/persistence/tests       PASS
mypy affected operations/persistence             PASS
operations unit tests                            5 passed
```

## 边界

该证据只关闭 UA-01。它不关闭 SDK 完整 typed async 源、MCP 双宿主/兼容协议、三阶段跨 adapter E2E、
provider outage/performance、真实数据 Gate 或独立 Agent Integration review。Schema 继续
`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`，Implementation 继续 `CANDIDATE`。
