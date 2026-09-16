# MiLAi 一致性备份与恢复 Runbook

> `0.1.x EXPERIMENTAL / CANDIDATE / NO-GO FOR SCHEMA FREEZE`

## 边界

备份归档包含单 tenant PostgreSQL custom dump、完整本地 Blob root、逐文件 SHA-256、Alembic
revision 和全量 tenant-owned durable inventory。工具拒绝在线 API/Steward/Worker session、跨 tenant 数据库、
已有目标目录和非空恢复目标。

Inventory 覆盖由数据库 catalog 反向校验：所有含 `tenant_id` 的 base table 必须恰好出现在
manifest 配置中。任何新 durable tenant 表若未加入备份模型，backup/restore 都 fail closed，
不能生成看似成功但不完整的归档。当前覆盖 Claim/OpenIssue/Evidence、Chat/Context、
Episode/Settlement、outbox/projection/search/trace、operational/deletion 与 backup obligation。
Migrations 0024/0025 新增、0026 只读认证的 `legacy_issue_transition_quarantine` 与
`legacy_grounding_relation_quarantine` 也必须完整覆盖；它们保存 exact legacy transition/rejected
relation、recomputable SHA-256 与 reconciliation links，但不参与 canonical Issue replay/lineage。

只使用 `milai-ops` 创建的归档，才能参与 `backup_expiry_status` 对账。手工复制、云盘同步和
未登记压缩包不属于可证明备份集。

## 创建与验证

1. 停止 API 和 worker，确认没有仍在处理的请求；
2. 保持 PostgreSQL 运行；
3. 确认 `MILAI_MIGRATION_DATABASE_URL` 使用 Migration Owner，
   `MILAI_AUDIT_DATABASE_URL` 使用 Audit Runner；
4. 创建新目录名的归档：

```bash
uv run milai-ops backup --output ./var/backups/milai-YYYYMMDDThhmmssZ
uv run milai-ops verify-backup --archive ./var/backups/milai-YYYYMMDDThhmmssZ
```

工具在 `REPEATABLE READ` transaction 内锁住 MiLAi 表的写入、导出 snapshot、执行
`pg_dump --snapshot`、复制 Blob，再生成 manifest。密码只通过 libpq 环境传递，不进入参数、
manifest 或日志。

## 恢复演练

恢复永远指向新建的空数据库和空 Blob 目录，不覆盖当前实例：

```bash
export MILAI_RESTORE_DATABASE_URL='postgresql://milai_owner:...@127.0.0.1:15432/milai_restore_drill'
uv run milai-ops restore \
  --archive ./var/backups/milai-YYYYMMDDThhmmssZ \
  --target-blob-root ./var/restore-drill/blobs \
  --confirm-empty-target
```

成功条件：dump 可读、所有 Blob hash/size/path 相同、Alembic revision 相同，并且 manifest 中
每张 tenant-owned durable table（包括 Episode/Settlement、backup obligation 与两个 legacy
quarantine ledger）的 count 和 SHA-256 inventory 全部相同。

若归档 revision 落后当前候选版，在恢复副本上设置 `MILAI_MIGRATION_DATABASE_URL` 后执行：

```bash
uv run alembic upgrade head
uv run milai-db-check
```

先在副本上完成 forward repair、完整测试和 inventory 报告，再决定是否切换；禁止手工改
`alembic_version`。

## 备份过期与删除对账

Evidence revoke 会为仍含对应 Blob content hash 的每个 ACTIVE backup 建立 deletion obligation。
物理 Blob 已擦除但旧归档仍活动时，`backup_expiry_status` 保持 `PENDING`。

按保留策略确认可擦除归档后：

```bash
uv run milai-ops expire-backup \
  --archive ./var/backups/milai-YYYYMMDDThhmmssZ \
  --confirm ERASE_BACKUP_ARCHIVE
```

工具先验证归档，再精确删除该目录，最后以 `ARCHIVE_ERASED` 记录 manifest 过期并完成相关
obligation。若归档已经擦除但数据库对账失败，错误会返回 backup ID；保留该 ID，修复 Audit
连接后由审计 procedure 完成 reconciliation，不得伪造“已删除”。

`LEGAL_HOLD`/`UNREADABLE` 的 request 继续显示 `RETENTION_BLOCKED`，不能通过备份过期绕过。
