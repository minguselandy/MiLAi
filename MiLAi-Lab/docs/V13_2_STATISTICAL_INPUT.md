# v13.2 离线配对统计输入合同

状态为工程验收通过、研究验证未完成。`tools/analyze_v13_2_paired.py`只读取已冻结输入，
不评分、不生成问题、不调用模型、不导入运行时记忆服务。其合成数值检查不是pilot、
正式样本或独立语义评分。研究协议仍由`data/manifests/v13-2-statistical-design.json`决定。

## 运行与事前身份

在Lab目录使用已有环境：

```bash
/cra/memory/mx_memory/MiLAi/MiLAi-Lab/.venv/bin/python tools/analyze_v13_2_paired.py \
  --input artifacts/declared-paired-input.json \
  --design data/manifests/v13-2-statistical-design.json \
  --output artifacts/paired-analysis.json
```

输入包括`stage`（development、pilot或formal）、`plan`和`rows`。输出保存输入、
统计协议、分析工具SHA256，并对`plan`按排序键的紧凑UTF-8 JSON计算SHA256。
分析时生成的hash不能证明事前冻结；实际运行manifest须在输出前记录相同plan身份、
真实来源/模板依赖、评分程序、费用归属及正式样本规模/停止规则。不得在看过输出后改组、
删条件或选择最好的seed。工具能验证标识非空及组合唯一，不能判断来源是否独立、
模板是否只是换名，也不能验证签名、冻结时间或独立评分人的身份。

## 计划与真实结果

`plan`必须声明：

- `methods`：非空且唯一的方法ID，主比较M/B6_PLUS，次比较M/B2_PLUS；未提供的比较不计算。
- `metric`：事前确定的指标ID；只有`task_lifecycle_success`可进入clean非劣数值门禁。
- `requires_independent_rating`：布尔值，语义指标必须为true。
- `bases`：每个基础任务有唯一`base_id`、单独报告的`workflow`、非空
  `source_components`和`template_families`列表，以及非空`variants`列表。
  每个variant声明`condition`和字符串/整数`replicate`。

来源组件及模板家族的传递连接形成统计cluster；clean、异常、方法和多个seed均不新增
独立样本。workflow与condition分层报告，MemSyco三种任务不得合并成一个accuracy。
所有预定变体先在基础任务内取均值，再让基础任务等权；抽样cluster时保留该cluster
中的全部配对基础任务，以抽到的基础任务总数重新计算均值。

`rows`只含实际结果，键为`base_id/condition/replicate/method`，不允许重复或计划外行。
每行的`utility`为[0,1]数值/布尔值或null，`independent_rating`为布尔值；缺少该声明
视为没有独立评分。真实完成指标的预算耗尽/中断应按事前合同计失败；语义不可评分
保留null，不能把基础设施缺失冒充观察到的语义失败。完全没有结果的计划行也保留缺失。

独立评分标记必须回链实际盲审材料与结果，不能把Root事后诊断或同家族模型复核标为true。
每次分析只比较一个事前metric；其他指标另立输入且仍使用相同计划依赖结构。普通交付的
2048材料预算约束当前来源索引、一份当前普通包及其当前召回引用正文；过去回合不同包、
显式追加读取与真实业务工具材料仍进入实际HTTP账单，整个HTTP输入不称为2048以内。

## 费用与缺失

每行`costs`分别声明以下八项；未测/不可归属保留null或缺项，不补零：

- generation_requests、charged_generation_tokens、known_generation_tokens；
- embedding_requests、charged_embedding_tokens、known_embedding_tokens；
- generation_unknown_usage、embedding_unknown_usage。

费用必须来自连续账本与逐请求trace，覆盖Host、原生形成、writer、repair、索引、失败、
截断及重启。共享初始化费用须在事前manifest说明分配规则，另列未分配的setup桶，并将
所有行加setup桶对回实际账本；分配后不得重复计费。工具只计算输入费用差，不代替对账。
保守charged费用与known费用分开；存在未知usage计数或任何缺失费用的行另计分母。
unknown usage不能设为0；延迟、存储、美元和GPU小时不由token推算。

任一预定效用缺失时，全计划点差为null。下界给M缺失0、对照缺失1，上界反向赋值；
另外显示每臂全计划效用上下界，以及明确标为scorable-pairs-only的基础任务等权点差。
费用任一配对缺失时，该费用的全计划均值/区间保持null，不删行算出表面低成本。

## 区间与非劣门禁

默认20,000次cluster bootstrap、seed132026、2.5%/97.5%分位区间；效用、缺失上下界和
所有费用列使用同一批抽样，并记录抽样矩阵hash。少于20独立组件只报告描述性差异及
分母，不给推断区间；该工程阈值不是覆盖率保证，零观察失败也不证明零风险。

clean 5pp非劣数值判定还要求：formal阶段、主要比较、二元完整task/lifecycle success、
事前要求且实际所有计划行具备独立评分，以及最坏缺失下界的95%区间下限≥-0.05。
字段准确率、分数型utility、development/pilot、Root评分或缺失评分不能开此门禁。
输出的`ESTABLISHED_UNDER_DECLARED_PROTOCOL`只表示这些输入数值满足声明协议；
真实结论仍须审核事前冻结、来源依赖、原生任务评分、独立盲审和完整费用证据。

[工程验收](../data/manifests/v13-2-statistical-analysis-acceptance.json)使用20项合成数值检查，
实际实验样本、生成和嵌入请求均为0。新pilot、正式统计、精度规划和独立验证仍未完成。
