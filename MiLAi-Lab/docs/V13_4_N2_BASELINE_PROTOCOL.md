# N2 共同候选与 B1/B2/B3 规则（问题创建前）

本协议在自然 query 数为 0 时固定规则。B1 源码检查点为 `08f82d8`，真实 query-free 索引见 `v13-4-n2-chain-index-results.json`。当前只有开发来源；32 候选、四类各 8 条、语义独立性均不可由这份协议自证。

## 共同输入和成本

所有方法使用同一来源权限/cutoff、384-body-token无损分段、全文BM25索引、实际公开关系、K32候选池和Q0（time/scope/exception/relation全部保守保留）。不提供query_kind或gold mask。候选按全体正BM25分数排序，逐seed补实际关系闭包；seed在前，然后最短边距离、普通排名、冻结稳定tie。无固定seed/扩展槽配额。超过K明确列出池外成员/未闭合关系，不把它记成完整链。

主Reader材料预算2048，成本曲线512/1024。Reader只有一次，沿用N1 R0 prompt；R1仍不采用。公共证据单元的原文、来源身份、角色、观察时间、range及candidate handle全部计入实际材料token。形成的研究metadata只供选择器，不额外送入Reader；因而不存在未计入Reader材料的隐式提示。选择器所读metadata的逻辑字节、序列化token规模和CPU另报，形成/构建索引/解析/存储/读取费用均保留；不是免费知识。这明确澄清计划第16节“元数据与材料共同预算”的口径：2048只称Reader材料预算，包含实际送达的任何metadata；共同索引中的选择器线索是额外可见信息，须与材料合计报告规模和完整费用，不能把整条pipeline称为仅2048 tokens。该口径在问题和结果出现前冻结，按第07/08/15节的共同信息/实际交付合同执行。若以后把任何metadata送入Reader，它必须与原文共同占用2048材料预算，不能沿用本协议声称等信息。

共同metadata分两类：来源原生的字面时间/格式字段，以及已冻结Writer的抽取假说。两者都向各臂开放，不替换或“修复”57份Writer失败。原生字段仅按明确模板识别publication、reported、verified和Publication Formats；它们不能填补effective/valid_time。Writer只接受原冻结7份schema/逐字quote通过输出，其他57份维持全部unknown。每个cue绑定实际Source hash与quote的全部匹配codepoint跨度；只投影到与该跨度相交的片段，不免费广播到原RFC或其他来源。重复位置全部保留为ambiguous；仅相交但没有覆盖整段quote时标partial_projection，不能声称证据充分。选择器只收到当前K32内的投影ID。subjects/properties只保留在原metadata和旁路清单，不进入这三种选择器。字段在新问题创建前单独冻结。

冻结cue合同为dimension(time/scope/exception/relation)、value、quote_spans、provenance(native_public/frozen_writer)、time_axis(null/publication/report/verification/effective)。native_public不得生成effective；Writer unspecified保留null。日期只在query-free投影阶段从quote抽取，不能在query时额外读未选正文或从Writer value猜日期。每条time cue的quote仅含恰好一个不同的最长合法日期atom时才暴露date_literals；若quote中有显式轴词，其不同axis集合须恰为{time_axis}，否则日期特征为空。无显式轴词时允许使用cue声明的axis，仍保留Writer语义未验证标记。多日期/混合轴只使B2日期特征为空，不修改原cue，也不取消B3的time维度存在。原生Month YYYY不改写为ISO，仅其中独立年份可提供year粒度软线索。

## B1：chain_rag_v1

只连接带原文绑定的更正注释；同一RFC下不同勘误不是按日期/ID串接的supersedes。一个声明关系的原文前身、公开旧引文、新文和整份勘误见证进入共同证据组；没有原件匹配只保留quoted-only，TBD/缺明确块标签为unknown。文字出处校验不验证修订语义。

按普通seed先后优先完整组，组内采用冻结索引稳定顺序；首组使用query-free计算的确切整体材料token成本。后续组合成本为显式估计，pack按真实token原子检查完整组，不能静默截断。超出预算或K的链缺口明确记录，剩余完整单元继续尝试。关系完整性不等于E*充分性：erratum自含旧文/纠正文/解释时，必须允许其独立充分的替代集合。

## B2：temporal_scope_chain_v1

这是自建Temporal-RAG，不是Zep/TSM复现。候选池、完整组/包装/预算与B1相同，只重排组优先级。组内仍采用B1冻结顺序。未知字段不作冲突或排除条件。

