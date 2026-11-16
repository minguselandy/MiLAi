# 原763行计划：当前证据与必须继续的工作

**2026-11-10 更新**：[v187检查点](MILAI_A100_DEVELOPMENT_CHECKPOINT_20261110.md)已实际核对
primary400的294 COMPLETED/106 FAILED、owner支付退出与原父子进程消失。
下文v186运行状态及原671块机器索引保持其历史时点；primary canonical closure/全Source与NN审计、
两方法评分/审计/归档、最终费用论文及全763行完成审计仍未完成。

完整原文与最初冻结UTF-8逐字一致，763行均归入不重叠的671文本块；438个非空块包含73个
标题、表格行、段落、列表及8个命令/结构代码块。这是**执行中的证据对照，不是完成证明**。
不同块权重不同，不计算“完成百分比”。[机器索引](../data/manifests/a100-plan-current-evidence-20261109-v2.json)保留每个
非空块行号、具体处置、关联原文合同、证据路径与命令参数；全部字面原文留在ignored产物。

上一版v66初审的待办已经过时，但原件保持。当前P0/A/B64/B修复/C/D共78项具体合同已有实际
审计，LME两451的六个原生关闭及旧64保留query评测也已闭合；Mem2Act800真实首结果、最终
全项目成本与论文/整体图表仍未齐。v186新增的实际闭合证据见[固定400全量审计](MILAI_A100_MEM2ACT_FIXED400_NATIVE_RESULTS_20261109.md)：
fixed400/全Source已通过、idle138已付，原primary400现实际运行；原671块机器索引保留其v183时点，不由本状态更新宣布763行完成。不得由标题、文件存在或绿色检查反推全目标完成。

## 新核对的来源分组、冻结与训练随机性

[分配/冻结机器凭据](../data/manifests/a100-plan-allocation-freeze-audit-20261109-v1.json)重建实际parent allocation：

- 从已用64个TRAIN论文之外按既有TRAIN顺序取B64；旧DEV32、旧用TRAIN64、新B64、DEV64、
  CONFIRM256各论文集合无交叉，按整个paper分组而非问句/状态/seed拆分。
- unused原生DEV249中的前64为研究DEVELOPMENT；剩余DEV先于unused原生TRAIN504，
  按固定原顺序取确认256，恰为原生DEV185/TRAIN71。原数据分区与本研究角色分开报告。
- 2026-11-06 08:29:45 UTC冻结方法/checkpoint/Host/预算/N，08:51:30开始选定256语义投影；
  native依据08:59:10在首次baseline模型调用前记录。它不是所有最终Source作者指南都在所有答案前完成。
- 通过同一冻结runtime的纯exporter重导出全部256完整histories和offline references，18932个
  Source单元、第一native问题、正文/role/顺序与全部heading/paragraph/caption逐字相同。
  只读取原train/dev成员，未打开nativeTEST；没有gold Source过滤、给定检索query或修补缺表格。
- E3 seed1/2的完整argv仅training seed/output/compute phase改变，45项run配方字段、数据长度
  与原seed0相同，固定E1-u16起点、FP32两GPU、完整128更新/2048draw。预选u32评测，仍计满128成本。
  这不是完整训练链三次独立初始化；原A/B BF16单卡与旧E3配方不混称只改数据。
- 实际5个关闭owner（baseline两段与3学习方法）、完整256首顺序和固定policy/argv核对，
  Source/Host/预算及primary seed0没有按确认结果重选；所有40/52/51/61首失败保留。

保护的是预冻结后的指定语义用途，并非公共预训练隔离、字节从未接触或独立/盲审。
早期DEV64解析过共享native-dev容器；当前Source-only复算也解析共享train/dev容器，只投影
已评估的选定256。公共Source内容、作者知道其他答案和评分不确定性均不能由冻结消除。
共同122掩码是在baseline80/primary16语义审阅后形成，82/101/231补充时序仍单列，不追认为预注册。
原64族三seed均值差值重新算出样本方差0.2038966049；+5pp规划近似约640族，实际预定N256，
没有功效保证或按结果增N。多seed/多请求不把来源数乘大。

## 条件停止与不能概括的结论

A1相对A0没有旧32任务增益，保留64原生条件指标也更低；A20k/32k/64k与J未获得既定门槛。
这是按原计划停止条件扩量，不是将这些可选规模伪称已经运行。DDP/精确resume与C菜单扩展
也分别需要实际瓶颈/表达缺口，未被本轮证据触发；保留未知标签、首失败和原全部成本。

