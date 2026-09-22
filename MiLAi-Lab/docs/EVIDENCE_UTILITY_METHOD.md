# 证据与效用候选：开发使用说明

状态：`v0.7-dev`，功能开发中；未通过正式确认，不推广默认方法。

## 已接入的路径

继续使用原 `run_reasoningbank_lifelong.py`、`run_reasoningbank_travel.py` 及原生环境。候选配置片段：

```json
{
  "method": "MILAI_EXPERIENCE_REVISION",
  "candidate_policy": "evidence_utility",
  "projection_mode": "selected",
  "post_task_revision": true,
  "feedback_regime": "H",
  "revision_application": "replace"
}
```

运行还需预先登记 split、IDs、作用域、完整资源额度和源码锁。已执行配置见本轮清单；不能直接启动不带额度的片段。

| 实现 | 责任 |
| --- | --- |
| `evidence_utility_session.py` | A1 选择、空采用、原始依据进入结束提炼、修订谱系、实际请求确认与结果归属 |
| `experience_utility.py` | 版本与组合使用记录；同请求保留新正文及历史旧页的两个版本；不平均分配成功标签 |
| `reasoning_bank.py` | 原检索、形成、来源、银行事务；可选 utility_state 与正文和已完成位置一起保存 |
| `reasoningbank_provider.py` | 请求与实际 wire 散列、已结算回执、包含维护的逐角色任务成本 |
| `reasoningbank_runtime_policy.py`／原生 runners | 方法身份、政策散列和 H／R 结果发布时点 |

`original`／`optimized` 仍对应独立 v0.6 算法。v0.7 的政策和反馈合同进入 bank contract；不得将旧政策的库改名为新库。既有正式运行继续使用各自冻结源码。

### 空采用、反馈及恢复

空采用不注入经验正文、消费说明、采用备注或全目录；原生请求和必需事实保留。XML 环境保留短来源入口 `experience:catalog`，旅行继续用 memory_read 工具；目录按范围分页回读。

H 不向方法发布原生正确标签；模型自判只用于提炼分支。R 的候选在原生终态已保存后仅取得正确性 bit，用于版本使用记录；提炼输入不增加该 bit。固定 TEST 的 R 也不发布结果。旅行首版仅接 H。

Provider 成功返回并核对实际请求后，确认的是 Actor 输入中的精确版本**暴露**，不是模型实际使用或因果贡献。
旧字段中的 use／使用序列沿用历史名称；只组装、只检索、未确认请求不计入，未知费用由账本保留。
结束提炼的修改不回填当前题暴露版本；多版本任务保留顺序，仅作组合／序列结果关联。
本 Goal 后续 Revision／Attention 的准入与旧实现差异见[零模型准备](REVISION_ATTENTION_READINESS.md)。

新正文绑定前身与依据，初态未校准；旧版正负结果仍可查，不转为新版实测分数，也不因改写获得额外探索机会。A1 可看到有界的相关历史序列；它不是已校准的因果效用估计器，A2 尚待开发。

在任务边界通过原 checkpoint 保存。恢复验证正文版本散列、前身、反馈合同、暴露版本及完成位置。真实 DB／OS 银行已在新进程恢复核对；不能恢复后重复提炼已提交任务。F 的任务覆盖层丢弃，长期内容、索引和效用保持原样。

## MemRL 本地移植

