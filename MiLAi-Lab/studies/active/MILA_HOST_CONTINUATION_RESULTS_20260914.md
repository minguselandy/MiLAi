---
goal_id: MILA-HOST-CONTINUATION-DEV-02
goal_version: "1.1"
status: DEVELOPMENT_COMPLETE_LOCAL_HYPOTHESIS_ONLY
experiment_kind: RESEARCH_PROTOTYPE
independent_lineages: 1
new_model_generations: 10
new_known_raw_tokens: 56547
prior_restricted_generations: 6
prior_restricted_raw_tokens: 24196
---

# 续接形成政策：正常上下文开发结果

本轮依照更新后的 [Goal v1.1](MILA_HOST_WORKSPACE_续接材料形成与使用_后续GOAL_v1.0_20260914.md)完成正常上下文三臂和唯一一次解释/形成诊断。**保留普通 NOTE/REVIEW 参照；范围保持 S 尚无足够优势。通用测量解释提醒在一条轨迹中改善了事务退出定位，可保留为可替换的局部开发假设，不能成为默认能力或短稿独立收益结论。** 本轮开发交付已完成，不再追加第三包。完整4434项清单经实际终态核对：4433 PASS、1项可选依赖SKIP、零失败/错误；其他规定工程检查及构建通过。开发完成不等于稳定政策收益成立。

## 1. 从 v1.0 受限条件转到 v1.1 正常上下文

用户更新前，v1.0 指令下的三臂已完整结束，6 次生成、24,196 tokens，无未知用量；K=1、input16384、交付512硬门及新消费者仅自动接收交付/新观察的原条件均保留。[原运行](/cra/memory/mx_memory/evidence/workspace-host/continuation-20260914/comparison-1-v1/run-header.json)有原始代码/政策快照，不能充当新版主比较，也不算第二来源。

当时 N/R 稿保留了旧批事务退出数值，S 稿漏掉这一定位并将 B1 未观测GC写成无重叠；消费者 N 忽略 B3 长尾，R 用 B3 正常退出反向排除 B2 原因，S 只综合 B3。三稿均低于512，无超长拒收，不能说放宽长度解释了这些错误或此前空工作记录。随后拟做的受限固定稿消费对照尚未发送请求，因用户更新取消；未执行的 v2 草稿单独留在新证据目录，不冒充完成比较。

v1.1 首先改为可用上下文优先。只改 [邻近入口](../../tools/run_workspace_continuation.py)及其测试/政策，旧 A runner、Host 核心和 Provider 的已报告默认行为未改。新入口：

- 前段同时发布原 B1/B2，后段发布原 B3；时点不由答对与否、关键词或工作记录决定。每段最多4次正常决策，stage_answer结束前段，final必须由后段实际生成。
- `COMMON_CONTEXT` 保留全部合法原材料、普通动作/回执及回答历史，有限K不参与筛选。后段只换形成提示为同一 NOTE，历史、任务、定义和共同可选工作区继续保留。
- stage_answer 原文在原 assistant 动作位置加 `HOST_CAPTURED_STAGE_OUTPUT` 标识，只出现一次；没有额外复制到置顶消息或工作区。交付被声明为可错数据，不提升为 system 权威。长度是软建议，没有独立512门限；空稿与缺失/服务截断分别记录，不自动修稿或补生成。
- H句柄按需返回前段可见动作与真实回执，原始材料仍由E/G读取。H不自动展开，避免重复加权交付；它不是可选focus句柄。没有新的业务工具、代码执行或任意路径读取。

现有 Provider 在执行时核验 **C_effective=65536**。共同 `O_reserve=4096`、`M_guard=0`，Host输入上限实际配置为61440；真实 tokenizer、聊天模板及generation prompt都已计入P_actual，不重复扣余量。所有发送均核对 `P_actual + 4096 <= 65536`，本轮实际输入3976–6535 tokens，未人为填满窗口。原先16k/8k门限不再是新入口的输入限额。

