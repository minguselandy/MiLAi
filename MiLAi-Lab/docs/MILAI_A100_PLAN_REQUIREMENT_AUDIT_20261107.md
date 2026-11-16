# A100原763行计划：逐项证据审计（执行中）

完整原计划763行已逐行归入对应标题/要求单元，并绑定现有实际证据文件；这份初审
不是实验完成证书。外部全量、完整项目成本、最终论文及最终审计仍未完成，目标保持active。
依据检查点a8e71c81/v66；后续实际进程进展仍由原progress入口记录。

`DONE_WITH_LIMITATIONS`表示对应范围有实际证据，附带的统计/曝光/计量限制保留。
`CONDITIONAL_NOT_TRIGGERED`与`DONE_AND_CONDITIONAL_STOP`按原计划的有信号门槛
处理，未用扩量、额外seeds或A→B凑满拟合上限。`PARTIAL`/`IN_PROGRESS_EXTERNAL`
明确仍缺结果；背景/模板与贡献方向不自动成为科研成功。各单元权重不同，不计算完成百分比。

主结果与限制见[完整质量结果](MILAI_A100_CONFIRMATION256_RESULTS_20261107.md)和
[操作/Source交付/推理成本](MILAI_A100_CONFIRMATION256_OPERATIONS_COST_20261107.md)。
原生机械关闭回执早期的quality-pending字段保持历史原样，后续语义与统计由分别闭合
的全量结果绑定，不回写旧首结果。A早期一次多余重复调用、源范围/指南时序修正和
只读metadata预读失败全部保留，不能概括为全项目从未失败或重复。

