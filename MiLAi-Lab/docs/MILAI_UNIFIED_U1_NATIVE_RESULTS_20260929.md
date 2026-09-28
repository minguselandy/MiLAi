# Unified V8/V9 U1 原生功能切片结果

状态：**U1 FUNCTIONAL COMPLETE；Continue U2**。36个冻结Host jobs及18次离线Judge均已完成，无自动重试、未完成Host或Judge解析失败。
实际HTTP、MCP、持久Store、业务world与原生评分链已接通；小切片不证明稳定收益。整个统一Goal继续active，研究目标NOT_ACHIEVED，Product NO_GO。

## 冻结身份与范围

方法源码A：`aa7a25ed203cc9b3a93801d7ac00ae7bfa255c83`；输入/执行提交B：`94d3b18ef6b8c1dfd6019703df8e84163628c360`。
报告提交不替代B。[事前协议](MILAI_UNIFIED_U1_PROTOCOL_20260928.md)、[调用顺序](../data/diagnostics/unified-v8-v9-u1/run-order.json)
及[评分合同](../data/diagnostics/unified-v8-v9-u1/scoring-contract.json)原字节保留。
全部六份正式prepare在B完成，execution-freeze SHA256为`d433cd562df0f0a080474792f65978a64a5cd5b26c6b1fd405ca7022023b96c3`。
36个Host jobs结束后，18份答案批次冻结为`2542f7dcaa9827a628edd2c109cd941ef3e260b7f1f8d307b9832fae1ba5a524`，才加载gold并评分。
逐项状态、原生标签、结果/轨迹/世界哈希与费用见[机器可读结果](../data/manifests/unified-v8-v9-u1-native-results-20260929.json)。

MemSyco沿用六个完整原题/六来源组，三任务各2题。MERIT沿用三域easy/hard各1完整arc、seeds5—10；
每臂6 arcs、30 episodes、12 dependent episodes、38公开消息。三臂共90 episodes，不能当作90个独立任务。
选择清单、原始输入、世界、工具、checkers和gold均未修改；没有按分数换题或重跑失败题。smoke现已曝光，独立U2尚未运行。

Host为Qwen3.6-35B-A3B-FP8@7862、65536容量、temperature0、max_tokens4096、thinking=false、native auto tools；
embedding为bge-m3@7861、1024维；每公开消息最多12次生成，真实HTTP并发1。Root执行全部真实调用与评分。
本轮服务/模型设置未改。原生reference使用已锁定独立LiteLLM/OpenAI环境，MiLAi使用foundation环境；这些是系统合同差异。
MemSyco reader采用固定2025-06-01日期、空extra instruction及上游格式；本地temperature0不同于上游0.2。
Judge为相同Qwen家族、max_tokens1024、一次尝试，存在同族和单次评审偏差，不与官方榜单直接排序。

## MemSyco 原生分类分数

表中分母均为2；scope为accuracy且无错误扩大偏好，valid为使用最新偏好且无旧偏好污染，personalized为回答正确且采用偏好。
这些不同任务不合成为一个“Agent Memory总准确率”。所有18份答案均可解析。

| 方法 | Scope pass | Valid selection pass | Personalized use pass | generation calls/tokens | embedding tokens |
| --- | --- | --- | --- | --- | --- |
| RawDialogue，共同reader | 1/2 | 1/2 | 2/2 | 6 / 9,996 | 0 |
| ordinary/MiLAi形成＋共同reader | 1/2 | 2/2 | 2/2 | 18 / 35,751 | 1,276 |
| MiLAi只读Agent查询扩展，复用上述形成状态 | 0/2 | 2/2 | 0/2 | 8 / 7,697（查询增量） | 24（查询增量） |

次指标：RawDialogue的scope错误扩大偏好1/2、旧偏好污染1/2、正确偏好使用2/2；
MiLAi共同reader对应1/2、0/2、2/2；Agent扩展对应0/2、0/2、0/2。拒绝回答使错误采用为0，不代表任务通过。

六次question-free归档形成实际产生18次Host-origin MCP `manage_memory` CREATE，形成记录数依次2、4、5、5、1、1。
读取时程序经MCP search获取同一owner的记录，18条全部交付、0条因预算省略，查询后与形成快照一致。
第一题的两条真实ID为`3b4ddeeb-d07e-4f17-b264-0b2c4cee5e6d`及`89bfae6a-c01e-4851-8b8d-223bf11a246d`；
生成提案、MCP返回created、Store重读、后续reader请求可逐条关联。此为基于归档边界的主动CRUD，不证明Host自己发现维护时机。

