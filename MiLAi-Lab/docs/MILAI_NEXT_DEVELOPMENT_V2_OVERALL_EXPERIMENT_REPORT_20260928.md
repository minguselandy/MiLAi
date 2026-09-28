# MiLAi 总体实验报告：NEXT_DEVELOPMENT v2.0 执行收口

**本轮计划的必需执行、分析和条件门槛已完成；结论为收缩方法，研究总目标尚未达成。**
固定bank读取没有显示独立A收益，固定前态更新中all最省；连续任务虽然业务正确，却仍有显式长期形成、临时约束和持久维护失败。
没有足够证据保留“当前State方法优于强简单对照”的主张，也没有稳定unseen收益、第二模型或Product准入证据。

用户确认执行实际存在的NEXT_DEVELOPMENT v2.0后恢复了本次工作。
此前暂停报告及当时WIP保留；本报告不回写历史暂停状态，也不把旧ACTIVE/草案当授权。
[原计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md)原字节与SHA不变；[执行记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V2_20260928.md)记录完整沿革。
本轮结束不自动触发N4/N6、旧v27、第二模型下载部署或下一批实验。

## 本轮最重要的结果

| 包 | 实际完成 | 结论与边界 |
| --- | --- | --- |
| N0 现场／等价提取 | 8个原C5 WIP身份保留；35场景、45个控制请求在声明范围内等价；局部检查通过 | 工程身份明确；Mock请求等价不是实际Postgres/模型效果证明 |
| N1 实际失败链 | 读回一条历史boundary真实HTTP，缺content、ordinary null、State拒绝及部分修复均可见 | 回执已交付；不把语义失败归咎于未送达，不重跑旧修复 |
| N2 固定bank读取 | 两前缀×五臂，10条完整READ/回答路径；各2/2 | full history最省1836tokens；独立A与query增强无额外质量收益，本切片Pivot |
| N3 固定前态更新 | 两前缀×四臂，8条单提案；正文/保持各2/2 | all1846tokens最省；U/oracle各漏一次显式来源绑定，独立U本切片Pivot |
| N5 连续任务 | 原生两个完整arc，各5episode/7消息；构造两臂各8消息，真实world、闭合回合后进程恢复 | 原生各5/5；构造严格生命周期各0/1。全程State空，正文预交付处理未激活，不能解释轨迹差为State效果 |
| WP7 | 按互斥阶段、实际provider请求、embedding、观测和复用机会累计 | 完整实际成本已归账；无20%等质生命周期节省证据 |
| N4 | 条件未触发 | 没有已交付State版本变化需要该有界反馈；不拿普通memory漏维护扩大功能 |
| N6 | 条件未触发 | 缺少可解释State质量/费用投入信号；未启动新任务族或第二模型 |

详细证据：[N2结果](MILAI_NEXT_DEVELOPMENT_V2_N2_RESULTS_20260928.md)、[N3结果](MILAI_NEXT_DEVELOPMENT_V2_N3_RESULTS_20260928.md)、[N5/WP7结果](MILAI_NEXT_DEVELOPMENT_V2_N5_RESULTS_20260928.md)。
论文/通用方法及Product验收均未通过；完成计划执行与获得研究成功是不同结论。

## 读取与更新：简单对照已经足够的切片

N2两前缀共享固定bank、合法完整历史、State READ能力、关闭维护；不让候选独享实体信息。

| N2方法 | 最终回答 | 生成calls | 生成tokens | embeddingtokens |
| --- | --- | ---: | ---: | ---: |
| full_history | 2/2 | 2 | 1,836 | 0 |
| query | 2/2 | 3 | 3,189 | 387 |
| all | 2/2 | 3 | 3,447 | 0 |
| query_enhanced | 2/2 | 5 | 3,889 | 433 |
| a_selector | 2/2 | 6 | 5,540 | 0 |

