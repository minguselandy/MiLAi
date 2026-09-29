---
title: MiLAi Lab 代码组织、结构优化与边界治理开发规划 v12.0
date: 2026-09-29
status: PLAN_ONLY_NOT_EXECUTED
scope: MiLAi-Lab / code organization / architecture boundaries
repository: minguselandy/MiLAi
latest_main_observed: cca2fd9d1cb4614c44a40ddc0458325d959e6740
latest_behavioral_code_merge: 8781ad798184040da2e4c48550b993915dcbe0db
architecture_head: 97efe0c997b37022f21905cff63f69cb480527a8
experiment_goal: paused
research_goal: NOT_ACHIEVED
product_status: NO_GO
---

# MiLAi Lab 代码组织、结构优化与边界治理开发规划 v12.0

## 0. 目标

本规划基于最新 GitHub `main`、PR #70–#74 合并结果、`application/` 重构、当前项目地图、验证矩阵及核心运行代码重新梳理。

目标是完成下一轮**行为保持型代码整理**：

> 把可复用能力放到明确 canonical 层；让 contracts / application / memory / providers / integrations / methods / benchmarks / runners 的依赖方向单向化；保留旧路径兼容入口和历史实验复现；用自动边界检查阻止未来重新耦合。

本规划不恢复实验 Goal，不运行 Host/embedding/Judge，不改变 Product，不改变 v10/R2 历史失败。

---

# 1. 当前仓库真实状态

当前观察到：

```text
main latest docs commit:
cca2fd9d1cb4614c44a40ddc0458325d959e6740

latest code architecture merge:
8781ad798184040da2e4c48550b993915dcbe0db

PR #74 source head:
97efe0c997b37022f21905cff63f69cb480527a8
```

PR #70 → #71 → #72 → #73 → #74 已按依赖顺序合入 `main`。

当前主线已经包含：

- v6 RequestContext；
- v7 protocol calibration；
- v8/v9 benchmark adapters；
- v10 R1/R2 修复代码；
- PR #74 application architecture refactor。

历史冻结提交继续作为历史实验复现身份。

---

# 2. 当前已经正确的架构边界

PR #74 已将业务核心整理为：

```text
src/milai_lab/application/
├── __init__.py
├── journal.py
├── recovery.py
├── tools.py
└── world.py
```

职责：

```text
world.py
  -> SQLite business world / actual business state

tools.py
  -> business schemas / owner-bound tool adapters

journal.py
  -> actual business calls / idempotency /
     trusted operation binding / effects

recovery.py
  -> unknown outcome query / recovery

runners/langmem_application.py
  -> experiment orchestration / phases / writer cadence
```

旧 `runners/langmem_foundation.py` 已变成薄兼容导出。

这一方向应保持。

---

# 3. 当前最主要的剩余结构问题

## 3.1 `baselines/` 同时包含基础服务和真正 baseline

当前 `baselines/` 中既有：

```text
langmem_mcp.py
langmem_strict_tools.py
langmem_revision_store.py
langmem_agent.py
```

也有：

```text
benchmark_memories.py
RawDialogue / summary / retrieval baseline
```

因此 `baselines` 同时表示：

```text
shared runtime foundation
+
experimental comparison method
```

应逐步拆开。

---

## 3.2 baseline 仍反向依赖 runner

当前 shared benchmark code 会调用：

```text
runners.mem0_native
runners.simplemem_native
```

但这些文件实际拥有：

```text
Mem0NativeRuntime
SimpleMemTextRuntime
SDK pin
provider bridge
native add/search
```

它们是 integration，不是 runner。

当前方向：

```text
baseline
  ↓
runner
```

目标：

```text
baseline ─┐
          ↓
      integration
          ↑
runner ───┘
```

---

## 3.3 runner 与 runner 复用公共 helper

部分 unified benchmark runner 会从另一个 runner 借：

```text
prepare_manifest
start_job
finish_job
source_identity
trace_costs
validate_config
```

