# v13.2 执行记录

2026-10-01。状态 **ACTIVE**，完整范围为原计划D0–D5及其条件门禁，不以首批、机械测试或开发样本代替完成。

用户明确要求详细阅读并执行[589行原计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_2.md)。
原文SHA256为 `84c89a3e8dbb1f23ad4478e8a809f264c76c430b537b0ea1501671230681a79a`，
字节未改；DESIGN_ONLY保留为原设计状态，不覆盖当前执行授权。

远端main已fetch并用ls-remote独立核对为 `95bf708bfd8aac9f7855485166e3bf739928b949`。
新分支为 `feat/lab-evidence-incremental-v13-2-20261001`，工作树为
`/cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v13-2`。
用户入口主工作树及v13.1未提交改动未动。[入口冻结](../data/manifests/v13-2-entry-freeze.json)
记录原计划、旧cohort、源码差异和真实账本。回滚基线是95bf708，尚未推送此分支或合并远端。

[完整48项验收映射](../data/manifests/v13-2-requirements.json)覆盖D0–D5、E0–E4、恢复、
预算、来源分组、正式统计、迁移、长程及条件消融。旧v13.1 P0–P8 requirements和实验结论
原样保留；新增amendment映射只修订实施路径，不把未证明项改为通过。

## 已取得的直接证据

[D0结果](V13_2_D0_PRIOR_COHORT.md)重新读取并核对139份旧回执和139份HTTP trace，
保留101回答，复核全部30完整轨迹。原60计划仍是45尝试、30完整、15中断、15未运行。
原四条反例保留，另确认一次初始操作与后续UNKNOWN的错误归属，并定位Field原卡修订失败、
额外CREATE和notes误解。Root复核只作事后开发诊断，独立语义评分仍未完成。

旧cohort逐请求费用对上543 generation／2,675,299 tokens与295 embedding／83,740 tokens。
其中126次writer／619,934 tokens。160次紧接记忆拒绝的请求／951,349 tokens是重叠子集，
不额外计费、不称全部为可消除浪费。方法、实际源、首个记忆拒绝、首个终止和原回执hash逐项留存。

D1已实现opt-in `memory_mutation_contract='event_bound_v1'`：可信runner绑定实际当前事件，
多事件必须明确选来源；user/tool/实际最终assistant保持角色与原hash，助手建议不能冒充用户决定。
search/read返回持久化候选句柄，绑定owner、record、读时revision和支持源hash；提交再核对，
交错更新返回冲突。单个相似结果不自动选择，提交前不临时填最新版本。旧默认为legacy。

D1来源/候选/交错更新/重开/实际runner脚本17项新窄测试通过；旧service/P5组87项、
旧prepare/schema/循环子集20项通过。真实安装Mem0 Memory SDK的关闭前采集、错误关闭、
独立重开及observed_events_v1载体4项通过，另实际update/get/history重开1项通过。
这些SDK检查禁止网络、使用有限向量/离线provider，只证明工程合同，不证明原生抽取或模型质量。
阶段记录在ignored `artifacts/v13-2-d1/source-checks.json`；每命令执行hash当时未保存，
其末尾source snapshot不能冒称所有检查共同使用的执行SHA。D2变更检查已逐命令保存执行前后身份及原日志。

D2确定性投影工程阶段已通过100项相关测试、四文件mypy、affected ruff和package边界。
[阶段验收](../data/manifests/v13-2-d2-observation-acceptance.json)记录各命令执行前后源码/测试身份与原stdout hash。
同源多对象/多字段、缺失与显式清除、迟到/不可比/同版本冲突、真实预订partial和文稿版本域通过。
实际持久Store部分写入失败保持pending，独立重开只重放投影；此证据不替代真实进程W2 crash或模型E1。

## 来源组与后续研究边界

[来源amendment](../data/manifests/v13-2-source-group-amendment.json)在任何新pilot内容读取前
从既有metadata-only catalog导出431个组件和成员图，原曝光及117条新pilot预留成员继续排除，
MERIT旧0–64及预留65–82不洗回未见集。没有回收预留样本，也没有打开新问题或gold。

| 任务 | 未预留行 | 独立组件 |
| --- | ---: | ---: |
| Scope | 250 | 250 |
| Valid | 7 | 2 |
| Personalized | 54 | 53 |

Valid七行只有两组件，不能支撑充分独立的更新验证或5个百分点非劣声明。
新pilot和正式规模尚未选择，须按真实独立组及pilot配对变异事前冻结，不以开发集替代正式结果。
独立Judge和第二模型家族仍不可用，按原计划继续独立工作；不默认下载、购买或部署替代服务。
已生成固定rubric、方法显式标签移除且顺序固定的审查包，但尚无独立审查结果。

## 当前工作与剩余门禁

D2工程阶段已接受；源码负责人继续实施D3一次有界公共预取、source→record反链、小patch、一次语义边界和Host提交去重，
必要窄检查后固定E0正常24及E1/E2小型真实自由Host诊断。此前未启动v13.2模型实验。E1共同固定观察流已由4个真实应用子进程生成：各预订一次、独立重开只查询；四设置的形成/交付检验尚未运行。
运行后证据collector已在旧R9核对48个实际HTTP最终回答及107次／170,905 tokens；篡改、缺失、畸形回包保持未验证，不自动语义评分。
D4同能力四臂、第二工作流24新冻结开发轨迹与12/24分轨仍未运行。
D5新pilot、正式独立来源比较、公开任务、独立评分、第二家族、统计和完整复现仍未完成。
相关机制只有满足原门禁才消融或扩大；负结果要求追首断点/一般修复，不能删失败或补答案。
[开发评分标准](../data/diagnostics/v13-2-small-development-rubric.json)已在新模型输出前固定；
[配对统计草案](../data/manifests/v13-2-statistical-design.json)固定主要比较、5pp界、依赖聚类和缺失上下界。
最终正式样本数和运行身份须由新pilot精度与实际独立来源事前补齐；该草案不算正式统计完成。

## 账本与验证边界

权威连续账本仍是原checkout `MiLAi-Lab/artifacts/ser-v20/budget.json`。
v13.2入口为7,946 generation／20,341,038 charged generation tokens／717,188 embedding tokens；
生成已知20,310,651，保守未知费用30,387，unknown usage为1；embedding unknown为0。
[历史账本差额审计](../data/manifests/v13-2-historical-ledger-bridge.json)将旧快照到入口的485次生成对到484次有响应请求／4,568,357已知tokens及1次30,387保守未知费用；449次embedding／178,885 tokens也与差额一致。旧文稿44份completed回执是完成消息数，不是完整轨迹数；缺响应请求未推定完成或归零。入口表遗漏的20个源码/config差异已按两个提交的实际字节补齐并保留修订身份。v13.2当前新增实验generation/embedding均0，账本hash仍等于入口。
价格、美元和GPU小时未测。所有新调用、失败、重启、维护及评审继续本账本，真实HTTP串行。

两个D0/source-group分析工具ruff通过，实际tools边界检查通过；现存6项grandfathered依赖未新增。
D1目标static/mypy和package边界通过，未跑全suite、build、模型质量或远端CI。
全部改动属于Lab研究opt-in合同；Product API、权限、Schema和Canonical未改，Product仍NO_GO。
没有把代码存在或局部测试通过表述为方法优势或发布就绪。
