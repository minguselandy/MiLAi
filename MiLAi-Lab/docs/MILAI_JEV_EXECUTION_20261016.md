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

首轮 `ce-pilot-v1` **已正常退出 0 并完成原生 checkpoint**：原生 soft-CE、完整 encoder+head、4 epochs、micro_batch=2、grad_accum=16、encoder_lr=2.5e-5、head_lr=1e-4、seed=0。55 个有效训练问题，实际 8 次优化器更新。四轮平均损失为 0.9295 / 0.5083 / 0.4532 / 0.3875。encoder 有 94,390,780 个权重项改变，decision head 有 11,205,360 个权重项改变；不是冻结编码器的头部训练或旧 Qwen LoRA。CPU 墙钟 2,071.19 秒、进程 CPU 6,996.50 秒，峰值 RSS 约 15.37 GiB。该预算仍不足以据此否定整条路线。

## 真实服务与零样本诊断

上游 HTTP 服务在 127.0.0.1:7870，当前 PID 3396426。完成原始模型调用后，已正常关闭本任务自己的旧 CPU 服务并注册两个实际目录：`milai-impact-base-v1` 指向基础权重，`milai-impact-ce-v1` 指向完成的 `ce-pilot-v1/checkpoint`。health 实测 CPU，自动 fallback 次数 0。上游响应 `model=laya-rl-agent` 是通用名称；实际模型身份由进程启动登记、health 的已加载别名及 checkpoint 配置共同记录，不能只依据这个通用字符串。

`base-dev-v1` 已完成 2 个 dev 事件、6 个问题的实际调用：

- 单元正确 3/6，事件完全正确 1/2。
- root 召回 0/1，误选 root 0，误选 preserve 3。
- 2 次 HTTP、6 个问题序列、7,671 输入 tokens、0 输出 tokens，客户端墙钟 20.354 秒。
- 原账本差额精确对应 2 次请求与 7,671 tokens；generation/embedding unknown 保持历史 10/1，无新增未知用量。原始服务回执均报告没有截断。

`ce-dev-v1` 已通过真实 HTTP 调用微调别名：5/6 单元正确，但六项全选 other，唯一 root 仍漏选，事件完全正确仍为 1/2。因此 5/6 是多数类分数，不是已证明的角色泛化。它同样消耗 2 次请求、6 个问题序列、7,671 输入 tokens，未截断、未校准。实际服务登记及 health 保存在两个 dev 产物中。

## 六条件真实维护对照已闭合

完整输入四臂从冻结 `45ec6d4b` 执行；局部 D3/D4 从 `932b39bd` 执行。三条来源均复用历史 factorial 的实际模型种子与实际来源到达点，不增加完美图，也不重新形成种子。D3/D4 分别读取原 CE/D1 的同一次选择，实际比较事件/candidate 输入一致后复用，没有再次调用控制器。

共 18 个维护位置、108 次首次 Reader 问答；均已读取 before/after、实际输出与回执。它们来自三条已暴露历史，并非 18 条独立历史。

| 条件 | 执行完成/3 | 实际维护观察 |
|---|---:|---|
| D0 无独立 Impact | 3 | 三项当前内容均写入；仍有 Reader 日期误述、过度保留判断等问题 |
| D1 生成式 Impact | 1 | 撤回成功；另外两项 Writer 到达长度上限，原状态不变 |
| D2-Laya-0 | 2 | 撤回和共享条件更新写入；替代支持一项 Writer 未完成；存在过宽 roots 和空支持组问题 |
| D2-Laya-CE | 3 | 撤回时反而追加无条件“可不戴手套”；替代支持 no-change；共享条件保存了部分当前内容 |
| D3 同 CE 选择、局部 Writer | 3 | 仅替代支持事件保存了五项新事实；撤回及共享条件均 no-change |
| D4 同 D1 选择、局部 Writer | 3 | 三项当前内容均写入；仍有 observed 归因与空支持组语义的审阅问题 |

表中的“执行完成”包括 no-change，不等于语义成功。D4 的小样本改善没有控制 Writer 随机采样方差，不能宣称已稳定优于 D1 或 D0。

