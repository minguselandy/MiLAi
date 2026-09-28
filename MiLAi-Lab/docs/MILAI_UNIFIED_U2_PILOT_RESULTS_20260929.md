# Unified V8/V9 U2 小规模接线结果与开发输入冻结

状态：**PILOT_COMPLETED；INDEPENDENT_MAIN_NOT_RUN；Continue**。五种方法均完成一题已曝光 MemSyco 的归档构建和查询，以及同一个已曝光 MERIT 完整 arc。
没有工程中断、重试或参数修改。此结果支持进入预定独立比较，不证明方法收益或稳定性。总体 Goal 仍 ACTIVE，研究目标 NOT_ACHIEVED，Product NO_GO。

## 身份与验收

源码及 pilot 执行提交为 `795725a297fb1ef5f9d7bb712b3500d5b72546c0`，远端一致；
[Fast CI 36471409915](https://github.com/minguselandy/MiLAi/actions/runs/36471409915) success，Full36471409881 skipped。
此前26个去重窄检查和10份零模型 prepare 已通过，本次没有为发布重跑。
[原协议](MILAI_UNIFIED_U2_PROTOCOL_20260929.md)保留事前字节，其 NOT_RUN 是冻结前状态；本报告提供后续结果。
[机器证据](../data/manifests/unified-v8-v9-u2-pilot-results-20260929.json)包含逐次费用、阶段、身份及结果/trace/调用回执哈希。

执行 freeze SHA256 为 `b8922944014af67fbb0eca6b20cc91d22431167744929e4db68f63c530b23103`，
绑定402份不可变输入/源码/环境资产；run-order SHA256 为 `3943f5572fed3e30d1318a5041aa3f55851bb39742fbe896d8d25e5e78fc0020`。
Root 按顺序串行完成15次调用单元：5次归档构建、5次 reader 查询、5次完整 arc。
输入是 U1 清单首题 `mso_hard_000072` 和首 arc `arc5-000`；各方法 namespace、Store、checkpoint、Mem0 数据库及业务 world 隔离。

真实请求、工具/持久化回执、后续交付、回答/原生 world checker 与连续账本已核对。
全部86次 generation 的本地完整请求 prompt 计数与服务 usage 一致，unknown usage 为0。
MERIT 每臂6个公开消息，Host、摘要和 Mem0 内部调用共享每消息12次上限；观测均未超限。
StrongRawRAG、摘要、FullHistory 和 Mem0 的实际查询均只来自已出现的当前 Human 消息。
五臂均未通过 `read_history` 额外回看原文。ordinary 仍有完整合法历史，不能据答对反推持久记忆维护成功。
服务、模型、温度、thinking、上下文和输出预算均未改变。

## MemSyco：工程通过，语义质量未评分

依事前 pilot 合同未调用 Judge；下表不含原生准确率。全部 reader 正常结束并返回非空回答。

| 方法 | generation calls | generation tokens | embedding tokens | 实际形成与查询证据 |
| --- | ---: | ---: | ---: | --- |
| RawDialogue | 1 | 1,421 | 0 | 完整原档案供共同 reader |
| StrongRawRAG | 1 | 3,241 | 1,535 | 10个原文块，真实 BM25+dense；交付10块、省略0 |
| Rolling summary | 2 | 3,266 | 0 | 1次真实摘要形成，无 degraded，另保留最近2回合 |
| Ordinary/MiLAi | 3 | 6,680 | 351 | 实际4条持久记录；查询前后 snapshot 相等 |
| Mem0 native | 2 | 10,990 | 1,826 | 实际 ADD 得5条记录；查询前后 snapshot 相等 |

RawDialogue/RAG/summary 核对的是不可变 formation 制品，不将不存在的语义记录 snapshot 写成通过。
Mem0 保持该 pin 的 ADD-only 合同；本次不证明同 ID 修订/删除。归档形成不含题目、答案或 rubric。
总计9次 generation、25,598 generation tokens、3,712 embedding tokens。

## MERIT：同一完整 arc，各方法均为5/5

| 方法 | 原生 episodes | dependent | 整 arc | generation calls | generation tokens | embedding tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| FullHistory | 5/5 | 2/2 | 1/1 | 13 | 19,412 | 0 |
| StrongRawRAG | 5/5 | 2/2 | 1/1 | 13 | 33,065 | 2,719 |
| Rolling summary | 5/5 | 2/2 | 1/1 | 16 | 19,553 | 0 |
| Ordinary/MiLAi | 5/5 | 2/2 | 1/1 | 15 | 39,566 | 7 |
| Mem0 native | 5/5 | 2/2 | 1/1 | 20 | 97,949 | 6,569 |

这是五种方法重复同一 arc，不是25个独立任务。原始 world、业务 tools 和 checker 未改。
摘要真实更新3次，cursor 从−1依次提交0、1、2；任务 Host 为17,099 tokens，摘要另收2,454 tokens。
加入更新后19,553 tokens 略高于 FullHistory 的19,412，不能用任务阶段减量声称生命周期压缩收益。
ordinary 最终持久记录为0，一次实际 memory search 收7 embedding tokens；原文可用及轨迹差异是混杂因素。
Mem0 六次真实回合维护均完成，最终10条记录；任务14次 generation/39,205 tokens，加维护6次/58,744 tokens。
同一公开回合总容量与真实 SDK embedding 均计入，未用单独预算掩盖维护成本。

## 费用、反思与决定

本 pilot 新增 **86 generation / 235,143 generation tokens / 54 embedding requests / 13,007 embedding tokens**，Judge0、重试0。
连续账本从3627/4,825,845/24,962增至 **3713/5,060,988/37,969**（generation calls / generation tokens / embedding tokens）。
包含此前失败的本 Goal 累计新增412次 generation、855,785 generation tokens、14,399 embedding tokens；历史账本字段均保留。
开发代理 token 不混入实验成本。GPU小时、净 Store CPU和物理 I/O未精确计量，不补估为0。

Observed：全链接通、所有 MERIT 原生任务通过，ordinary 零持久记录，强方法各有额外费用。
Expected：工程 pilot 应能完整执行并逐层核账；不要求复杂方法获胜。未发现新的工程首断点。
竞争解释一：该短、已曝光 arc 的完整合法历史足够，额外记忆维护无必要收益。
竞争解释二：单一 arc 缺乏范围/长度变化，工具目录和自然轨迹差异影响成本，不能外推其他任务。
因果链只支持“实际材料/操作→world 达成”及费用分解，尚不能隔离记忆机制贡献。
通用修复候选暂不实施；不按 pilot 答案改提示、参数或选样。最小下一实验是已预定独立 development 切片。
决定 **Continue unchanged method**；不把 Mem0 的记录数量当语义正确性，也不把进程退出替代评分。

## 已生成的独立输入与下一步

方法冻结并完成 pilot 后，Root 使用原官方生成器按既定 seeds11—28生成
[18条完整开发 arcs](../data/manifests/unified-v8-v9-merit-development-inputs-20260929.json)：三域×easy/hard×3，90 episodes、36 dependent、111公开消息。
每条保留完整原任务/world；官方 leak check 通过，历史及批内 arc/world 哈希无碰撞，没有按答案筛选或替换。
此操作无模型/embedding调用；原始数据留在 ignored artifacts，仅发布身份/参数/哈希。新 seed 仍属同一生成器任务族。

[开发执行合同](../data/diagnostics/unified-v8-v9-u2/development-contract.json)沿用已发布方法/参数及评分合同。
每臂 MemSyco60题、60份不同历史、54统计来源组；先该臂全部归档构建，再全部查询。
MERIT每臂18完整 arcs；五方法合计390个任务机会、300次形成，共690个调用单元。
所有 Host 工作完成并冻结回答/状态后，才进行300个单次 Judge 评分机会，缺失保留原分母/unknown。
提交输入和本报告后，在发布 HEAD 正式 prepare，冻结源码、输入、模型/tool/scorer、顺序、隔离和账本，再执行。
U2主表、第二外部系统及证据触发的U3—U5和U6收口仍未完成，不因 pilot 成功关闭总 Goal。