独立工作区机械容量显式为2048 tokens/focus32，输出还保留共同动作/外壳空间；三臂均可更新，COMMON正文不由focus筛掉。真实10次均未写work_update，不能将交付称为自主持久Note或工作区机制消费。最多一请求在途，单请求60秒、整条两段900秒、任务工具CPU10秒；4k输出比实际236–444-token交付留有充足空间，最终响应亦未截断。两段不重置已花墙钟。

## 2. 实际比较与错误发生位置

主比较使用同一已暴露A lineage、相同材料原字节与来源映射、共同容量/权限/续接规则。N/R/S 的差异仅在[形成政策](../../configs/policies/workspace/continuation-formation.json)，后段系统政策相同。实际每臂均用一次stage_answer及一次final完成；读源、计算、提议检查工具均未实际调用，重复读源成本为0。正文已直接提供，这不是工具不可用的证据。

| 正常上下文主比较 | 交付 tokens | 形成+消费 raw tokens | 形成时（E1/E2/G2在场） | 消费时（五份原文及普通历史在场） |
| --- | ---: | ---: | --- | --- |
| N | 415 | 4,424 + 7,149 = 11,573 | 漏掉164/310ms事务退出，将约1.5–1.9ms残差当重要/外于事务的成本；GC归因超出观察 | 找到B3约42ms前区间，但R12 application错引成R11的3.5ms；将测量前区间说成arrival至handler，随后认定调度原因 |
| R | 279 | 4,293 + 6,705 = 10,998 | 把hold-enter-exit残差说成退出后到释放；把1.53/1.93ms普通样本叫近零，漏掉实际主耗时 | 将42.4ms before_handler说成handler内pre-runtime；这是对当前可见新证据的误读，不能叫遗忘 |
| S | 236 | 4,283 + 6,739 = 11,022 | 保留旧批hold/application量级，残差称minor较合理；但仍漏掉给出的exit组件，GC范围含混，百分比有小误差 | 分开旧批hold与B3 pre-handler较好；仍未细化旧批exit，把前区间等同arrival/dispatch到handler，原因未证实 |

三份稿实际不同，但主比较中**三臂都未抓住旧批已测出的事务退出主耗时**。因此选择唯一第二包：在同样完整原材料可见时，比较原样R与R加[通用测量解释提醒](../../configs/policies/workspace/continuation-interpretation.json)。提醒只涉及分量与总体量级、区间端点、残差不等于特定活动、缺失不等于零；不含A字段名、数值、未来观察、案例标识或理想交付。它是解释/形成诊断，不是持续记忆固着或短稿消费拆解。

v4只增加可信政策文件/运行顺序参数，正常上下文默认语义保持；第二包R→EXPLAIN，各自从头形成，再由共同NOTE消费，最多16次、实际4次。没有复用稿，因此两条形成成本均真实发生并计费。

| 唯一追加 | 交付 tokens | 形成+消费 raw tokens | 观察 |
| --- | ---: | ---: | --- |
| R（原政策） | 359 | 4,375 + 6,954 = 11,329 | 仍只定位hold并误读残差；final以B3“真正模式”为由将旧批DB定位笼统推翻，扩大GC零/小重叠的适用范围 |
| EXPLAIN | 444 | 4,544 + 7,081 = 11,625 | 稿中明确R12 exit164.426/hold166.204、R22 exit309.995/hold312.028；final保留这些定位并加入B3约42.4ms前区间。仍把旧批application说成fast，将pre-handler过推为dispatch/scheduling，并泛化GC结论 |

第二包EXPLAIN较R多296 raw tokens，出现有用的局部定位改善；这不证明稳定净收益。两次R形成请求的**实际wire字节完全相同**，但响应不同，尽管temperature=0、seed=213；该变异已保留，未重跑到理想输出，也不据此诊断共享服务或声称单对照足以证明提示因果。首批N/R/S失败与追加成功全部并列。

### 消费分析子集

按前段内容是否正确且实际呈现来选子项，不按final输赢挑分母：

