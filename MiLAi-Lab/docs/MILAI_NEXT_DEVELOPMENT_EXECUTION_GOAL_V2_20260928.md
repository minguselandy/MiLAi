---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
method_reference: cf1588ab3f1d1fe8105f3f239cb56f1151e8f5bc
report_reference: ae2d29285ce263e32b0729444e1dc6a4f57ed5b1
plan_sha256: 84d5ddd45224d83c4206c95d8b46ca41f2a5dabd9990266aadccae0df1c0df22
---

# 后续开发 v2.0 执行记录

用户启动新的实际active Goal，要求详细阅读并执行v2.0，覆盖上一任务已完成的暂停收尾。
Goal给定文件名为`MILAI_NEXT_IMPROVEMENT_PLAN_20260928_v2.0.md`，现场不存在；唯一同日期/版本文件为
[MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v2.0.md)。
Root已完整读取527行、向用户说明文件名差异并提出可选澄清，按该唯一v2.0继续；不修改实际Goal的原目标。
新树保存原计划逐字副本，规划时“PAUSED/不授权”文字保留，当前执行授权来自最新用户Goal。
旧v1计划、报告、失败、曝光集合和C5原始WIP全部保留。

## 完整目标和验收依据

| 包/要求 | 证明完成需要什么 | 当前状态 |
| --- | --- | --- |
| N0 / G1现场与基线 | 8个WIP实物身份、真实PR拓扑；等价提取与行为分开；同输入请求差分、相关窄检；新协议prepare覆盖源码/schema/模型/输入/评分 | 8/8哈希一致；35场景/45控制请求等价、相关检查通过；N2/N3实现及新prepare未完成，未关闭整个G1 |
| N1消费与维护 | 既有真实HTTP、来源和部分成功回执核对；确认已有strict护栏；仅有明确竞争因素才调用新模型 | 窄机械检查与一个历史boundary失败的实际HTTP核对完成；实际回执已交付，保留语义消费瓶颈，不加提示变体 |
| N2 / X3固定bank读取 | 两前缀全读/query/同State增强/实际A/完整历史共10条路径；共同读取能力、维护冻结、实际交付与最终回答/续接、全部费用 | 原输入准备存在；旧首响应合同不足，未冻结v2完整路径 |
| N3 / X4固定前态更新 | 两前缀all/U/U=A/oracle共8条诊断；同前态/整体维护/权限；空U可CREATE；实际提交/保持/误改/pending/费用 | 原6输入文件中的更新草案待校核，未实现或运行v2 |
| N4有限交付版本反馈 | 仅有相关问题才触发；UPDATE/DELETE/CREATE/NO_CHANGE/拒绝/恢复/超限机械检查；独立开关和真实续接 | NOT_TRIGGERED；不是N2/N3前置 |
| N5 / X5 / G3连续任务 | 一个强简单基线与至多一个获筛选候选，同版本从形成到复用、变化、owner/临时约束、真实副作用/恢复/授权退出；原生单元与构造补充明确分列 | NOT_RUN；11消息旧草案不是已冻结协议 |
| WP7全生命周期 | 形成/维护/使用/恢复互斥归属、request ID不重复记账、摊销R、质量并列；Store/CPU/wall/逻辑字节/观测边界 | NOT_DONE |
| N6 / G4独立确认 | 有可解释信号后新任务族、强简单对照及有明确资源安排的第二模型；未见/已暴露严格分开 | NOT_TRIGGERED，不自动部署或训练selector |
| 论文/总验收 | 完整CRUD与实际任务、受控A/U额外价值或明确收缩结论、任务/维护/业务分别评分、贡献与局限及复现完整 | 尚未完成，不能用N0或绿色CI替代 |

保留全计划§12—18的使用、统计、公平性和Go/Pivot/Stop义务：当前版本不等于真相，选择不等于交付，
交付不等于语义采用，工具成功不等于用户任务成功。普通query/all足够时收缩selector，不人为扩充干扰以制造收益。
N5优先实际原生完整任务，owner/临时/遗忘等缺项另列构造诊断；不改原benchmark后沿用原生成绩。
只有确有信号才进入条件分支，不因条件尚未触发自动展开所有开发，也不将未运行写成无效。

## 当前源码、工作树与服务

main仍为9515017；上一报告为ae2d292，方法为cf1588a。原C5树`MiLAi-worktrees/next-improvement`
保持`feat/lab-state-selection-20260928`/cf1588a，controller/protocol两修改及read/update各三JSON均与暂停清单一致。
Luna建立干净`MiLAi-worktrees/next-development-v2`，分支`refactor/lab-selection-contract-v2-20260928`，
从ae2d292出发。原WIP不切换、不reset/clean、不覆盖。Sol先在新树移植原两文件并检查等价，不混入N2行为。

真实PR关系已由Luna读取远端和本地祖先核对：PR51与PR52均base main、head相互非祖先；
PR53 base PR52，其后54→55→56→57→58→59→60逐级承接。PR51 head不是PR53 head祖先，
不能将C1的带来源标记移植称为合并PR51。全部旧PR仍draft/open/unmerged；PR60自身Fast36338918693已success。
没有自动合并、关闭或重写旧PR；每次CI只归属于实际测试组合树。