| 原计划行 | 标题/要求 | 当前处置 | 证据范围与剩余工作 |
|---|---|---|---|
| 1–10 | MiLAi 详细开发实验计划：2×A100 40GB | BACKGROUND_OR_REFERENCES | 原计划标题、上下文或参考资料；不凭参考链接推断新实验已执行。 |
| 11–12 | 1. 执行摘要 | PARTIAL | 功能/机制/自主Host与256确认已有结果；完整外部与全成本/论文尚未闭合。 |
| 13–22 | 1.1 本轮要交付什么 | PARTIAL | 功能/机制/自主Host与256确认已有结果；完整外部与全成本/论文尚未闭合。 |
| 23–36 | 1.2 推荐工作顺序 | PARTIAL | 功能/机制/自主Host与256确认已有结果；完整外部与全成本/论文尚未闭合。 |
| 37–46 | 1.3 本轮成功的层级 | CLAIM_LIMITATION | 五个成功层级分别判断：功能/机制不替代任务、独立泛化或实用；确认主seedCI跨零，三seed主C均值下降，不采用。 |
| 47–48 | 2. 最新状态与本次源码核验修正 | BACKGROUND_PRESERVED | 历史E1—E5事实与已有执行器复用；不将旧失败或已试目标重包装为新成果。 |
| 49–62 | 2.1 当前需要保留的实验事实 | BACKGROUND_PRESERVED | 历史E1—E5事实与已有执行器复用；不将旧失败或已试目标重包装为新成果。 |
| 63–75 | 2.2 已有功能应直接复用 | BACKGROUND_PRESERVED | 历史E1—E5事实与已有执行器复用；不将旧失败或已试目标重包装为新成果。 |
| 76–79 | 2.3 训练入口与推理入口需要分开判断 | BACKGROUND_PRESERVED | 历史E1—E5事实与已有执行器复用；不将旧失败或已试目标重包装为新成果。 |
| 80–81 | 3. 两张 A100 40GB 的资源规划 | DONE_WITH_LIMITATIONS | 显式独立单卡、精度、完整窗口和计量已用于真实训练；Host保持单worker；有效长上下文与Kernel忙时不由编码上限推断。 |
| 82–95 | 3.1 默认调度 | DONE_WITH_LIMITATIONS | 显式独立单卡、精度、完整窗口和计量已用于真实训练；Host保持单worker；有效长上下文与Kernel忙时不由编码上限推断。 |
| 96–118 | 3.2 起始训练配置 | DONE_WITH_LIMITATIONS | 显式独立单卡、精度、完整窗口和计量已用于真实训练；Host保持单worker；有效长上下文与Kernel忙时不由编码上限推断。 |
| 119–126 | 3.3 显存与长度边界 | DONE_WITH_LIMITATIONS | 显式独立单卡、精度、完整窗口和计量已用于真实训练；Host保持单worker；有效长上下文与Kernel忙时不由编码上限推断。 |
| 127–134 | 3.4 DDP 和精确续训的地位 | CONDITIONAL_NOT_TRIGGERED | 未将DDP或optimizer/RNG精确续训作为首轮前提；既有权重开始称warm-start，未引入通用恢复/重试平台。 |
| 135–136 | 4. 开发包 P0：让双单卡训练真实可用 | DONE_WITH_LIMITATIONS | 两臂各512行/32更新、28稳态更新；BF16实测2.344645倍吞吐，重载保留一次近tie翻转；不声明任务收益或12k有效上下文。 |
| 137–152 | 4.1 最小代码修改 | DONE_WITH_LIMITATIONS | 两臂各512行/32更新、28稳态更新；BF16实测2.344645倍吞吐，重载保留一次近tie翻转；不声明任务收益或12k有效上下文。 |
| 153–160 | 4.2 BF16 实现要点 | DONE_WITH_LIMITATIONS | 两臂各512行/32更新、28稳态更新；BF16实测2.344645倍吞吐，重载保留一次近tie翻转；不声明任务收益或12k有效上下文。 |
| 161–170 | 4.3 32-update profile | DONE_WITH_LIMITATIONS | 两臂各512行/32更新、28稳态更新；BF16实测2.344645倍吞吐，重载保留一次近tie翻转；不声明任务收益或12k有效上下文。 |
| 171–184 | 4.4 必要验证与记录 | DONE_WITH_LIMITATIONS | 两臂各512行/32更新、28稳态更新；BF16实测2.344645倍吞吐，重载保留一次近tie翻转；不声明任务收益或12k有效上下文。 |
| 185–186 | 5. 数据体系：增长的是有效信息，不只是行数 | DONE_WITH_LIMITATIONS | 实际TRAIN64、DEVELOPMENT64及CONFIRMATION256独立论文身份分配；nativeDEV185/TRAIN71与研究角色分列；历史Source曝光限制保留。 |
| 187–199 | 5.1 现有可用资产 | DONE_WITH_LIMITATIONS | 实际TRAIN64、DEVELOPMENT64及CONFIRMATION256独立论文身份分配；nativeDEV185/TRAIN71与研究角色分列；历史Source曝光限制保留。 |
| 200–207 | 5.2 数据用途与分割 | DONE_WITH_LIMITATIONS | 实际TRAIN64、DEVELOPMENT64及CONFIRMATION256独立论文身份分配；nativeDEV185/TRAIN71与研究角色分列；历史Source曝光限制保留。 |
| 208–217 | 5.3 条件数据扩容阶梯 | CONDITIONAL_NOT_TRIGGERED | A-10k实际完成；20k及32k/64k需既定条件/任务收益，当前不满足，不伪造新信息或补标签。 |
| 218–230 | 5.4 完整动作反馈扩容阶梯 | DONE_AND_CONDITIONAL_STOP | 57状态READ覆盖补齐，C真实已读集合切片及B64完成；B192/B256为有信号后候选，当前B任务结果不支持扩量。 |
| 231–232 | 6. 开发包 A：条件负例采样修复 | DONE_WITH_LIMITATIONS | A0/A1各44868实际行/2805更新；原生负例条件5→9540；真实任务C均15/32，无组成收益；不以辅助分数采用。 |
| 233–242 | 6.1 修改位置与具体问题 | DONE_WITH_LIMITATIONS | A0/A1各44868实际行/2805更新；原生负例条件5→9540；真实任务C均15/32，无组成收益；不以辅助分数采用。 |
| 243–254 | 6.2 选择优先级 | DONE_WITH_LIMITATIONS | A0/A1各44868实际行/2805更新；原生负例条件5→9540；真实任务C均15/32，无组成收益；不以辅助分数采用。 |
| 255–272 | 6.3 A0/A1 训练合同 | DONE_WITH_LIMITATIONS | A0/A1各44868实际行/2805更新；原生负例条件5→9540；真实任务C均15/32，无组成收益；不以辅助分数采用。 |
| 273–280 | 6.4 A 的评测与决策 | DONE_AND_CONDITIONAL_STOP | 128新条件族按已有依据保留unknown；A两臂旧32真实任务15/32，A1−A0零增益，不进20k/额外seeds/J。一次早期多余重复调用已保留成本并恢复更早首结果，非宣称全项目从未重复。 |
| 281–282 | 7. 开发包 B：完整参数反馈，优先使用既有候选 | DONE_WITH_LIMITATIONS | B64的128状态/384绑定并集全部首结果保留，358新执行/26复用；两面板同初始化、528slots/1056draws/66更新；原有52READ补采完成。 |
| 283–290 | 7.1 候选选择的最小增量 | DONE_WITH_LIMITATIONS | B64的128状态/384绑定并集全部首结果保留，358新执行/26复用；两面板同初始化、528slots/1056draws/66更新；原有52READ补采完成。 |
| 291–306 | 7.2 两种比较不能混在一起 | DONE_WITH_LIMITATIONS | 共享实际分支监督面板B0/B1已完成，baseline只计实际一次；等采集槽位的效率实验是另一可选问题，当前不作效率优势主张。 |
| 307–312 | 7.3 首步与后续执行 | DONE_WITH_LIMITATIONS | B64的128状态/384绑定并集全部首结果保留，358新执行/26复用；两面板同初始化、528slots/1056draws/66更新；原有52READ补采完成。 |
| 313–324 | 7.4 反馈语义 | DONE_WITH_LIMITATIONS | B64的128状态/384绑定并集全部首结果保留，358新执行/26复用；两面板同初始化、528slots/1056draws/66更新；原有52READ补采完成。 |
| 325–337 | 7.5 新数据应覆盖的真实决策条件 | DONE_WITH_LIMITATIONS | 按真实可见条件/已知证据/Source角色时间和预算执行；静态QASPER与D更新轨迹分别解释，不凑每题全条件或将未知补为负例。 |
| 338–355 | 7.6 B0/B1 训练合同 | DONE_AND_CONDITIONAL_STOP | 两臂按原E3目标和同slot预算真实拟合；任务没有改进，不追加B192或重复已试answer-first配方。 |
| 356–357 | 8. 开发包 C：材料集合与原文粒度 | DONE_WITH_LIMITATIONS | 原菜单的C8及补充7个真实已读池完成，完整READ→材料→Host链分列；没有足够表达缺口证据，不扩菜单或为凑额度补执行。 |
| 358–363 | 8.1 先定位“没选中”还是“菜单没有” | DONE_WITH_LIMITATIONS | 原菜单的C8及补充7个真实已读池完成，完整READ→材料→Host链分列；没有足够表达缺口证据，不扩菜单或为凑额度补执行。 |
| 364–371 | 8.2 仅在具体表达缺口时扩展有界候选 | CONDITIONAL_NOT_TRIGGERED | 既有完整菜单已做实际对照，未发现支持新增add/remove/swap的具体表达缺口；原菜单和完整绑定保持。 |
| 372–377 | 8.3 集合训练与指标 | DONE_WITH_LIMITATIONS | 原菜单的C8及补充7个真实已读池完成，完整READ→材料→Host链分列；没有足够表达缺口证据，不扩菜单或为凑额度补执行。 |
| 378–379 | 9. 开发包 D：持续更新与旧 View＋增量读取 | DONE_WITH_LIMITATIONS | 旧8/新32×2流程×5请求×3策略完成；known-View及旧输出可检索性对照已保留首结果；后者父exec观察缺失不臆造退出码，CPU未知范围保持。 |
| 380–385 | 9.1 当前控制流的具体限制 | DONE_WITH_LIMITATIONS | 旧8/新32×2流程×5请求×3策略完成；known-View及旧输出可检索性对照已保留首结果；后者父exec观察缺失不臆造退出码，CPU未知范围保持。 |
| 386–393 | 9.2 最小实验路径 | DONE_WITH_LIMITATIONS | 旧8/新32×2流程×5请求×3策略完成；known-View及旧输出可检索性对照已保留首结果；后者父exec观察缺失不臆造退出码，CPU未知范围保持。 |
| 394–405 | 9.3 三个分开的评测因素 | DONE_WITH_LIMITATIONS | 无关增长/事实更新/旧输出回流分别有冻结协议与真实对照；32族统计不把320请求视为320独立来源；不默认补1024额度矩阵。 |
| 406–407 | 10. 实验矩阵、训练次数与两卡波次 | DONE_WITH_LIMITATIONS | A/B各两次首轮拟合，入选E3补seed1/2；三seed仅固定E1初始化下训练随机性，非完整训练链三seed；不选最好seed。 |
| 408–422 | 10.1 主矩阵 | DONE_AND_CONDITIONAL_STOP | P0/A/B/C/D实际推进；J仅在A与B都有任务信号时触发，当前不触发；12次拟合是条件上限而非必须凑满。 |
| 423–428 | 10.2 数据规模与训练计算量应分开比较 | CONDITIONAL_NOT_TRIGGERED | 未把行数扩展、重复draw、tokens或FLOPs声称同时匹配；后续规模曲线未由本轮结果触发。 |
| 429–441 | 10.3 计算预算工作表 | PARTIAL_FINAL_COST | P0/A/B和内部Host已有实际draw/tokens/CPU/wall；外部实际调用、最终GPU区间及所有准备/筛选/分析阶段总成本仍需汇总。 |
| 442–447 | 10.4 训练 seed 与采集 seed | DONE_WITH_LIMITATIONS | 训练RNG、公共初始化与Host随机生成明确区分；固定u32，不因确认或外部表现换seed/checkpoint。 |
| 448–449 | 11. 评测、统计与采用标准 | PARTIAL | 内部256×4完整质量、材料、gains/losses、三seed族内均值与20k家族CI闭合；LME/Mem2Act完整外部结果仍执行。 |
| 450–462 | 11.1 四层评测 | PARTIAL_EXTERNAL | 离线、同before机制、自主Host与外部四层分列；内部各层完成，外部451×2/400×2仍缺完整预测/评分/审计/归档。 |
| 463–474 | 11.2 来源与样本量规划 | DONE_WITH_LIMITATIONS | 实际保留全256论文家族，未因结果扩N；规划约640仅假设+5pp近似功效，不是256保证；旧64保留query资格另审，仍未打开语义。 |
| 475–482 | 11.3 主指标与解释 | DONE_WITH_LIMITATIONS | 来源族宏平均、配对增减/CI、材料、实际操作与成本并列，三seed族内聚合；作者/掩码/指南时序限制保持，不声明胜出或等效。 |
| 483–490 | 11.4 外部评测范围 | IN_PROGRESS_EXTERNAL | LME451仅首119已封存并保留6ReaderF，006运行未尝试尾部；主方法与Mem2Act均须按既有协议实际执行，不以组件探针代替全量。 |
| 491–492 | 12. 全成本、里程碑与停止规则 | PARTIAL | 停止规则已用于A/B不扩量；已关闭native/CPU阶段按原账本一次计量，外部与全项目成本、M5交付仍待完成。 |
| 493–500 | 12.1 成本分项 | PARTIAL_FINAL_COST | 已付idle1..32与关闭native阶段不重复累计；新增离线计时待实际空闲窗口，正在运行外部整段成本尚未闭合，未知开销不记零。 |
| 501–513 | 12.2 建议里程碑 | PARTIAL_M5 | M0至M4有相应实际证据和边界；M5的外部全量、全成本及最终论文/整体图表仍未交付。 |
| 514–523 | 12.3 停止或改变方向的规则 | APPLIED_CONTINUOUSLY | 已依据实际反馈停止无信号扩量/额外loss；确认结果不用于同面板反复挑选；Reader输出失败保留，仅显式执行nativeNOT_RUN尾部。 |
| 524–529 | 13. 命令与配置模板 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 530–539 | 13.1 一次性资源记录：只读 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 540–559 | 13.2 当前训练入口已有参数 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 560–585 | 13.3 P0 完成后的 A 单卡模板 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 586–611 | 13.4 B 反馈训练模板 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 612–646 | 13.5 现有真实分支准备与执行 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 647–667 | 13.6 现有 handoff-only 机制入口 | BOUND_TEMPLATES | 模板参数按实际run/config绑定，已用真实训练、分支和handoff入口；不是额外必须逐字重跑的实验矩阵。 |
| 668–669 | 14. 交付物、论文主张与开发边界 | PARTIAL | 协议、代码、内部结果与PNG/PDF已保留；全外部、全成本、最终论文/总体图表未完成，贡献方向不等同已证实优势。 |
| 670–686 | 14.1 沿用现有产物体系 | PARTIAL_FINAL_DELIVERABLES | 延续原ignored产物/单一账本及Git摘要、协议与代码，内部两个报告和科学图已生成；全项目最终结果包仍待外部闭合。 |
| 687–694 | 14.2 可形成的贡献 | CLAIM_LIMITATION | 剩余取证价值、联合获取/交付、持续更新是待证贡献方向；开发面板信号不自动成为独立泛化或学习策略胜出结论。 |
| 695–700 | 14.3 本轮明确保持的开发原则 | APPLIED_WITH_RETAINED_REFLECTIONS | 沿原Host/权限/来源/计量，无SHA门禁、新服务或第二账本；保留所有已知失败和早期A多余重复的反思，不把后来的更好答案当首结果。 |
| 701–702 | 参考资料 | BACKGROUND_OR_REFERENCES | 原计划标题、上下文或参考资料；不凭参考链接推断新实验已执行。 |
| 703–719 | MiLAi 固定提交 | BACKGROUND_OR_REFERENCES | 原计划标题、上下文或参考资料；不凭参考链接推断新实验已执行。 |
| 720–728 | 官方硬件/框架资料 | BACKGROUND_OR_REFERENCES | 原计划标题、上下文或参考资料；不凭参考链接推断新实验已执行。 |
| 729–763 | 本轮采用的研究机制 | BACKGROUND_OR_REFERENCES | 原计划标题、上下文或参考资料；不凭参考链接推断新实验已执行。 |

逐项实际路径与原计划行绑定见[机器可读审计](../data/manifests/a100-plan-requirements-audit-20261107-v1.json)。
全部原文保留在ignored `artifacts/a100-development-20261104/original-plan-requirements-audit-v1.json`，
使用完整UTF-8文本相等性与行位置，不使用SHA/内容指纹。原计划参考链接仅作为历史引用
保留，本审计没有另行浏览论文、打开保留query/原生TEST语义、调用模型或打开/写入账本。