- **旧批exit精确定位**：主比较N/R/S及追加R均因前段没有正确给出而排除；只有EXPLAIN进入此子集，后段保留了这些数值与对应对象。这里只有1条，不构成统计结论。
- **旧批hold/application数值**：主比较S正确保留约166.2/166.6与312.0/312.5，final仍保留量级；其精确百分比并不全准，数值续接通过不等于整稿正确。N/R的定位解释有误，不拿其整稿当正确前提。
- **局部数值而非整条解释**：主比较R的173/320ms请求耗时、1.56/1.79ms残差，以及N的R22 GC约0.3ms可单独核对；对应含义/因果未因此成立。正文在场时的新错引与范围过推单列。
- **B3新观察**：前段尚未发布，不进入“前段正确信息”的分母；所有后段错误都发生在E3/G3实际可见时。

原始证据支持的边界是：R12/R22退出164.426/309.995ms；hold-enter-exit差值可能包含事务主体，不能据此称为事务外/连接释放。R32 client51.367854ms、handler7.012ms，前区间42.393870ms、后区间1.962101ms；前区间从MCP client事件start开始，不是arrival dispatch，也不是handler内到runtime开始。B1 GC未观测；B2/B3 GC仅覆盖命名客户端及窗口。源时点有clock binding不等于排除一切测量问题。可直接核对[任务原材料](/cra/memory/mx_memory/evidence/workspace-host/task-a-v2/visible/task.json)及[批1原行映射](/cra/memory/mx_memory/evidence/workspace-host/task-a-v2/offline/source-map-1.json)、[批2原行映射](/cra/memory/mx_memory/evidence/workspace-host/task-a-v2/offline/source-map-2.json)、[批3原行映射](/cra/memory/mx_memory/evidence/workspace-host/task-a-v2/offline/source-map-3.json)。

这些是主开发者对原始记录的开发标注，不是独立human gold；无模型Judge。假设/有用检查不自动算采信或已执行，也不因没有重复声明audit等约束就判失败。所有轨迹的调度终态均COMPLETE，**没有一条因此被宣布全任务语义正确**。

## 3. 证据、版本与全部成本

[源数值计算核对](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/source-arithmetic.json)与[机械核对摘要](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/audited-experiments.json)核验了原材料manifest及其源文件hash、代码快照、实际HTTP body、当地真实tokenizer/服务tokenize/usage一致性、正文实际出现及交付原文对应。10次新请求全部已结算，pending/violation为空。每个后段都有E1/E2/G2/E3/G3各一份原文，交付原文在对应原历史位置一次；形成政策未进入共同消费者系统提示。上限大或依赖列表都没有被用作全文呈现的替代证据。

| 账本 | 生成 | 输入 tokens | 输出 tokens | raw tokens | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| v1.1 主比较 | 6 | 31,177 | 2,416 | 33,593 | 正常上下文N/R/S，3/3完整 |
| v1.1 唯一解释诊断 | 4 | 21,037 | 1,917 | 22,954 | 正常上下文R/EXPLAIN，2/2完整 |
| v1.1 合计 | **10** | **52,214** | **4,333** | **56,547** | 新52上限内，调试生成0，余42不再使用 |
| 更新前v1.0受限条件 | 6 | 22,025 | 2,171 | 24,196 | 独立历史条件，不并入新版质量分母 |
| 两版续接工作实际总账 | **16** | **74,239** | **6,504** | **80,743** | 仅成本加总，不合并胜率/来源数 |

v1.1有3次身份GET（容量预核验1次、两个包各1次）、10次tokenize POST、10次生成POST；容量/接线CPU模拟不算模型。v1.0身份/tokenize/生成另列为1/6/6。没有新调试生成、未知用量或真实输出截断。真实调用前的CPU开发模拟曾因未创建arm日志目录而失败，已修复并经邻近测试；不计为模型或Memory失败。

形成与消费每次成本均保留，不把回顾性引用当免费形成。新包真实输出上限4096，实际使用按usage；tokenizer初始化、总墙钟及各工具CPU/墙钟见结构化摘要，包含正常两段过程。持续落盘不另声称零成本，持久化成本未细分；钱价/缓存折扣未知，不宣称稳定加速。主agent用量由平台另记，无新协作者/Judge，不混入实验tokens。更早managed 51次/234,134与COMMON 10次/44,209仍是各自旧报告账目。

