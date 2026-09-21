# MiLAi 代码整理加速执行 Goal v2.0

## 1. Goal 身份

```text
Goal ID:                    MILAI-CODEBASE-CLEANUP-V2
Goal 类型:                  behavior-preserving cleanup / bounded modularization
执行状态:                   ACTIVE — 用户已于 2026-09-21 明确恢复
前置合同:                   MiLAi 全仓代码整理与模块化重构执行总指令 v1.0
本版作用:                   优化执行节奏、验证分级、CI 触发与剩余 PR 边界
当前阶段:                   C5 OpenWorker Host final candidate
当前候选分支:               cleanup/c5-openworker-host-final
最近权威 full workflow:     Run #57 / 17 jobs success / composition PASS
当前 base main:             0bd5ed414bd11ef8841025b5177f7b79f6e92a00
```

本 Goal 不推翻 v1.0 的行为保持、Source of Truth、Frozen Architecture、历史证据和完成定义。
如两份文档发生冲突：

```text
行为与安全边界      → v1.0 优先
执行节奏与测试频率  → 本 Goal v2.0 优先
```

恢复执行必须由用户明确发出恢复指令。文档改写本身不恢复 cleanup、不合并 PR、不触发 CI。

---

## 2. 核心目标

在不减少安全覆盖、不改变 Product/Lab/Archive 行为合同的前提下，将剩余 cleanup 从：

```text
小范围改动
→ 频繁 push
→ 每次完整 17-job composition
→ merge 后重复完整验证
```

改为：

```text
一个 subsystem
    ↓
多个本地、可审查的小 commit
    ↓
每个 commit 只运行高相关验证
    ↓
subsystem 本地 pre-push gate 一次
    ↓
只 push 最终候选
    ↓
远端 fast PR gate
    ↓
subsystem 收口时 full composition 一次
    ↓
验证树身份后 merge
```

最终目标不是少测试，而是：

> 将高相关验证前移到本地，将全仓组合验证降为低频最终证明，停止使用 GitHub CI 作为开发循环。

---

## 3. 成功结果

本 Goal 完成时应同时得到：

1. Retrieval、Memory Context、MCP Server、OpenWorker Host 均形成清晰的内部责任 seam；
2. 所有 public import、MCP tool/schema、CLI、HTTP、DB 与实验合同保持兼容；
3. Lab 大型 active runner 开始 thin-runner 化，复杂实现进入 `src/milai_lab/`；
4. receipt 引用的 pytest node ID 与所有历史 diagnosis/remediation receipt 保持不变；
5. cleanup 开发循环由本地 targeted gate 驱动，远端 CI 支持 fast/full 分流；
6. 相同 merge tree 不再重复执行完整 post-merge replay；
7. 五项已修复 TECH_DEBT 在最终 Product tree 重新产生 current-tree execution receipt；
8. 最终全仓 17-job composition 实际执行并 PASS；
9. `main == origin/main`，working tree clean，最终身份和模块图已记录。

---

## 4. 不可违反的边界

整个 Goal 必须保持：

```text
architecture/v1.0/**                    IMMUTABLE
Product / Lab / Artifact-Archive        TOP-LEVEL BOUNDARY IMMUTABLE
public Runtime API                      BEHAVIOR IMMUTABLE
MCP tool names / schemas                IMMUTABLE
CLI / HTTP contracts                    IMMUTABLE
DB schema / migrations                  NO CHANGE
retrieval route / ranking / thresholds  NO CHANGE
Context budget / activation thresholds  NO CHANGE
Prompt / system policy                  NO CHANGE
authority / scope / permission          NO CHANGE
token / confirmation semantics          NO CHANGE
Lab experimental treatment              NO CHANGE
sealed fixtures / labels / configs      NO BYTE CHANGE
historical receipts                     NO REWRITE
studies/archive/**                       NO CHANGE
Artifact Archive historical bytes       NO CHANGE
```

禁止：

