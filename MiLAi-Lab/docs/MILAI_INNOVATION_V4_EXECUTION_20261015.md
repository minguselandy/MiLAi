# MiLAi v4 方法创新：当前执行记录

目标仍 **ACTIVE / 未完成**。执行用户提供的 `MILAI_INNOVATION_DEVELOPMENT_PLAN_20261015_v4.md`，
以 PR #122 的实际开发线 `c835cf67` 为起点，在
`feat/lab-innovation-v4-20261015` 独立工作树开发。已核对 #122 仍 open/draft/unmerged。
不合并 PR，不改写旧实验，不新增 SHA 校验、审核 Agent、第二账本或模型服务。

## 当前实现与可运行入口

`methods/semantic_delta.py` 接入现有 `EditMemory`、维护、Benchmark 与 Functional 设置入口。
设置 `maintenance_mode=semantic_delta_v1`、`maintenance_recipe=single_pass`，使用 M/I2、
来源元数据、时间选择和支持组，关闭独立 Impact。模型只生成新建、替换、追加、撤回和必要关系变化；
未变单元、版本与来源绑定继续交由现有服务处理。

共享前提用 `all`，替代路线用 `any` 表达，编译为现有 OR-of-AND 支持组。
没有显式关系时可保存自包含文本。关系是模型解释，不能将无证据当假，也不以可解析证明含义正确。
这一切片使用记录内关系；不是完整跨记录差分方法或已验证的架构优势。

初版 `922b79de` 增加一个由模型命名的 bases 表；真实形成失败后，`a47e88b8` 去掉该额外别名层，
改为直接引用已交付 e 证据，每个变化明确 kind。新建规则只允许新节点引用，移除仅用于已有关系。
这是减少模型机械决策的表示调整，没有给旧结果补别名或重新提交旧输出。

可运行配置：

- `configs/milai-innovation-delta-v1.json`：紧凑差分。
- `configs/milai-innovation-plain-v1.json`：普通命题局部更新。
- `configs/milai-innovation-full-v1.json`：保留完整依赖候选作为参照，尚未在新六链运行。
- `configs/milai-innovation-delta-smoke-v1.json`：首链子集；原失败运行已封存。

入口继续使用 `tools/run_baseline_alignment.py CONFIG OUTPUT --phase prepare|predict|score
--backend MiLAi-memory-only --benchmark halumem --runtime-dir RUNTIME`。
实际运行配置和数据路径固定在 `artifacts/innovation-v4/`，不在实验中热改。

## 已关闭的首轮真实调用

`delta-pilot-v1` 使用冻结 `c8ffd8e5`，四次来源到达、四份最终答案，进程 exit 0。
其状态并未全部成功：初次 bases 引用错误使形成失败；第二次生成空差分；第三次才建立凭证状态；
最后修正通行条并追加夜训要求。原准入规则、培训与电池位置仍未完整形成，未形成支持组，
年证已注销这一确定事实曾被标为 uncertain。

四份答案的核心内容均符合原文，但原文补答不能算状态成功。这是作者来源审阅，非独立盲评，
没有官方 Judge 调用。所有原始输入、输出、状态、失败和费用保留。

| 阶段 | 响应 | 输入 tokens | 输出 tokens | 总 tokens |
| --- | ---: | ---: | ---: | ---: |
| 维护 | 4 | 6,000 | 17,316 | 23,316 |
| 回答 | 4 | 3,816 | 8,234 | 12,050 |
| embedding | 5 | 312 | 0 | 312 |

生成总计 35,366，embedding 312；均与原连续账本增量一致，新增 unknown 0。
完整机器汇总见 `data/manifests/innovation-v4-delta-pilot-v1-summary.json`。

## 当前串行配对实验

`data/fixtures/milai-innovation-pilot-v1.jsonl` 是六条新作者开发链，各四事件/四题。
覆盖共享条件、OR 路线、未知、未来生效、历史纠错、局部例外撤销、传闻与计划、独立范围。
首链已用于格式调试，全部都明确是开发材料，不是独立保留集或官方 benchmark。

