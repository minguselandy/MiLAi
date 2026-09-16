---
document_id: MILA-PRODUCT-04
version: "1.1"
status: COMPLETE
created_at: "2026-09-02T18:44:08+08:00"
parent: MILA-PRODUCT-GOALS@1.5
predecessor: MILA-PRODUCT-03
execution_authorized: true
formal_holdout_authorized: false
schema_change_authorized: false
public_api_change_authorized: false
database_migration_authorized: false
---

# MILA-PRODUCT-04：Query 规划归一化与 Reader 可用性

## 1. Goal

Product-03 已证明真实 OpenWorker → MCP → Runtime → Qwen 链路可用。
Product-04 最初尝试用 TypeBinding 把自然语言关系变成执行权威，但回归表明这会
持续累积动词、介词、词序和 actor 规则，无法泛化。本修订正式撤回该路线。

本 Goal 建立一条简单、可用、可泛化的读取前端：

```text
user query
→ QueryTaskContractV01       # 内部规划描述
→ QueryExecutionPlanV01      # 机械执行投影
→ MemoryQueryIRV02           # 现有路径兼容投影
→ official acquisition / Governance
→ Memory Availability
    ├─ Raw natural language → Qwen Reader
    └─ externally verified structured operand → deterministic Operator
```

优先完成普通记忆查询的可用性：有合法 Evidence 就可以调用 Reader，不必先把自然语言
证明为 typed `COMPLETE`。当前自然语言 compiler 不提供 strict operand；未来只有显式
Canonical mapping、可验证 projection 或 typed-tool 输入才能进入该边界。
不引入自治搜索 Agent、新数据库对象或 benchmark-specific 规则。

## 2. 规划合同与权威边界

`QueryTaskContractV01` 只表达：

```text
parse disposition
operation
output type
evidence topology
显式 source/time 约束与非权威 retrieval hints
temporal contract
requirements
operator operands
proof obligations
```

必须保持：

- QueryIR 表达用户想做什么，不证明 Raw Evidence 说了什么；
- `RetrievalHintsV01` 只影响候选发现，不定义 Binding 或完成性；
- `EXECUTABLE` 表示合同可执行，不表示 Evidence 已齐备；
- `BEST_EFFORT_RECALL` 是无法安全规范化的 memory query 通用降级，仍可进入 Reader；
- `UNSUPPORTED` 只用于空/非法输入，不得用于阻止合法记忆问题；
- 显式 source 限制是硬约束，自然语言中的 assistant/user 归因默认只是可校验偏好；
- Raw prose、regex interpretation 和手写 TypeBinding 都不能成为 deterministic operand；
- memory availability 与 completion 独立；`PARTIAL/UNSATISFIED` 不等于没有可用 Context；
- query reference time 是 Runtime operand，不得伪造为第二条 Evidence requirement。

## 3. 实施范围

### Q0 — Domain contract

- 实现 `QueryTaskContractV01`、query shape、explicit constraints 和 retrieval hints；
- 明确 planning descriptor 不是 Raw-language semantic authority；
- 使用通用 invariant，不加 case ID、gold answer、sealed quote 或领域词表。

### Q1 — Compatibility integration

- `MemoryQueryCompiler` 先编译 contract，再机械投影为现有 V02/plan；
- Planner 和 acquisition 共享 contract lineage，但 Binding/Operator 不得把该 lineage
  当成 Raw 语义证明；
- 保持 public request/response JSON、MCP contract 和 PostgreSQL Schema 不变。

### Q2 — Generality and correctness

使用不同表面词、句式和语义族检查：

```text
ordinary attribute lookup
assistant-provided information recall
scalar count
member-set count
multi-operand comparison
event/time lookup
query-reference temporal distance
unknown memory computation → best-effort Reader recall
```

同一任务族应投影为相同规划形状；表面词只能改变 retrieval hints，不得
成为 evidence acceptance 或 operator authority。

### Q3 — Product usability confirmation

在不消费 formal 500-case holdout 的前提下，使用合成/去标识和已打开的诊断族检查：

```text
ordinary/ambiguous lookup 只要存在受治理 Evidence 就能进入 Qwen Context
source-role 语义不再被误当作 Evidence speaker 真值
Raw prose 在任何措辞下都不产生 strict Operator/COMPLETE
member-set COUNT 只在 identity/dedup/closure 成立后执行
```

