# MiLAi Lab 项目地图

本页回答“这类修改应去哪里”。实验状态以[当前状态](LAB_CURRENT_STATUS.md)为准，
实际方法身份以对应冻结提交为准。本次开发范围只在 Lab 和必要的根 CI；Product 保持 NO_GO。

## 从任务定位实现

| 要处理的问题 | 入口 | 相关检查/证据 |
|---|---|---|
| Agent 组装、记忆工具与原生工具续接 | `baselines/langmem_agent.py` | `tests/unit/test_langmem_foundation.py` |
| 严格记忆 MCP 传输、Store 读写 | `baselines/langmem_mcp.py`、`langmem_revision_store.py` | foundation/provenance/persistent-memory 测试 |
| 模型 HTTP、容量与实际 request | `providers/contextual_vllm.py`、`langmem_chat.py`、`contextual_capacity.py` | provider/capacity 和真实模板的分组检查 |
| 业务 world 与 owner 对象 | `application/world.py` | application world/lifecycle 检查 |
| 操作授权、重复、partial/unknown 记录 | `application/journal.py` | foundation journal 与 R2 机械反控 |
| 原生 schema 与工具适配 | `application/tools.py` | schema-only 与原始回执检查 |
| unknown 后实际查询恢复 | `application/recovery.py` | 多调用 pending 与真实子进程 MockHTTP 检查 |
| 多阶段应用运行、资源重开 | `runners/langmem_application.py`、`langmem_application_runtime.py` | `tests/unit/test_langmem_application.py` |
| 请求副本中的记忆/历史呈现 | `methods/memory_boundaries.py`、`request_context.py` | boundary 与 R1 现有合同；效果见冻结报告 |
| 普通记忆形成及共同读取接口 | `baselines/langmem_benchmark.py` | `tests/unit/test_benchmark_memories.py`、unified 检查 |
| MemSyco/MERIT 系统比较 | `runners/memsyco_native.py`、`merit_native.py`；`tools/run_unified_benchmarks.py` | unified/native 测试；实际数据需独立授权和冻结 |
| 外部 Mem0/SimpleMem | `runners/mem0_native.py`、`simplemem_native.py` | external 依赖组和原 pin；不能静默改原 baseline |
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

已识别但本次不扩展的结构问题包括旧阶段大 runner，以及若干 baseline 对外部系统 runner 的
依赖。这些涉及不同方法/SDK 合同，应依据实际后续改动再提取，而非为统一目录一次搬迁所有代码。