Agent查询扩展保持只读目录、新checkpoint、同一形成快照。六题均未改写记录；仅两道valid题自然调用search_memory并通过，
其余四题没有调用工具，直接要求补充上下文。没有额外强制检索来补成绩。
共同reader形成费用为12 calls/30,603 generation tokens及18 embeddings/1,132 tokens，reader为6 calls/5,148 tokens，程序检索为6 embeddings/144 tokens。
Agent扩展的7,697只计复用后查询；若单独冷启动同一形成＋Agent查询，应计20 calls/38,300 generation tokens及1,156 embedding tokens。
这些形成费用在实际连续账本只收费一次。共同reader全生命周期generation为RawDialogue的约3.58倍，单独reader较短不能冒充总成本下降。

## MERIT 原生业务结果

| 方法 | episode成功 | dependent成功 | 整arc全成功 | generation calls/tokens | embedding tokens |
| --- | --- | --- | --- | --- | --- |
| 原生NoMemory | 16/30 | 0/12 | 0/6 | 101 / 88,942 | 0 |
| 原生FullReplay tail60000 | 28/30 | 12/12 | 4/6 | 81 / 156,765 | 0 |
| ordinary/MiLAi＋合法历史 | 26/30 | 10/12 | 3/6 | 89 / 288,222 | 30 |

| arc（依既定顺序） | NoMemory | FullReplay | MiLAi |
| --- | --- | --- | --- |
| arc5-000 | 3/5 | 5/5 | 5/5 |
| arc6-000 | 3/5 | 5/5 | 5/5 |
| d2-arc7-000 | 3/5 | 5/5 | 3/5 |
| d2-arc8-000 | 3/5 | 5/5 | 5/5 |
| d3-arc9-000 | 2/5 | 4/5 | 4/5 |
| d3-arc10-000 | 2/5 | 4/5 | 4/5 |

全部90个episode的pre_satisfied为false、Host均完成；成绩来自实际执行后的官方world checker。
NoMemory依赖题0/12是观察结果，不是预设前提。FullReplay最大memory block为15,774字符，本批没有触及60,000尾截断；
仍保留上游递归`[memory shown]` transcript，不能称为无冗余强FullHistory。

**MiLAi六个arc各episode后普通记忆均为0。**实际Host-origin MCP只有4次search_memory与5次read_history，无CREATE/UPDATE/DELETE。
其冻结工厂明确配置`complete visited owner checkpoint history`，即合法已访问完整历史＋CRUD；不能根据共同配置中未被该工厂使用的
`history.enabled=false`字段，把它解释为retained-memory-only。实际请求包含先前用户/工具证据。因而26/30不能证明主动持久维护、SER或State–Attention收益。
它与FullReplay的格式、工具目录和运行器也不同；generation tokens约为后者1.84倍，不作纯压缩或位置因果解释。

## 首断点、竞争解释与决策

1. **Scope题mso_hard_000072。**Observed：共同reader未回答原发音情境，改用不相关项目管理示例；Expected：保留独学偏好，同时处理需要外部反馈的局部边界。
   归档→两条偏好CREATE→两条都检索交付→reader回答链成立；原发音情境未保留于这两条记录，独学偏好本身存在。
   首个可见信息损失在形成材料，后续又采用了无关决策偏好。解释A是只存耐久偏好而丢失情境；解释B是reader/排序的干扰，而非检索漏掉独学记录。
   RawDialogue也未按本地Judge通过，因此不能把差异全部归于形成。Judge把已有决策偏好称为幻觉、把underuse解释配成misuse标签，理由有语义疑点；原标签和原失败均保留，不改分或重评。
   通用候选是比较完整历史、原文hybrid与真实摘要，随后若需要再做固定材料诊断。最小下一步为U2已选来源组；Continue比较，暂不提示词微调。
2. **只读Agent的四个无检索失败。**Observed：已有合法记录但未取材，转而询问缺失背景；Expected：在已有工具能提供必要材料时完成原问题。
   首断点为工具选择/材料取得前。解释A是泛指问题未触发自然搜索；解释B是归档形成欠缺情境使Host预期信息不足。
   两个valid题确实调用并获得材料，排除接口整体不可用，但不能证明所有失败经搜索必能修复。候选是独立显式检索参照和必要固定bank诊断；
   共同reader已提供前者，Agent扩展保留失败，不强迫同题重试。Continue U2主表；不把低查询成本当成有效压缩收益。
3. **MiLAi的D2 easy两个依赖失败。**Observed：HTTP返回的deploy参数从来源`v8.1.0`/`v7.0.7`变成`8.1.0`/`7.0.7`；
   工具按参数成功执行并持久化了不匹配的版本，官方exact checker失败。Expected：原样传递已批准目标。
   首断点为生成参数：两次实际生成请求都含正确带`v`原值，历史不可见的解释被证据否定；更符合模型对版本字符串的规范化，或多余呈现诱发的错误复制。
   原world和工具不做补前缀。通用候选为有真实来源的精确参数/对象引用，属于U3-O问题线索；先完成U2强参照，再决定是否值得独立扩展，不能把修订臂混入原生成绩。
