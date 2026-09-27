---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
reference_commit: 4aea99de0b7e058e2d254bf8860d0aba6d6b48db
plan_sha256: 079f8bfb6cdefbe4da11696d29b6f6cc74755f81337bdbfe3996add000cf18dd
---

# Local State–Attention 执行 Goal

## 用户最新收束指令

用户要求当前任务结束后暂停Goal，生成总体实验报告并上传GitHub。当前任务限定为正在
进行的window_summary切片：完成实现、必要窄测/构建和已预注册4轨迹验证后暂停。
不再启动R、U=A、新公开任务、模型下载/部署或其他后续开发。下面仍写ACTIVE或下一步的
历史段落不覆盖这条指令。总体报告须保留完整失败、连续成本、局限和未完成项。

用户已明确要求详细阅读并完整执行
[736 行原规划](MILAI_LOCAL_STATE_ATTENTION_DEVELOPMENT_EXPERIMENT_PLAN_20260927.md)。
本 Goal 保留 P0–P7、WP1–WP5 全部范围，不把完成定义收缩为 P1 原型或局部测试。
原规划字节不变；其中“拟议、尚未执行”是授权前状态，后续进展记录在此。
旧 `MILAI_MODEL_SENSITIVITY_V27_GOAL.md` 是独立过时草稿，不恢复其下载/部署。

## 当前事实与责任

授权开始时 main 与远端均为 reference_commit；v26 85 个 source 和 8 个 validation
文件哈希匹配。只有两份用户提供的未跟踪规划，没有预存 LSA 实现。当前实际 thread Goal
为 active；新会话没有可复用的旧代理，已启用一名 gpt-6-sol/xhigh 源码负责人。

Root 独占 docs、AGENTS、合成输入/rubric、阶段选择与冻结、所有真实模型/embedding 调用、
评分、成本及报告；Sol 独占 LSA 源码、必要共享接线、config、根 CI 和相邻窄检查。
Luna high 按需下载和已授权 commit/push；Astra xhigh 仅处理具体困难问题。
真实 HTTP 并发 1，开发代理不能替代实验 Host 或 Judge。

既有 Host 为 Qwen3.6-35B-A3B-FP8/7860，temperature=0、max_tokens=4096、
thinking=false、context=65536、每公开消息 Host 最多 12 次；embedding 为 bge-m3/7861、
1024 维。不改变既有 vLLM 服务；控制器预算单独声明且计入总计算。
连续账本 `artifacts/ser-v20/budget.json` 从 863 生成 / 1042729 generation tokens /
9617 embedding tokens 继续，历史成本链不清零；既有 exact-version reads 为 107。

## 完整执行与证据清单

| 阶段/工作包 | 必须交付的证据 | 当前状态 |
| --- | --- | --- |
| P0 / WP1 | 方法关闭 B1 请求/工具/持久状态对照；锁定公共 hook；实际 run_manifest；来源权限及计费角色 | R3 补全机械依赖与实际Store计量；真实授权删除链仍待独立验证 |
| P1 / WP1 | bank、独立共享维护器、U/A、实际视图；两条完整交错轨迹，含跨进程、新 session、真实部分失败与恢复 | R4两臂原各7/12；R5 partial来源on4/6、off3/6，原完整均失败；精确恢复出现局部正例 |
| P2 | 同 bank 的扁平/普通检索/State-conditioned 读取；组合与交换/缺项/错误状态诊断 | R1四断点12方法+3诊断完成；State值影响输出，来源直送有用，维护/独立Host错误未闭合 |
| P3 / WP2 | G/L/LRU 同维护机会、来源权限、预算、降级策略的小样本重复比较 | 六模板×三臂×两重复已闭合：35完整+1中断；G60/78、L60/78、LRU59/78；未证明稳定收益，维护输入修复原高耦合三臂各6/6，新反例3/5，首断点在Host |
| P4 / WP3 | 信号出现后 LR、U=A、R；六项关键消融及跨模板验证；共享约束、高耦合与错误状态反例 | LR接线与共同完整历史接线已完成；完整历史/LR历史各10/12且成本不同；U=A/R/滑窗摘要与其余消融未完 |
| P5 / WP5 | 新 frozen 原生 selection、第二任务族、交错顺序及完整重复；原 scorer 和失败分母 | 未运行；不消费旧暴露任务作 unseen |
| P6 / WP4–5 | N/d/a/r/H 代表点、质量—成本边界、第二模型族；有瓶颈证据才训练 selector | 未运行；第二模型仍缺独立端点 |
| P7 / WP5 | 无模板提示的模拟协作应用、复现命令、失败分类、强对照与论文证据包、发布及远端核对 | 未完成；Product 仍 NO-GO |

P3 的建议规模与后期 3–5 次重复在各阶段冻结前按方差/资源确定，不能结果后删失败或改分母。
只换名称/数值不算跨模板泛化；§15.2 十二种组合须在输入覆盖表中逐项映射。
完整历史、滑动窗口+摘要、强工作笔记/统一短维护器必须进入相关强基线判定；
B1/Mem0 系统对照与表示/注意力消融分开，不用被动 B1 代表全部 LangMem 能力。

原规划§15.2的覆盖按真实机制逐项区分，不能把fixture中出现过词语当实现完成：

