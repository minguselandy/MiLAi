# 已测已付成本：LME六阶段关闭后的静态截止点

截至两方法LME全部prediction/score/archive实际关闭与idle137支付之后、Mem2Act固定前缀
全400条子进程启动之前，当前目标可核对的已付CPU为 **156,772.304695秒
（43.547862 CPU小时）**，已知Host生成用量为
**30,712,462 tokens**。
这是已测、已支付的静态截止量；正在运行的Mem2Act、之后离线计时和未测部分仍在边界之外。
CPU小时不等于GPU小时或金额，也不代表完整项目真实成本已知。

## 与上一截止点逐项衔接

| 互斥费用范围 | CPU秒 |
|---|---:|
| 上一LME007启动前已付截止量 | 87,091.840961 |
| 新99个原生LME client具名残差＋已测父CPU | 51,591.727529 |
| 同期通用NN/加载phase实际增量 | 4,475.314659 |
| 新101次idle：465个闭合普通GNU计时 | 8,992.050000 |
| 新95个独立存储整child＋已测父CPU | 4,621.371547 |
| 本次新增合计 | 69,680.463734 |
| 当前目标已付可观测CPU截止量 | 156,772.304695 |

新增295个具名compute phases恰好分成99原生client、101普通离线付款和95独立存储，
没有交叠或未解释项；另有两项原已存在的通用native phase改变。增加的NN CPU
4,139.538284秒与加载CPU
335.776375秒由实际关闭owner逐项解释，
已包含在相应整child中。新增99原生调用的整child＋父CPU为
56,067.042188秒，恰等于具名残差/父CPU加上述通用native增量；
不能再把整child与native/residual列相加。普通审计、CPU存储和原生归档各自来自不同进程范围。

通过当前截止点，具名A100 phases共418个，剔除旧v79遗留债务45.39秒后净额
141,983.853060秒；累计通用native增量14,788.451635秒。
它们相加得到总截止量，P0原四个具名phase仍只计一次。上一截止点20条native归属边
已重新读取实际owner/关闭回执，并与最早功能结果的原始budget-before差分再次核对。
没有重置、退款、新charge或第二份操作账本。

LME全部106个原生client phases均已支付、父子进程实际退出；它们包括两方法各51段
首预测、各1次评分与各1次归档，合计整child＋已测父CPU74,405.324207秒。
其中最早7段的18,338.282019秒已在旧截止量内，本次只增加其余99段，避免跨截止点重复计量。
首次CPU条件不匹配、观察器中断、Reader/Judge失败和已知用量都按实际保留；阶段段数
不是新增任务或独立样本数。早期Source物理快照缺口的披露不改变实际已付费用。

## 离线与独立存储证据

idle37至137的101张回执对465个原始GNU timer逐个读取复核，路径没有与旧1–36的
已付计时重复；465项包括10个实际非零退出，失败费用未删除。每份普通付款CPU与
其闭合计时之和及缓存compute phase数值相符。95个独立存储phase另与实际存储owner
的整child/父CPU、退出状态和指定付款回执逐项一致；不把它们再混入原生模型child。
模型、加载、Source准备、归档和更早存储的嵌套费用没有重新加总。

本次核对只读固定的Mem2Act budget-before副本、旧快照、原始owner/付款回执和关闭
计时，不打开正在变化的原账本，不中断当前400条任务。新分析/报告CPU发生在这份
截止快照之后，等待下一合格idle；不能提前写入此截止量或当作零成本。

## Host、本地NN及未知范围

相对旧截止点，Host已知/charged生成tokens均增加5,343,665，
逐项等于新增99个已关闭LME owner的实际用量。原RunBudget reserve计数增加
999；该段与owner实际准入一致，但累计
6766个历史reserve仍不能一概改称成功HTTP或本地NN调用。
全部LME两个方法实际共1164次Reader/Judge HTTP、6,111,718已知tokens，部分已在旧
截止点中计入，不能再把全部LME tokens加到新目标总量上。

本地categorical NN另有3594个返回forward、25,070,604输入tokens及51次实际加载；
raw native计数还保留state_tokenizations3594/state_tokens22,265,944。这些是模型的
本地输入/计数，不是Host生成tokens；决策head输出为候选分数，不伪装成生成tokens。
NN、加载及完整调用区间的定义分别保留在[两方法LME调用报告](MILAI_A100_LME_NATIVE_COMPARISON_20261109.md)，
GPU调用区间含复制/IO/Reader等待，不能据本表CPU换算GPU忙时或Encoder纯延迟。

截至快照新增generation unknown为0；历史15次generation及1次embedding unknown保留，
embedding状态和limits逐字段不变。当前Mem2Act及活动行的新未知用量等待原生owner
实际退出核算，此处不推断。Host GPU0/1忙时、能耗和货币费用未测；未计量的作者/
编排/启动/检查/清理CPU仍为unknown_not_zero。旧输出控制丢失父监测的成本仍只有
已观察child199.51秒下界，父及未观察清理未知，不被升级为完整测量。

本表不含快照之后的v175/v176、真实失败病例Source审计、v2观察审计冻结、当前新分析
及后续Mem2Act/报告成本。基础模型与历史数据取得/摊销单列，执行助手自身tokens
也不混入实验Host账本。完整项目的质量—成本结论仍需后续全部实际成本和未知范围。

## 复核入口

- [295个新增具名phase、通用增量及计量边界](../data/manifests/a100-known-paid-cost-through-lme-20261109-v1.json)
- [静态来源复算代码](../tools/reconcile_a100_cost_through_lme_closed.py)
- [上一历史截止点](MILAI_A100_KNOWN_COST_CUTOFF_20261107.md)
- [LME两方法原生结果/操作/调用成本](MILAI_A100_LME_NATIVE_COMPARISON_20261109.md)
- [整体执行状态](MILAI_A100_DEVELOPMENT_EXECUTION_20261104.md)

完整106个原生owner、95个新存储owner、101回执及465计时路径保存在ignored
`artifacts/a100-development-20261104/known-paid-cost-through-LME-closed-before-Mem2Act-v2.json`。
用不存在的新输出可重现，不读取live账本，不发模型/HTTP，不用SHA或内容指纹：

```bash
python3 tools/reconcile_a100_cost_through_lme_closed.py \
  artifacts/a100-development-20261104 \
  artifacts/a100-development-20261104/known-paid-cost-through-LME-closed-new-output.json
```

Mem2Act400×2、最终完整项目成本、论文/图表及原763行逐项完成审计仍未完成，目标继续。

后续使用[最终静态成本衔接入口](../tools/reconcile_a100_final_known_cost.py)。当前只执行了
`--preflight-only`：核对这份静态截止点，列出尚缺的两方法closure/Source/score及800归档门禁，
没有计算Mem2Act成本，也没有打开活动账本。真正汇总必须等这些门禁全部通过、原owner退出
支付、实际idle138及后续普通/失败计时付款，再显式传入当时保存的账本副本和最后idle编号。

入口按全部实际owner祖先核对原生/整child/残差/已测parent，将新增具名phase严格分成原生
client与普通付款；逐张回执排除旧计时并保留非零退出。不会把NN/加载再次加到整child上，
也不会把旧156772秒或共享baseline重复加入。报告自己的计时与后续出版CPU位于输入快照
之后，仍需下一实际idle处理；未测作者/settler/清理、HostGPU忙时和金额继续保留未知。
最终结果仍是明确时点的已测已付范围，不能把未知成本填成零后称完整真实成本已知。
