---
goal_id: MILA-HOST-CONTINUATION-DEV-03
goal_version: "1.0"
status: DEVELOPMENT_COMPLETE_NO_STABLE_NET_BENEFIT
decision: KEEP_SIMPLE_LOCAL_HANDOFF_CHANNEL_SIGNAL_NO_NET_BENEFIT
experiment_kind: RESEARCH_PROTOTYPE
independent_lineages: 1
model_generations: 12
raw_tokens: 73119
unknown_usage: 0
regression_passed: 4439
regression_optional_skipped: 1
---

# 解释提示复测与交付文本消融：实验结果

执行 [新 Goal](MILA_HOST_INTERPRETATION_AND_HANDOFF_GOAL_20260914.md)，不是补跑已关闭的 v1.1。固定 R/EXPLAIN 提示，完成两波反序形成；每个真实形成终点分叉为 FULL 与 NO_HANDOFF。**普通 R 这次也提到了退出主耗时；EXPLAIN 没有显示足够可靠的独有优势。交付文字可以保留旧定位，也可以延续其中的错误解释，尚无净任务质量收益。保留简单 NOTE/REVIEW，不追加请求。**

实际 12 次生成、73,119 raw tokens、未知用量0；4份交付形成、8个消费尝试，7个合法 final，1个已知动作格式拒绝。所有分配均有终态，但不是8/8业务成功，更不是机制确认。工程全回归4439 PASS、1项既有可选依赖SKIP，4440项覆盖无遗漏；其他检查与构建通过。本轮开发交付完成，未使用的36次上限关闭。

## 1. 这次真正改变了什么

新增 [邻近 runner](../../tools/run_workspace_handoff_ablation.py)与[测试](../../tests/unit/test_workspace_handoff_ablation.py)，复用原 Host、任务、Provider、tokenizer、R/EXPLAIN 及 NOTE 消费政策；旧入口和产品默认不改。

原 `task-a-v2` 的五份原材料及定义全部保留。前段 B1/B2，后段 B3；普通历史、工具能力、目标和输出位置相同。每份交付实际生成一次，再从同一终点复制为两个独立消费者：

- FULL：在普通 assistant 历史位置保留原 stage_answer，一次呈现。
- NO_HANDOFF：只将该 action 的 text 改为明确的实验留空标记；历史 H 读取也返回留空版本。原始证据及交付所在交换的其他消息都不删。

这是受控移除阶段交付的信息通道，不是容量不足下的产品默认裁剪。它测到的可能包含文本长度、重复强调与表述影响，不能单独归因于认知状态。两边可以通过原始资料重新判断；没有强迫 baseline 遗忘，也不要求自主 work_update。

[实际输入核对](</cra/memory/mx_memory/evidence/workspace-host/interpretation-handoff-20260914/input-audit.json>)确认：每个消费请求14条消息、E1/E2/G2/E3/G3原字节各一次；每对首请求只在交付 text 不同，系统提示和其余消息完全相同。四个 NO_HANDOFF 的**完整 HTTP 请求逐字相同**，因此它们是同输入重复，不是保留了四种前段政策的不同消费者。R、EXPLAIN 各自两次形成请求也逐字相同；输出不同，不能把 temperature=0、seed=213 当作完全确定性保证。

实时服务窗口65536，Host输入61440、输出4096；实际输入3983–6518。交付318–426 tokens，无512硬门、K裁剪、截断或容量拒绝。12次均未更新工作区，没有读源/算术/提议工具的实际调用；直接呈现的正文已经在场。公开持久化、冷 Host、真实业务动作世界和第二来源均不属于本次已完成证据。

## 2. 冻结提示的两波复测

次序为 W1：R（FULL→NO_HANDOFF）、EXPLAIN（NO_HANDOFF→FULL）；W2：EXPLAIN（FULL→NO_HANDOFF）、R（NO_HANDOFF→FULL）。没有看结果后换顺序、重试成好答案或补齐失败。