这些应属于 benchmark execution harness。

不应让：

```text
MemSyco runner
   -> MERIT runner
```

成为长期结构。

---

## 3.4 provider 仍知道具体 research methods

`providers/langmem_chat.py` 历史上直接理解：

```text
MemoryBoundaryView
memory_result
M1
ODR
freshness projection
```

这形成：

```text
provider
  -> methods
```

增加新方法时必须修改 provider。

目标：

```text
method defines generic transform/hook
runner injects hook
provider only executes pipeline
```

---

## 3.5 Memory canonical contract 不明确

当前 Memory core 合同分散在：

```text
baselines/langmem_mcp.py
baselines/langmem_strict_tools.py
baselines/langmem_revision_store.py
methods/memory_boundaries.py
methods/request_context.py
```

没有统一 canonical package 表达：

```text
MemoryRecord
MemoryMutationReceipt
MemoryReadResult
MemorySourceRef
MemoryObjectRef
```

这会阻碍后续 Grounded Memory / Semantic-Episodic 分类。

---

## 3.6 `methods/request_context.py` 实际不是 method

它定义：

```text
RequestContext
MemoryPlacement
ModelView
render_system
render_request
```

前半部分是通用合同，后半部分是 Memory presentation。

应拆成：

```text
contracts/request.py
memory/presentation.py
```

旧路径兼容 re-export。

---

## 3.7 `langmem_application.py` 仍承担多类实验编排

虽然业务 core 已提取，但该 runner 仍包含：

```text
WriterPolicy
LocalStateBank
LocalStateController
writer boundary
history
summary
public-message lifecycle
phase orchestration
```

建议后续只拆明确的 writer-policy 实验编排，不按 LOC 大拆文件。

---

## 3.8 External Memory adapter 仍放在 runners

当前：

```text
runners/mem0_native.py
runners/simplemem_native.py
```

更合理归属：

```text
integrations/memory/mem0.py
integrations/memory/simplemem.py
```

runner 只管理生命周期和任务顺序。

---

## 3.9 strict mypy exclude 暴露边界技术债

当前 strict mypy exclude 覆盖多个 active 模块：

```text
application/journal
application/tools
application/recovery
baselines/langmem_agent
instrumentation
revision_store
local_state_attention/*
providers/langmem_chat
若干 runner
```

不要求一次清零。

应优先把未来 canonical contracts / memory / application public interfaces 纳入类型检查。

---

# 4. 目标目录结构

逐步收敛为：

```text
src/milai_lab/
├── contracts/
│   ├── request.py
│   ├── memory.py
│   ├── operations.py
│   ├── evidence.py
│   └── benchmark.py
│
├── application/
│   ├── world.py
│   ├── journal.py
│   ├── recovery.py
│   ├── tools.py
│   └── refs.py
│
├── memory/
│   ├── records.py
│   ├── mcp.py
│   ├── strict_tools.py
│   ├── revision_store.py
│   └── presentation.py
│
├── providers/
│   ├── contextual_vllm.py
│   ├── contextual_capacity.py
│   ├── chat_bridge.py
│   └── request_pipeline.py
│
├── integrations/
│   └── memory/
│       ├── mem0.py
│       └── simplemem.py
│
├── methods/
│   ├── memory_boundaries.py
│   ├── memory_lifecycle.py
│   ├── local_state_attention/
│   ├── freshness_projection/
│   ├── milai_m1/
│   └── on_demand_reconstruction/
│
├── benchmarks/
│   ├── common.py
│   ├── memsyco.py
│   ├── merit.py
│   └── execution.py
│
├── runners/
│   ├── application.py
│   ├── benchmark.py
│   ├── persistent_memory.py
│   └── writer_policy.py
│
├── harness/
├── datasets/
├── scorers/
└── analysis/
```

这是目标职责图，不要求一次完成全部移动。

---

# 5. 目标依赖 DAG