`paired-v2` 冻结代码 `08de761d`，普通局部与差分两臂分别从空库形成，共 48 次来源到达和 48 个答题位置。
两臂共享同一批来源、Qwen3.6-35B-A3B-FP8、BGE-M3、来源访问、Reader、8,192 输出上限和原账本。
先两臂预测，再分别首次评分。格式、结构及既有提示不同，不能把这次整体配方对比宣称为单一格式的因果消融。

启动工具会话 `9063`，driver PID `2877480`，初始 plain predict PID `2877561`；
最后检查这两个实际进程均存活。权威状态为 `artifacts/innovation-v4/paired-v2/driver.json`、
进程和实际回执，不能从本段静态文字推断未来仍运行。尚无整臂结果或排名。
下次先检查同一会话/进程，不重启、不增加竞争模型任务。

## 匹配学习与资源

`tools/prepare_innovation_training.py` 从审阅引用导出普通操作、转换质量、关系后果和紧凑差分四种目标。
`data/fixtures/milai-innovation-matched-training-v1.jsonl` 当前仅有 **1 个** 来源作者修正样例，
基于首轮实际来源与真实空 before；相同事实与规则正文给普通对照，关系目标单独增加支持组。
修正标签未写入运行库、未作为模型成功输出。此样例已暴露，只用于开发。
导出目录 `artifacts/innovation-v4/matched-training-v1`；参数更新 0、教师调用 0。

实际读取到四张 A100 40GB 均约 39.9GB 已用，现有 7860/7862 为同一生成模型。
未停止服务、未安排新 GPU 训练。后续扩充转换而非只形成的样本，固定未见组合，匹配训练 tokens、
步骤及参数后再启动真实学习；数据导出不是学习收益。

## 验证与完整剩余范围

17 项差分/依赖检查与168项现有入口/Functional 检查通过，共185个不同用例。
直接来源版本调整后5项差分检查再次通过。受影响6个源码类型检查、新编译器类型检查、Ruff、
包 DAG、工具依赖边界和278活动源码验证矩阵通过。真实 SQLite 与普通 CLI 都已使用。
新测试已归属安装 LangGraph 的现有 CI 作业。未运行全仓回归、未提交远端 CI、未声称生产就绪。
Product/Archive及Product公开 Schema/API/权限/Canonical不变；Lab新增 opt-in 方法输出协议。
回退依据是上述独立本地提交，源码基点 `c835cf67`；没有合并或远端发布本轮分支。

完整计划的以下要求仍待完成，不能以本批替代：

1. D0/D1：完成当前两臂状态、来源、全部答案、首次分数和阶段成本审阅；同真实 before 三方法诊断；
   相同示例的旧动作/新差分对照；短/充分输出匹配对比；保持失败而非择优重试。
2. D2：按需局部结构的无缓存、版本缓存和局部增量复用，处理新覆盖事件、时间边界及遗忘可见性；
   与原文/完整维护对照，实际测量复用与更新密度。
3. D3：同候选池增量证据价值、停止/补读和真实子集交付，先接原文；范围聚合单列。
4. D4：来源可审阅的匹配转换数据、实际参数训练、不同目标且相同预算、未见实体/范围/事件顺序评价。
5. D5：独立开发历史、长历史规模与质量—成本曲线、官方外部数据、第二模型、有效机制消融、
   按链配对统计和区间、适当的独立盲审与稳定性重复；选择规则和正式划分在看结果前固定。
6. D6：有机制收益的同一配方进入普通 Host 并完成真实端到端例子；不复制第二套算法。
7. 对每个继续推进的候选交付可运行配置、真实示例、配对结果与完整成本、支持/否定/下一步结论，
   再按 v4 全文逐项审计。三条路线不要求全部获胜，负结果允许改变或放弃旧架构。