B需要分清三个问题：

| DEV64比较 | 完整成功差 | 原家族95%区间 |
|---|---:|---:|
| B0−共同E1初始化 | +12.50pp | [0,+25.00]pp |
| B1−共同E1初始化 | +10.9375pp | [−4.6875,+26.5625]pp |
| B1覆盖提名−B0当前提名 | −1.5625pp | [−17.1875,+14.0625]pp |

没有稳定coverage-vs-current优势，不等于已证明pure-delivery学习完全无任务改善。
原文“明确answer/delivery分歧且pure-delivery仍不能改善”的复合条件，不能只凭粗材料tie里
存在答案差异就自动判为成立。相同packet也有首生成差异，已知材料/答案方向反转为0；
原保持B64/不自动新objective或A→B的决定保留。不得用后来确认的负结果重写这两个不同问题。
固定最终候选仍是已选E3 seed0/u32，另报三seed固定初始化随机性和所有否定/不确定结果。

D的0→1构造无关会话是最小因素测试，不是多规模历史增长曲线。E3虽在新32开发有正点估计，
但未收到或使用View；不能归因学会View复用。2048预算拒绝17/26/2保持，不因非零计数自动
扩大1024历史矩阵。原生Source身份/时钟、后来检索参数与内生历史变化均单列。
首次Provider请求实际在各方法对旧8为16/16、新32为64/64匹配，后续检索参数均0匹配，
这里沿用D18审计后的准确表述，避免把两类请求混淆。

## 七个工作组的当前状态与剩余交付

这是工作组划分，不是七个等权要求。全部原计划仍在范围内，最终审计还需逐项复验。

| 工作组 | 当前状态 | 必须满足的实际结束条件 |
|---|---|---|
| MEM-FIXED | CLOSED_NATIVE_AND_FULL_SOURCE_V186 | 实际400首结果/owner支付退出/最早canonical closure/冻结v2全Source已闭合；299 COMPLETED与101 FAILED保留，400快照全可重放 |
| MEM-PRIMARY | ACTIVE_REQUIRED_V186 | 原owner已启动，GPU2 FP32预定u32实际load验证；仍需全400首结果、支付退出及完整Source/NN/Host审计 |
| MEM-SCORE | REQUIRED_AFTER_PREDICTIONS | 两方法400适配评分、原生失败保留、评分审计、范围/暴露/分组与比较 |
| MEM-ARCHIVE | REQUIRED_AFTER_AUDITS | 两方法400原始Source/状态/输入/首结果/评分/日志可重建归档及原生关闭 |
| FINAL-COST | REQUIRED_AFTER_ACTUAL_PRIMARY_CLOSE | idle138已付155普通计时/3105.55CPU；primary与post138待后续实际idle闭合，最终已知/未知全项目成本仍需汇总 |
| FINAL-PAPER | REQUIRED_AFTER_EXTERNAL_CLOSE | 完整内外部/冻结确认的最终论文与结果包、总体图表、能主张/不能主张的结论 |
| FINAL-AUDIT | REQUIRED_FINAL | 以最终实际状态重新完成全763行要求/命令/门禁/交付物逐项审计，不能用本执行中清单宣布完成 |

当前固定400原父328495/子328497已实际退出、exit0、owner支付；原canonical别名之后的
冻结v2全400Source审计也实际exit0，完成初始6737200/pre-first6737600 Source比较、426 SDK packet
重建，400真实首次快照全部可重放。原primary400父2793546/子2793571已显式启动，完整原
memory_control合并仅覆盖policy/checkpoint，GPU2/cuda0 FP32/threads4/max16384/head2048实际load验证。
运行状态随原driver推进，见[最新v186](../data/manifests/a100-development-progress-20261109-v186.json)。
只核对真实named PID，不因超时重启；primary完成后仍按原alias→全Source/NN审计→两方法
适配评分/审计→最后无损归档。失败保留、不将partial intent提升为完成，尚无全800任务指标。
[原衔接操作卡](MILAI_A100_MEM2ACT_CLOSEOUT_HANDOFF_20261109.md)保留原流程与实际SDK顺序；
这些工作组不能由小面板、静态manifest或load回执代替。

