# v26：原生外部记忆形成对照结果

原四例、每臂六消息的小规模对照完成。Mem0 OSS原生自动摄取严格通过4/4，公开LangMem B1通过2/4；差异来自两个需要长期保留的案例。两臂临时控制均不误存。Mem0总生成tokens为B1的10.1倍，因此结果支持形成能力与成本之间的取舍，不支持低成本替代、SER因果收益或Product迁移。

[总结果](../data/manifests/milai-external-memory-v26-results.json)、[B1逐例证据](../data/manifests/milai-external-memory-v26-b1-results.json)、[Mem0逐例证据](../data/manifests/milai-external-memory-v26-mem0-results.json)、[复现说明](MILAI_EXTERNAL_MEMORY_V26_REPRODUCTION_20260927.md)。这是RESEARCH_PROTOTYPE、已暴露开发输入；不是未见评估或托管Mem0公开benchmark复现。

## 结果与完整成本

| 指标 | B1 | Mem0 native |
|---|---:|---:|
| 正确形成 | 0/2 | 2/2 |
| 后来实际检索并正确使用 | 0/2 | 2/2 |
| 临时内容不存储 | 2/2 | 2/2 |
| 严格case | 2/4 | 4/4 |
| Host公开消息完成 | 6/6 | 6/6 |
| Host生成次数 | 10 | 10 |
| 额外原生抽取次数 | 0 | 6 |
| 总生成输入tokens | 4993 | 53343 |
| 总生成输出tokens | 331 | 509 |
| 总生成tokens | 5324 | 53852 |
| embedding请求/tokens | 2 / 29 | 14 / 640 |
| Provider累计墙钟秒 | 3.866 | 11.223 |
| 含初始化的进程墙钟秒 | 9.459 | 19.618 |

本阶段新增26次生成、59176生成tokens、16次embedding请求/669tokens；连续账本为863次生成、1042729生成tokens、9617embeddingtokens，累计exact-version reads仍107。没有新Judge、截断、未知用量、服务错误或容量失败。每臂六次session末状态读取属于观察开销，不混入方法exact refresh。原生add/search内部局部读写和entity检索不冒充SER exact read。

Mem0普通Host生成仅3750tokens，额外原生抽取为50102tokens（输入49897、输出205）。六次抽取使用完全相同的官方system文本，本地同tokenizer计8136tokens/份；实际每次输入8235–8423tokens。四次正确返回空记忆的抽取仍消耗33330生成tokens：两次后来查询、两个临时控制。自动摄取另用10次embedding/576tokens，原生search用4次/64tokens；批量形状和每次费用均在逐臂结果中。不能把“单次批量提案”解释成整个对话只需一次调用，也不能删掉空结果费用。

相对B1，Mem0增加48528生成tokens和611embeddingtokens，两个额外严格通过案例；这一样本内，两臂均不在质量与总生成成本两轴上支配对方。墙钟含缓存/服务调度和初始化差异，只有一次轨迹，不能据此作性能承诺。

## 实际链条

1. Maple Courtyard：两臂均真实发送包含14株rowan和site-lead批准门槛的确认，收到CNF-7318。B1未调用manage，首次session没有记忆；后来search实际返回空数组，模型如实回答未找到。Mem0在第一轮结束后原生ADD一条包含项目、数量、品种和批准门槛的记忆；后来search返回相同原生ID，其完整JSON确实出现在下一次HTTP工具消息里，回答正确，未增加业务调用。
2. Eastbank exhibit cases：两臂均调用book_collection，hold_until_approval=true，收到COL-4826、H-6、awaiting_depot_approval。B1没有持久化，后来空检索。Mem0原生ADD保留全部字段，后来真实检索送达并准确回答COL-4826、H-6、Pending；没有编造批准或再次预订。
3. 临时计算：两臂回答378。Mem0仍执行预注册的整轮自动摄取，原生抽取返回空，未写记忆。
4. 一次格式：两臂准确回答READY；Mem0同样执行摄取并返回空，未把一次性格式要求存成长期偏好。

六次Mem0摄取journal均complete。只读复核官方SQLite确认12条历史消息（user/final assistant各六）、2条ADD；持久快照与后来检索ID/scope一致。后来查询摄取没有重复ADD。运行期BM25启用；此前真实SDK假Provider窄测还验证了稀疏向量、entity关联、关闭与重新打开后持久化。本轮实际比较是每臂一个进程中的六个session，不能将离线重启测试混称为本轮跨进程效果。

所有六个原生抽取请求均核对其New Messages来自实际user和最终assistant。原始tool role没有被伪装或补写；本轮两条最终assistant恰好完整复述关键回执，因此该边界没有造成事实遗漏。Mem0第二条记忆的attributed_to为assistant，保持官方语义；不将其改写为独立业务来源证明。若最终答复漏述业务字段，当前标准整轮摄取没有保证能保存它们。