A有一次将State ID交给memory READ的真实not_found；仍从历史答对，失败保留。
combined query未预选目标field正文也答对，因此ID覆盖不能代替实际任务效果。
短失败回执带来的56tokens差异不称压缩；本切片不足以否定所有密度、规模或任务上的选择，但没有依据任意加干扰制造收益。

N3固定同一前态、相同整体维护接口及CREATE权限；U使用真实新观察，U=A使用实际N2选择助手，oracle仅诊断。

| N3方法 | 正文＋保持 | 显式来源绑定 | strict联合 | 生成calls | 生成tokens |
| --- | --- | --- | --- | ---: | ---: |
| all | 2/2 | 2/2 | 2/2 | 2 | 1,846 |
| U | 2/2 | 1/2 | 1/2 | 4 | 2,110 |
| U=A | 2/2 | 2/2 | 2/2 | 4 | 2,466 |
| oracle U | 2/2 | 1/2 | 1/2 | 2 | 1,386 |

新建主题时U和oracle均缺structured evidence_refs；自动保守dependency/内容里写Source不替代显式绑定。
四臂正文正确，不能称两臂内容形成失败；成功ack也不能升级成来源维护通过。
独立U维护节省不足以抵消selector额外费用，all总体最省。oracle也出现同样绑定缺口，不能把下一步默认为训练selector。

## 连续使用：实际成功与失败

N5使用共同Host普通memory＋State strict CRUD、完整已访问owner历史和原业务工具；两臂只设计State正文none/all差异。
原生MERIT任务、checker、world与输入保持；原生结果不是native B1方法复现。
两臂均正确完成地址、金额修订确认和后续7256／1882 cents退款，但所有ordinary与State记录都为空。
历史已足以支持此短任务，State处理变量未被实际激活。

构造补充中的Riley与Noel明确长期计划均未在初次请求形成持久记录；独立提醒也未形成，实际记录删除未被验证。
all在删除请求时创建了普通计划，后来真实预约后仍保留“Nothing is reserved”；另有一次TEMP前缀泄漏到后续回复。
H没有形成任何普通记录，却曾声称计划“remains saved”。

两组实际业务与恢复均正确：各只有一条Riley预约和一次创建尝试；标签服务失败被如实报告，进程重开后返回同一实际ID，无重复副作用。
Noel实际历史/记录视图保持owner隔离，回答自己的计划与无预约事实。
这不补正形成、维护或退出失败，不是任意硬崩溃恢复、外部真实物流履约或全面权限安全证明。

首断点分别是Host未提出长期保存、后续答案未消费临时范围，以及业务回执后未维护普通记录。
已核对真实输入、工具schema、回执和后续请求；这些失败不是本批程序漏送数据。
竞争解释、混杂因素、通用修复候选和最小未来实验分别见N5报告；本批没有通过改措辞、补种记录或替换失败样本重跑。

## 完整成本

| 本v2阶段 | 新generation calls | 新generation tokens | 新embedding tokens |
| --- | ---: | ---: | ---: |
| N0／N1工程与历史核查 | 0 | 0 | 0 |
| N2 | 19 | 17,901 | 820 |
| N3 | 12 | 7,808 | 0 |
| N5 | 51 | 138,109 | 63 |
| 合计 | **82** | **163,818** | **883** |

开发代理tokens与这些实验Host/embedding费用是两套账，未混算。
连续账本由2799／3,486,504／19,273到**2881／3,650,322／20,156**；
终点SHA256 `e3f5bf8ad50f7825ad010692164238c9dc14e10c113a39d2f0de383b7e3dce83`。
当前known=charged、unknown0，保留sealed旧历史及早期未知成本，不清零。

| N5路径 | 生成tokens | embeddingtokens | 生命周期验收 |
| --- | ---: | ---: | --- |
| native H | 43,169 | 0 | 原生5/5；无记录形成／State对照 |
| native all | 43,646 | 0 | 同左 |
| application H | 23,582 | 14 | 严格0/1；业务及恢复正确 |
| application all | 27,712 | 49 | 严格0/1；另有临时泄漏与过期记录 |

