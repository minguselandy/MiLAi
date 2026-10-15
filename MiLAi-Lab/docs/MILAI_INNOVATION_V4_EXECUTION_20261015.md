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

## 已关闭的六链配对实验

`data/fixtures/milai-innovation-pilot-v1.jsonl` 是六条新作者开发链，各四事件/四题。
覆盖共享条件、OR 路线、未知、未来生效、历史纠错、局部例外撤销、传闻与计划、独立范围。
首链已用于格式调试，全部都明确是开发材料，不是独立保留集或官方 benchmark。

`paired-v2` 冻结代码 `08de761d`，普通局部与差分两臂分别从空库形成，共 48 次来源到达和 48 个答题位置。
两臂共享同一批来源、Qwen3.6-35B-A3B-FP8、BGE-M3、来源访问、Reader、8,192 输出上限和原账本。
先两臂预测，再分别首次评分。格式、结构及既有提示不同，不能把这次整体配方对比宣称为单一格式的因果消融。

队列 `9063` / driver `2877480` 已正常结束，两个预测阶段与两个首次评分阶段均 exit 0。

| 方法 | 首次 Correct /24 | invalid / Omission / missing | 预测生成 tokens | embedding tokens |
| --- | ---: | --- | ---: | ---: |
| 普通局部 | 21 | 2 / 1 / 0 | 230,866 | 2,696 |
| 紧凑差分 | 23 | 1 / 0 / 0 | 258,521 | 3,618 |

差分预测多用27,655生成tokens（11.98%），没有本批节省证据。两臂各24次维护和24次Reader；
普通局部有2次维护length和1次时间来源拒绝，差分无length，但仍有实质错误。
差分确实形成了首个OR支持组、保存并撤回临时例外；同时遗漏电池、传闻、贴纸和West未知事项，
出现错误有效期、重复事实、将当前成员变化泛化成永久规则，以及未更新或错误的新依赖。
普通局部也有更新遗漏和历史纠错限定缺失。原文补答不能等同于状态成功。

已读完48份完整答案和两臂全部到达后状态/变化。逐项记录分别在
`data/manifests/innovation-v4-paired-v2-plain-review.json` 与 `innovation-v4-paired-v2-delta-review.json`；
它们是作者审阅，完整结构化来源绑定/UJS审计仍待完成，不伪装为独立盲评。
同时发现两处**两臂共用**的作者问题：周末窗口却询问周四/周五，以及把目录不依赖通风误当成目录当前在线。
冻结题目、参考和首次Judge标签保持原样，冲突另列；不能只依据参考把来源忠实的回答判成方法失败。

预测与首次Judge合计144生成响应/615,686tokens，124embedding响应/6,314tokens；原连续账本差额均0、
新增unknown0，历史unknown9/1不变。总额含48次首次Judge，其126,299tokens单列，不混入预测成本。
按六条链配对的首次Correct率差为+8.33个百分点，穷举经验聚类bootstrap区间[0,16.67]个百分点；
仅为探索性结果，含invalid和上述参考问题，不能冒充非劣确认、来源正确性或普适排名。

[完整汇总](../data/manifests/innovation-v4-paired-v2-summary.json)由
`tools/summarize_innovation_pair.py`读取原始结果和回执生成；记录模型、阶段墙钟及账本差额，货币费用未知。
[结果图](figures/innovation-v4-paired-v2.svg)由`tools/plot_innovation_pair.py`从同一汇总生成；
不把共享服务上的CLI墙钟宣称为纯GPU加速。

## B：按需局部结构与真实复用队列

`methods/query_structure.py`已接入共同Benchmark证据包/Reader，复用同一Store中的单个有限缓存。
`query_structure_policy=rebuild|version_cache|incremental`分别为每次重建、来源版本缓存与局部增量刷新。
缓存保存来源绑定的事实/规则，不保存最终答案；新来源即使不在旧支持或当前检索结果内，也进入同一解释步骤。
检索范围变化会重开新选中的旧来源；查询时间变化后Reader重新解释原规则。读取检查当前来源可见性，
遗忘来源会隐藏缓存解释。无缓存对照仅保存到达游标，丢弃解释正文。

这一首版仍全量枚举可见来源，记录可见数量和实际elapsed_ms，隐藏行扫描数未知，不能宣称所有计算已局部化。
缓存复用目前依据检索来源范围及新到达事件；模型声明的语义scope并非已验证的覆盖保证。
首次真实重建只构造了日间范围，未包含同一来源中的全部夜间/电池信息；后续需评价跨问题复用的真实适用范围，
不能用Reader原文补答替它证明覆盖正确。