- 为让结构 PR 通过而修改业务行为；
- 删除 receipt-referenced、安全负向、跨租户、撤销、确认、防重放、持久化或历史 replay 测试；
- 将 Lab 方法推进 Product；
- 用历史 Product tree receipt 冒充当前 tree evidence；
- 因文件尺寸目标进行无边界的大规模重写；
- 在一个 PR 同时修改两个大型 production subsystem；
- 写一点、push 一次、等待 CI、再继续调试。

发现真实行为缺陷时：

```text
STOP STRUCTURAL WORK
→ 保存复现证据
→ 登记 TECH_DEBT / issue
→ 当前 cleanup 保持行为不变
→ 独立 behavior Goal / PR
```

---

## 5. 当前权威断点

阶段状态：

| Phase | Scope | Status |
| --- | --- | --- |
| C0 | Baseline + inventory | COMPLETE |
| C1 | Safe hygiene | COMPLETE |
| C2 | Runtime Retrieval modularization | COMPLETE |
| C3 | Runtime Memory Context modularization | COMPLETE — PR #19 merged; fast PR and main identity PASS |
| C4 | MCP Server modularization | COMPLETE — PR #20 merged; fast PR and main identity PASS |
| C5 | OpenWorker Host modularization | IN PROGRESS — implementation complete; candidate validation |
| C6 | Test organization | PENDING |
| C7 | Lab active code organization | PENDING |
| C8 | Compatibility/dead-code audit | PENDING |
| C9 | Current-tree evidence refresh | PENDING |
| C10 | Final cleanup baseline | PENDING |

PR #17 已完成并合并 Memory Context foundation：

```text
common
contracts
provenance
semantics
units
```

合并前权威远端状态：

```text
Run #55       17/17 SUCCESS
composition   PASS
mergeable     true
PR base       77ef5be43c05016d122a128144f635b130b8dc2d
```

恢复 reconciliation 已于 2026-09-21 完成：PR #17 的 tested HEAD 被严格 fast-forward 到
`main`，GitHub 确认 closed/merged；merged commit/tree 与 Run #55 被测对象完全一致。

---

## 6. 恢复门槛

收到明确恢复指令后，第一轮只做只读 reconciliation：

```text
1. PR #17 仍 open
2. Run #55 conclusion == success
3. composition 实际执行且 PASS
4. PR base 仍为 77ef5be...
5. mergeable == true
6. origin/main 未出现未纳入测试的新提交
7. local candidate 与 remote PR HEAD 一致
8. Product manifest / Conformance freshness 可验证
```

全部成立后：

```text
merge PR #17
→ 记录 merged main SHA
→ 验证 merged tree 与 Run #55 tested tree 等价
→ sync local main
```

若 merge tree 与已验证 candidate tree 相同，不再等待一轮重复的 post-merge 17-job full
composition；只运行 tree identity、manifest、boundary 与 Conformance freshness 检查。

任一条件不成立时停止合并，先更新断点报告。

---

## 7. 五级验证模型

### L0 — 编辑循环

目的：数秒到数十秒发现语法、import、搬运或直接行为错误。

只运行：

```text
changed-file Ruff
import smoke
AST / constant equivalence
facade object identity
1–5 个直接相关测试
```

禁止运行 full Runtime、Lab、所有 integrations、Archive deep validation 或 historical replay。

### L1 — 本地 commit gate

每个逻辑 extraction commit 前必须通过：

```text
affected compatibility tests
affected behavior tests
Ruff changed scope
```

通过后才允许本地 commit。L1 commit 不立即 push。

### L2 — 本地 subsystem pre-push gate

一个 subsystem 完成后只执行一次：

```text
full relevant unit/contract suite
Ruff package scope
strict mypy
package build
contract/distribution snapshot
Product manifest
repository boundary
receipt verifier
Conformance verifier
```

只有存在直接数据库风险且本地 PostgreSQL 可用时，增加少量明确相关 integration nodes。

L2 全部通过后，才允许 push 最终 branch candidate。

### L3 — 远端 fast PR gate

普通结构 PR 默认执行：

```text
boundaries
Product identity
Conformance
affected package
affected contract smoke
```

不默认执行四个 historical replay、无关 integrations、完整 Lab 或 Archive deep validation。

