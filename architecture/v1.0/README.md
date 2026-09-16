# MiLAi Logical Architecture 1.0.0 Frozen Bundle

> Bundle version：`1.0.0`  
> Status：`FROZEN LOGICAL ARCHITECTURE`  
> Schema：`0.1.x EXPERIMENTAL`  
> Implementation：`CANDIDATE`  
> Freeze：`LOGICAL ARCHITECTURE FROZEN / NO-GO FOR SCHEMA FREEZE`

本目录把根目录
[`MiLAi_Logical_Architecture_v1_设计文档.md`](../../MiLAi_Logical_Architecture_v1_设计文档.md)
拆分为可校验的冻结逻辑架构 bundle。它由独立 reviewer 对精确 candidate.5 bytes 全量接受后
单独发布，不是从外部项目复制的规范，也不把当前 runtime 或 experimental Schema 自动认定为
production/frozen。

## Bundle index

| Artifact | Responsibility |
| --- | --- |
| `BASELINE.md` | 设计输入、版本、license、hash 和当前实现事实 |
| `OBJECTS.md` | logical aggregate、对象身份、mutability、writer 与 authority |
| `PERMISSIONS.md` | trust boundary、角色、RLS、tenant 与 credential isolation |
| `INVARIANTS.md` | G1–G9、I-01～I-12 与 hard failure |
| `TRANSACTIONS.md` | TX-01～TX-06、EP-01/02、CAS 与 atomicity |
| `RETRIEVAL_CONTEXT.md` | QueryPlan、L0/L1/L2、Gate、Context、Chat 与 external candidates |
| `DELETION_RECOVERY.md` | revoke、purge、watermark、backup obligation 与 restore |
| `THREAT_MODEL.md` | assets、trust boundaries、threats、privacy review 与真实数据门 |
| `FREEZE_REVIEW.md` | AF-09 独立 ACCEPT 与冻结发布链 |
| `AUTHOR_PREFLIGHT.md` | candidate.5 作者预检与 release promotion 导航；不替代独立签署 |
| `AF09_REMEDIATION.md` | candidate.4 F12 → candidate.5 整改 → independent ACCEPT 审查链 |
| `CROSSWALK.md` | 人类可读的实现/测试映射摘要 |
| `crosswalk.json` | machine-readable goal/invariant/transaction/role/gate crosswalk |
| `architecture_manifest.json` | required artifact、bundle lock 和 source lock |
| `scripts/validate_bundle.py` | 结构、ID、coverage、路径和状态校验 |
| `scripts/verify_lock.py` | bundle/source SHA-256 drift 校验 |
| `scripts/refresh_manifest.py` | 只刷新已声明 lock 的可复现 SHA-256，不扩大锁定范围 |
| `tests/test_bundle.py` | 正向与 missing mapping/hash drift 负向测试 |

## Normative language

| Word | Meaning |
| --- | --- |
| MUST / 必须 | freeze 和实现的不可缺条件 |
| MUST NOT / 禁止 | 违反即阻止架构冻结或产品发布 |
| SHOULD / 应 | 默认设计；偏离需要 ADR 和测试 |
| MAY / 可以 | 可选能力，不是 v1 完成条件 |
| PARKED | 不进入在线依赖和 Definition of Done |

## Authority

当前优先级：

1. 本 `1.0.0 FROZEN` bundle 中的 G/I 与 MUST；
2. 独立 AF-09 acceptance 及其精确 candidate.5 chain of custody；
3. `MiLAi_Lean_V1_实施合同.md`；
4. 产品/需求/路线文档；
5. experimental implementation。

bundle 内部冲突时，`INVARIANTS.md` 的 I-01～I-12 优先于物理实现建议；必须修复冲突并提交
ADR，不能让代码事实静默重定义架构。

## Validation

在项目根目录运行：

```bash
runtime/.venv/bin/python architecture/v1.0/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0/scripts/verify_lock.py \
  --scope all --mode release --expected-manifest-sha256 "$TRUSTED_RELEASE_MANIFEST_SHA256"
runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0/tests -v
```

Release 验证不得只信任 bundle 内 manifest；Verifier 必须从 bundle 外的 release receipt 取得 digest：

```bash
runtime/.venv/bin/python architecture/v1.0/scripts/verify_lock.py \
  --scope all --mode release --expected-manifest-sha256 "$TRUSTED_RELEASE_MANIFEST_SHA256"
```

review/release 模式缺少外部 digest 或 digest 不匹配时强制失败。

Candidate.1–4 均由同一独立 reviewer 判定 `REVISE`。Candidate.5 的外部 receipt 锚定 manifest
`ece90366e5e3e3647af729351d8ae80310c8f6c30db1cf85b5a74ccb4168ed64`；同一 reviewer 对 175 个
archive members、121 项 exact-role runtime、三代 F12 对抗重放和全部 AF-09 门禁完成独立复审并
`ACCEPT`。接受记录 SHA-256 为
`8ddf9e8a302b46404319ef2b27d99403f73b4d71127b4483c3b333d27230d1f3`。

`validate_bundle.py` 验证所有 required artifact、G/I/TX/role/gate ID、crosswalk coverage、
repo-relative evidence path、独立 acceptance 与 frozen banner。`verify_lock.py` 验证 bundle 与输入
基线的 SHA-256。逻辑架构已冻结，但任一 release lock 失败都阻止使用该 release；Schema 继续
保持 `NO-GO FOR SCHEMA FREEZE`。

完整 release audit 使用默认 `--scope all`，同时验证 sibling external assets 和 Git revisions。
普通 CI checkout 不包含这些 sibling 目录，因此只运行 `verify_lock.py --scope project`；
该较小 scope 不能作为 AF-09 release lock 的替代证据。

## Change control

- 修改 G/I/object/role/transaction 必须更新 design、分册、crosswalk、manifest 和测试；
- 修改 locked implementation evidence 必须重新审计映射，不得只刷新 hash；
- `refresh_manifest.py` 只更新 manifest 已声明路径的 digest；新增/删除路径必须人工审阅并显式改
  manifest；
- manifest 不锁自身，其他 required artifact 全部锁定；
- manifest status 必须是 `FROZEN`，review 必须精确绑定已接受的 candidate.5 review；
- 本目录发布后不可原地修改。任何 G/I/object/role/transaction 或锁定证据变化必须创建新架构
  版本、显式 migration/compatibility policy 和新的独立 review。
