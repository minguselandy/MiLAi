# 原生 Agent 上的 ReasoningBank 与经验修订

本实现是 `RESEARCH_PROTOTYPE`。业务动作、任务终止和评分由固定版本的原生 benchmark 执行；
Lab 负责方法、作用域、模型调用账本和分析。当前只使用 Qwen3.6-35B-A3B-FP8 进行文本生成，
按用户既定配置使用 bge-m3 检索，reranker 关闭。

## 方法与配置

| 方法 | 原生循环中的行为 |
| --- | --- |
| `NATIVE_AGENT_OR_HISTORY` | DB／OS standard；旅行保留给定和累计计划 |
| `OM_SYNC_PORT` | 沿用同步 Observer／Reflector，按阈值整理历史，保留近期原文和来源回读 |
| `REASONINGBANK_BASE_PORT` | 查询索引 top-1 历史任务的全部经验；独立自判、成功／失败提炼和追加 |
| `MILAI_EXPERIENCE_REVISION` | RB 底座，加临时采用判断、Actor 明确反馈请求、旧经验修订和按需回读 |
| `NATIVE_VERIFIED_HISTORY_REFERENCE` | 上游回调只回放 CORRECT 且 COMPLETED 的历史，单独标明反馈条件 |

候选的采用调用只更新临时 working note／可选 Frame。修改旧经验必须由 Actor 请求，
指定它已见到的经验条目和实际业务工具反馈。维护器可先读取来源，再提出稀疏修改。
v0.4 的旅行适配在采用前发布给定及前序计划原文，采用和 Actor 视图均可见，来源仍可按需回读。
下次输入使用当前版本，旧版本以历史来源保留。维护不能替代原生 Actor 的最终交付。

`revision_application=append_only` 是贡献对照：沿用同一采用／修订调用机会、输入来源和工具，
把提议追加到原查询记录，保留旧活动经验。重复建议的上下文和维护成本全部计入。
模型没有请求修订时，对照仍保留在计划分母中；不挑选触发过修订的案例报告。

## 三种作用域

- **F：固定支持银行。** 每题使用同一支持制品的临时副本，末尾自判／提炼仍计费，所有更新丢弃。
- **O：在线独立流。** 从空库开始，只继承本流已完成任务形成的经验；流间不共享。
- **G：依赖旅行组。** 从固定支持银行复制；给定 base plan 进入各方法记忆，组内保持原生顺序。
  已给定的基础人员不额外生成 Actor 答案；记忆维护单独计费。测试组之间不提交新经验。

银行绑定 experiment、method、model、domain、method_version、protocol、split 和 stream。
支持库到测试作用域的复制是显式操作。新进程恢复会核对方法／政策／embedding 合同，
不会重做已完成的业务动作或用重新生成猜测先前是否提交。

## 运行入口

外部 checkout、数据、虚拟环境和运行证据的位置见
[执行清单](../data/manifests/reasoningbank-transfer-20260915.json)。
原生依赖各自安装在外部环境；`src/milai_lab` 不导入原生仓库或 Product 私有代码。

```bash
# 在 MiLAi-Lab 目录运行，使用执行清单指定的外部解释器。
PYTHONPATH=src:tools /path/to/lifelong-venv/bin/python tools/run_reasoningbank_lifelong.py --config /path/to/config.json
PYTHONPATH=src:tools /path/to/travel-venv/bin/python tools/run_reasoningbank_travel.py --config /path/to/config.json

# 独立计划的 worker；依赖银行按已登记顺序传递。
uv run python tools/run_reasoningbank_batch.py --manifest /path/to/batch.json

# 评分只读原生评分制品；不调用模型。
uv run python tools/summarize_reasoningbank_evaluation.py --batch /path/to/batch.json --output /path/to/summary.json
```

配置指定冻结 split 的路径和 SHA256、原生域／ID、唯一模型、输出目录、任务／组资源上限、
流／worker 总上限和来源锁。输出目录必须是新的。批次不自动重跑失败任务，也不重发用量未知的请求。
单位时间上限在新请求发出前检查；已发请求受 HTTP 等待和 worker 总截止时间约束，
实际单位耗时可能越过准入上限。时间实耗与停止原因单独保留。
正式矩阵由 `prepare_reasoningbank_evaluation.py` 根据版本选择结果和预选 ID 生成。

已有服务没有启用自动工具解析。旅行使用该模型的实际 `/tokenize` 工具聊天模板，
把返回的精确 token IDs 传给 `/v1/completions`，再解析模板声明的 XML 工具调用。
四方法共享这一传输；原生工具名称、schema、返回值和业务步骤上限保持相同。

## 成本与失败

每次生成先登记上界，收到可核对的 usage 后结算。Actor、自判、提炼、采用／修订和
Observer／Reflector 都计入。embedding 使用独立账本；不把它算成免费工具或文本生成。
未知用量保留请求和上界，不能填零。没有实际价格时不计算货币费用。

任务已经交付但新的经验提炼失败时，保留原生成绩和已有银行；在线已接受的旧经验修订
不因后续提炼格式失败而撤销。F 的整个临时工作层仍然丢弃。
原生环境错误、上下文／资源终止和维护失败分别保留原因；旅行缺失人员按计划分母计入。
`terminal_sessions` 包括原生步数上限后的空计划；另列 `nonempty_final_plans`，二者不等于正确率。

公开 Working State 的真实银行恢复检查复用既有生命周期入口，使用已经固定的修复 Product lock。
已验证 6 卡片／2 查询记录经公共 SDK 在不同进程中保存和恢复。大银行仍是外部研究制品，
不能将这次小载荷成功解释为公共接口支持任意银行容量。

## 结果解释

四主方法的全质量和全成本是主要结果。只追加对照评估更新应用方式；
`run_reasoningbank_consumption_diagnostic.py` 从同一个实际输入产生两种下一动作，
仅替换候选消费指令，保留相同经验、工作判断、原文来源、历史和工具。
该诊断不执行任何动作，因此不能证明最终业务结果的因果差异。

F 按来源簇、O 按独立流、G 按完整组及已知来源簇进行配对重采样；
少量流的区间不稳定必须保留。工程可运行、自然机制出现和创新收益成立分别报告。
当前进度与限制见[开发记录](../studies/active/MILA_REASONINGBANK_DEVELOPMENT_RESULTS_20260915.md)。
