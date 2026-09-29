# v12 S4：benchmark 公共执行流程

状态：本地工程验证完成，远端 CI 与发布待完成。源码基线为
`5aa61b8d767a2e6b3db8783f9497dad82b671405`。

公共执行实现进入 `harness/benchmark_execution.py`，包括 `sha`、`trace_costs`、
`validate_config`、`source_identity`、`prepare_manifest`、`start_job`、`finish_job`
七个函数。MERIT 旧名导出同一对象，MemSyco 直接使用 canonical 模块。
原生数据选择、任务转换、业务世界、工具和 scorer 继续属于各自 benchmark runner。

首个断点是 MemSyco 为复用 manifest 和任务生命周期而依赖 MERIT runner。竞争解释是
这些操作属于 MERIT 原生任务合同，或它们只是放错了层的共享执行能力。
实际函数只处理共同配置、制品、任务状态与计账，不调用原生 task/world/scorer，支持后者。
提取以真实共同职责为界，不把原生 benchmark 整体搬成另一套框架。

## 冻结合同比较

[合成 golden](../data/diagnostics/code-architecture-v12/benchmark-execution-golden.json)
为 65,267 bytes，SHA256：
`f5dd86e7ec77e56109671883b10c5ba9f4ce13f05e1ea967a7c0a9c41844e1b7`。
覆盖 prepare/start/finish、顺序拒绝、已尝试任务、身份漂移、dirty 目录、未知字段、任意
状态字符串、原 JSON 文件字节、费用分类与异常，以及源码身份的结构、排序和哈希变化。

`start_job` 原先先写 STARTED/RUNNING，再检查任务目录；目录冲突时留下该状态的行为保留。
`finish_job` 原有 aggregate status 规则与自由状态字符串也保留，没有新增 enum 或状态校验。
未知 token usage、重叠的 MCP 观察耗时和失败开销不被删掉或重新计费。

行为 golden 使用合成源码树和明确的 metadata/git 返回，真实工作树的完整源码身份另行保存。
因此，迁移导致的正确 source SHA 变化不会被掩盖成“源码身份未变”。
本阶段不调用模型，不运行原生 benchmark，也不读取其真实资产或私密轨迹。

## 本地验证

迁移前后与公开 golden 全字节一致。七个共享函数和十五个保留的原生 runner 函数，
去除类型注解与 `typing.cast` 后的执行 AST 一致。五个 DTO 与三个参数 Protocol 用于真实
生产者和消费者，没有新增运行时字段或校验。

- Core 合同 3 项、Foundation 相关检查 49 项通过，共 52 项。
- Ruff、Core mypy 35 个文件、两份受影响 runner 的 strict mypy、两项 boundary 和矩阵检查通过。
- 离线 sdist → wheel，以及新安装中的完整合同和七个兼容对象身份检查通过。
  所有加载的 Lab 模块均来自新安装目录；Foundation 借用已有依赖，没有下载。

sdist SHA256：`c77d0b60f4da71c57c6fcc4f3acbc97f0fa5dba8d7185c55b49fc0e4195b3f11`。
wheel SHA256：`8ac15b8bd2b926eec51b26db08bc392d01c98a330a741ce3315d9027314efcfd`。
真实源码身份记录新增两份 canonical 文件和三份预期改动，共 190 个条目，不强迫旧源码哈希相等。

初次 Ruff、类型及检查脚本失败与修复保留在
[精简工程证据](../data/diagnostics/code-architecture-v12/s4-engineering-evidence.json)。
S4 还发现并修复 S3 最后 fixture 文件名调整遗漏的一行 Ruff 超长问题；原始 AST 保持一致，
[S3 报告](CODE_ARCHITECTURE_V12_S3_RESULTS.md)已明确原检查覆盖限制。
这项测试文件的最终纯格式调整晚于 sdist，故构建字节验证只认领记录的六份相关源码及新合同测试，
不声称该构建包含最后的全工作树字节。最终格式检查已通过，无需重跑未改变的 SDK 行为。

这些证据只证明公共流程迁移兼容，不更新历史实验分数或成本收益结论。
S5–S7、剩余 runner 依赖审查与最终 Fast CI 仍待完成。
