---
status: EXECUTION_CLOSED_INCONCLUSIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
plan_sha256: a4b0fe36e77e20c5e227c6341ea6de3b5febcd415f22b2e4c6938c70d9a84269
base_commit: c6f335fef7cf00c86fa3dbe201a60c802439ca12
research_goal: NOT_ACHIEVED
product: NO_GO
---

# v7 执行记录

## 当前结案状态（优先于以下历史准备记录）

P0/P1 和全部可运行 E1 已结束；[总体实验报告](MILAI_DEVELOPMENT_EXPERIMENT_V7_OVERALL_REPORT_20260928.md)
及[逐项需求审计](../data/manifests/development-experiment-v7-requirement-audit-20260928.json)构成 P5 交付。
结论为 **协议 INCONCLUSIVE / N BLOCKED_ENVIRONMENT**。这不是整体研究目标达成，Product 仍 NO_GO。
配套架构复盘已完整补读且 hash 一致，初始路径缺失已解除。

- 源码 A：`37d48577bdff582f74faf2f5e663b359885350ec`；实际 E1 输入／运行 B：`2f30c14c5e7ea82db2b0a962d3636e14de5f2391`。
- 全部 24 job 已 prepare/freeze；J12 条／26 消息／22 session 各运行一次，N12 条事前环境阻断保留。
- J12/12、任务92/92（current52、later8、persistent32）；26诊断无新问题。六结构的两次重复不是独立样本。
- 真正效果为8 CREATE、2同ID UPDATE、2预约／标签、2实时查询；无重试、假保存或新隐藏评分修复。
- 新增38次生成／49,456生成tokens及10次embedding／294tokens；权威账本末值3301／4,205,203／23,570。
- 末账本 SHA `f9efa35e1a83f4c4300f03f28394a584868f8955b320e960dc3f8bb7a4ce1592`；完整历史未动。
- B Fast36422762879的缺tokenizer资产失败保留；C `a1c6c683a39e8d0bf87e75afec32061fae46dfd4`仅补测试／矩阵和独立检查回执，运行源码／输入不改。
- C Fast36425412512待最终状态核对；Full36425412508 skipped。最终文档提交的CI状态由PR71 checks直接给出，不改原冻结证据。

所有运行进程已结束。停止本slice，不自动开启 N、E2–E6、第二家族、下载或新服务。
Root 完成纯文档／JSON／链接／哈希核对，Luna high 提交推送；实际 Goal 仅在最终远端核对后结案。
PR71 保持 draft/open、base v6分支 @ c6f335fe；PR70未合并、main07cc364f不变。
最终报告提交身份取本文件所在 Git commit，不能冒充实验 B；发布后核对收据保存在 ignored 制品及 PR。

## 初始准备记录（历史快照）

实际active Goal明确要求详细阅读并执行[原v7计划](MILAI_DEVELOPMENT_EXPERIMENT_PLAN_20260928_v7.0.md)。
Root完整阅读1055行，原DESIGN_ONLY/NOT_STARTED字节保留。新Goal仅恢复新计划范围，旧v6结论不改。
配套架构复盘全文在工作区（含ignored）、/tmp中未找到；计划所列SHA尚不可验，已询问现存路径。
现有v7文本、v6完整trace和源码足够先核对具体P0/P1断点，不假装读过缺失文档。

## 需求与证据责任

| 要求 | 所需权威证据 | 当前 |
| --- | --- | --- |
| P0身份/成本 | 服务version/models、真实启动flags、模板/tokenizer/部署源码、依赖、连续账本 | 完成；无模型调用 |
| P0四首断点 | H/I原输入→真实首响应→工具/Store→后续结果与hash | 清单完成，旧失败保持 |
| P1投影 | 两协议同合法内容/权限、JSON旧编码不变，catalog入容量 | 已实现及局部检查通过 |
| P1执行语义 | 无工具/单多工具/拒绝/续接/同ID更新/删除读取/未知工具/坏参数/截断/partial/owner窄证据 | 已通过必要检查 |
| E1冻结 | 六结构×二重复×二协议；完整执行及新session复用，源码/输入/权限/顺序/成本冻结 | Root输入/义务/顺序已定；待已发布SHA prepare/freeze |
| E1真实运行 | 每个可运行job实际HTTP/执行/持久/交付/回答；不可用协议明确BLOCKED_ENVIRONMENT | 未调用 |
| P5报告 | 七层结果、四层义务、条件化分母、全成本、两解释、修复/局限/复现、逐项审计 | 待完成 |
| E2推理 | E1后有实际需要及受支持协议/模式、独立冻结 | CONDITIONAL_NOT_STARTED |
| E3引用/P2 | 固定协议/writer，真实key选择失误，独立接口比较 | CONDITIONAL_NOT_STARTED |
| E4写入/P3 | 校准后仍漏存，唯一有限candidate，负例同样计费，无双writer | CONDITIONAL_NOT_STARTED |
| E5连续/P4 | 已有修复内容冻结及适用综合验收 | CONDITIONAL_NOT_STARTED |
| E6 Attention | 真实取材/范围/预算问题，同bank同writer与强简单基线 | CONDITIONAL_NOT_STARTED |
| 第二模型 | E1/E2未决、已具备且已授权独立服务 | CONDITIONAL_NOT_STARTED |

