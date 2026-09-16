# MiLAi Permissions and Trust Boundaries

> Architecture `1.0.0 FROZEN`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

## 1. 安全原则

- 默认单机、单配置 tenant、loopback-only；远程暴露是另一个安全阶段。
- 每个 tenant-owned row 都由 forced RLS 保护。
- transaction-scoped session context 同时设置 tenant 与 actor，归还连接前必须 reset。
- canonical mutation 只通过 `SECURITY DEFINER` Steward procedure，函数内重验 tenant、角色、
  live Evidence、CAS 与 policy 输入。
- function owner 不作为常驻登录身份；`PUBLIC` 无执行权。
- permission、retention 或 tenant 无法判断时 fail closed。

## 2. 角色

| Role | Login/use | Allowed | Explicitly denied |
| --- | --- | --- | --- |
| Migration Owner | migration window only | DDL、ownership、roles、grants、migration | API/worker 常驻连接 |
| API Runtime | local API process | typed Evidence/API 写入、允许的 canonical 查询、proposal 提交 | Claim/OpenIssue/Decision direct DML、DDL |
| Steward Executor | API 经受控调用 | EXECUTE canonical/revoke/settlement procedures | table ownership、任意表 DML、migration |
| Projection Worker | local worker | lease outbox；写 delivery/watermark/search projection；purge eligible derivatives | Claim/OpenIssue/Decision DML、authority decision |
| Audit Runner | offline/local job | consistent snapshot、只读 audit、backup/restore verification | production canonical commit |

三个在线 DSN 的 login 身份是协议的一部分：API=`milai_api`、Steward=`milai_steward`、
Worker=`milai_worker`。连接池 open、ping 和每次借用连接都必须验证
`session_user=current_user=expected_role`；任一 runtime role 若具有 superuser、BYPASSRLS、
CREATEDB、CREATEROLE、INHERIT 或拥有 MiLAi schema/object，立即拒绝启动/请求。Migration Owner
不能代填任何 runtime DSN，角色互换也不能“权限够用即接受”。

## 3. Grant matrix

符号：`R` read，`I/U` 受限写，`X` procedure execute，`—` 禁止。

| Resource | Migration | API | Steward | Worker | Audit |
| --- | ---: | ---: | ---: | ---: | ---: |
| Evidence/API input tables | owner | R/I | R/X | R for purge refs | R |
| Claim/OpenIssue/history tables | owner | R | X only | R only when projecting | R |
| Legacy quarantine ledgers | R/I during offline migrations; U/D trigger-denied | — | tenant-scoped R | — | tenant-scoped R |
| Steward procedures | owner | approved X entry | X | — | — |
| Outbox | owner | narrow causal summary X only | emitted inside X | R/U lease state | R |
| Search projection | owner | R | — | R/I/U/delete-derived | R |
| Context/Chat | owner | allowed R/I | invalidate via X | purge-only | R |
| Backup metadata | owner | status R | — | obligation reconcile only | R/I through backup procedure |
| Schema/roles/grants | owner | — | — | — | inspect only |

任何临时扩大权限都必须通过 migration 和负向测试，不能在部署脚本中临时 `GRANT ALL`。

## 4. Tenant/RLS contract

每个请求事务执行以下逻辑：

```text
authenticate
→ derive configured tenant and actor from trusted boundary
→ begin transaction
→ SET LOCAL milai.tenant_id / milai.actor_id
→ execute typed command/query
→ commit or rollback
→ reset pooled connection state
```

要求：

1. body/header 中 tenant 与认证 tenant 不同返回 `TENANT_MISMATCH`。
2. RLS policy 使用数据库 session tenant，不信任任意 body tenant。
3. 测试使用真实 login roles，不能只用 owner/superuser。
4. missing tenant、malformed tenant、cross-tenant ID 和 pool reuse 都必须负向验证。
5. 错误不能泄露目标 ID 是否存在于另一 tenant。

`legacy_issue_transition_quarantine` 与 `legacy_grounding_relation_quarantine` 都属于 tenant-owned
row，启用并强制 RLS。它们是迁移审计证据，不是 canonical history/lineage：API 与 Worker 无任何
表权限，Steward/Audit 只能 tenant-scoped SELECT；仅 Migration Owner 能在 0024/0025 的离线事务中
INSERT。0026 只以 Migration Owner 锁定并读取 source proof，不写 ledger/authority。两个 append-only
trigger 对 Owner 的 UPDATE/DELETE 同样报 `APPEND_ONLY_VIOLATION`，防止
“有权限做 migration”等同于“有权限重写历史”。

## 5. Procedure boundary

Steward procedure 必须：

- 明确 `search_path`，避免对象劫持；
- 验证 caller role 与 tenant；
- 锁定或 exact-CAS 当前 Head/Issue revision；
- 重验 live Evidence、GroundingBlock、Scope/time 和批准 decision；
- 在一个事务内写 mutation、Decision result、OperationalEvent 与 Outbox；
- 使用数据库时间和数据库生成 commit sequence；
- 失败时全部回滚并返回稳定错误码。

模型、LLM、embedding、外部 adapter、API route 和 worker 都不能取得 procedure owner 凭据。

## 6. Network and secret boundary

默认允许：

```text
browser/client -> 127.0.0.1 MiLAi API
MiLAi API/worker/audit -> 127.0.0.1 PostgreSQL
MiLAi process -> configured local blob root
```

默认禁止公网监听、FRP/Nginx 暴露、共享数据库密码和无 TLS 远程连接。启用远程访问前必须独立通过：
TLS、强认证、device/session revoke、CSRF/CORS/cookie、rate limit、secret rotation、审计、
备份与事故响应门禁。

密钥只来自受限环境或 secret provider；不得写入仓库、manifest、trace、prompt 或 API error。
客户端 Bearer secret 与 `MILAI_CAUSAL_TOKEN_SECRET` 必须不同；后者至少 32 字符、server-only，
只用于签发/验证 tenant-bound causal token。API 不能用客户端 token 作为 HMAC key。

## 7. Log privacy

可记录：对象 ID、不可逆 fingerprint、reason code、状态、耗时、route、commit sequence。

禁止记录：Evidence 正文、完整消息/query/prompt、password、token、cookie、DSN、私密 profile 推断。
日志 redaction 在结构化日志边界执行，异常对象也必须经过相同过滤。

## 8. External adapter isolation

外部项目只接收只读 export snapshot 或最小化 Outbox payload，并使用独立 namespace、数据目录、
凭据和 watermark。它们：

- 不持有 Migration Owner 或 Steward 凭据；
- 只能返回带 source refs 和 adapter version 的 typed candidate；
- 不能将 external mutation/delete 直接映射为 canonical mutation；
- 可被 feature flag 完全关闭，且关闭后 L0、revoke、backup 和启动仍工作；
- 涉及敏感正文时必须另行批准 data policy。

## 9. 发布证据

候选门禁至少包括：真实角色 direct-DML denial、cross-tenant denial、missing session denial、
body tenant mismatch、pool reset、exact-login/role-swap/owner denial、unsafe cluster attributes/object
ownership denial、procedure execute allowlist、Outbox raw-read denial、causal-secret separation、log secret
canary、external dependency absence。任何 P0 失败均阻断发布和 schema freeze。
