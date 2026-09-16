# V0220 Provider 兼容修复：生成语法与业务验收分离

日期：2026-09-11。范围：仅 Lab 前瞻 Provider；不重开旧批、不改共享 vLLM、Product 或 Memory。

## 问题与选择

原四根的完整动作 Schema 中，三根含当前安装后端不支持的 `uniqueItems`。
参数验证拒绝经异常包装变成空消息 HTTP 500。已复现路径不等于追回历史 usage。
不再用小型 finish 样例替代完整合同，也不靠删除业务唯一性约束获得表面通过。

采用显式版本 `UNIQUE_ITEMS_RUNTIME_V1`：

```text
完整公共 Schema（不变，仍呈现给模型）
       ├── 编译生成语法：仅移出 uniqueItems，记录全部 JSON pointer
       └── 保留完整权威校验器
                   ↓
完整语法 CPU 准入 → 历史用量门 → 原始 HTTP/usage 记录
                   ↓
原始输出 → 严格 JSON + 完整公共 Schema 校验 → 原 Session/执行器再次校验
                   ↓
身份 / scope / CAS / 幂等 → 业务效果
```

生成语法的合法集合是原集合的上集，**不是等价 grammar**。
接受动作必须同时通过生成结果解析与原完整 Schema，之后仍受原执行器约束。
这一设计恢复的是业务接受边界，不保证生成分布、成功率或成本不变；未来各比较臂必须共用该版本。

所有 `uniqueItems` 仍在完整公共 Schema 中，并在实际提示里明确呈现。无字段/目标删减，
不改业务值、enum、required、additionalProperties、版本和身份规则；不自动去重/排序/修复。
仅遍历已审阅的正向 Schema 位置，不把同名属性/enum/default/example 当关键字删除。
`not/oneOf/if/$ref/contains/unevaluated*` 等未经证明的组合直接拒绝，不能无声扩大兼容转换范围。

## 实现接线与证据

- `v0220_wire_contract.py`：不可变 canonical/wire 对、转换明细、完整输出校验。
- `v0220_wire_provider.py`：可选 Provider 包装；保留旧 hardened Provider 的账本、请求 ID、无重试和停发。
- `v0220_wire_admission.py`：四根 full/finish 全覆盖，绑定 canonical/wire、请求选项、证据哈希及容器/库状态。
- 新检查器：旧八个请求与新八个请求逐一 CPU 验证；完整正向参考动作及重复项/身份/CAS反例分开记录。

调用点沿用 `Session.run(provider, ...)` 接口，不改冻结 Session、World、Provider、Oracle 数据或判据。
新 Provider 返回原始合法输出；非法输出先记录实际 usage，再停止，不派发业务、不生成隐式修复请求。
HTTP 失败/未知用量仍是独立阻断，即使兼容语法通过也不得绕过。
新增系统说明与完整 Schema 所占字节单列；不删来源、裁剪上下文或伪装成零额外成本。

## 验证范围与恢复限制

本次先执行零生成修复验证：原四根八种完整合同、安装代码参数验证、零副作用语义负控、
Provider→Session→SQLite 的模拟 HTTP 端到端、账本和无重试回归。
CPU 通过不等于 GPU、真实生成、Intent Oracle 或 Memory 通过。历史未知请求不结算为零。

当前“设计并修复”的授权用于实现和这些安全检查，不被解释为放弃历史未知预约、
重启共享服务或自动执行 V2 的 23 条剩余链。真实兼容探针需要独立记录及明确的未知用量处置授权。
保留当前 A0、Schema NO-GO、保护池及 V3–V5 未触发状态。

## 官方接口依据

[vLLM Structured Outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/) 说明
JSON Schema 结构化输出由生成后端处理；具体兼容结论以本机冻结安装代码和原八份完整合同为准，
不把最新版文档当作本机兼容通过。业务验收仍使用既有 JSON Schema 2020-12 校验器及原执行器。

## 接线示意与本次验证

以下是后续已授权新批的接线形态，不是恢复旧 V2 的运行命令：

```python
gate = WireSchemaAdmission(
    matrix_path,
    hashes=frozen_batch["matrix_hashes"],
    identity=lambda: backend_identity(frozen_batch["container"]),
)
provider = WireProvider(
    new_batch_path,
    deadline=deadline,
    max_requests=frozen_batch["max_requests"],
    historical_ledgers=historical_ledgers,
    admission=gate,
)
# The existing Session.run(provider, deadline=...) interface can consume this provider.
# Unsettled historical usage still stops before tokenize/completions.
```

实际使用应从 `v0220_wire_admission` 导入 `WireSchemaAdmission/backend_identity`，
从 `v0220_wire_provider` 导入 `WireProvider`。哈希、容器、deadline、次数和历史账本
必须来自新批冻结配置；不能临时计算被改过制品的 hash 或传空白新账来规避旧未知用量。

已完成的 [修复报告](../studies/active/MILA_V0220_WIRE_COMPAT_FIX_20260911.md)：
8/8 wire CPU 校验、25 完整记录及语义负控、新 Provider 真实旧账零 HTTP 停发均通过。
40 新测试，全仓库 1545 通过 / 1 可选跳过；真实生成未运行，V2 未恢复。
