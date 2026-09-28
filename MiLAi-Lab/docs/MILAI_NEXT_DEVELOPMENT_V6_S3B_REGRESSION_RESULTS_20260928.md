---
status: PASS_EXPOSED_COMPACT_REGRESSION
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
method_commit: 85f45b367ee1c90d1c378e4a8a5c699c03889ee9
source_pr: 70
research_goal: NOT_ACHIEVED
product: NO_GO
---

# v6 S3b：完整 compact 回归结果

唯一 compact_v6 候选通过 **12/12 scripts、156/156 task obligations**，共35条公开消息。
分层为 current55/55、later34/34、persistent67/67；显式 current+later89/89。
全部持久化义务包含形成、修订、删除和不写入，不能把67/67称为单独的formation成功率。
三项未请求的字段仍为diagnostic-only，0/3；没有改分母或把缺项变成隐藏任务要求。

本轮是全部原v5暴露脚本的回归，不是新的独立任务或unseen证据。
S1/full真实smoke和S2固定输入计量属于[前一阶段](MILAI_NEXT_DEVELOPMENT_V6_S2_PROFILE_S3A_RESULTS_20260928.md)。
[S3b精简结果](../data/manifests/next-development-v6-s3b-regression-results-20260928.json)保留逐案例回答、成本、trace身份和核查回执。

## 冻结与实际链路

[原协议](MILAI_NEXT_DEVELOPMENT_V6_S3B_REGRESSION_PROTOCOL_20260928.md)与顺序、原inputs/义务/guide字节在运行前固定。
Luna先发布源码85f45b3，Root核对远端19文件后prepare12独立运行空间；prepare无模型或共享DB调用。
执行freeze SHA `aba430e9c39213f856d956036c9451c5c651fa2d75b862fdc275d53afb4a99d3`。
Fast36406544195 success，Full36406544104 skipped；没有为本轮重复广泛测试或构建。

服务与配置保持Qwen3.6-35B-A3B-FP8、temperature0、max_tokens4096、thinkingfalse、容量65536，
bge-m3/1024维；每公开消息12次生成上限，Root真实HTTP并发1。
每脚本独立namespace、Store、checkpoint和world，运行源码/输入冻结后不变，runtime不读取评分合同。
Root逐脚本核查回答和实际工具/Store/后续HTTP，上一脚本任务义务通过才运行下一脚本。

| 脚本 | 任务义务 | 实际关键观察 |
| --- | ---: | --- |
| complete_plan | 14/14 | 五字段真正保存，fresh-session完整回答 |
| partial_plan | 11/11 | 保存五字段，回答只要求的数量/包装；另三字段诊断缺项保留 |
| one_reply_format | 5/5 | LOCAL:仅当次；下一session普通句，Store空 |
| independent_update | 20/20 | 同ID只更新时间，独立key记录identity/body保持 |
| quoted_rule | 4/4 | 引用归于courier，后续search为空，无 adopted rule |
| read_only_note | 13/13 | 两次后续使用正确，无写入 |
| explicit_delete | 13/13 | 真正DELETE TX、CR保持，后续当前缺失正确 |
| assistant_conflict | 9/9 | 旧assistant确认6与当前durable9同时交付，回答9 |
| dynamic_world | 23/23 | reserve/label一次、实际lookup；旧规划仍not booked |
| moderate_bank | 18/18 | 六个独立records、两组三项查询准确，无写入 |
| reversed_count | 13/13 | 当前COUNT: 4；历史12，即使search返回当前4 |
| revised_location | 13/13 | 当前两行LOCATION/cupboard D-9；历史L-2 |

沿用原合同，COUNT: 4可作为椭圆句，不临时要求主谓/句末点号；L-2在保留上下文中唯一指向原locker，
不添加重复locker字词要求。历史读取、当前记忆、实时业务状态与临时格式分别通过，不靠 pooled分数替代。
54条HTTP均有真实provider ID、路由/交付和工具审计关联；实际tool正文保持，model前缀省略hash，
完整body hash和操作来源继续存在于trace/Audit。所有54次走all，最多6 records/329 candidate tokens，
每消息最多2次生成，没有query/attention压力或controller调用。

