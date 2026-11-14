# MiLAi Reader效用实验：结果报告（持续补全）

状态：**实验未完成，不是最终验收报告。** 本文把方法效果、执行状态和成本分开；阶段过程见[执行记录](MILAI_READER_UTILITY_EXECUTION_20261112.md)，机器可读状态见[进度清单](../data/manifests/reader-utility-progress-20261112-v3.json)。固定计划为`MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20261112_2XA10040GB_v3.md`。

目前最明确的结论是：真实完整动作、效用蒸馏、结果校正及任务读出链已经运行，但E1、E2和自身状态对照没有确立主要任务增益。新来源确认中，10k＋Q的已验证完整支持首次低于强固定上下文；未知判断和评审偏差仍限制真实质量解释。自然应用暴露了View交付预算与自动评审可靠性的限制。重复读出稳定性及最终成本仍待关闭。

## 评分工程与执行模式

正式教师评分使用冻结4B模型、FP32/SDPA、关闭TF32，只投影答案前驱位置，不保留整段B×L×V logits。此前BF16在相同输入、不同批次组合下出现明显分数变化，因此原结果保留、正式数值协议单列，学生训练仍使用BF16。未知参考、边界无法确认和容量不足保持未知，不转成负例。

同一实际训练来源的579包比较中，266包共同可评分、313包共同未知。每包原始答案别名共享相同token前缀后，384个比较方向和69个有效状态不变；包均分最大差2.91e−5，逐token最大差2.10e−4，不称逐位一致或普遍误差上界。实际处理输入从986,192降至198,462 tokens，评分阶段/整个作业分别加速约3.88/3.52倍。这是同一数学评分任务的有限工程证据，不能写成任务质量提高或相对生成式评价的同等效果加速。[原始比较](/data/milai-experiments/20261112-reader-utility/alias-prefix-full-pilot-comparison-v1.json)

另在已暴露TRAIN包中，按输入长度固定9个分位位置、涉及8来源，比较同一4B FP32模型的别名评分与贪心生成。独立公共前缀逐token一致，离线答案字段不进入生成输入。评分累计3.833秒，生成91.753秒；但9次生成全部达到事先固定的256-token上限，均未按直接短答要求结束。因此这不是等价完成输出的效率对照，也不估计无截断生成或“生成＋语义评审”的完整成本。新评分均值与原FP32完整前向最大差7.98e−6，原首生成、截断及成本全部保留，没有挑选或重试。[探针及解释](/data/milai-experiments/20261112-reader-utility/same-teacher-mode-probe-v1/interpretation-v1.json)

## 可用监督的产出与分母

20个新增TRAIN生产块包含283个原始来源、279个已知依赖组、22,613个实际状态和85,907个执行包。43,984包可评分、41,923包未知；实际教师输入36,614,350 tokens，产生11,486个非平坦弱监督状态，最终按既定方案选入6,644个，与原3,356组成10k。每千个实际输入token对应0.314个活跃状态、1.201个可评分包。这只覆盖新增块的规范评分，不含原3k、数值探针、采集与Host成本；多个状态不是多个独立来源。

600个预选反馈机会涉及481来源，保留2,018个读出记录，其中143失败、1,875完成；实际报告2,004次调用、14个复用记录。可用于Q的材料质量状态为331，涉及287来源，其中249有方向、82为正质量平局；即每100机会得到55.17个已知目标，每100读出记录得到16.40个已知或12.34个有方向状态。原记录中的Reader与来源评审已知/扣额token分别7,533,432、3,661,598，unknown usage增量均0；这两个生成窗口不是本地弱评分的等价任务或完整GPU成本。

| 全600机会的比较对象 | 有方向的成对比较 | 质量平局 | 未知 | 全部比较 |
|---|---:|---:|---:|---:|
| 材料质量 | 540（21.93%） | 468（19.01%） | 1,454（59.06%） | 2,462 |
| 答案质量 | 393（15.96%） | 423（17.18%） | 1,646（66.86%） | 2,462 |

成对比较共享读出记录，不能解释成2,462个独立分支或来源；331已知状态子集里的390个未知材料比较也不能替换全600中的1,454。候选只执行了被提名的合法替代，因此没有穷尽“所有有益动作”的真值，不能据此估计相同预算下的完整发现率。以上分母均从原始关闭记录重算，0新模型调用。[监督产出及逐块证据](/data/milai-experiments/20261112-reader-utility/learning-information-efficiency-v1/summary.json)

## E1：训练信号改变了，任务优势仍未确立

两条U链从同一S1/36k固定终点开始，使用相同3,356主状态、4,096 replay池和420次更新，每臂10,068主曝光、3,356 replay曝光。U0只有37个主状态具有活跃旧目标，U1有3,355个活跃弱效用目标；相应主监督曝光为111对10,065。这是监督内容与覆盖共同变化的比较，不能称为纯损失函数隔离。

