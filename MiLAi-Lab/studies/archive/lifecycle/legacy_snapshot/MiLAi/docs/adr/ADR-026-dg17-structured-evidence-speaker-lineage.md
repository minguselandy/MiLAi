# ADR-026：DG-17 结构化 Evidence Speaker Lineage

状态：`ACCEPTED FOR DG-17 A3 CANDIDATE`  
日期：`2026-08-27`  
适用范围：Runtime `0.1.x CANDIDATE` / Schema `0.1.x EXPERIMENTAL`

## 背景

旧的 A3 working-tree 草稿从 query 中的少量中英文词和 Evidence 正文的 `user:` / `assistant:`
前缀猜测 speaker，并用未标定的 `+0.05` 改变排名。该实现混淆 event actor 与 Evidence source，
无法处理多 slot、引用、否定、指代或未知语言，已被 DG-17 v0.3.1 明确标记为
`REJECTED_DRAFT`。

## 决定

Evidence capture 增加可选、类型化 `speaker`。该值作为 capture envelope metadata 写入
`evidence_record.source_speaker`，并以 `speaker_source=STRUCTURED_TURN_METADATA` 记录来源；
未提供字段的历史和新 Evidence 固定为 `source_speaker=NULL / speaker_source=UNKNOWN`。
禁止根据正文回填。

`EvidenceRequirementV02` 分离：

```text
semantic_roles = actor / experiencer / beneficiary
evidence_source = preferred_speakers / allowed_speakers / provenance
```

`AcquisitionPlanCompiler` 只逐 requirement 复制这些类型化约束。global safety-net probe 保持中性。
`allowed_speakers` 只有 `EXPLICIT_QUERY` provenance 才合法；preference 不是 permission filter。
本 change set 不启用 speaker score boost。后续 fielded retrieval 只有在独立 matched calibration
绑定 policy identity 后才能改变默认排名。

## Schema、投影与兼容

Migration `0043_dg17_speaker`：

- 为 `evidence_record` 与 `evidence_search_document` 增加 speaker/lineage 字段和 pair constraint；
- 通过 TX-01 wrapper + insert trigger 在原子 Evidence ingest 中写入 metadata；
- 将 speaker 纳入 Evidence immutable identity guard；
- projection trigger 从 canonical Evidence metadata 复制字段；
- 历史行只回填 `UNKNOWN`，不解析正文；
- turn-first search result 输出 `speaker` 与 `speaker_source`；
- purge、RLS、scope、permission、retention、revoke 和 watermark 行为不变。

MCP `milai_evidence_capture` 只增加 backward-compatible optional argument；旧调用不变并产生
`UNKNOWN`。结构化 response/receipt 可携带 speaker lineage，Reader prose 不因此暴露 opaque ID。

## 回滚

`downgrade()` 先恢复不引用新字段的 0042 turn-first search function，再删除 wrapper、triggers、
constraints 和 columns。回滚会丢失新 speaker metadata，因此只允许在停止新 Runtime、确认无依赖
后执行；Evidence 正文、治理状态和 canonical Claim 不受影响。

## 验证要求

- unit/property：per-slot actor/source 分离、UNKNOWN fallback、正文前缀不推断、hard source constraint
  只接受结构化 metadata；
- real PostgreSQL：API/MCP capture → projection → search → CandidateEnvelope round-trip；
- historical capture 无 speaker → `UNKNOWN`；
- immutable speaker update 被拒绝；
- revoke/scope/permission negative controls 不回归；
- migration upgrade/downgrade/upgrade 与完整 Runtime regression；
- Ruff 和 touched-package strict mypy。

本 ADR 不升级 Runtime/Schema 状态，继续保持
`CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。
