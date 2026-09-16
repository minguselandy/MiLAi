# MiLAi Logical Architecture 1.0.0 Candidate Bundle

> Bundle version：`1.0.0-candidate.5`  
> Status：`CANDIDATE — NOT FROZEN`  
> Schema：`0.1.x EXPERIMENTAL`  
> Implementation：`CANDIDATE`  
> Freeze：`NO-GO FOR SCHEMA FREEZE`

本目录把根目录
[`MiLAi_Logical_Architecture_v1_设计文档.md`](../../MiLAi_Logical_Architecture_v1_设计文档.md)
拆分为可校验的架构候选 bundle。它是 MiLAi 自研上位架构的实现产物，不是从外部项目复制的
规范，也不把当前 runtime 自动认定为 frozen。

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
| `FREEZE_REVIEW.md` | AF-09 独立评审清单、finding 和签署模板 |
| `AUTHOR_PREFLIGHT.md` | AF-09 作者预检矩阵；不具备独立签署效力 |
| `AF09_REMEDIATION.md` | candidate.4 复审后 F12 的 candidate.5 整改与完整审查链 |
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

1. 未来经 AF-09 发布的 MiLAi Logical Architecture frozen 版本（当前不存在）；
2. 本 candidate bundle 中已通过 review 的 MUST；
3. `MiLAi_Lean_V1_实施合同.md`；
4. 产品/需求/路线文档；
5. experimental implementation。

bundle 内部冲突时，`INVARIANTS.md` 的 I-01～I-12 优先于物理实现建议；必须修复冲突并提交
ADR，不能让代码事实静默重定义架构。

## Validation

在项目根目录运行：

```bash
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode development
runtime/.venv/bin/python -m unittest discover \
  -s architecture/v1.0-candidate/tests -v
```

AF-09 review/release 不得只信任 bundle 内的可变 manifest；Reviewer 必须从独立提交回执取得 digest：

```bash
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
```

review/release 模式缺少外部 digest 或 digest 不匹配时强制失败。

Candidate.1–4 均由同一独立 reviewer 判定 `REVISE`；四次 review 及各自 archive/receipt 是不可变
历史。Candidate.4 关闭 F01、修复 F11 的 exact missing-request 反例，但新增 F12：四条 TX-05
`created_at` 未进入同一事务证明。本 candidate.5 在 corrected 0024/0025 中补齐精确时间谓词，并
新增 proof-only 0026 认证 already-applied candidate.4；只声明整改证据已就绪。仍须同一 reviewer
针对外部回执标识的精确 bytes 重放并签署。`AF09_REMEDIATION.md` 不是独立接受结论。

`validate_bundle.py` 验证所有 required artifact、G/I/TX/role/gate ID、crosswalk coverage、
repo-relative evidence path 和 candidate banner。`verify_lock.py` 验证 bundle 与输入基线的
SHA-256。任一失败都保持 `NO-GO FOR SCHEMA FREEZE`。

完整 release audit 使用默认 `--scope all`，同时验证 sibling external assets 和 Git revisions。
普通 CI checkout 不包含这些 sibling 目录，因此只运行 `verify_lock.py --scope project`；
该较小 scope 不能作为 AF-09 release lock 的替代证据。

## Change control

- 修改 G/I/object/role/transaction 必须更新 design、分册、crosswalk、manifest 和测试；
- 修改 locked implementation evidence 必须重新审计映射，不得只刷新 hash；
- `refresh_manifest.py` 只更新 manifest 已声明路径的 digest；新增/删除路径必须人工审阅并显式改
  manifest；
- manifest 不锁自身，其他 required artifact 全部锁定；
- `FROZEN` 字样只可出现在状态说明或未来 release 流程中，manifest status 必须是
  `CANDIDATE`；
- Candidate 可以演进；发布 `1.0.0 FROZEN` 前必须通过 AF-00～AF-09 和独立 review。
