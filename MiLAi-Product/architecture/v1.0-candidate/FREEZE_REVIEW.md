# AF-09 Independent Freeze Review

> Architecture：`1.0.0-candidate.5`  
> Review status：`PENDING_INDEPENDENT_REVIEW`  
> Decision：`PENDING`  
> Schema `0.1.x EXPERIMENTAL` · Implementation `CANDIDATE` · `NO-GO FOR SCHEMA FREEZE`

本文件是评审输入与签署模板，不是批准记录。实现作者、自动 validator 或当前 candidate report
都不能代替独立 reviewer。

Candidate.1–4 的独立结论均为 `REVISE`。Candidate.4 关闭 AF09-F01，并确认 exact
missing-DeletionRequest F11 反例已修复，但新增 P1 AF09-F12：四个 durable TX-05 `created_at` 未被
证明来自同一 transaction。本模板用于 candidate.5 的全量复审；既有 review record 不得修改，
candidate.5 作者整改导航见 `AF09_REMEDIATION.md`。

## 1. Reviewer record

```text
Reviewer:
Reviewer role/independence:
Review started:
Review completed:
Candidate manifest SHA-256:
Validation environment:
Decision: PENDING | ACCEPT | REVISE | REJECT
Decision rationale:
Signature/reference:
```

Reviewer 必须先记录评审前 candidate manifest SHA-256；评审修订后需对新 manifest 重新验证。

## 2. Required inputs

- 根设计文档与本 bundle 全部分册；
- `AUTHOR_PREFLIGHT.md`（仅作作者证据导航，不作独立结论）；
- `crosswalk.json` 与 `architecture_manifest.json`；
- ADR-001～ADR-019；
- candidate.1/2/3/4 review、receipt/archive/remediation/report，candidate.5 DG-00/remediation 与
  GOALS completion audit；
- migrations 0001～0026、runtime source/tests，尤其真实 populated 0014→head、candidate.3
  0024→0025、candidate.4 0025→0026、Issue/Context 与逐腿 provenance regressions；
- threat/privacy review、runbooks、backup/recovery evidence；
- ReMe/Hindsight/Graphiti/Mem0/benchmark version/license/source identity。

## 3. Reproduction commands

在包含 sibling external assets 的 workspace 中：

```bash
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/validate_bundle.py
runtime/.venv/bin/python architecture/v1.0-candidate/scripts/verify_lock.py \
  --scope all --mode review \
  --expected-manifest-sha256 "$TRUSTED_MANIFEST_SHA256"
runtime/.venv/bin/python -m unittest discover -s architecture/v1.0-candidate/tests -v
```

`TRUSTED_MANIFEST_SHA256` 必须来自 bundle 外的 candidate.5 submission receipt。还必须重跑 runtime
format/lint/type/full PostgreSQL tests、fresh forward migration、
backup/revoke/purge/restore drill 和 research isolation gate。`--scope project` 只用于普通 CI，
不能作为 release lock。

## 4. Semantic checklist

Reviewer 对每项选择 PASS/FAIL 并引用 finding/evidence：

| Check | Decision | Evidence/finding |
| --- | --- | --- |
| G1–G9 目标相互一致且没有循环授权 | PENDING | |
| I-01～I-12 每项含可执行正/负向证据 | PENDING | |
| Evidence/Claim/OpenIssue/Context identity 边界明确 | PENDING | |
| Steward single-writer、CAS、append-only 与 rollback 完整 | PENDING | |
| authority/Scope/time/freshness/epistemic 正交匹配 | PENDING | |
| projection/external/model 不能提升 truth/authority | PENDING | |
| revoke、Context invalidation、purge、Blob/backup obligation fail closed | PENDING | |
| tenant/RLS/roles/network/secrets/log privacy 最小权限 | PENDING | |
| dual sequence、watermark、RYW、recovery 语义无歧义 | PENDING | |
| external assets 可完全关闭且 license/identity 可验证 | PENDING | |
| threat model residual risk 与 synthetic-only boundary 可接受 | PENDING | |
| migration/rollback/legacy/real-data change policy 可执行 | PENDING | |
| populated candidate.1 provenance、quarantine、continuous replay 与 validated constraints 可执行 | PENDING | |
| rejected grounding exact support/hash quarantine 且真实 Issue/Context 不泄漏 | PENDING | |
| legacy TX-05 join actual DeletionRequest、逐腿 fail-close、fresh/compat prior-head rollback | PENDING | |
| legacy TX-05 六个 durable timestamps 精确一致，0024/0025/0026 四腿反例均保持 prior head | PENDING | |

## 5. Hard-reject conditions

任一情况必须 `REVISE` 或 `REJECT`：

- unmapped G/I/MUST，或 positive/negative evidence 只是间接推断；
- API/worker/model/adapter 能 direct canonical DML；
- cross-tenant、permission/retention unknown、revoke 或 canonical outage fail open；
- conflict/issue 被 summary、retrieval omission、time 或 model 自动关闭；
- projection、Context、graph 或外部 memory 被当作 authority；
- CAS loser、rollback、outbox 或 history 出现部分写；
- populated migration 猜测/伪造 authority、遗漏创建 history、保留 NULL governance、丢弃原始 row、
  quarantine 可变/越权，或 unprovable state 未整体 fail closed；
- rejected Proposal 的 grounding 仍留在 canonical Issue/Context，或 relation 未 exact-hash 保存；
- legacy TX-05 未 join durable DeletionRequest，任一 proof leg 缺失仍能重建 Proposal/Decision，或失败
  后 Alembic/head/canonical/quarantine/event/outbox 出现本次 residue；
- legacy TX-05 任一 durable timestamp 缺失/冲突仍获得新 head 或重建/认证 authority；
- manifest/source/Git drift 未被拒绝；
- review/release 缺少外部 manifest trust anchor，或 coordinated bundle+manifest substitution 未被拒绝；
- 真实数据门、远程门或 residual risk 被隐瞒；
- candidate banner 在实际 freeze decision 前被移除。

## 6. Findings

| ID | Severity | Artifact/line | Finding | Required change | Resolution evidence |
| --- | --- | --- | --- | --- | --- |
| — | — | — | No findings recorded yet | — | — |

P0/P1 finding 未关闭时禁止 ACCEPT。P2 finding 只有在 reviewer 明确证明不影响 G/I、schema、
权限、删除或恢复语义时才能延期，并必须有 owner/date。

## 7. Decision protocol

### ACCEPT

只有全部 checklist PASS、P0/P1 finding 关闭、完整 lock/tests 重跑，且 reviewer 对 residual
synthetic-only/real-data boundary 明确接受时可签署。ACCEPT 后：

1. 保存独立 review record；
2. 刷新 source lock 与 manifest review fields；
3. 再次执行全 scope verification；
4. 生成 hash-stable release receipt；
5. 另行发布 `1.0.0 FROZEN`，不能直接改写本 candidate 历史。

### REVISE / REJECT

保持 `CANDIDATE / NO-GO`。每个 finding 走 ADR、设计/crosswalk、migration/code/test/report 和
manifest 同步修订；不得删除不易满足的 invariant 来获得通过。

## 8. Current result

```text
Reviewer: SAME INDEPENDENT REVIEWER ASSIGNED FOR CANDIDATE.5 REREVIEW
Decision: PENDING
AF-09: PENDING_INDEPENDENT_REVIEW
Freeze: NO-GO
```
