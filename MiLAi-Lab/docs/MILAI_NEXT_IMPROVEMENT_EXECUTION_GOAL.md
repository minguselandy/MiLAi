---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE; necessary root CI only
reference_commit: 9515017a5dfaba6b6e306fa778fd20f4383b6e35
plan_sha256: e407a8ac577b2fb184b6e4386efb79536bcf75007252c8006e96eb296fa3cbbb
---

# 后续改进计划执行记录

用户已明确要求详细阅读并执行[新计划v1.0](MILAI_NEXT_IMPROVEMENT_PLAN_20260927_v1.0.md)。
Root完整阅读466行并核对实际Goal为active。规划稿写作时的未授权/暂停说明及上一轮暂停
保留原样，不能覆盖这次明确执行指令。保留完整WP0—WP7与X0—X5目标，不把成功收缩为修CI。

用户追加收尾要求：**当前任务结束后暂停实际Goal，生成总体实验报告并上传GitHub。**
这是一项任务结束后的安排，并非立即停止指令。执行期间继续记录全部失败、未完成项及累计费用；
达到本计划阶段结束条件后，暂停实际Goal（不把总研究目标标成完成），由Root生成总体报告，
Luna high提交/推送并核对远端SHA。总体报告须独立列出工程完成、实验结论与尚未触发的G4。

## 基线、证据与当前实际状态

main=`9515017a5dfaba6b6e306fa778fd20f4383b6e35`；PR51 head=
`055a0769c1ce75d128d6459ee25773587d9003ae`，首个结构提交
`26c4f3058691af3fe31cda906f67ffce6bd1986f`。原main工作树只有新计划与旧v27草稿未跟踪。
未发现仍运行的实验/下载；现有共享Qwen服务保持不动，未部署模型。
连续账本为2768次生成、3420333 generation tokens、18746 embedding tokens，
SHA256 `a9d4c681e2bee395c170a4672b4895a442522df47951c9a043e9f6b3a32e3580`。
开发代理与依赖安装开销不混入实验token账本；历史sealed链不重算、不清零。