复现正常主比较可用以下入口；已有证据无需重跑，执行新目录会消耗新请求：

```bash
uv run python tools/run_workspace_continuation.py \
  --package /cra/memory/mx_memory/evidence/workspace-host/task-a-v2 \
  --root /absolute/path/outside-lab/new-run
```

解释诊断另加 `--formation-policies configs/policies/workspace/continuation-interpretation.json --order R EXPLAIN`。每包header在发送前登记实际政策、来源、容量、上限和代码版本。原v1、正常v3、诊断v4不拼接前缀/结尾，不合并质量统计。

## 4. 工程终态与取舍

- 最终实现邻近及受影响测试 **70 PASS，4.66秒**，含超过512的合法交付与超过16k的真实tokenizer输入、实际容量越界停止、K不起筛选作用、历史/新观察/交付唯一呈现、可选更新共同保留、读源及失败生命周期。[日志](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/neighbors-final.log)。
- boundary、ruff `src tests tools`、mypy `src/milai_lab`（40文件）及sdist/wheel build均PASS。[构建日志](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/build.log)。
- 完整回归固定 **4434项**，分为scoped模块3项和其余4431项；各7200秒预算、最多2个CPU进程，沿用已验证的关闭可选faulthandler计时器方式。两片均exit 0：其余片4430 PASS/1 SKIP，1672.60秒；scoped片3 PASS，2821.94秒。合计 **4433 PASS、1 SKIP、0 FAIL、0 ERROR**；跳过原因仅为可选Host SDK wheel未安装，另有44项既有pytest警告（含record_property/JUnit格式警告）。每项收集、执行阶段与JUnit名称核对4434项，无遗漏、重复或意外项，运行期间源码hash未变。[覆盖终态](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/regression-coverage.json)、[其余片JUnit](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/remaining-suite.xml)、[scoped片JUnit](/cra/memory/mx_memory/evidence/workspace-host/continuation-natural-20260914/scoped-integration.xml)。本轮没有重启分片或重新出现exit139；旧异常及其根因未确定状态原样保留。

保留可用上下文优先的opt-in研究入口，以及普通NOTE/REVIEW参照。暂停范围保持S的优胜/必要性主张。EXPLAIN仅保留为可替换、可检验的局部解释提示假设；本轮没有可靠净价值或短稿单独贡献证明，不能默认集成产品。

第二包已回答新增的形成解释问题，不再缩窗口找阳性。当前只有A一个已暴露lineage；B不恢复、跨来源验证未完成。独立来源/查新、冻结确认、公开持久化/冷恢复及产品集成均未执行，属于需另有充分信号和范围的条件性后继；本轮普通历史续接不等于真实冷恢复，也不声称概念新颖。


## 5. 完成要求核对

| Goal v1.1要求 | 终态证据 |
| --- | --- |
| 真实容量与完整历史入口 | 实时容量65536，Host61440/output4096；真实请求五份正文及普通历史在场；超过16k输入与600-token交付CPU检查PASS |
| 正常上下文完整三臂 | v3 N/R/S均实际形成和final；6次完整账目，旧受限条件未混用 |
| 唯一第二包或不启动理由 | 三臂形成均漏exit触发解释诊断；v4 R/EXPLAIN均完整，4次含全部形成成本；无第三包 |
| 形成/传递/消费与全任务边界 | 原始字段、数值计算、请求/交付逐项核对；正确形成子集与排除理由明确；不以部分数值称全任务正确 |
| 全部尝试和费用 | v1.1 10次/56547；旧受限6次/24196单列；无未知用量；CPU模拟、HTTP身份/tokenize、agent与实验成本分账 |
| 当前工程交付 | 70邻近PASS，4434项完整覆盖，boundary/ruff/mypy/build PASS；旧失败及规划保留，当前索引同步 |
| 有依据的取舍及范围 | 保留简单参照和局部解释假设；S优势/短稿独立贡献未证实；单来源、无冷恢复/产品默认改变 |
