# v20开发记录

依据1422行[总计划](MILAI_LONG_HORIZON_MASTER_DEVELOPMENT_PLAN_20260926.md)，SHA `d7a5331bf20ecd649a1bf75187ea0d65224ad559572a30dde0bb5527a66217d2`。原文不改；[阶段Goal](MILAI_SER_V20_GOAL.md)属于完整[长程Goal](MILAI_LONG_HORIZON_EXECUTION_GOAL.md)，不是新的缩小终点。

## P0与开发前判断

P0完成：参考提交024fa69的59个runtime及validation按Git对象核对；19份旧artifact与9例合计54个关键原始文件已核对并引用，未复制旧源码树、覆盖失败或重跑模型。vLLM容器/image/command/env/HostConfig与原环境一致。新阶段账本累计从0开始，但history完整引用旧repair的45次/41457tokens/808embeddingtokens和更早历史，不清零旧费用。见[reference](../data/manifests/milai-ser-v20-reference.json)。

开发前已声明[评价协议](../data/manifests/milai-ser-v20-evaluation-protocol.json)。先原三例A4，之后非温度泛化；原A3为封存参考，新CLI仍提供同源A3用于有明确问题的matched对照，不自动为凑齐arms重跑。

Observed failure：A3 changed在当前8°C已实际交付、旧4°C记忆正文已隔离后仍执行4。Expected mechanism：当前证据应能支持更新动作。Actual chain：原search@1→助手4→真实update@2→request-copy当前8与旧助手4同在→助手再次4→最终动作4。

First broken link候选是未失效的派生助手上下文。替代假设至少包括：H1旧助手文本形成主要锚点；H2当前材料位置/格式不足；H3普通业务调用复制最近结论而没有重新对齐证据。它们尚未被独立因果证明。

最小下一实验仅增加基于真实生成snapshot的ordinary assistant demotion，固定A3 schema、authority、刷新和vLLM。保留工具调用JSON及原checkpoint，不搜具体值；若失败，再根据实际wire选择一个区分H1/H2/H3的对照，不同时堆叠capsule或grounding。

## 泛化输入先于结果

已定义[selective_adaptation_v1](../data/diagnostics/selective_adaptation_v1/rubrics.json)共12个非温度开发fixture，另有原温度三例。覆盖金额1774→6595、分类、两个布尔方向、同值新metadata、低排名无关变化、删除、多revision、current冲突、assistant-only stale、no-stale及mixed current/stale/deleted/unknown。尚未运行。

输入fixture只含任务、公共工具schema、受控外部事件；expected值和类型族在独立rubric，方法runtime不读。assistant-only使用诊断harness的请求副本view，隐藏初次search结果但保留lineage和历史；新search结果仍可见。mixed的UNKNOWN来自未被observer观测的public工具seed，不伪造revision。

这些都是可见开发控制，不是benchmark或未见证据。一次结果不能建立泛化；后续仍需P5–P12方法收敛、exposed regression、未见matched、鲁棒性、独立生命周期研究和质量—成本分析。

## P1–P3完成

Sol在现有projection链路增加一张assistant_lineage机械表、新lineage.py及新v20 CLI/config。实际Provider回执核对完整request与SHA后提取真实exact snapshot；普通AIMessage生成后绑定原response ID/hash。A3刷新X@2的新回复绑定X@2，旧X@1不作为其support。下一request仅降权自身snapshot确已stale的普通文本，工具调用、原历史与CURRENT文本保留。

29项受影响检查与静态/边界检查通过后Root冻结62文件source并zero-model prepare三组空namespace；随后串行跑原三例。结果3/3通过，changed真实动作8、retained取得X@2、irrelevant8且无追加search。9个marker实际交付并对账，9条lineage可恢复。费用15次/14090tokens/274embeddingtokens，9exact get；projection CPU/wall与存储另行记录。

详见[P3结果与十项Reflection](MILAI_SER_V20_P3_RESULTS_20260927.md)。Root将先由Luna保存P3源码checkpoint，再允许P4通用harness扩展；P3 lock/结果不覆盖。没有因为温度控制通过而结束长程Goal或直接消费未见数据。
