# MiLAi Threat Model and Privacy Review

> Architecture `1.0.0 FROZEN`  
> Review scope：local synthetic logical-architecture release  
> Decision：`PASS_FROZEN / SYNTHETIC DATA ONLY`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

## 1. Scope and assumptions

本评审覆盖单机、单用户、loopback API/PostgreSQL、当前 31 张 tenant-owned 表、本地 Blob、
worker、backup 与已下载但默认离线的 external projects。它不批准公网部署、多人协作、移动设备、
云模型传输或真实个人数据。

假设主机管理员可读取进程和磁盘；因此数据库 RLS 防止应用角色越权，但不能抵抗已取得 root 的
攻击者。host/disk security 属于部署共同责任。

## 2. Protected assets

| Asset | Sensitivity | Required property |
| --- | --- | --- |
| Evidence/Blob content | highest | confidentiality、integrity、revocation |
| Claim/OpenIssue/Decision | high | integrity、tenant isolation、history |
| credentials/KEK/token/DSN | highest | non-disclosure、rotation |
| Context/Chat/query | high | minimization、lineage、expiry |
| Outbox/projection | medium-high | integrity、purge ordering |
| Backup/deletion obligation | highest | integrity、confidentiality、recoverability |
| Audit/trace/log | medium-high | tamper evidence、payload minimization |
| Architecture/manifest + external receipt | integrity-critical | reproducibility、drift/substitution detection |
| Legacy quarantine/provenance chains | integrity-critical | exact rows/hash、append-only、tenant isolation、non-authority |

## 3. Trust boundaries

```text
untrusted local client input
→ loopback API authentication/validation
→ API Runtime DB role + tenant session
→ Steward procedure boundary
→ canonical PostgreSQL/RLS
→ Outbox
→ least-privilege worker / derived projection / Blob

canonical read snapshot
→ ECS/Canonical Gate
→ bounded ContextCapsule
→ deterministic/model answer candidate

Audit Runner
→ exported DB snapshot + Blob inventory
→ isolated backup/restore target

read-only export
→ optional external adapter namespace
→ typed candidate
→ canonical ID resolution + Gate
```

## 4. Threat register

| ID | Threat / attack | Current control and evidence | Residual decision |
| --- | --- | --- | --- |
| TM-01 | guessed UUID or body tenant accesses another tenant | forced RLS, trusted session tenant, mismatch checks, real-role negative tests | candidate pass |
| TM-02 | API/worker/model directly alters Claim/OpenIssue/history | minimal grants, Steward procedure, append-only trigger, direct-DML tests | candidate pass |
| TM-03 | `SECURITY DEFINER` search-path or caller confusion | fixed search path, tenant/role revalidation, execute allowlist | candidate pass; review each migration |
| TM-04 | concurrent writers move Head/issue twice | exact-head/expected-revision CAS, two-connection tests | candidate pass |
| TM-05 | stale vector/cache revives revoked belief | ECS/Gate, synchronous block, canonical-required fallback | candidate pass |
| TM-06 | Context compression hides conflict/constraint | protected sections, Bmin infeasible failure, live-issue tests | candidate pass |
| TM-07 | forged or stale action confirmation | typed USER_CONFIRMATION Evidence, five-minute/live/content binding, DB revalidation | candidate pass |
| TM-08 | log/error/trace leaks payload or secret | allowlisted structured metadata, fingerprints, redaction tests | candidate pass; production log review pending |
| TM-09 | path traversal/symlink corrupts or exposes Blob | tenant CAS URI, resolved-root containment, regular-file/hash checks, private modes | candidate pass for synthetic |
| TM-10 | disk theft exposes plaintext Blob | current store is plaintext | **P0 real-data blocker: ADR-012** |
| TM-11 | backup omits a table/blob or is tampered | catalog equality, per-table/blob hash, pre-restore validation | candidate pass for synthetic |
| TM-12 | deletion reported complete while projection/backup retains data | layered state, obligations, dead-letter visibility, reconciliation drill | candidate pass; physical completion remains explicit |
| TM-13 | external memory/model becomes authority or exfiltration route | dependencies absent from runtime, adapter namespace/credential/gate, default disabled | candidate pass while disabled |
| TM-14 | dependency/source drift invalidates evidence | uv lock, source/Git locks, bundle verifier | candidate pass |
| TM-15 | remote listener exposes weak local token | remote bind rejected, Compose loopback | remote deployment **not approved** |
| TM-16 | malicious archive overwrites restore target | restore-to-empty rule, archive/hash validation | candidate pass; sandbox drill remains release evidence |
| TM-17 | denial of service via huge input/budget/retry | typed bounds, bounded worker retry/context budget | partial; performance/abuse baseline not frozen |
| TM-18 | local root or compromised host reads all data/keys | outside RLS trust boundary | requires OS hardening/disk encryption/incident plan |
| TM-19 | owner/swapped DSN 让 runtime 获得错误数据库身份 | exact URL login + per-connection session/current-user and role-attribute/ownership attestation | candidate pass |
| TM-20 | 客户端伪造 RYW sequence、跨 tenant token 或复用 API secret | real Outbox-ID resolution, narrow SECURITY DEFINER function, tenant-bound HMAC, distinct causal secret, bounded canonical fallback | candidate pass |
| TM-21 | worker 删除失败或伪造结果后 SQL 报告 ERASED | typed identity-bound absence proof, lstat/hash/fsync/recheck, independent SQL SHA-256, crash-retry drill | candidate pass |
| TM-22 | attacker 同时修改 candidate 内容与 bundle 内 manifest | review/release 强制 bundle 外 trusted manifest digest；missing/mismatch/coordinated-tamper tests | candidate pass |
| TM-23 | upgrade 仅凭相似 ID/时间猜测历史，伪造 creation/Decision authority，或在未知 shape 上继续服务 | corrected 0024/compatibility 0025 在任何写前核对 Proposal、Decision、actor、sequence、original Outbox；unknown/conflict 单事务 fail closed并保持 prior head | candidate pass；同 reviewer 必须重跑 fresh/compat populated regressions |
| TM-24 | 为“修好”canonical replay/lineage 而静默删除、改写非法 transition/rejected grounding，或 Owner 事后篡改隔离证据 | exact rows + PostgreSQL SHA-256 原子移入两个 forced-RLS ledger；governed replacement/reversal；rejected relation 从 canonical 移除；Owner U/D trigger denial；backup catalog/hash coverage | candidate pass；quarantine 不是 authority source |
| TM-25 | 多个 JSON 文档重复同一 request UUID，却没有真实 DeletionRequest，migration 仍重建 STEWARD APPROVE | ACCESS EXCLUSIVE lock + tenant join actual DeletionRequest，并与 Evidence/Blob、actor/reason/time/status、idempotency、OperationalEvent、revoke/purge Outbox 逐腿一致；stable F11 error + whole rollback | candidate pass；九类独立破坏及 candidate.3 compatibility negative test |
| TM-26 | 被 REJECT 的 legacy resolution relation 仍由 Issue/Context 返回，形成 proposal submission 的 surviving canonical effect | exact Proposal support-set proof；relation hash quarantine + canonical delete；final approved-only postcondition；真实 Issue/Context consumer tests | candidate pass；同 reviewer 必须重放 F01 counterexample |
| TM-27 | Legacy TX-05 各实体 ID/state 一致，但四个 event/record `created_at` 来自不同事务，migration 仍合成 APPROVE | DeletionRequest/Evidence 时间为锚，corrected 0024/0025 精确关联 idempotency、OperationalEvent 与两条 Outbox；proof-only 0026 重证 candidate.4 state；stable F12 error + prior-head rollback | candidate pass；四个具名 fresh negatives、0024/0025 compatibility negatives 与六腿 valid control；同 reviewer 必须独立重放 |

