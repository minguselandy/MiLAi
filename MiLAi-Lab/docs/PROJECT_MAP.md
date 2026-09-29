# MiLAi Lab 项目地图

本页回答“这类修改应去哪里”。实验状态以[当前状态](LAB_CURRENT_STATUS.md)为准，
实际方法身份以对应冻结提交为准。本次开发范围只在 Lab 和必要的根 CI；Product 保持 NO_GO。

## 从任务定位实现

| 要处理的问题 | 入口 | 相关检查/证据 |
|---|---|---|
| Agent 组装、记忆工具与原生工具续接 | `baselines/langmem_agent.py` | `tests/unit/test_langmem_foundation.py` |
| 严格记忆 MCP 传输、Store 读写 | `memory/mcp.py`、`strict_tools.py`、`read_tools.py`、`revision_store.py`；旧 baseline 路径为兼容导出 | foundation/provenance/persistent-memory 测试；[S2进度](CODE_ARCHITECTURE_V12_S2_RESULTS.md) |
| 请求和跨组件数据合同 | `contracts/request.py`、`memory.py`、`operations.py`、`scope.py` | `tests/contracts/`、`tests/architecture/` |
| 模型 HTTP、容量与实际 request | `providers/contextual_vllm.py`、`chat_bridge.py`、`request_pipeline.py`、`contextual_capacity.py`；旧 `langmem_chat.py` 为兼容导出 | provider/capacity、冻结 wire 和分组检查；[S5记录](CODE_ARCHITECTURE_V12_S5_RESULTS.md) |
| C/M1/ODR/projection 等配方组装 | `methods/langmem_recipe.py` 显式构造并注入通用 hooks | 原方法断言、live fields 与 request/delivery/response 时序对照 |
| 通用向量合同与归一化 | `memory/embeddings.py`；`methods/reasoning_bank.py` 导出同一函数 | 数学/embedding 边界对照；只含标准库数学，不启动模型 |
| 业务 world 与 owner 对象 | `application/world.py` | application world/lifecycle 检查 |
| 操作授权、重复、partial/unknown 记录 | `application/journal.py` | foundation journal 与 R2 机械反控 |
| 原生 schema 与工具适配 | `application/tools.py` | schema-only 与原始回执检查 |
| unknown 后实际查询恢复 | `application/recovery.py` | 多调用 pending 与真实子进程 MockHTTP 检查 |
| writer 策略与受控触发编排 | `runners/writer_policy.py` | [S6记录](CODE_ARCHITECTURE_V12_S6_RESULTS.md)、writer/phase 合同与导入顺序检查 |
| 原 LSA trace 与连续预算汇总 | `analysis/trace_accounting.py` | 14 个合成计账边界；不替代 benchmark 的 `trace_costs` |
| 多阶段应用运行、资源重开 | `runners/langmem_application.py`、`langmem_application_runtime.py` | `tests/unit/test_langmem_application.py` |
| 请求副本中的记忆/历史呈现 | `memory/presentation.py`；具体策略在 `methods/memory_boundaries.py`；旧 `methods/request_context.py` 为兼容导出 | boundary 与 R1 现有合同；[S1结果](CODE_ARCHITECTURE_V12_S1_RESULTS.md) |
| 普通记忆形成及共同读取接口 | `baselines/langmem_benchmark.py` | `tests/unit/test_benchmark_memories.py`、unified 检查 |
| MemSyco/MERIT 系统比较 | `runners/memsyco_native.py`、`merit_native.py`；`tools/run_unified_benchmarks.py` | unified/native 测试；实际数据需独立授权和冻结 |
| benchmark manifest、任务顺序和费用汇总 | `harness/benchmark_execution.py`；数据合同在 `contracts/benchmark.py` | [S4记录](CODE_ARCHITECTURE_V12_S4_RESULTS.md)、合成执行合同；原生任务与 scorer 仍在各自 runner |
| 外部 Mem0/SimpleMem | `integrations/memory/mem0.py`、`simplemem.py`；旧 runner 为兼容导出 | [S3记录](CODE_ARCHITECTURE_V12_S3_RESULTS.md)、External 依赖组和原 pin |
| 通用 JSON 制品与摘要 | `harness/artifact_io.py`；原 `contextual_artifacts` 导出相同对象 | IO 字节/摘要、原子替换、轻量导入检查 |
| 成本、输入来源和结果 | `harness/`、`analysis/`、`scorers/`、`data/manifests/` | 离线检查；运行时不可读取 rubric/gold |

上述是路径导航，不表示每个方法都启用。M1、ODR、各版本 State/Attention 等历史候选留在
源码和旧锁中供原提交复现；不要因文件存在就恢复某条研究路线。

## 常见开发流程

1. 从用户指令、AGENTS 和最新报告确认当前授权及首断点。
2. 在隔离分支明确一个文件负责人；通用能力放在职责模块，runner 只组合当前实验。
3. 保留用户输入、原始回执、消息身份、已有持久数据合同及失败结果。
4. 运行与改动相关的检查，按照矩阵使用真实可选依赖；涉及模块移动时验证构建与安装。
5. 更新当前导航和工程结果，再提交/推送并核对远端。代码检查不授权真实实验。

本次由 Root 负责文档与验收，Sol xhigh 负责源码/配置/测试/必要 CI，Luna high 负责 Git。
具体困难再使用 Astra，不设置常驻审计者，不平行修改同一文件。

## 依赖与测试归属

- Core：基础合同、分析和不依赖 LangMem 的检查。
- Foundation：LangMem/LangGraph、应用组合、真实 ToolNode 的 MockHTTP 检查。
- External：固定 Mem0/SimpleMem SDK 与其必要依赖。
- Local artifacts：明确需要本地 tokenizer、私有冻结或原始 world 的历史检查。

归属由 [verification matrix](../configs/lab-verification-matrix.json) 和
[检查器](../tools/check_verification_matrix.py)约束；CI 位于根 `.github/workflows/`。
可选依赖测试不能通过扩大全局 ignore 或 skip 躲避检查，历史资产检查也不能冒称公开可复现。

## 当前报告和保留边界

- [v10 总体报告](MILAI_REPAIR_V10_OVERALL_EXPERIMENT_REPORT_20260929.md)：最近实验结论与连续成本。
- [R2 暂停详报](MILAI_REPAIR_V10_R2_PAUSE_RESULTS_20260929.md)：错误事实真实持久化；未自动修复。
- [架构整理记录](ARCHITECTURE_REFACTOR_20260929.md)：本次改动范围、检查与兼容性。
- [结果索引](RESULTS_INDEX.md)：历史阶段的原始判断与报告入口。

原 repair-v10 工作树、九个未跟踪 R2/R3 草稿、私密轨迹和原 v27 草稿保持原状。
当前工作树只基于已发布报告提交整理结构，不复制这些草稿为新协议。

v12 正按冻结合同逐阶段提取外部集成、公共 lifecycle 和 Provider hooks，完整进度见
[执行记录](CODE_ARCHITECTURE_V12_EXECUTION.md)。旧阶段大 runner 不按文件行数整体搬迁。
历史代码的复现边界见[历史索引](HISTORICAL_CODE_INDEX.md)。
