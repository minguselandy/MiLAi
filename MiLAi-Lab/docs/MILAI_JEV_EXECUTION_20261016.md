# Jev 类 Laya 接入与训练执行记录

目标是完整执行 [接入与训练决定](MILAI_JEV_INTEGRATION_TRAINING_DECISION_20261016.md)，当前 **ACTIVE / 未完成**。
本页是执行证据，不把接线、少量分类结果或正在运行的训练视为目标完成。

## 当前实现与 GitHub 对齐

已 fetch origin。主工作树 main 已快进到远端 main `518aee41`；两个阻止快进的同名用户文档与远端正文相同，原件另存主工作树 `MiLAi-Lab/artifacts/jev-alignment-20261016/user-plan-backup/`，其他用户计划保留。
实现分支 `feat/lab-jev-training-20261016` 从 PR #124 对应的远端 `feat/lab-open-jev-laya-impact-20261016`（`dc431c06`）建立，沿用原 Laya 模块及其未合并开发祖先，没有把历史开发分支整体并入 main。
本次 GitHub API 查询被匿名限流，网页也未返回 PR 正文；因此当前 PR 的 open/draft 状态只保留为原决定文档的观察，不冒充本次已核实。

- `methods/laya_impact.py` 共用训练/运行 payload，保留日期、完整 delivery、真实单元别名和原三分类。普通 Host 的当前维护范围作为独立指令保留，不混成事实证据。
- 原始 HTTP 响应在状态码、JSON 和语义标签验收之前保存。非法标签、缺失响应和截断不变成空选择；已经执行的计算仍然计费。
- `runners/laya_impact.py` 通过原 wrapper 替换 Impact。Benchmark 和普通 Host 使用同一入口，其他调用继续使用原 provider；没有串联旧 Impact。
- typed HTTP 使用原账本和显式 endpoint/model/输入预算登记。Host 与生成调用共用每条消息的调用限额；保存的响应直接复用，未确认请求不重新派发。
- 非自回归请求计入原 `generation` 计算预算桶；新增 `compute.laya_impact` 单列请求数、问题数、真实输入 token 和墙钟时间。零输出 token 不视为零成本。训练计算在同一账本的 `compute.laya_training` 单列，未创建第二账本。
- Product、公开 Schema/API、权限与 Canonical 未修改。Laya 请求配置和回执格式属于 Lab 新实验配置；不改变现有默认 provider。

未增加 SHA 校验或内容指纹门禁。普通 Git commit 仅作来源说明。没有停止、修改或挪用已有 GPU 服务。

## 数据与训练

原始材料是 `method-architecture/strong-v1/candidate` 的实际 Impact 请求，包含模型真实形成的不完美记忆。逐项依据当前原文、旧支持和实际单元重新审阅，未读取旧 Impact 选择来生成标签。

首个诊断集共 20 个事件、11 条已暴露作者开发历史、8 个合并后的来源/机制家族；没有增强，没有将它们包装成 200 个独立事件。AND、OR、例外撤回的同类历史归在同一家族。

| 划分 | 事件 | 家族 | direct_root | preserve_successor | other | 遮罩 |
|---|---:|---:|---:|---:|---:|---:|
| train | 15 | 5 | 9 | 1 | 45 | 8 |
| dev | 2 | 1 | 1 | 0 | 5 | 0 |
| calibration | 1 | 1 | 0 | 0 | 3 | 0 |
| test | 2 | 1 | 1 | 0 | 10 | 0 |

家族划分在问题展开之前固定。划分、作者审阅、歧义理由只在 metadata 中，不进入 state/questions。8 个带历史日期或混合条件且角色不唯一的单元不参与监督，问题仍保留。全部 83 个问题的完整序列最大 1,774 tokens，未截断，采用 max_len=2048/head_max_len=256。

此数据量及 preserve 类覆盖不足，只能作分组学习诊断。test 也是之前已暴露的开发材料，不是盲测。calibration 仅有 3 个 other，未使用它拟合温度；关闭上游随机校准，不按置信度跳过维护。

基础模型为 `convaiinnovations/laya-multilingual`，已下载并加载，参数 321,908,995。上游固定采用决定文档核查的 `4ac226d5`，Laya 0.4.8，隔离 Python 3.11 / PyTorch 2.7.0+cpu / Transformers 4.52.3。机器的 4 张 A100 均被原有服务占用，本次使用 CPU。

首轮 `ce-pilot-v1` **仍在运行**：原生 soft-CE、完整 encoder+head、4 epochs、micro_batch=2、grad_accum=16、encoder_lr=2.5e-5、head_lr=1e-4、seed=0。55 个有效训练问题，预计 8 次优化器更新，不是冻结编码器的头部训练，也不是旧 Qwen LoRA。实际损失与最终报告以产物为准；8 次更新不能据以否定全部路线。

## 真实服务与零样本诊断

