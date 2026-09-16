# DG-20 Requirement-aligned acquisition operator runbook

Status: `CANDIDATE / EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`。本 runbook 只覆盖本地 opened-dev
诊断与 default-disabled candidate flag；不授权 Production、remote MCP release、真实个人数据、formal
LongMemEval holdout、Reader/prompt/model 变更或新持久 schema。

## 产品路径与唯一 authority

```text
immutable QueryIR + candidate snapshot + Binding + policy
→ RequirementState v0.1
→ executable AcquisitionCapabilitySet v0.1
→ deterministic feasible action（最多一个 extra pass）
→ official EvidenceAcquisitionExecutor
→ EvidenceSpan / Interpretation / RequirementBinding
→ fresh RequirementState epoch + 1
→ SufficiencyDecision
→ Context 或 typed abstention
```

RequirementState 是 query-local derived state；它不写 canonical Memory，不决定 final answer，也不拥有
Sufficiency authority。action 必须绑定 RequirementState、CapabilitySet 和 policy digest；epoch/digest stale
一律 fail closed。event time 缺失不能用 source-observed time 冒充，COUNT/set/completeness gap 不能降级为
普通 lexical miss。

产品设置 `MILAI_RETRIEVAL_DETERMINISTIC_RECOVERY_ENABLED` 默认 `false`。只有 opened-dev candidate
operation 可显式打开；未设置、Provider 不可用或 cue 无效时均保持 deterministic-only 行为。DG-20 没有
新增 MCP tool、public schema、DB table 或 Migration。

## Residual lane

当前 residual disposition 是 `DISABLED_NOT_NEEDED`：S2/S5 deterministic lane 已达到冻结门槛，S3
entry gate 未进入，Provider calls、automatic retry 与 cue pass 都是零。

若未来新 Goal 授权 S3，Provider 只能返回 `ResidualCue v0.2` 的 aliases、phrases、morphological variants；
Runtime 已经固定 channel、scope、time bounds、source policy、candidate cap、expansion 与 completion
policy。精确 cue 只能进入加密、受限、带 retention 的 artifact；公开回执只保留 digest、计数和 typed
reason。详见 `docs/dg20-residual-cue-artifact-contract.md`。

## Typed terminal handling

| 条件 | 必须结果 |
| --- | --- |
| state epoch/digest 不匹配 | reject action；不调 Provider/executor |
| capability unavailable | typed unavailable 或 `NO_FEASIBLE_ACTION` |
| event projection unavailable | typed abstention；不使用 source time fallback |
| completeness proof 缺失 | bounded proof acquisition 或 unresolved；不假 COMPLETE |
| wrong scope/permission/retention/revoke | Evidence Gate reject；不得进入 Binding |
| deterministic COMPLETE | auxiliary calls = 0 |
| extra pass 后仍不足 | 完整重算后 typed abstention |
| Provider unavailable/invalid | deterministic-only；zero retry |

## 失败隔离与恢复

固定一个 case、一个 requirement、一个 state epoch，并从下列枚举记录唯一 first loss：

```text
QUERY_IR → REQUIREMENT_STATE → CAPABILITY → CUE → CHANNEL → RAW_RANK
→ FUSION → CUTOFF → EXPANSION → APPLICABILITY_GATE → INTERPRETATION
→ BINDING → COMPLETENESS_PROOF → SUFFICIENCY → CONTEXT_PACKING → READER → SCORER
```

只修改该 owner，先跑最窄 unit，再跑 DG-20 matched slice；风险相称时才扩大到全量 gate。不得通过增加
Top-k、改变 Reader、重试/换 seed、隐藏 fallback、false COMPLETE 或覆盖失败 receipt 来通过门禁。
每次 fresh execution 使用新 run ID；旧 sealed artifact 和 failure ledger 保持不可变。

## 验证命令

权威门禁由收据 runner 固定命令与日志；无数据库运行：

```bash
PYTHONPATH=runtime/src:. runtime/.venv/bin/python \
  scripts/run_dg20_quality_gates.py \
  --run-id <fresh-quality-run-id>
```

DG-20 evaluator 门禁：

```bash
PYTHONPATH=runtime/src:. runtime/.venv/bin/pytest -q tests/test_dg20*.py
```

真实 PostgreSQL integration/security 必须使用专用合成测试库，配置 owner/API/Steward/Worker/Audit
五个 test DSN 和 migration DSN 后运行：

```bash
PYTHONPATH=runtime/src:. runtime/.venv/bin/python \
  scripts/run_dg20_quality_gates.py \
  --run-id <fresh-quality-run-id> \
  --include-integration
```

禁止把 Production 或含个人数据的数据库 URL 传入这些测试。

## 当前 authoritative artifacts

```text
S0 var/dg20/s0/dg20-s0-fresh-state-20260828-003/
S1 var/dg20/s1/dg20-s1-official-channel-oracle-projection-20260828-005/
S2 var/dg20/s2/dg20-s2-deterministic-policy-20260828-002/
S3 var/dg20/s3/dg20-s3-conditional-disposition-20260828-002/
S4 var/dg20/s4/dg20-s4-product-faithful-projection-20260828-004/
S5 var/dg20/s5/dg20-s5-matched-q6-rescore-20260828-005/
Quality var/dg20/quality/dg20-quality-postgres-20260828-008/
S6 var/dg20/s6/dg20-s6-terminal-20260828-002/
```

S1/S4 projection 目录的 seal 和 score 与真实源 execution byte-identical；projection 没有重放产品、
重跑 scorer 或改写 seal，只补齐标准 plan/loss-ledger/receipt 绑定。S6 terminal receipt 是最终 source、
artifact、quality 与 frozen-boundary 验证入口。
