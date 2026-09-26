# v20 P4：非温度控制完成，继续刷新成本优化

状态：`PASS_ADVANCE_P5`。五个预先定义的非温度实例均通过机制与最终动作判定。加上P3原三例，当前8个小规模开发控制通过；这不是未见验证或总体可靠性结论。[总Goal](MILAI_LONG_HORIZON_EXECUTION_GOAL.md)继续执行。

| 实例 | 最终结果 | 更新后自然search | exact get | 回复降权次数 |
| --- | --- | ---: | ---: | ---: |
| categorical_route | 实际记录South | 0 | 3 | 3 |
| boolean_approved | 实际记录true，JSON布尔类型保留 | 0 | 3 | 3 |
| deleted_evidence | 0业务动作，明确缺少当前依据并请求warehouse | 1 | 0 | 3 |
| multi_revision | 依次送达X@2/South、X@3/West，实际记录West | 0 | 3 | 5 |
| assistant_only_stale | 旧search已不在请求，旧回复仍被降权；新search后实际记录South | 1 | 0 | 4 |

五例共15条公开消息完成、4个获批业务动作、0次Host memory写入。18次普通回复降权均与实际请求位置、response ID、生成request、原正文和投影hash核对；15条lineage记录绑定实际交付的版本。旧search ToolMessage与原助手正文留在checkpoint。删除不读取不存在的当前正文，多次更新使先前基于X@2的回复在X@3后也失效。

`assistant_only_stale`有明确的中间表述缺陷：index 1的回复称已经搜索且未找到记录，但实际新search发生在index 2，随后取得South并正确执行。预注册rubric要求旧search缺席、lineage仍有效、自然重新取得当前版本和正确获批动作，这些均成立；不能把5/5写成每句话都正确。没有修改rubric或隐藏该回复。

## 实现与身份

P4扩展的是通用诊断运行流程：按声明边界执行多次公开CRUD、允许未观测的公开seed形成UNKNOWN、以及按真实search生成位置过滤请求副本。`request_view`是显式fixture实验条件，SER算法不读取case/rubric，不把旧search从checkpoint删除。A3/A4在每个fixture使用相同业务schema与authority。

源码62文件mapping：`7de0f597d54ddce43f77448bdb4aba093a90f4dec1c3ff6975b23e0f6b57d20b`；[P4 lock](../data/locks/milai-ser-v20-p4.lock.json) SHA：`0e9b9ab3557224fb219f70ac79548ea54f02eee23bdce298edb5f5300a604933`。P3源码在`d8a6b1694fd25457782c04879d248cac29bbcd29`，旧lock与结果不改。[P4 freeze](../data/manifests/milai-ser-v20-p4-freeze.json)封存执行前配置、5个prepare、空namespace、评分与窄检查。

真实请求前发现初始P4锁沿用了P3温度示例的全局schema描述，已改成五个逐fixture合同并重新做零模型prepare；初始描述、修正hash及当时0调用证据保留在freeze。实际模型运行只使用最终锁。该修正没有改源码或模型输出。

31条受影响窄测试、ruff、mypy及两个依赖边界通过。包装检查发现sdist原规则未包含新`data/diagnostics`；该打包修正纳入P5首次源码变更并使用新锁，届时做一次累计必要build。P4运行采用仓库checkout，当前未宣称sdist已包含这些诊断。v20机制完成，包装交付项继续追踪。vLLM、Product API/Schema/权限/Canonical行为均未改。

## 成本

本组26次生成：输入21721、输出1023、合计22744tokens；17次embedding请求/315tokens；9次exact get。projection CPU22.093ms、wall27.720ms，get wall10.891ms是其中分项，不相加。Provider回执wall11.724秒，不能当端到端加速证据。18次降权marker共558片段tokens，已包含在输入费用。没有Judge、unknown usage或截断。