### L4 — Full composition

仅在以下事件执行完整 17 jobs：

```text
subsystem final candidate
behavior contract change
CI cadence infrastructure candidate
C9 evidence refresh
C10 final baseline
nightly / release candidate
```

同一 tested tree 只需要一份权威 full-composition 结果。

---

## 8. 测试执行规则

### 8.1 开发和 pre-push 不重复覆盖

开发阶段运行 targeted tests；pre-push 直接运行 full relevant unit/contract suite。

禁止在同一 pre-push gate 连续执行：

```text
targeted tests
→ full unit suite containing the same tests
```

### 8.2 Runtime unit gate 使用明确目录

不得再使用：

```bash
pytest -m 'not integration'
```

本地 Runtime unit gate 使用：

```bash
pytest tests/unit tests/contract
```

原因：`tests/integration/` 中未标记模块可能绕过 marker expression 并要求 PostgreSQL。

### 8.3 Integration marker contract

PR #18 必须：

1. 为 `tests/integration/test_host_notes.py` 增加 module-level integration marker；
2. 增加 collection/contract test，要求 `tests/integration/` 下所有测试模块均具有明确 integration
   marker；
3. 不改变测试节点名称和业务断言。

### 8.4 测试去重条件

两个测试只有同时满足以下条件才可合并或降低执行频率：

```text
same behavior statement
same input class
same failure boundary
same execution layer
same evidence value
```

unit fail-closed 与 PostgreSQL authoritative integration 不属于重复测试。

### 8.5 必须保留的测试

```text
receipt-referenced tests
security negative tests
cross-tenant isolation
revocation and purge
confirmation replay
capsule lifecycle
blob durability
projection rebuild
HTTP ingress exposure
canonical gate
historical replay fixtures
```

允许减少的是运行频率与重复环境，不是安全覆盖。

---

## 9. CI 加速交付物

在继续 C3 final 前，先完成独立 CI/test cadence PR。

### 9.1 Change classifier

增加 paths/change classification job，至少输出：

```text
runtime
mcp
openworker
python-client
hooks
langgraph
autogen
lab
archive
full_required
```

### 9.2 Fast PR workflow

按影响范围选择：

| PR scope | Required fast jobs |
| --- | --- |
| Runtime-only structural | boundaries, identity, Conformance, Runtime |
| MCP | boundaries, identity, Conformance, MCP；必要时 python-client |
| OpenWorker | boundaries, identity, Conformance, openworker-mcp |
| Lab | boundaries, Lab fast |
| Archive | boundaries, Archive validation |
| Cross-subsystem/behavior | full_required=true |

MCP/OpenWorker import smoke 可作为 Runtime-only PR 的小型 contract smoke，但不得隐式升级成
所有 integrations full run。

### 9.3 Full candidate workflow

提供显式 full-composition 入口，可采用：

```text
workflow_dispatch
或
PR label: full-composition
```

合并前流程：

```text
L2 pre-push PASS
→ push final candidate once
→ L3 fast PR PASS
→ trigger L4 full composition once
→ 17 jobs PASS
→ merge
```

### 9.4 Main push workflow

当 merged tree 与 tested PR tree 相同时，main push 只执行：

```text
tree identity
Product manifest
boundary
Conformance freshness
```

完整 main replay 转移到 nightly、manual 与 release workflow。

### 9.5 本地统一验证入口

新增：

```text
MiLAi-Product/tools/cleanup_validate.py
MiLAi-Product/docs/cleanup/validation-profiles.json
```

至少支持：

```bash
python tools/cleanup_validate.py memory-context --level dev
python tools/cleanup_validate.py memory-context --level prepush
python tools/cleanup_validate.py mcp --level dev
python tools/cleanup_validate.py mcp --level prepush
python tools/cleanup_validate.py openworker --level prepush
python tools/cleanup_validate.py lab --level prepush
```

每个 profile 必须机器可读地定义 changed paths、Ruff、mypy、tests、integration requirement、
build、manifest 与 boundary。

该工具只编排已有命令，不引入 Runtime dependency，不隐式扩大测试范围。

---

