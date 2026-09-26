---
status: ACTIVE
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
reference_commit: 3ecad01dcf2f3f07bc4a44926848597a2e63f71b
---

# v21：可调刷新预算与完整类型诊断

执行总计划P5/P6。P3原三例、P4五种非温度机制与最终动作已成立，但A4在无关更新中仍反复读取Y。保留其算法作为同源对照，新A5只增加机械rank预算策略，不改变自然语言任务、业务schema、authority、lineage或当前正文的身份绑定。

每个search按原返回顺序扫描。更高排名CURRENT exact结果或成功绑定的exact refresh可以形成当前候选；启用`refresh_until_current_candidate`后，后续低排名stale继续隔离而不自动读取。`max_exact_refresh_per_search`限制真实新Store.get次数，默认1；同request缓存只复用已绑定的版本，不重复计费。DELETED跳过，UNKNOWN保留未知，二者都不冒充当前候选。不跨request持久缓存，不判断语义是否充分，也不自动禁止业务动作。两参数可独立关闭/调整，用于后续消融；本轮不扫参数寻找最好结果。

机械排名不是语义权威。一个高排名current结果可能与当前任务无关，因此保留自然search路径并在混合对象/current冲突中验证边界。源码不读取fixture名称、expected值、rubric或case type。

## P5：六个小规模对照运行

采用P3时已定义、当前尚未运行的三个fixture，各同源A4/A5两臂：

| 顺序 | fixture | 必须验证 |
| --- | --- | --- |
| 1 | numeric_amount | 1774→6595，初始与当前版真实送达，实际整数参数正确 |
| 2 | retained_metadata | 数值48不变但元数据更新；必须取得X@2，不能靠碰巧旧值相同通过 |
| 3 | irrelevant_lower_rank | primary current、Y确实先被检索且低于primary；更新后不额外search，动作保持North |

每例先A4再A5，独立空namespace、同样公开文本和初始化，同一模型/工具/评分/失败策略。运行前冻结源码、逐例schema合同、配置、fixture/hash和本方案。主要gate：两臂各3/3任务与机制成立，A5对changed/retained仍取得当前版本；irrelevant的A5 exact get低于A4，且无额外Host search或动作退化。更少get不等于总tokens或总延迟更低，各项分别报告。若低排名Y没有实际进入初始请求，该例属于机制未暴露，不假称成本收益或换题。

## P6：同源码完成十二类诊断

P5通过后复用其中三条A5轨迹，按原rubric顺序运行余下九例A5：categorical_route、boolean_approved、boolean_cancelled、deleted_evidence、multi_revision、current_conflict、assistant_only_stale、no_stale、mixed_memories。不为P6重复前三条；若实现因失败修改，则建立新的源码身份，明确旧、新轨迹的边界，不能拼成同源成功。

缺失和冲突例要求0业务动作且Root读取终端缺失/澄清正文。no-stale要求无exact get、derived demotion或额外search。mixed要求实际请求同现CURRENT/SUPERSEDED/DELETED/UNKNOWN、current与unknown原样、历史stale/deleted正文隔离、顺序保留。普通回复机械risk按实际生成快照及真实revision边界判定，指标不宣称词级语义因果。当前版本和最新排名均不自动解决语义冲突。

P4的assistant-only中间虚称search原样保留；本阶段读取自然完整证据场景的工具报告。若同类缺陷重复且影响结果，单独做Failure Review与最小通用修复，不能默默改通过条件或添加针对样例的提示。

## 执行、费用和后续

Sol xhigh独占实现/config/CI和必要窄检查，Root持有真实调用控制权（并发1）、fixture/评分、freeze/结果，Luna high执行已授权的发布。原v20和历史结果/锁不改；新recipe/config/lock为v21，vLLM配置不变。预算沿用`artifacts/ser-v20/budget.json`，起点41生成/36834tokens/589embeddingtokens；新失败费用永久计入。

P5同时修正sdist包含`data/diagnostics`，在新锁与源码完成后做一次必要build及成员检查，闭合v20延后的包装项。测试仅覆盖可调策略、rank顺序/current/UNKNOWN/deleted、缓存与实际Provider接线及原受影响窄回归；不跑full suite或重复decoder probe。

- [x] P5最小实现、11项窄检查、源码与配置冻结；一次必要build通过。
- [x] P5 R1三例×两臂及Reflection，严格2/6；R2仅澄清两个fixture完整目标引用合同，4个新run通过，见[R2结果](MILAI_SER_V21_P5_R2_RESULTS_20260927.md)。原irrelevant v1证据单列，旧失败不改判。
- [x] P6九例与P5三例组成同源12类结果：本轮8/9、覆盖11/12，保留唯一current冲突失败与全部费用，见[P6 R1](MILAI_SER_V21_P6_R1_RESULTS_20260927.md)。
- [ ] 按§11修复current冲突中的存储时间/来源权威混淆，先三个小控制，不将未完成修复当成阶段终结。
- [ ] 累计成本/存储、打包、复现、Luna发布与远端核对。
- [ ] 进入P7已暴露12-case/MERIT arc0回归；总体Goal仍ACTIVE。

本阶段没有许可提前将开发样例称为unseen，也不跳过formal gate。P7及以后依长程Goal继续；阶段成功不等于整个项目完成。

R1后的明确调整：P6复用两条R2 A5 v2和一条R1 irrelevant A5 v1，再执行九条预先统一完整引用说明的v2案例。没有把这组开发覆盖称为一轮统一新合同的独立12例试验，原四次失败与成本全部保留。方法源码仍为P5冻结版本。
