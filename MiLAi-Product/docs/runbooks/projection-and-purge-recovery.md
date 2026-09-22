# Projection、Dead-letter 与 Purge 恢复 Runbook

> `0.1.x EXPERIMENTAL / CANDIDATE / NO-GO FOR SCHEMA FREEZE`

## Worker 单周期与依赖检查

`milai-worker --once` 启动后先初始化 settings/依赖并执行 Blob orphan reconciliation，
再依次处理 `evidence`、`purge`、`fts`、`vector`，最后关闭数据库连接并退出。
`MILAI_WORKER_EVENT_LIMIT` 是**每个 projection** 的单周期上限，不是全局事件数或一次只处理
一个事件；batch size 不能突破剩余上限。处理过 work 的 projection 会 reconcile watermark。
空队列或无 eligible work 时不会进入 polling sleep；剩余 work 需要下一次调用或持续 worker。

`milai-worker --check` 只检查依赖（包含 embedding warmup 和数据库 ping），不 lease/process
队列、不推进 watermark，也不做 orphan cleanup。它与 `--once` 互斥。依赖检查可能初始化目录
或调用所配置的 embedding provider，不应把它理解成完全无外部 I/O。

退出码 `0` 表示周期正常返回，**不保证所有 delivery 成功或 queue 已清空**。单项处理失败会
持久化为 `PENDING`（有 retry delay）或达到重试上限后的 `DEAD_LETTER`，记录安全错误码，
watermark 不跨失败 gap。未处理的启动/数据库异常以非零退出。调度器需要结合 delivery、
watermark 和安全日志判断是否追平，不能仅凭进程退出码宣布投影成功。

真实 PostgreSQL 的有界队列、负路径与退出证据见
[worker-once revalidation](../revalidation/worker-once/REVALIDATION.md)。

## Dead-letter

每个 `evidence`、`fts`、`vector`、`purge` projection 有独立 delivery 和 contiguous watermark。出现
`DEAD_LETTER` 后 watermark 不跨 gap；先保存 outbox ID、projection、attempt count 和安全错误码，
修复依赖，再由 Steward 调用显式 retry。不要直接更新 delivery 或 watermark。

Purge dead-letter 期间 TX-05 的 GroundingBlock 仍同步生效，retrieval/chat 必须 fail closed。
恢复后查询 deletion request，分别确认 derived purge、primary bytes、backup expiry 和 retention。

## 搜索 Projection 全量重建

停止 worker，确认 canonical DB 可用，然后执行：

```bash
uv run milai-ops rebuild-projection \
  --projection fts \
  --confirm REBUILD_DERIVED_PROJECTION
uv run milai-ops rebuild-projection \
  --projection vector \
  --confirm REBUILD_DERIVED_PROJECTION
uv run milai-worker
```

受控 procedure 只清除指定 tenant 的 derived rows、delivery 和 watermark，不修改 Claim、
ClaimVersion、Head、Grounding、OpenIssue 或 outbox。worker 从 outbox sequence 重新回放；达到最新
sequence 前，RYW 使用 canonical fallback，任何 consistency 仍经过 Gate。

## Purge reconciliation

不要把 purge projection 当作普通搜索索引清空。按 deletion request 检查：

- `derived_purge_status=DEAD_LETTER`：修复 adapter/lease 后显式 retry；
- `primary_bytes_status=BLOCKED_SHARED_REFERENCE`：保留 Blob，直到最后一个 live/held ref 消失；
- `RETENTION_BLOCKED`：等待合法 retention 变化，禁止手工擦除；
- `ERASED` 但 `backup_expiry_status=PENDING`：按 backup runbook 处理旧归档 obligation；
- `primary_bytes_status=ERROR` 且 `last_error_code=INVALID_ERASURE_PROOF`：数据库没有接受物理完成；
  检查 Blob URI/hash、文件类型和 worker 身份后显式 retry。若文件已在故障点删除，adapter 必须
  返回 `VERIFIED_ALREADY_ABSENT` 的身份绑定证明，不能伪造“本次已擦除”；
- 所有 primary/backup 状态完成后仍保留 append-only Evidence identity、GroundingBlock 和审计记录。

`ERASED` 只在数据库验证 disposition、tenant、Blob URI、content hash、lease 与 SHA-256 proof
后写入。合法 disposition 只有 `ERASED_AND_VERIFIED_ABSENT` 和
`VERIFIED_ALREADY_ABSENT`；两者都表示 durable absence，但审计语义不同。

物理清理失败、worker 停止或索引残留都不能让旧内容重新可见；若 Gate 或 canonical DB 不可用，
立即停止 authority-bearing answer 并返回 abstention。
