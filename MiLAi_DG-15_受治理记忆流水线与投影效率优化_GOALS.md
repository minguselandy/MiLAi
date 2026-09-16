# MiLAi DG-15：受治理记忆流水线与投影效率优化 Goal

> Goal ID：`DG-15`
> 文档版本：`0.1.0 READY FOR IMPLEMENTATION`
> 生效日期：`2026-08-26`（Asia/Shanghai）
> 当前状态：`SCOPED OPTIMIZATION / DEVELOPMENT DATA ONLY`
> 前置产品基线：`DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE`
> 性能基线：`DG-14 LongMemEval opened-development characterization`
> Runtime / Schema：`0.1.x CANDIDATE / 0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`

---

# 0. Goal 决定

DG-15 优化 MiLA 当前 MCP 写入、治理、投影、就绪确认和清理流水线，不替换 Memory Engine，也不改变 MiLA 的产品定位。

目标是把当前：

```text
逐条串行 Evidence capture
→ 逐 chunk 串行 create / get / approve
→ finalize 集中启动 worker --once
→ 等待全部投影
→ query
→ 逐 Evidence revoke
→ cleanup 集中启动 worker --once
```

改为：

```text
有界并发 Evidence capture
        │
        ├── Raw Evidence / Episode projection（非权威候选）
        │
        └── Derived canonical proposal（仅在确有状态主张时）
                    │
          跨独立对象并行治理链
          对单 proposal 保持有序
                    │
           常驻 worker 增量投影
                    │
          watermark readiness barrier
                    │
          resolve → Context → vLLM
                    │
        namespace cleanup job + receipt
```

核心优化顺序冻结为：

```text
消除不适用 projection 工作
>
常驻增量 worker 与精确 watermark barrier
>
受控并发 MCP 调用
>
数据库微批处理
>
连接与身份上下文复用
>
异步 namespace cleanup
>
经 profile 证明后再优化 ledger
```

本 Goal 的产品判据是：

> 在不削弱 Evidence、Proposal、Steward、Canonical Gate、Scope、权限、撤销与审计语义的前提下，显著缩短“历史写入到可查询”和“查询结束到清理完成”的时间，并保持 MCP 调用路径可操作、可追踪、可恢复。

---

# 1. Goal 关系与所有权

## 1.1 与 DG-13 的关系

DG-13 已获得 scoped release：

```text
DG13 = LOCAL_MCP_GOVERNED_MEMORY_SERVICE_USABLE
```

DG-15 是 DG-13 之上的性能 successor，不重新定义以下已关闭边界：

- MCP 是 MiLA 第一产品接口；
- OpenWorker 是 MCP client，不是 MiLA Canonical Core；
- Evidence 不等于 Claim；
- Proposal 不等于 canonical commit；
- reviewer 与 submitter 保持角色分离；
- projection、检索候选与 Context 不获得 canonical authority；
- task hint 缺失不能使 query 无法进入 Memory；
- 本地 MCP 可用性不等于生产、远程 MCP 或真实个人数据可用。

DG-15 不改写 DG-13 release receipt、测试收据或历史报告。

## 1.2 与 DG-14 的关系

DG-14 提供本 Goal 的真实 opened-development workload、adapter 和性能基线。历史 DG-14 run artifact 保持只读；DG-15 使用新的 run ID、配置身份和报告目录。

DG-14 已证明：

- 五个 opened-dev case 可以完成真实 MCP write → persist → retrieve → Context → vLLM；
- 2048-token 质量达到 `EM/F1=0.60`、Evidence Coverage `0.80`；
- 在线 query 已不是主要生命周期瓶颈；
- finalize 与 cleanup 是首要效率问题。

DG-15 可以修改 successor adapter、worker、projection repository、Migration 和相关测试，但不得回写 DG-14 历史结果。

## 1.3 与 DG-12 和正式实验的关系

DG-15：

- 不修改 DG-12 frozen candidate；
- 不消费正式 holdout；
- 不打开 paper labels；
- 不把 opened-development 五 case 结果外推为生产或论文结论；
- 不以性能优化为理由重跑一次性正式授权。

正式 benchmark、论文 claim 和 generalization confirmation 属于后续独立 lane。

---

# 2. 当前实现与测量基线

## 2.1 Observed baseline

来源：

```text
var/dg14/runs/dg14-matched-001-20260826/stage-ledger.jsonl
```

五个 opened-development case 当前均值：

| Stage | Current mean | 说明 |
| --- | ---: | --- |
| warm reset | `4.310 s` | 每 case 打开四套 scope-bound MCP profile |
| ingest | `5.801 s` | 每 case 约 486–514 次独立 Evidence capture |
| finalize | `109.534 s` | 约 424–441 个 canonical chunk + 集中 projection |
| cleanup | `85.017 s` | 逐 Evidence revoke + 集中 purge projection |
| full lifecycle | `204.662 s` | 不含把该值外推为通用生产 SLA |

查询基线：

| Memory budget | MCP query p50 | MCP query p95 |
| --- | ---: | ---: |
| 2048 | `77.73 ms` | `92.29 ms` |
| 512 | — | `118.23 ms` |