v20截至P4连续合计41次生成/36834tokens、27次embedding请求/589tokens、18次exact get。所有历史费用继续引用，未清零。持久语义State为0，但机械lineage、trace、checkpoint与业务journal仍占存储，分项见[accounting](../data/manifests/milai-ser-v20-p4-accounting.json)。删除例未执行业务，因此业务journal文件不存在，计0字节，不能当采集丢失。原始Provider日志和数据库保持ignored。

## Reflection（总计划§32）

| 问题 | 回答 |
| --- | --- |
| 支持什么假设 | 相同机械lineage/rebase机制可处理分类、布尔、删除和多版本；即使旧search不再可见，保存的生成快照仍可识别旧回复。 |
| 反驳什么假设 | 成功不依赖温度数字规则，也不必须靠当前请求保留原search才识别旧回复。 |
| first broken link | 最终动作链在这五例成立；中间虚称search显示自然语言报告可信度仍有缺口，刷新次数仍需优化。 |
| 更简单解释 | 当前版本交付与通用重新评估marker共同作用；没有对二者在每种新类型做充分因果消融。 |
| 更简单方法 | 继续保留A3同源arm；本组不能证明每例都需要derived demotion，也未证明全局最简。 |
| 复杂度是否合理 | 同一小型投影机制，无新LLM/语义State；fixture过滤只构造反例，不是产品实现。 |
| 是否可能过拟合 | 仍是开发自建短历史实例；词汇、模型与每类样本量有限，未见任务尚未消费。 |
| 应加什么反例 | 更低排名无关更新、取消权限、相同值元数据、current冲突、no-stale及mixed对象；高排名current不一定语义相关。 |
| 下一步 | Continue P5可调rank-bounded refresh，再完成P6全部类型与P7已暴露回归。 |
| 为什么 | 非温度正确性门槛成立，已观测无关Y重复get，优化有具体成本依据；formal条件仍未齐备。 |

## 中间表述缺陷的Failure Review

Observed failure：assistant-only的index 1虚称search返回空；Expected mechanism：缺少当前证据时如实报告不确定或自然search。Actual causal chain：harness移出旧结果、SER降权旧回答，模型在这一轮直接作答，下一轮才search并正确行动。First broken link是自然语言声称工具效果与实际调用不一致。

至少两个解释：H1模型把被移出的历史结果误当空结果；H2模型通用习惯是用“已搜索”表达当前无可用依据。单例不能区分。通用候选修复是准确区分“本请求没有证据”与“工具实际返回空”的报告合同；不注入case或正确值、不强制search。潜在混淆是实验过滤保留了原tool-call历史但移除了对应结果，并非自然完整工具对话。

当前不据此修改SER或追加定向prompt。最小下一证据是P6缺失/冲突与P7自然完整历史中的真实工具报告；若同类失实报告重复并影响任务，再单独冻结通用修复。Continue理由：预注册当前证据取得和最终动作已成立，先检验自然历史边界，避免为一个人工过滤场景过拟合。

## 复现

沿[P3入口](MILAI_SER_V20_P3_RESULTS_20260927.md)使用`tools/run_milai_ser.py prepare`再`run`，arm=`a4_selective_rebase`、显式`--lock data/locks/milai-ser-v20-p4.lock.json`，fixture及mechanism-freeze来自`data/diagnostics/selective_adaptation_v1/`和其`freezes/`。使用当前P4源码checkpoint、新run ID与空namespace；config中本地路径替换为各run独立ignored路径，DSN只通过环境变量注入。准备回执、源码、fixture、实际请求hash需吻合，不能用后续P5源码冒充P4。

原始证据：`artifacts/ser-v20/p4-a4-{case}-r1/`；[公开结果](../data/manifests/milai-ser-v20-p4-results.json)保留实际动作、普通回复、逐请求交付和rebase事件、全部费用及原始artifact SHA。重新执行属于新诊断，不能覆盖这轮结果或重置账本。