| 项 | 现有输入/证据 | 仍未闭合 |
| --- | --- | --- |
| 1 多事项交错/相似对象 | P1 interleaved、P3 shared/conflict | 局部分组仍可能退化为综合卡 |
| 2 前台不变/后台变化 | P1 background-revision及新session恢复 | 跨模板独立收益未证实 |
| 3 局部与共享更新 | P3 shared-scope/high-coupling | 多State原子共享更新组未实现 |
| 4 适用范围变而正文部分不变 | P3 shared-scope的indoor修订 | 最终方法跨模板比较待做 |
| 5 值/metadata/无关变化 | P3 same-value-confirmation和独立briefing | 保持失败保留；不是鲁棒性完成 |
| 6 新建/归档/重新打开 | P3 reopen-history | 已测语义关闭/重开，未实现真正archived生命周期 |
| 7 部分失败/未知/维护滞后 | P1/R5/P3/LR真实部分预约与同ID恢复 | 未知结果仍需独立实际边界验证 |
| 8 跨会话和独立进程 | 两phase原脚本及P3批次 | 只证明相应小轨迹，不是长期规模可靠性 |
| 9 历史查询和当前执行 | P3 conflict/reopen-history | 完整历史公共接口已交付；滑窗摘要/重建待验收 |
| 10 错误/缺项State遇新证据 | P2交换诊断、Host snapshot R2 | 后者只读且失败；在线状态纠正及A6未完成 |
| 11 当前来源冲突与权威 | P3 conflicting-sources | 保留混合结果，不能用时间/rank作权威 |
| 12 高耦合反例 | P3 high-coupling与events-only修复三臂6/6 | 新distinct-event反例仍失败；非密度曲线 |

上述历史结果按各自冻结提交解释，不要求当前源码重新匹配所有旧锁；原始36轨迹没有重跑。

## 实现与验证不变量

- 复用 BaseStore 独立 owner namespace；程序拥有 ID/revision，模型不生成 UUID/hash。
- 一个真实事件有稳定来源 ID；同文本不同事件不能去重；原消息、工具 JSON、checkpoint 保留。
- 独立控制入口不递归调用 Host；Host schema 保持 answer/calls，控制与 Host request 绑定分开。
- 当前用户纠正、所有真实工具结果（含 ok=false）均可见；部分副作用不回滚、不因维护重放。
- 单条坏编辑独立跳过，相关 pending 保留；无变化无新版本；共享原子组不能半组声称完成。
- 可选控制错误退化并计入主分母；真实数据库/权限错误显式隔离，不冒充模型语义失败。
- State 是可错的估计，引用合法不等于支持；pending 状态不静默宣称为已核对当前事实。
- 原始来源、索引、State、队列均计存储/访问成本；匹配臂权限相同，不读取 gold/未来事件。
- 删除覆盖 State 与缓存引用；撤回潜在影响和历史查询用途分开，scope 不可软回退。
- 根 `.github/workflows/fast.yml` 执行新窄测；完成切片运行实际受影响 foundation/journal/
  集成/包装检查；不跑全套 benchmark，不为发布重复成功检查。

每次运行由真实入口生成一个 manifest，自动绑定 Git/实际源码、config、依赖、模型参数、
输入 hash/split、arm/repeat、阶段计费/异常和输出。Root 在调用前冻结 source、输入、rubric、
顺序与隔离方式，并独立核对实际 HTTP→持久化→后续上下文→回答/动作。
不新建一套与运行入口重复手抄的参数/方法/输入清单；旧 source locks 原字节保留。

## P0/P1 的首个断点与竞争解释

当前源码没有 LSA bank、控制调用和前置视图接线。既有 B1 在 formation 上的失败不证明
新方法必然有效；先实现新机制，再以真实链路检验。

H1：普通 Host 自选 CRUD 的维护机会不足导致未来信息未保存。
H2：观察已到达，但缺少可持续状态视图/恢复路径使后续任务无法使用。
部分失败另比较 H3：模型将 ok=false 当成全失败，与 H4：跨进程事件/pending/状态接线丢失。
最小区分证据是公开输入→事件→控制 HTTP→真实 Store 写入→新 session 视图→业务回执，
不能靠 schema、进程 exit code 或测试通过替代语义判断。

P1 输入使用新合成事项；所有 State 与 U/A 由方法自行产生。轨迹 A 覆盖三事项、后台局部
修订、前台保持、新会话恢复及组合行动；轨迹 B 覆盖部分提交、跨进程读取实际对象并继续，
并检查第二用户隔离。复用既有 ApplicationWorld，不把正确分组或参数注入运行器。
rubric 与脚本分离，runtime 不读取 rubric；这些实例从首次执行起记 development。

[P1 输入协议](../data/manifests/local-state-attention-p1-protocol.json)已固定两轨迹、12 消息、
各两阶段的独立进程顺序与 rubric。源码完成并已交接冻结，协议当前为 PRE_REGISTERED_READY_FOR_SOURCE_PUBLICATION；
这不是已执行记录。Host 12 次及 controller 13 次为每公开消息容量上限，控制输出 2048 tokens、
Host 输出 4096 tokens，真实 HTTP 仍串行。服务 `/v1/models` 只读核对为原 Qwen/bge-m3，
生成窗口 65536；此次核对没有生成或 embedding 调用。

Sol 已完成 23 项相关测试：`tests/unit/test_local_state_attention.py`、
`test_langmem_application.py`、`test_langmem_foundation.py`；目标 ruff、7 文件 mypy、
core 110 文件 mypy、package/tools boundary 与 diff 检查通过。两条新脚本的 CLI prepare
均零模型通过。最终 build 已通过，sdist `4363d01093d0411d94e5b34299aa5ad344fb4fcc67b713e324d717d4d0ed75a7`、wheel `22855bf1325d25ddbd51fed1993b82fbb836c831f51eca6f399c3b4fc310cce9`。最后一次重建对应删除视图源码变更；没有为了发布重跑已通过组。以上证明工程接线，
不代替 P1 真实内容/副作用验收，也不证明后期消融、规模与泛化。