```text
contracts
   │
   ├────────► application
   ├────────► memory
   ├────────► providers
   └────────► datasets

application ──────┐
memory ───────────┤
providers ────────┤
                  ▼
             integrations
                  │
                  ▼
                methods
                  │
                  ▼
              benchmarks
                  │
                  ▼
                runners
                  │
                  ▼
                 tools
```

`analysis/scorers` 从结果侧读取，不进入 runtime 写路径。

---

# 6. Package import rules

## `contracts/`

允许：

```text
stdlib / typing / light DTO dependency
```

禁止：

```text
runner
method
provider
external SDK
business implementation
```

## `application/`

允许：

```text
contracts
application-local persistence
LangGraph adapter where explicitly needed
```

禁止：

```text
runner
research method
benchmark scorer
gold
external memory SDK
```

## `memory/`

允许：

```text
contracts
LangGraph Store
LangMem adapter
```

禁止：

```text
runner
benchmark
business world
specific research method
```

## `providers/`

允许：

```text
contracts
harness accounting
HTTP/model SDK
```

禁止：

```text
specific method
runner
benchmark
```

## `integrations/`

允许：

```text
contracts
providers
memory interfaces
external SDK
```

禁止：

```text
runner
scorer
method policy
```

## `methods/`

允许：

```text
contracts
memory interfaces
application interfaces
generic provider hooks
```

禁止：

```text
runner
benchmark scorer
Product private implementation
```

## `benchmarks/`

允许：

```text
contracts
datasets
scorers
integrations
harness
```

不持有 method implementation。

## `runners/`

负责组合下层模块。

任何被多个非-runner 模块依赖的能力，应下沉而不是继续放 runner。

---

# 7. 兼容策略

采用：

```text
canonical implementation
+
old path thin re-export
```

例如未来：

```python
# baselines/langmem_mcp.py
from milai_lab.memory.mcp import MemoryMCP as MemoryMCP
```

兼容 facade 不允许新增逻辑。

---

# 8. 历史复现规则

历史报告、source SHA、method commit、execution commit 不重写。

历史实验：

```text
checkout original commit
```

当前 main 不需要保持所有历史源码字节一致。

当前 re-export 只保证当前兼容 import。

---

# 9. Phase S0 — import / ownership inventory

只读阶段，模型调用 0。

输出：

```text
docs/CODE_ARCHITECTURE_V12_BASELINE.md
data/manifests/code-architecture-v12-import-map.json
```

记录：

- package/import graph；
- reverse dependencies；
- runner-to-runner edges；
- baseline-to-runner edges；
- provider-to-method edges；
- canonical owner；
- compatibility facade；
- mypy excludes；
- CI verification group。

不要仅用 LOC 判断问题。

---

# 10. Phase S1 — canonical contracts

## 10.1 `contracts/request.py`

迁移 canonical：

```text
RequestContext
MemoryPlacement
ModelView
```

原：

```text
methods/request_context.py
```

改为 thin re-export。

## 10.2 `memory/presentation.py`

迁移：

```text
record_material
render_system
render_request
json_action history rendering helper
```

因为这些知道 Memory material / placement。

## 10.3 `contracts/memory.py`

先定义最小 DTO / Protocol：

```text
MemoryRecord
MemoryMutationReceipt
MemoryReadResult
MemorySourceRef
MemoryObjectRef
```

首阶段不改变 Store 序列化。

## 10.4 `contracts/operations.py`

定义：

```text
EffectStatus
OperationIdentity
ApplicationTarget
```

仅数据合同。

---

# 11. Phase S2 — Memory core 从 baselines 提取

迁移 active shared core：

```text
baselines/langmem_mcp.py
    -> memory/mcp.py

baselines/langmem_strict_tools.py
    -> memory/strict_tools.py

baselines/langmem_revision_store.py
    -> memory/revision_store.py
```

旧文件 re-export。

暂不整体移动 `langmem_agent.py`。

因为它仍然包含 recipe / prompt / tool wiring，具有 baseline/agent 配方属性。

