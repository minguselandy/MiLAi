# U2 SimpleMem text 试跑结果

**PILOT_COMPLETE_WITH_CAPACITY_INTERRUPTION；当前 PAUSED_BY_USER。** 用户已要求暂停实验并生成报告。以下记录已发生的结果；任何早先 Continue 或后续 development 提议均不再构成执行授权。总体状态见[暂停报告](MILAI_UNIFIED_V8_V9_EXPERIMENT_REPORT_20260929.md)。

## 固定身份与方法

源码／执行提交 `9200de0146da03ac09c78dab820feb1c9d09a708`，官方 SimpleMem `db80b6a7c591e0ea730a058e9f5fc4eb06572299`。
按[原协议](MILAI_UNIFIED_U2_SIMPLEMEM_PROTOCOL_20260929.md)使用真实 core MemoryBuilder、LanceDB/Tantivy 和 HybridRetriever；共同 MemSyco reader／MERIT Agent 代替原生最终 AnswerGenerator，不能称完整 native ask() 复现。

沿用 Qwen@7862、bge-m3@7861，真实 HTTP 串行1。Host 温度0，原生内部温度保留0.1／0.2／0.3，max4096、thinking=false。
窗口40／overlap2，检索25／5／5，planning及reflection开启、最多2轮、原生并行关闭。各公开消息共享12次生成，摄入与独立查询各自也限12。无新服务或模型权重。

两份正式 prepare 在已发布 HEAD 完成，执行冻结390份文件。freeze SHA256 `493a1f835e7e806eafa716b787e0222d31e1c984d9953dbe52d4ad2554672084`，顺序 SHA256 `8900652ad37339b78f91f9c40bd10a91847d25aeb592103002235cbee96d9810`。
输入为既有已曝光 `mso_hard_000072` 和完整 `arc5-000`，共3次 invocation，全部尝试一次；不安排 MemSyco Judge。参数、样本、源码和输入在运行中未变。

## 结果与实际链路

| 执行单元 | 结果 | generation calls | generation tokens | embedding tokens |
| --- | --- | ---: | ---: | ---: |
| MemSyco 形成 | COMPLETED，33条原生记录 | 1 | 5,122 | 1,055 |
| MemSyco 查询 | COMPLETED，29条取回／交付，0省略 | 5 | 5,042 | 39 |
| MERIT 完整arc尝试 | FAILED：第4个episode容量中断 | 45 | 46,465 | 916 |
| 合计 | 2完成、1中断 | 51 | 56,629 | 2,010 |

MemSyco 的10条输入消息与原生摄入记录完全一致，形成不见 question/gold。查询重新打开真实持久bank并核验33条快照；取回29条材料实际进入共同reader HTTP，查询后存储不变，最终回答已保留。**没有 Judge 分数，不能将回答非空写成语义通过。**

MERIT 计划5个episodes／2个dependent／6个公开消息：前3个episodes成功，第4个中断未评分，第5个未运行，故3成功＋2未知/5、dependent1成功＋1未知/2，完整arc未完成。
4个已关闭turn维护全部完成、最终11条原生记录。5个已启动消息自动检索各一次，取回数量依次0／6／8／9／11；实际记录逐字匹配当时已有bank。
后续ReAct复用同一query/material，不重复自动检索。已执行9次业务工具：send_message1、refund1、update_address2、get_order1、get_policy4；实际world、journal、ID和checkpoint保留。

Host 此次没有自主选择显式 SimpleMem search 或 MCP read_history；自动SDK检索与Host→MiLAi MCP能力不能混计。既有真实MCP基础能力由U0等阶段单独证明。

## 中断分析

- **Observed：** 第4个episode的当前公开消息没有最终回答，触发 `PUBLIC_MESSAGE_GENERATION_CAPACITY_EXCEEDED`；最后一个episode未启动。
- **Expected：** 检索、Host续接与维护共用12次实际生成，不能由内部服务开第二预算或默默延长；无法完成就保留真实部分状态。
- **实际因果链：** 当前Human→一次原生检索的7次planning／structured-query／reflection生成→5次Host生成，依次查询订单、泛化政策key及3个实际政策key→下一次Host生成在HTTP之前被拒绝→无最终回答、无本turn结束维护。
- **首个硬中断：** 共同公开消息容量耗尽。更早的泛化 `refund_policy` key 未命中，工具返回实际可用key列表，随后查询按真实key进行；没有静默修正工具参数。
- **解释一：** 原生检索与自然Agent工具查询共同用完额度。由7＋5个真实回执、总45个MERIT生成和容量计数一致支持。
- **解释二：** 适配器循环检索或虚扣额度。5个公开消息仅5次native检索，复用材料一致，45次计数等于45次HTTP，已检查路径不支持该解释。
- **其他混杂：** 当前订单13100 cents高于免批准阈值10000，可能影响后续政策选择；没有实际最终选择，不能断言加额度就成功。原生内部温度、单模型及已曝光单arc也限制结论。

没有发生原生重试耗尽或fallback；本次所有已完成原生维护/检索都记录为COMPLETED。容量中断不改写成Store错误，也不代表完整业务成功。
通用候选如缩减planning／reflection或扩大预算会改变方法合同，本次均未实施。没有适配器重复执行证据，不因pilot未满分重新调原生方法。

暂停前建议的最小下一步是用不变方法补相同已曝光60题／18arcs；**现已暂停，138单元未prepare／冻结／执行，0新增Judge。** 不续接原中断轨迹、补答案或重放业务。

## 成本、证据与复现限制

51次生成本地prompt计数与实际usage全部一致，ledger/trace核对无差异。连续账本由5941／10864712／414792增至 **5992／10921341／416802**，顺序为generation calls／generation tokens／embedding tokens。
账本SHA256 `2ef3e45b0150cb6c5cc2c47dc0f0493497157e84dae0a9e991d71b1181113e3c`；不包含开发代理消耗，物理I/O／GPU小时／货币费用未测。

[机器结果](../data/manifests/unified-v8-v9-u2-simplemem-pilot-results-20260929.json)记录分母、逐episode原生score、成本、12个末端真实调用、失败分析及证据哈希。
ignored运行目录为 `artifacts/unified-v8-v9/u2-simplemem-pilot-r1`，保留execution-freeze、run-order、三个invocations、trace、bank、business-journal、原始失败和预算前后快照。
暂停前机器结果原件SHA为 `d999782f9cf59d375d6f0a7dbae86a07f24592903772cdb4c4f4fc96ef5ffa51`；公开文件额外标明用户暂停覆盖，旧原件不改。

复现使用上述实际提交和原冻结依赖/输入，新隔离运行身份，不用后来的报告提交冒充实验源码。未公开原始私密制品不可从文档凭空重建；必要资产按固定清单取得。任何复现调用仍须等明确恢复授权。
本次报告不重复已通过的14项工程检查或构建。研究 **NOT_ACHIEVED**，Product **NO_GO**。