P1 实现是小 bank 全目录和原始事件逐项读取，尚未交付规模检索、原子共享更新组、归档/
重新激活和完整 G/L/LR/LRU/R 对照。源码相关问题已修正：到达序号替代 hash 排序；新建
引用绑定原编辑索引；LSA 显式关闭 SER；删除身份阻止旧 checkpoint 内容重新进入 State，
发送副本在删除来源后的下一条真实用户消息处重新开始，避免旧助手复述泄漏；原 checkpoint 保留。原始 DB 写入故障显式失败并保留 pending；
可选控制超时/截断允许 Host 继续。真实 Postgres 只读连接和现有依赖已核实可用。

## P1 实际进展

原型提交 `031acc7ae63353ac00ef237755b7b028ef8ae989` 已与远端 main 核对。
[R1 失败记录](MILAI_LOCAL_STATE_ATTENTION_P1_R1_RESULTS_20260927.md)确认新建 title
在 schema 可选、bank 必需，导致三次合法 HTTP 输出均未形成 State，pending 被保留。
实际运行 3/12 消息，Host 当轮 3/3 完成不能替代 State 验收；后九条未运行，不替换。
同一 Sol 仅修复通用字段契约，Root 将冻结新版本并重跑两条完整原 development 轨迹。
累计成本为 869 generation / 1048218 generation tokens / 9617 embedding tokens。
P2–P7 和完整 Goal 保持 ACTIVE。

R2 通用契约修复已冻结：创建必须有标题，更新可保持省略字段，focus 限于当前真实 ID
或本批新建短引用；10 项 LSA 窄测、相关 ruff/mypy/diff 通过，没有重新 build 或模型探针。
[R2 协议](../data/manifests/local-state-attention-p1-r2-protocol.json)继承原输入及 rubric
字节和顺序，新的源码发布后由实际 prepare 生成运行身份。R2 首请求检验新 schema 的
真实 decoder 兼容性，P1 语义验收仍待完成。

[R2 实际结果](MILAI_LOCAL_STATE_ATTENTION_P1_R2_RESULTS_20260927.md)及
[精简数据](../data/manifests/local-state-attention-p1-r2-results.json)保留全部两条轨迹。
跨进程持久恢复与部分失败 ID 保持可用，但控制器在业务调用前虚构了行动结果，且存在
读取遗漏和独立 Host 参数错误。真实用户/工具历史保留，0 degraded/0 pending 不等同
语义通过。全部9张State无evidence_refs，当前删除关联和Store操作计量也需补。
累计903 generation /1082606 generation tokens /9626 embedding tokens。
先进行冻结同bank的P2条件使用诊断（不声称P1已完成），再由Sol实现单一通用修复候选；
P3仍未触发。临时Astra只处理这一个具体跨层问题，不是常驻审计或效果裁判。

[P2 读取诊断协议](../data/manifests/local-state-attention-p2-r1-protocol.json)固定
四个真实断点的同bank all/query/focus。bank由真实请求与已接受写入重建，并逐项核对
实际view；普通query用bge-m3相似度top2，只读focus额外调用单列计费。
所有原始Host历史、工具合同和模型参数保留；仅改变临时工作视图，停在第一answer/calls，
不执行业务动作。12个方法job按固定轮转顺序，另3个diagnostic覆盖人工选择的真实旧计划、
反事实值及完整真实部分失败回执。raw输入留ignored，协议绑定输入字节hash；rubric分离。
独立薄入口已通过4项窄测及ruff/mypy，实际冻结输入的临时prepare为15 jobs/0 attempts。
一次必要build确认新CLI在sdist、新模块在wheel；哈希见协议，正式manifest在发布后生成。

Astra建议的后续单一语义候选是来源身份保持的状态迁移：维护输入保留actor/call身份，
区分请求、用户陈述与真实工具观察，不把读取任务写成已发生结果；不同时改Host。
删除另外使用程序机械dependency_source_ids，累积旧值、当前来源及所有可见State依赖，
与模型evidence_refs分开；全bank可见时可能保守多删，必须报告。缺失旧依赖不能视为无依赖。
这些是开发候选，不能据建议声称问题已经解决。

[P2 R1结果](MILAI_LOCAL_STATE_ATTENTION_P2_R1_RESULTS_20260927.md)与
[精简数据](../data/manifests/local-state-attention-p2-r1-results.json)记录15个首响应，业务执行0。
12个方法job为3个直接正确、2个中间memory步、7个错误业务参数，不能换算最终任务分数。
正确旧计划/反事实值改变输出，完整真实回执消除本例get键类型混淆；但精确对象名和
内部State ID被误用于memory仍未解决。同wire也出现不同输出，不归因于臂标签。
累计922生成 /1100126生成tokens /10394 embedding tokens。
R3仅做一个来源身份保持的控制合同候选，并独立补机械删除依赖/Store计量；Host、工具描述
和工作视图暂不改。随后原两完整P1轨迹+用户过去事件报告反例，若同族仍失败停止措辞微调。
[R3协议](../data/manifests/local-state-attention-p1-r3-protocol.json)已固定原12消息与新增2消息
的独立分母、顺序及输入hash。三个run的新State/memory namespace只读核查为空；正式
prepare/执行必须在新源码发布后。不是恢复任何旧运行，也不改变旧模型敏感性草稿。
R3切片已完成13项窄测、目标ruff/mypy及一次必要build，三脚本/tmp prepare零模型通过。
源码仅改bank/controller、原runner计量和窄测，Host/render/config未动；构建哈希见协议。
机械依赖不进入模型输入，旧记录unknown依赖会导致授权删除时保守多删；正常no-op不写入/
不增版本。每phase的finally汇总实际get/search/put/delete次数、耗时及逻辑字节，历史不回填。