结果解释：

- 2048-token query p95 已低于 100 ms；
- 512-token query p95 略高于 100 ms，但与 finalize/cleanup 相比不是 P0；
- finalize 中 proposal/create/get/review/readiness MCP latency 均值合计约 `10.3 s`，剩余约 `99.2 s` 主要位于 worker/projection 等非 MCP 区段；
- cleanup 中 revoke MCP latency均值合计约 `4.2 s`，剩余约 `80.8 s` 主要位于 purge worker/projection；
- 因此只增加 MCP 线程不能解决主要瓶颈。

## 2.2 Current code path

| Current behavior | Evidence |
| --- | --- |
| 每 turn 一次 Evidence capture | `evals/dg14/milai_mcp_adapter.py::DG14MiLAIMCPAdapter.ingest()` |
| finalize 每 1,600-byte session chunk 建立 canonical proposal | `evals/dg14/milai_mcp_adapter.py::_create_and_review_session_claim()` |
| 单 chunk 调用 create → get → review | 同上 |
| finalize/cleanup 通过 readiness hook 集中投影 | `evals/dg14/milai_mcp_adapter.py::_run_readiness_hook()` |
| cleanup 逐 Evidence revoke | `evals/dg14/milai_mcp_adapter.py::cleanup()` |
| benchmark 多次启动 `milai-worker --once` | `evals/dg14/benchmark.py::_worker_once()` |
| Runtime 已存在常驻 worker 循环 | `runtime/src/milai/workers/main.py::ProjectionWorker.run()` |
| repository 当前按单事件 lease/apply/complete | `runtime/src/milai/persistence/projection_repository.py` |
| stage ledger 已支持单次批量 append + fsync | `evals/dg14/ledger.py::HashChainedLedger.append_many()` |

## 2.3 Current semantic amplification

当前 DG-14 为了让原始 LongMemEval history 可检索，将每个 1,600-byte session chunk 包装成 `SESSION_MEMORY_CHUNK` canonical Claim，并逐项治理。

Observed：

```text
Raw conversation Evidence
→ hundreds of chunk proposals
→ hundreds of canonical ClaimVersions
→ FTS/vector projection
```

这保证了当前实现能经过 Canonical Gate，但也把“可检索历史片段”与“系统接受的 canonical state”混在同一重路径中。

DG-15 必须建立更清晰的双通道：

```text
Raw Evidence / Episode lane
  → searchable projection
  → candidate only
  → permission / retention / revoke / provenance gate

Derived State lane
  → OperationProposal
  → independent review / policy
  → ClaimVersion / ClaimHead / OpenIssue
  → canonical projection
```

这不是绕过治理。Raw Evidence lane 仍必须执行 tenant、permission、retention、revocation 和 provenance 检查；它只是禁止把每个历史 chunk 无条件升级为 canonical truth。

## 2.4 Projection work amplification

当前 projection delivery 以 ordered outbox 为基础，不同 projection 会接触大量与自身无关的 event，随后返回 `NO_OP`。已观察的例子包括：

- Evidence 事件进入 Claim search projection 后成为 `NO_OP/NO_CLAIM_VERSION`；
- 非 purge 事件进入 purge projection 后成为 `NO_OP/NOT_PURGE_EVENT`；
- 每个 projection 都需维护连续 watermark，因此不能简单忽略 sequence gap。

结论：

> 在批量化之前，必须先定义 event→projection applicability，并让“不适用”成为可证明的有序跳过，而不是昂贵的业务 apply。

---

# 3. 不可破坏的架构不变量

DG-15 的任何性能收益都不得破坏以下不变量。

## I-01 Canonical single writer

Canonical State 仍只能通过受控 Canonical Procedure 变化。Worker、MCP adapter、Evidence projection、benchmark harness 和批处理器都没有直接 canonical DML 权限。

## I-02 Evidence is not belief

Evidence capture、Evidence search projection 或 Episode grouping 不得自动创建或更新 ClaimHead。

## I-03 Governed proposal ordering

单个 proposal 的合法链保持：

```text
create
→ immutable payload/digest verification
→ independent approve/reject
→ canonical procedure
```

不同 proposal 可以受控并行；同一 proposal 的语义步骤不得乱序。

## I-04 Role and scope isolation

reader、proposer、reviewer、revoker、worker 使用现有最小权限身份。连接复用必须以 principal/profile/scope digest 分池，并在归还时清除数据库 tenant/actor context。

## I-05 Per-item idempotency and receipts

批量请求不改变逐逻辑对象的幂等语义：同 key 同 fingerprint 返回原结果；同 key 不同 fingerprint 返回 `IDEMPOTENCY_CONFLICT`。批量结果必须逐 item 返回 ID、状态和 typed failure。

## I-06 Ordered, gap-free projection readiness

每个 projection 只有在 durable apply 或显式 applicability acknowledgement 后才能推进 watermark。dead-letter gap 未修复前不得越过。

## I-07 Barrier is readiness, not projection work

`finalize` 只负责等待本 case 所需 projection 达到目标位置。它不得隐式启动多轮 worker、重建全部历史或以 query 结果猜测 readiness。