新`milai-innovation-query-reuse-v1.jsonl`为1条作者链：3次实际来源到达、4个查询检查点、每点4种问题。
5月8日只有查询没有新来源，跨越未来生效边界；之后加入凭据/培训变化和独立电池搬动。
五个配置为`configs/milai-innovation-query-{source,rebuild,version_cache,incremental,full}-v1.json`。
与完整维护对照共享来源和最终Reader；16道题不当作16个独立历史。

首轮`query-reuse-v1`冻结`73116958`，driver `2991155` / 会话`63952`已FAILED并原样保留。
原文预测16答闭合，另从同一冻结源码完成首次评分：13Correct、3invalid、0missing。
重建条件保存9答/9个解释；第10次解释在`halumem/innovation-query-pine/2/qa/1`收到确认length响应，
输入1,048、输出8,192、总9,240tokens，导致整个预测阶段停止。其余条件原轮未运行。
首轮35生成/120,165tokens、0embedding与原账本一致，新增unknown0；原文首次评分另列。
详见`data/manifests/innovation-v4-query-first-v1-summary.json`。

`f07e830d`仅把新只读结构阶段接入已有确认响应/容量处理：失败保留，已有原文继续交给共同Reader，
扣除已消耗的调用名额；不消费未知响应、不盲重试，不放宽写入或来源权限。
新的`query-reuse-v2`从真实失败库和19份已确认响应建立独立目录，保留原terminal作prior记录，
缓存读取已知length后新增普通Reader，已观察到`incomplete_raw_only`与继续保存答案。
旧9答、10解释响应不重生成、不重复计费；这不是同版本冷启动成功，完整条件成本仍包括先前失败。

继续队列冻结`c7c5c469`，会话`58505`、driver `3145177`、rebuild worker `3145185`最近均实查存活。
在原文首次评分实际退出后启动；随后串行运行尚未开始的version_cache/incremental/full及各自首次评分。
实际进程和回执优先于静态记录，不能因观察超时重启。

D2最初10项新SQLite/正常Benchmark测试与20项既有证据读取测试通过；
加入已确认结构length后的原文继续读取、差分关系的多来源支持后，最终36项相关检查通过；
包括新来源未被检索到、已检索到的新来源、时间边界、范围变化、遗忘、规则单独刷新、缓存命中仅需一次Reader，
以及原规则与新事件同时绑定的真实SQLite提交。`1e7a0cf0`补充关系also证据入口，属于后续源码；
未回填已闭合A结果或正在执行的冻结B源码。
四个相关源码mypy、Ruff、包DAG、工具边界及279源验证矩阵通过。真实模型队列仍在验证，代码通过不算方法胜出。

## 匹配学习与资源

`tools/prepare_innovation_training.py` 从审阅引用导出普通操作、转换质量、关系后果和紧凑差分四种目标。
`data/fixtures/milai-innovation-matched-training-v2.jsonl`现有 **8 个样例、6条来源链**：
保留原形成样例，新增七个基于实际持久writer mapping/实际before的转换参考，包括支持路线重设、未知、
未来生效分开保存、历史纠错、避免成员数泛化/重复、独立未知事项与遗漏的贴纸。
没有手填理想before，没有把参考写入实验库，也不把修正标签当模型成功。全部已暴露，只用于开发。

已验证紧凑目标与现有操作schema可编译；四种目标导出到`artifacts/innovation-v4/matched-training-v2`。
当前仅1个样例具备显式后果标签，数据覆盖远未完成，参数更新仍为0。
实验中新增教师HTTP调用0；参考作者/审阅工作未由实验账本单独计量，**不是零成本**。

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

1. D0/D1：补齐结构化来源绑定与目标/非目标/范围时间联合审计；同真实 before 三方法诊断；
   相同示例的旧动作/新差分对照；短/充分输出匹配对比；保持失败而非择优重试。
2. D2：完成当前五条件真实对照及适用范围审阅，继续语义scope/覆盖决策、复用1/4/16和更新密度比较；
   不用原文补答或相同来源版本冒充跨问题缓存正确。
3. D3：同候选池增量证据价值、停止/补读和真实子集交付，先接原文；范围聚合单列。
4. D4：来源可审阅的匹配转换数据、实际参数训练、不同目标且相同预算、未见实体/范围/事件顺序评价。
5. D5：独立开发历史、长历史规模与质量—成本曲线、官方外部数据、第二模型、有效机制消融、
   按链配对统计和区间、适当的独立盲审与稳定性重复；选择规则和正式划分在看结果前固定。
6. D6：有机制收益的同一配方进入普通 Host 并完成真实端到端例子；不复制第二套算法。
7. 对每个继续推进的候选交付可运行配置、真实示例、配对结果与完整成本、支持/否定/下一步结论，
   再按 v4 全文逐项审计。三条路线不要求全部获胜，负结果允许改变或放弃旧架构。
