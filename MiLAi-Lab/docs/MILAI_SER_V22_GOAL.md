---
status: COMPLETE_METHOD_FREEZE_FOR_SMALL_EVALUATION
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
reference_commit: 010ada50bddc6f208ce4311fe311beff4c5c4551
---

# v22：已暴露回归与方法收敛

交付状态：[R3结果](MILAI_SER_V22_P7_R3_RESULTS_20260927.md)验证条件authority，诊断7/12、MERIT4/5、dependent1/2、Host7/7；形成/漏搜/动作后维护缺口全保留。[P8方法冻结](MILAI_SER_V22_P8_METHOD_FREEZE.md)允许小规模正式三臂比较，尚无端到端收益结论。连续SER415生成/373013tokens/4370embeddingtokens/75get。长程P9–P12继续；下文为各轮历史。

最新：[P7 R2](MILAI_SER_V22_P7_R2_RESULTS_20260927.md)已完成覆盖修复及两臂原arc重跑。B1 native4/5、dependent1/2；A5 native3/5、dependent0/2，ep2容量错误后ep3真实继续，ep4再次失败，Host仅4/7消息完成。连续SER360生成/332460tokens/3902embeddingtokens/75get。下一候选仅条件化authority，先离线空证据/current/assistant-only反例，再冻结原小规模对照；Formation/Reconciliation不混入方法修复。下文保留原冻结范围与R1历史。

P6最终同源13/13已发布；本Goal执行总计划P7并依据证据判断P8冻结条件。P9及后续仍由长程Goal继续，不能把本轮交付作为整个项目终点。

## 最小接线

新增 `tools/run_milai_ser_v22.py` 薄入口和输出路径config，复用现有 `run_frozen_diagnostics`、`run_exposed_merit_arc`、LangGraph loop与原scorer。A5沿用最终P6的算法、authority、recipe与transport；B1只观察，不加projection或authority。新锁绑定当前公共接线和两臂源码，实际run-identity分别保留B1 recipe与A5 projection.recipe_id。不能把新入口版本误写成新方法收益。

不添加自动形成、强制搜索、动作后写入、第二模型、业务真值gate或特定benchmark规则。原业务工具schema不采用P5的fixture合同修正。原输入/顺序/世界/判定不变，两个arm各用独立空namespace和原始world，历史结果保持原样。

## P7冻结的小规模范围

| 顺序 | 运行 | 原输入 |
| --- | --- | --- |
| 1 | B1 diagnostic | 原12例、20session |
| 2 | A5 diagnostic | 完全相同12例、20session |
| 3 | B1 MERIT | 原arc0、5episode、7message |
| 4 | A5 MERIT | 完全相同arc0、5episode、7message |

诊断input SHA=`a6852f07b4b1801e0426cb9ca930c518b3182ac2d5b9f2754f9109e98bf862bc`；原rubric SHA=`62ab23a2a15f2ef3b81ecb51a715a19e379d24581b90ade2e9b8c12968a0ebcc`，仅供Root离线完整语义评审。沿用v16的评审边界：要求真实保留/回答/业务结果与禁止过度保存，不把旧v14专有材料句柄、literal_uses或maintenance字段强加给LangMem。

MERIT selection=`data/manifests/contextual-memory-v7-e0-selection-final.json`，SHA=`cd0f4fb2d7ae294b8d74ed937e29ffe28475c97a457ee76e3c279b7ef72d5982`；arc SHA=`32e50fc25c1ce473eccb5c0653e3867072d792c9aed80148236f9b0baff5d12f`。保留原5/2 native/dependent分母和merged-task checker规则，补充义务诊断不改native分数。此输入早已暴露，不称unseen。

模型、embedding、容量、温度、工具、重试/失败策略和初始化两臂一致。B1/A5协议差异完整保存，尤其A5额外authority；模型可见协议带来的变化不能单独归因于stale rebase。原runner的MERIT `memory_had_fact`来自checkpoint搜索历史，另用实际Provider request核对送达，不重命名原字段或冒充因果采用。

## 判定与失败处理

两臂原任务均完成后，比较逐case语义结果、native/dependent成功、真实业务参数、形成/检索/更新/动作后维护、证据送达和成本。技术TERMINAL不等于语义通过。无自然revision时stale-action/rebase/refresh分母0保持undefined；不把0触发称为选择性成功。

发现技术失败按最小受影响单元定位，保留费用和失败轨迹，再冻结通用修复。语义失败不换题、不改rubric或拼接最好run；依据§11写至少两假设，识别是SER断点还是形成/检索/维护独立瓶颈。只有实际退化与wire证据支持才改方法。若暴露回归明显退化，先修复或pivot；非本机制的既有问题不自动通过，也不能假称已解决。

P8逐条审查总计划§25九项门槛，包括无stale正文泄漏、真实derived失效、无关干预可控、多对象多版本、协议稳定、参数冻结、无特定题规则和完整费用。进入P9前另写正式freeze，预注册B1/lite/full及未见selection。可选capsule/action-grounding/Attention/Jev仍依原条件，不提前加入。

## 费用、分工与交付

Sol xhigh独占源码/config/CI/必要窄检查，Root独占方案/冻结/评分/所有真实调用（并发1），Luna high继续已授权发布。使用原 `artifacts/ser-v20/budget.json`，起点202生成/195740tokens/2837embeddingtokens/75版本解析get，绝不清零。每公开message原上限12模型请求；不另立全程固定caps、不利用无限重试筛结果。每个技术失败先诊断，费用始终累计。

本次只测试新CLI/身份/原runner接线及实际受影响边界；沿用已有schema，不重跑decoder probes或全套测试。新锁后一次必要build，同时纳入P6R2与v22锁以及新入口/config；不宣称旧包已有新内容。

- [x] 薄入口、正确run身份、20项受影响窄验证与66文件新源码锁；一次必要build通过。
- [x] R1四个同源串行尝试；R2/R3新源轨迹另列，不拼接，费用完整。
- [x] 完整语义/native/实际request核对、失败反思、成本/存储与复现；业务失败保留。
- [x] P8九项判定及方法冻结；P9另冻结selection与新入口。
- [x] Luna发布R3/P8为`7f26a9b5f3ff3b5ba54f7c2a0b3dacf3d4d03f90`并核对remote；长程Goal继续P9–P12。

P7 R1已执行四个预定run，见[R1结果与Failure Review](MILAI_SER_V22_P7_R1_RESULTS_20260927.md)。诊断B1 8/12、A5 7/12；两条MERIT在ep2 msg0因空搜索循环达到12次容量后中止，不能记为完整回归。累计SER306生成/274357tokens/3689embeddingtokens/75exact reads。下一轮先以独立锁增加opt-in episode局部容量失败隔离，原scorer公式、world/Store副作用与全分母保持，未尝试消息单列；不同时调整authority。随后独立检验无memory却注入authority的开销/决策影响。R1所有失败与费用不改。
