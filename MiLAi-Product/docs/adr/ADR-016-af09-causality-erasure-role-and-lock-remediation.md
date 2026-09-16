# ADR-016：AF-09 Causality、Erasure、Role 与 Trust Anchor 整改

> 状态：`ACCEPTED FOR 1.0.0-candidate.2`  
> 日期：`2026-08-17`  
> 关闭：`AF09-F07`～`AF09-F10`

## Decision

1. Blob erasure 使用 typed durable-absence proof；worker 不得丢弃 adapter 结果，SQL 不得在没有验证
   disposition、tenant、lease、URI、content hash 与 proof hash 时写 `ERASED`。
2. API、Steward、Worker DSN 必须分别使用精确 `milai_api/milai_steward/milai_worker` login。
   建池、ping 与每次借用连接都核验 `session_user=current_user=expected role`，并拒绝 superuser、
   BYPASSRLS、CREATEDB、CREATEROLE、INHERIT 或 MiLAi object owner。
3. RYW 使用服务器从真实 Outbox ID 签发的 tenant-bound HMAC token。签名 secret 与客户端 Bearer
   token 强制独立；API 只获准调用 narrow causal summary functions，没有 Outbox 原表读取权。
4. Architecture manifest 仍不自锁，但 review/release 必须从 bundle 外提交回执取得预期 SHA-256；
   缺失、格式错误、不匹配和 coordinated content+manifest substitution 全部失败。

## Implementation and evidence

- Migrations：`0018_causal_trace`～`0023_erasure_sha256_repair`；后两项也验证已部署数据库的前向修复。
- Runtime：`domain/causality.py`、retrieval wait/trace、blob typed proof、database exact-role boundary。
- Tests：causal token reached/timeout/dead-letter/forgery/future/cross-tenant/concurrent snapshot；Blob
  tamper/symlink/non-regular/missing、伪造 proof 后 crash recovery；owner/swapped login 与 cluster role
  attribute negatives；外部 trust-anchor coordinated-tamper negative。

## Consequences

`MILAI_CAUSAL_TOKEN_SECRET` 成为必填 server-only 配置，至少 32 字符且不得等于
`MILAI_API_TOKEN`。Candidate.2 migration `0015+` 属于 forward-only audit evolution；恢复依赖新空库、
一致性 backup/restore 和显式 forward repair，不假装可逆地删除治理或擦除证明。