N5原生按前期任务/形成、维护、复用归属；构造按形成、维护、使用、恢复归属，不对同一请求重复收费。
原生R=2，总生成/R为21,584.5／21,823；构造R=5为4,716.4／5,542.4。
混合提醒＋总结消息计一次维护费用，也计一个复用机会；该分母在执行前修正冻结，失败留在分母。
这些是按计划机会摊销，不能当每个成功生命周期成本或等质节省。

N5的51个generation provider ID唯一，3个embedding请求按trace事件计；无新增Judge/selector/自动维护。
所有形成失败、空搜索、实际写入、恢复、后续冗余材料及观测开销保留。
HTTP wall、整个runner进程wall/user/system CPU及Store逻辑调用/字节在[N5机器清单](../data/manifests/next-development-v2-n5-results-20260928.json)分列。
物理DB I/O、未测普通写入CPU、GPU小时与金额unknown，不填零。

## 与历史结果的关系

以下沿用对应阶段原结果，不重新合并分母、不使用当前源码强配所有历史lock。
历史详细总表见[暂停时总体报告](MILAI_OVERALL_EXPERIMENT_REPORT_V2_PAUSE_20260928.md)。

| 已完成阶段 | 保留的证据 | 仍不能推出 |
| --- | --- | --- |
| SER机制／v21 | 机制集成与有限开发样本验证 | 稳定unseen收益 |
| v23原生匹配 | B1 6/10，A3/A4 7/10；无自然refresh/rebase | 分数差是SER因果收益 |
| v24 formation/reconciliation | 三formation提示均0/2；reconciliation strict2/3，所需维护0/1 | 再调措辞即可解决；这些提示路线已停止 |
| v25八次应用 | 多进程、持久化、恢复、scope；仍有过期动作、容量循环、错误key及虚构ID | fresh-session轨迹变化是压缩收益 |
| v26原生Mem0系统比较 | 四个暴露样本B1 2/4、Mem0 4/4；生成5,324 vs53,852 tokens，约10.1倍 | SER消融、同ID修订、跨系统公平消融 |
| 历史LSA及v1 | 16轮小诊断、E2、WP6、C3b/C4反例；v1全成本保留 | 挑最佳轨迹证明State优越；工具忠实自动等于业务严格成功 |

旧M1、持久Decision State、结构化ODR冻结；旧v27未跟踪草稿仍保留且不是冻结协议。
没有新模型下载、部署或共享vLLM设置变化；第二独立模型家族仍NOT_RUN。
参考代码准备、资源下载或包装器工程不自动算效果基线完成。

## 本轮产物、复现与后续边界