`MEMRL_LLB_PORT_v0.1` 已接入 DB／OS，固定 [MemTensor/MemRL@c1b322c](https://github.com/MemTensor/MemRL/tree/c1b322ca43de36ddf64c6712f89d0095bfc35ce0)，保留 MIT 许可。核心位于 `memrl_port.py`；政策、来源和许可位于 `configs/policies/memrl/`，wheel 也包含许可。

1. `retrieve_query` 按余弦阈值过滤并取候选查询，再按归一化相似度与 Q 加权排序，以 epsilon 选择最终条目；不能用未被该 runner 调用的通用选择器代替。
2. 已选择条目按原生结果做 Q 更新。成功时形成策略脚本并保留原轨迹；失败时新增反思条目，默认 append。相近查询可共用检索键。
3. Actor 输入区分成功与失败经验，去除重复环境前言及失败轨迹长尾；原始内容仍保存。冻结评价不能更新正文、Q、索引或参数。

入口沿用 `run_reasoningbank_lifelong.py`，配置需设置 `method: MEMRL_LLB_PORT_v0.1`、`feedback_regime: R` 和完整运行额度。每道任务新建 Session；内部银行格式和候选／RB 分开。R 仅在保存原生终态后公布正确性 bit，缺失不补零；当前题不重做。F 不向方法发布当前标签，也不形成或更新；跨题探索仅推进运行中的临时随机游标，种子银行包括 RNG 状态在内保持不变。

固定参数：查询候选 10、最终条目 5、epsilon 0.01、alpha 0.3、gamma 0、正负初值均 0.5、奖励 1／0、Q 下限 0、过滤阈值 −0.8、相似度与 Q 权重各 0.5。DB／OS 相似度阈值为 0.37／0.50，查询归并阈值 0.99，Q 标准化统计在过滤前计算。沿用官方 YAML 的相似度均值 0.39、标准差 0.14；这是未在 BGE 上校准的已声明设置，不是 TEST 拟合结果。

本地差异：共同 Qwen、BGE-M3 1024 维原始任务查询、不加 RB 检索前缀；DB 3／OS 5 轮；一次顺序学习；形成输出上限 2,048 tokens。成功形成温度 0，失败反思温度 0.3。沿用上游的 Actor 基础说明、末尾严格格式和形成提示，共同行动预算仍保留。JSON 银行替代 MemOS，查询向量在提交前完整缓存；不使用重放训练、第二求解模型或未知费用后的自动重试。

已知形成失败保留当前 Q 更新和完成位置，并报告未形成；未知网络／费用状态停止执行，不伪造反思文本。Q 按上游算法关联所选条目，**不代表每条经验对成功或失败都有因果贡献**。实际呈现另外绑定已结算 Provider 请求，供行为核查。

固定源码函数对照通过 27 个检索条件、6 个实际本地 Q 更新及经验呈现文本。真实 DEV 完成 O-R 两道 DB／两道 OS，以及 F-R 各一道；四份银行在独立进程恢复，F 状态精确不变。完整研究仍待新来源确认，H 的强参照仍是 OM。

## OM 容量版本

`native-om-capacity-v0.3.1` 通过以下独立配置启用，旧配置继续使用原 OM：

```json
{
  "method": "OM_SYNC_PORT",
  "om_compact_provenance": true,
  "om_capacity_policy": "bounded_v1",
  "om_config": {
    "measurement_margin_tokens": 256,
    "maintenance_max_calls": 4
  }
}
```

`observational_capacity.py` 复用原始事件和分页格式。Observer 按完整请求容量选页，必要时细分未覆盖的范围，只提交实际提供且获接受的页；未看到的页不前移。Reflector 按容量处理活动日志的一个前缀，以较短结果替换该前缀，保留余下日志和原始引用。相同完整请求的失败／无进展记录进入 checkpoint，恢复后不重复调用；任务或材料确实改变时按新的请求指纹判断。

每次装配或任务结束最多四次维护调用；仍采用原 12,000／16,000 token 触发阈值，Actor 容量压力可要求先整理日志。完整输入包含工具定义、原生事实及模板，另留 4,096 Actor 输出和 256 token 余量。必需材料自身超窗时报告容量不匹配，不删任务要求。

Actor 的遗漏目录仅含固定大小的来源引用、字符数和页数，原目录按范围回读；不再逐页展开。目录试装不会注册每个中间版本。最终发送前再次核对完整消息；旅行适配器保留独立的原生消息副本，避免结束维护把已注入记忆重复计入。

旧银行不能直接当作新版 SUPPORT 银行使用。旧旅行 31 的失败材料仅用于有明确标识的诊断导入，旧数据和冻结运行均未修改；已复现旧版容量失败，新版投影能够装入。此诊断不产生原生任务成绩，完整旅行组和新条件下的建库仍待验证。

## 未完成

新候选实际修订后再用的功能证据、共同旅行输入／工具及完整组验证、A2 开发配对与 VALID 选择、H／R 新来源确认、贡献拆解及最终完整回归。

来源盘点排除了两轮既有非 RESERVE 分配、已发送请求及关联来源。候选池尚有 DB 212 项、OS 242 项、旅行 150 组；这是待冻结的来源池，存在生成谱系不完整带来的近重复风险。

[目标](../studies/active/MILA_EVIDENCE_AND_UTILITY_DRIVEN_IMPROVEMENT_GOAL_v1.0_20260916.md) · [问题与结果](../studies/active/MILA_EVIDENCE_UTILITY_RESULTS_20260916.md) · [清单](../data/manifests/evidence-utility-improvement-20260916.json)