真实 OpenWorker replay 若未运行，本 Goal 只能声称 contract core 完成，不得声称召回效果已提升。

## 4. 高效失败修复

对可恢复失败执行：

```text
最小失败用例
→ 定位第一个错误语义边界
→ 修复通用合同或投影
→ 增加同族正/反例
→ 重跑 narrow tests
→ 继续后续阶段
```

不为普通解析错误建立新 Goal、失败账本或重复 witness。只在 public I/O、权限、持久化、
Canonical authority 和外部 Provider 边界保留防御性校验。

## 5. Validation

开发顺序：

```text
targeted contract/compiler tests
→ complete Runtime unit suite
→ Ruff
→ strict mypy
→ Runtime build
→ affected real Product path when available
```

数据库集成测试仅在本次实际改动持久化或事务语义时为必需门。本 Goal 不通过扩大
审计代替功能测试。

## 6. 权限与终态

本 Goal 不授权：

```text
public MCP/API shape change
database migration
Canonical authority change
default enablement of WIDE_V02 or experimental retrieval
formal 500-case holdout
production or Schema-freeze claim
```

```yaml
terminal_status: PASS_PRODUCT04_READER_AVAILABILITY_WITHOUT_TYPEBINDING
completed_scope:
  - QueryTaskContractV01 planning descriptor
  - QueryExecutionPlanV01 mechanical projection
  - MemoryQueryIRV02 compatibility integration
  - Raw TypeBinding removed from deterministic operand authority
  - informational memory availability separated from completion
  - progressive acquisition can stop on governed Reader availability without COMPLETE
  - ambiguous and unknown memory queries retain governed Reader access
  - wide Product budget propagation without authority relaxation
test_results:
  runtime_unit: 717 passed
  python_client: 170 passed
  mcp: 54 passed
  openworker_mcp: 112 passed
  runtime_public_serialization: 11 passed
  ruff: PASS
  strict_mypy: PASS (170 Runtime source files; configured integration packages PASS)
  builds: PASS (Runtime, Python Client, MCP, OpenWorker MCP)
  architecture_bundle: PASS (1.0.0 frozen)
product_identity_source: product.manifest.json
product_tree_identity: 04b356531db615de7dcd68af036669ef8d88371013af513b89cd1228aeb13f20
product_tree_file_count: 311
product_manifest_sha256: c1dbf5d0aa940be668d99a5c5e95c2e75611531b6a3898b43eca2b231073959c
public_schema_shape_change: NONE
formal_holdout_consumed: false
remaining_limitations:
  - no Product-04-specific native OpenWorker/Qwen black-box replay; Product-03 remains the latest real replay evidence
  - Raw multi-item/count questions are Reader tasks until a verified structured operand source exists
  - deterministic query grammar remains a planning convenience, not semantic authority
  - WIDE_V02 and experimental retrieval remain default OFF
```

可选终态：

```text
PASS_PRODUCT04_READER_AVAILABILITY_WITHOUT_TYPEBINDING
FAIL_AUTHORITY_OR_PUBLIC_CONTRACT_REGRESSION
```

普通可恢复缺陷不应直接 terminal；修复后继续执行。如 member-set closure 尚未完成，必须在
`remaining_limitations` 中明确保留，不得用“精准召回已完成”概括。

## 7. 实施结论

Product-04 最终关闭了三类通用漂移：

1. QueryIR 统一计划形状，但不再被宣称为自然语言语义真值；
2. ordinary/ambiguous memory query 在受治理 Evidence 存在时会继续到 Qwen，不再因
   TypeBinding 或 strict Sufficiency 失败而变成零 Provider 调用；
3. Raw prose 无论规则或模型解释如何评分，都不能驱动 deterministic Operator 或
   `COMPLETE`；缺少 contract 也不能恢复旧 Raw-match authority。

新回归覆盖 `PARTIAL` 和 `ABSTAINED` soft context 会调用 Provider，而 `DENIED`
和 OpenIssue 仍保持零 Provider 调用。本 Goal 不声称 LongMemEval 准确率或集合计数闭合；
它证明的是一个更简单的产品边界：“可读”不必先被 Runtime 证明为“已完成”。