随后两臂均接相同实际331状态的质量池及原replay池，63次更新、993主曝光与993 replay曝光。600个已处理反馈机会不能写成600个有效质量训练样本。训练采用FP32参数/Adam、BF16前向；保存权重实际为FP16，普通保存模型推理再加载为FP32，不能将保存格式写成BF16。

完整DEV保留96个来源、每方法一次原生首答，共576个位置。来源支持评审与Reader使用同一模型，非独立裁判；官方原生答案F1仅作为辅助指标。

| 方法 | 完整且受来源支持 | 未决 | 执行失败 | 原生答案F1 |
|---|---:|---:|---:|---:|
| 固定上下文 | 40/96 | 31 | 1 | 0.327982 |
| 共同S1 | 31/96 | 23 | 5 | 0.242052 |
| U0 | 30/96 | 18 | 8 | 0.185132 |
| U1 | 34/96 | 20 | 4 | 0.199899 |
| U0→Q | 31/96 | 20 | 4 | 0.236308 |
| U1→Q | 32/96 | 24 | 1 | 0.235431 |

主要比较U1→Q减U0→Q为+1.04个百分点，来源配对bootstrap 95%区间为[−8.33,+9.38]个百分点。未决判断对应的识别范围为[−19.79,+26.04]个百分点；它不是另一置信区间。原生F1差为−0.000877，配对区间[−0.061923,+0.060107]。当前结果既不证明优势，也不证明等效。固定方法数值上最高，不据此改写预定主要比较。

策略层确实发生了变化：共同992状态上，U0/U1有397个完整首选不同，其中148个动作类型相同但目标或参数不同。该面板的条件原生见证来源宏差为−0.1071，区间[−0.1682,−0.0492]，U1在这个代理上较差；它不是保存模型的全轨迹任务指标。实际96来源轨迹中，Q0/Q1分别493/517个决策状态、5/7次预算强制停止、85,157/93,565终点包tokens，不能把更长轨迹或更多材料直接解释为更好任务效果。[动作比较](/data/milai-experiments/20261112-reader-utility/formal-U-closed-reference-comparison-v1.json)、[六方法实际轨迹](/data/milai-experiments/20261112-reader-utility/formal-task-dev96-all-six-trajectory-comparison-v1.json)

为补足类型先验对照，另对已暴露的992个DEV状态及原保存预测作事后分析：枚举HANDOFF、READ、SEARCH全部6种固定顺序，同类型选原菜单首项，既不查看query/来源，也不用标注作选择。584个状态有原生见证偏好，涉及77来源；其余408状态保持无标签。全部顺序的来源宏参考接受率分别为：HANDOFF优先两种均19.50%，READ优先两种均0，SEARCH→HANDOFF→READ为46.84%，SEARCH→READ→HANDOFF为27.34%。READ首项在992状态均为分页动作`source_page_next`，说明菜单内绑定选择不能被类型名称代替；这些顺序未选入确认集。

| 原保存模型预测 | 来源宏参考接受率 | 保留模型类型、改选同类型首项 | 保留模型类型、同类型均匀选择的期望 |
|---|---:|---:|---:|
| U0 | 49.80% | 38.04% | 30.83% |
| U1 | 39.10% | 26.01% | 20.49% |
| Q0 | 41.13% | 28.89% | 24.07% |
| Q1 | 37.99% | 23.47% | 18.56% |

这说明在固定已到达状态与各自选定类型下，参数绑定携带了类型以外的信息；同时Q0/Q1的参考代理低于其中一个简单类型顺序。均匀选择是解析期望，没有执行随机策略；以上均为同一DEV的事后代理分析，不证明策略轨迹、Host质量或新来源因果收益，也不据此改候选。完整动作与逐状态对照已保存。[类型和绑定对照](/data/milai-experiments/20261112-reader-utility/DEV-type-order-binding-controls-v1/summary.json)

E1来源评审中，固定/S1/U0/U1/Q0/Q1的材料充分计数分别42/32/34/37/35/34，均以96计划来源为范围；这些计数与完整受支持答案40/31/30/34/31/32分开保存。材料充分仍可能伴随Reader失败或使用不足，来源支持的局部答案也可能不完整。[独立的证据层计数](/data/milai-experiments/20261112-reader-utility/closed-DEV-evidence-layer-inventory-v1/summary.json)

预定12来源×6方法的72个人工绑定全部核对。完整受支持二分类有63项一致、9项不同：3项与非逐字引用校验有关，6项是语义解释差异。作者也不是独立真值。仅在该12来源子集替换人工正判断时，Q0/Q1计数会变为31/31；这只是敏感性说明，原主要标签和首次回答均未改写。