[R3实际结果](MILAI_LOCAL_STATE_ATTENTION_P1_R3_RESULTS_20260927.md)保留六phase全部结果，
原轨迹5/12、新增用户报告1/2；空focus导致已保存信息不可用，空memory搜索仍被写成业务结果。
交错组合达到原12次Host容量，末消息跳过并留在分母；两条原完整业务均未通过。
停止来源合同措辞微调。累计983生成 /1184433生成tokens /10575 embedding tokens。
实际Store操作已计量，所有六张末State含程序依赖；真实授权删除链尚未执行。

[R4协议](../data/manifests/local-state-attention-p1-r4-protocol.json)固定三原脚本×两臂×一次完整
运行，全量读取local_all与原focus读取local_state共享R3控制器和调用频率。共同移除Host
临时视图内部ID/revision，保留控制输入/Store/trace；不同时改变Host业务合同或工具schema。
这是暴露样本的端到端读取诊断，不是固定bank实验或P3的完整G/L/LRU比较。
29项相关测试、最后16项LSA测试、目标静态检查、六个/tmp零模型prepare及一次必要build通过；
不为发布重复检查。正式prepare在源码发布后，完整六轨迹过程中源码冻结。

[R4实际结果](MILAI_LOCAL_STATE_ATTENTION_P1_R4_RESULTS_20260927.md)完成六轨迹28消息：
两臂原各7/12、原完整各0/2；新增用户报告all2/2、focus1/2。全量解决了部分读取遗漏，
却不能阻止维护丢信息与Host错用对象/地点。两partial臂均实际原ID补标签，但get均not_found，
初始key也错误，严格分数不追补。累计1079生成 /1300287生成tokens /10831 embedding tokens。
下一薄切片按选中State的合法evidence_refs展开原始来源，机械删除依赖不作为语义引用；
不继续来源合同措辞微调，不同时换Host业务schema或独立selector。
P3完整比较尚未启动；强G/L的少量实现/wiring可推进，不等所有旧Host参数失误都消失。

[R5协议](../data/manifests/local-state-attention-p1-r5-protocol.json)固定两条完整partial轨迹，
来源展开on/off各一次，原6消息/rubric不变。新臂local_all_sources只展开交付State的显式引用，
精确当前scope读取，16384 UTF-8整事件预算；空refs无额外get，不回退机械依赖或全档案。
38项相关窄测、目标ruff/mypy/diff、两个/tmp零模型prepare与一次build通过。R4真实恢复断点
无模型replay解析3个refs/1336字节（含1条实际tool receipt），额外6get；不是再次运行P2能力探针。
构建哈希和验证见协议。发布后正式prepare与两条真实运行，源码全批保持冻结。

[R5结果](MILAI_LOCAL_STATE_ATTENTION_P1_R5_RESULTS_20260927.md)完成两条partial：来源on4/6、
off3/6，原完整均0/1。on实际交付原部分失败回执后get使用真实持久key并found，再沿原ID
补标签；off仍把RSV作key而not_found。初始单数key与Noel错误保留，不能称P1全过。
off还有一次错误evidence ID被独立跳过，pending保留但Host正确回答，降级也在分母。
累计1119生成 /1347149生成tokens /10919 embedding tokens；此切片新增40/46862/88。
下一切片已授权Sol实现强G/L小wiring：单global note vs local bank，共同已有来源展开，
相同事件/维护/模型/工具/读取预算。共享aggregate正文16000 chars，G单note16000、L每卡4000，
报告其他字段/来源/实际wire容量；原配置不显式给新预算时维持历史行为。
只先两原脚本×两臂的少量wiring，不运行36轨迹，不宣称更新候选缩减/LRU或P3完成。

[G/L wiring协议](../data/manifests/local-state-attention-p3-wiring-r1-protocol.json)固定4条完整
原development轨迹：interleaved G→L，partial L→G，各一次。G为每owner/workspace一note，
L为原多State；共享all_sources、16384字节来源和16000字符aggregate正文预算。
源码只改bank/controller/CLI/config及窄测：G现存note仅update/no-op，保留共同edits+focus外层；
原L提示与业务合同不改。26项LSA+6项相邻application检查、目标静态、四/tmp prepare和一次build
通过；最后仅补测试断言，无产品目录修改。协议载构建哈希；发布后正式prepare，批内源码不变。
这一步不包含LRU候选缩减，全部结果仍按完整原rubric及失败分母报告。

[G/L wiring R1结果](MILAI_LOCAL_STATE_ATTENTION_P3_WIRING_R1_RESULTS_20260927.md)已完成4轨迹24消息，
源码053a5ed08b6e01f826997e7b1158d7a9de033fc5。G11/12、完整1/2，L9/12、完整0/2；
两臂均实际get found并原ID恢复label，但interleaved错对象键，L另有初始/第二owner字段错误。
关键限制是L本批也每owner只有1张综合卡，不能称已隔离局部表示收益。G作为强基线保留。
本批新增72生成/93431tokens/173embeddingtokens；累计1191/1440580/11092。无控制退化、
pending或容量错误，不把预算未触发说成规模可靠性。下一切片落实通用局部事项粒度和真实
LRU更新候选/独立读取，保持来源合同与业务接口，不再R3措辞微调，不启动广泛比较。