LME已不是待执行：两方法各451，六个原生prediction/score/archive关闭实际exit0/支付/进程消失。
每方法50个未评分首失败仍在完整451分母，cohort metric不可用，不补负gold、不按共同完成子集
声称优势。早期primary1至9物理step快照未生成的限制保留；归档不创造那些缺失字节。
旧64保留query三模型12999首输出/完整输入/原生评分已闭合，Source共享语料与query家族资格分别解释。

历史LME截止点（idle137后/preMem）的已知已付成本为156772.30469547494 CPU秒、30712462已知Host tokens。
不是当前或最终全项目成本；v186中启动primary前的静态已付参照为178100.221431642CPU/35272283已知Host tokens，
另有当前primary、post138出版分析与未测范围。idle138只支付一次，历史截止量不重加。
不离线打开活动原账本，不把native/load/whole/residual/parent/旧存储或共享baseline重复加账。
未测作者/启动/丢失父/Host GPU忙时/货币成本保持unknown_not_zero或明确未知。

## 原命令与全部章节的当前处置

8个原代码块连同shell变量/所有参数都在机器索引中保留。训练代码块参数已对实际argparse
源文件逐项核对，P0新增device/parallel-mode/precision存在；旧说明中不存在的bf16/resume/
gradient-accumulation-steps没有被误当要实现的接口。第一次扫描将说明混进命令导致失败，
已按Markdown代码块修正，失败GNU计时保留。示例LR/长度/objective按原E2/E3实际配方绑定，
不把逐字重跑模板当额外实验。资源CSV/topology与当前独立GPU清单由已有P0实际回执支持。