| 形成稿 | 实际保留 | 仍有的问题 |
| --- | --- | --- |
| W1-R，361 tokens | 明确 R12 exit164.426/hold166.204，称 exit 约99%；建议细化退出阶段 | 同时把主要区间称为“transaction exit 到 connection release”；给残差命名固定释放开销；GC外推 |
| W1-EXPLAIN，426 tokens | 明确 R12、R22 exit164.426/309.995 与各自hold关系 | 同样误称退出后到释放；把1.5–1.8ms残差当释放/验证开销，R12未观测GC当零；后续检查偏向小残差 |
| W2-EXPLAIN，414 tokens | 再次保留两请求 exit 与hold数值关系 | 残差解释成释放或网络确认；误写R12 GC为零；建议用RTT解释小残差而不是先细化主要退出耗时 |
| W2-R，318 tokens | 再次用 R12 exit164.4/hold166.2 定位主要分量，保留退出原因未决 | 开头仍把区间称为退出到释放；GC覆盖扩大；没有明确给出R22退出数值 |

数字/字段定位的局部现象重现了，但这次 R 也出现，**不能保留“只有 EXPLAIN 才能定位退出”这个解释**。EXPLAIN在两份稿中更完整地列出两个请求，却没有消除它原本针对的残差命名和覆盖误读。四份都是混合正确/错误的工作产物，不是四份完整正确的旧 Memory。

## 3. 同一交付的保留与留空

| 配对 | FULL 合法交付 | NO_HANDOFF 结果 | 能说明什么 |
| --- | --- | --- | --- |
| W1-R | 用B3笼统推翻旧定位，错误称所有批次DB仅1–4ms、GC为零 | 主要只说B3；未保留旧退出定位，也把GC全称零 | 该稿存在不保证正确续接；两边均错 |
| W1-EXPLAIN | 保留B1/B2 exit约占hold99%与B3前区间；同时延续释放/验证残差误读，且把7.012与6.913ms称显著差异 | 漏掉旧退出定位，混淆pre-handler与handler内pre-runtime，并将B3解释推广为总体原因 | 保留文字有局部定位连续性，也有错误解释延续 |
| W2-EXPLAIN | 再次保留旧exit关系和B3前区间；延续释放/网络残差解释和7.012/6.913量级问题 | **动作拒绝**：在arguments中多写kind；未派发final，不重试 | 原始文本仍可审阅，但不能伪装成合法交付或完整语义配对 |
| W2-R | 保留“旧批DB、B3新前区间”的粗粒度区分，未明确旧exit；GC与后续时间差公式有错 | 将旧主要耗时误定位为runtime外application残差，并混淆B3前区间 | 某些连续性有所保留，不等于整任务正确 |

唯一拒绝发生在 `W2-EXPLAIN/NO_HANDOFF`：输出合法JSON，但 `arguments` 除text之外多了 `kind=HOST_CAPTURED_FINAL_OUTPUT`，违反既有动作合同，dispatch次数0。834个输出tokens全部记账。[原始输出与拒绝](</cra/memory/mx_memory/evidence/workspace-host/interpretation-handoff-20260914/run-v1/W2-EXPLAIN/NO_HANDOFF/rows.json>)保留。其未派发文字事实上也提到了旧hold及164/310ms，不能隐去这一点以夸大 FULL 的必要性；正文可重新推导这些信息。格式错误发生原因未单独归因，不能认定由移除Memory造成。

两条 EXPLAIN/FULL 都保留旧exit关系；对应的一个合法留空结果遗漏、另一个留空结果未能合法交付。因此只有一个完整、方向明确的 EXPLAIN 配对，**不是“两次语义比较全部胜出”**。NO_HANDOFF四次同请求却输出不同，使小样本的行为差异更需要谨慎解释。只有一个已暴露lineage，没有显著性、跨任务泛化或可靠提示净收益主张。

所有7个合法 final 都仍有明确错误；另外1个无合法 final。不能用调度 FINISHED 或单个正确数字宣称全任务通过。准确率总分不用于选择创新；当前不足以证明增加短稿、解释提示或复杂State值得成为默认能力。

## 4. 判读依据和分母

按发送前 Goal 的七项检查审阅；这是开发者对原记录的标注，不是独立人工gold或模型Judge。下面仅简写关键断点，原文在上述各组 `terminal.json` 与 `rows.json`：