证据：[完整来源评审汇总](/data/milai-experiments/20261112-reader-utility/formal-task-dev96-all-six-summary-v1/summary.json)、[原生任务与人工结果](/data/milai-experiments/20261112-reader-utility/formal-task-dev96-native-and-author-summary-v1.json)、[人工一致性检查](/data/milai-experiments/20261112-reader-utility/formal-dev96-author-teacher-agreement-v1.json)、[任务结果图表](/data/milai-experiments/20261112-reader-utility/formal-E1-task-results-v1)。

## 机制与反例

全部600个已选TRAIN反馈机会、481来源共2,462对材料比较已与原FP32评分逐项绑定；实际初始状态、完整动作表、动作、执行后的证据包及续跑条件均一致，前261机会的既有统计得到完全复现。它们仍是被选中的训练机会，不是总体随机样本；评分与语义反馈还使用不同模型/输出协议。

| 语义目标 | 语义未知对数 | 共同有方向的对数 | 同向／反向 | 来源宏同向率及条件95%区间 |
|---|---:|---:|---:|---|
| 材料质量 | 1,454 | 523 | 375／148 | 0.701 [0.644, 0.754]，218来源 |
| 答案质量 | 1,646 | 382 | 276／106 | 0.721 [0.661, 0.778]，173来源 |

148个材料反向比较中，82个弱分数赢家是无K空包；449个有弱分数的语义质量平局中，46个绝对弱分数差超过0.5。由此不能将弱分数差直接当作质量差，也不能把所有反向都归因于参数记忆：参考歧义、语义评审误差和抽样条件仍存在。条件bootstrap没有消除这些偏差，原U/Q标签没有改写。[全部600机会](/data/milai-experiments/20261112-reader-utility/canonical-fp32-vs-semantic600-diagnostic-v1/summary.json)、[条件来源区间](/data/milai-experiments/20261112-reader-utility/canonical-fp32-vs-semantic600-diagnostic-v1/source-conditional-bootstrap-v1.json)

K诊断有16来源、32实际cold/known状态，7来源共同可评分，其中6个教师最佳完整绑定改变；动作菜单和候选支持也可能不同，不能隔离K因果效应或声称学生学会正确停止。h=0/h=2诊断在同8个已暴露来源、36实际状态的120绑定中有16个最佳候选改变，相同停止请求最大差3.05e−5，取得动作的平均分数增量约0.3133；额外续跑成本不同，且这仍不是Host质量增益。[K诊断](/data/milai-experiments/20261112-reader-utility/known-evidence-train16-diagnostic-v1.json)、[短程价值诊断](/data/milai-experiments/20261112-reader-utility/immediate-vs-h2-new8-diagnostic-fp32-v2.json)

公开TRAIN固定8状态、31证据包的人工检查中，25包不足、6包含歧义，没有明确完整支持包；只有3状态的12包具有可用弱分数。一个命名来源案例中，补充国家关联的包反而比缺少该关联的包低约0.08646 log-prob。该小样本说明弱分数并不等于材料质量，不能外推为总体教师准确率，也没有据此重写训练标签。

I2公开来源比较保留16个cold/K状态、8来源族。学习策略与全量包在16状态上的实际输入完全相同，因此不能用相同答案的成功证明学习交付具有独特收益。确有一个cold案例需要组合电影身份与银幕数信息；其K版本已由A包足够支持，而A的首次读出失败不能当作互补性的证明。角色、时间与歧义反例一并保留。

证据：[弱信号人工诊断](/data/milai-experiments/20261112-reader-utility/public-weak8-source-panel-v1/unmasked-summary-v1.json)、[I2原生比较](/data/milai-experiments/20261112-reader-utility/i2-public-dev8-native-v2/summary.json)。K、短程价值、停止和参数变化的完整诊断仍需在最终综合时与任务结果逐项关联。

## E2与自身状态：原生F1与主要来源指标分离

E2三臂均从共同S1重新开始，使用新冻结的共同replay：3,356×3遍、10,000×3遍、3,356×9遍，计划420、1,250、1,259更新，再各接相同Q63。旧U不能替代新的3遍基线。扩量臂实际训练输入为241,314,753 tokens；近似匹配主曝光不等于匹配tokens/FLOPs，来源与条件构成也改变。

三个E2臂的U、Q、DEV轨迹、首次Reader与来源评价均已关闭，post-Q完整参考21/63均提名固定63，无额外checkpoint进入任务读出。基线有一个真实采集失败，只取得95个实际终点；全部统计保留计划96分母，没有虚假的HANDOFF、证据包或Reader调用。9遍重复U实际为1,259更新、30,204主曝光与10,068 replay、228,957,845训练输入tokens。

| E2方法 | 完整受支持答案 | 未决 | Reader失败／采集失败 | 全96来源原生F1 |
|---|---:|---:|---:|---:|
| 3k×3＋Q | 37/96 | 21 | 4／1 | 0.249705 |
| 10k×3＋Q | 36/96 | 32 | 2／0 | 0.331559 |
| 3k×9＋Q | 35/96 | 28 | 3／0 | 0.251309 |