## I-08 Canonical Gate remains authoritative

FTS、vector、Evidence projection、summary、graph 或任何批处理结果只产生 candidate。进入 Context 前仍执行 Canonical/Evidence applicability gate。

## I-09 Revoke remains fail closed

TX-05 提交后，已撤销 Evidence 立即失去可用 authority；异步清理可以延后，但 stale projection candidate 必须被拒绝。

## I-10 Cleanup state is explicit

必须分别报告：

```text
cleanup accepted
canonical block applied
derived purge complete
primary bytes erased
backup expiry pending/completed
```

不得用一个 `cleanup complete` 掩盖未完成阶段。

## I-11 Trace remains complete

并发、批量和异步执行仍需记录逻辑 operation、物理 batch、outbox range、watermark、失败 item、actor、scope 和耗时。性能优化不得通过丢失 provenance 或 hash-chain 记录实现。

## I-12 Quality and safety non-regression

Wrong-scope、cross-case contamination、stale/revoked Evidence acceptance、silent fallback 和 unauthorized canonical write 必须保持 `0/N`。

---

# 4. 目标架构

```text
Long-lived MCP service
        │
        ├── bounded call_many(capture requests)
        │        └── TX-01 + outbox, per-item receipts
        │
        ├── derived state proposals, only when applicable
        │        ├── cross-proposal bounded parallelism
        │        └── per-proposal ordered review chain
        │
        ▼
Ordered Outbox
        │
        ├── applicability routing / explicit skip acknowledgement
        │
        ├── Evidence search projection lane
        ├── Canonical FTS projection lane
        ├── Vector projection lane
        └── Purge / invalidation lane
                 │
          long-running worker(s)
          bounded micro-batches
                 │
                 ▼
        per-projection watermarks
                 │
                 ▼
        readiness barrier(targets)
                 │
                 ▼
      milai_memory_resolve → Context → vLLM
                 │
                 ▼
       namespace cleanup job + receipt
```

## 4.1 Worker topology

第一实现保持 Lean V1 的模块化单体和 one background worker 默认部署。

允许：

- 一个常驻 worker 在同一进程中按 projection lane 调度；
- 在单 lane 内对连续、可安全批处理的 event 做 micro-batch；
- 删除/权限失效任务优先于普通 embedding 补建；
- 通过配置做开发期 `batch_size` 与 concurrency sweep。

第一阶段禁止：

- 直接引入 Kafka；
- 建立通用 Projection Registry；
- 无证明地启动多个竞争同一 ordered lane 的 worker；
- 用越过 gap 的高 watermark 伪造 readiness；
- 把 Neo4j、OpenViking、Hindsight 或新 vector DB 加入产品路径。

## 4.2 Applicability routing

应建立显式、版本化的 event→projection routing table。候选语义如下，最终以当前 event enum 和 Migration 为准：

| Event family | Evidence search | Canonical FTS | Vector | Purge/invalidation |
| --- | --- | --- | --- | --- |
| Evidence ingested | applicable | not applicable | optional/later | not applicable |
| ClaimVersion committed | provenance link only | applicable | applicable | not applicable |
| OpenIssue changed | optional structured projection | applicable if searchable | optional | not applicable |
| Evidence revoked | remove/block | invalidate affected docs | invalidate affected vectors | applicable |
| Physical erasure eligible | not applicable | not applicable | not applicable | applicable |

不适用事件必须产生轻量、可审计的 ordered acknowledgement，使该 projection 可以连续推进 watermark；不得创建无意义的 search row，也不得执行完整业务 apply。

## 4.3 Readiness target

每个 case 记录最后一个相关写入返回的 outbox/canonical position。`finalize` 计算：

```yaml
required_projections:
  evidence_search: target_position_or_not_required
  canonical_fts: target_position_or_not_required
  vector: target_position_or_not_required
  purge: not_required_before_query
```

barrier 只有在所有 required projection 满足以下条件时成功：

```text
durable watermark >= target position
AND no unresolved dead-letter gap <= target
AND projection version/readiness identity matches query plan
```

超时返回 typed `PROJECTION_READINESS_TIMEOUT`，包括 lagging projection、current/target watermark 和最早 gap。禁止 silent retry、反复启动 worker 或用低质量 query result 当作 readiness 证明。

## 4.4 Evidence search projection

DG-15 应使 Raw Evidence/episode 成为非权威可检索候选，最小 projection 至少包含：

```yaml
evidence_id:
source_ref:
subject_id:
observed_at:
captured_at:
scope dimensions:
lexical_text:
semantic_text:
provenance pointer:
permission snapshot/ref:
retention state/ref:
revocation state/ref:
projection_version:
outbox_position:
```

读取规则：

```text
candidate generation
→ tenant/principal permission
→ retention readability
→ live revoke check
→ scope/time applicability
→ provenance hydration
→ Context candidate
```

Evidence projection 不能：

- 移动 ClaimHead；
- 提升 authority；
- 关闭 OpenIssue；
- 把摘要当原文；
- 把 LongMemEval answer/label/scorer 字段写入 projection；
- 绕过撤销与物理清理传播。

---

# 5. 开发原则