Root只读GET `/v1/models`核实Host7860仍Qwen3.6-35B-A3B-FP8/max_model_len65536，
embedding7861仍bge-m3。只读探测不产生generation或embedding收费；完整请求参数按新实验freeze核对，
不靠models列表声称全部服务配置已证明。共享vLLM/parser/thinking/容量/温度保持，不部署新模型。

## 首断点、竞争解释与最小动作

N0：原WIP只有共同A提示/载荷函数提取，尚无执行检查。
H1是纯等价提取；H2是字段、目录构造次序或阶段副作用发生隐含变化。静态diff支持H1，但需同输入实际请求差分。
最小动作是只移植两文件、运行相关mock/协议和N1现有strict窄检；不重复WP0/全部旧测试、无必要不build。

N1：既有boundary缺正文在raw HTTP可见，已由独立strict guard拒绝；后续修复只完成State。
H1是Host/维护模型见到全部合法材料仍误用；H2是来源时点或真实部分回执未进入该次请求。
先对照已有实际HTTP/ToolMessage/Store结果，只有可区分的新因素才另冻模型实验；不做标题微调或重复失败直到通过。

N2：原read草案的`host_execution`仍是一次首响应，工具目录没有State READ；新v2要求实际读取及最终答案/必要续接。
这是旧范围与新验收不一致，不能把“needs_continuation”记为已完成。另立v2输入与工具/运行身份，
复用公开ReAct/ToolNode及已有读取接口，保留共同合法历史和信息权限；原六份JSON不改。
固定bank下维护保持关闭，query增强与A共用同目录/实体信息，普通query保留完整原问题；全部额外费用计入。

## 责任与成本起点

Root负责计划/输入/rubric/冻结、全部真实Host/control/embedding、评分、连续账本与报告。
现有Sol xhigh唯一源码/配置/runner/相关检查负责人，Luna high负责已授权Git发布/必要资源下载；
Astra仅处理明确困难问题，不设常驻审计者。每个文件一个写入负责人，真实模型HTTP并发1。

本v2起点：2799 generation calls、3486504 generation tokens、19273 embedding tokens，unknown usage均0；
原账本SHA256为`bfc2768c4cd6d92ce650bc65e2018b8d23a404de0c9a61e07e88ccbd1c43d0c6`。
权威路径仍是原checkout的`MiLAi-Lab/artifacts/ser-v20/budget.json`，sealed历史不变，不建立清零账本。
开发/CI费用与模型实验分开；失败、修复、seed embedding、空维护和观测保留。当前新模型调用0。

## 发布和后续证据

只发布源码、配置/锁、合成输入/rubric、精简结果和文档；不含凭据/DSN、私密原始轨迹、数据库、环境/模型/缓存/构建制品。
原v27草稿保留且不是当前授权。每阶段Root写真实结果和局限后，Luna提交/推送并核对远端SHA与预期工作树。
原源码检查不为发布重复执行，必要构建取决于入口/依赖/包装改动；文档仅检查链接/JSON/哈希。
Goal保持完整目标active；完成判定必须逐项回看本表与原计划，单个故障用具体修复/转向处理，不缩减目标。

## N0等价提取与N1已有链核对完成

[精简检查回执](../data/manifests/next-development-v2-n0-n1-checks-20260928.json)保存源码与原8文件哈希。
protocol与原WIP字节一致；controller仅在原WIP基础上按Ruff整理import分组，初次I001失败保留。
旧cf1588a和新树执行35个现有合同场景，45个控制请求及bank顺序/receipt/pending/capacity的完整有序JSON相同，
未去除字段或做规范化，两者SHA256均为`1b3069b6a44ef41de18a8ca999eb39dff2d52ac251bfe8dd2dd9a29b7e6edbfb`。
这是scripted model/fake Bank合同差分，不是原始HTTP字节或真实Store等价证明。
71项core协议、11项strict/共享executor/partial回执相关foundation窄检及目标Ruff/Mypy通过。
无入口/依赖/包装变化，未build、未全suite、未真实HTTP/embedding或共享DB；N2/N3仍未执行。

Root另读原C3b boundary增量失败trace：原模型HTTP确实省略两个UPDATE的content；
后续repair control请求中的成功/error回执，按tool_call_id与实际boundary回执逐字段一致，ordinary正文确为null。
两次Host工作视图均逐字进入实际请求，含null；后续控制只调用manage_state，Host触发理由明确标non_evidence。
因此“这条失败因为真实回执没交付”的解释被该轨迹排除；材料被语义误用/修复聚焦State仍可能。
不将一个轨迹外推全部故障，不新增措辞试验；新strict拒绝合同已由上述窄检查核对，旧失败不回写。

N2输入审计另发现：combined旧raw_history只有当前session的field问答，不能标完整合法历史；
5条State中的两张“预约失败”卡由旧控制模型在实际业务调用前生成。它们是实际存储的模型声称，
不是实际失败回执。保留原bank不“修好”后比较，新输入将登记合法历史截止点、构造任务和这个混杂，
绝不将State正文作为业务事实或把旧局部session直接当强完整历史参照。

发布暂存检查发现原计划第3、4行的Markdown双空格硬换行被`git diff --cached --check`提示。
为保留用户计划原字节及SHA，接受且仅接受这两处文档空白，原文不改；源码空白检查要求不变。
