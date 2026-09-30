# MiLAi v13.1 实验现状总结

日期：2026-09-30

源码身份：截至 `1787b60`（carrier 补丁提交）；报告自身的 Git 提交由后续报告提交固定。

## 当前结论

本轮已经取得工程链路证据和少量已曝光开发样本结果：正常开发门槛达到 R9 的 22/24；显式回执、持久化与有限恢复合同完成了局部机械或真实链路核查；旧来源上的等额配置实际试跑也已完成。

这些证据尚未显示研究优势。开发比较样本很小、来源已曝光，且使用同族本地 Judge；生命周期质量结果尚待语义复核并有大量中断。完整 P0–P8 目标保持 ACTIVE，Product 保持 NO_GO。

| 门禁 | 当前判断 | 依据与边界 |
|---|---|---|
| 工程证据 | 有若干限定通过 | SDK 持久化读回、机械合同、来源与成本对账已完成；P0、P1、P2、P3、P5仍有未满足项。60项要求中11项为 PASSED_SCOPED、26项为 PARTIAL、23项为 NOT_VERIFIED。 |
| 正常使用 | R9 门槛通过，整体仍部分完成 | 24例中22例达到预定正常门槛；两个更新版本失败，不能代替所有场景的使用验收。 |
| 研究支持 | 未通过 | 无未见正式集结果、无独立 Judge、无第二模型家族确认，也无足够证据支持优势或非劣。 |
| 产品发布 | NO_GO | 研究和产品发布是不同门禁；本总结不改变产品状态。 |

## 已完成的实测与工程证据

### P0–P8 阶段状态

| 阶段 | 当前状态 | 可支持的表述 |
|---|---|---|
| P0 | PARTIAL | 环境、来源暴露和账本有直接核查，完整冻结及正式分组未完成。 |
| P1 | PASSED_SCOPED / PARTIAL | R9 正常门槛22/24通过；完整 P1 仍有缺项。 |
| P2 | PARTIAL | 两个字段的有限支持合同已实测；历史送达与语义 guard 收益未证。 |
| P3 | PARTIAL | 强简单组、NoMemory和外部 baseline 有限实测；公平正式比较未完成。 |
| P4 | PASSED_SCOPED | 已曝光来源的因素诊断完成；类型独立收益未证明。 |
| P5 | PASSED_SCOPED / PARTIAL | SQLite恢复原语有限通过；Agent 生命周期对比和语义质量仍不完整。 |
| P6 | NOT_VERIFIED | Pilot身份仅预留，尚未运行或正式冻结。 |
| P7 | NOT_VERIFIED | 正式比较、独立评分和第二模型家族确认未完成。 |
| P8 | PARTIAL / NOT_VERIFIED | 有限反思和状态整理存在；统计、评分、复现包和论文收口未完成。 |

具体逐项状态以60项 requirements 及结果 manifests 为准；本表是阶段概览，不把局部证据提升为阶段整体完成。

### 正常使用和显式回执

R9 的正常开发检查覆盖24例、48条公开消息、48个实际进程，并对24个持久资源做了独立 SDK 读回。最终22/24达到预定门槛，owner 泄漏和虚假保存成功均为零；两个版本更新失败继续计入分母。R9 是开发门槛通过，不等于完整 P1 或研究门禁通过。[执行记录](V13_1_EXECUTION.md) · [R9结果](V13_1_D0_R9_RESULTS.md)

P2 的有限回执检查完成8案例臂、16条真实消息和16个独立进程，8个 Store/world 均经真实 SDK 重开核对。Field-grounded 的4条记录中，有限的 `status`、`label_status` 声明与观察相符；Ref-only 的4条不声称字段已验证。6次不合法正文拒绝及付费新提案都保留在记录中。