## 5.1 可用性和效率优先

按真实 MCP 产品链优化：

```text
MCP write
→ governed persistence
→ projection readiness
→ MCP resolve
→ Context
→ vLLM
```

不为漂亮抽象、未来多集群或论文故事提前建设框架。

## 5.2 减少防御性编程

“减少防御性编程”不表示削弱 Canonical Gate、权限、CAS、撤销或水位线不变量。它表示：

- 不新增宽泛 `except Exception` 后继续执行；
- 不为同一失败叠加多个隐式 fallback；
- 不用多轮 automatic retry 掩盖确定性错误；
- 不重复实现数据库已经原子保证的业务事实；
- 不保留两套长期并行的 production code path；
- 不把 optional 字段层层包装成无实际使用者的 abstraction；
- 失败在最接近根因的 typed boundary 暴露；
- 只有观察到的 failure 才增加针对性处理和测试。

现有 baseline path 可以在开发期通过显式实验开关保留，用于 matched comparison；DG-15 release 后只保留一个默认产品路径。

## 5.3 单项失败调试

任何批次失败都必须：

```text
停止当前批次
→ 定位一个 case
→ 定位一个 stage / projection / event
→ 复现一个最小失败
→ 修复根因
→ 运行该单项测试
→ 再恢复相关集合
```

禁止通过盲目增加 timeout、并发重跑或宽泛重试获得表面 PASS。

## 5.4 并行使用计算资源

开发与实验应充分利用当前 CPU、内存和可用 GPU，但必须保持逻辑调用与统计身份不变：

- 独立 namespace、不同 projection lane 或无共享状态的测试可以并行；
- 并发 sweep 使用 `1 / 2 / 4 / 8`，默认从 `4` 开始验证；
- 并发只改变物理调度，不增加 logical attempt、hidden retry 或 provider call；
- 先测 DB lock wait、connection saturation、queue lag 和失败率，再提高并发；
- 同一 proposal、同一 aggregate 和同一 ordered outbox lane 保持必要顺序；
- 不抢占、不重启、不重配 operator-owned vLLM 服务。

## 5.5 Provider

需要真实回答质量确认时，provider 固定使用当前 operator-owned vLLM：

```text
http://127.0.0.1:7860
Qwen3.6-35B-A3B-FP8
```

投影、数据库和 MCP transport 的单项性能测试不得调用 provider。只有通过 readiness 与 Context gate 后，才运行最小 matched E2E vLLM confirmation。

## 5.6 审查最小化

- 每个 work package 不重复生成独立审计包；
- 开发期以测试、结构化 metrics 和可重放 receipt 为证据；
- 只在唯一 release boundary 做一次独立审查；
- 如确需独立审查，可按 `/cra/memory/mx_memory/MiLAi/codex_sol_xhigh.md` 调用一次 reviewer；
- reviewer 工具输出不能自动成为 PASS，最终 disposition 仍需映射到 Goal gate；
- 安全 trace、hash-chain、role test 与 secret scan 不属于“无用审计”，不得删除。

---

# 6. Work Packages

## O0 — Baseline 与可观测性闭合

目标：先精确测量工作量，不改变语义。

交付：

1. 冻结 DG-14 五 case baseline identity 和当前配置；
2. 新增或补齐以下 stage metrics：
   - service cold start / warm reset；
   - Evidence logical items、MCP physical calls、DB transactions；
   - proposal logical items与 create/get/review calls；
   - worker process startup；
   - event queue wait、lease、apply、complete；
   - event type × projection type count；
   - applicable、explicit-skip、`NO_OP`、failed、dead-letter count；
   - watermark lag 与 barrier wait；
   - projection rows、embeddings、bytes；
   - cleanup accepted / blocked / purged / erased；
   - DB connection count、lock wait 和 transaction time。
3. 将 `time_to_query_ready` 定义为独立主指标：

```text
first capture start
→ all required query projections reach target watermark
```

4. ledger 继续使用现有 `append_many()`；除非 profile 证明其占目标 stage 的显著比例，否则不改 ledger 架构。

Exit：

- 一个 opened-dev case 可重放；
- stage、event、projection、watermark 和 transaction 身份闭合；
- 当前 `NO_OP` 与不适用 delivery 比例可量化；
- O0 不调用正式 holdout、不改 provider。

## O1 — 常驻 worker 与精确 barrier

目标：移除 finalize/cleanup 中反复启动 `worker --once` 的集中投影模型。

实现：

1. 测试 fixture / benchmark composition 启动一个常驻 `ProjectionWorker.run()`；
2. adapter 不再调用 `_worker_once()` 完成投影；
3. 每个 write receipt 传播目标 outbox/canonical position；
4. finalize 只调用 readiness barrier；
5. barrier 以 required projection watermark 和 dead-letter gap 为准；
6. worker 进程异常、barrier timeout 和 projection failure 返回 typed outcome；
7. cleanup readiness 与 query readiness 使用不同 target 集合。

Exit：

- finalize 不启动 worker 子进程；
- worker 在 case 间持续运行；
- barrier 能正确等待、超时并报告最早 gap；
- worker crash/restart 后不重复 side effect；
- exact/canonical query 不等待不相关 projection。

