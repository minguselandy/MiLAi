# ADR-001：Runtime 技术基线

> 状态：`ACCEPTED FOR 0.1.x EXPERIMENTAL`  
> 日期：`2026-08-15`  
> 冻结影响：不构成 Schema freeze

## Context

MiLAi 需要从零建立本地优先的模块化单体，同时保留真实 PostgreSQL transaction、
RLS、FTS、pgvector、受控 procedure 和单 worker。MiLAi Logical Architecture 现由本项目设计，
当前处于 `1.0.0-candidate.1`，因此技术选择必须可替换、可测试，并避免把外部 memory
framework 引入 canonical 路径。

## Decision

- Runtime 使用 Python 3.11，支持范围暂定 `>=3.11,<3.13`；
- HTTP 使用 Flask application factory，服务入口使用 Waitress；
- typed configuration 使用 Pydantic Settings，但只接受显式 `MILAI_*` allowlist；
- PostgreSQL 16 系列是唯一 canonical store，pgvector 只保存派生向量；
- 数据库访问使用 psycopg 3，关键事务使用显式 SQL/受控 procedure；
- Alembic 版本化表、function、procedure、RLS policy 和 grants；
- worker 直接消费 transactional outbox，不引入 broker；
- packaging 使用 `pyproject.toml` 和 `uv.lock`；
- pytest、Ruff、mypy 与真实 PostgreSQL role tests 构成基础质量门禁。

## Consequences

- API 与 worker 可以共享 domain/application 代码，但必须使用不同数据库登录角色；
- ORM 不承担 CAS、append-only 或权限语义；
- Docker Compose 当前只提供 loopback PostgreSQL，API/worker 从锁定的 host venv 运行；
- 新依赖必须进入 lockfile 并接受 license/替代性检查；
- candidate bundle 每次变更必须重新执行 crosswalk/lock validator，冲突时更新或废弃本 ADR。

## Rollback

在 canonical product data 进入前，可删除 `runtime/` 并重建候选技术栈。进入真实数据后，
替换 driver/framework 必须保持 API、Migration、procedure 和备份格式兼容，并另写 ADR。