第一slice严格P0/P1/E1；不因列出全范围就同时开发/运行所有分支。
若native环境不可用，记录不能进行真实协议优劣比较；仍完成允许且有价值的工程/JSON基线、P5和未执行清单。
不以环境阻断当算法失败，不只报告提案成功，也不因普通语义失败取消冻结剩余独立任务。
危险scope/权限/未知世界重复等违例立即停止该路径并隔离，其他比较仍按已冻结规则处理。

## 身份与起点

工作树 `/cra/memory/mx_memory/MiLAi-worktrees/development-experiment-v7`，branch
`feat/lab-protocol-calibration-v7-20260928`，base c6f335fe。Luna已只创建工作树，Root复制原计划并记录本次范围。
PR70仍draft/open、未合并；远端main07cc364f。v6最后Fast36411545487 success，Full36411545583 skipped。
旧main工作树及八份未跟踪文档保留，未pull/reset/cleanup。

账本起点3263 generation calls /4155747 generation tokens /23276 embedding tokens，
SHA `2df7547a9d038cb53105afbf5daa97bbd8225bb204c19af40b7c68eee264ade2`，known=charged、unknown0。
权威账本原树 artifacts/ser-v20/budget.json，不创建新账本或重置历史。
现有Host7860 Qwen3.6-35B-A3B-FP8/65536，embedding7861 bge-m3/1024；原参数temperature0/max_tokens4096/thinkingfalse。
实际读取Host /version=0.27.1；进程无 --enable-auto-tool-choice/--tool-call-parser/--config。
模型卡支持与服务实际启用不同，P0需以安装版本接线判定。没有实验或下载进程。

## 首个工程断点及竞争解释

已读provider：request_view.project/fit_final_request/record_delivery在JSON分支，native直接发wire/tools；
runner还把tool_mode限定json_action。仅改配置不会构成同材料比较。
解释一：这是局部协议适配接线缺失，可共用结构化投影并保留不同编码器。
解释二：native的tools模板/结果解析/实际调度和旧扩展还有独立约束，只搬project会漏容量/来源/执行一致性。
先让Sol核对并实现最小完整P1路径，不把未运行native说成质量失败。

源码/测试/config由Sol唯一负责；Root只写文档/输入/评分/制品，所有真实调用由Root串行。
Luna负责精确Git发布；先源码提交A，再冻结输入提交B，再Root在发布SHA prepare/freeze，结果提交单独发布。后因CI资产登记修复插入C，最终报告为D；实际E1身份始终为B。
不合并PR70，不擅改共享服务，不下载模型，不恢复历史C/ODR/M1。最新v7具体职责优先于旧阶段过时限制。

## 配套复盘补读

用户随后提供原路径；文件现已可读。Root完整阅读487行，SHA
`03ba2a29c041b0a3ca5bb4e79db3585d6c996b781688b06496b79e6070928484`与计划一致。
已按原字节复制[架构复盘](MILAI_MEMORY_ARCHITECTURE_REVIEW_20260928.md)进入独立树；此前缺失记录仅是初始时点，当前缺口解除。
复盘明确允许有依据的工作事实/多个局部项、动态观察记忆、必要时有限同步子任务与非容量选择问题；
这些最新设计优先于旧阶段绝对禁令，但首批仍P0/P1/E1，不能提前全开。

## P0 已完成与 E1 范围

[能力清单](../data/diagnostics/development-experiment-v7-p0/protocol_capabilities.json)已核实服务、部署源码、
模型四项资产与计数资产的hash一致、依赖、usage和账本；P0新增generation/embedding均0。
[四类失败链](../data/diagnostics/development-experiment-v7-p0/failure_chain.json)从真实H/I trace与结果重建，
原分数/实际世界评分修正均保留。复盘文件加入后原main现九份未跟踪文档，全部保留。
部署vLLM无auto/parser，安装ParserManager和serving分支共同证明native auto不可用；
不进行无效生成探测，不声称观察到HTTP400，不改服务或新增client-parser第三协议。
N的12个预定job保留为BLOCKED_ENVIRONMENT；J的12个job在P1检查和双提交冻结后真实执行，
不能由单组成绩推断协议因果优劣。六结构每重复13消息，两重复每协议26消息，计划双组52消息。
E1输入与根离线义务现已成稿，未来可用N也不能在本slice自动恢复。E2–E6仍不启动。

## P1 源码已发布

Sol已完成五源码、三测试、两config并停止写入；Root审阅源码diff和配方差异。
Luna提交A `37d48577bdff582f74faf2f5e663b359885350ec`，Root ls-remote核对一致。
[工程报告](MILAI_V7_P0_P1_ENGINEERING_REPORT_20260928.md)记录131个原请求双视图回放、
86审计、native实际工具／容量窄查与最终静态／边界检查。Fast36422089826当时仍运行中。
J/N只差协议和描述性recipe名称，J相比原v6 compact只增加profile与名称。
P0/P1新模型调用0，权威账本SHA仍为原起点。接着发布B文档/输入并prepare/freeze。