[R2小接线协议](../data/manifests/local-state-attention-p3-wiring-r2-protocol.json)准备原两脚本×
G/L/LRU各一次，顺序interleaved LRU→G→L、partial G→L→LRU，共36公开消息；先遇到新
LRU decoder，全部输入/rubric仍是development。L/LRU显式打开local_granularity，按可
独立更新/恢复的事项分卡，缺省配置保持旧行为，G保持一note。LRU用短目录选U、只交付U
正文给维护器，再基于更新目录选A；所有子调用共用原13次控制容量和2048输出上限。
空U/no-create可跳过维护，坏编辑逐条跳过并保留pending；A失败不撤销已经提交的State。
目录仍读取完整Store记录，不能把模型正文候选减少说成物理读取减少。新源码已完成44项相关窄测、
目标静态检查、六个/tmp零模型prepare及一次必要构建（哈希见协议）。发布后Root正式
freeze再运行，批内不改源码；不是提前开始完整P3重复比较。

另已准备[四类后续输入与rubric草稿](../data/diagnostics/local_state_attention/p3-additional-rubric-draft.json)，
共27消息，覆盖共享政策/适用范围与同值确认、等权来源冲突、用户报告闭合与重开/历史、
高耦合共享容量。runtime脚本与rubric分离，不提供oracle State分组；未选入或执行批次，
不声称unseen。逻辑关闭不等于物理归档实现，未知副作用真实恢复及错误State注入仍是
独立缺口。先完成当前小接线的机制检查，再冻结后续完整情景/重复/顺序。

[R2结果](MILAI_LOCAL_STATE_ATTENTION_P3_WIRING_R2_RESULTS_20260927.md)已完成6轨迹36消息，
源码2b65c175c9ffe40f2e09f0327ee4f5faec87a84a，G9/12、L8/12、LRU6/12，完整各0/2。
L在workshop形成3卡，后台修订初次只改field-kit卡，但Mira仍合卡。LRU首次计划被
may_create=false拦截，维护未调用且pending消费，导致后续缺项/虚构；无控制退化不等于
正确no-op。三partial均实际found/原ID补label，错误初始key和其他字段仍计失败。
累计1321生成/1582759tokens/11162embeddingtokens；本批130/142179/70，历史不变。
下一单一结构修复让U只选择已有State，所有pending批都有共享维护器的新建/no-op机会，
空bank直接维护→A；保持预算、来源合同、Host与G/L，随后仅两原LRU轨迹小验证。

[R3修复协议](../data/manifests/local-state-attention-p3-wiring-r3-protocol.json)已固定仅两条原LRU
轨迹、12消息；G/L保留R2历史身份，不重跑、不伪称新配对比较。Sol修改限controller/CLI/
config/窄测，45项相关检查、目标静态、两次/tmp prepare及一次build通过。新manifest
声明creation_policy=shared_maintenance_each_pending_batch；selector不再否决新建，所有
pending到共享维护器，但合法空edits仍消费pending，因此语义是否改善仍待真实核查。

[R3真实结果](MILAI_LOCAL_STATE_ATTENTION_P3_WIRING_R3_RESULTS_20260927.md)完成两条原LRU：
8/12、完整0/2。三处初始计划都进入维护，交错三卡保存；正确U与实际旧正文中的rigid cases
已到维护HTTP，却被替换为packing stays the same，后续实际行动用same。Mira沿原ID实际
found/补label成功，两owner初始key错误仍计失败。Noel空U导致后续重复新建，不能把新建
机会等同于正确粒度。新增61生成/51693tokens/0embedding；累计1382/1634452/11162。
保留当前源码，不继续提示词微调，也不等所有Host错误消失才进行方法比较。

[P3完整小样本协议](../data/manifests/local-state-attention-p3-matched-r1-protocol.json)固定
原两模板加四个关系/约束模板，G/L/LRU各两次独立完整运行，共36轨迹/72phase/234消息。
分块交错顺序与seed、全部输入/逐turn rubric、隔离、成本、全失败分母均已冻结；发布后
正式prepare，批内不改源码/输入。四模板是Root预先编写审阅的development，不冒充unseen。
L联合edits+focus与LRU拆分控制的合同差异明确列为系统比较混杂；后续LR用于归因。
§15.2的物理归档/重激活、未知结果恢复、错误State注入等缺口仍单列，不靠覆盖表宣称完成。

Sol只读核查还确认：forget_source/delete_scope已有Bank原语及删除后的防重摄取hook，但
应用/CLI没有实际授权删除入口；不能直接把mock删除当成完整授权链。后续独立实现入口并
冻结真实删除验证。跨session完整历史/滑窗摘要与R也需合法、同权限且计费的事件档案入口，
不能偷偷从trace或其他臂checkpoint取免费历史。当前bank.events的256上限不得被称为全档案。

[P3匹配R1结果](MILAI_LOCAL_STATE_ATTENTION_P3_MATCHED_R1_RESULTS_20260927.md)保留全部36轨迹/234消息：
35轨迹完成、LRU第二次高耦合首消息缺manage_memory ID中断，随后五消息未运行，整条0/6。
Root先停机只读定位，冻结继续决定后完成原剩余四条；没有重试、替换或批内改源码。
G60/78、L60/78、LRU59/78；完整2/12、3/12、4/12。LRU候选正文为全bank的69.1%，
总生成472853tokens却为L的约1.34倍，尚无稳定质量或成本优势。精确业务大小写/限定词
失败与错误数量/容量单列；任务通过也可能留下重复/过期State。
本批+922生成/1241742tokens/6173embeddingtokens；累计2304/2876194/17335，历史不变。

