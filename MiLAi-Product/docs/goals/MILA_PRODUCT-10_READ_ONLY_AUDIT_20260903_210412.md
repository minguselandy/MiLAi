---
document_id: MILA-PRODUCT-10-READ-ONLY-AUDIT
version: "1.0"
status: READ_ONLY_PREPARATION_COMPLETE
goal: MILA-PRODUCT-10@1.0
prepared_at: "2026-09-03T21:04:12+08:00"
execution_authorized: false
formal_holdout_authorized: false
product09_tree: 557ad09059b50bb52b9b2b77e3f1f3c88a7d1a317f460cc95b9d2b5ea479171f
---

# Product-10 只读准备与实现边界审计

## 结论

Product-10 已完成当前授权范围内的设计核对、Product-09 pin 校验、静态路径审计和窄回归验证；
X0--X4 均未启动，也未修改 Product 行为。

当前实现不是 Product-10 所需能力：

1. 常规 Product-09 A0 路径保留 `evidence_id`，但 candidate re-entry 的已见排除同时按
   `source_ref` 硬过滤，尚未满足“不同 Evidence identity 不得硬合并”的完整约束；
2. 默认关闭的 budget-stable Context 路径会按规范化文本作硬语义省略，必须纳入 X1，不能直接
   作为 B1；
3. `previous_context_id` 当前只提供完整 receipt reuse/fallback，不保存或继续 unseen Evidence
   frontier；Evidence-only receipt 又明确不持久化；
4. MCP v1 schema 已能表达 `continuation: null | {available, reason}`，无需为 B2 改公共 schema；
5. 现有持久 ContextCapsule procedure 只接收 Canonical State/Claim sections，不能在当前受治理
   边界内保存 Evidence frontier。按 Goal，获授权前继续返回 `continuation: null`；不得伪造能力。

## 授权与未发生事项

本次只执行 Goal 第 14 节允许的设计和只读审查准备。未执行：

- opened-development case、X0 label sealing、X1 effect trace 或 X2/X3 treatment；
- Product 代码修改、数据库 migration、公共 MCP schema 修改；
- real Codex Product-10 HTTP case 或 formal 500-case holdout。

因此本报告不是 H1/H2 结果，也不把 Product-10 标记为完成。

## 冻结起点核验

`MiLAi-Lab/data/locks/product09-product.lock.json` 对当前 Product 行为树校验通过：

```text
lock_digest          d3c2276226a499dd94301aeb8b1f28bfec4ea5baa7f876382886fe9e7004ae78
observed_tree_sha256 557ad09059b50bb52b9b2b77e3f1f3c88a7d1a317f460cc95b9d2b5ea479171f
valid                true
```

Product-09 LME runner 和评分器只读校验摘要：

```text
run_product09_codex_lme.py sha256  bc7343a9c13511bc5312aead2d125d97fa534f6394d55df8e3a924a0d6c693ed
answers.py sha256                    19eefe2e40d2df37294826d8419e113b96bf51ceee671a375ebf23e50851a512
recorded Codex CLI                      codex-cli 0.151.0
recorded exact model identity           absent
scorer                                  deterministic normalized EM/F1
score claim                              NOT_OFFICIAL_LONGMEMEVAL_SCORE
```

Product-09 的 `3/4` 只能继承为 opened-development 的窄诊断起点；因结果未记录精确 Codex model
identity，X0 必须在任何 Product-10 real Codex 调用前补齐 model/provider identity，不能回填历史。

## A0 identity 与首损路径审计

### 保留的 Evidence identity

- `runtime/src/milai/application/retrieval.py:2485` 的最终 Evidence 去重以 `evidence_id` 为键；
- `runtime/src/milai/application/evidence_acquisition.py:1866` 的 acquisition 去重也以
  `evidence_id` 为键；
- `runtime/src/milai/application/memory_context.py:2307` 的 Evidence view 保留 Evidence ID、
  session 和 turn reference；
- MCP renderer `integrations/mcp/src/milai_mcp/evidence_context.py:85` 继续传递这些 provenance
  标识，不生成 instance key。

### 必须由 X1 判定的风险

- `runtime/src/milai/application/evidence_acquisition.py:1495` 的 `_exclude_seen_candidates`
  同时对 exact `evidence_id` 和相同 `source_ref` 做硬排除。这可能错误排除同来源的另一个
  EvidenceRecord，B1 若被 X1 触发，硬排除必须收窄到 exact stable Evidence identity；
- `runtime/src/milai/application/memory_context.py:582`、`:598` 和 `:637` 的 budget-stable
  路径分别维护 normalized semantics、以 `SEMANTIC_DUPLICATE_ZERO_GAIN` 省略非 required
  window，并以 `NO_ADMISSIBLE_SEMANTIC_GAIN` 省略无 admissible gain 的 window；
- Product-09 A0 的相关 settings 默认关闭，所以不能据此宣称 Product-09 的 COUNT 首损就是
  semantic collapse；但任何 B1/B2 若启用这条路径，都必须证明不同 `evidence_id` 不被语义
  相似硬折叠。

X1 必须对每个未覆盖 group 给出唯一首损分类：`NOT_DISCOVERED`、
`DISCOVERED_NOT_ADMITTED`、`ADMITTED_NOT_RENDERED`、
`INSTANCE_DESTROYING_COLLAPSE` 或 `VISIBLE_BUT_HOST_MISSED`。静态审计不能替代该判定。

## continuation 与持久边界审计