4. **D3两个共同邮件失败。**Observed：三臂都把用户小写`pick`写为句首`Pick`，真实邮件已入world；Expected：官方`must_contain`大小写敏感子串成立。
   解释A为工具未执行或记录丢失；解释B为模型改写原文而不符合严格评分。实际邮件持久化及官方d3.py的检查函数支持B，排除A。
   原分母和六次失败不变，不新增“语义通过”替代主分数。通用精确文本传递可在后续独立问题中检验，但不为此改工具/checker或为smoke补跑。Continue并报告测量敏感性。
5. **MERIT全程未写普通记忆。**完整历史可直接支持任务，零写本身不违反这些原任务。解释A是合法替代路径使写入无必要；解释B是Host维护倾向弱。
   当前证据不能区分，也不能以零写直接触发强制writer。MiLAi的未来维护收益保持NOT_ACTIVATED；U2比较共同历史权限下的简单对照，禁止把历史旁路隐藏。

本批支持真实MCP/原生评测链可用，反驳“退出成功即语义通过”“有CRUD即可证明维护收益”“查询便宜即可证明总成本下降”。
采用成熟底座和薄适配；不新增常驻审计、额外selector或持久Decision State。所有定位只读旧证据，未改变冻结模型、数据、scorer或方法。

## 全部费用、工程检查与复现

U1新增**321 generation calls / 613,029 generation tokens / 1,330 embedding tokens**。
其中Host/形成/reader为303 calls/587,373 tokens，Judge为18 calls/25,656 tokens；embedding30次，费用已按36个job逐项与实际HTTP usage、连续账本核平。
连续账本从3306/4,212,816/23,632增至**3627/4,825,845/24,962**，当前unknown usage为0；旧嵌套账本和历史未知用量仍保留。
本统一Goal含此前MCP R1失败及R2验收累计新增**326 calls/620,642 generation tokens/1,392 embedding tokens**，不包括开发代理token。
原始预算前后快照、HTTP、工具、Store/checkpoint和world留在ignored artifacts；公开精简哈希和汇总，不上传DSN、数据库、原始语料或私密轨迹。

MCP HTTP/resource观测的inclusive CPU/wall与底层模型/Store时间重叠，不能相加宣称净开销。逻辑字节/次数有原始记录；
物理I/O、Store净CPU、独立GPU小时和货币费用未知，不按0计算。没有把额外提取、失败、重试或观察费用清零。

[工程回执](../data/manifests/unified-v8-v9-u1-engineering-checks-20260928.json)的29个唯一窄目标、必要静态/矩阵/边界检查、
真实SDK MockHTTP dry-run、6个零模型prepare及单次构建已通过，未为发布重跑。
B的GitHub Fast run `36458779219`为success；条件跳过的Product/archive/tree-identity jobs不计为实际模型检查，也不声称另跑了Full workflow。

复现从B检出，按[来源清单](../data/manifests/unified-v8-v9-merit-smoke-inputs-20260929.json)生成/验证原始arc/world和既定MemSyco原题，
依[reference环境锁](../data/locks/unified-v8-v9-native-transport-20260928.requirements.txt)及既有foundation环境准备。
逐项执行run-order中的零模型prepare，冻结源码/输入/config/catalog/namespace/scorer，再依36-job顺序运行，最后冻结全部答案后单次评分。
私密DSN只通过`MILAI_LANGMEM_POSTGRES_DSN`注入；为新复现建立独立namespace、checkpoint、world与追加预算记录，不覆写本次单次执行。
Root本次入口、命令、时间、退出码及预算快照在`artifacts/unified-v8-v9/u1-native-r1/`；公开run-order提供可复建参数，私密现场路径不是其他机器的即用服务。

## Gate与后续

G0/G1在本批已使用资源/功能范围通过；没有宣称所有待用外部环境已验收。G2待U2，G3/G4/G5未由smoke建立。
下一项仍是独立MemSyco60题/54来源组与MERIT18 arcs，以及FullHistory、真实rolling summary、真BM25+dense、ordinary/实际不同候选、原生Mem0。
无实际差异的ordinary/MiLAi继续合并；首表可运行后接入第二外部SimpleMem或A-MEM。U3-O记录已观察参数问题，U3-W没有强制触发依据；
U3-P、U3-R、U4、U5仍按统一计划的具体证据/前置条件判断，最终U6逐项收口。第二模型、稳定unseen收益、跨进程故障恢复与Product准入均未完成。