首断点已由实际HTTP定位：用户增量处理后，只有普通工具回执pending的维护仍带旧current_task，
将3/4/5重复改成4/5/6。下一独立源码切片统一G/L/LRU可写维护只接收pending事件/候选State，
U/A与Host保留任务；G/L全读改为edits-only，legacy focus显式兼容。不新增事件账本或文本去重，
不同时改Host/schema/历史优先级。先零模型输入边界反例，再冻结三臂各一条原高耦合及少量
相同文本新事件反例，不重跑36条。缺ID工具错误观察另作局部切片，不宽泛吞掉Store异常。
LR、共享合法档案/强历史基线、授权删除及P4–P7仍待实现；不以这些失败终止完整Goal。

[维护输入隔离R1协议](../data/manifests/local-state-attention-maintenance-events-r1-protocol.json)已固定
原高耦合G/L/LRU各一次，加一条LRU相同文本/不同来源ID增量反例，共4轨迹23消息。
Sol仅改controller/CLI/config/相邻窄测：G/L/LRU写维护payload不含current_task，G/L全读使用
edits-only且controller_focus为空；U/A和Host仍有当前任务，legacy focus联合合同保留。
47项受影响检查、目标静态、三臂/tmp零模型prepare及一次必要build通过，哈希在协议。
现在先发布、正式prepare绑定实际源码/输入/配置，再由Root串行执行；四轨迹完成前源码冻结。
请求边界通过不代表模型增量语义或最终行动已经通过；缺ID工具异常仍未在此切片修复。

[维护输入隔离R1结果](MILAI_LOCAL_STATE_ATTENTION_MAINTENANCE_EVENTS_R1_RESULTS_20260927.md)完成4轨迹23消息：
原高耦合G/L/LRU各6/6、实际3/4/3行动正确；新增同文本不同事件LRU3/5、完整0/1。
37次实际写维护均无current_task，包括14次tool-only；新事件实际形成3→4，但Host收到正确4
仍在manage_memory写5，随后答5并实际reserve5。首断点在Host消费post-event State和当前增量，
非重复pending或维护再加一；L另保留过期未预约卡。新增108/135012/848；累计2412/3011206/18183。
保留修复、不再调维护措辞；缺ID可选工具错误观察另作局部源码切片。临时Astra只读定位新的
Host快照时点/事件关系冲突，候选尚未冻结；不删除真实当前消息、不把引用当正确性证明、
不重跑36条或宣布整体可靠。完整Goal与后续强基线/消融/公开任务/规模等工作仍ACTIVE。

下一两个薄边界已由同一Sol完成：默认原生manage_memory实例的update/delete缺ID、create带ID，
在已有参数校验入口返回真实error ToolMessage；同名外部工具不误套，底层Store ValueError仍抛出。
这处理了P3中断的确定性条件参数缺口，未改变工具schema或强迫模型成功恢复。

[Host快照诊断协议](../data/manifests/local-state-attention-host-snapshot-r1-protocol.json)仅复用现有
first-response probe，增加diagnostic_only原样view_text变体，避免诊断wrapper污染原请求对照。
固定失败trace54的原视图、时点/当前source身份说明、实际维护前State3，三种各两次，共6次
Host首响应，不执行工具/不读写Store，不把中间步骤称完整任务成功。首次错误请求只有system+
当前user，尚无旧assistant5；所以先定位快照基准/来源副本关系，再单列后续历史混杂。
24项相关单测、目标静态、6-job/tmp零模型prepare及一次build通过，哈希在协议；发布后正式
prepare与Root串行诊断。原生工具修复不被这个probe执行，不能用诊断结果声称它有语义收益。
即使时点候选有利，live采用前仍需stale/no-op State和tool-loop反例，不把引用/观察过等同于
变化已经正确应用。当前Host实时view和原始用户/工具消息尚未修改。

[Host快照R1结果](MILAI_LOCAL_STATE_ATTENTION_HOST_SNAPSHOT_R1_RESULTS_20260927.md)完成六次只读首响应：
原请求两次都提出写5；时点/来源身份说明两次使用4（一次memory提案、一次直接回答）；实际
维护前State3两次都提出写4。首次错误无旧assistant5，支持快照基准/来源副本歧义，但未分离
元数据与说明的贡献，且没有工具执行或完整任务成绩。新增6/8062/0；累计2418/3019268/18183。

[R2正确性反例协议](../data/manifests/local-state-attention-host-snapshot-r2-protocol.json)固定三断点×
无说明/同一说明，共6个首响应：注入实际旧State3且两臂同加真实initial2来源，tool-only回合的
正确State4与实际错误memory5，以及注入旧计划4但真实预约回执5。不得把时点当语义应用证明，
不得隐藏真实side effect。来源/当前消息相对于各断点无未来信息，原工具JSON保留，全部为
明确offline diagnostic，不作方法分数。无新源码改动或构建；发布后正式prepare并串行执行。
只有三个候选反例均正确才考虑另外冻结的live切片；否则不部署/不调措辞，继续LR及强基线，
当前Host liveview保持原样。完整Goal不因这六个诊断结束而关闭。

