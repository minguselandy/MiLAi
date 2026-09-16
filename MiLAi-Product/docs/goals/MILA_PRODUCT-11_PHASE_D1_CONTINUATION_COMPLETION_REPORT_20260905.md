---
document_id: MILA-PRODUCT-11-PHASE-D1-COMPLETION
version: "0.2"
status: PASS_PERSISTED_FRONTIER_CONTINUATION_ENGINEERING_BASELINE
date: 2026-09-05
goal: MILA-PRODUCT-11@1.0
adr: ADR-032
mode: ENGINEERING
research_effect_claim: NOT_MADE
formal_holdout_accessed: false
---

# Product-11 Phase D1 Persisted-frontier Continuation 完成报告

## 1. 结论

Phase D1 已交付默认关闭、可回滚，并已在当前公网候选服务启用的 non-destructive
persisted-frontier continuation：

```text
Call 1
  official acquisition + unchanged first-call context compilation
  -> persist selected exact Evidence ids + remaining exact frontier

Call 2
  same query + previous_context_id
  -> load owned predecessor state
  -> online exact-id revalidation
  -> exclude seen/ineligible Evidence
  -> render only novel persisted-frontier Evidence; adjacent hydration disabled
  -> append idempotent successor
```

Call 2 不执行 global reacquisition、candidate-pool extension 或 query replanning。该结论是
Engineering Mode 功能闭环，不是 P11-C1 coverage/effect claim。

## 2. 实现范围

- 新增 immutable `RetrievalContinuationState` domain model；
- 新增 PostgreSQL repository、基础 migration `0052_retrieval_continuation` 与 hardening migration
  `0053_continuation_hardening`；
- 新增 root/successor append、database operation fingerprint 幂等、RLS 与写入审计；
- `MemoryResolveService` 在 `previous_context_id` 存在时优先恢复 persisted frontier；
- unknown/not-owned/expired continuation 统一 fail closed，绝不退化为 fresh global retrieval；
- continuation page 只对 exact Evidence identity 做 live hydration/revalidation，并要求 projection
  content hash 与当前 Evidence content hash 一致；
- authenticated edge identity 由 MCP 在内部 Runtime 边界绑定为有效 principal digest；同一 Runtime
  reader credential 下的不同 edge principal 不能共享 continuation state；
- successor identity 由 predecessor + operation fingerprint 确定性产生；数据库在锁内验证
  predecessor partition、seen 集合、累计 ineligible 数与 replay payload；
- generation、successor/root-state 数、frontier refs 与 256 KiB state payload 上限由 Runtime profile
  所有，触限使用 typed operational error；
- first call 仍使用原 retrieval 与 `MemoryContextCompiler`，未改变选择或 renderer 参数；
- public MCP input 仍为 `query + optional previous_context_id`；
- capability surface 增加 `retrieval_continuation_v0_1` 开关状态；
- backup inventory 纳入新表；
- feature flag 默认为 `false`，当前候选部署显式设为 `true`。

未实现：residual acquisition、explicit intra-source acquisition、anchor-first renderer、语义
instance grouping、Reader/vLLM retry、Formal effect runner。

## 3. 合同证明

```text
first-call context/evidence behavior   unchanged under flag A/B
same-query continuation origin         PERSISTED_FRONTIER
global reacquisition Call 2            0
candidate-pool extension Call 2        0
query replanning Call 2                0
adjacent hydration Call 2              0
exact seen overlap                     0 in integration E2E
online ineligible evidence returned    0
successor retry duplication            0
cross-principal state read              0
unknown locator fresh fallback          0
projection content-identity mismatch    0 returned
all-ineligible false availability       0
recall-side Canonical mutation          0
public MCP input schema change          0
Reader / vLLM / semantic retry          0
Formal files/cases                      false / 0
```

D1 尚未持久化 official-route exhaustion receipt，因此不发布 `FRONTIER_EXHAUSTED`。保存的候选池
耗尽使用 `PERSISTED_FRONTIER_EXHAUSTED`；因权限、retention、revocation 或 content identity 在线
变化而失效使用 `FRONTIER_ELIGIBILITY_CHANGED`。二者都不表示 semantic completeness、corpus
exhaustion、official route exhaustion 或不存在有用 residual query。

## 4. 验证凭据

### Runtime

```text
focused continuation/capability/settings      PASS
full unit + contract                           793 passed
fresh PostgreSQL full integration              115 passed, 1 dependency skip
Ruff                                            PASS
mypy src                                        PASS (186 source files)
uv build                                        PASS
```

Fresh PostgreSQL integration 包含：

