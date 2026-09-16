---
document_id: MILA-PRODUCT-11-PHASE-D2-COMPLETION
version: "0.1"
status: PASS_EXPLICIT_INTRA_SOURCE_ACQUISITION_SHADOW_ENGINEERING_BASELINE
date: 2026-09-05
goal: MILA-PRODUCT-11@1.1
adr: ADR-032
mode: ENGINEERING
research_effect_claim: NOT_MADE
formal_holdout_accessed: false
---

# Product-11 Phase D2 Explicit Intra-source Acquisition SHADOW 完成报告

## 1. 结论

Phase D2 已交付 lexical-only、默认 `OFF`、候选部署启用 `SHADOW` 的 explicit intra-source
turn acquisition：

```text
official coarse Evidence candidates
  -> exact coarse Evidence IDs
  -> PostgreSQL live identity/scope/snapshot revalidation
  -> derive exact (source_type, structured session_id) pool
  -> bounded lexical turn search inside that pool
  -> content-free DIRECT_ANCHOR diagnostic summaries
```

SHADOW candidates 不进入 `MemoryContext`、不进入 persisted frontier、不触发 global source
acquisition，也不修改 Canonical。该结论只证明 Engineering acquisition telemetry 可运行且边界
正确，不声明 P11-C2 coverage gain 或用户可见 recall improvement。

## 2. 最小实现

- 新增 `IntraSourceAcquisitionService`，只处理具有
  `STRUCTURED_TURN_METADATA | AUTHORITATIVE_BACKFILL` 的 coarse Evidence；
- Runtime profile 只接受 `OFF | SHADOW`，拒绝尚未授权的 `FRONTIER`；
- 新增 migration `0054_intra_source_shadow` 与 least-privilege SECURITY DEFINER read function；
- repository 传递 exact coarse Evidence UUID，不信任 Host 提供的 source/session partition；
- 数据库对 coarse anchors 与 fine candidates 分别重验 tenant、requested project scope、
  `observed_at <= snapshot_as_of`、structured provenance、permission、revocation、retention 与
  Evidence/projection content hash；
- 数据库从合格 anchor 推导 `(source_type, source_session_id)`，避免同名 session 跨 source type
  串池；
- 固定服务端 envelope：最多 50 个 source/session、每个 8 个 lexical hits、总计 120 candidates；
- trace 明确区分 requested coarse pool 与实际产生 lexical match 的 eligible source keys；
- candidate summary 包含 Evidence/source/turn/content identity 与 provenance rank，但不含正文；
- SHADOW SQL/DB 异常 fail-open 为 `UNAVAILABLE`，official MemoryContext 保持原结果；
- public MCP input、13-tool catalog、Host prompt、Reader、vLLM、Canonical schema 均未改变。

## 3. 验证结果

```text
focused D2/settings/capability tests       40 passed
full Runtime non-integration              805 passed
fresh PostgreSQL integration              137 passed, 2 existing dependency skips
MCP                                      155 passed, 1 skipped
Python client                            175 passed
Ruff                                      PASS
mypy                                      PASS (Runtime 189 source files)
Runtime/MCP/client package build           PASS
```

Fresh PostgreSQL 测试从空库执行 `0001 -> 0054`，并证明：

- exact acquired source/session 内的不同 turn 可被 lexical direct acquisition 返回；
- pool 外 session 不返回；
- 相同 session ID、不同 `source_type` 不返回；
- 相同 source/session、不同 project scope 不返回；
- candidate identity 与 source snapshot 保持；
- continuation D1 的 persisted-frontier-only、principal isolation、content identity 和
  no-adjacent-render 合同继续通过。

候选部署：

```text
Alembic head                                  0054_intra_source_shadow
MILAI_INTRA_SOURCE_ACQUISITION_V0_1_MODE       SHADOW
milai-product-api-mcp.service                  active
milai-product-worker-mcp.service               active
milai-codex-full-public.service                active
Runtime live/ready                             PASS
MCP live/ready                                 PASS
public 36.140.33.19:7968 initialize             MCP 2025-06-18 PASS
Runtime capability                             SHADOW
0054 function privilege                        API=true; worker/steward/PUBLIC=false
empty-pool deployment probe                    no Context/frontier/global-acquisition change
```

## 4. Failure reflection

开发中遇到并修复的真实问题：

1. 中途重构时 application/repository 已切换 exact Evidence UUID，而 migration 仍是裸
   `session_id text[]`，focused test 也残留占位断言。停止继续调参，统一为数据库内 exact-ID
   attestation，修复 migration/test 后再验收；
2. 仅按 `session_id` 建池会在不同 `source_type` 使用同名 session 时串池。数据库 partition 改为
   `(source_type, source_session_id)`，并加入真实 PostgreSQL 排除测试；
3. fine fixture 的 `observed_at` 晚于运行 snapshot，导致目标 turn 合法地被过滤。修正 fixture时间，
   保留 `observed_at <= as_of` 安全合同；
4. repository 的非连接类 PostgreSQL error 可能穿透 SHADOW。现在统一包装为 `RuntimeError`，并用
   unit test 证明 official MemoryContext fail-open 不变；
5. 第一次 fresh test 错把不存在的 `MILAI_TEST_*` 环境变量替换成 `/milai_d2_verify`。改为从现有
   least-privilege role DSN 派生隔离数据库，不放宽 DSN validation；
6. 第一次 full integration 复用了 targeted test 已写入的数据库，0053 downgrade safety test 正确
   拒绝包含 v0.2 continuation state 的降级。重建空白隔离库后完整套件 `137 passed`；没有为测试
   污染削弱 downgrade fail-safe；
7. 部署后的公网无凭证 initialize 返回 401，这是现有 authenticated MCP 合同。使用服务器签发
   credential 后标准 Streamable HTTP initialize 正常；没有降低认证要求。

## 5. Boundary review 与后续

Functional、Architecture、Generalization/Simplicity 三路独立 subagent 对最新树最终均为 `PASS`，
required fixes 为 0。审查确认 D2 没有引入 benchmark/gold/case 特化、隐藏模型、Dense、Reader、
renderer/frontier mutation 或额外 MCP surface。

当前适用范围应诚实表述为“具有结构化 turn metadata 的 source/session”，不是任意 document/span。
Dense、FRONTIER integration、anchor-first renderer 与量化 P11-C2 effect 继续由 Research X0 gate
约束；在出现真实 latency/payload/failure 前，不预建新 trace store、epoch 或更复杂 policy。
