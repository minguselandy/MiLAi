# MiLAi 开发与实验进度：2026-11-10

本次按用户“查看之前对话的开发情况和实验进度，提交到github上去”的要求，核对最近对话、
`feat/a100-development-20261104` 的已提交开发记录，以及原 owner、driver 和进程状态。
此前 GitHub 已保存至 `48b9c155`；本次补充该提交之后已经发生的实验进展。
最近开发对话因传输或上下文错误结束，不能据此推断实验子进程也已停止。
以下状态以 2026-11-10 的磁盘证据及实际进程核对为准。

[机器可读检查点](../data/manifests/a100-development-progress-20261110-v187.json)记录观察时间、
原始证据路径、400 条分母、owner 费用状态及尚未产生的后续交付物。
完整 763 行计划仍未完成；本次是进度发布。

## 已有开发与训练

当前分支已有双单卡 FP32/BF16 训练入口、训练及推理资源记录、Source 与实际输入绑定、
冻结主模型、全量审计、适配评分和图表准备工具。预定主参考继续使用 E3 seed0/u32，
没有根据后续实验重新选 seed、checkpoint、样本数或预算。

| 工作 | 已完成范围 | 当前证据及解释 |
|---|---|---|
| P0 / A / B / E3 追加训练 | 两个 P0 短测、A0/A1、B0/B1、E3 seed1/2 共八作业 | [训练计算表](MILAI_A100_CLOSED_TRAINING_COMPUTE_20261107.md)：共 6,062 更新、96,968 draws；上游 E1/E3 seed0 没有重跑或重复计费 |
| 原计划开发包 | P0/A/B64/B 修复/C/D 的 78 项具体合同已有审计 | [完整计划当前证据](MILAI_A100_PLAN_CURRENT_EVIDENCE_20261109.md)；条件扩量、J、DDP 和精确 resume 未被停止条件或实际瓶颈触发，不冒称已执行 |
| 内部冻结确认 | 四方法各 256 来源族，共 1,024 首结果、完整 Source/输入审计及作者语义审阅 | [256 结果](MILAI_A100_CONFIRMATION256_RESULTS_20261107.md)：fixed 完整任务 C 为 149/256，primary 为 148/256；尚无采用学习策略的质量优势证据 |
| 更新轨迹与旧 64 保留 query | 已有完整开发结果、配对分析及原生评分 | [内部结果总览](MILAI_A100_CLOSED_INTERNAL_OVERVIEW_20261107.md)；不同面板不能合并成一个成功率，旧 query 与共享 Source 的暴露分别解释 |
| LME Small | 两方法各 451 首预测，Source/Reader/Judge 审计、评分及归档六阶段闭合 | [LME 比较](MILAI_A100_LME_NATIVE_COMPARISON_20261109.md)：各 401 已评分，fixed 正确 75、primary 正确 73；各 50 首失败保留，全 451 准确率不可用 |
| 论文与总体图表 | 已有结果草案、内部图、LME 图、方法及来源暴露表 | [结果草案](MILAI_A100_DEVELOPMENT_RESULTS_DRAFT_20261107.md)；Mem2Act 最终适配指标、全项目成本与最终论文仍待完成 |

内部 C 标签为实施作者按 Source 审阅，不是独立人类或盲审。E3 三 seed 共享 E1 初始化；
多 seed、多个 query 或共享 session 不增加独立来源族数。历史失败、unknown、负结果与暴露限制保留。

## 本次新增确认：Mem2Act 两套 400 条首执行均已结束

| 原生执行状态 | Fixed prefix | Primary seed0/u32 |
|---|---:|---:|
| 原计划位置 | 400 | 400 |
| COMPLETED | 299 | 294 |
| FAILED | 101 | 106 |
| HOST_RUNNING / NOT_RUN | 0 / 0 | 0 / 0 |
| owner exit code | 0 | 0 |
| owner 已记录 client CPU、验证全部终态 | 是 | 是 |
| 原 owner 与 child 进程均不存在 | 是 | 是 |