这只能说明两个公开字段的机械绑定和有限观察一致性。它没有验证正文、scope、notes、引文、世界真值或当前授权。后续查询没有检索并送达历史 bank；已记录的错误和 UNKNOWN 不能算作通过，也没有证据证明 Field-grounded 带来语义收益。[P2合同与结果](V13_1_P2_TYPED_RECEIPTS.md) · [结果清单](../data/manifests/v13-1-p2-typed-receipts-results.json)

### 等额配置开发比较

从8个旧来源组实际完成48个题对：B2、B3、公开 Scope 候选各两套配置。运行使用96个不同进程、48份独立 SDK 资源读回；另有48次本地 Qwen 同族 Judge 诊断。按事前规则，后续选择为 B2-a、B3-a、Ours_scope-a。

同族 Judge 的开发诊断成功率为：B2-a 在 scope、valid、personalized 上分别为3/4、1/2、2/2；B3-a 为3/4、1/2、2/2；Ours_scope-a 为4/4、2/2、2/2。其他候选及每项分母均见结果文档。每项样本数仅2至4，且来自已曝光开发来源；不能据此声称统计优势、非劣或泛化。

此处比较的维护节奏和形成方式并不相同，不能归因为单一表示变量。原生文本任务没有本项目的实际业务对象或字段绑定；来源存在也不能证明内容正确。因此这些结果不能证明 operational grounding、权限或恢复增益。[开发比较总结](V13_1_EQUAL_CONFIG_DEVELOPMENT.md) · [完整结果](../data/manifests/v13-1-equal-config-development-results.json)

### 生命周期采集和故障证据

旧冻结版本计划60条方法轨迹，已尝试45条：30条完成全部消息，15条中断，另15条未运行。完成消息不等于语义正确或完整 Lifecycle Success；原始最终回答仍需单独评分。

139个实际独立进程和45份 SDK 资源读回已对账。23次真实 SIGKILL 由进程返回码验证，分布为 W1 14次、W2 6次、W3 3次。原冻结的共同每消息12次生成额度跨重启累计；15条中断的首次终止原因分别为10条额度耗尽、2条输出截断、3条 native 证据关闭错误，均保留，没有补答或挑选最好结果。

其中 Mem0 matched 仅尝试3/6，native 为0/6，手动 UPDATE 扩展为0/6；这些路径后来因 Qdrant 已关闭后才采集快照的工程缺陷而隔离。取证确认相关资源里存在已持久化原生记录，但这没有修复原运行，也没有把它们重分类为通过。修正源码属于新的候选冻结，不能与旧冻结结果拼接。

原生／matched 的覆盖并不均衡，15条未运行也留在分母。当前证据只描述六个已曝光开发故事、一个工作流中的覆盖、成本和机械效果，不支持 Field-grounded 优于简单回执投影，也不支持把原生与 matched 差异归因于字段机制。[P5覆盖总结](V13_1_P5_COMPARISON_OLD208_COVERAGE.md) · [覆盖结果清单](../data/manifests/v13-1-p5-comparison-old208-coverage-results.json)

另有一个限定机械恢复结果：在协作串行 SQLite 条件下，真实 W1 结果可由独立查询区分，W2 可重开同一资源；另在 clean 副本执行真实 UPDATE、W3 硬退出和精确回执重放。该原语范围有限，不代表通用 exactly-once、外部并发或完整 P5 Agent 质量。[P5生命周期结果](V13_1_P5_LIFECYCLE.md) · [requirements](../data/manifests/v13-1-requirements.json)

### 强简单对照与最近邻

B0–B6 强简单对照共运行238个不同进程，224条完成、7条 owner 拒绝、7条真实容量拒绝；42份 SDK 资源读回一致。runner 的旧 HTTP 计数错误保留，Root 以完整 response/error wire 单独对账。NoMemory 的当前业务工具查询也可完成，说明部分任务并不需要长期记忆；未知答案不计为语义成功。[强简单对照](V13_1_P3_CONTROLS.md)