上游 HTTP 服务已在 127.0.0.1:7870 启动，`LAYA_EXTRA_MODELS` 显式将 `milai-impact-base-v1` 注册到本地原始 checkpoint。health 实测 CPU，自动 fallback 次数 0。上游响应 `model=laya-rl-agent` 是通用名称；实际模型身份由进程启动登记、health 的已加载别名及 checkpoint 配置共同记录，不能只依据这个通用字符串。

`base-dev-v1` 已完成 2 个 dev 事件、6 个问题的实际调用：

- 单元正确 3/6，事件完全正确 1/2。
- root 召回 0/1，误选 root 0，误选 preserve 3。
- 2 次 HTTP、6 个问题序列、7,671 输入 tokens、0 输出 tokens，客户端墙钟 20.354 秒。
- 原账本差额精确对应 2 次请求与 7,671 tokens；generation/embedding unknown 保持历史 10/1，无新增未知用量。原始服务回执均报告没有截断。

这是控制器诊断，不含 Writer、状态转换或 Reader QA。微调 checkpoint 尚未完成并注册，不能称为 D2-Laya-CE 结果。

## 逐项完成审计与下一步

| 决定文档要求 | 当前证据与剩余事项 |
|---|---|
| §1 固定多语言开放权重、保留原编码器与头 | 基础 checkpoint 已真实加载；完整微调运行中 |
| §2 复用 Impact、单次替换、根/保护合同 | 共享接线及 SQLite 提交机械测试已有；普通 Host 的真实模型全路径尚待执行 |
| §3 W/B 局部 Writer、完整内部绑定、支持更新 | 未完成。现有 Writer 仍接收完整候选；不得称作局部计算。需要范围干预和独立边界标签 |
| §4 来源核对、先分家族、遮罩歧义、覆盖高价值对照 | 首批 20 事件已完成来源审阅与分组；缺充分独立历史、多 root/缺来源/共享数量等覆盖和更均衡标签 |
| §5.1 零样本与原生完整 soft-CE | 零样本真实 HTTP 完成；完整 CE 待退出、检查原生权重、曲线与逐角色指标 |
| §5.2 同数据组合/关系目标比较 | 尚未实现与运行；增强必须同时给 CE，不能把数据收益归于新损失；RLCD 仅可选消融 |
| §6 实际微调别名、部署、回执及统一成本 | 基础别名服务和统一账本已跑通；微调别名及其真实请求、独立 calibration 尚待完成 |
| §7 D0/D1/D2-Laya-0/D2-Laya-CE/D3/D4 | 六条件的 Writer 对照均未完成，当前只有 Impact dev 诊断。仍需共同 before、各臂空库连续轨迹、必要候选覆盖、联合状态/状态受限/混合QA、分阶段完整成本 |
| §7 扩大至未见家族、种子 | 尚未开始；先完成少量真实事件全路径 |
| §8 反思、创新主张与简化出口 | 目前没有新颖性或性能胜出结论。已有错误指向角色语义和可修订粒度，仍允许 D0 更好 |

目前最明确的机制问题是：旧状态常把资格结论与前提合在一个单元；结论仍可成立，单元中失效前提却必须修订。另一问题是旧记忆只有一般规则而没有当前事实时，不应伪造一个“直接受影响的旧事实”。Laya 的误 preserve 和这些粒度问题必须分别检验，不能只用分类准确率掩盖。

## 验证与可恢复入口

已通过：14 项 Laya 适配/回执/分组测试；24 项包含实际 SQLite 的依赖范围与 typed owner 测试；45 项原 benchmark recipe/预算回归。7 个改动源码模块 mypy、受影响 Ruff、Lab DAG 和 tools/Product 边界通过。普通 Host 完整回归 392 项通过（548 条既有依赖弃用警告）；全仓与远端 CI 未运行。

较早的扩大回归暴露了 7 个未启用 Laya 时仍访问预算属性的问题，已修复且对应 45 项回归通过；旧失败输出保留。历史 hash 断言测试不作为本任务验收门禁。

执行工作树：`/cra/memory/mx_memory/MiLAi-worktrees/jev-training-20261016/MiLAi-Lab`。
可核查简报：[`data/manifests/milai-jev-pilot-v1-progress.json`](../data/manifests/milai-jev-pilot-v1-progress.json)。
原始权重、输入、响应、日志、Python 环境和训练 checkpoint 均在 ignored `artifacts/jev-training/`。
原账本仍是 `/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`。

训练进程 PID 3233933，启动日志 `runtime/ce-pilot-v1.log`，结果 `ce-pilot-v1/result.json`；
基础服务 PID 3258785，日志 `runtime/laya-base-server.log`。继续工作前必须观察真实 PID/进程命令与退出结果，不能仅凭本页状态重新启动。
训练实际源码副本、环境版本及输入均保留在产物内；新开发不会改写当前训练输入或旧结果。

撤销本轮接线可回到父版本 `dc431c06`；此回退只针对代码，不删除原始运行产物。当前没有发布或合并本轮分支，Product 仍 NO_GO。