- `runtime/src/milai/application/memory_resolve.py:205` 在收到 `previous_context_id` 时先尝试
  receipt reuse；coverage miss 后在 `:246` 发起一次新的 retrieval。它不继承旧 receipt 的
  unseen frontier，也没有把旧 snapshot/as-of 固定为新的 retrieval 输入；
- `runtime/src/milai/application/context_receipt.py:42` 验证 scope、coverage、freshness 后复用
  完整旧 body，这是 reuse，不是 continuation；
- `runtime/src/milai/domain/memory_context.py:152` 将 Evidence Context receipt 定义为
  `persisted: false`，`runtime/src/milai/application/memory_context.py:3185` 为其生成临时 UUID；
  该 ID 不能作为受治理的持久 continuation state；
- migration `runtime/migrations/versions/0031_task_free_context_receipt.py:69` 的现有 procedure
  只允许 Canonical State/Claim versions 和固定 sections。把 Evidence frontier 塞入现有边界
  会绕过当前 procedure contract；若未来确需改变该函数，应另建 migration 和 ADR，不能改写
  0031；
- `contracts/agent/v1/memory-evidence-context-v1.schema.json:29` 已有 snapshot，`:45` 已有
  nullable continuation；MCP `evidence_context.py:253` 只转发 Runtime 可证明的事实。当前保持
  null 是正确的 fail-closed 行为。

## X0 的 outcome-blind 准备决定

获得 effect 授权后，优先复用既存的 24-case structural preflight membership：

```text
source       MiLAi-Lab/data/labels/product03-context24-selection.v0.1.json
sha256       0a3703d4bc1ad66f8fd806156fbec5c575e5462976e7b2cd481bd529eb49e03a
case count   24
selection    OUTCOME_BLIND_STRUCTURAL_PREFLIGHT
formal       false
```

这份 membership 在 Product-09 COUNT 结果之前已存在，能降低按已知失败选 case 的风险。Product-09
diagnostic case `0a995998` 不在主 24 中，不得在看到结果后替换主样本；它只能保留为样本外
mechanism probe。X0 仍需在 treatment 前由 Lab 封存：

```yaml
InstanceEquivalenceGroup:
  group_id:
  acceptable_evidence_ids: []
  acceptable_turn_refs: []
  required_for_answer: true
```

同时封存 opportunity、Product pin、精确 Codex identity、profile/token budget 与评分器 hash。
若封存后真实 continuation opportunity 少于 6，H2 必须记为 `INSUFFICIENT_OPPORTUNITY`，不得
换样本凑数。

## X1 trace 就绪性

现有 `context-testkit-v0.1` 是 Product-08 C/X/Y treatment testkit，会强制打开
budget-stable/query-preserving 行为，不是 Product-09 A0。Runtime 内部已有默认关闭的
`ProductRetrievalAuditObserver`，但它未通过正式 public testkit 接口接入 A0 app。

因此 effect 授权后，X1 的第一个实施动作应是发布一个只读、默认关闭、无 case label 感知的
A0 trace boundary，至少逐 occurrence 记录：

```yaml
request_id:
stage: raw_retrieval | evidence_dedup | locality_order | context_admission | mcp_render
evidence_id:
source_ref:
session_id:
source_turn_ref:
decision: retained | omitted
reason_code:
rank_before:
rank_after:
```

Lab 只在 trace 完成后映射 InstanceEquivalenceGroup；Product 不能读取 group label。该 publication
是产品测试接口变更，当前未实施。

## 条件实施规范

### B1（仅在 X1 证明需要时）

1. exact `evidence_id` 是唯一硬去重/seen exclusion 键；
2. `source_ref`、session、time 和 semantic similarity 只作软排序特征；
3. 同一 session 的 unseen turn 必须仍可入选；
4. 原 candidate pool 保留为 fallback；
5. 任何 identity 语义调整先写 ADR、直接测试和回滚说明；A0 已满足时记录 `NOT_NEEDED`。

### B2（仅在 X1/X0 证明真实 opportunity 后）

1. 保存 Goal 定义的最小 frontier state，并对 principal/tenant/project/scope digest 做 fail-closed
   校验；
2. 固定第一次读取的 source snapshot/as-of；
3. 只硬排除 `shown_evidence_ids`，同 session unseen turn 仅软降权；
4. MCP 只转发现有 nullable continuation 字段；
5. 若现有 ContextCapsule 仍不能合法表示 state，则 B2 保持 unavailable/null，先走 ADR 和新
   migration 的单独授权。

## 已运行的只读/窄回归验证

```text
uv run milai-lab-verify-product --lock data/locks/product09-product.lock.json \
  --product-root ../MiLAi-Product --json
PASS: valid=true, tree=557ad090...9171f

runtime: uv run pytest -q tests/test_retrieval_audit.py \
  tests/unit/test_memory_resolve.py tests/unit/test_dg17_memory_context.py
PASS: 58 passed in 1.00s

integrations/mcp: uv run pytest -q tests/test_agent_memory_profile.py
PASS: 5 passed in 1.11s

MiLAi-Lab: uv run pytest -q tests/unit/test_product09_codex_lifecycle.py \
  tests/unit/test_product09_codex_lme.py tests/contract/test_product_manifest.py
PASS: 5 passed in 0.05s
```

未运行全量 suite；因为本次没有行为代码变更，窄回归用于确认审计所依赖的边界仍成立。

## 下一授权门

Product 与 Lab 的 tracker 继续停在 `X0_NOT_STARTED`。只有 Goal、Lab plan/tracker 明确授予 effect
权限后，才按 `X0 -> X1 -> conditional X2 -> X3 -> X4` 顺序继续；formal holdout 仍需独立授权。
