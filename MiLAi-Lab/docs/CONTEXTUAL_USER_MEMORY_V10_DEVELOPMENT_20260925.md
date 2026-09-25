# v10 执行记录：接口冻结与开发

用户已要求执行完整 [Goal v10](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v10.0_20260925.md)。以下记录实际实现边界和证据，不把起草阶段的“仅文档”当作新的审批流程。

## A：开发前冻结

基线为 `7247742133de888276342c48638b12c81eaeec23`。原 v9 44 个运行文件已逐项核对，映射仍为 `9854a237f583563618c45ffb59e589484f6c4dea74a8393a1b5c41aa0ce7a0b8`；旧账仍是 119 次生成／966332 generation tokens／4358 embedding tokens。新增调用使用独立 v10 账本，旧账文件散列记在[开发清单](../data/manifests/contextual-memory-v10-development.json)。准备阶段没有模型请求。

本地 MERIT、AgeMem、ProactiveMemory 和 MemTX 的 commit、许可证现状、实际查看文件及散列已记录。AgeMem 和 MemTX checkout 未找到仓库许可证文件，本轮只参考接口思想、不复制其代码。ProactiveMemory 的每轮独立记忆 Agent 与 MemTX 的全局依赖图不引入本实现。Luna 已下载 ATMem v2／StateMem v1 的官方论文 PDF 和 TeX 包，版本、字节数、SHA 与论文许可证已记录；这些不是可运行代码。论文及其源码包、GitHub/Hugging Face 精确查询和作者发布入口均未给出可核验的官方数据／代码仓库及评分入口。StateMemBench 的数据许可与 scorer 仍不可核验，计划实验标记 NOT_RUN；其缺失不阻塞纯接口开发。核查结论只说明本次未取得官方发布，不声称证明任何未来或非公开发布不存在。

## 冻结的最小接口

- `decision_policy=off|notes|basis`；旧 ordinary 与旧 State 行为保持默认，v10 两个主要比较臂都使用 `state_policy=off`。新 policy 只允许 json_action；native 不能静默丢掉 sidecar。
- 唯一 `TaskState.active_decision` 为显式类型，Host 提供 decision、scope、adopted_evidence、critical_gap、status，程序补准确身份、代次、范围和变化原因。notes 使用单份自由工作笔记，允许判断、引用、不确定性和自主检索，不认证任意字符串为采用关系。两臂使用可比状态容量、相同上下文和输出容量，全部计费。
- basis 外壳为 `state_delta`＋`tool`＋`arguments`，notes 为自由笔记 sidecar＋原动作；两者都在正常一次生成中更新，null 无变化。finish 同样经过预检。先验证完整包，再保存小状态，之后依原顺序登记业务 intent、执行和保存 raw result；不把 sidecar 传给业务工具。
- 新采用只来自 HostSession 当前已交付正文绑定。现有采用用当前投影的 `cN` 继续，保持旧 exact_ref 和 spans，不扩充 seen 或隐式跟随最新版。重新确认旧历史版本后，对相同已观察变化不重复通知。
- 有关版本／生命周期／适用性变化置 needs_recheck；无关变更不触发全体重核。新观察与当前判断一起交付给 Host，程序不按主题字符串排除。null 不冒称已消化新观察。
- `memory_search(focus=critical_gap)` 从缺口和必要事项 anchor 构造一次真实查询；普通显式 query 不变。焦点变化进入实际缓存与 expansion 身份，不能只改 trace。原读缓存复用，不新建缓存系统。
- task 切换清当前槽，同 task 续轮保留；checkpoint 显式重建嵌套类型。受管删除清受影响采用和自由文本，恢复不得复活已删除正文。决策状态不能清掉未决业务或持久维护义务。