## O2 — Event→Projection applicability

目标：先减少工作量，再批量执行剩余工作。

实现：

1. 冻结版本化 routing table；
2. lease/apply path 区分 `APPLY` 与 `ACK_NOT_APPLICABLE`；
3. 不适用 event 只推进该 projection 的有序 acknowledgement；
4. 删除/权限事件优先调度；
5. watermark 仍保持 gap-free；
6. 记录每类 event 的 apply/skip/no-op count。

Exit：

- 对 routing table 声明为不适用的组合，完整业务 `NO_OP` apply 为 `0/N`；
- explicit skip 可审计且不创建 projection row；
- dead-letter gap 测试继续阻止 watermark；
- 删除事件不被普通 embedding backlog 长期阻塞。

## O3 — Evidence search projection

目标：让原始会话作为 Evidence 候选高效检索，停止为 benchmark 历史无条件创建数百个 canonical chunk Claim。

实现：

1. 定义 Evidence search projection typed contract；
2. 建立 lexical/temporal 最小 projection；
3. 仅在 bounded lexical/temporal不足时生成或读取 semantic projection；
4. resolve 支持 Evidence candidate 与 Canonical State candidate 的双通道；
5. Context 明确标记 evidence observation 与 canonical state；
6. revoke/permission/retention 变化触发 projection invalidation/purge；
7. LME adapter 默认使用 Raw Evidence lane；只有明确 derived state 才走 proposal/review。

若 Schema 变化，必须同时提交 Migration、upgrade/downgrade 或不可逆理由、回填策略、真实 PostgreSQL 测试和 ADR/crosswalk 影响说明。

Exit：

- task/session history 可以从 Evidence lane 被检索；
- Evidence candidate 不出现在 ClaimHead；
- revoked/denied Evidence acceptance 为 `0/N`；
- provenance 可映射到 original LongMemEval session；
- 质量不低于 DG-14 对应 budget Gate；
- canonical chunk count 相对 DG-14 显著下降，并报告实际降幅。

## O4 — 受控并发 MCP 调用

目标：减少逐项网络/stdio等待，不改变 logical operation 数和治理顺序。

实现：

1. 为当前 persistent stdio MCP transport 增加明确的 async/multiplexed `call_many` 或等价 batch contract；
2. 不使用不具备 request-ID demultiplexing 的共享 dispatcher 加 naive thread pool；
3. Evidence capture 支持有界并发；
4. 不同 proposal/chunk 可以并行；
5. 单 proposal 的 create→verify→review 保持有序；
6. 每个 item 独立返回 receipt/typed failure；
7. 对 concurrency `1/2/4/8` 做 matched sweep；
8. 选择吞吐、p95、DB lock wait 和失败率共同最优的最小并发度。

可选简化：如果 review boundary 能直接验证 immutable proposal digest，可以移除热路径额外 `proposal_get`；但必须保留独立 reviewer、digest binding、权限检查和契约测试。仅为少一次调用而绕过 review 禁止。

Exit：

- logical operation count 与串行基线一致；
- hidden retry/provider call 为 `0`；
- dispatcher 不串包、不交叉 actor/scope；
- partial batch failure 可精确定位并只重放允许重试的 item；
- 并发度由报告选择，不写死为越高越好。

## O5 — Projection 数据库微批处理

目标：减少每 event 多事务 lease/apply/complete 的数据库放大。

前置：O2 applicability 已完成或等价工作量证据已建立。

实现：

1. 按 projection lane lease 连续、有界 event range；
2. 同类适用 event 使用 set-based SQL 或 bounded micro-batch；
3. embedding 请求跨同 batch item 合并，但保留 deterministic downstream key；
4. durable apply 后批量 complete 并推进连续 watermark；
5. batch 内返回 per-item outcome；
6. 单 item 确定性失败不得把其后的 watermark 越过；
7. batch size 做 `1/16/32/64` sweep，记录 lock、memory、latency、retry amplification。

Exit：

- DB transactions/logical item 显著低于基线；
- projection row、embedding 和 receipt 与 batch size 1 语义等价；
- crash at lease/apply/complete boundary 可恢复；
- idempotency、ordered watermark 和 dead-letter gap 测试通过。

## O6 — Runtime、MCP 连接与身份上下文复用

目标：降低 warm reset 和 per-case profile startup，不扩大权限。

实现：

1. Runtime、MCP server、DB pool 和 worker 在 matched development run 中常驻；
2. case 只创建隔离 namespace 和 scope-bound logical context；
3. MCP client pool 以 profile/principal/scope digest 为 key；
4. 数据库连接归还时清除 tenant/actor session state；
5. case switch 必须显式重新绑定 identity；
6. 冷启动与热复用分别报告。

Exit：

- warm reset 不重复启动 Runtime/MCP/worker；
- wrong-profile/wrong-scope reuse 为 `0/N`；
- pool contamination 真实 login role 测试通过；
- cold start 不被混入 warm reset 指标。

## O7 — Namespace cleanup job

目标：保持逐 Evidence 可追溯撤销，同时避免 benchmark 逐项同步等待清理。

实现：