| 输出 | 主要正向证据 | 明确不成立/遗漏 |
| --- | --- | --- |
| 四份形成稿 | exit/hold的正确局部数量关系；R两稿提出细化退出或数据库/应用边界的检查 | 四稿均有退出后到释放的错误区间描述；GC未观测边界未保持 |
| W1-R/FULL | 提到B3约42.4ms前区间并提出上游队列/线程检查 | 旧DB全称低值、GC全称零、把调度原因说成已定位 |
| W1-R/NO_HANDOFF | B3数值关系、给出OS运行/阻塞的区分思路 | 旧定位遗漏、GC全称零、arrival/dispatch与测量起点混用、时钟绑定被当作排除测量伪差 |
| W1-EXPLAIN/FULL | 保留旧exit与新前区间的不同位置 | 残差命名、7.012/6.913量级和GC外推仍错 |
| W1-EXPLAIN/NO_HANDOFF | B3 client/handler/前区间数值；GC谈论相对限定于B2/B3 | 旧定位遗漏、pre-handler与pre-runtime混淆；用已有起点关系过推内部MCP原因 |
| W2-EXPLAIN/FULL | 新旧不同定位、保持原因未决、提出边界队列/锁检查 | 残差命名和handler/runtime量级判断仍错；GC范围未交代 |
| W2-EXPLAIN/NO_HANDOFF | 未派发原文仍有旧hold/exit与新前区间数字 | 主终态为动作拒绝；原文另有44ms错引为handler外runtime、混淆前区间等问题，不列为合法语义成功 |
| W2-R/FULL | 旧批DB与B3前区间有区分 | 旧exit具体定位遗漏；GC外推，dispatch/eventstart的检查公式错误 |
| W2-R/NO_HANDOFF | 仍列出旧handler/runtime数值，识别B3约42ms | 把约2ms的旧runtime外application残差当主成本，混淆新前区间、GC外推 |

正确数值片段允许进入片段续接分析，不因此把混合稿升级为“旧记忆曾完整正确”。整体Memory因果链没有形成：没有真正持久化/新Host，也没有完整正确旧Note的资格。新证据在场下的解释错误不能直接叫记忆固着；实验移除一段文字后的差异也不能自动叫自主注意力调控。

对应预定七项的开发判读如下。S=supported（本项得到支持），O=omitted（所需内容缺失），I=incorrect（存在明确矛盾），—=not_applicable。列分别是：L旧exit定位、N嵌套/残差、M量级、E新前区间、H新旧范围保持、G GC范围、P推进主要问题的检查。L只评价退出分量定位，区间解释另由N检查；S不认证整篇回答。形成阶段没有B3，E/H不适用。无合法final的一行不以未派发原文填补正式质量分母。

| 输出 | L | N | M | E | H | G | P |
| --- | --- | --- | --- | --- | --- | --- | --- |
| W1-R formation | S（R12明确；R22未细列） | I | S | — | — | I | S |
| W1-EXPLAIN formation | S | I | S（exit/hold比例） | — | — | I | O（只追小残差） |
| W2-EXPLAIN formation | S | I | S（exit/hold比例） | — | — | I | O（只追小残差） |
| W2-R formation | S（R12明确；R22未细列） | I | S | — | — | I | S |
| W1-R FULL | I | S | I | I | I | I | S |
| W1-R NO_HANDOFF | O | I | S（B3量级） | I | O | I | S |
| W1-EXPLAIN FULL | S | I | I | S（前区间位置） | S | I | S（B3检查） |
| W1-EXPLAIN NO_HANDOFF | O | S（残差差值） | S（B3量级） | I | I | S（限定B2/B3所谈请求） | I（已有起点关系不能证明内部原因） |
| W2-EXPLAIN FULL | S | I | I | S（前区间位置） | S | O | S（B3检查） |
| W2-EXPLAIN NO_HANDOFF | — | — | — | — | — | — | — |
| W2-R FULL | O | S | S | I | S | I | S（队列检查；公式错误另记E） |
| W2-R NO_HANDOFF | I | I | I | I | I | I | S（边界检查；解释错误另记E） |

检查建议未实际执行；P的支持仅表示存在能推进的观察思路，不表示原因已经证实。表中同一底层误解可能影响多个项，因此不把单元格相加为独立错误次数或创新分数。尤其不因FULL保留了正确片段就隐去它同时保留的错误残差解释。

## 5. 全部成本

| 组 | 形成实际成本 | FULL消费 | NO_HANDOFF消费 | 实际合计 |
| --- | ---: | ---: | ---: | ---: |
| W1-R | 4,376 | 7,043 | 6,755 | 18,174 |
| W1-EXPLAIN | 4,527 | 6,990 | 6,848 | 18,365 |
| W2-EXPLAIN | 4,514 | 6,944 | 6,936（拒绝） | 18,394 |
| W2-R | 4,332 | 6,857 | 6,997 | 18,186 |
| 总计 | **17,749** | **27,834** | **27,536** | **73,119** |

