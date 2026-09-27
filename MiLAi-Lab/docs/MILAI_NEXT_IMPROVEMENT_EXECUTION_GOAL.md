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
| WP0/C0/G0 | 同命令main/PR隔离复现；静态源码—依赖—测试归属无遗漏；core/foundation/external真实依赖；锁定pytest运行71纯协议及原集成、实际收集数；全Ruff、适用Mypy、边界/归档、最终wheel/sdist；真实CI | IN_PROGRESS |
| WP1/C1/X0 | 保留protocol/controller分工；CLI职责归包内且单实现；活动AGENTS与历史分开且原内容可恢复；完整请求/顺序/U维护A/来源/pending/容量/回执/trace等价，规范化项明确 | NOT_DONE |
| WP2/C2/G1 | 锁定上游实际集成复现未知合法UUID被upsert；薄严格CRUD同步/异步一致；已有/缺失/错误namespace/message UUID/空删除/真实删除/Store异常/无副作用回执；不强制每次额外Host READ，不声称CAS | NOT_DONE |
| WP3/C3/X1 | 固定表示/前缀/工具能力先比较写入责任；Host主导/边界主导/重叠保持合理CRUD途径；长期约定/临时约束/owner/变化/事件不重复/后续动作与费用；再决定引用化State | NOT_RUN |
| WP4/C5/X3/X4/G2 | 明确A≠U且U空可CREATE；保留原问题实体、全读/普通检索/同State查询增强/可关selector；固定同bank与前态比较all/U/U=A/oracle；对真正使用引用做有限失效，不引全库图 | NOT_DONE |
| WP5/C4/X2 | 同粒度整体/普通patch/候选局部维护；明确目标版本/唯一片段，广泛变动可整体；更新与无关保持同时测；D0/真实事件身份/部分成功维护续接保留 | NOT_DONE |
| WP6/X1 | 用户、真实工具结果、助手提案、可修订State角色清楚且原回执完整；固定正确正文比原标题/源标题/无State，首响应后实际动作；无gold键名规则 | NOT_RUN |
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

### 后续定向诊断准备（未冻结、未运行）

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
