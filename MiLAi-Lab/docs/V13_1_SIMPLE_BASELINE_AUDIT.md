# v13.1 B0–B6 现有代码检查与接入缺口

状态：READ_ONLY_STATIC_AUDIT；不能替代固定微型验收，完整P3未完成。

已有benchmark_memories.py提供raw_chunks/raw_index/raw_retrieve、rolling_archive/
summary_material，langmem_benchmark.py已有MERIT闭合回合FullHistory/StrongRawRAG/
RollingSummary适配；memsyco_native.py也有对应归档形成和共同reader入口。
MERIT no_memory保留原生环境与工具。需要沿实际新runner检查，而不能由函数存在推断新表采用。

| 原规划方法 | 可复用代码 | 尚缺的直接证据或能力 |
|---|---|---|
| B0 NoMemory | merit_native的原生NoMemory路线 | 新固定微型；合法当前业务工具继续可用，不能人为去掉 |
| B1 FullHistory | 原始角色/闭合回合材料，HostCapacity拒绝 | 新持久/重启/owner与不截断检查；旧tail60000不能当完整历史 |
| B2 StrongRawRAG | 全原行JSON分块，BM25+dense稳定RRF | 独立微型和同数量开发配置；现参数大多写死，不能只改元数据称调参 |
| B3 RollingSummary | 实际同模型summary请求、已覆盖cursor、完整history fallback | 微型必须至少3闭合回合，触发实际summary；≤2回合不生成不能当维护成本检查 |
| B4 Ordinary-Matched | 既有ordinary_milai与LangMem归档 | 当前新SourceEvent形成边界/来源与共同预算对齐，不拼接旧pause结果 |
| B5 Prompt-only | 可复用B4并用共同来源/限制提示 | 新显式命名/配置/微型；无字段绑定，与P2结构合同分开 |
| B6 Receipt-RAG | 原始回执与公开World/journal可复用 | 仍需公开实现检索+简单确定性历史/状态投影与共同保护，禁止读隐藏world/gold |

现StrongRawRAG在原文2048字符窗口/1792步长上建立真实embedding，Unicode BM25使用
k1=1.2/b=0.75，固定RRF60、top10、材料16000字符，stable tie。metadata与代码此处一致。
这些参数不是已经开发挑选的最优参数；共同HostCapacity的总上下文限制不等于已验证
相同材料token预算。公平配置与实际预算仍需事前冻结并执行，不能继承历史最佳成绩。

RollingSummary现将最后2闭合回合作为recent，更旧回合进入actual model摘要；降级保留
完整历史并继续真实容量检查。B3微型应预先声明公共中性闭合历史，让同一source供各方法，
明确脚本assistant与实际模型执行不同；不能给B3事后特供更容易摘要或隐藏future query。
archive helper假定每行event_id，当前合成assistant部分只有id。必须以公开身份契约处理，
不能伪造已验证SourceEvent或把仅id行悄悄丢掉。该点尚未修改或验收。

P3外部微型的trace_equal_v1只在新driver明确选择；既有langmem_benchmark原生SimpleMem
构造仍为legacy默认。未来公开T1/T3不能凭微型载体测试认为所有runner已切换。需按各表
实际writer wire/同一闭合边界/SDKpin冻结，原默认和旧表结果继续保留。

下一接入应复用以上实现，先做小而冻结的API/持久/容量/Scope/实际费用检查，再依公平
开发配置合同和pilot数据选择正式方法。当前不消费正式问题或gold，不接近弱RAG替代强邻。