计划 method v15、decision-basis-v1、contextual-json-action-v2；仅在实际格式／行为改变处升级协议。原 write／material／operation 不无差别升级，最终采用身份以代码和 freeze 为准。准备入口最小扩展现有工具的模板与 arm 参数，新模块进入源码映射，不复制另一套准备平台。

实验控制只增加 `decision_feedback` 和 `decision_gap_focus` 两个 bool，basis 默认开启，notes/off 关闭。前者关闭时只停止候选自动通知；后者关闭时只隐藏并拒绝 critical_gap 焦点动作，普通查询改写仍然可用。没有在开发阶段就决定跑齐 E2／E3。

## 开发与验证安排

Sol xhigh 是核心、Host、会话和准备入口的唯一编码所有者；根负责参考记录、后续选择、模型调度和结果解释。先完成 B–D 及必要窄检查，再冻结原生样本。一个实际模型控制入口、并发 1。StateMemBench 无官方可用数据时如实记录 NOT_RUN，不改题或换集补分；既有 MERIT 保持完整 arc、原生消息／session 边界和 checker，仅提供其真实能覆盖的机会。

A 的基线、接口与参考状态记录已完成，B–D 实现已冻结。受影响的八个窄测试文件 77 passed；复用跨进程 raw result 恢复、受管删除及会话缓存三个节点，3 passed。随后核对发现 gap 不变而 scope.item 改变会命中旧缓存，已把失效依据扩为真实查询依赖 `(critical_gap, scope.item)`；该修复后对应文件 7 passed。它是同一测试的复核，不是新增七个独立案例。相关 Ruff 和 mypy 均通过，确切命令和结果保存于[开发清单](../data/manifests/contextual-memory-v10-development.json)。没有运行全量 pytest、构建或 Product 检查。

已在部署的 vLLM 0.27.1／xgrammar 0.2.3 上编译 basis、notes 和终结外壳，12 个接受／拒绝语法探针全部符合预期，模型调用为零。探针覆盖 set、clear、null、gap 搜索、REVISE、continued 句柄、finish，以及缺 sidecar、混合外壳和非法 resolved 状态。缓存修复不改变这些 schema。

method v15、decision-basis-v1 和 contextual-json-action-v2 为实际实现身份；write v13、material view v9 和 operation v2 延续原合同。两份 v10 模板共同进入源码映射，准备入口逐臂生成配置身份并保留相同原始 arc/world/checker。新配置与旧 v9 checkpoint 不静默混用。[准备与运行命令](CONTEXTUAL_USER_MEMORY_V10_REPRODUCE.md)不依赖 ignored 的历史运行产物。

E 已在开发冻结后选定原有一个完整 MERIT arc，见[选择及机会清单](../data/manifests/contextual-memory-v10-selection.json)：5 个 episode、7 条原始消息、2 个依赖任务。各 episode 保留原始 session 重置；第 1、2 个 episode 各有两条消息，但第二条涉及另一订单。跨 episode 的金额变化能验证持久记忆更新，不能当作旧 active_decision 连续传播；只有 Host 在同轮实际采用旧卡并修改它时，才可能出现结构重核机会。不合并 session，不预告未来提问，不添加复用轮数。E4 没有自然的同一决策持续复用窗口，保持 NOT_RUN。

E1 已按同一原始初态顺序运行 notes 与 basis，运行前后源码及配置不变。原生结果为 5/5 与 3/5；两臂都完成 7 个 Host 轮次，但 basis 所有完整动作都为 state_delta:null，没有实际采用、gap query 或重核链。两次截断、业务失败与费用全部保留：51 次生成／452656 generation tokens／3955 embedding tokens，unknown=0、Judge=0。[详细结果](CONTEXTUAL_USER_MEMORY_V10_RESULTS_20260925.md)与[结果清单](../data/manifests/contextual-memory-v10-results.json)记录了语义失败和未运行项。E2/E3 没有适用前态，保持 NOT_RUN；工程窄检查不能补作真实语义链证据，完整 Goal 保持 active。
