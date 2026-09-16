# MiLAi v0.2 通用记忆流程执行记录

状态：`COMPLETED_KEEP_BASELINE / G0–G4 complete / selected A0`。
目标为 Product 的 [MILA-V02-01](../../../MiLAi-Product/docs/goals/MILA_V02_通用Agent记忆_可用性优先增量开发与实验_GOAL_20260905.md)，完整范围仍为 G0–G4。
本研究不访问 Formal 500，不续跑 Product-11，不变更公网服务。

## 执行起点与配置

- 专用锁：`data/locks/v02-memory-flow-product.lock.json`。校验通过：Product tree
  `d93bef8bfdf846963dabddf5635ba254dea7442d42e0eee3dcebb3ae87d9199d`，lock digest
  `5869a678201fbe1babb00c5fdcc0a305e7c50ce02b15887b3023c84c99c98ddd`。
- 独立实例：`artifacts/v02-memory-flow/v02-g0g1-20260905a/`；独立 Compose project、
  随机 loopback 端口、独立数据库和 blob root。未使用 Product 全局 local-runtime supervisor，
  因其状态文件属于共享运行路径。实际运行 API/worker 使用本研究 env，PID 与环境路径可复核。
- Runtime、MCP、hooks 的安装模块解析到被锁定 Product `src/`；具体解释器与模块路径
  保存于 `installed-artifact.json`。每次产品效果运行先复核 pin。
- 后续最小产品修复只改善 Working State 错误反馈，当前 tree
  `7fdf4f12d8c9ef63a9662145f6a1abb2e053fce2860e60ddcde8eeabcaf1fc0c`、lock digest
  `63b35d33b59928683f21283e37b66034a068ba7e9b5d95c97c662de1535705ec`。
  旧锁另存 `data/locks/v02-memory-flow-product-d93bef8b.lock.json`；旧 server 文件和 manifest
  存于本研究 artifact `pre-error-feedback-product/`，已发生的运行继续绑定旧身份。
  新 MCP 已通过原隔离数据库的实际拒绝探针；原 API/worker 对应 Runtime 源文件未变，
  公网服务未更新。没有迁移、权限、Canonical 或 CAS 语义变更；回退只需恢复旧 MCP 文件/包。
- 入口：`uv run python tools/run_v02_memory_flow.py`；公共 `milai-ops init`、Alembic、
  API/worker、`milai-hook AgentEvent`、`milai-codex-full-mcp`、`milai codex`。
  实验复用现有 Lab lifecycle runner 的命令与捕获辅助函数，未导入 Product 私有实现。
- Host：实际本机 Codex CLI 0.153.0、`gpt-6-astra`、`high`、`default` tier；
  由 Docker 执行同一静态二进制。新会话、新 home、无历史对话、关闭 Skills/plugins/apps/multi-agent。
  这些受控实验配置同时用于 A0/A1，不代表用户的全部个人插件配置。
- 预算在第一次模型运行前写入 `configs/v02-memory-flow.json`：240 秒/会话，24 次工具调用
  watchdog，rollout 120000 token tracking；每批最多6会话、1440秒。watchdog 可能有正在执行的
  调用，rollout tracking 不是单次 API 硬 token 上限。未知用量保持 null。
  CLI 对 reminder 配置的本地要求已用不调用模型的 `debug models --bundled` 检查。

## A0 与干预

A0 完整保留 Product launcher 的 prefetch/revalidation、MCP server instructions、工具目录、
checkpoint gate 和合法文件/搜索能力。真实 bootstrap、配置和 MCP 目录按会话导出，
不是删减版“无记忆”对照。A1 只在用户请求后附加 Goal 指定的一次统一条件回查文本。
G3a 的 H1 另有预定通用机会文本，已完成3对，不与 G2 混算。

