# E2 R1：回合开始 State 的条件诊断

状态：`COMPLETE_CONDITIONAL_TIMING_SIGNAL_WITH_RECEIPT_COUNTEREXAMPLE`。
按[预冻结协议](../data/manifests/local-state-attention-review-e2-r1-protocol.json)，
源码`a471932695dc077dd88077b5aa24949beab978dd`上的既有read-probe入口完成24次首响应。
[逐项结果与账本](../data/manifests/local-state-attention-review-e2-r1-results.json)
保留全部输出判定；无补跑、替换、批内源代码或参数修改。

这是两个已暴露历史轨迹中的六个请求边界，每条件两次重复，不是六个独立新情景。
所有业务/Store执行为0；“正确proposal”不能表述为在线任务通过或维护已经持久化。

| 原请求边界 | 即时post-event State | 回合开始State |
|---|---:|---:|
| 首次增量2→3 | 2/2 | 2/2 |
| 新ID相同文本的第二次增量3→4 | 0/2 | 2/2 |
| 同回合内部memory-created回执 | 2/2 | 2/2 |
| 无变化只读 | 2/2 | 2/2 |
| 已发生的错误业务回执 | 2/2 | 1/2 |
| 已预留、标签失败的部分回执 | 2/2 | 2/2 |
| **正确首响应proposal** | **10/12** | **11/12** |

## 干预与实际链路

两臂使用逐字相同的原始非system消息、完整当前ReAct前缀、来源展开、工具schema及模型参数。
post-event是原实际视图；turn-start替换为该公开用户回合之前真实交付过的同ID State正文，
附一行事实标签“Snapshot captured before the current public user turn.”。当前user/tool均保留。
这是State时点/正文与标签的组合干预，不是只改标签的消融；没有使用人工纠正的oracle State。

同回合工具前缀使用**整个用户回合开始时**的快照，而非上一次hook前的State。
来源材料固定为原请求实际收到的内容，不随两个版本的refs重新扩展；两臂共享合法来源。
24条实际HTTP均与保存的输出请求绑定，顺序、非system消息、参数/schema、发布源码hash均核对。
所有请求均完成，无HTTP/容量/解析错误或中间lookup首响应。不同条件均保留普通memory工具。

第二次增量的首断点重现：原实际State已经4，post-event两次均提议把普通memory改成5；
turn-start使用真实旧State3，两次均提议正确4。H1“已应用增量被当作前态再次消费”获得
此固定前缀的支持；H2“旧助手/普通memory独立传播错误”未被排除，不能从这条局部信号
推导所有增量场景或在线长期收益。

新反例保留：实际业务回执明确quantity5、destination=`S-2`。turn-start第一次保留真实5和
原ID，但把destination说成计划中的`storage S-2`；第二次正确报告`S-2`。post-event两次
均按原回执报告。首断点在Host回答，而非输入缺失。H1是旧计划与新回执字段混合；H2是
回答规范化/补全地点名。小样本不能区分二者，不追加措辞补丁或自动参数修正。
原先错误预约本身仍是旧轨迹失败，这次正确报告不撤销旧副作用。

## 评分边界

主判定依[预冻结rubric](../data/diagnostics/local_state_attention/review-e2-r1-rubric.json)：
正确事实/条件、原ID、允许的proposal以及不超出回执的陈述。
规划地点的普通转述如“stored in S-2”可指向同一明确位置；没有执行改写后的业务参数。
但要求报告实际回执的任务，不能把原返回`S-2`换成计划字段`storage S-2`，因此该项失败。
“successfully labeled”视为label_status=created的自然语言表达；对五件物品的复数描述
不重新判定之前错误item_key为正确。所有真实ID均保持，没有再次预约/标签proposal。

turn-start首增量一次直接回答“已更新计划”，一次提议memory create。这里仅评首响应的
正确理解，不证明任何新持久写入；实际写入与真实动作要由在线原型验证。
辅助数量项post-event10/12、turn-start12/12，不能替代包含回执字段失败的主分数。

## 成本、决定与下一步

| 条件 | 调用 | prompt tokens | completion tokens | 总generation tokens | 实际HTTP秒 |
|---|---:|---:|---:|---:|---:|
| post-event | 12 | 17,612 | 783 | 18,395 | 7.803 |
| turn-start | 12 | 16,868 | 787 | 17,655 | 7.321 |

新增24次生成、36050 generation tokens、0 embedding；unknown=0。连续账本为
**2701次生成 / 3332841 generation tokens / 18445 embedding tokens**，旧sealed链不变。
这只计新proposal费用；原轨迹的全部成本保留在旧账本中。两个快照正文长度不同，且尚未计
在线snapshot写入、恢复、close维护，不能把740-token差称为完整方法节省或压缩收益。

Continue：由同一Sol实现最小显式epoch/close原型，正常结束、capacity、跨进程同回合恢复及
未归并尾部各有必要窄检查，再冻结小sandbox比较。业务完成与维护结果分列，真实回执
不得被旧快照掩盖；异常finally不偷偷追加模型调用。局部entry保持实验另行独立，
不同时引入selector优化、Host权限变化或业务ID修正。完整D1–D5和论文证据包仍未完成。