| 原计划行 | 原章节 | 当前块处置 |
|---|---|---|
| 1–10 | MiLAi 详细开发实验计划：2×A100 40GB | STRUCTURE_OR_HISTORICAL_REFERENCE |
| 11–12 | 1. 执行摘要 | 结构/上下文 |
| 13–22 | 1.1 本轮要交付什么 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 23–36 | 1.2 推荐工作顺序 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 37–46 | 1.3 本轮成功的层级 | CLAIM_THRESHOLD_NOT_A_SUCCESS_CERTIFICATE |
| 47–48 | 2. 最新状态与本次源码核验修正 | 结构/上下文 |
| 49–62 | 2.1 当前需要保留的实验事实 | HISTORICAL_CONTEXT_PRESERVED |
| 63–75 | 2.2 已有功能应直接复用 | HISTORICAL_CONTEXT_PRESERVED |
| 76–79 | 2.3 训练入口与推理入口需要分开判断 | HISTORICAL_CONTEXT_PRESERVED |
| 80–81 | 3. 两张 A100 40GB 的资源规划 | 结构/上下文 |
| 82–95 | 3.1 默认调度 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 96–118 | 3.2 起始训练配置 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 119–126 | 3.3 显存与长度边界 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 127–134 | 3.4 DDP 和精确续训的地位 | CONDITIONAL_NOT_ADMITTED |
| 135–136 | 4. 开发包 P0：让双单卡训练真实可用 | 结构/上下文 |
| 137–152 | 4.1 最小代码修改 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 153–160 | 4.2 BF16 实现要点 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 161–170 | 4.3 32-update profile | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 171–184 | 4.4 必要验证与记录 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 185–186 | 5. 数据体系：增长的是有效信息，不只是行数 | 结构/上下文 |
| 187–199 | 5.1 现有可用资产 | HISTORICAL_CONTEXT_PRESERVED |
| 200–207 | 5.2 数据用途与分割 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 208–217 | 5.3 条件数据扩容阶梯 | CONDITIONAL_NOT_ADMITTED |
| 218–230 | 5.4 完整动作反馈扩容阶梯 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 231–232 | 6. 开发包 A：条件负例采样修复 | 结构/上下文 |
| 233–242 | 6.1 修改位置与具体问题 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 243–254 | 6.2 选择优先级 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 255–272 | 6.3 A0/A1 训练合同 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 273–280 | 6.4 A 的评测与决策 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 281–282 | 7. 开发包 B：完整参数反馈，优先使用既有候选 | 结构/上下文 |
| 283–290 | 7.1 候选选择的最小增量 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 291–306 | 7.2 两种比较不能混在一起 | EVIDENCE_SCOPED_WITH_LIMITATIONS, OPTIONAL_EFFICIENCY_STUDY_NOT_CLAIMED |
| 307–312 | 7.3 首步与后续执行 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 313–324 | 7.4 反馈语义 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 325–337 | 7.5 新数据应覆盖的真实决策条件 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 338–355 | 7.6 B0/B1 训练合同 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 356–357 | 8. 开发包 C：材料集合与原文粒度 | 结构/上下文 |
| 358–363 | 8.1 先定位“没选中”还是“菜单没有” | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 364–371 | 8.2 仅在具体表达缺口时扩展有界候选 | CONDITIONAL_NOT_ADMITTED |
| 372–377 | 8.3 集合训练与指标 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 378–379 | 9. 开发包 D：持续更新与旧 View＋增量读取 | 结构/上下文 |
| 380–385 | 9.1 当前控制流的具体限制 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 386–393 | 9.2 最小实验路径 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 394–405 | 9.3 三个分开的评测因素 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 406–407 | 10. 实验矩阵、训练次数与两卡波次 | 结构/上下文 |
| 408–422 | 10.1 主矩阵 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 423–428 | 10.2 数据规模与训练计算量应分开比较 | CONDITIONAL_NOT_ADMITTED |
| 429–441 | 10.3 计算预算工作表 | PARTIAL_REQUIRED_EXTERNAL_OR_FINAL_DELIVERABLES |
| 442–447 | 10.4 训练 seed 与采集 seed | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 448–449 | 11. 评测、统计与采用标准 | 结构/上下文 |
| 450–462 | 11.1 四层评测 | PARTIAL_REQUIRED_MEM2ACT_LAYER |
| 463–474 | 11.2 来源与样本量规划 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 475–482 | 11.3 主指标与解释 | EVIDENCE_SCOPED_WITH_LIMITATIONS |
| 483–490 | 11.4 外部评测范围 | PARTIAL_REQUIRED_EXTERNAL_OR_FINAL_DELIVERABLES |
| 491–492 | 12. 全成本、里程碑与停止规则 | 结构/上下文 |
| 493–500 | 12.1 成本分项 | PARTIAL_REQUIRED_EXTERNAL_OR_FINAL_DELIVERABLES |
| 501–513 | 12.2 建议里程碑 | MILESTONE_RESULTS_SCOPED_M5_STILL_OPEN |
| 514–523 | 12.3 停止或改变方向的规则 | ONGOING_INVARIANT_WITH_RETAINED_FAILURES |
| 524–529 | 13. 命令与配置模板 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 530–539 | 13.1 一次性资源记录：只读 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 540–559 | 13.2 当前训练入口已有参数 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 560–585 | 13.3 P0 完成后的 A 单卡模板 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 586–611 | 13.4 B 反馈训练模板 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 612–646 | 13.5 现有真实分支准备与执行 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 647–667 | 13.6 现有 handoff-only 机制入口 | TEMPLATE_OR_INTERFACE_BOUND_TO_ACTUAL_EVIDENCE |
| 668–669 | 14. 交付物、论文主张与开发边界 | 结构/上下文 |
| 670–686 | 14.1 沿用现有产物体系 | PARTIAL_REQUIRED_EXTERNAL_OR_FINAL_DELIVERABLES |
| 687–694 | 14.2 可形成的贡献 | CLAIM_THRESHOLD_NOT_A_SUCCESS_CERTIFICATE |
| 695–700 | 14.3 本轮明确保持的开发原则 | ONGOING_INVARIANT_WITH_RETAINED_FAILURES |
| 701–702 | 参考资料 | 结构/上下文 |
| 703–719 | MiLAi 固定提交 | STRUCTURE_OR_HISTORICAL_REFERENCE |
| 720–728 | 官方硬件/框架资料 | STRUCTURE_OR_HISTORICAL_REFERENCE |
| 729–763 | 本轮采用的研究机制 | STRUCTURE_OR_HISTORICAL_REFERENCE |

所有原文、分组、未知和条件项保留；最终完成审计要在全量外部、成本和论文图表实际闭合后
重做，本执行中清单绝不设置goal_complete或证明整个763行已经完成。

- [复算源码](../tools/audit_a100_plan_completion_evidence.py)
- [来源分配与预冻结复核](../tools/audit_a100_plan_allocation_freeze.py)
- [D18具体合同](MILAI_A100_PLAN_D_AUDIT_20261109.md)
- [整体执行状态](MILAI_A100_DEVELOPMENT_EXECUTION_20261104.md)