Primary 原 owner 状态为 `CLOSED_NATIVE_MEM2ACT400_FIRST_OUTCOMES_RETAINED`，
原 driver 为 `COMPLETED_WITH_FAILURES`。两方法的 row 均为原顺序 0..399，qa_id 配对相同。
此前保存的 primary 最早 100 条完整 case 记录仍与最终 driver 前缀逐字段相同，
其中 76 COMPLETED、24 FAILED；最终 canonical alias 仍须保持这一前缀。
原生 COMPLETED 只是执行状态，不是任务正确、严格 intent 正确或真实业务执行成功。

Fixed 的 canonical alias 与冻结 v2 全 400 Source/SDK/首次 Host 审计已经通过，
400 份首次快照可重放，见[原报告](MILAI_A100_MEM2ACT_FIXED400_NATIVE_RESULTS_20261109.md)。
Primary 的 canonical closure 和全 400 Source/NN 审计尚未生成；之前的两例 NN 机制检查与
最早 100 条检查点不能替代这些门禁。两方法评分、评分审计与最后无损归档也尚未生成。
没有由这次执行终态观察产生全 800 条适配指标或质量优劣结论。

## 费用边界

Primary 已关闭 owner 记录 whole-child CPU 12,154.361424 秒、已测 parent CPU
0.280344148 秒、known generation tokens 5,308,357，新增 generation/embedding unknown 均为零。
原字段 `shared_generation_admissions=1068` 保留其准入语义，不能直接更名为 HTTP 次数或响应回调数。
其中 native 模型加载及决策 CPU 已包含在 whole-child 内，不另行相加。
GPU2 作业区间 8.664538662 小时含整个原生子进程区间，不是 GPU kernel 忙时。
这些数据来自已结束 owner，未离线打开或改写原连续账本。

以上为单阶段已有计量，不是当前全项目成本，也不是受控延迟优势。
idle138 历史已付快照保持；后续出版、审计、评分及归档的普通 CPU 仍须在实际合格空闲窗口
按原流程结算。作者、启动清理等未测 CPU 保持 `unknown_not_zero`，不填零或估造总成本。

## 尚未完成的原计划工作

按[原收尾操作卡](MILAI_A100_MEM2ACT_CLOSEOUT_HANDOFF_20261109.md)保持原顺序：

1. 原 primary 400 最早首结果生成 canonical alias/closure，并核对保存的最早 100 条完整记录。
2. 对该 alias 执行原冻结 v2 全 400 Source/Store/Saver/角色/时钟/权限/应用/SDK/Host/NN 审计。
3. 两方法各 400 的原适配评分及逐项评分审计，保留 failed、零/多个/invalid proposal。
4. 六个 closure/Source/score 门禁全部通过后，再执行原无损归档与全量比较、图表。
5. 完成实际空闲费用结算、全项目已知与未知成本、最终论文和最后全 763 行要求审计。

这些是待执行工作；本次没有启动、重启或自动排队任何实验、评分、归档或模型调用。
已有保护的 Source、协议、模型、query/schema、首结果、标签与预算保持原样。

## 本次提交与验证范围

改动限于 `MiLAi-Lab/AGENTS.md`、进度文档和精简 manifest。开发实现此前已在分支历史中提交，
本次没有新增方法代码；Product/Archive、公开 Schema/API/权限/Canonical 行为均不变。
原始请求、日志、Source 正文、数据库、模型权重与运行产物继续留在 ignored artifacts。

已执行两方法终态/400 顺序/配对身份/最早 100 条完整记录核对、JSON 与文档链接检查、
根仓库依赖边界和 Lab 活动包依赖边界检查及 `git diff --check`。
Lab 边界检查首次使用系统 Python 3.10 时因缺少 `StrEnum` 未能运行；
改用项目已有的 Python 3.11 环境后通过，首次失败计时保留。
没有运行全仓单元、PostgreSQL、模型实验或最终全 Source/评分门禁；本次文档提交不代替这些检查。
本次不合并分支，不宣称生产就绪；回退参照为提交前检查点 `48b9c155`。