## 10. C3 — Memory Context final

### 10.1 目标

在 PR #17 foundation 之上完成：

```text
activation
Evidence views
adjacency windows
ordering
rendering and fitting
receipts
trace projection
MemoryContextCompiler relocation
facade compatibility
```

只保留一个剩余 C3 PR：

```text
cleanup/c3-memory-context-final
```

### 10.2 本地 commit 边界

```text
commit 1  activation + Evidence views
commit 2  windows + ordering
commit 3  rendering + fitting
commit 4  receipts + trace projection
commit 5  compiler relocation + facade compatibility
commit 6  docs + module map + Product identity
```

这些 commit 只作为本地 checkpoint；全部完成并通过 L2 后才 push。

### 10.3 定向验证

| Commit scope | Direct tests |
| --- | --- |
| activation/views | `test_dg17_memory_context`, `test_dg18_context_expansion`, compatibility |
| windows/order | `test_dg18_context_expansion`, `test_dg18_context_packing`, `test_context_excerpt_focus`, compatibility |
| rendering/fitting | `test_dg17_memory_context`, `test_dg18_context_packing`, `test_context_excerpt_focus` |
| receipt/compiler | `test_dg17_memory_context`, `test_memory_resolve`, compatibility, relevant Context contracts |

### 10.4 验收条件

- `memory_context.py` 继续提供所有原 import；
- `_reader_semantic_value` 与 `_order_windows` 兼容入口保持；
- Context bytes、budget、threshold、ordering key、receipt mapping 与 token accounting 不变；
- moved definitions 具备 AST/global/default/constant equivalence evidence；
- L2 PASS；
- L3 fast PR PASS；
- 一次 L4 full composition PASS。

### 10.5 2026-09-21 执行记录

`cleanup/c3-memory-context-final` 已按六段本地边界完成前五段实现：

```text
1d2a24d  activation + Evidence views
8e53223  windows + ordering
87171f4  rendering + fitting
7471c3c  receipts + trace projection
c6d56a1  compiler relocation + facade compatibility
```

当前结构结果：

```text
memory_context.py                 3716 → 268 lines
memory_context_core/compiler.py   orchestration implementation
memory_context_core/activation.py activation and Evidence views
memory_context_core/windows.py    window construction and ordering
memory_context_core/rendering.py  serialization and fitting
memory_context_core/receipts.py   receipt projections
memory_context_core/trace.py      lifecycle trace projections
```

五段 L1 均已通过对应定向用例、changed-scope Ruff 与 strict mypy。对 base
`f57cdcf043f81e945b35046913cc7a1df6455777` 的本地 AST/constant 比对覆盖 54 个定义与
10 个常量，兼容调用名归一化后 mismatch 均为 0。详细责任与兼容边界见
`MEMORY_CONTEXT_MODULE_MAP.md`。

按用户对耗时验证的明确要求，本候选不在本地编辑循环或纯结构提交上运行 historical
replay；只执行一次 memory-context L2 pre-push 与远端 fast PR gate。L4 是否升级留到最终
候选或出现真实 behavior-path 风险时决定，不将约 35 分钟回放作为每次结构 PR 的默认门槛。

PR #19 已经 fast PR gate PASS 后 squash merge 为
`43a2c6a031cbe79a5f34dd835de60c6e3fc9cec3`。候选 tree 与 merge tree 均为
`bc0141db4429e4467e5c9388a185274da5e62c98`；main push fast identity gate 亦 PASS，因此没有对
同一 tree 重复运行 full composition。

---

## 11. C4 — MCP Server modularization

使用一个 subsystem PR、多个本地 commit：

```text
1 models + middleware
2 wire + compact serialization
3 reader toolset
4 governance + working-state toolsets
5 codex-full
6 factory + CLI + facade
```

必须保持：

```text
server.py import path
build_server()
main
tool names
tool annotations
JSON schemas
profile catalog
wire size and error codes
authorization behavior
```

开发只运行相邻 tests；L2 才运行完整 MCP package 一次。HTTP/OAuth 测试仅在对应代码发生
变化时加入 targeted gate。最终执行一次 L4 full composition。