P4 清洁列因素诊断没有显示类型单独带来增益；来源引用仍可能错误映射用户意图。最近邻审计是源码与主张边界检查，不含原生复现或可比较的独立类型收益。[P4类型与scope](V13_1_P4_TYPE_SCOPE.md) · [最近邻边界](V13_1_NEAREST_WORK_BOUNDARIES.md)

## 成本与资源

等额配置比较阶段新增108次运行 generation、200,166 generation tokens、96次 embedding、28,728 embedding tokens；本地 Judge 另新增48次 generation、78,556 tokens。该阶段账本快照为6,918次 generation、13,066,995 generation tokens、454,563 embedding tokens。

旧冻结生命周期批次新增543次 generation、2,675,299 generation tokens、295次 embedding、83,740 embedding tokens；该批次收口时账本为7,461次 generation、15,742,294 generation tokens、538,303 embedding tokens，generation 与 embedding unknown usage 均为0。该批次新增 Judge 为0；v13.1 累计同族 Judge 为48次、78,556 tokens，已包含在当前 generation 累计值内。

经 Root 只读核对，原连续账本当前累计为7,461次 generation、15,742,294 generation tokens、538,303 embedding tokens，SHA256 为 `165f89487c70d988bca88b58d8f84960609e270c4d0da26cedb8fd8d4904fb7b`，generation 与 embedding 的 unknown usage 均为0。相对 v13 起点，delta 为1,316次 generation、4,335,208 generation tokens、121,373 embedding tokens；包含48次同族 Judge。等额配置阶段的6,918次账本读数是更早快照。价格、美元费用、GPU 小时和完整 I/O 覆盖均未知，不作估算。[当前实验快照](../data/manifests/v13-1-experiment-status-20260930.json) · [等额配置成本](V13_1_EQUAL_CONFIG_DEVELOPMENT.md) · [P5成本和覆盖](V13_1_P5_COMPARISON_OLD208_COVERAGE.md)

60项 requirements 的11项 PASSED_SCOPED 是各自限定范围内的通过，不能作为完整完成率或“11/60 已完成”的汇总；26项仍 PARTIAL，23项 NOT_VERIFIED，完整 P0–P8 继续 ACTIVE。[requirements 状态清单](../data/manifests/v13-1-requirements.json)

冷进程 wall time、CPU 与部分存储／I/O 有记录，但 I/O 覆盖不完整；不能从这些数据推算 GPU 小时或美元。额度耗尽属于原预算设置的真实结果，应与语义错误分开记录。

## 未完成工作与硬限制

### 来源池和正式比较

当前官方 MemSyco 来源排除历史已曝光及旧预留来源后，新 Pilot-S 预留前可用行数为：`contextual_scope_control` 270、`valid_memory_selection` 63、`personalized_memory_use` 95。后两项已经不足规划要求的每任务100题。

预留每任务20题的新 Pilot-S 身份后，整组连通组件共117行计入 development，剩余250、7、54题。新 Pilot-S 的题目和 gold 尚未读取；MERIT 的65–82 seed 也只预留，尚未生成 arc 或运行 pilot。用户已确认没有额外未曝光官方来源，当前来源缺口因此仍在。[来源容量总结](V13_1_SOURCE_AVAILABILITY.md) · [机器清单](../data/manifests/v13-1-memsyco-source-availability.json) · [Pilot身份预留](../data/manifests/v13-1-pilot-prospective-selection.json)

Pilot-S、Pilot-M、Pilot-L、正式冻结及 P6–P8 尚未完成。原规划要求的正式 MemSyco、MERIT 和生命周期规模没有被开发轨迹替代；正式测试题不得用于开发提示。来源不足、服务缺失或负结果都没有自动缩小完整目标。[原规划（第9节）](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_v13_1.md) · [完整requirements](../data/manifests/v13-1-requirements.json)

### Judge、第二模型家族和最近邻