E2三臂的材料充分计数为40/40/36；3遍基线另有一个无实际包的采集失败，不虚构材料判断。自身状态批次的初始Q1/旧状态/自身状态材料充分为39/39/35。初始Q1属于不同评审批次，不能用39与E1中的34比较模型进步。

主要来源指标的扩量−3遍基线差为−1.04个百分点，95%来源bootstrap区间[−11.46,+9.38]，未知识别范围[−22.92,+32.29]个百分点。扩量−9遍重复为+1.04个百分点，区间[−9.38,+12.50]，未知识别范围[−28.13,+34.38]个百分点。来源评审192组中1组未决，285个候选记录中74个被校验屏蔽。尚未建立完整受支持答案优势。

原生F1的对应差为+0.081854，区间[+0.012520,+0.153218]；以及+0.080250，区间[+0.016170,+0.148306]。这些辅助结果与主要来源指标不同，不能用较好的词面答案指标替换预定主指标。单训练seed、首次Host波动、不同来源/条件组成及token工作量仍限制解释。[主要来源结果](/data/milai-experiments/20261112-reader-utility/formal-E2-task-dev96-primary-summary-v1/summary.json)、[重复曝光次比较](/data/milai-experiments/20261112-reader-utility/formal-E2-task-dev96-repeat_secondary-summary-v1/summary.json)、[全96原生比较](/data/milai-experiments/20261112-reader-utility/formal-E2-native-firsts-full96-v1.json)

![E2首次任务结果与不确定性](/data/milai-experiments/20261112-reader-utility/formal-E2-task-results-figure-v1/E2-task-results.png)

自身状态比较每臂657个匹配主状态、4,056 replay，从同一Q1固定终点继续83更新，再同Q63。它复用原TRAIN来源，不能称新来源泛化；匹配与replay重叠排除改变了可比较条件，须保留覆盖范围。两臂拟合、96来源DEV、首次Reader与来源评审均已关闭，均提名Q63；新状态U实际输入16,254,459 tokens。

旧状态／自身状态续训分别得到36/96和33/96个完整受支持答案，差−3.125个百分点，95%来源区间[−13.54,+7.29]，未知识别范围[−33.33,+18.75]个百分点。Reader失败1／3，未决29／21；原生F1为0.283560／0.241373，差−0.042187，区间[−0.096218,+0.010384]。尚未建立自身状态续训优势。预定作者24绑定也已完成，两臂各5/12完整受支持，与自动二分类有4/24项不同，不以作者替换主标签。[自身状态主比较](/data/milai-experiments/20261112-reader-utility/formal-ownstate-task-dev96-primary-summary-v1/summary.json)、[作者对照](/data/milai-experiments/20261112-reader-utility/formal-ownstate-author-teacher-agreement-v1.json)

原Q1的96条首次答案未重跑，但在自身状态评审分组中重新判断后，完整支持计数从E1的32变成37。新旧分组、同组候选和评审采样不同，不能将这种变化归为模型进步或纯采样噪声，也不能跨评审批次按计数宣布赢家。原E1标签完整保留。[同一首次的重评敏感性](/data/milai-experiments/20261112-reader-utility/formal-Q1-rejudgment-context-sensitivity-v1.json)

![自身状态对照实际任务结果](/data/milai-experiments/20261112-reader-utility/formal-ownstate-task-results-figure-v1/ownstate-task-results.png)

在E2及自身状态首答之前，已固定沿用E1的12个来源位置，对三个E2终点及两个自身状态终点共60个新绑定作作者复核；现已全部完成，原Q1的12作者绑定只复用一次。E2完整受支持计数为4／5／5，与自动评审有6/36个完整支持二分类分歧。它们包含引用屏蔽和语义解释差异，作者不是独立真值。作者已看过这些DEV来源，非独立且未盲化，结果作为补充核对。[作者样本协议](/data/milai-experiments/20261112-reader-utility/formal-E2-ownstate-author12-protocol-v1.json)、[E2作者对照](/data/milai-experiments/20261112-reader-utility/formal-E2-author-teacher-agreement-v1.json)

## 自然应用与View

当前应用使用10条公开自然消息历史、8,944条原消息，每方法100个按到达切点安排的问题。共享参与者仅形成3个依赖组，不能把100请求或10历史当作独立来源数量；请求由评价安排，不是原参与者真实发问，且不是完整原生基准。

现有服务拒绝首次native-auto工具请求，原失败及未知用量保留，服务未重启。另用已有JSON-action协议执行自主工具/答案选择，不强制调用。四方法400个首次位置全部关闭：固定94完成/6失败，增量缓存84完成/16失败，S1为90完成/10失败，Q1为89完成/11失败。合计357个完成、43个失败；357个完成回答全部未遵循内层三字段格式。Q1失败包括6次输出截断和5次JSON-action格式错误。HTTP完成不是语义成功，原文不补字段、不抽取有利短答。

