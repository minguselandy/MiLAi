# T0 开发标注与评价协议

本协议先于自然问题及Reader结果。仅适用已冻结的32个RFC公开更正候选及其96份实际来源，不把它们称作32个已证实独立历史，也不将RFC纠错直接推广为个人对话中的规则变化。全部是开发材料；没有独立人类标注者或独立Judge，本轮标注及复核统一称单人开发审查，多个同族工作代理不增加独立语义样本或实验模型家族。

## 创建次序与权限

自然问题须晚于B1/B2/B3规则、实际源码、query-free metadata与片段投影的冻结。此后方法实现者不读问题、答案或评价结果，不按T0表现修选择器。标注者只读既有来源、来源资格/语义审查及冻结来源身份；不读候选排名、选择结果或Reader答案来挑题。全部32候选保留，不能按某方法胜负换题或换历史。

运行时query文件只含query_id、origin_id及question；来源/权限/cutoff/config由共同driver绑定。query_kind、答案约束、解释、充分集合、许可与语义标签只在独立evaluator目录保存，不能被Writer/Selector/Reader driver导入。源文件ID用于来源绑定，不作预测特征。公开RFC编号可自然出现在问题中，不使用隐含题型ID或标准动作提示。

## 每历史四种问题

围绕实际技术更正写四个英文自然问题：当前明确要求、原陈述回放、追溯适用、跨对象/时间/格式的范围边界。每题必须有实际主题与约束，不仅替换编号或问法。题目不必强行可答；不能为满足8/8/8/8配额虚构生效日期、变化历史、对象差异或世界事实。若某类仅能构成给定档案不足的诊断，明确标为该类诊断，不能将它计作自然关系歧义发生率。原计划32×4是开发起点，实际类型分布与适配不足照实报告。

“当前”限于给定冻结档案支持的修正文义；题面本身明确给定RFC及其公开更正的范围，不将仅evaluator知道的cutoff变成隐藏答案条件，不断言覆盖全部后续标准。reported/verified/publication日期与业务effective时间分离；公开Verified状态不证明某实现何时改动，也不证明所有历史使用情况。陈述回放允许引用勘误复述的旧文，但必须保留“勘误所引旧文”与“冻结RFC实际旧文”的区别。原件冲突、错误节号、TBD、仅HTML/PDF适用等情况不能人工修进运行时。

## 隔离的逐题标注

每题至少保存以下字段：

- query_id、origin_id、question、query_kind、archive_cutoff及history hash；
- solvability：SOLVABLE、PARTIALLY_SOLVABLE、ARCHIVE_INSUFFICIENT或ANNOTATION_UNKNOWN；answer_mode、逐项required_constraints、allowed_partial_answers、forbidden_claims、remaining_uncertainty；
- compatible_interpretations及open_set=true。它们是有证据支持的局部解释，不伪称完整世界枚举或可直接归一化的后验；
- minimal_sufficient_evidence_sets：可解题至少一个集合，每个成员为Source/hash/codepoint [start,end)/逐字quote及其支持的约束。保存实际可替代集合；erratum已经同时引用旧文、纠正文和注释时，不强制再读RFC才能算充分；
- evidence_set_status、最小性理由及遗漏替代集合的风险。不能完整核实集合时标unknown；档案不足题为null，覆盖N/A，不能填0/1；
- 各来源对该题的直接消歧/部分帮助/无关/误导/重复/unknown标签及理由；只在evaluator使用；
- 每题预先写明utility的0/0.5/1语义锚点、严重forbidden_claim及哪些错误使正确片段只能计部分分；
- 审查者、实际读取路径/hash、限制及是否已看过方法结果。

充分集合是支持允许答案的语义片段集合，不要求整份RFC或整个更正连通分量。逐字绑定只证实出处；最小性、充分性和替代性由开发语义审查判断。若问题只能部分回答，全题minimal_sufficient_evidence_sets为null，另存partial_answer_support_sets与不可答部分；可答部分覆盖只单列，不计入全题充分覆盖分母。各集合可包含多个互补片段；同义表述、同一quote的重复位置及公开旧引文可成为等价替代。无法穷尽所有集合的覆盖数字是已枚举集合上的保守估计；未命中记录NO_ENUMERATED_SET_COVERED，不能自动断言候选或包装发生语义漏证，更不能归为关系缺口。只有替代集合风险已审清时才能使用该最早断点标签。