[R2正确性反例结果](MILAI_LOCAL_STATE_ATTENTION_HOST_SNAPSHOT_R2_RESULTS_20260927.md)已完成全部六首响应。
两视图在旧State下均提出3而非应有4，tool-only均沿错误memory历史答5；真实预约组均保留5和
真实ID、不重复业务，但把实际目的地S-2写成storage S-2。按原门槛不部署/不调时点说明，
Host liveview不变。新增6/11093/0；累计2424/3030361/18183，143源码及wire/ledger核对通过。
下一最小实现为LR：沿L全候选events-only维护，再复用LRU独立A；没有U模型调用。
先以原interleaved/partial小接线验证L/LR/LRU，原失败不替换，随后推进强历史/重建对照。
源码由同一Sol负责，Root继续冻结输入与评分；不同时修改Host或恢复旧v27部署。

[LR小接线协议](../data/manifests/local-state-attention-lr-wiring-r1-protocol.json)已冻结六轨迹36消息，
interleaved顺序LR→L→LRU，partial顺序LRU→L→LR，每格一次，保留原12消息/rubric。
实现只改controller/CLI/config/LSA窄测，LR没有U调用；L/LR维护请求、LR/LRU独立A请求的
mock相等性通过，并覆盖新卡读取及A失败后已写State保留。53项受影响检查、目标静态、两原
脚本LR零模型prepare及一次必要build通过，哈希在协议。发布后正式prepare绑定实际源码；
六轨迹期间不修改源文件。LRU候选限制措辞与L/LR仍有差异，在线分叉不能称纯U因果效应。

## 后期资源准备记录

[LR小接线结果](MILAI_LOCAL_STATE_ATTENTION_LR_WIRING_R1_RESULTS_20260927.md)完成六轨迹36消息：
L9/12、LR10/12、LRU8/12，完整分别0/2、1/2、0/2；生成tokens44872/53386/55262。
LR17次实际全候选维护且0次U，L/LR维护prompt和LR/LRU的A prompt核对相等。L/LRU首先
形成综合卡并在行动排除时丢简报事实；LR的三卡轨迹不构成纯A收益。三partial都同ID恢复成功，
但初始错误item_key保留失败。51视图/122来源绑定、ledger核对通过，无降级/容量/末pending。
新增150/153520/154；累计2574/3183881/18337。LRU仍提交全bank正文的93.0%，不扩大路由调参。
下一最小源码为所有匹配臂共同可用的合法历史接口及完整历史对照，复用公开checkpoint、
记录I/O/字节/时延；bank.events仅user/tool不能冒充含assistant的完整历史。不新增私有observer
档案或数据库。滑窗摘要、R、U=A、生命周期与公开任务等剩余项仍需后续实现/冻结/验收。

[共同历史小接线协议](../data/manifests/local-state-attention-history-wiring-r1-protocol.json)先固定
原两脚本×full_history/local_lr_history，共4轨迹24消息，源码已完成验证，尚未调用本批模型。
两新臂共同注册read_history，机械cursor/16384字节整回合分页；这会增加相同工具枚举分支，
不再称旧B1原工具合同。full_history不调用State控制器，自动提供完整真实既往会话与当前
前缀，超限由原HostCapacity显式记录，不另设隐藏字节截断；LR历史臂保留原维护/A，按需读取。
已发生但容量失败的过去前缀保留实际副作用与不完整状态，不补造ToolMessage。已有owner
tombstone则统一保守抑制新增历史读取/投影，其他owner不受影响；仍不声称物理删除完成。
Root源码放行范围限共同历史接口及这两臂，不同时实现滑窗摘要/R/U=A，不生成新公开样本。
71项受影响窄测、目标Ruff/Mypy/diff、四个/tmp零模型prepare和一次离线build通过；
构建哈希及命令见协议。full_history从公开checkpoint保留final assistant和完整工具链，
容量失败前缀以带实际序号的数据呈现；原消息不改写。新增Host prompt tokens及checkpoint
读取逻辑字节/CPU/墙钟计量。源码发布后正式prepare，四轨迹保持同一源码；不为发布重跑。

[共同历史R1结果](MILAI_LOCAL_STATE_ATTENTION_HISTORY_WIRING_R1_RESULTS_20260927.md)完成全部4轨迹24消息，
源码e44465b全批冻结。完整历史10/12、LR历史10/12，完整0/2、1/2；生成tokens18508与56198
（3.04倍）。16次full HTTP逐消息匹配原checkpoint，17次LR视图/43次来源绑定。两臂都未
自然调用read_history；分页/删除/不完整前缀只属离线检查，不冒充真实触发。两partial实际
found并同ID补标签，无重复预约；原始单数/下划线item_key失败保留。LR卡也有行动前称
attempted与部分提交称failed的语义问题。新增67/74706/108，累计2641/3258587/18445。
没有模型/容量/末pending异常。下一最小切片为相同合法历史权限的滑动窗口+摘要强对照，
先完成接口及少量接线；不等待旧Host命名错误都消失，不重跑本批或恢复旧v27部署。

[滑动窗口+摘要接线协议](../data/manifests/local-state-attention-window-summary-wiring-r1-protocol.json)
预注册原两脚本×window_summary/full_history，共4轨迹24消息。窗口固定最近2个完整完成
回合，当前ReAct前缀另保留；更早新驱逐回合与旧摘要最多每公开消息一次短摘要，正文上限
16000 chars，control2048/13与Host4096/12沿用。只在成功时同键提交摘要/游标；原checkpoint
不变。已知可选模型失败回退完整原历史，真实Store故障显式抛出。共享read_history及owner
tombstone屏蔽；不完整旧回合不吞掉。源码已完成：80项受影响窄测、目标静态、四个零模型prepare与一次离线build通过，哈希见
协议。尚未调用本批模型、未生成新题；四轨迹完成后按用户最新要求暂停并做总体报告。