### 11.1 2026-09-21 执行记录

`cleanup/c4-mcp-server-final` 已按六段本地实现边界完成：

```text
9df765f  models/contracts + middleware
2249cad  wire + compact serialization
aba4413  reader toolset
222b3cd  governance + working-state toolsets
191c5ca  codex-full governance toolsets
425793d  factory + CLI + facade
0457032  clean-environment CLI facade compatibility correction
```

当前结构结果：

```text
server.py              4145 → 122 lines (compatibility facade)
server_contracts.py    profiles, catalogs, annotations and typed inputs
server_middleware.py   strict arguments, token binding and request middleware
server_wire.py         bounded wire serialization and resolve compaction
server_reader.py       Reader tools and access policy projection
server_governance.py   identity, mutation and Working State tools
server_codex.py        Codex-full submitter/reviewer/operator tools
server_factory.py      assembly, transport and CLI
```

六段 L1 均已通过对应定向用例、changed-scope Ruff 与 strict mypy。对 base
`43a2c6a031cbe79a5f34dd835de60c6e3fc9cec3` 的递归 AST/constant 比对覆盖基线全部 104 个
class/function 定义：102 个逐 AST 完全一致，0 个名称丢失；仅 `build_server` 与 `main` 因装配
边界变化而结构不同。15 个共享顶层 assignment 中 14 个完全一致；`_LOGGER` 显式固定为原有
运行时名称 `milai_mcp.server`。详细责任与兼容边界见 `MCP_SERVER_MODULE_MAP.md`。

按用户对耗时验证的明确要求，本候选只执行一次 MCP L2 pre-push 与远端 fast PR gate；不在
该纯结构 PR 上执行约 35 分钟 historical/full composition。完整回放保留到 C9/C10 最终候选，
或仅在出现真实 behavior-path 风险时升级。

PR #20 的最终候选 `1af1fbb2d02795178a87ed8f81508af9ccc8746c` 已通过 fast run
`35619186995` 并 squash merge 为 `0bd5ed414bd11ef8841025b5177f7b79f6e92a00`。候选 tree 与
merge tree 均为 `b93e860726592fe2fb502bd2f48a536c5d731f66`；main push run
`35619423565` 的 tested-tree identity、manifest、boundary、Conformance 与总 gate 全部 PASS。
full-composition workflow 按范围正确 skipped。

---

## 12. C5 — OpenWorker Host modularization

使用一个 subsystem PR、多个本地 commit：

```text
1 request contract
2 ingress
3 tool compatibility
4 task state
5 memory flow
6 provider bridge
7 trace
8 orchestrator facade
```

定向测试责任：

| Scope | Direct tests |
| --- | --- |
| ingress | HTTP exposure revalidation + relevant Host HTTP tests |
| task | task binding |
| memory | memory facade + controller |
| provider | provider execution + completion capture |
| transport | transport + broker + relay |

必须保持 PR #4 的 explicit-local-address ingress contract、Bearer auth、auth-before-parse、
process-lifetime token、task lifecycle、cache reuse、memory-required barrier、provider ordering、
settlement 与 trace privacy。L2 才运行完整 `openworker-mcp` package 一次；最终执行一次 L4。

### 12.1 2026-09-21 执行记录

`cleanup/c5-openworker-host-final` 已完成全部 implementation extraction checkpoint：

```text
b810284  request contract
cafa1bb  ingress contracts
06c2a4b  ordinary tool compatibility and SSE wire adaptation
d4a8df7  task state
a4690e4  memory flow
65c0a37  payload-free trace projections
a83ef6f  provider bridge + thin HTTP/CLI orchestrator
```

