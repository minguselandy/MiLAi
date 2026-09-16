---
document_id: MILA-EVENT-RECONCILIATION-PHASE-C1-COMPLETION
version: "1.0"
status: PASS_SIMPLE_EVENT_JOURNAL
date: 2026-09-05
milestone: PHASE_C1_SIMPLE_EVENT_JOURNAL
schema: 0.1.x-EXPERIMENTAL
public_mcp_schema_change: NONE
canonical_change_authority: NONE
---

# MiLA Event Reconciliation Phase C1 完成报告

## 1. 结论

C1 已交付可逆、append-only、SHADOW-only 的 Host execution Event journal：

```text
trusted Host observation
  -> authenticated internal REST
  -> idempotent Event append
  -> exact task-bound Event window
  -> PostgreSQL
```

里程碑终态：

```text
PASS_SIMPLE_EVENT_JOURNAL
```

它只证明稀疏 Event 可以安全持久化和窗口读取；不声明 StateDelta、自动 checkpoint、
reconciliation 效果、retention completeness 或 public MCP Event tool 已完成。

## 2. 已实现

- `0051_host_execution_event` reversible migration；
- append-only `host_execution_event` 与 exact Evidence ref 关联表；
- tenant/actor RLS、immutable trigger、least-privilege procedure；
- 内部 `POST /v1/host-events/append` 与 `POST /v1/host-events/window`；
- open `event_family/event_type` vocabulary 与 bounded payload/ref contract；
- `DIALOGUE/MESSAGE` 仅保存 role metadata 与 exact Evidence refs，不复制 raw dialogue；
- public operation ID 在进入共享 idempotency table 前按 actor/principal/project/task 命名空间化；
- watermark、rows 与 read audit 在同一 `REPEATABLE READ` snapshot 中读取；
- revoked/unreadable Evidence ref 不再作为有效 ref 返回，只保留 stale identity warning；
- backup inventory、capability discovery、Runtime migration-head tests 同步更新。

Public `codex-full` MCP catalog 仍为 13 tools，C1 没有扩大模型可见 mutation surface。

## 3. 真实测试凭据

最终 fresh-database full gate：

```text
run_id          ead8c4b33199ddc45b5fd4f3
pytest          922 passed, 1 skipped
exit_code       0
cleanup         PASS
connections     0 before drop
```

机器可读凭据：
`docs/goals/artifacts/phase-c1/runtime-full-gate-final.json`。

唯一 skip 是既有 context-chat integration 环境未安装 `milai_client`，与 C1 无关。

补充验证：

```text
Host Event unit/capability focused    12 passed
Ruff                                 PASS
mypy                                 PASS
Runtime package build                 PASS
MCP package suite                     148 passed, 1 skipped
MCP Ruff/mypy/build                    PASS
```

初始部署 smoke 在真实 PostgreSQL 上完成 append/window/replay：Event identity
`ba2cf431-d472-4fcd-92cc-0196fbfbfe39`、position `7`。最终修复部署后，两个 principal 使用同一
公开 operation ID 分别成功生成 position `8`/`9`，第一个 principal 重试稳定 replay Event
`03a24488-8c6a-446f-89a2-ec62c5c5fd13`。Runtime live/ready 与 public MCP healthz/readyz
全部通过，API、worker、public MCP 三个 service 均 active 且 `NRestarts=0`。

## 4. Failure reflection 与修复

### 4.1 shared database 测试数据污染

第一次直接运行完整 Runtime suite 使用长期共享数据库，固定测试 binding 与历史数据产生四项
非 C1 failure。没有清理用户数据；新 C1 测试改用唯一 project/task/content，并改用一次性 fresh
database full gate。最终 922 项通过且数据库自动清理。

### 4.2 错误工作树的 `.env` symlink

第一次 project full-gate 尝试让 `.env` symlink 指向 sibling repo。runner 对路径做 `resolve()`，
因此错误地从旧 sibling Runtime 运行，得到的 retrieval failure 证据无效。最终使用当前工作树内的
临时 hardlink，使 runner root 保持在当前 Runtime；测试后自动 unlink。

### 4.3 window 并发边界

初版在默认 `READ COMMITTED` 下先读 watermark、再读 rows。独立 reviewer 指出并发 append
可能出现在 rows 中，却大于返回 watermark。修复为同一 `REPEATABLE READ` 事务，并增加确定性交错
测试：第二连接在两条 SELECT 之间 append；当前窗口只见旧 Event，后续窗口才见新 Event。

### 4.4 幂等键 namespace

初版把公开 operation ID 直接放入 tenant 共享 idempotency namespace。独立 reviewer 指出不同
principal 可能互相冲突。修复后内部 key 绑定 actor、principal、project、task 与公开 operation ID；
真实 PostgreSQL 测试证明两个 principal 使用相同公开 ID 时独立 append、各自稳定 replay。

### 4.5 测试执行目录

一次 focused integration 从仓库根目录启动，Alembic 相对路径找不到 `script_location`。这属于命令
执行错误；切换到 `runtime/` 后正确复跑。没有产品数据或 schema failure。

## 5. Subagent milestone review

三个独立 reviewer 的最终结论：

```yaml
functional:
  decision: PASS
  required_fixes: []
architecture:
  decision: PASS
  required_fixes: []
generalization_and_simplicity:
  decision: PASS
  required_fixes: []
```

最初发现的两个 required finding 均已修复并由原 reviewer 复核。没有人工 adjudication，也没有
消费 Formal holdout。

## 6. 保留的边界与限制

- `/v1/host-events/*` 是 trusted Host REST surface，不是 public hostile-client API；tenant/actor
  来自 credential，principal/project/task 由可信 Host adapter 选择。若未来公开该路由，必须增加
  server-verifiable binding，不能把这些字段交给模型自由指定。
- 部署前已有的 C1 Event 仅为 smoke/disposable 数据；内部 idempotency key 从公开 ID 改成绑定摘要
  后，旧 smoke Event 不会通过新 key replay。若未来出现真实 pre-fix Event，需先做兼容迁移。
- Event journal 仍是 SHADOW；没有 adapter 自动写入，没有 State basis，没有 dirty/checkpoint。
- journal epoch、retention-gap proof、late Event、batching 与 semantic grounding benchmark 保持延期。

## 7. 下一步

下一个最小增量是 C2 sparse observation adapter：只把 Host 已客观观察到的 dialogue Evidence、
去重文件集合、重要 test transition、material command failure 与 Git commit 聚合后写入 C1 journal。
它不得判断 requirement/decision/hypothesis，不得逐命令复制 execution log，也不得触发 Working
State update。