基线200位置的自动来源评审已关闭：22个执行失败不虚构语义标签；178个回答中7个评审未决（6个容量超限、1个输出截断），101个判断被引用/字段规则屏蔽。最终固定方法为71 unknown、13 incorrect、10 incomplete；缓存为48、24、12，没有自动supported判断通过校验。这不是“真实成功为零”：人工已核实至少两条有原文且Host实际可见的回答，被不一致的grounding/resolution字段屏蔽为unknown。筛选未选中也不证明历史中不存在。

178个完成回答的实际最终provider输入中，完整声明的system prompt（含内层三字段格式指令）均逐字存在。因此已排除这些绑定中的提示词未送达问题，但没有由此证明模型为何不遵守格式，四方法的冻结条件均未改变。[实际输入核对](/data/milai-experiments/20261112-reader-utility/natural-answer-format-wire-observation-v1.json)

缓存减固定的已验证supported标签差为0，条件性标签bootstrap也为[0,0]；该退化区间不能解释为等效或精确测得零效果。未决判断的三依赖组加权识别范围为[−71.39,+49.17]个百分点，且作者和自动评审均非独立真值。基线评审使用4,067,025已知tokens、CPU25.085秒、wall3,529.570秒，已原生记账。完整400位置的预定主要比较仍为Q1减S1，不改为此基线次比较。

预定请求位置2/7×10历史的基线人工40绑定已完成：固定2 supported、8 incomplete、1 incorrect、7 unknown、2执行失败；缓存0、9、1、7、3。作者未盲化且非独立，关键词搜索只定位证据，不作为缺失证明。Pachinko读完记录的遗漏、Latte饮料与宠物混淆、提问日期与实际消息日期不符均有原始证据。

S1的同位置20个作者绑定也已关闭：2 supported、9 incomplete、1 incorrect、6 unknown、2执行失败。Pachinko与推荐《The Alchemist》的日期回答同时有原文和实际Host输入支持；另一些回答漏掉已存在的兄弟共同兴趣、过去感染Covid的记录，或将“没有检索到”扩大为“没有提及”。此处未知与不完整的边界受题意和覆盖限制影响，作者不是真值；不从20个绑定推断整体方法优势。[S1闭合记录](/data/milai-experiments/20261112-reader-utility/natural-common_s1-closure-v1.json)、[S1作者20](/data/milai-experiments/20261112-reader-utility/natural-author-source-review-v1/common_s1-20.json)

Q1的预定20个作者绑定也已关闭：1 supported、8 incomplete、3 incorrect、7 unknown、1执行失败。四方法共80绑定全部保留，正确的Alchemist日期、遗漏和明确否认已有事实、题意/来源覆盖未知均分开记录。该小样本不是80个独立来源，也不替换全400位置的预定评审。[全部作者80](/data/milai-experiments/20261112-reader-utility/natural-author-source-review-v1/all80.json)

缓存方法实际执行129次View构建与14次复用，143次全部返回材料预算不足，没有成功View交付。原实现先写入View再检查交付容量，因此构建成本不能记为零。构建elapsed 4.321865秒嵌套在62.468747秒操作和128.815875秒检索wall中，不能相加。S1在597个实际决策点获得REFRESH_VIEW选项，零次选择View操作；它的616个本地模型结果均与随后记录的完整菜单和实际选择一致，输入4,353,620 tokens、原生截断标志均为false，没有从泛化的selection_mode=policy字段猜测模型是否运行。

固定／缓存／S1／Q1分别在96／98／91／95个位置出现检索返回，总返回117／192／123／126次；没有返回包含未调用和返回前失败，不能直接当作Host拒绝调用。S1的运行时模型计量为CPU698.702秒、wall408.130秒，另一次模型加载CPU7.019秒、wall5.864秒；它们嵌套于控制、检索及driver计时，不能与父时间重复相加。S1已记账generation tokens为1,795,859，unknown usage增量0。[完整菜单机会](/data/milai-experiments/20261112-reader-utility/natural-all-four-opportunity-inventory-v1/summary.json)、[实际S1模型核对](/data/milai-experiments/20261112-reader-utility/natural-common_s1-model-trace-audit-v1/summary.json)

Q1有708次本地模型结果，全部与完整菜单及实际选择相符；5,193,340输入tokens、0原生输入截断。697个菜单提供REFRESH_VIEW，仍无View选择。其513次READ多于S1的391次，预算耗尽终止43次对14次；8次执行了参数化HANDOFF，但没有同一已读池的配对干预可将它们解释为质量收益。Q1运行时模型CPU843.051秒/wall483.538秒，加载CPU7.245秒/wall5.980秒；generation tokens为1,920,902，unknown usage增量0。完整400位置来源评审已关闭，度量限制见下文。[Q1闭合记录](/data/milai-experiments/20261112-reader-utility/natural-q1-closure-v1.json)、[实际终止原因](/data/milai-experiments/20261112-reader-utility/natural-all-four-control-terminations-v1/summary.json)

