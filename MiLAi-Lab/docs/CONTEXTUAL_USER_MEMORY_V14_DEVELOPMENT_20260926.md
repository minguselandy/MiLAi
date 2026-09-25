---
version: v14.0
date: 2026-09-26
status: IMPLEMENTATION_IN_PROGRESS
baseline_commit: 488a4291925c607f6d0dc313a7dcbaf1906a6fad
planning_commit: a1154d8
scope: MiLAi-Lab
---

# v14 语义边界开发记录

用户明确要求执行 [v14 Goal](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v14.0_20260926.md)，原仅规划授权限制已由新指令取代。[实施基线](../data/manifests/contextual-memory-v14-baseline.json)确认 Git 基线的 46 份运行文件与 v13 最终映射相同，v13 结果清单引用证据及封存账本未改动。v13 的首次约定零卡/零持久来源、无回执审批措辞和持久正文临时引用问题继续保留。

一个 Sol xhigh 负责核心/Host/合同、配置和正式入口；主线程负责基线、输入冻结、真实模型控制、成本与报告。模型并发为 1。Luna high 沿用已有 Git 发布授权。本轮源码与模型已在本地，无须下载；不设置常驻审核代理。

| 工作包 | 当前安排 | 验证边界 |
| --- | --- | --- |
| A 未来用途及剩余处置 | 复用 maintenance.pending/frontier，增加最小 dispositions 与真实 write_facts | 首次直接观察均有处置机会；真实来源关联不等于整条消息全部意义处理完毕 |
| B 执行回执 | 复用 RuntimeStore intent/result，finish 声明 completed_action_refs/pending_actions | 结构回执与实际 answer 分别验收，不以查询/消息冒充另一业务完成 |
| C 自包含正文 | 已发布协议 token、有效原始来源支持的 literal_uses；CREATE/full REVISE/patch 新片段 | 不按 mN 外形全禁，不因真实重复型号出现多次拒绝；混合字面/指代仍要语义核对 |
| D 表达与身份 | 先离线定位重复，再收敛说明；独立 v14 notes/maintenance v5 与必要协议版本 | 同一可调用能力；旧活动身份不冒充新运行，原磁盘布局不重造 |
| V0—V3 | 开发后窄检查 → 冻结独立诊断 → 原 arc0 → 条件满足后两条新原生 arc | 原始输入、gold 隔离、费用与所有失败保留；不提前生成未见题挑样本 |

v14 费用使用新连续账本并引用封存 v13 的 56 次生成、345375 generation tokens、2797 embedding tokens，unknown=0、Judge=0。累计上限保持 null；单工作流容量仍有效。开发代理开销不混入 benchmark provider tokens。

尚未生成 V1 诊断输入、未生成或读取 V3 新原生任务、未调用 v14 实验模型。此开发记录不表示任何 readiness gate 已通过；最终必须分开核对 G1 首次保留、G2 不过度保留、G3 执行依据与真实措辞、G4 正文及字面碰撞。


## 零模型基线测量与运行准备

[固定请求拆分](../data/manifests/contextual-memory-v14-contract-baseline.json)读取 v13 R1 的 29 份真实请求：system 文本累计 86868 tokens、frontier 文本 7755；两者与其他历史材料的独立估计不直接加总为 provider 计费。稳定规则前缀为 790、工具目录 1915，动态主体尾部为 94—368。未来约定保留及业务完成/记忆保存的区别在多个位置重复；v5 将据此收敛，新增语义字段成本另外报告。初次统计脚本未考虑目录后面的主体尾部，JSON 解析报错后按真实边界修正；未涉及模型调用或运行源码。

[服务核对](../data/manifests/contextual-memory-v14-provider-baseline.json)确认部署为 vLLM 0.27.1 / xgrammar 0.2.3；实时配置指标显示 prefix caching=false。未重启或变更服务，未估算缓存/延迟收益。新 v14 连续账本已创建，累计上限为 null，引用封存 v13 的准确账本哈希。

[曝光及前瞻规则](../data/manifests/contextual-memory-v14-exposure-rule.json)只读取历史选择与原始制品的身份字段，汇总 36 项记录；已暴露 base_seed 为 0、1、2。只有 V1/V2 满足 G1—G4 后，才生成最小未暴露的两条原生 arc，并在请求前排除相同完整哈希；初始候选为 3、4，尚未生成/读题。运行失败不得换 seed 覆盖。

独立入口 [run_contextual_semantic_v14.py](../tools/run_contextual_semantic_v14.py)使用正式 TaskTurn/task_runtime 和可信本地工具结果。它不读取 rubric/expected future_use，不设置 persistence_required；每例隔离运行库、按正式 session 边界关闭/重开，失败保留制品及费用。入口源通过单文件 Ruff/mypy；尚未生成诊断输入、未运行模型。此检查只证明接线与静态属性，不算语义成功。

## 本次 GitHub 开发快照

用户要求由 Luna high 将全部当前开发提交到 `minguselandy/MiLAi`。本次快照仍为 `IMPLEMENTATION_IN_PROGRESS`，不关闭 v14 Goal，也不声明研究基线已通过语义验收。核心改动已经接入正式路径：

- A：maintenance-v5 复用现有 pending/frontier，提供 unhandled_candidates、dispositions、write_facts；预检与实际 finish 使用同一语义校验入口。
- B：execution_facts 来自实际 journal 和当前已交付来源；completed_action_refs 仅接受已交付的成功回执，包括当前明确展开的合法既往回执。HostResult 分开保留 answer、完成引用和 pending_actions。
- C：写入前检查已发布的临时 token；literal_uses 需有有效写入依据及已交付原始字符支持。patch 仅检查新增片段，未改动的旧正文污染单独报告。
- D：独立 v14 notes 模板及 prepare/MERIT 入口已接线；config 为 contextual-task-v14、maintenance 为 turn-maintenance-v5、write 为 contextual-write-contract-v14。现有身份校验区分新旧运行。

核心负责人执行的受影响检查：

```bash
.venv/bin/python -m pytest -q --tb=short \
  tests/unit/test_contextual_turn_maintenance.py \
  tests/unit/test_contextual_content_patch.py \
  tests/unit/test_contextual_host_adapter.py \
  tests/unit/test_contextual_runtime_recovery.py \
  tests/unit/test_contextual_v9_prepare.py \
  tests/unit/test_contextual_merit_adapter.py
```

结果为 **88 passed**；同批 12 个改动源码/测试文件 Ruff 通过，8 个源码文件 mypy 通过，`git diff --check` 通过。独立诊断入口的单文件静态检查另见上文；新增四份 manifest 与 notes 模板 JSON 解析通过。未运行全套测试、构建或 v14 实验模型。

后续仍需部署 decoder 检查、合同压缩后的同口径 token 对照、开发完成后冻结的 V1 独立诊断、V2 原 arc0，以及满足语义门槛后才开展的 V3。结构检查不能证明自然语言答案真实或混合来源已被完整处置。改动均限于 Lab，未改变 Product Schema/API/权限/Canonical，也未移动包或引入跨 bundle 依赖；未另跑边界全套。回退基点为本快照前的 `a1154d8781fb3c25ffaa397cff2f5e688fa57cd1`。原始日志、数据库、模型、数据集与运行制品继续保持 ignored。