没有可用官方 MemSyco Judge、独立 Judge 或第二模型家族服务。7860 与7862是同一 Qwen3.6-35B-A3B-FP8 家族的不同工具服务模式；本地同族48次 Judge 仅用于开发诊断，不能替代独立评审或官方分数。Luna 只负责整理实验总结，不作为实验第二家族或独立 Judge。用户已确认无额外服务，要求继续其余独立工作；这些缺口不重复询问，也不改写验收要求。[服务可用性清单](../data/manifests/v13-1-external-service-availability.json) · [发布快照](../data/manifests/v13-1-experiment-status-20260930.json)

最近邻工作只完成论文、源码与主张边界核查，没有原生复现或原作者分数核验。Hindsight 已涉及事实／经历、综合摘要、信念及 retain／recall／reflect；HiMem 已涉及 Episode／Note 层次和冲突再整合。仅使用类型名称或“证据与推断”标签不能构成独立新颖性，也没有优于这些系统的证据。[最近邻边界](V13_1_NEAREST_WORK_BOUNDARIES.md) · [只读审计](../data/manifests/v13-1-nearest-work-readonly-audit.json)

### 第二个业务工作流

文稿审批与发布工作流已通过源码和机械检查：真实 SQLite 文稿版本／摘要、独立审批和 sandbox 发布记录都有明确合同；编辑会使旧审批失效，审批和发布检查当前版本／摘要。该记录是 sandbox 内持久化结果，不代表向外部受众送达。

文稿工作流的14种方法设置共84条预定开发轨迹；所有质量臂使用同一每消息24次生成额度，联合预算另列每消息12次。实际质量运行尚未开始，当前 prepare 为零 HTTP。真实执行前仍需冻结完整源码、CLI、环境、输入、提示、schema、时序和评分合同；冻结完成后继续已授权的文稿实跑。文稿开发故事不等于新的 Pilot-L12 或正式60个基础任务。[文稿工作流](V13_1_DOCUMENT_WORKFLOW.md) · [源码验收](../data/manifests/v13-1-document-source-acceptance.json) · [开发候选与预算](../data/manifests/v13-1-document-development-candidates.json)

源码截至提交 `1787b60`，carrier patch 的机械验收已通过：patch 明确标记 `observed_events_v1`，旧 carrier 仍为默认，native 算法保持不变。Root 使用两个实际已安装 SDK 的 socket 禁止／MockTransport 测试复跑，2项通过；另核对3个 Source 文件及保留日志的9个哈希，ledger 完全不变。[patch 验收清单](../data/manifests/v13-1-mem0-observed-carrier-source-acceptance.json)

这是 patch 的局部验收，不是新的完整模型 freeze；新的完整 freeze 和实际模型运行仍为 NOT_RUN。原 `2672373` 提交的209文件联合身份未改；旧准备记录和原运行失败继续保留。修复后的运行须在新的完整源码、输入和执行身份下单独报告。

## 接下来需要完成的工作

1. Root 已核查当前账本与结果证据；报告提交时继续保留旧冻结结果与新候选的身份边界。
2. 为文稿质量运行完成完整源码、CLI、环境、输入与执行冻结，然后继续已授权的实跑；carrier patch 的局部验收不能替代该 freeze。所有 HTTP 和账本仍由 Root 管理。
3. 对已完成的生命周期消息做独立语义审查，同时保留中断、额度耗尽、截断、工程错误和未运行分母。
4. 继续已授权且不依赖缺失服务的独立 P0–P8 工作；正式样本不足、独立 Judge 缺失和第二家族缺失保持显式未完成。
5. 在来源、模型、统计和复现门禁得到直接证据之前，维持完整目标 ACTIVE 与 Product NO_GO，不提出研究优势或发布结论。

本总结由 Luna 根据仓库文档与 manifests 整理，Root 已核查原连续账本和提交前实验事实。报告整理不新增实验 HTTP 调用。