发现原“当前”问句已包含课程结束、断电或栈桥关闭等前提，可能用提问本身补救未维护状态。因此另行固定了不提供变化前提的三个当前状态问题，从各臂的冻结 after 银行读取，**没有重跑 Writer 或重写原答案**。该补充是发现问题后编写的已暴露诊断，不是盲测。

| 条件 | 不带变化前提的状态问答（撤回／供电／路线） |
|---|---|
| D0 | 核心正确但带保留判断／正确／正确 |
| D1 | 正确／当前内容缺失／错误地使用过期状态 |
| D2-Laya-0 | 正确／当前内容缺失／正确 |
| D2-Laya-CE | 错误地允许免手套／当前内容缺失／正确并明确推断向导在场 |
| D3 | 不能确定例外是否已结束／正确／错误地使用过期状态 |
| D4 | 核心正确但带保留判断／正确／正确 |

18 次补充查询全部结束、原银行值均保持不变；全部答案已阅读。原 mixed QA 可答对，不证明实际状态正确。完整原始审阅见六臂 review 与 current-state review，不采用“命令退出 0 = 模型通过”。

## 局部输入与真实成本

局部 Writer 保留完整内部 binding map，另建明确标为 partial_units 的模型视图；解码/提交仍使用原完整 map。共享条件的 reuse 引用可从被隐藏的兄弟声明处重新展开；未读单元不成为目标，空 roots 仍有新事实创建机会。支持更新目标与正文可写目标继续分开。没有放开 semantic_delta 与 Impact 的不兼容组合。

D3 三次 Writer 输入总计从 12,868 降到 10,155 tokens（约 21.1%）；D4 从 14,094 降到 13,643（约 3.2%）。D3 的两次 no-change 说明输入更少不能代替必要状态更新。D4 中旧支持片段粗、prior_context 重复已有材料，仍限制节省；显式必要边界学习和细粒度范围干预尚未完成。

| 条件 | 实际模型请求 | 原 generation 桶已知 tokens | embedding tokens | Writer 输入 tokens |
|---|---:|---:|---:|---:|
| D0 | 21 | 76,152 | 1,267 | 14,716 |
| D1 | 24 | 96,164 | 995 | 14,094 |
| D2-Laya-0 | 24 | 104,507 | 1,166 | 13,732 |
| D2-Laya-CE | 24 | 99,312 | 1,171 | 12,868 |
| D3 | 21 | 77,313 | 1,085 | 10,155 |
| D4 | 21 | 73,756 | 1,280 | 13,643 |

六条件合计 135 请求 / 527,204 已知 generation 桶 tokens / 6,964 embedding tokens；补充状态查询另有 18 请求 / 52,544 tokens / 0 embedding。所有回执与原账本差额一致，新增 unknown 均为 0，历史 10 generation / 1 embedding unknown 保留。

D2 两个模型各用 3 次 HTTP、12 条问题编码序列、16,892 输入 tokens，CPU 请求墙钟约 45 秒。D3/D4 的实际增量成本不重复计费原控制器；作为独立方法比较时，必须分别加回被引用的 16,892 Laya tokens 或 14,710 生成式控制器 tokens。不同架构的 token 数不是等价 FLOPs；部分基础模型调用与 CPU 训练重叠，墙钟不能作为严格匹配的硬件速度结论。

## 逐项完成审计与下一步