---

# 12. S2 验收

必须保证 old/new：

```text
same object where possible
same tool schema
same ToolMessage JSON
same namespace
same UUID behavior
same Store calls
same exceptions
same revision semantics
```

需要：

```text
unit tests
golden receipts
architecture import checks
source identity checks
```

---

# 13. Phase S3 — External integration canonicalization

迁移：

```text
runners/mem0_native.py
    -> integrations/memory/mem0.py

runners/simplemem_native.py
    -> integrations/memory/simplemem.py
```

旧 runner 文件 re-export。

---

## 13.1 Integration owner

负责：

```text
SDK source pin
dependency identity
provider bridge
native database
native add/search
snapshot
native retries
```

## 13.2 Runner owner

负责：

```text
task ordering
owner/session
when adapter is created
when it is closed
result collection
experiment identity
```

---

# 14. Phase S4 — Benchmark common extraction

提取：

```text
prepare_manifest
start_job
finish_job
source_identity
trace_costs
benchmark execution status
```

至：

```text
harness/benchmark_execution.py
```

或：

```text
benchmarks/execution.py
```

MemSyco 不再 import MERIT runner helper。

MERIT 与 MemSyco 各保留自己的：

```text
native data
world/tools
scorer
task conversion
```

---

# 15. Phase S5 — Provider / method decoupling

这是最高风险结构阶段。

## 15.1 问题

provider 不应包含：

```text
if M1
if ODR
if memory boundary
if freshness projection
```

## 15.2 新 generic interfaces

新增：

```python
class RequestTransform(Protocol):
    def project(...) -> ...

class DeliveryObserver(Protocol):
    def record_delivery(...) -> None

class ResponseHook(Protocol):
    def on_response(...) -> None
```

runner 注入具体 transforms。

## 15.3 Provider 只做

```text
message conversion
tool protocol
capacity
HTTP
usage
response decode
```

---

# 16. S5 等价 Gate

provider 重构前冻结：

```text
JSON-action requests
native requests
tool continuation
empty memory
multiple memory
current_request placement
system placement
actual tool receipts
capacity checks
```

比较：

```text
ordered request dict
locked HTTP serialization
tool catalog
usage accounting
decoded tool calls
```

任何行为差异都阻断该阶段。

---

# 17. Phase S6 — Runner orchestration cleanup

前面依赖边界完成后再处理。

从 `langmem_application.py` 提取：

```text
WriterPolicy
WRITER_POLICY_INSTRUCTIONS
run_writer_policy_turn
```

至：

```text
runners/writer_policy.py
```

`langmem_application.py` 保留：

```text
phase orchestration
public message lifecycle
session progression
resource reopen
result handoff
```

不重新实现 application core。

---

# 18. Phase S7 — Automated dependency boundaries

扩展现有：

```text
milai-lab-check-boundary
milai-lab-check-tools-boundary
verification matrix
application architecture tests
```

正式验证 package DAG。

规则示例：

```text
contracts -> no upper internal layer
application -> no runner/method/benchmark
memory -> no runner/method/benchmark
provider -> no method/runner/benchmark
integration -> no runner
method -> no runner/benchmark scorer
benchmark -> no runner
runner -> downward composition
tools -> runner/public API
```

---

# 19. Compatibility facade checker

增加 AST 检查。

兼容 facade 只允许：

```text
docstring
import / re-export
__all__
TYPE_CHECKING
```

禁止在 facade 中重新加入逻辑。

这样可以防止未来 old path 再次变成第二实现。

---

# 20. 类型治理

不一次性清除所有 mypy exclude。

第一批纳入 strict：

```text
contracts/*
application/world.py
memory contracts
integration public interfaces
benchmark execution DTO
```

第二批：

```text
application/journal.py
application/tools.py
application/recovery.py
```

历史 M1 / ODR / old LSA 不作为第一优先级。

---

# 21. Source identity