1. 提交 namespace-scoped cleanup job；
2. Runtime 内部仍按 Evidence 执行授权、TX-05、GroundingBlock 与 purge outbox；
3. 返回 namespace job receipt 和逐 Evidence outcome；
4. benchmark 默认在全部 case query 完成后提交 cleanup，避免同 tenant ordered outbox 对下一 case形成 head-of-line blocking；
5. 分别暴露 accepted、canonical-blocked、projection-purged、bytes-erased watermark；
6. next isolated query 不等待不相关 physical erasure；
7. 共享 blob、legal hold、backup expiry 状态保持精确。

Exit：

- cleanup 提交不逐 Evidence 做 MCP round trip；
- TX-05 fail-closed 仍同步生效；
- query 看不到已撤销 Evidence；
- cleanup job restart/replay 幂等；
- 物理未完成时不宣称“已删除”。

## O8 — Query critical path cleanup

目标：在完成写入/投影 P0 后再处理剩余 query p95。

候选：

- 将 diagnostic `milai_trace_get` 移出回答 critical path；或让 `milai_memory_resolve` 返回足够的 trace receipt；
- 保持一次逻辑 MCP resolve；
- lazy hydrate 原始 Evidence body；
- exact current-state route 不进入 vector/reranker。

Exit：

- trace 完整性不下降；
- 512 与 2048 budget query p95 均达到本 Goal development target；
- provider prompt/context identity 不变。

## O9 — Ledger 优化（条件启动）

当前 ledger 已使用 `append_many()`，且 finalize/cleanup 计时不包含主要 ledger batch 写入。因此 O9 默认 `DEFERRED`。

只有 O0 profile 证明 ledger 占目标 critical path 的显著比例时，才允许：

- 单 writer queue；
- bounded buffer；
- 批量 hash-chain append/fsync；
- 明确 flush/barrier。

禁止降低 hash-chain、logical operation completeness、crash durability 或 run seal 语义。

---

# 7. 有序实施计划

## P0 — 最大瓶颈闭合

```text
O0 Baseline
→ O1 Persistent worker + barrier
→ O2 Applicability routing
```

P0 完成前不开始大规模 MCP 并发或 DB batch。

## P1 — 语义工作量与调用等待优化

```text
O3 Evidence search projection
∥
O4 Bounded MCP concurrency
```

O3 与 O4 可由隔离文件 owner 并行开发；共享 schema/contract 变更必须先冻结接口并串行合并。

## P2 — 数据库与生命周期优化

```text
O5 DB microbatch
→ O6 Connection/context reuse
→ O7 Namespace cleanup
```

O5 可在 O3 的 Evidence projection lane 和现有 Canonical projection lane分别测量。

## P3 — 次要残差与发布确认

```text
O8 Query path
→ conditional O9 Ledger
→ five-case matched confirmation
→ one release-boundary review
```

---

# 8. 实验设计

所有 optimization experiment 先用一个 opened-dev case，单项 PASS 后才恢复五 case。

| Experiment | Variant | 主要回答 |
| --- | --- | --- |
| E1 Worker lifecycle | `worker --once` vs persistent | 进程启动和集中 drain 占多少 |
| E2 Applicability | current delivery vs routed/skip | 无意义 NO_OP 与事务减少多少 |
| E3 MCP concurrency | `1/2/4/8` | 吞吐、p95、lock wait、失败率的最优点 |
| E4 DB batch | `1/16/32/64` | transactions、projection throughput 与恢复代价 |
| E5 Memory lane | canonical chunk wrapper vs Evidence projection | 质量、治理对象数、ready time、Context tokens |
| E6 Cleanup | immediate per-item vs deferred namespace job | query isolation 与清理完成时间 |
| E7 Query trace | separate trace call vs receipt-in-resolve | query p95 与 trace completeness |

执行规则：

1. 相同 case、input、scope、token budget 和 provider配置；
2. 每个 variant 使用新的 namespace 和 run identity；
3. automatic retry 默认 `0`；
4. 失败进入 denominator；
5. 单项 infrastructure test 不调用 vLLM；
6. 最终质量 confirmation 才调用同一 vLLM；
7. 不消费正式 holdout；
8. 不按 label、case ID 或正确答案优化 routing/projection。

---

# 9. 指标合同

## 9.1 Lifecycle

```text
cold service startup
warm namespace reset
evidence capture throughput
governance throughput
projection queue lag
time_to_query_ready
barrier wait
query p50/p95/p99
cleanup submission
canonical block latency
derived purge latency
physical erasure latency
```

这些必须分开报告，禁止只给一个 full lifecycle speedup。

## 9.2 Work amplification

```text
logical Evidence / MCP calls / DB transactions
logical proposal / create-get-review calls
outbox events by type
deliveries by projection
applicable / explicit skip / NO_OP / failed
projection rows per logical source
embedding unique items / duplicate ratio
worker starts / case
watermark advances / DB transaction
```

## 9.3 Correctness

```text
wrong-scope acceptance
cross-case contamination
revoked evidence acceptance
stale-current acceptance
unauthorized canonical write
reviewer/submitter collapse
idempotency conflict handling
watermark over dead-letter gap
silent fallback
lost or duplicated logical item
```

