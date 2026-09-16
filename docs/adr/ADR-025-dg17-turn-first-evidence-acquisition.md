# ADR-025：DG-17 Raw Evidence Turn-first Seed Acquisition

状态：`ACCEPTED FOR DG-17 A1 CANDIDATE`  
日期：`2026-08-27`  
适用范围：Runtime `0.1.x CANDIDATE` / Schema `0.1.x EXPERIMENTAL`

## 背景

`search_evidence_projection` 的 0041 实现先以单个最高 FTS turn 为每个 `subject_id`
（LME 中为 session）评分，再回填该 session 的其他 turns。高分噪声 session 因而可以用不匹配
的 turn 占满 `p_limit`。DG-17 A0 的 after-the-fact ledger 在当前 23 个 required Evidence 中，
将 Q6 路径的 `16/23` 首次丢失定位到 session cutoff。

## 决定

0042 在所有既有 tenant、actor、scope、as-of、permission、retention 和 revoke 过滤之后，
只对实际命中 `search_vector` 的 Evidence turn 计算 `ts_rank_cd`。候选按以下稳定顺序选择：

```text
turn_score DESC
→ observed_at DESC
→ source_ref
→ evidence_id
```

`subject_id` 不参与 primary relevance 或 cutoff。它继续保留在结果中，供后续明确授权的
session/episode structural expansion 和 provenance 使用。

每个结果额外保留以下内部 acquisition provenance：

```text
turn_rank
candidate_unit=TURN
acquisition_channel=FTS_RAW
matched_fields=[lexical_text]
relevance_score=original turn score
```

本变更不加入 role boost、lexical enrichment、dense、reranker、per-slot quota/fusion 或 Context
packing 改动；这些分别属于 A2–A7。

## 不变量

- public MCP tool/response contract 不变；
- Raw Evidence 仍为 `EVIDENCE_ONLY / canonical=false`；
- tenant、principal session context、scope、retention、permission、revoke 和 `as_of` 过滤不变；
- function signature、projection version 和持久化表不变；
- 不读取 eval label、case ID 或 gold answer；
- session/episode 只可在后续 Runtime Context/expansion 边界使用，不能替代原始 turn score。

## Migration、兼容与回滚

Migration：`0042_dg17_turn_first`，只使用 `CREATE OR REPLACE FUNCTION` 替换内部 SQL，
无需 backfill 或 projection rebuild。已有 `evidence_search_document` 与 watermark 保持有效。

`downgrade()` 明确恢复 0041 的稳定 session-first SQL；回滚会恢复旧行为但不丢数据。若 A1
matched receipt 发现 correctness 或 governance 回归，先停止 successor rollout，再执行该精确
函数回滚。不得通过回滚 permission/revoke 条件来恢复召回。

## 验证

- unit：turn 排序不受 session grouping 影响；migration upgrade/rollback SQL 合同；
- real PostgreSQL：一个高分 session 含两条不匹配 backfill turn，另一个 session 含第二条匹配
  turn；`p_limit=3` 只能返回两个实际匹配 turn，并保留 `turn_rank` provenance；
- regression：projection ingest/query、permission/revoke、Runtime/MCP resolve、migration unique-head、
  Ruff 和 strict mypy；
- A1 receipt 必须绑定 A0、Q6、Q8 identities，并报告 session-first vs turn-first mediator。

本 ADR 不升级 Runtime/Schema 状态；继续保持 `CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。