只使用以下两项固定特征，按 `(T, L, -B1_group_rank)` 降序稳定排序：

1. `T` 为明确事件轴与日期配对的软匹配数。英文轴词采用casefold后的整词：publication={publish,published,publication,issued}；report={report,reported,reporting}；verification={verify,verified,verification}；effective={effective,effect,valid,validity}。先从完整问题抽取最长的合法Gregorian日期atom，依次接受ISO日期`YYYY-MM-DD`、ISO年月`YYYY-MM`或独立四位年份；与字母、数字、下划线、点或连字符相邻的日期不接受，紧随RFC/version/ver/v词前缀的年份也排除，避免RFC编号和版本号冒充日期。无效完整日期不得降级成有效年份。
   再按`[,;.!?\n]`划分分句，只有同一分句恰有一个不同axis、一个date且没有以下标记时贡献一对(axis,date)：整词`before after since until earlier later latest current currently now no not never neither nor without`、连续词短语`as of`（词间空白），或原分句含英语缩约`n't`/`n’t`。有比较、否定、多轴、多日期或缺字段则该分句T=0，不做全问题轴×日期笛卡尔组合，不执行区间/大小比较。cue日期精度必须不低于问题日期，且已知年月日分量按prefix一致；一个(axis,query-date)最多计一次；跨合格分句仍按同轴prefix去重，只保留最细的显式日期（如2020与2020-03-04仅留后者），不同且互非prefix的日期分别保留，不把同一日期年/月/日重复加分。仅有year粒度cue可能因此不匹配更细日期，属于本规则的保守限制。effective仅接受Writer明确标为effective且quote有日期的未经语义验证线索；reported/verified/publication永不跨轴替代effective，也不代表历史快照当时可见。
2. `L` 为scope cue与自然问题的最大词法Jaccard重合。只取scope字段，不把time/subject/relation字段混成scope；使用Unicode casefold后`[A-Za-z0-9_]+`词，去掉长度1及冻结停用词`a an the and or of to in on at for from with by is are was were be been this that these those it its as`. cue文本使用原生格式值或实际Writer value，不能使用source/candidate ID、文件名、顺序或evaluator类型。

组特征只对实际K32内成员投影到的cue去重后计算（不使用同组池外成员cue），不因同一quote投影到多个片段反复加分。若所有组T=L=0，结果必须逐项等同B1。此版本没有可靠区间/对象逻辑来判硬冲突，所以不虚构负冲突分、不以unknown排除。空问题词集、空scope词集或无scope时L=0。报告requested_method、effective_method及fallback原因、有有效日期cue的来源比例、scope cue覆盖、真正发生重排的query比例以及与B1相同的比例。字段稀缺导致的退化不能证明“强时态系统已被排除”，也不能独自支持G1。

## B3：slot_retrieve_v1

Q0把time/scope/exception/relation均视为潜在未决维度，不进行额外LLM规划，也不因Writer少列unresolved字段而断言已解决。每候选片段的`d`为它实际绑定的不同维度cue存在数（0至4）；`score=d/max(1, unit_tokens)`。cue出现只是可能有帮助，不证明有效时间/范围已确定。按score降序选完整片段，同分保留共同候选顺序；零分片段仍保留在尾部以继续尝试装包。d只计算四类实际cue，不计subjects/properties/unresolved列表，原生日期只计time、原生format只计scope。全部d=0时直接使用原B1计划和pack，selected IDs及材料须相同。B3的选择单位是片段，不能把它的成本标为B1首个完整组exact cost，也不能冒称完整组已选；另报实际关系覆盖。按真实共同预算装包、同样保留遗漏和估计误差，不通过更少读或更多拒答自行宣布收益。各方法都可见相同cue，B3不独占人工补槽标签。

## 未开放的结论

B4主目标按已锁定EC²-style定义，成本只除一次。有限世界参考210项算术验证不等于自然B4已可运行；没有共享诚实结果模型则NOT_RUN，不用gold先验补齐。

T0自然问题与E*必须在本规则和实际metadata投影冻结后创建。所有方法实现者继续隔离于问题/答案。T0运行还需当前代码/配置/数据/预算冻结与实际trace。只有证据存在且同预算强简单法仍留下可重复的关系消歧缺口才考虑G1；原生字段不可得、引文匹配失败、普通技术推理错和Reader误读分别报告。