R的局部设计冲突已由Astra只读处理，尚未实现或运行。竞争方案是借用LR已维护目录（含
needs/revision等动态信息，不能免费且不算独立不维护系统）与R自行维护薄目录。Root选择
后者作为后续系统对照：既有Store中只持久事项ID/短title/合法来源指针/机械版本，在线目录
更新、选择、公共历史读取和临时重建全计费；不存重建content/needs，无LR影子维护。title
仍是语义信息，不宣称目录免费。原始历史可在同预算继续分页，引用不是完整证据边界；不读
observer/gold/未来，Host共享原history/memory/business权限。分组分叉如实报告，不造同步器。
另以真实前缀冻结其实际目录/A集合，比较原持久正文与同历史临时重建；共同前缀目录生成
成本公开计入，边际成本另列。这只能隔离给定目录/集合下的正文来源，不能称完整A5或独立R
总成本胜利。当前Sol仍只实现window_summary，R留待其后，不因设计建议扩展本批执行范围。

已核对 [LangMem 官方 API](https://langchain-ai.github.io/langmem/reference/) 确实区分
memory manager、store manager 与普通 tools；强基线不能只代表后者。
LangGraph 官方 reference 页面本次抓取返回 unsupported content-type，实际本地锁定源码
`chat_agent_executor.py` 提供 v1 pre_model_hook/llm_input_messages，以本地 mock 接线为准。

[MemoryArena 官方站](https://memoryarena.github.io/)链接公开源码与数据，数据卡声明 CC-BY-4.0；
[源码 README](https://github.com/ZexueHe/MemoryArena)说明当前为 preview、各环境需独立准备。
已按需委派 Luna high 仅固定官方源码与数据元数据，不安装环境、不读取/下载题目正文。
Root 浏览 Hugging Face 数据卡时，网页自动呈现了 bundled_shopping ids 0–17 的问题/答案
片段；这些不得在后期无披露地声称未见。当前未选择样本，未接入 runner 或宣布该任务族可用。

[资源回执摘要](../data/manifests/local-state-attention-resources.json)确认复用既有
`reference-sources/contextual-v7/MemoryArena`，源码 SHA
`6cd9de14b71915e39ac742a20dc33785e14b6aab`；数据 revision
`da1a37c8b19280e18627ca01cf368195a5e1d92e`。只新增 4762 字节数据卡，JSONL 下载为 0。
源码未发现根级 LICENSE，子目录 MemoRAG 许可不能代表整个仓库；不复制其实现进入公开交付。

[RIMs](https://arxiv.org/abs/1909.10893)和
[HiAgent](https://aclanthology.org/2025.acl-long.1575/)分别已有稀疏模块更新、子目标工作记忆
研究；本方法不以“多个 State”主张首次性，后期仍需操作级比较与独立收益证据。

后续资源准备已取得 pinned `group_travel_planner/data.jsonl`（270组、ID 1–270，6165901字节）
及官方Drive航班CSV（304807007字节）。Luna仅用程序统计结构/ID/列表长度和哈希，没有向
Root展示问题/答案，没有选择样本、安装宽泛依赖或运行Agent/scorer。实际环境为5个CSV与
3个城市/州文本资源；6是工具数，固定HF revision并无nested_constraints_satisfaction配置。
[资源manifest](../data/manifests/local-state-attention-resources.json)已记录正式身份、哈希与
接触范围；上面的JSONL=0是早期回执，不再是当前库存。HF数据卡的CC-BY-4.0不自动覆盖
参考实现和外部CSV；这些内容继续留在ignored外部资源中，不进入Git。第二任务族尚未接入。

静态接入核查还确认：native ToolExecutor支持显式db_path及六个本地工具，离线PS/SPS/SR
scorer不调用LLM，但只遍历已提交项；未来冻结分母必须给失败/缺失项保留空plan，不能消失。
原loader默认拉最新HF且把answers与questions一起返回，native runner也有ground_truth判分/
judgement feedback路径；直接运行它尚不满足本项目runtime不读gold边界。后续薄适配器须
固定本地revision、隔离gold并明确反馈合同，保留官方给定base_person初始plan及原scorer公式。
这是静态可行性发现，不是已运行独立任务族；未读取任何任务正文或选择样本。

## 失败、决策与完成审核

Luna的[MERIT元数据暴露盘点](../data/manifests/local-state-attention-merit-exposure.json)补充确认
base_seed0–4均已暴露：1/2在v11已有完整或中断的模型轨迹，3/4在v23完成三臂。后续P5须全部
排除，不能只排0/3/4。当前最小未记录seed是5；本次没有生成、选择或查看新题正文，仍需在
P5源码冻结后另行预注册原生selection。记录之外的手动接触无法由元数据证明不存在。

每个失败阶段记录 Observed、Expected、实际链、首断点、至少两种解释、最小区分实验、
通用修复与反例、混杂、完整成本和 Continue/Simplify/Redesign/Stop 理由。
保留全部失败、重试、退化、空维护和观察开销；不拼接最好轨迹。

结束前逐项审核原规划 §4–11、§12 阶段、§13 强对照、§14 六消融、§15 泛化、§16 指标/
重复、§17 预算曲线、§19 六组测试、§21 证据链、§22 五工作包。条件项须有证据决定，
未运行的必要项不能称完成。第二模型/公开独立任务族尚缺资源时如实 NOT_RUN，
继续可独立推进工作，不拿资源缺口关闭整个 Goal。
源码/config/合成输入/rubric/精简结果/文档由 Luna 发布；私密 DSN、raw 轨迹、DB、venv、
weights/cache/build 留在 ignored 目录。每次发布核对远端 SHA 和预期工作树。