原始外显记录在 Git 外 artifact；只导出初始 prompt 装配、工具调用与返回、外显回答及成本，
不收集私有思维链。后续逐请求输入在尚未取得直接观测时标 `UNOBSERVED`，工具返回全文
不直接算作“关键内容已经进入模型上下文”。

来源限定为构造、允许保留的项目材料，包括合法干扰文本。Agent 容器只挂载本会话 home、
workspace、只读 sources、运行二进制及公共 CA 证书；不挂载标签、Lab、Product 或历史 artifact。
MCP 按分支项目范围读取。`governance emulated by sealed allowed-source set`；不做动态权限
变化，不宣称撤销后派生内容传播已验证。网络沿用 Host 代理，非生产网络隔离试验。

## G1 预定案例与评分

| 案例 | 起点 | 预定当前交付与关键条款 | 后续任务 | 保存评价 |
|---|---|---|---|---|
| g1-software | 支付 POST 超时三次重试的过时记忆 | 调用伪代码；不自动重复支付，超时结果未知；保留10秒与日志隐藏卡号 | 验收测试设计 | 修订有后续价值，检查真实保存及重新装配 |
| g1-research | 正确且充分的简报记忆 | 18%归属论文作者、40构造查询、团队未复现、不可推广生产 | 团队会议议程 | 无新增信息时不保存可以合理；若保存则检查原正确内容 |

两例为明确构造的 development，不能作为新家族验证。标签位于 fixture 的 evaluation 字段，
不会复制到 Host。首次相关判断按首次向用户交付的实质判断或执行的任务产物，最终答案另报。
逐例由本线程Agent语义复核任务条款、来源归属和 State 差异；不依赖严格字符串匹配。
未进行独立人类复核，因此标签来源明确为Agent review。无判断与超时保留。
后续预先指定两例；实际更新子集才做 U/V，所有预定后续仍报告。

## 失败与修复

| 运行 | 最早可确认位置 | 事实 | 改进与下一验证 |
|---|---|---|---|
| g1-software-a1 | Codex 配置解析 | Host prefetch ACTIVE V1；要求 rollout reminder；无模型用量，State V1不变 | 补 `reminder_at_remaining_tokens=[60000,10000]`；bundled catalog 非模型检查通过 |
| g1-software-a1-r1 | 初始输入导出超时 | Host prefetch ACTIVE V1；45秒导出超时；无模型执行或保存证据 | 容器补继承已有代理及CA证书，增加诊断容器超时清理；新运行 r2 验证 |
| g1-software-a1-r2 | 容器工具/元数据装配 | 缺少rg，Agent用合法文件工具替代；model catalog refresh失败后采用fallback metadata；仍真实提交V2 | 为后续配置补本机rg及模型catalog；该例只作开发闭环，不和新配置作A0/A1效果配对 |
| g1-research-a0 | 完整模型的code-mode入口 | 缺少code-mode-host，工具不可用；Agent仍用已有正确记忆答对，未保存 | 挂载完整Codex bin；r1工具可用并通过；本行保留为执行偏离，不纳入有效控制比较 |
| g0-public-boundary-probe | Lab错误记录 | MCP错误文本不是JSON，诊断解析失败 | 先保留raw MCP error；Lab正常化器保留isError，不再误解析 |
| g0-public-boundary-probe-r1 | 产品错误反馈 | 过期版本与跨项目引用均被拒绝，V2不变；但两者公开错误文案相同 | MCP输出已知错误码和固定恢复建议，不输出后端details、不自动重试；r2真实PostgreSQL复验通过 |