PR #74 已正确要求 canonical application source 被 identity hash 覆盖。

以后每个 canonical move 都必须：

1. 新 canonical path 进入 identity；
2. facade 不能是唯一 hash；
3. historical lock 不重写；
4. new recipe 用新 identity。

建议新增：

```text
harness/source_identity.py
```

统一生成 package source maps。

---

# 22. 避免 source list 漂移

当前 `APPLICATION_SOURCE_FILES` 为显式 tuple。

保留审计价值，但增加测试：

```text
all .py in package
==
registered package sources
```

避免新增文件忘记进入 identity。

---

# 23. Tests 组织

新测试逐步使用：

```text
tests/contracts/
tests/application/
tests/memory/
tests/providers/
tests/integrations/
tests/methods/
tests/benchmarks/
tests/runners/
tests/architecture/
```

不强制一次迁移所有历史测试。

---

# 24. Architecture tests 必须覆盖

### Dependency DAG

禁止非法 import。

### Canonical object identity

旧 re-export 指向 canonical object。

### Facade purity

兼容文件无运行逻辑。

### Source identity

canonical implementation 被 hash。

### Optional dependency

core import 不加载 Mem0/SimpleMem/local assets。

### Package build

wheel/sdist 包含 canonical files。

---

# 25. Optional dependency boundary

## Core

不依赖：

```text
LangMem
Postgres
Mem0
SimpleMem
local model assets
```

## Foundation

包含：

```text
LangGraph
LangMem
checkpoint
application adapters
```

## External

包含：

```text
Mem0
SimpleMem
```

## Local artifacts

只用于：

```text
tokenizer
private frozen traces
local benchmark assets
```

不得用 broad skip 隐藏缺失依赖。

---

# 26. `application/` 后续小优化

PR #74 已经足够好，不应继续大拆。

唯一值得记录的轻微边界：

```text
application/journal.py
    -> harness.contextual_artifacts read_json/write_json
```

如果未来 application 需要完全脱离 experiment harness，可以再提取：

```text
common/json_store.py
```

或：

```text
application/storage.py
```

当前不是最高优先级。

---

# 27. 为 Grounded Memory 预留正确归属

本 v12 不实现语义效果，但架构应预留：

```text
contracts/memory.py
memory/records.py
application/refs.py
```

未来不要把：

```text
Memory schema
business ref
presentation
routing
attention
```

全部继续塞进 `MemoryBoundaryView`。

---

# 28. Semantic / Episodic 的未来边界

未来建议：

```text
contracts/memory.py
  -> MemoryKind

memory/records.py
  -> canonical record serialization

method
  -> formation algorithm

memory/presentation.py
  -> model-facing rendering
```

即：

```text
data model
!= formation algorithm
!= presentation algorithm
```

---

# 29. Verified Object Ref 的未来归属

未来：

```text
application/refs.py
```

负责：

```text
actual object identity
owner
actual source
version / expiry
```

Memory 只引用它。

Memory service 不负责自行判断业务对象是否真实。

---

# 30. Benchmark layer

建议新增 canonical `benchmarks/`。

负责：

```text
official benchmark input conversion
native reader contract
native scorer boundary
selection/freeze metadata
```

不持有 research method。

方法由 runner 选择和组合。

---

# 31. External baseline identity

Mem0 / SimpleMem 迁移后继续保留：

```text
source commit
dependency versions
source hashes
ambient setting verification
provider substitution identity
```

目录移动不得改变 upstream semantics。

---

# 32. Verification matrix 更新

保留现有：

```text
Core
Foundation
External
Local artifacts
```

增加 source owner 标签：

```text
contracts
application
memory
provider
integration
method
benchmark
runner
```

每个 active source prefix 必须映射到至少一个 CI group。

---

# 33. 文档治理

更新：

```text
LAB_ARCHITECTURE.md
PROJECT_MAP.md
LAB_CURRENT_STATUS.md
README.md
```

建议新增：