## 实现、合同和冻结

固定Mem0 OSS `f8082a7345dadd9e042ebbc40b57b1498c8f6d63`；SDK运行文件与固定源码相符。适配器只接入现有Provider传输、串行调用、预算和用户scope；实际使用官方infer=True ADD-only抽取、批量embedding、本地Qdrant及SQLite history。默认search top_k20/threshold0.1保留。Host的工具、system及原生search输出合同不同，均在[协议](../data/manifests/milai-external-memory-v26-protocol.json)冻结，不声称首请求相同或单变量消融。

85文件source mapping为`37e57b17808d9378111032de11ba66960280620586b1a2a9586e4e81aaffc4cb`。输入、rubric、模型合同、source lock和[执行冻结](../data/manifests/milai-external-memory-v26-execution-freeze.json)均在首请求前固定；Git开发提交`2968f75ab69aedc0fd5349ba196aabe63da7f46f`的发布时间晚于B1第一请求，不能混淆这两个时间点。冻结后源码未变，旧锁/失败/费用未重写。

两臂使用同一Python3.12.11隔离环境；之前研究是Python3.11，原环境未改。本次现有依赖版本改变0、新增43项。spaCy模型和BM25资产提前准备，运行期离线、telemetry关闭。FastEmbed0.8.1要求的mock.file与tamil.txt不在固定Hub快照，隔离缓存补入两个公开记录hash的空兼容文件；前者无权重占位，后者采用原加载器无Tamil词表的语义，本轮全英文。运行前确认BM25可用，避免原SDK静默降级被误称联合检索。见[环境回执](../data/manifests/milai-external-memory-v26-environment-receipt.json)。

官方SDK假Provider4项、B1已有2项、受影响静态/边界检查及一次打包通过。没有全套测试、扩大benchmark或修改vLLM。原生抽取实际传送top_p=1与json_object；普通Host默认wire未加top_p。共用HTTP串行化，所有原生额外调用进入原连续账本。

## Failure Review

**Observed / Expected。** B1业务成功但形成0/2、后来使用0/2；期望两个未来相关事实均可跨session保留。Mem0达成两例形成目标，但总生成成本10.1倍，尚不满足低开销方向的期待。

**First broken link。** B1首次session结束时未作持久写，后续搜索为空；断点在形成决策，不能归咎检索排名或旧证据污染。Mem0没有本轮功能失败；成本集中在六次默认8136-token system抽取，不在HTTP重复发送或适配器额外循环。

**竞争解释。** H1：同一模型在普通ReAct任务中缺少可靠的主动形成触发；自动整轮摄取直接补足。H2：Mem0专用抽取prompt、管理策略和不同Host合同共同改变了行为。两臂业务首轮实际调用/答案相同、后来原生ID真实送达支持形成链条，但当前系统对照不能分离H1/H2，更不能证明SER作用。成本另有两种解释：固定长prompt主导，或多次embedding/实体处理主导；实际50102生成tokens与640embeddingtokens定位前者为主要token开销，时延仍包含本地初始化。

**通用修复与混杂。** 已完成的通用修复是接入官方自动摄取及正确传输/计费边界，不加case路由、gold判断或丢弃空结果。本轮不缩写官方prompt、不跳过临时轮次、不改参数寻找优胜。模型族、四个已暴露案例、不同工具/system、只摄取final assistant、ADD-only语义及共同新Python环境限制外推；既有F/R cue负结果保留，自动摄取不能算作这些cue已修好。

**最小后续 / Continue–Pivot–Kill。** 本外部对照切片COMPLETE；停止本样本的措辞和成本调参。仅当另立低开销形成开发目标时，才比较一个通用固定成本变化并保留临时/遗漏反例，本切片不追加扩测。继续交付/第二模型资源接线准备；第二模型真实检验仍NOT_RUN，Product继续NO-GO，master不标完成。

## Reflection

1. 本轮先定位并修复确定性缓存/传输边界，再发实际请求，避免把降级运行当原生能力。
2. 自动摄取覆盖了普通Host漏写，但需要独立形成策略；不能把两者混为相同CRUD路径。
3. 成功必须看到持久化、later实际HTTP送达与正确答案，只有ADD返回不够。
4. 两个临时反例均实际经过摄取，未靠跳过case获得好分数。
5. 空抽取仍昂贵，33330tokens必须进入质量—成本判断。
6. 批量embedding减少往返，无法消除长prompt的固定开销。
7. final assistant的内容边界在本轮未失败，不等于所有业务回执都能保存。
8. Mem0 ADD-only不保证同ID修订；本结果不能代替v25更新/删除/恢复证据。
9. 四个暴露案例与单模型只构成开发对照，无法支撑普遍可靠性和产品推广。
10. 本轮已达到预定判定点；保留收益和代价，完成交付，不追加轨迹选择最佳结果。