## 5. Privacy data-flow review

Data minimization rules:

- Evidence plaintext only enters Blob; canonical rows reference identity/hash and structured claims.
- query/prompt/message plaintext is not written to RetrievalTrace or log; only fingerprint and bounded IDs.
- Context copies only Gate-approved minimum and expires/invalidates pointers.
- external adapters receive no data by default; future exports require per-adapter data inventory and approval.
- backup contains the full sensitive state and inherits the strongest retention/encryption requirement.
- model-produced sensitive profile is never authority without Evidence, proposal and review.

Purpose/retention:

- Evidence retains source-specific permission/retention snapshots;
- legal hold and unknown retention preserve bytes but never restore authority;
- deletion status distinguishes revoke、derived purge、primary erase、backup expiry；
- no telemetry or cloud export is enabled in the candidate.

## 6. Abuse cases verified

- missing/wrong bearer does not reveal resource state；
- tenant switch and pool reuse do not cross isolation；
- direct canonical/history DML is denied；
- idempotency conflict/rollback leaves no duplicate side effect；
- stale/revoked/scope/time/authority candidate is rejected；
- canonical outage abstains；
- pointer after revoke fails；
- forged/expired confirmation abstains；
- log canary/unsafe exception is redacted；
- external frameworks are absent from runtime imports；
- backup archive/hash/catalog mismatch fails closed；
- bundle path escape/hash/Git drift is rejected。
- owner/role-swapped/unsafe-attribute DB login 在 open/ping/borrow 边界被拒；
- forged/cross-tenant/future causal token 被拒，timeout/dead-letter 留痕并走 canonical fallback；
- Blob tamper/symlink/non-regular/forged absence proof 不会产生 ERASED；
- coordinated bundle+manifest substitution 无外部 trust anchor 时失败。
- unprovable fresh populated history 使 0024 整体回滚到 0023；unprovable candidate.3 compatibility 使
  0025 整体回滚到 0024；unprovable candidate.4 certification 使 0026 整体回滚到 0025；
  canonical/quarantine 均无本次部分写；
- exact legacy transition/relation row 的 SHA-256 可重算，Migration Owner 也不能 UPDATE/DELETE 两个
  quarantine ledger；
- pending pre-Decision effect 只能 POLICY REJECT + CAS reversal，不能被 migration actor 批准或提升。
- rejected resolution branch 不再由真实 Issue/Context 返回；真实 APPROVE relation 保持并链接 Decision；
- TX-05 actual DeletionRequest 与其余 provenance 任一腿缺失/冲突都以固定错误码 whole rollback。
- TX-05 六个 durable transaction timestamps 必须精确一致；四条独立一秒偏移均不能获得新 head。

## 7. Open gates

| Gate | Required before |
| --- | --- |
| Implement ADR-012 envelope encryption/key recovery/rotation | any real personal data |
| source-specific privacy inventory and user authorization | legacy/real-data import |
| TLS、strong auth、session/device revoke、CSRF/CORS/rate limit | any remote access |
| target-device load/abuse and resource limits | performance SLO / broader beta |
| independent security/privacy review | architecture freeze |

## 8. Review conclusion

当前控制足以继续 synthetic local candidate 的架构和回归验证。由于 TM-10、远程访问和真实数据
授权门尚未关闭，本评审明确不批准真实个人数据、production、远程部署或 schema freeze。