当前 `host_adapter.py` 继续作为 27 行历史兼容门面；核心 `host/orchestrator.py` 已从 3,735 行
降至 415 行。最终递归 AST 比对覆盖基线全部 81 个 class/function 定义：80 个逐 AST 完全
一致，0 个名称丢失；唯一 class container 差异是 `OpenWorkerProviderAdapter` 继承内部
`HostTaskState`，所有原方法分别保持 AST-identical。request、HTTP exposure/auth-before-parse、
startup policy、ordinary-tool/vLLM streaming、task binding/cache reuse、memory facade/controller、
provider/completion 与 trace privacy 定向测试均 PASS；每段 Ruff 与 strict mypy PASS。详细责任与
兼容边界见 `OPENWORKER_HOST_MODULE_MAP.md`。本分支尚未 push，下一步只执行一次 OpenWorker
L2 pre-push 与远端 fast PR gate，不运行 historical/full composition。

---

## 13. C6 — Test organization

C6 只整理测试结构，不修改 Product behavior。

开发 gate：

```text
pytest --collect-only
receipt node inventory
wrapper identity
Ruff
affected tests
```

任何 receipt-referenced node ID 必须继续由原路径/函数 wrapper 提供。不得因为移动 test、抽
fixture 或建立 `tests/support/` 而运行 historical behavior benchmark。

本阶段同时建立显式 compatibility registry：

```text
PUBLIC_API
PUBLIC_COMPAT
TEST_COMPAT
HISTORICAL_COMPAT
INTERNAL_TEMPORARY
```

---

## 14. C7 — Lab active code organization

逐步将大型 active runner 改为：

```text
tools/run_x.py                 argparse / config / exit only
src/milai_lab/runners/x.py     typed reusable implementation
```

每个 runner 迁移只运行：

```text
runner direct tests
Lab boundary
tools boundary
Ruff
mypy new package
```

全部 runner 收口后运行一次 Lab fast；historical replay 只在 C7 final candidate 的 L4 执行。

禁止修改 seed、dataset ordering、arms、prompt、budget、provider、output schema、metrics、sealed
fixtures 和 `studies/archive/**`。

---

## 15. C8 — Compatibility 与 dead-code closure

主要证据：

```text
AST/import inventory
git grep
module graph
pytest --collect-only
entrypoint inventory
receipt references
Lab dependency inventory
```

只有同时满足以下条件才允许删除：

```text
category == INTERNAL_TEMPORARY
no production consumer
no test consumer
no CLI/plugin entrypoint
no Lab consumer
no receipt/archive dependency
direct affected tests PASS
```

本阶段不默认运行 Runtime PostgreSQL full suite、Lab full 或 historical replay。

---

## 16. C9 — Current-tree evidence refresh

所有结构改动结束后固定一个 Product candidate tree，重新执行五项已修复行为：

```text
projection purge/rebuild
CAS blob-first orphan
confirmation binding
validation/capsule lifecycle
OpenWorker HTTP auth/exposure
```

每项新增：

```text
post-cleanup.receipt.json
```

不得覆盖 diagnosis/remediation receipt，不得扩大原 claim：

```text
SCOPED remains SCOPED
COMPLETE remains COMPLETE only when the complete contract reruns
```

---

## 17. C10 — Final cleanup baseline

生成：

```text
docs/cleanup/CODEBASE_CLEANUP_RESULTS_v1.md
docs/cleanup/final-module-map.json
docs/cleanup/final-cleanup-baseline.json
```

记录：

```text
baseline commit / final commit
before/after hotspot size
new internal packages
public/compat import preservation
deleted code with evidence
receipt node preservation
Lab runner migration
current receipt coverage
Product tree SHA
Product manifest SHA
full CI run ID
```

C10 执行最终权威验证：

```text
Runtime full + PostgreSQL
all integrations
Lab fast
4 historical replay shards
Archive
Product identity
Conformance
composition
```

---

## 18. PR 路线

目标路线约八个剩余 PR：

```text
PR #17  C3 foundation                         已验证并合并
PR #18  CI/test cadence optimization          已验证并合并
PR #19  C3 Memory Context final               已验证并合并
PR #20  C4 MCP Server complete modularization 已验证并合并
PR #21  C5 OpenWorker Host complete modularization 本地开发中
PR #22  C6 test organization + compatibility registry
PR #23  C7 Lab active runner organization
PR #24  C8 dead-code / compatibility closure
PR #25  C9 + C10 evidence refresh/final baseline
```