| 阶段 | 方法提交 | 结果提交／发布 |
| --- | --- | --- |
| N0 | `ddd5ab71bcc213eb97c52b22698ff9ed4ac1f8ae` | [PR61](https://github.com/minguselandy/MiLAi/pull/61) |
| 历史暂停交接 | `105bdaee7f95d6cccc9b4d227f3492ee33f8794d` | [PR62](https://github.com/minguselandy/MiLAi/pull/62)，原报告保留 |
| N2 | `575360295946a77847702a527271f66102375365` | `8eca99e06f6de3642371a37cc38b08703bfb166b`，[PR63](https://github.com/minguselandy/MiLAi/pull/63) |
| N3 | `dfbc59d39f445dd6d2c3642069e11a8a4da4ed7d` | `4ca0ce1e155715612cebc8ec7486545f7af1a7a6`，[PR64](https://github.com/minguselandy/MiLAi/pull/64) |
| N5 | `1d7460bd73cbff99122e4014df6bfdd15ababec7` | [PR65](https://github.com/minguselandy/MiLAi/pull/65)，本报告及结果随该分支发布 |

每阶段源码/方法、实际输入、scorer、组序、namespace/store/checkpoint/world隔离与连续账本分别冻结。
当前分支是逐级stacked draft；发布不等于合并到main，未自动关闭旧PR。
原C5 WIP、暂停N2树及closeout树保留；当前执行在next-development-v2-resume。

Root负责协议、合成输入/评分、真实串行调用和报告；同一Sol xhigh完成源码、薄装配和必要检查；Luna high执行Git发布。
Astra xhigh只解决一次具体N5共同工具/历史装配冲突，没有常驻审计或并行重复研究。
N5最终38项受影响窄测、Ruff/Mypy、归属矩阵、边界、四份prepare及一次build通过；文档发布只检查JSON、链接、身份和diff，不重跑模型/整套测试。
源码/config/lock/合成输入/rubric/精简结果与文档可发布；DSN、数据库、原始私密轨迹、权重、环境、缓存和构建输出继续忽略。

**Continue：** 保留可复用的公共接口、真实业务回执、隔离与费用工具，作为后续独立问题研究的基底。
**Pivot：** 当前独立A/U及Host-only双库持久维护配方未显示足够额外价值；优先研究最简单普通memory下明确写入/维护责任和语义采用。
**Stop：** 本轮不再宣称当前State方法优越，不追加同题措辞试验、任意干扰扩容或第二模型。
若未来另立研究，应先说明新任务为何需要持久形成、怎样排除完整历史替代、如何验收维护后真正行动，再冻结最小独立比较。
这是一项未来研究建议，不是未冻结的新批次执行授权。Product保持NO-GO，研究总目标保持未达成。

## 前序阶段Reflection补记

本表集中对应总规划§32，补齐逐项可检查的反思，不改各历史结果；N5十项见其结果文档。

| 问题 | N0 | N1 | N2 | N3 |
| --- | --- | --- | --- | --- |
| 1 支持假设 | 声明范围内提取等价 | 真实失败回执确已送达 | 强历史足以答对两个前缀 | all可完成两种正文变化与绑定 |
| 2 反驳假设 | 未见提取改变45请求的证据 | 本轨迹不是回执漏交付 | 独立A/增强在本切片必需 | 独立U减少维护段即总体更省 |
| 3 首断点 | 原WIP尚未取得新执行身份 | 缺正文提案、null及后续只修State | A Host一次选错对象类型 | CREATE提案缺evidence字段 |
| 4 更简单解释 | 共同函数提取即可 | 模型未正确消费可见回执 | 历史已含答案；同请求也有自然响应差 | 可选schema与空候选形式，而非缺来源输入 |
| 5 更简单方法 | 保留原接口，窄等价提取 | 复用已完成strict护栏 | full_history／普通query／all | all候选共享单次维护 |
| 6 复杂度 | 必要工程整理，不当方法进展 | 不增审核Agent或真假规则 | selector额外调用未抵消 | U成本与全bank扫描仍在，不宜加索引/训练 |
| 7 过拟合风险 | 35脚本不等于全运行域 | 单条历史轨迹不能概括所有失败 | 两暴露前缀不可调至胜出 | 两前缀提示/证据自动补写会污染归因 |
| 8 未来反例 | 新实际接线由N5窄测与真实链覆盖 | 合法正文但语义消费失败、部分成功后维护 | 有任务依据的缺背景/重用场景，非任意干扰 | 空mask新建、当前任务外变化、未绑定但可见来源 |
| 9 决定 | Continue已完成N2/N3/N5 | 复用护栏，继续独立诊断 | Pivot独立A/增强，完成N3/N5 | Pivot独立U，进入共同Host连续使用 |
| 10 理由 | 身份明确是有效比较前置 | 已送达不能再靠堆提示解决交付 | 质量相同而额外调用更贵 | all最省且绑定更完整；oracle同样失败指向维护合同 |

发布前读回方法提交1d7460b的[Fast CI run 36366280183](https://github.com/minguselandy/MiLAi/actions/runs/36366280183)：completed/success。该CI只证明相应源码树工程检查，不补正本轮语义失败。