冻结前交叉检查每题可解性、约束和至少一个最小充分集合。冻结后如发现标注错误，保留原标注、记录勘误并将该题的预注册评价列为无效/不确定，另报探索性修订；不得静默改gold再重跑Reader。

## 实际比较与断点

T0主臂只有B1与B2，128题×2臂，主Reader材料预算2048；每槽一次实际Reader，沿用R0。全部方法共享candidate IDs、metadata、权限、分段、tokenizer和Reader；512/1024可作无模型选择覆盖曲线。B3已定义但不把未运行的B3/B4/M补成模型样本。B4自然条件不足维持NOT_RUN，不宣称超越通用主动取证。FullArchive不是必要主臂，若启动需先独立预算/准入，不能免费拿来改答案。

主结果逐题保留全文输出、成本、实际材料、候选与选择/遗漏。用精确Source/hash及codepoint区间并集检验：某一充分集合的每个片段是否全部在实际K32中，是否全部实际送达。主whole-query充分覆盖分母只含SOLVABLE且E*已核实的题。PARTIALLY_SOLVABLE、ARCHIVE_INSUFFICIENT、ANNOTATION_UNKNOWN全题覆盖均为N/A；部分题只单列其明确可答约束覆盖。不同来源的相同文字不能自动代替有来源归属要求的证据。relation完整组覆盖、quote投影覆盖与语义E*覆盖分别报告。

最早断点依次为：档案本身不足；标注未知；候选遗漏；预算/包装遗漏；证据已送达但Reader解释错误；仍需关系假设/消歧。一个题可以另记多个伴随错误，但最早断点不能由下游答案反推。只有证据确实存在、允许预算下可送达且简单法留下可重复的关系消歧缺口，才可支持G1。预算可行性必须由evaluator保存实际公共单元集合S⊆共同K32，在同render/包装/tokenizer下合计≤2048且覆盖一组已核实的全题E*；不能只算裸quote长度。这个离线见证只用于诊断，不进入runtime，不形成新Reader主臂。没有候选池内同预算可行见证的题不能支持选择器的关系消歧缺口。普通文本检索/技术推理错误、公开关系缺失、时间字段unknown及Reader日期误归因不单独支持复杂预测器。

## 评分与费用

在隐藏方法名和成对位置的副本上进行开发语义评分：utility=1表示满足全部允许答案约束且无实质矛盾，0.5表示有正确实质部分但遗漏/混合错误，0表示错误、对已标明确可答内容没有正确实质部分或全拒答。PARTIALLY_SOLVABLE若完整回答全部允许部分并保留剩余不确定，可得1；ARCHIVE_INSUFFICIENT若合理指出档案不足且不补造，也可得1。ANNOTATION_UNKNOWN的utility保持unknown，不进入已评分均值但保留计划槽位。无依据确定性与可解题过度拒答另列布尔值并附具体输出证据；字面关键词命中不自动计语义正确。四类query分别报告，不将其未经定义汇总为单一准确率。方法盲化降低先入影响，但不改变单人开发审查的限制。

未运行、接口失败、unknown usage、超预算和语义失败分别列出，保留128×2计划分母，不重试挑答案。形成、索引、metadata存储/读取、CPU、逻辑I/O、Reader provider费用分别报告；未测物理I/O/GPU时间/价格保持unknown。2048只代表实际Reader材料，额外共同选择器metadata规模及生命周期费用不能省略。

T0以来源历史分组做描述性配对结果；RFC关系组、已知派生组和JSON/CBOR/CDDL宽依赖族做聚类敏感性分析，不把4query或seed当独立来源。128题与32候选不是正式功效或泛化保证。G1判定后再决定条件性T1；无可信关系缺口则采用简单方案并收缩问题，不为继续开发重挑历史。