原版400位置来源评审已经关闭，四方法均没有supported标签通过全部校验；S1有68 unknown、11 incorrect、11 incomplete，Q1为67、16、6，另各10／11执行失败。原版Q1−S1已验证标签差为0，退化bootstrap[0,0]不能支持等效结论；三依赖组未知识别范围[−68.61,+66.94]个百分点。作者80中已确认的受支持例子说明“零个通过校验标签”不等于“真实成功为零”。[原版全400结果](/data/milai-experiments/20261112-reader-utility/natural-all-four-source-outcome-summary-v1/summary.json)

另冻结的一次全400位置评审输入诊断已完成：只移除原引用规则不允许作为依据的顶层system/assistant消息，完整保留所有user/tool内容、原来源和候选回答，并明确标记候选回答字段。357个完成上下文逐项验证不丢失任何原可引用内容，178个既有基线默认评审请求也逐字复现。新版每位置只尝试一次、单独报告，不按位置择优、不替换主标签；设计时作者80已知，不能称独立或留出验证。[诊断协议](/data/milai-experiments/20261112-reader-utility/natural-eligible-context-review-protocol-v2.json)

该诊断仍未恢复可用的正判断：357个完成回答中11个评审未决、214个被校验屏蔽，四方法依然没有supported标签通过校验；作者的5个支持例子在两个版本中均为unknown。114个分类发生变化，但不能视作准确率提高。投影版Q1−S1仍为0，未知识别范围[−54.44,+63.61]个百分点；退化bootstrap[0,0]仍不能证明等效。本轮使用7,181,796已知/扣额tokens、CPU47.585秒、wall4,860.799秒，已原生记账。按事前约束不启动第三轮；自然线的自动质量度量存在严重限制，控制/成本证据和作者样本分开报告。[诊断闭合与局限](/data/milai-experiments/20261112-reader-utility/natural-eligible-context-diagnostic-closure-v2.json)

证据：[冻结应用协议](/data/milai-experiments/20261112-reader-utility/natural-realtalk-application-plan-v2/protocol.json)、[基线来源评审闭合及局限](/data/milai-experiments/20261112-reader-utility/natural-baseline-source-review-closure-v1.json)、[人工40绑定](/data/milai-experiments/20261112-reader-utility/natural-author-source-review-v1/baseline40.json)、[实际View工作量](/data/milai-experiments/20261112-reader-utility/natural-baseline-view-work-v1/summary.json)。

## 已测成本与未测范围

14个正式拟合全部关闭并与原生阶段账本核对一致：累计819,510,075实际训练tokens，原生CPU 91,915.137秒，训练wall累计58,437.095秒、评价wall累计14,117.382秒。累计wall是并行作业时长之和，不是项目经过时间；原生约21.309设备小时是按阶段wall计算的分配代理量，不是活跃kernel时长、能耗或总项目成本。没有重复结算，图中自身状态列只展示新增续训，不把已在E1记录的Q1初始化再次收费。[14拟合逐项数据](/data/milai-experiments/20261112-reader-utility/formal-fit-costs-all14-v1/summary.json)、[图表PDF](/data/milai-experiments/20261112-reader-utility/formal-fit-work-figure-v1/fit-work.pdf)、[图表CSV](/data/milai-experiments/20261112-reader-utility/formal-fit-work-figure-v1/plot-data.csv)

![14个关闭拟合的实际训练工作量](/data/milai-experiments/20261112-reader-utility/formal-fit-work-figure-v1/fit-work.png)

短Q阶段的评价约占各自账前wall的42.5%–45.0%，10k U约5.4%；不能把所有阶段统称评价开销很小。数据准备、前缀采集、分支、Teacher、Host、来源评审、存储和未测根进程工作仍须另列。已有非原生成本清单尚未最终结算，不能与包含其子过程的父进程时间重复相加。

已另保存96个`milai_reader_utility_`已付费阶段的逐项清单，并再次核对其中14个拟合阶段。这一前缀不涵盖全部通用运行时、当前/未来Host阶段及未结算CPU工作，因此清单中的账面合计不是完整、去重后的项目总成本。[已记账阶段快照](/data/milai-experiments/20261112-reader-utility/paid-study-phase-inventory-v1/summary.json)