安全事件必须报告 `0/N`，并同时报告 N；`N=0` 不能作为 PASS。

## 9.4 Quality

```text
EM
normalized F1
Hit@K
NDCG@K
Evidence Coverage
UNKNOWN / abstention rate
provenance resolution
Context token count
```

## 9.5 Resource

```text
CPU utilization
RSS
DB connections
DB lock wait
transaction time
worker utilization
embedding GPU/service utilization when applicable
vLLM provider calls and latency only in E2E confirmation
```

---

# 10. Development targets 与 release gates

以下数字仅适用于当前 DG-14 opened-development workload 和当前设备，是 DG-15 development target，不是生产 SLA、论文 claim 或 schema freeze 条件。

## 10.1 Primary efficiency gate

| Metric | Baseline | Required target | Stretch target |
| --- | ---: | ---: | ---: |
| warm namespace reset p95 | current mean `4.310 s` | `<= 2.0 s` | `< 1.0 s` |
| ~500 Evidence ingest | current mean `5.801 s` | `<= 3.0 s` | `1–2 s` |
| finalize barrier after last logical write | current mean `109.534 s` | `<= 15 s` | `<= 10 s` |
| time_to_query_ready | not previously isolated | `<= 45 s/case` | median `<= 30 s` |
| MCP query p95, 512/2048 | `118.23/92.29 ms` | no regression beyond `+10%` | both `< 100 ms` |
| cleanup submission | current cleanup mean `85.017 s` | `<= 2.0 s` | `< 1.0 s` |
| derived cleanup completion | current mean `85.017 s` | `<= 45 s` | `<= 30 s` |

若 O0 证明现有计时边界与表中解释不同，先修订 metric identity，再冻结 gate；不得为了通过而删除慢阶段。

## 10.2 Structural cost gate

EXACT query：

```text
auxiliary LLM calls = 0
embedding calls     = 0
vector search       = 0
reranker calls      = 0
broad scan          = 0
```

Projection：

```text
worker process starts per case       = 0 after warm service start
full apply for declared-inapplicable = 0/N
watermark over unresolved gap        = 0/N
lost logical items                   = 0/N
duplicate canonical commits          = 0/N
```

Cleanup：

```text
namespace cleanup MCP submissions = O(1) per namespace
logical Evidence revoke outcomes   = N explicit receipts
next isolated query waits for unrelated physical erasure = false
```

## 10.3 Quality gate

在同一 opened-dev 五 case matched confirmation 中：

- 2048-token `EM/F1 >= 0.60`；
- 2048-token Evidence Coverage `>= 0.80`；
- 512-token quality 不低于 DG-14 对应 arm 的已记录值；
- provenance mapping success 为 `N/N`；
- Context 不包含 answer、answer session labels 或 scorer output；
- Evidence projection 与 canonical state 在 Context 中可区分。

## 10.4 Governance and safety gate

```text
WrongScopeAcceptance             = 0/N
CrossCaseContamination           = 0/N
RevokedEvidenceAcceptance        = 0/N
StaleCurrentAcceptance           = 0/N
UnauthorizedCanonicalWrite      = 0/N
ReviewerSubmitterCollapse        = 0/N
SilentFallback                   = 0/N
WatermarkGapViolation            = 0/N
IdempotencyDuplicateSideEffect   = 0/N
```

## 10.5 Operability gate

- 一条命令可启动 persistent MCP + Runtime + worker development composition；
- 单 case smoke 可单独运行 ingest/finalize/query/cleanup stage；
- typed failure 指向一个具体 stage/projection/event；
- worker restart、MCP reconnect、DB transaction rollback 可重放；
- warm/cold、query-ready/cleanup-ready、logical/physical operation 不混写；
- provider 仍为 vLLM，最终 matched confirmation 不重启 operator service。

---

# 11. 测试矩阵

## 11.1 Unit / contract

- event→projection applicability table；
- explicit skip 不执行 business apply；
- required projection target calculation；
- barrier timeout typed payload；
- per-item batch idempotency/fingerprint conflict；
- dispatcher request-ID demultiplexing；
- Evidence projection schema 与 label boundary；
- Context 中 Evidence/Canonical 类型隔离；
- namespace cleanup receipt 聚合。

## 11.2 PostgreSQL integration

- contiguous batch lease；
- apply/complete/watermark 原子性；
- batch 中单 item failure；
- dead-letter gap 不可跨越；
- lease timeout/reclaim；
- worker crash after apply before complete；
- two-connection idempotency race；
- real login role/RLS；
- tenant/actor context pool reset；
- revoke 后 stale Evidence/FTS/vector candidate 被 gate 拒绝；
- shared blob 不提前物理删除。

## 11.3 Concurrency

- 500 bounded concurrent Evidence capture；
- 同 idempotency key 并发 replay；
- 不同 proposal 并行、单 proposal有序；
- reviewer 与 proposer 身份不交叉；
- dispatcher response 不串包；
- connection pool 不跨 scope；
- batch size/concurrency sweep 无丢失、重复或 watermark violation。

## 11.4 Failure

