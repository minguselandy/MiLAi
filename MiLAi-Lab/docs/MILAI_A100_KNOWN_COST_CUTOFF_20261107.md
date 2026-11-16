# A100已付可观测成本：LME007启动前的静态截止点

截至三套旧64模型真实退出/全量评分审计及idle36支付之后、LME007实际启动之前，
可核对的新目标已付CPU为 **87,091.840961秒（24.192178 CPU小时）**。
这是已测且已支付的截止量，不是完整项目真实总量，也不是GPU小时或金额。
该截止点之后的LME007、其存储、后来计时以及未测作者/启动/清理等均不包含。
后续[LME六阶段关闭截止点](MILAI_A100_KNOWN_COST_THROUGH_LME_20261109.md)已单独核对，本文历史口径保留。

| 互斥计算范围 | CPU秒 |
|---|---:|
| 123个具名A100 phase（包含旧债） | 76824.093984690 |
| 减：旧v79遗留债务 | 45.390000000 |
| 当前目标具名phase净额 | 76778.703984690 |
| 加：通用native/加载phase精确增量 | 10313.136976421 |
| 当前目标已付可观测CPU截止量 | 87091.840961111 |

## 差分边界与不重复计量

终点直接读取原冻结LME007的budget-before副本，没有打开正在运行的原账本。
通用模型phase的基线来自32个本轮首次功能结果中最早的budget-before，revision48733。
当时只有四个本轮P0具名phase已存在；它们仍通过终点的具名phase数值计入一次。
在其余不具名phase中，只有dynamic_memory_laya与load的CPU改变。

两者共10313.136976421秒，已经由20个实际owner/关闭回执的native部分逐项解释，
加总与静态快照差分完全相等。这些native部分嵌在各整child内；具名client phase只
补残差/已测父CPU。因此不能再把整child或原GNU timer与native phase一起重复相加。
最早C切片已从离线付款中扣掉native380.644227562秒；原32/33次离线证据普查也
单独核对了此边界。此处没有新charge、退款、重置或第二份操作账本。

## Host用量与未知边界

从第一次新功能请求前，到静态截止点的原生generation已知用量差为
**25,368,797 tokens**，与charged差相同。
原账本generation_requests增量为5767，它是原RunBudget reserve计数，不能不经逐请求
核对就改名为成功HTTP响应数或本地NN决策数。本地categorical NN输入tokens另列，
不混成Host文本生成tokens。未测的Host GPU0/1 kernel忙时、能耗与价格不推算。

新增generation unknown_usage为0；旧15次generation/1次embedding未知保持。
embedding状态逐字段不变。早期旧输出控制丢失父退出监测，child只能报告已观察
199.51秒下界，父/未观察清理仍unknown；该截止量不会把它补成完整测量或零开销。
训练器进程内clock之外的部分开销、扫描器/编排/作者等未测范围仍须在最终表里保留。

这不是GPU执行效率比较。三个旧64模型的约9分钟整进程区间还包含初始化、完整
输入/输出持久化与逐格驱动状态写入；不能直接称为Encoder推理延迟。原native每次
preparation/inference计时保留在首输出，完整child费用只计一次，不再加嵌套计时。

三套旧64模型的保存首输出给出以下嵌套计时；它们已包含在各自完整进程范围内。
两者差额还含加载、驱动状态序列化、文件写入和其余代码，现有计时不能把差额全部
归为某一个环节。后续性能工作应另立新协议，不能重跑这些首结果来替换本次成本。

| 模型 | native准备wall秒之和 | native推理wall秒之和 | native CPU秒之和 | 完整child CPU秒 |
|---|---:|---:|---:|---:|
| initial | 11.188143 | 106.893566 | 132.095760 | 547.449487 |
| A0 | 10.765776 | 106.674114 | 131.103556 | 543.132255 |
| A1 | 10.640348 | 106.531764 | 130.851684 | 535.756401 |

## 复核入口

[全部123个具名原始phase、20条native归属边及静态来源路径](../data/manifests/a100-known-paid-cost-cutoff-20261107-v1.json)
提供逐项数值和不变条件。[离线计时证据](MILAI_A100_CLOSED_COST_EVIDENCE_20261107.md)
与[旧64原生结果](MILAI_A100_RESERVED64_NATIVE_RESULTS_20261107.md)保留各自口径。
[静态来源复算代码](../tools/reconcile_a100_known_paid_cost_cutoff.py)只读已有结果与账本副本，
实际复现输出除时间戳外与原报告逐字段相同，不读取live账本：

```bash
python3 tools/reconcile_a100_known_paid_cost_cutoff.py \
  artifacts/a100-development-20261104 \
  artifacts/a100-development-20261104/known-paid-cost-cutoff-before-LME007-reproduction-new.json
```

完整LME451×2/Mem2Act400×2、最终全成本、论文/图表与完成审计仍在进行，目标未完成。
本报告没有新模型/HTTP、业务写入、SHA或操作账本读写。