| 决定文档要求 | 当前证据与剩余事项 |
|---|---|
| §1 固定多语言开放权重、保留原编码器与头 | 基础/完整微调权重均已加载并通过真实服务调用；质量未获证明 |
| §2 复用 Impact、单次替换、根/保护合同 | 共享接线及 SQLite 提交机械测试已有；普通 Host 的真实模型全路径尚待执行 |
| §3 W/B 局部 Writer、完整内部绑定、支持更新 | 首版投影和同选择 D3/D4 已执行；细粒度目标独读/共享条件/替代支持干预、必要边界标签与学习仍未完成 |
| §4 来源核对、先分家族、遮罩歧义、覆盖高价值对照 | 首批 20 事件已完成来源审阅与分组；缺充分独立历史、多 root/缺来源/共享数量等覆盖和更均衡标签 |
| §5.1 零样本与原生完整 soft-CE | 首次完整训练、原生权重、曲线与服务验证均完成；多数类坍缩暴露，仍需更多来源家族/角色覆盖和充分学习诊断 |
| §5.2 同数据组合/关系目标比较 | 尚未实现与运行；增强必须同时给 CE，不能把数据收益归于新损失；RLCD 仅可选消融 |
| §6 实际微调别名、部署、回执及统一成本 | 基础/微调别名、实际请求、CPU 训练成本和统一账本已验证；独立 calibration 未完成，不能用置信度跳过维护 |
| §7 D0/D1/D2-Laya-0/D2-Laya-CE/D3/D4 | 三条共同 before 的六条件与状态受限/混合 QA 已闭合并审阅；独立空库连续轨迹、完整候选/角色标注及联合状态四维评价、稳定性仍不完整 |
| §7 扩大至未见家族、种子 | 尚未开始；当前仅是三条已暴露历史及单次 Writer 采样 |
| §8 反思、创新主张与简化出口 | 目前没有新颖性或性能胜出结论。已有错误指向角色语义和可修订粒度，仍允许 D0 更好 |

目前最明确的机制问题是：旧状态常把资格结论与前提合在一个单元；结论仍可成立，单元中失效前提却必须修订。另一问题是旧记忆只有一般规则而没有当前事实时，不应伪造一个“直接受影响的旧事实”。Laya 的误 preserve 和这些粒度问题必须分别检验，不能只用分类准确率掩盖。

## 验证与可恢复入口

已通过：14 项 Laya 适配/回执/分组测试；24 项包含实际 SQLite 的依赖范围与 typed owner 测试；45 项原 benchmark recipe/预算回归。7 个改动源码模块 mypy、受影响 Ruff、Lab DAG 和 tools/Product 边界通过。普通 Host 完整回归 392 项通过（548 条既有依赖弃用警告）；全仓与远端 CI 未运行。

较早的扩大回归暴露了 7 个未启用 Laya 时仍访问预算属性的问题，已修复且对应 45 项回归通过；旧失败输出保留。历史 hash 断言测试不作为本任务验收门禁。

执行工作树：`/cra/memory/mx_memory/MiLAi-worktrees/jev-training-20261016/MiLAi-Lab`。
可核查简报：[`data/manifests/milai-jev-pilot-v1-progress.json`](../data/manifests/milai-jev-pilot-v1-progress.json)。
原始权重、输入、响应、日志、Python 环境和训练 checkpoint 均在 ignored `artifacts/jev-training/`。
原账本仍是 `/cra/memory/mx_memory/MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`。

训练 PID 3233933 及全部六条件/补充查询进程均已退出，原结果和失败保留。唯一任务服务为本地 CPU Laya PID 3396426（exec 84042），health 同时列出 base/CE 别名；没有排队的下一模型任务。继续前观察真实进程/终态，不凭旧状态重启。

本轮局部实现相关 154 项测试通过；8 个改动源码 mypy、Ruff、Lab DAG/tools 边界、287 源码矩阵通过。早期 392 项普通 Host 回归属于 a02 接线版本；本轮没有重跑全仓或远端 CI。

机器证据：
- [六臂成本与逐案闭合](../data/manifests/milai-jev-six-arm-pilot-v1-summary.json)
- [18 个状态位置和 108 个首次答案审阅](../data/manifests/milai-jev-six-arm-pilot-v1-review.json)
- [18 个不带变化前提的当前状态查询审阅](../data/manifests/milai-jev-current-state-probe-v1-review.json)

下一步保持原目标：扩充来源独立、类别覆盖更好的短决策数据；对不足预算与不可学习性作区分；同数据比较普通 CE 与关系目标；清理局部输入重复并开展必要边界干预；补独立连续轨迹和普通 Host 真实调用，再进行未见家族/种子验证。不得把本轮小样本闭合改称整体完成。

撤销本轮接线可回到父版本 `dc431c06`；此回退只针对代码，不删除原始运行产物。当前没有发布或合并本轮分支，远端 CI 未运行，Product 仍 NO_GO。