GitHub重新核实：[PR51](https://github.com/minguselandy/MiLAi/pull/51) open/draft、未合并、无review/未解决review thread。
[Fast run36318522281](https://github.com/minguselandy/MiLAi/actions/runs/36318522281)已终止failure；
Lab job108617763464原日志证实14错误/7文件，缺langgraph/langchain_core/langmem/openai及unused-ignore。
foundation job108617763499成功；full run36318522284 skipped。其余成功不替代默认Lab gate失败。
这些是旧head的实际远端证据，不冒充新修复已通过。

隔离checkout：`MiLAi-worktrees/next-wp0-main`与`next-wp0-pr51`只读源码对比；
`MiLAi-worktrees/next-improvement`为开发工作树，分支`ci/lab-verification-matrix-20260927`，起自main。
三个独立core环境，foundation/external另置ignored环境；不复用主研究环境造成可选依赖假通过。

## 工作归属与授权

沿用现有Sol xhigh唯一源码/配置/CI/必要检查负责人；Root独占文档、合成输入、rubric、
协议冻结、全部真实HTTP/embedding/评分/连续费用；Luna high负责依赖/参考源码下载和已授权Git发布。
Astra xhigh仅在具体难题需要时启用。每文件一个写入负责人，真实HTTP并发1。
本次执行授权涵盖计划内实现及冻结后的小规模研究，不须为规划时“需新授权”逐项重复询问。
PR合并仍须正常检查和审阅闭环，当前不自动merge；先完成可审查产物，不提前制造许可阻塞。
第二模型部署、学习selector、Product迁移、分布式事务和物理删除保证不在当前默认范围。

## 完整验收对应表

| 工作包/门槛 | 必需完成及权威证据 | 当前状态 |
| --- | --- | --- |
| WP0/C0/G0 | 同命令main/PR隔离复现；静态源码—依赖—测试归属无遗漏；core/foundation/external真实依赖；锁定pytest运行71纯协议及原集成、实际收集数；全Ruff、适用Mypy、边界/归档、最终wheel/sdist；真实CI | G0_PASSED（声明的历史资产skip不算通过） |
| WP1/C1/X0 | 保留protocol/controller分工；CLI职责归包内且单实现；活动AGENTS与历史分开且原内容可恢复；完整请求/顺序/U维护A/来源/pending/容量/回执/trace等价，规范化项明确 | ACCEPTED；C1本地检查/最终构建与实际Fast已通过 |
| WP2/C2/G1 | 锁定上游实际集成复现未知合法UUID被upsert；薄严格CRUD同步/异步一致；已有/缺失/错误namespace/message UUID/空删除/真实删除/Store异常/无副作用回执；不强制每次额外Host READ，不声称CAS | ENGINEERING_ACCEPTED；C2实际Fast通过，在线语义另验 |
| WP3/C3/X1 | 固定表示/前缀/工具能力先比较写入责任；Host主导/边界主导/重叠保持合理CRUD途径；长期约定/临时约束/owner/变化/事件不重复/后续动作与费用；再决定引用化State | C3a PR55初轮失败保留，2c7修复实际Fast通过；C3b六完整轨迹完成：Host双写2/2、boundary1/2、overlap2/2；连续生命周期仍待X5 |
| WP4/C5/X3/X4/G2 | 明确A≠U且U空可CREATE；保留原问题实体、全读/普通检索/同State查询增强/可关selector；固定同bank与前态比较all/U/U=A/oracle；对真正使用引用做有限失效，不引全库图 | NOT_DONE |
| WP5/C4/X2 | 同粒度整体/普通patch/候选局部维护；明确目标版本/唯一片段，广泛变动可整体；更新与无关保持同时测；D0/真实事件身份/部分成功维护续接保留 | 候选与强普通patch合并两臂；C4工程冻结及必要检查/构建完成，实际实验NOT_RUN |
| WP6/X1 | 用户、真实工具结果、助手提案、可修订State角色清楚且原回执完整；固定正确正文比原标题/源标题/无State，首响应后实际动作；无gold键名规则 | R1六次首响应及全部实际续接完成；严格1/6，标题修复Pivot |
| WP7 | 独立语义写入/重复规则/依赖、Host/U/maint/A、材料、Store调用/CPU/wall、任务与维护分别测量；全生命周期Cbuild+Cmaint+ΣCuse及复用摊销；只有实测热点才优化 | NOT_DONE |
| X5/G3/C6 | 正常可用简洁基线＋独立可切换最小候选；同合法历史/权限/CRUD/可比预算；连续在线真实世界/恢复/复用及全成本；逐例首断点和可执行Go/Pivot/Stop | NOT_RUN |
| G4（条件后续） | 有有效比较与投入信号后，模板未见/跨模型/强外部对照及局限；无端点/原生scorer不称完成 | NOT_TRIGGERED |

强对照义务：full history（容量允许时）、强原文检索、同内容State＋ReAct、同State普通query、
同粒度更新/patch、相同额外预算回看/rerank/重建。按假设选择最小切片，不一次展开所有模块大矩阵。
Archive-access与Retained-memory分开；日志可搜索权限各臂一致；原生LangMem/Mem0与薄适配机制归因分列。

约5个百分点质量或预声明不劣界限下约20%生命周期成本是投入信号，不是小样本统计证明。
重复生成不增加独立场景数，以arc/owner/共享历史聚类报告差值及适用区间；不将未评分强行计普通失败。
G4和旧研究缺口继续保留，未运行不能被解释为无效。完整目标的完成须逐条检视本表和原计划，不能以绿色CI结案。

## WP0首断点与竞争解释

Observed：默认core安装后Mypy进入需要可选依赖的7模块，总gate停在类型检查。
Expected：每个活动模块在安装真实依赖的环境检查，纯core不引入可选依赖；后续测试/构建实际完成。
H1：main已有检查归属缺口，PR只是首次暴露；H2：重构导入图使额外模块被递归发现；H3：本地/CI安装环境不一致掩盖缺失。
先在相同锁/Python的干净main与PR head执行同命令，结合实际模块映射区分；“未修改文件”不直接证明H1。
禁止global ignore_missing_imports或只扩大exclude，无覆盖归属的排除无效。类型修复不得顺带改变运行协议。

当前没有新增真实generation、embedding或业务调用。离线复现与最小矩阵已经实现；
Root按真实结果补依赖对应表/协议/总证据，Luna在最终构建后发布C0独立提交并获取实际CI。
旧实验不重跑，未取得远端结果前不关闭G0。

## 交付与回滚

每切片记录原问题、变更类型/路径、输入输出合同、已运行与未运行、费用/失败/样本单位、剩余风险和决定。
代码C0可回滚至9515017；PR51结构分别保留26c4f305/055a0769身份。方法变化独立C2—C6提交与freeze。
未知真实副作用不盲重放；旧snapshot不能回滚业务世界。原始轨迹、凭据、数据库、缓存/模型继续ignored。
原计划、旧报告、rubric、曝光集合与旧v27草稿原样保留；遵从用户本次任务结束后暂停的安排。

### WP0离线复现进展

Luna完成三core环境（各60包）、foundation（96包）、external（138包）的隔离安装，
均Python3.11.13/pytest8.4.2/uv0.8.3，uv.lock未改；仅补普通依赖包，无模型资产。
安装receipt位于ignored `artifacts/next-improvement/envs/installation-receipt/`。
Sol在main与PR51两源码上用各自core执行 `uv run --no-sync mypy src/milai_lab`，
两者均为同14错误/7文件、110个直接检查源码；H1既有依赖归属缺口得到支持。
PR51在锁定core环境真实执行 `pytest -q tests/unit/test_lsa_controller_contract.py` 为71 passed。
新矩阵覆盖143个活动源码，core公共检查5171 passed/19 skipped/8 deselected，
foundation144 passed/0 skipped，external4 passed/0 skipped，本地历史MERIT4 passed。
19项core skip中1项为历史固定SDK wheel，18项为外部tokenizer/model证据；
8项deselect为4项local_artifacts和4项原regression。逐项归属见对应表，不当成远端已通过。
全Ruff、适用Mypy、两个边界、Archive1728项与工作流检查通过。
最终分发构建及实际远端CI仍须以发布回执和对应run为准，不据局部通过宣告WP0已关闭。

对应表、实际断点与未完成检查见[WP0验证记录](MILAI_NEXT_IMPROVEMENT_WP0_VERIFICATION_20260927.md)。
新增首断点包括可选测试导入、历史私有制品前置及Mem0缓存缺失导致的skip，按实际归属修复，
不把跳过或本地通过写成远端通过。锁定NLP资产准备只是既有原生Mem0集成的检查前置，
不启动第二LLM下载或部署。

### C0修复终态与C1工作记录

修复提交`ebf7878fc34bef6f72723ce22e445e5bf712d4f3`的Fast36325329534已通过；
远端core为5043 passed/142 skipped/14 deselected，foundation145 passed/1 deselected，
external成功且原生mock SDK测试真实执行。Full36325329524的core和分发构建均通过，
2026-09-27 14:54 UTC已核实historical presentation-v2-positive和最终composition gate
全部成功，Full的21个job成功，G0关闭。
新CI实际checkout为merge commit `516f13aa330625440d98fd53a2bb5b282cffdab7`，
将该PR head组合到main `9515017`；这不是已经合并main。

隔离子进程隐藏MERIT后的本地core为5166 passed/19 skipped/14 deselected；
core deselect精确为4 regression＋10 local_artifacts，foundation另有1项local_artifacts。
远端142项skip来自缺失的历史资产，逐项记录，不能与本地19项混用或称全部5199项通过。
直接相关门禁完成后先在独立C1分支做可逆结构工作；随后完整G0也已通过。
这段工程验证期间没有启动行为实验。
当前本地组合head `5dc024d3b277915709556af4e3eee4e1e64f06f1`带`-x`保留PR51两原提交，
main、PR51、C0原分支不变。Root已完整保存旧AGENTS并拆出活动指南，Sol已完成薄runner整理与三组mock差分。
准确身份、原字节恢复路径和待验证项见[WP1记录](MILAI_NEXT_IMPROVEMENT_WP1_REVIEW_20260927.md)。

### 历史C0发布及后续定向诊断准备（研究仍未冻结、未运行）

C0已作为[PR52](https://github.com/minguselandy/MiLAi/pull/52)发布，head
`64741a6475fbc30ccabeffd3ba782de9763d0d98`，最终本地分发构建通过。
实际Fast36324207954/Full36324207975的core和foundation因未声明的本地MERIT历史路径失败；
external真实依赖检查成功。首断点、竞争解释和原失败job已写入WP0验证记录。
继续最小测试资产修复；未关闭G0，未开始真实研究调用，main和PR51保持原身份。

修复精确登记11项历史MERIT资产node，并在相同文件保留公共合成prepare/loader及三臂装配
覆盖，不改运行时或历史freeze。public定向1＋23项、新增历史7项以及目标静态/matrix已通过；
隐藏本地MERIT目录的子进程隔离public core检查与修复后远端CI仍待实际结果。
通过后C1使用独立stacked branch承接C0和PR51两个原结构提交，原PR和main保留，
新组合以实际新head验证，不声称原PR51失败head已经变绿。

Root保存5个已有已发布哈希的完整历史HTTP请求，来自两个已暴露脚本，涵盖对象key、
第二次增量及正确State后的错误动作；这些嵌套前缀不构成5个独立场景。
目录为ignored `artifacts/next-improvement/x1-source-catalog/`，仅保存原请求，不带原答案或rubric。
新实验仍须独立冻结源版本、合同、输入、scorer、顺序和隔离；旧合同请求不冒充新CRUD配方。

Astra只读分析了WP3的具体冲突：Host普通memory与控制器State是两类存储，直接关闭一条
写入路径会丢失能力，立即统一两库又会同时改变表示/身份/检索/生命周期。
竞争设计为：A，保留两库、补共同带目标类型的严格操作入口；B，先迁到单一持久目标。
初步推荐A，但它仍保留两份可能冲突的事实，不能宣称单一语义真值。
共同能力准备及工具呈现必须先独立冻结，再比较Host主导、边界主导与历史分工适配版；
需要立即结果的边界路径返回真实提交结果，所有新增调用与原提案保留计费。
**该设计未实施；共同操作入口不能混入C2首次仅补存在性/回执的修复。**
先完成C2，再选择一个第二次增量和一个无变化反例的最小条件比较；正例后还须验证真实动作。

### C1完成与C2开始

C1最终内容为`0d04ca68d0e575919773c24b764c3c0b1832de7e`。发布预检发现新文件EOF空白，
原本地提交`9bc3c9fe74cf6072025e3f205904d85dd66c2b86`保留，后续只去除一个换行字节且AST相同。
最终必要构建通过：wheel `b968f3183fdb4b47ec08526e1a50f58cdb47566da892a16f5eee5796584cd552`；
sdist `db650a7bb4c4d173d2cdc0ce4382dff12745567535decec211875b4fe0a134f4`。
源码/请求差分归属与首轮构建保留，已发布[PR53](https://github.com/minguselandy/MiLAi/pull/53)，Root核对远端head一致；
其Fast36328343542及最终gate108646972066均已通过，按新head独立验证。PR53保持draft，main与原PR不变。

独立C2分支`fix/lab-strict-memory-contract-20260927`已开始。
[WP2合同记录](MILAI_NEXT_IMPROVEMENT_WP2_STRICT_CRUD_20260927.md)列出首断点、
模型身份混淆与集成upsert两种解释及最小可选严格接口；102项相关检查和必要静态/边界通过，
C2本地工程验收通过，尚未开始在线语义验证。
现有服务只读GET核实7860为Qwen3.6-35B-A3B-FP8/65536，7861为bge-m3；没有推理或部署。

### C3a共同能力开始

C2源码与Root检查记录已提交`93cb3e9cb405c97d52bc807b54f532b2a5b489f3`。
独立C3分支进行[共同能力准备](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_CONTRACT_20260927.md)；
Astra就State-only controller、两库CRUD能力与D0 slot/ack冲突给出有界建议，采用共同executor
及薄边界提案入口，保留原State表示与旧controller合同，不全量扩展LR/LRU或创建新journal。
完整overlap需要两个写阶段，不能把六次生成当三模式各自完整对照。共同能力、角色配方、
语义输入与执行分别冻结；当前仍为0新增真实调用。

### WP6首响应R1开始

C2 Fast36329556696和最终gate108650321223已通过。Root在独立detached C2 checkout
冻结[WP6协议](MILAI_NEXT_IMPROVEMENT_WP6_PRESENTATION_20260927.md)，两个已暴露arc、三种材料条件、
六次首响应按固定顺序串行执行。此前0新增真实调用的记录是当时状态；从本段起新增费用
以原连续账本和R1 trace为准，不把提案正确当业务成功。C3共同能力仍独立开发。

### C3a冻结与WP6首响应结果

C3a六份源码/测试已停笔冻结，最终7项Writer检查通过，具体时序和限制见WP3合同。
WP6首响应六次均有已知HTTP usage；正确提案1/6，错误5/6。两个已暴露arc不当六独立样本，
标题变更未修复，后续六臂均需实际工具与Host续接。费用增量6/7605/0，连续2774/3427938/18746。
原始输入/rubric/顺序未改；协议说明对partial raw历史信息的误述已有明确更正和原字节快照。

### C3a发布与WP5比较范围收敛

C3a `bd5b4acb50a37b84cdcf87b4fcfab7b4b699faa5`已发布[PR55](https://github.com/minguselandy/MiLAi/pull/55)，
base=C2，Fast36331279476待实际结果；未合并main。新分支
feat/lab-frozen-action-continuation-20260927只进行WP6实际首响应续接接线，Root随后冻结执行。
Astra完成WP5“候选局部表达与强普通patch是否独立”的有界分析，Root采纳
[两臂同粒度合同](MILAI_NEXT_IMPROVEMENT_WP5_LOCAL_UPDATE_20260927.md)：没有独立第三算法，
不为凑对照复制实现。该项仍未实现/冻结/运行，不将设计决定写为实验结果。

### C3a实际core失败与WP6续接范围

PR55初始Fast36331279476未通过：新controller顶层可选LangChain导入阻止core71协议测试收集。
最小lazy import修复已在真实core71和foundation Writer7通过；原失败保留，按新commit等待CI，
不据foundation成功盖过core失败。WP6续接使用[独立草案](MILAI_NEXT_IMPROVEMENT_WP6_CONTINUATION_20260928.md)，
目前只有零模型graph恢复API验证；原六真实响应不重新生成，实际续接仍NOT_RUN。

C3a修复Fast36331881913与最终gate108656930104实际成功，core5114/142skip/14deselect、
foundation162/1deselect、external成功；C3a工程门槛关闭。WP6续接前态与评分输入已冻结，
入口源检查/最终构建和执行identity仍须完成，实际续接尚未开始。

### WP6续接完成，C3b开始

[WP6续接](MILAI_NEXT_IMPROVEMENT_WP6_CONTINUATION_20260928.md)在独立ec34c89源码完成六条实际ToolNode/SQLite/后续Host链。
五个错误提案全部落库，严格任务1/6；三条标签失败均停止，六条实际ID正确。新增6/8846/327，
连续2780/3436784/19073。停止标题措辞路线，保留角色/原历史混杂，不宣称纯State消融或unseen收益。
[三种写入责任](MILAI_NEXT_IMPROVEMENT_WP3_WRITER_POLICY_20260928.md)在独立开发branch准备；
仍待源码/协议冻结与真实运行。完整WP0—WP7目标继续active，任务结束后按用户要求暂停并整体报告。


C3b工程已冻结，终版16项定向检查通过，预发布六job零模型prepare通过；
真实运行仍NOT_RUN。Root公开检查回执及构建前后身份，Luna随后发布独立C3b提交。
同回合真实维护回执续接已修复，跨进程保证仍留待连续生命周期切片，不据本切片提前宣称。


### C3b实际比较完成，WP5独立实现

C3b在07aaa3c独立冻结源码完成六完整轨迹，严格5/6；一个已暴露arc/两个前缀，不作统计或unseen主张。
Host双写与overlap均2/2；boundary增量缺content导致ordinary memory写null，后续只修State。
真实HTTP证明不是parser丢字段；保留失败，另立strict CRUD缺正文拒绝修复，不混入WP5。
连续费用2795/3479362/19273，历史链未变。Host双写先作为最小候选进入后续X5，仍需真实形成/owner/
临时要求/复用/动作恢复与完整费用；不能以这六轨迹结案。
[WP5](MILAI_NEXT_IMPROVEMENT_WP5_LOCAL_UPDATE_20260927.md)两前缀四job的输入及scorer已冻结，
Sol在独立C4分支实现同粒度整体/普通patch合同；没有独立第三算法，实际比较尚未运行。