## 离线核查错误与修正

第8脚本完成后，Root新增的工具前缀检查错误要求所有observation_received_at非空，离线核查退出。
竞争解释一是compact误删当前回执时间；解释二是核查误把历史工具记录当成本轮回执。
实际当前回执有时间，原`_receipt_time()`只接受相同run/arm/owner/message作用域；历史应保留null。
旧full冻结回放中已有18处历史null，运行源码没有在S2改变该规则。

首断点是Root离线核查断言。R1原字节保留；R2加入精确scope/body校验时误从缺run_id的view取字段，
KeyError后改为实际route的完整scope；R3按同scope精确时间、异scope必须null及原body hash核查全部12脚本通过。
原freeze保持R1 helper hash，结果单列R2/R3 hash和修正依据。源码、prompt、输入、评分门槛都未改变，
没有真实语义失败、模型重试或重放业务。只读工具入口查找时的缺失路径也未引发实际执行。

## 成本与比较

| 口径 | v5对应12脚本实际运行 | v6 compact本轮实际运行 |
| --- | ---: | ---: |
| generation calls | 53 | 54 |
| input tokens | 72,573 | 71,723 |
| output tokens | 2,239 | 2,296 |
| generation总tokens | 74,812 | 74,019 |
| embedding calls/tokens | 22 /438 | 23 /448 |
| task义务 | 156/156 | 156/156 |

实际总tokens少793，但新UUID、生成措辞和历史问题额外search导致轨迹不同，不能将这793解释为压缩净效应。
固定131请求的S2离线输入差仍单独是-6,870 tokens（完整输入-3.80%，定义的记忆组件-9.54%）。
本轮新增54 generation/input71,723/output2,296，总74,019；23 embedding/448 tokens。
CREATE17、UPDATE4、DELETE1、search_memory2；业务reserve_and_label1、get_reservation1。
无HTTP错误、unknown usage、capacity拒绝或semantic/infrastructure retry。
process wall75.91秒、user CPU67.86秒、system CPU5.00秒；HTTP wall26.74秒。
Store逻辑calls/bytes、checkpoint和审计CPU/wall详见结果；物理I/O、独立write CPU、GPU/货币费用和未计时分析保持unknown。

连续账本为 **3,199 calls /4,072,857 generation tokens /22,784 embedding tokens**，
SHA `21391244c78c87deb85efa144a6c91c36e98ed82977d341731dfb0c3c988b9a1`；history/limits保持，差额与全部54唯一provider IDs核平。
v6至此合计新增74 generation/101,503 tokens，28 embedding/563 tokens，不含开发代理消耗。

## Reflection 与下一阶段

1. 支持：选定compact投影在全部12个暴露脚本上保留原任务能力。
2. 反驳：本轮未发现需要把value包装、空容器或模型hash恢复才能完成这些任务的证据。
3. 首断点：无真实任务失败；离线timestamp断言错误已定位到Root核查层。
4. 简单解释：旧脚本原本就可解，回归通过不证明新结构泛化或压缩因果收益。
5. 简单方法：继续唯一current_request/compact_v6 recipe，不增加prompt、reviewer或持久状态。
6. 复杂度：显式renderer/投影得到局部可验证边界，库默认system/full仍保留。
7. 过拟合：脚本已暴露，COUNT/历史措辞沿用既定解释，不在结果后新增要求。
8. 反例：独立任务的scope、引用命令、部分副作用、多owner与混合语言仍待S4。
9. Continue：S3完整门槛已通过；冻结并发布预先草拟的12-script/40-message独立任务，再执行唯一S4候选。
10. 理由：具备进入独立任务的工程与回归依据；S5/S6按S4结果触发，S7/S8仍需真实检索压力。

S4–S9未完成，不据此关闭v6 Goal。总体研究NOT_ACHIEVED，Product NO_GO。