实际输入66,393、输出6,726；12次生成、无未知/未结算/超界账务。一次身份GET、12次tokenize POST、12次generation POST；无调试模型或Judge调用。实验runner墙钟约52.93秒，包括tokenizer初始化与本地记录；期间开始了仓库回归，不作独立延迟性能结论。模型上下文利用、生成和总预算分别记录，不为用满48配额补发余下36次。

每条策略路径成本应加上本组形成：FULL为11,419/11,517/11,458/11,189；NO_HANDOFF为11,131/11,375/11,450/11,329。两列路径不能再次相加为实际账单，因为它们共享形成。FULL消费者总计比留空多298 raw tokens，但留空包含一次格式失败且质量未匹配，不能把这个差额当可靠效率收益。价钱、缓存计费、完整产品生命周期成本未知；平台agent账另列，不混入实验tokens。

## 6. 工程核对

- 73项邻近测试通过，包含两路输入仅交付text不同、源正文保留、工作区一致、历史H无法绕过、分支副作用隔离、空稿/格式错误/截断/未知用量处理。
- boundary、ruff、mypy（40个源文件）、sdist/wheel build已通过。
- 新完整清单4440项，沿用前轮两片方案：scoped模块3项、其余4437项；每片7200秒，关闭可选faulthandler定时器。两片均exit0：其余片4436 PASS、1项可选SDK SKIP、44项既有warning，1527.82秒；scoped片3 PASS，2448.31秒。合计4439 PASS、1 SKIP、0 FAIL/ERROR。收集nodeid与两片JUnit逐项对应，4440项无遗漏、重复或意外项。[覆盖终态](</cra/memory/mx_memory/evidence/workspace-host/interpretation-handoff-20260914/regression-coverage.json>)。这次没有旧exit139重现；旧异常根因仍未确认，不追认已修复。
- 发送前修正一次ruff全角标点检查，没有改变政策；无真实生成后的接线/提示修复。未修理上述模型多字段输出，也没有重发。
- 本轮代码、政策与执行合同在模型运行和完整回归期间hash未变；完成后仅给Goal补充生命周期终态/报告链接，原发送前Goal快照仍在run/code内。模型比较约53秒，最慢旧回归片约40分48秒；不能把后者算作Memory机制运行成本，也不隐去工程交付实际耗时。

## 7. 当前决定

**保留普通 NOTE/REVIEW，保留可用上下文优先的研究入口；不把 EXPLAIN 或必写阶段稿接入默认产品。** 局部保留“文本可帮助旧定位续接，也可延续错误解释”的现象。它提示应分别检查信息是否正确形成和之后是否被采用，而不是给State增加更多字段。

本轮模型实验与工程交付均已结束，不追加同根微调或第三波。跨来源、独立确认、真实持久化和产品化仍未执行；这些不是关掉本轮Goal必须填满的矩阵。

## 8. 复用与完成核对

原始证据：[run header](</cra/memory/mx_memory/evidence/workspace-host/interpretation-handoff-20260914/run-v1/run-header.json>)、[全部结果与账务](</cra/memory/mx_memory/evidence/workspace-host/interpretation-handoff-20260914/run-v1/result.json>)、[输入核对](</cra/memory/mx_memory/evidence/workspace-host/interpretation-handoff-20260914/input-audit.json>)。原始请求、响应、每段rows及形成文本均在同目录，未放进Git。

代码复用入口为 `tools/run_workspace_handoff_ablation.py --package <现有task-a-v2目录> --root <全新Git外目录>`，需在Lab环境以 `uv run python` 显式执行；会消耗新模型请求，不是本轮自动后继。此次没有新增常驻服务，Provider客户端已关闭，共享vLLM未修改。

| Goal交付项 | 实际完成 |
| --- | --- |
| 原样提示反序复测 | W1/W2四个形成终点全部完成，提示未按结果修改 |
| 同源交付配对消费 | 8尝试有记录，7合法final/1已知拒绝；输入差异与读取边界已核对 |
| 全尝试、分母与成本 | 12次/73119，未知0；共享形成只入实际账一次，失败未删除 |
| 判读与取舍 | 逐项开发审阅，保留普通方案及局部交付现象；不认定净收益或创新 |
| 工程与文档 | 73邻近PASS、4440完整覆盖、boundary/ruff/mypy/build PASS；新Goal与索引收口 |