- worker unavailable；
- worker crash/restart；
- MCP connection reset；
- DB deadlock/serialization failure 的现有合法重试语义；
- embedding unavailable 时 exact/canonical correctness 保持；
- projection timeout；
- cleanup partial failure；
- physical erasure blocked by live shared reference；
- vLLM unavailable只影响最终 answer，不改变 Memory state。

## 11.5 E2E

```text
history Evidence
→ bounded MCP capture
→ governed derived state where applicable
→ persistent incremental projection
→ watermark barrier
→ memory.resolve
→ Context
→ vLLM answer
→ namespace cleanup job
→ revoked candidate rejected
```

先运行一个 opened-dev case；相关单项通过后再运行五 case matched confirmation。

---

# 12. 变更边界与非目标

DG-15 不实现：

```text
新的 Memory Engine
embedding model 替换
新的 vector database
Neo4j canonical graph
OpenViking/Hindsight/Graphiti production route
Kafka 或通用 Projection Registry
Direct + HTTP + MCP 三 transport parity
远程 MCP / OAuth 产品化
portable offline CURRENT lease
push invalidation
learned Task resolver
默认 reconstructive L2
自动 canonical promotion
自动 OpenIssue resolution
自动真实个人数据导入
论文创新或 SOTA 声明
```

DG-15 也不通过以下方式“优化”：

- 减少 required audit facts；
- 合并 proposer/reviewer 权限；
- 跳过 Proposal 或 Canonical Gate；
- 延迟 TX-05 fail-closed；
- 将失败从 denominator 删除；
- 增加 hidden retry；
- 关闭 fsync 或 transaction durability 后比较；
- 用更宽 scope 提高 retrieval recall；
- 将 projection cache 当 truth；
- 把 cleanup submission 当作 physical erase complete。

---

# 13. 交付物

DG-15 至少交付：

1. 本 Goal 文档；
2. event→projection applicability contract；
3. persistent worker + readiness barrier 实现与测试；
4. Evidence search projection ADR、Migration 和回滚/兼容说明（若 O3 改 Schema）；
5. bounded MCP batch/concurrency contract；
6. projection micro-batch 实现与真实 PostgreSQL 测试；
7. namespace cleanup job 与状态 receipt；
8. operator runbook；
9. O0 baseline 与 before/after stage report；
10. E1–E7 experiment artifacts；
11. 五 case matched vLLM confirmation；
12. 唯一 release-boundary independent review disposition。

报告必须逐项标注：

```text
IMPLEMENTED
TESTED
CHARACTERIZED
DEFERRED
BLOCKED
UNKNOWN
NOT FORMALLY EVALUATED
```

---

# 14. 开发状态板

初始状态：

```text
[ ] O0 Baseline 与可观测性闭合
[ ] O1 常驻 worker 与精确 barrier
[ ] O2 Event→Projection applicability
[ ] O3 Evidence search projection
[ ] O4 受控并发 MCP 调用
[ ] O5 Projection 数据库微批处理
[ ] O6 Runtime/MCP/身份上下文复用
[ ] O7 Namespace cleanup job
[ ] O8 Query critical path cleanup
[ ] O9 Ledger 优化（默认 DEFERRED，需 profile 解锁）
[ ] 单 case E2E
[ ] 五 case matched vLLM confirmation
[ ] release boundary review
```

状态晋级必须以代码、测试、运行 receipt 和 report 为准；文档完成不表示实现完成。

---

# 15. Release disposition

只有同时满足 Primary efficiency、Structural cost、Quality、Governance/Safety 和 Operability gate，才能标记：

```text
DG15 = LOCAL_MCP_GOVERNED_MEMORY_PIPELINE_EFFICIENT
```

该标签严格限定为：

```text
local MCP
opened-development LongMemEval workload
current machine and pinned configuration
deidentified/synthetic development data
Runtime CANDIDATE
Schema EXPERIMENTAL
```

该标签不表示：

```text
Production ready
Remote MCP ready
Real personal data ready
Schema frozen
General benchmark superiority
Paper result
Novelty claim
```

若质量、安全或治理 gate 失败，即使 latency 达标也不得发布该标签。若性能 target 未达但语义正确，应标记 `CHARACTERIZED / TARGET_MISS`，输出瓶颈与下一最小实验，不得降低 Gate。

---

# 16. 停止条件

完成以下闭环后停止本 Goal：

```text
persistent MCP/Runtime/worker
→ bounded Evidence ingest
→ governed canonical writes only where semantically required
→ continuous routed projection
→ exact watermark readiness
→ memory.resolve
→ minimal Context
→ vLLM confirmation
→ namespace cleanup receipt
```

并且：

- 五 case opened-development Gate 通过；
- 所有安全事件为 `0/N` 且 N 非零；
- before/after 性能按阶段完整报告；
- 未消费正式 holdout；
- 唯一 release-boundary review 关闭 P0/P1；
- Runtime/Schema 继续明确为 `CANDIDATE / EXPERIMENTAL / NO-GO FOR FREEZE`。

随后停止，不在本 Goal 中继续扩展 graph、reconstructive retrieval、multi-transport 或论文实验。