- root/successor append、operation fingerprint replay、RLS；
- 三条真实 Evidence capture + projection；
- first resolve `max_results=1`；
- second resolve 使用 first `context_id`；
- second Evidence identity 与 first 不重叠且来自 persisted frontier；
- projection content hash 漂移会被在线剔除，all-ineligible page 不会误报 available；
- same operation replay 返回同一 successor；payload/state digest 改变返回 conflict；
- 同 scope、同内部 reader credential 下的两个 authenticated edge principal 仍相互隔离；
- root 创建后才投影的 structured adjacent Evidence 不进入 continuation render；真实 DB successor
  仍成功，selected ids 是 predecessor frontier 的子集；
- trace 中三类 reacquisition/replanning counter 全为 0。

### HTTP MCP 与客户端

```text
MCP tests                         155 passed, 1 skipped
MCP Ruff / mypy / uv build        PASS
Python client tests               175 passed
Client Ruff / mypy / uv build     PASS
```

真实 `http://127.0.0.1:7968/mcp` 验收：

```text
Streamable HTTP initialize        PASS
authenticated tools/list          PASS
codex-full tool count             13
Resume Gate visible               true
memory_resolve                    PASS
55-Evidence two-page continuation PASS
authenticated edge-principal isolation PASS
typed continuation errors         PASS
```

真实部署状态：

```text
Alembic head                                  0053_continuation_hardening
milai-product-api-mcp.service                 active
milai-codex-full-public.service               active
Runtime /health/live                          ok
Runtime /health/ready                         ready
MCP /healthz                                  ok
MCP /readyz                                   ready
capability retrieval_continuation_v0_1        true
public 36.140.33.19:7968 initialize            MCP 2025-06-18 / MiLAi 0.1.4
```

## 5. Failure reflection

开发中出现并已修复的真实问题：

1. Alembic revision ID 超过现有 version column 长度：事务回滚后缩短为
   `0052_retrieval_continuation`，未留下半迁移；
2. successor integration 使用跨运行固定 fingerprint：测试改为按 predecessor 构造，保持生产
   operation fingerprint 语义；
3. full integration 在共享 live DB 上受固定 fixture 身份碰撞影响：改用 fresh isolated PostgreSQL，
   同时修复 backup inventory 与 migration-head 断言；
4. `python -m build` 环境缺少 build module：按项目工具链改用 `uv build`；
5. 部署探针最初误用 `/health`/`/ready`，随后依据实际合同分别使用 Runtime
   `/health/live`、`/health/ready` 与 MCP `/healthz`、`/readyz`；未为错误探针改产品代码；
6. capability 未暴露 feature flag：补充受认证 capability 字段与 contract test。
7. 首轮 subagent review 发现 edge principal 未贯穿 Runtime、unknown locator 会 fresh fallback、候选池
   耗尽被误称 official route exhaustion，以及 content hash/replay validation 不足；以 `0053`、内部
   principal binding、uniform fail-closed 和更窄 typed reason 修复，没有扩 public MCP schema；
8. 全量 integration 首次复跑复用了已写入的 disposable DB，出现 fixture conflict 与 v0.2 state
   downgrade 拒绝；重建明确命名的测试库后 `114 passed`。保留 downgrade fail-safe，没有为污染
   测试环境放宽数据保护；最终加入 late-neighbor 回归后 fresh suite 为 `115 passed`；
9. 公网地址首次探针经 shell HTTP proxy 返回 502；绕过代理后标准 Streamable HTTP initialize
   正常。未修改服务协议来适配本地代理误路由。
10. 架构复审发现 continuation anchor 仍进入通用 adjacent hydration，可能引入 frontier 外 Evidence
    并触发数据库 partition 拒绝；新增 continuation-only render mode，明确禁止 Call 2 adjacency，
    unit 与真实 PostgreSQL late-neighbor 回归均通过。没有放宽 successor 校验。

## 6. Review 与后续

Milestone boundary 采用 Functional、Architecture、Generalization/Simplicity 三路独立 subagent
review。首轮共同决议为 `FIX`；修复后 Functional=`PASS`、Architecture=`PASS`、
Generalization/Simplicity=`PASS`，required fixes 为 0。过期 state 的物理批量 GC 留在 Phase E：
TTL 已保证逻辑不可读，当前没有真实 failure 要求把清理器作为 D1 功能门。

下一最小开发项为 Phase D2：explicit intra-source turn acquisition，先以 SHADOW/Engineering
模式证明直接 acquisition 可运行；不得依赖 hydration 充当 discovery，也不得提前声明 P11-C2
量化效果。
