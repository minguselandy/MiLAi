# WP6：固定正确正文后的实体与动作诊断

协议状态：R1六次首响应完成，实际动作续接待验。执行依据见[当前Goal](MILAI_NEXT_IMPROVEMENT_EXECUTION_GOAL.md)。
这是X1的首响应切片，不是完整业务验收；写入责任C3另行实现和冻结。

## 问题与竞争解释

历史E2已出现正确State后错误动作：partial把准确实体改成单数；distinct在2→3→4后仍保留3。
H1：生成标题与精确源实体竞争；H2：旧助手/工具材料或动作生成仍覆盖正文。
只改变标题能缩小H1解释范围；全条件仍错不能自动归因于某个唯一内部机制。

选取已暴露的partial/pre_model请求23和distinct/turn_end请求49；不是新样本。
原始请求SHA分别为`b5f95c4fd9ab5ceddc072fb78aeb3ef85afbd8880bf3840e2a1eb56e4905ac4c`、
`766b91fe861cadeee952af26afa87ce3557d0715e643fe2ebec1d9225b04b7e6`。
两arc为独立报告单位，六输出不能当六独立场景，不估计总体置信区间。

## 冻结合同

方法为C2 `93cb3e9cb405c97d52bc807b54f532b2a5b489f3`，独立detached checkout，
使用已有read_probe runner。完整活动源码、依赖、配置、输入与顺序进入prepared identity，
不受并行C3源码修改影响。C2实际Fast36329556696已成功，测试merge为
`972e9a94786d0862161c2c640677d2148f9ca843`，并非合并main。

每个arc三条件：原标题、只换成来源精确实体的标题、删除派生State但保留所引来源事件。
前两条件正文、needs、evidence和原消息相同；第三条件不是等信息量/等token的纯标题干预，
所有原始messages均保留；partial初始完整计划仍在原历史中。不得用它直接宣称State压缩或算法收益。
各条件共同采用C2 strict工具描述，参数schema与历史native相同；历史原生回执不改写。
运行时不读取rubric，也没有按样本ID选择业务参数的代码。

顺序固定：partial/original → distinct/source_title → partial/raw_sources →
distinct/original → partial/source_title → distinct/raw_sources。
Root串行执行，每项恰好一次Host首响应；无重试、替换或挑最佳轨迹。
各job请求独立且没有共享会话、Store、checkpoint或业务状态；本切片不执行工具。
统一Qwen3.6-35B-A3B-FP8、temperature=0、max_tokens=4096、thinking=false、容量65536。
不改共享服务，embedding调用0。预检每项容量均通过；输入token按实际HTTP回执另报。

精确字节：inputs `e79ac6613558f30517148ff2957c2c5805297ab53ea47defdec15c6a299cbe6e`；
config `32a7705ce5f60861a0547350c7f9b968bdbb1d955797b91607e430984c02a0d5`；
rubric `c300f6edf67bca9c4fd6557454fd9b307d4af46a1930696ad0770b92a8049519`。
prepared identity `ad997c16dd13b77c4a47489a6e3109add44454d7c5c1f5865c75c8ecfb667159`。
[机器冻结记录](../data/manifests/next-improvement-wp6-presentation-freeze-20260927.json)
保存所有source hash和容量/费用前态。语义输入与rubric分文件发布，rubric只供Root事后评分。

## 评分与继续条件

首响应只有恰好一次reserve_and_label，且item_key、quantity、destination、packing均精确
满足冻结rubric，才算direct_correct_action。错误字段或多次业务尝试为direct_wrong_action。
memory/search/read等先行工具请求标requires_tool_continuation，不当普通语义失败。
无动作回答及基础设施/格式错误分别记录。保留全部实际输出、调用、空结果和失败费用。
这项分类只描述第一提案；即使正确，也没有业务世界成功。

随后需要在实际隔离合成业务世界执行并继续Host，验证真实回执、持久状态、后续回答，
才能验收动作消费。所有需要续接的条件仍保留，不选择性只续接正确项。
该后续有独立冻结：当前普通memory前态从历史先前generation receipt对应的Store操作恢复，
不能把未来正确记录放回过去。partial当前mira namespace为空，先前noel记忆保持其他owner；
distinct有两条旧3-unit记忆，不能清成正确oracle bank。标签服务partial失败、distinct可用。
初次提取误用不存在response键而得到空前态已在调用前否决并保留；改用真实receipt ID核验。

预调用连续账本：2768 generations、3420333 generation tokens、18746 embedding tokens，
SHA `a9d4c681e2bee395c170a4672b4895a442522df47951c9a043e9f6b3a32e3580`。
仅使用原checkout的连续账本；开发代理/CI成本不混入。决定Continue这一有界诊断，
不重复旧全套实验、不部署第二模型、不宣称unseen或Product价值。

## R1首响应实际结果

| 条件 | partial | distinct | generation tokens（两arc合计） |
| --- | --- | --- | --- |
| 原标题 | 错：单数item key | 错：3而非4，destination删去storage | 2695 |
| 来源标题 | 错：item key自行添加括号限定 | 错：3而非4 | 2704 |
| 原来源，无派生State | 首提案四字段精确正确 | 错：3而非4 | 2206 |

[逐例机器结果](../data/manifests/next-improvement-wp6-presentation-results-20260927.json)
核对实际trace request与保存请求完全一致、回执ID一致；六次HTTP全部200且usage已知。
总计6 generations/7605 tokens/0 embedding，连续账本为2774/3427938/18746。
这些是1/6正确首提案、5/6错误首提案，不是业务成功率；两arc不能支持总体显著性结论。

Observed：原标题与来源标题均未解决两个错误；无派生State仅partial首提案正确。
Expected：保持精确key与4-unit当前要求。实际链为冻结请求→HTTP→模型JSON提案；
首断点在动作参数生成，尚未执行工具。H1单独换标题足以修复不获支持；H2旧材料/
消费生成问题仍与现象一致，但不能从这一切片区分模型内部原因。通用修复候选是明确
材料角色或减少派生竞争文本，而不是样本特例/实体改写规则。混杂包括派生正文冗余、raw_sources的说明头也随材料角色改变、
strict工具呈现共同变化、temperature=0仍非确定性，以及distinct的旧memory/助手回执。
因此raw_sources改善不能单独归因于删除某一段正文；它是明确冻结的复合材料条件。
决定Pivot标题单项修复，Continue六臂真实动作与后续回答；保留所有失败和费用。

文档更正：最初冻结说明误把partial单条引用事件的信息不足写成raw条件缺少约定；
实际raw messages含完整初始计划，输入始终未改。原冻结说明字节保存在
[协议快照](../data/diagnostics/next-improvement-wp6-presentation-r1/protocol-freeze.txt)，
冻结manifest中的protocol SHA指该快照；本更正不改变输入、顺序、rubric或计分。