编号是当前规划，不是硬编码依赖；若 GitHub 实际编号变化，以 scope 和 evidence identity 为准。

预计最多执行约六次新的 full composition：

```text
CI cadence candidate
C3 final
C4 MCP final
C5 OpenWorker final
C7 Lab final
C9/C10 final
```

C6/C8 仅在影响真实 behavior path 或 final candidate 需要时升级到 L4。

---

## 19. Commit / push / merge 纪律

### 本地开发

```text
modify
→ L0/L1 targeted validation
→ local commit
→ continue locally
```

### Subsystem candidate

```text
all local commits complete
→ L2 once
→ working tree clean
→ fetch/reconcile main
→ push final candidate once
```

### 远端

```text
L3 fast PR PASS
→ L4 once when required
→ base/mergeability/tree identity check
→ merge
```

禁止用新增 commit 修改已进入 L4 的 candidate tree；如必须修改，该 L4 结果自动历史化，新的
HEAD 必须重新验证。

---

## 20. 停止条件

出现以下任一情况必须暂停当前结构 PR：

- public import、wire/schema、CLI/HTTP、Context bytes 或 receipt output 发生非预期变化；
- AST-identical extraction 产生 global/default/constant resolution drift；
- 需要改 threshold、budget、policy、prompt 或 lifecycle 才能继续；
- receipt node ID 丢失；
- Lab 开始依赖 Product private implementation；
- Frozen Architecture、sealed fixture 或 historical receipt 出现 diff；
- Product manifest 无法由 generator 重建；
- CI fast/full classification 可能跳过受影响安全边界；
- merge base 漂移导致 tested tree 不再等于待合并 tree。

暂停时必须生成进度报告，记录 exact commit、Product tree、已完成验证、未完成 gate 与恢复步骤。

---

## 21. 完成定义

只有以下全部成立，本 Goal 才可标记 `COMPLETE`：

```text
[ ] PR #17 已按 tested-tree identity 安全合并
[ ] fast/full CI 与 validation profiles 已落地并验证
[ ] Runtime integration marker contract 已建立

[ ] C3 Memory Context 完成
[ ] C4 MCP Server 完成
[ ] C5 OpenWorker Host 完成
[ ] C6 test organization 完成
[ ] C7 Lab active runner organization 完成
[ ] C8 compatibility/dead-code audit 完成

[ ] public Runtime imports 保持
[ ] MCP tool/schema 保持
[ ] CLI/HTTP contracts 保持
[ ] DB schema/migrations 未改变
[ ] receipt-referenced node IDs 保持
[ ] Frozen Architecture 未修改
[ ] Lab archive/sealed bytes 未修改
[ ] historical receipts 未改写

[ ] 五项 FIXED TECH_DEBT 已在最终 Product tree 重跑
[ ] current-tree post-cleanup receipts 已生成
[ ] Conformance claim 未人为扩大

[ ] Runtime full PASS
[ ] all integrations PASS
[ ] Lab fast PASS
[ ] four historical replay shards PASS
[ ] Archive PASS
[ ] Product identity PASS
[ ] Conformance verifier PASS
[ ] final composition 实际执行并 PASS

[ ] cleanup result/module map/final baseline 已生成
[ ] main == origin/main
[ ] working tree clean
```

---

## 22. 最终执行原则

每次决定是否运行一项验证时，必须回答：

> 这项验证能否发现本次改动可能造成的真实回归？

最终模型：

```text
Local                 high relevance / high frequency / fast
PR fast               cross-environment / affected subsystem
Full composition      low frequency / high coverage
Historical replay     subsystem milestone / nightly / final
```

执行顺序始终是：

```text
先证明边界
→ 本地移动代码
→ 保持兼容入口
→ 运行高相关验证
→ subsystem 一次 pre-push
→ final candidate 一次 full composition
→ 验证 tree identity 后 merge
→ 最终统一刷新 behavior evidence
```

本 Goal 的成功标准不是“CI 跑得更少”，而是：

> 在保持 MiLAi 安全、行为与研究证据纪律的前提下，以更少的重复验证完成同等或更强的工程证明。