```text
CODE_OWNERSHIP.md
DEPENDENCY_RULES.md
HISTORICAL_CODE_INDEX.md
```

---

# 34. `AGENTS.md` 整理建议

当前 `AGENTS.md` 保留了大量历史授权快照，证据价值高，但日常阅读成本很高。

建议未来拆分：

```text
AGENTS.md
    -> current operating constraints only

docs/agent-history/
    -> historical authorization snapshots
```

前提：

- 原历史字节保存；
- 当前授权优先规则不变；
- 不删除证据；
- 不在同一代码 PR 中同时修改实验语义。

---

# 35. 本轮明确不处理的内容

v12 不处理：

- R2 Grounded Memory 实验效果；
- Semantic/Episodic benchmark；
- State–Attention 算法；
- SimpleMem budget；
- assistant label 默认切换；
- Product；
- 历史 v17-v27 method 重写；
- Archive 迁移；
- 全量 benchmark rerun。

---

# 36. PR / Commit 组织

建议：

## PR-A

```text
contracts + request canonicalization
```

## PR-B

```text
memory core extraction
```

## PR-C

```text
external integration extraction
```

## PR-D

```text
benchmark common + runner import cleanup
```

## PR-E

```text
generic provider pipeline
```

## PR-F

```text
runner split + boundary/type/docs
```

如果团队更希望一个 PR，也必须按 commit group 保持上述边界。

---

# 37. 每阶段最低验收

### Static

```text
Ruff
mypy relevant group
boundary checker
verification matrix
```

### Behavior

```text
existing unit tests
same-object imports
golden schemas/receipts
wire replay where relevant
```

### Packaging

涉及 module move：

```text
sdist
wheel
isolated installed import
```

### Experiment

默认：

```text
0 Host calls
0 embedding calls
0 Judge calls
```

---

# 38. Golden contracts

必须冻结：

```text
Memory MCP schemas
strict CRUD ToolMessages
business schemas
business receipts
journal JSON
SQLite schema
RequestContext render
JSON/native wire
capacity counts
benchmark manifest shape
source identity
```

Golden 只证明行为保持。

如果旧行为是失败，整理后仍应保持该失败。

---

# 39. 完成判据

v12 完成时要求：

1. `application/` 无 runner import；
2. provider 无具体 method import；
3. shared baseline code 无 runner import；
4. Mem0/SimpleMem canonical owner 不在 runner；
5. runner 不通过另一个 runner 获得公共 lifecycle；
6. Request / Memory shared DTO 有 canonical contracts；
7. Memory service canonical path 明确；
8. old paths 为纯 compatibility facade；
9. canonical sources 被 identity hash；
10. package dependency DAG 有自动 CI；
11. active canonical modules type coverage 提高；
12. request/tool/store/on-disk contracts 不变；
13. affected Fast CI 通过；
14. 0 新语义实验调用；
15. v10/R2 失败和连续成本不变。

---

# 40. 完成后的研究代码入口

完成结构整理后：

## Grounded Memory

进入：

```text
contracts/memory.py
memory/records.py
application/refs.py
```

而不是继续分散到 runner / strict tool / boundary。

## State–Attention

继续留：

```text
methods/local_state_attention/
```

只消费 canonical Memory / application refs。

不拥有第二套 business truth。

---

# 41. 最终整理原则

> **把可复用能力从 runner 和 baseline 中下沉；把研究变量留在 methods；把实验顺序留在 runners；把模型协议留在 providers；把外部 SDK 留在 integrations；把跨层数据结构留在 contracts；再用 CI 保证这些边界不会反转。**

PR #74 已完成 application core 的第一步。

v12 应将同一原则扩展到：

```text
Memory core
External integrations
Provider pipeline
Benchmark harness
Runner orchestration
```

这样后续继续开发 Grounded Memory、Semantic/Episodic Memory 和 State–Attention 时，新增研究逻辑不会再次污染业务执行、Provider 或 benchmark 基础设施。