在线 [Codex 配置参考](https://learn.chatgpt.com/docs/config-file/config-reference) 确认 rollout
tracking 是开发中功能；具体字段以本机 CLI 检查为准。r1 的网络原因属于待复验诊断，不能仅凭
“缺少配置”就确定唯一根因。旧失败记录不覆盖，不计为语义失误或策略负面结果。

## G0/G1 与首对重访结果

以下均为真实 Codex，输入/输出 token 使用 CLI 的实际 usage；缓存命中是输入子集，不重复相加。
墙钟包含 Host启动、输入导出、模型调用与工具执行；来源捕获和索引准备另存各会话
`source-preparation.json`。无模型usage的启动失败为未知，不填零。

| Session（artifact中同名目录） | 工程/语义结果 | State | 完成工具调用 | 输入/输出token | 秒 |
|---|---|---|---:|---:|---:|
| g1-software-a1 | 模型启动前配置失败 | 1→1 | 0 | 未知 | 3.2 |
| g1-software-a1-r1 | 模型启动前输入导出超时 | 1→1 | 0 | 未知 | 47.9 |
| g1-software-a1-r2 | 真实纠正、设计与提交；fallback metadata开发条件 | 1→2 | 4 | 85961 / 1689 | 132.1 |
| g1-research-a0 | code-mode不可用；已有记忆下答对，但执行偏离 | 1→1 | 0 | 37191 / 546 | 65.3 |
| g1-research-a0-r1 | 完整Host控制例：正确、未重复保存 | 1→1 | 4 | 33242 / 447 | 91.6 |
| g1-software-resume | 同task直接恢复原V2，正确设计验收测试 | 2→2 | 4 | 42010 / 1526 | 96.5 |
| g1-research-resume | 同task恢复V1，正确准备会议议程 | 1→1 | 3 | 37579 / 658 | 65.4 |
| g3b-software-u | 隔离分支初始化旧内容；查源后测试设计正确 | 1→1 | 4 | 37443 / 1270 | 92.0 |
| g3b-software-v | 隔离分支初始化实际保存内容；测试设计正确 | 1→1 | 3 | 41952 / 1505 | 96.3 |

本线程Agent语义复核依据为 fixture原始合同与外显回答/State：软件例当前与三个后续输出均未自动
重试支付，保留10秒、结果未知/人工核对和日志隐藏卡号；完整控制例及研究后续均准确保留
作者归属、40例、18%、团队未复现和不可外推。修订State新增的保守设计被明确标为建议，
没有冒充接口合同；原正确内容未发现丢失。`decision_changed`保持未知：没有模型在查源前
交付错误设计的证据，不能把旧记忆错误直接当作模型先前判断。

全部9次分配均保留：2次模型前失败、1次工具不可用偏离、1次fallback metadata下成功开发
修订、5次完整Host运行。工程偏离不从总成本里删除，也不伪装为策略语义失误。
两个预定G1后续均完成，原修订例保存1/1、正确控制例合理未保存1/1；原链无保存失败、
无已观察错误复发/负面迁移。小样本不构成可靠性声明。

U/V在两分支执行前固定为U→V，见 `uv-first-pair-plan.json`；代码、wrapper、配置摘要完全
一致，均为新home/新task/新State，外部产物均为空workspace加同一来源集合。V的分支版本1
来自原成功版本2的内容快照，不伪造版本号或回退共享head。来源ID映射留在分支记录。
U/V均4项合同正确，无已观察连带损坏；V少1次工具调用，但输入加输出token为43457，
U为38713（V多12.3%），墙钟V多约4.3秒。当前没有净收益证据；不能把恢复成功本身算收益。
该结果只适用于1个真实更新子集，G2新增预定后续仍须另作观察。

G0边界证据：运行中容器实际看不到标签、source mount只读，见 `g0-filesystem-probe.json`；
公共MCP跨项目来源和旧版本拒绝后原V2不变，修复后能区分错误码，见
`g0-public-boundary-probe-r2/result.json`。不外推动态权限撤销与派生记忆披露安全。
模型catalog刷新仍偶发超时，已加载本机缓存元数据且不再报fallback；开销计入墙钟。

当前已完成检查：Lab boundary、Ruff、mypy（30源文件）、pytest **119 passed**、build通过；
MCP Ruff、mypy（12源文件）、pytest **160 passed, 1 skipped**、build通过。skip为需显式开启
`MILAI_MCP_BASELINE_E2E=1`的独立完整lifecycle实验；本次用真实隔离PostgreSQL定向验证了
受影响的拒绝路径，没有重跑无关Runtime全套。没有新数据库迁移。

## 后续完整工作

G2已在任何pilot模型运行前写入 [预注册计划](MILA_V02_MEMORY_FLOW_G2_PLAN.json)：8个新构造
任务覆盖两领域×四种起点，分4批各2对；每对保留原完整A0，只附加一次统一请求构成A1。
顺序一次随机生成并保存，fixture和配置哈希冻结。候选需至少1个净首次判断/任务进展胜例、
无连带损坏，且总体及充分记忆控制的中位token成本比不超过1.5；无增益则保留A0。
这是当前pilot的取舍规则，不是统计显著性标准。首对为库存上传摘要遗漏，A1→A0；
后续6个预定持续任务全部纳入保存选择评价。当时尚未创建G4新家族；后续按配置冻结顺序进入。

G2首对 `g2-p1` 已完成，外显伪代码与State经本线程Agent按预定合同复核：两侧均正确给出
200/200/50、最大200、保序与保留重复记录。A1为V1→V2，A0为V1→V1；A1补全遗漏并保存，
但本轮任务正确性没有净增益。A1输入81717/输出1338 token、86.4秒；A0输入36937/输出570
token、63.5秒。两侧均保留原正确内容，下一阶段须检验保存选择的后续价值。
其余7对现已按冻结计划串行执行完成；无缺失、超时或失败分配。

G2批量handle `67042`已返回 `G2_ALL_PLANNED_RUNS_TERMINAL`，不可重启该批。各会话
`process.json` 与 `result.json` 分别定位运行进程和终态事实。

## G2结果与取舍

逐对数据见 [紧凑结果](MILA_V02_MEMORY_FLOW_G2_RESULTS.json)，原始结果及本线程Agent语义
复核在各会话 `evaluation.json`。8对的fixture、代码、模型metadata、Product pin、初始payload
均一致，State/project分别隔离；比较的是统一提示策略的总效果。

| 起点 | A0/A1核心条款 | A0/A1保存 | A0/A1输入+输出token | A0/A1秒 |
|---|---|---|---:|---:|
| 软件遗漏 | 4/4、4/4 | 否/是 | 37507 / 83055 | 63.5 / 86.4 |
| 研究正确 | 4/4、4/4 | 否/是 | 82399 / 143071 | 104.0 / 159.0 |
| 软件正确 | 4/4、4/4 | 否/是 | 37717 / 87757 | 62.9 / 96.8 |
| 软件过时 | 4/4、4/4 | 否/是 | 40946 / 84864 | 78.3 / 118.5 |
| 研究遗漏 | 4/4、4/4 | 是/是 | 78701 / 188323 | 131.9 / 152.6 |
| 研究过时 | 4/4、4/4 | 是/是 | 109175 / 163718 | 158.3 / 156.2 |
| 软件一次性展开 | 4/4、4/4 | 否/否 | 37136 / 39331 | 40.7 / 60.1 |
| 研究一次性展开 | 4/4、4/4 | 否/否 | 37387 / 56557 | 49.5 / 60.9 |

16/16的首次相关判断符合预定核心任务条款，A1净胜0；未观察到原正确内容损坏（全部16次，
其中8次实际更新）。A1保存6/8，A0保存2/8；对6个有后续任务的案例，分别为6/6、2/6。
正确记忆的保存主要是新增任务进展，不能算事实纠正，也不能只凭保存次数判为收益或损害。
两类一次性任务均不保存。软件过时A1伪代码在传输异常判断前访问响应状态，具体异常返回
表示未定义；已记录为实现时待核对点，不宣称伪代码已通过可执行客户端验证。

A0总输入+输出460968 token、689.2秒；A1为846676 token、890.5秒。
逐对token比中位数1.904，正确记忆控制中位数2.032；无净胜且超过预定1.5成本比，
因此 **G2_COMPLETED_KEEP_A0**。不继续扩大A1策略，不增加A2或按案例调提示。
保存选择的后续结果在G3b另报，不能从当前对照直接推断。

记录修正：工具成本包含shell、MCP及file_change事件；历史watchdog漏数文件修改，补计后
单次最多9次，仍低于24，所以没有改变任何G2执行条件。后续watchdog已按事件ID去重计入
文件修改。三个A1运行的原始input+output超过名义120k tracking值；跟踪器的加权、缓存及
响应边界计账未被观测，不能视为原始总token硬上限。未追溯改预算或重跑这些结果。
受控wall/tool限制均未触发；来源捕获/投影准备另列，其他初始化细分耗时未完整计量。

关键来源进入后续请求的精确比例保持未知；工具返回、外显使用及任务条款评价分别保留，
不以完整工具输出冒充实际请求输入。以上为构造pilot和Agent复核，不是统计显著性或生产
可靠性结论。Host二进制当前摘要补记于 `host-installation-identity.json`，明确是G2期间观测，
不伪造为运行前digest；先前容器mount绑定同一个0.153.0 release路径。

## G3预定执行

[G3计划](MILA_V02_MEMORY_FLOW_G3_PLAN.json) 在运行前固定：3个同起点A0/H1配对，
H1仅在现有Host developer/bootstrap装配加入一次固定通用机会；用户followup完全相同。
该干预仍是提示强调，不是新增检索能力或无Host时的自然调用。12个原始持续任务来源全部
保留：3个用配对中的A0分支代表后续，其他9个直接恢复原task；额外H1分支单列。
现已接入任务产物延续，只复制原会话真实交付文件，保留模式，排除临时最终回答、sources
和缓存；符号链接拒绝自动带入，防止越过允许集。U/V或Host配对两侧使用相同产物快照。

- [x] G0：完成真实模型启动、预算启用、初始输入可观察性与来源资格检查；后续逐请求输入仍不可观测。
- [x] G1：两例开发使用、选择性提交和新会话恢复；语义、偏离及失败反馈分别记录。
- [x] G2：两领域四类起点8对完成，按预定标准保留A0；失败/损坏/成本及未知项已记录。
- [x] G3a：正常恢复任务3对完成，与条件请求单列；无净胜，保留A0。
- [x] G3b：真实更新的隔离 U/V 重访，加全部12个G2预定后续；未证明保存净收益。
- [x] G4：冻结取舍后4个新家族任务和2个续做完成；使用示例、撤回配置及最终结论已交付。
- [x] 本轮代码检查：Lab boundary/pytest/Ruff/mypy/build及MCP包gates；后续实现变化仍需对应检查。

Product `0.1.0-candidate`；Schema `0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`；
研究机制、自然调用及一般可靠性未证明，创新性 `RQ pending`。

## G3a结果与配置冻结

[逐对结果](MILA_V02_MEMORY_FLOW_G3A_RESULTS.json)记录3对同起点正常续做：软件遗漏、研究正确、
研究过时。两侧全部完成任务，首次实质判断符合来源与followup要求，H1净胜0。没有修改State，
6次均未观察到正确内容损坏。软件边界测试按followup要求评价，不把初始任务的450条例子
强加为本轮必需输出。评价来源为本线程Codex语义复核，不是独立人工评审。

| 续做起点 | A0/H1输入+输出token | A0/H1秒 | A0/H1工具调用 |
|---|---:|---:|---:|
| 软件遗漏 | 37536 / 37574 | 58.5 / 59.1 | 2 / 2 |
| 研究正确 | 38589 / 38622 | 63.1 / 58.5 | 2 / 2 |
| 研究过时 | 41760 / 42060 | 50.3 / 58.1 | 3 / 3 |

H1/A0逐对token比中位数1.001，成本接近，但未达到预定至少1个净胜要求，因此
`G3A_COMPLETED_KEEP_A0`。三对代码、模型metadata、Product pin、初始内容、用户请求和
任务文件hash一致，State/project隔离；H1在初始装配输入恰好出现一次，A0与用户请求中没有。
研究简报的实际文件带入两分支，临时回答与缓存均不带入。后续逐请求输入仍为UNOBSERVED。

已保存[配置冻结记录](MILA_V02_MEMORY_FLOW_SELECTION.json)。随后才创建并登记
[G4计划](MILA_V02_MEMORY_FLOW_G4_PLAN.json)：项目规划和内容写作共4个新构造案例、2个预定
续做，沿用相同A0与预算，无领域专用触发器或答案模板。G3b全部后续结束后串行执行。
这些是策略冻结后的新家族，作者与评价者仍相同，不称为独立盲验证，也不主张表示泛化。

G3执行代码的交付检查已通过：`uv run milai-lab-check-boundary`、`uv run ruff check src tests tools`、
`uv run mypy src/milai_lab`（30文件）、`uv run pytest`（123 passed）、`uv build`。
后续只添加计划、案例和文档，未改冻结运行代码。Product普通启动、两领域续做、失败反馈及
候选撤回说明已补入[现有runbook](../../../MiLAi-Product/docs/runbooks/http-mcp.md#ordinary-task-continuation)。

## G3b全部预定后续

[逐例结果](MILA_V02_MEMORY_FLOW_G3B_RESULTS.json)覆盖G2原始12个持续任务起点：原先保存8个、
未保存4个，原阶段保存失败/结果未知0个。后续全部由正常A0请求续做，12/12完成，未观察到
错误复发、负面迁移或原正确内容损坏。3条使用G3a中的A0隔离快照分支，9条直接使用原task ref；
均清除临时对话/cache并保留真实任务文件。额外3条H1结果单列，不加入12条原任务分母。

| 原任务 | 原A0/原A1后续输入+输出token | 后续秒 | 后续再次保存 |
|---|---:|---:|---|
| 软件遗漏 | 37536 / 40247 | 58.5 / 68.3 | 否/否 |
| 研究正确 | 38589 / 203189 | 63.1 / 129.6 | 否/是 |
| 软件正确 | 38184 / 100155 | 96.8 / 122.3 | 否/是 |
| 软件过时 | 38739 / 83230 | 95.8 / 179.7 | 否/否 |
| 研究遗漏 | 41627 / 43549 | 59.3 / 69.9 | 否/否 |
| 研究过时 | 41760 / 44016 | 50.3 / 74.4 | 否/否 |

两次再次保存均为真实V2→V3：研究正确例更新了已核验的检索状态，软件正确例扩展边界测试设计。
原正确事实保留，没有把设计伪装成已执行实验。研究例的检索状态维护还进入了简报文件；
本轮没有显示这类运行状态维护改善了任务交付。软件过时的两种起点都产出正确异步测试设计；
其中原A1分支写了12例测试文档，仍没有可执行客户端或真实业务测试的结论。

后续共3个失败shell动作：一次`rg`无匹配返回1，两次Python解释器不存在；Agent用现有合法工具
继续完成任务。它们计入调用与耗时，未修改冻结容器来重跑成功样本。名义rollout tracking再次
不能约束原始20万token用量；保留真实值，不扩大“硬预算已验证”的主张。

原A0六条链的“初次+后续”合计622880 token，原A1为1265174 token；后续阶段分别236435、
514386 token和423.9、644.2秒。这是包含不同State和任务产物的策略历史描述，且部分A0后续用
隔离快照，不能当作只改变保存内容的因果比较。真正U/V仍仅覆盖G1一个真实更新：两侧正确，
V少1次工具但token和时间更高。未保存起点也能查源完成，因此目前只证明恢复与选择性保存
路径可运行，没有证明额外保存的净价值。G1的两个预定原链后续另已完成，均保留在总记录。

## G4新家族与最终取舍

[G4结果](MILA_V02_MEMORY_FLOW_G4_RESULTS.json)：冻结A0后新写项目规划、内容写作4个案例，
初次任务4/4和预定续做2/2完成，6次首次实质判断均符合任务与来源。没有观察到连带损坏，
没有State更新；其中两个一次性文稿均未保存。6次初始装配的payload和真实version与GET
记录完全一致，fixture身份、Product pin及冻结代码检查均通过。

| 会话 | 交付 | 输入+输出token | 秒 | 工具调用 |
|---|---|---:|---:|---:|
| g4-1-a0 | 工作坊时段、人数方案文件；每场5+2=7，上限12含工作人员 | 70932 | 143.1 | 5 |
| g4-2-a0 | 开幕依赖计划文件；拟定北厅安排待确认，保留负责人和通知前置条件 | 53307 | 95.7 | 4 |
| g4-3-a0 | 140字导览及事实核对点；12位受访者、原句准确、不代表全体 | 37835 | 66.3 | 2 |
| g4-4-a0 | 三条指示牌；不误写全馆关闭或禁止拍照 | 37102 | 47.7 | 2 |
| g4-1-resume | 新会话给出开场和换场检查；人数、时限、禁止重叠均保留 | 37947 | 63.2 | 2 |
| g4-2-resume | 新会话正确区分可推进、待确认及内部通知草稿安排 | 38074 | 64.7 | 4 |

两个续做都保留原任务文件，文件hash不变。开幕案例修正的是当前交付文件，旧State仍保持
过时内容；新会话再次读源后答对，不能说记忆已自动修复，也不能把任务文件的延续归功于
State保存。新家族仅支持这组受控规划/写作任务的可用性，不构成独立盲验证、表示泛化或
生产可靠性证明。没有因这些结果修改提示或增加领域模板。

终态为 **COMPLETED_KEEP_BASELINE**：真实Host读取、公开CAS保存、错误反馈、新会话恢复
及实际任务文件延续已可用；A1在8对中净胜0且更贵，H1在3对中净胜0，均不默认启用。
保留原完整A0，交付[普通使用说明](../../../MiLAi-Product/docs/runbooks/http-mcp.md#ordinary-task-continuation)。
保存价值、自动维护与更广泛的检索机制收益继续保持未证明；本Goal不要求候选必须获胜。

## 总成本、边界与交付核对

最终原始审计为artifact根目录的 `final-observation-audit.json`。预定/实际分配均46，全部有终态，
没有漏掉或新增未登记会话。44次有实际usage，2次模型启动前失败用量未知；另保留1次工具入口
不可用、1次fallback metadata的开发偏离。其余42次为完整Host运行，不能把这个数量当成功率。
冻结计划中NOT_RUN是登记时状态，最终执行状态以对应RESULTS与本记录为准，未回改预注册历史。

| 执行集合（互不重复） | 分配 | 已知输入+输出token | 在线秒 | 工具动作／其中失败 |
|---|---:|---:|---:|---:|
| G1开发与首对U/V | 9 | 323019（7次有usage） | 690.4 | 22 / 3 |
| G2 | 16 | 1307644 | 1579.7 | 69 / 4 |
| G3a | 6 | 236141 | 347.7 | 14 / 0 |
| G3b直接恢复G2原任务 | 9 | 632936 | 896.1 | 39 / 3 |
| G4初次与后续 | 6 | 275197 | 480.7 | 19 / 0 |

合计已知2774937个输入+输出token、3994.7秒在线墙钟；这是已知用量之和，不把2次未知填零，
也不是账单金额。缓存token是输入子集，未重复加总。33次来源捕获与就绪等待共43.45秒，
33/33 READY，和在线成本单列；其余初始化细分未完整计量。G3a中的三个A0已代表G3b原任务
后续，因此上表没有重复计费。G2的4个失败动作是3次Python命令不可用和1次rg无匹配，均恢复；
不把这些命令退出码隐藏为零，也不等同于整个任务失败。

实际模型MCP调用仅resolve 13次和Working State update 11次；11次更新均观察到head递增
（G1 1次、G2 8次、G3b 2次）。早期4份回执尚无独立save_status字段，依据外显调用和前后head
复核，不能把字段缺失当作未保存。所有分配均无watchdog终止；4次超过名义120k原始token，
因此硬token上限仍未验证。后续逐请求实际输入、关键来源实际呈现比例仍为UNOBSERVED。

| Goal要求 | 最终证据与范围 |
|---|---|
| G0身份、完整A0与真实入口 | 两代专用锁保留；实际安装路径、服务身份、Host导出、封闭来源及真实拒绝探针；原始总token硬上限有明确限制 |
| G1两例闭环与失败修复 | 真实保存/恢复、正确控制；保留启动与工具故障，补通用容器依赖及MCP精确错误反馈 |
| G2条件回查增量 | 两领域四起点8对；正确条款、损坏、保存与成本；按预定规则撤下A1 |
| G3正常使用与保存价值 | 3对Host接入、1对实际保存U/V、全部12个G2预定后续；额外H1和G1后续分别报告 |
| G4新家族及交付 | 先冻结A0，后创建4个新任务和2个续做；普通启动、软件/研究例、候选撤回和失败处理已写入现有runbook |
| Product/Lab与权限边界 | 案例、标签、执行器和评分留Lab；只调用公开接口；无schema、CAS、权限或Canonical语义变更，无公网部署 |
| 验证与未完成研究 | Lab 123 tests及boundary/Ruff/mypy/build；MCP160 passed、1 opt-in skip及静态/build；真实PG拒绝探针；不重跑无关Runtime全套 |

终态检查确认冻结配置/执行器/wrapper/任务文件复制模块/锁均未变，所有G2–G4外显结果已语义
复核；无保留的reasoning事件，实验home内auth副本为0。原始artifact被Git忽略，真实来源均为
允许保存的构造材料；公开环境密钥未写入交付文档。动态撤销传播没有验证，ACTIVE warning
不能当作披露许可。Formal500、D2公开frontier、Product-11封存结果和共享数据未变。

最终只改进MCP错误反馈，不改输入schema、版本事务或authority；无需迁移，恢复旧MCP包可回退。
Product仍为`0.1.0-candidate`，Schema仍为`0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE`，
创新性`RQ pending`。没有把有限可用性验收提升为生产、自然调用或研究机制结论。

最终文档检查：8份交付/索引文档的本地链接目标全部存在，v0.2案例与结果JSON全部有效，
所改tracked文件`git diff --check`通过。最后一次服务身份与Product pin检查通过后，于
2026-09-05 09:03 UTC停止本次API/worker和专属Compose项目；数据库卷与artifact保留，见
`resource-closeout.json`。没有运行中的试验Host容器，也没有停止共享或公网服务。

如需复跑，可从Lab目录创建新的隔离运行身份（需要原有Codex认证、Docker及已安装Product包）：

```bash
uv run python tools/run_v02_memory_flow.py prepare --run-id v02-review-20260905b
uv run python tools/run_v02_memory_flow.py run --run-id v02-review-20260905b --batch-id review-b1 --case data/fixtures/v02-memory-flow/g4-planning-correct.json --session-id planning-a0 --arm A0
```

入口会先校验专用Product pin，不覆盖已存在的运行目录。以上是已打开案例的复跑，不能当作
新的盲验证。实际个人任务使用Product runbook中的正常启动入口，无需实验arm或评分字段。