三个既有待结算清单中的216个关闭范围已重新核对到原始回执，合计CPU53,309.534秒。父子分开计量、单阶段对象和早期按目录名记录的已付范围已按实际格式处理；未发现这些范围彼此、已核对的phase01/02已付范围或其覆盖子计时的重复；原生自记账排除仍依既有清单和owner标记。其记录wall之和44,320.264秒包含一个明确等待范围，不是项目经过时间。结算器等待确认HTTP和稳定性汇总关闭后才按单一阶段记录，并读回核对、防止重复记录。后续工作及未知成本仍另列。[216范围核对](/data/milai-experiments/20261112-reader-utility/reconciled-prior-closed-cost-scopes-v4/summary.json)

后续又核对47个关闭子进程与76项独立计时，合计CPU32,811.744秒，与前述216范围分开。包含失败任务、归档和一个已退出等待器的最后实测前缀；重复的继承计时与父子嵌套计时已排除，未测尾部不填零。记录wall之和69,977.100秒包含等待和重叠，不能解释成经过时间。此批等待确认、稳定性和前批结算后再记账；确认HTTP后处理及未来分析仍另列，服务端GPU与编排的可比实际算力成本未知。[后续123范围核对](/data/milai-experiments/20261112-reader-utility/reconciled-later123-cost-scopes-v1.json)

## E4：新来源确认，主要比较未支持替换强固定基线

确认集包含事前预留的256个原生TEST来源，与已知TRAIN/DEV分配及已扫描项目元数据无交集；不声称隔离公开预训练。完整协议冻结后才导出每篇原生首题，答案/证据标注留在离线controls，没有训练样本导出。四方法为强固定上下文、原规则、共同S1及原定10k＋Q固定终点；10k路线是待检验候选，未称为DEV赢家。E4唯一主比较固定为10k＋Q减强固定上下文，S1和规则为次比较，早期E1/E2/自身状态主比较不变。主要指标是完整受支持首次答案，官方原生F1为辅助。[冻结确认协议](/data/milai-experiments/20261112-reader-utility/new-confirmation-protocol-v1.json)

配置保留同一Host温度1、8,192输出上限、65,536上下文、2,048材料tokens、8控制步、空初始K及完整动作菜单。32来源第二次Reader和32来源作者样本均在结果出现前按身份固定，所有方法使用同一子集。当前DEV没有确立决定性主要质量增益，因此未追加seed1/2拟合，不作训练seed稳定性声明；确认结果不用于改选模型、提示、预算或N。

四方法全部1,024首次、编译与原生评分已关闭。每方法实际256次新调用，无跨方法响应复用；983个完成回答全部保留原声明的answer/explanation/evidence字段，41个失败均为length。官方评分只取固定answer字段，失败按原生缺失记0，同时保留执行失败身份；没有修复、重试或从长回答抽取有利片段。

| 方法，每方法256来源 | 完整受支持首次 | 未知任务判断 | 长度截断失败 | 原生答案F1，失败记0 |
|---|---:|---:|---:|---:|
| 固定上下文 | 116 | 53 | 1 | 0.342100 |
| 10k＋Q | 92 | 60 | 10 | 0.310370 |
| 规则 | 72 | 50 | 12 | 0.243335 |
| 共同S1 | 96 | 51 | 18 | 0.300559 |

主要来源评审512个双方法组已全部关闭，4组未决，返回1,016个候选判断，其中177个被引用/字段校验屏蔽。上述未知与失败均保留；F1仍是辅助指标。全部首次合计3,501,683已知/扣额tokens，来源评审另用2,699,023 tokens，两阶段unknown usage增量均0。评审原生CPU52.055秒、wall7,275.414秒已读回账本核对，不能解释为服务端GPU忙时或重复计费。[首次与格式核对](/data/milai-experiments/20261112-reader-utility/new-confirmation-firsts-all1024-closure-v1.json)、[来源层及计量闭合](/data/milai-experiments/20261112-reader-utility/confirmation-first-source-evidence-v1/summary.json)

预定主比较10k＋Q减固定上下文为−9.375个百分点，来源配对bootstrap 95%区间[−15.625, −3.125]个百分点。两者共同完整69来源、仅10k完整23、仅固定完整47、均未达到完整标签117；这不是穷尽真实错误的分类。至少一方未知的来源有73个，未知识别范围[−30.078, +14.063]个百分点，不是另一置信区间。因而当前验证标签下固定方法较高，但未知、同模型评审偏差和单训练seed使该结果不能推广为无条件真实质量差。原生F1差−0.031730，95%区间[−0.075178, +0.011078]，也没有确立候选优势。[冻结主比较](/data/milai-experiments/20261112-reader-utility/new-confirmation256-primary-summary-v1/summary.json)

![确认首次的来源支持与辅助原生指标](/data/milai-experiments/20261112-reader-utility/confirmation-first-results-figure-v2/confirmation-first-results.png)

相对共同S1，10k＋Q的来源差−1.563个百分点，区间[−7.422, +4.297]，未知识别范围[−21.484, +21.875]；原生F1差+0.009811，区间[−0.034361, +0.054334]。相对规则，来源差+7.813个百分点，区间[+1.172, +14.453]，未知范围[−11.719, +31.250]；原生F1差+0.067035，区间[+0.021468, +0.112175]。这些次比较是预定补充，不替换负向的主比较，也不证明至少+5个百分点的可靠提升或训练seed稳定性。[S1次比较](/data/milai-experiments/20261112-reader-utility/new-confirmation256-common_s1_secondary-summary-v1/summary.json)、[规则次比较](/data/milai-experiments/20261112-reader-utility/new-confirmation256-rules_secondary-summary-v1/summary.json)

![确认首次配对差与未知范围](/data/milai-experiments/20261112-reader-utility/confirmation-first-results-figure-v2/confirmation-paired-contrasts.png)

固定/10k/规则/S1的材料充分判断分别124/102/85/100；其余材料判断为不足85/94/120/102、未知45/58/49/52，每方法另2项未决评审。材料充分与完整支持首次是不同层，S1还有1项自动材料充分但Reader失败。图表已生成PNG/PDF/CSV并视觉检查；v2只调整刻度密度和文字精度，两份CSV与v1逐字相同。[图表及数据](/data/milai-experiments/20261112-reader-utility/confirmation-first-results-figure-v2/manifest.json)

四方法的实际控制行为与交付量如下，每方法均有256个最终HANDOFF。规则的992次READ全部observe-only，随后256次参数化HANDOFF；10k候选有5次参数化HANDOFF，固定与S1为0。更多读取、参数化选择或更长包本身不证明质量收益。

| 方法 | 实际控制状态 | SEARCH | READ | 预算强制停止 | 平均终点包JSON tokens |
|---|---:|---:|---:|---:|---:|
| 固定上下文 | 1,546 | 256 | 1,034 | 5 | 1,201.93 |
| 10k＋Q | 1,366 | 255 | 855 | 14 | 935.57 |
| 规则 | 1,504 | 256 | 992 | 0 | 625.14 |
| 共同S1 | 1,065 | 256 | 553 | 2 | 627.71 |

token数来自原准备器对序列化packet JSON的计数，不是纯证据正文或完整Host提示。固定采集包含共享Source库首次创建，其余方法复用，原collector wall不能直接当公平的方法延迟。10k与S1有24来源的完整准备请求相同，10k与规则2、规则与S1为1，固定与其他均0；首次没有因此事后合并或择优。全部5,481个事件与1,024个终点绑定已核对，行为统计不使用答案或原生标注。[控制与材料量](/data/milai-experiments/20261112-reader-utility/confirmation-controller-work-v1/summary.json)

预定作者128绑定也已全部关闭，覆盖同32来源×4方法，而非128个独立来源。作者按实际首答、交付材料、原生问题身份及字面引句核对，保留所有失败。

| 方法，每方法32绑定 | 完整受支持 | 不完整 | 未知 | 错误 | 执行失败 |
|---|---:|---:|---:|---:|---:|
| 固定上下文 | 10 | 12 | 8 | 1 | 1 |
| 10k＋Q | 8 | 13 | 8 | 1 | 2 |
| 规则 | 7 | 14 | 7 | 2 | 2 |
| 共同S1 | 8 | 15 | 4 | 1 | 4 |

作者非独立、未盲化且存在跨方法源文暴露；相关工作与直接比较、局部语言筛选与全部实验范围、核心架构与完整细节等判断有解释空间，不将作者当真值或替换主要标签。S1在MDL与GAN两个样本中材料充分但首答失败，材料层与任务层保持分开。作者与原自动判断的对照也已关闭：完整支持二分类18/128项不同，按固定/10k/规则/S1分别7/5/2/4；17项自动为完整而作者未认定完整，1项相反且带引用屏蔽。共同否定和未知也会计入二分类一致，因此不能把一致率当准确率。主要分歧是问题范围、背景与实际变量、局部数据与整体数据、材料完整性的解释，另有语言清单问题被人口/GDP解释替代；作者本身仍有解释局限。原标签未改。[作者128完整记录](/data/milai-experiments/20261112-reader-utility/new-confirmation-all128-author-closure-v1.json)、[作者与自动对照](/data/milai-experiments/20261112-reader-utility/new-confirmation-author-teacher-agreement-v1.json)

预定128次第二次Reader已按冻结队列开始，固定方法32次已完成，其余继续运行，使用同32来源、同终点与完整请求，不重跑控制器、不替换首次、不best-of-two、不把来源N翻倍。准备和稳定性汇总入口已分别通过28项、9项相关测试；实际稳定性仍需真实第二次结果，来源标签变化也包括评审分组/采样影响，不能全归因于Host波动。

当前仍需关闭预定第二次读出、相应来源评价及稳定性，并完成去重后的已测成本与未测范围、五层综合和计划验收。没有产品默认、权限、Canonical或服务配置迁移；功能运行及负结果留存均不等同于方法已取得优势。
