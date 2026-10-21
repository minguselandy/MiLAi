# 训练数据泛化计划执行记录

2026-10-21。完整目标 **ACTIVE / 未完成**。执行依据为
[原计划](MILAI_TRAINING_DATA_GENERALIZATION_PLAN_20261021.md)，原文复制留存，原目录文件未修改。
该计划中的“本轮已完成”是另一环境的历史说明，不能代替本机当前验证。

## 续次执行 v4：执行后快照与分支恢复

实现提交 `eb112254`，缓存重入修正 `490c683e`。新增可选的真实决策快照：

- `tools/run_host_intent_retrieval.py --capture-control-steps` 同时保存初始调用与每个实际后续决策的
  Store、读预算、模型调用额度和执行器状态。SQLite 使用既有在线 backup。
- `EvidenceOperations` 保留候选与已读取索引、observed/delivered/known 材料、搜索和读取尝试、
  View 槽位/版本、历史页和来源分页状态；回调函数不序列化。这些私有快照不进入策略输入。
- `tools/prepare_view_feedback_branches.py --include-control-steps` 纳入实际已捕获的执行后状态，
  按原可观察条件加“操作前/后、已有交付”分层；直接导出 masked `raw-selected-states.jsonl`。
  可选动作和参数不改写，legacy 交付与 observed/delivered 分离模式都可使用，不再以 W4 字段存在性筛除。
- 既有 frozen replay 自动恢复 `control.json`，核对实际 before、offered actions、请求绑定与剩余额度。
  保留原绝对步骤预算，干预和共同 continuation 从恢复点相对计步。已经执行的前缀不重新 SEARCH、READ
  或调用模型生成 View；已知材料也不重新读取计费。
- 原始 Host 完整读出 frame 仍可用于替换实际回执。原失败、错误 View 和不完整回执均保留；
  恢复后的完成结果仍支持幂等缓存重入。

实际 post-operation 文件形如 `frozen-retrieval-calls/CASE/steps/step-N/{call.json,control.json,before/}`。
只支持真实保存了执行器/Store 快照的决策点，不能凭历史 before 投影或动作 trace 补造任意状态。
分支使用新声明的共同后续策略，不声称恢复任意 Agent 隐状态。
回执 usage 包含原逻辑前缀；`replay.json` 的 `restored_prefix_usage` 与
`prefix_operations_reexecuted=0` 将其和本次实际执行成本分开。原前缀/模型费用仍属于原收集，不能重复计费或当作免费。

机械验证使用真实 SQLite/Store 与脚本化模型回调，覆盖 SEARCH/READ 后恢复、恢复后实际 READ、
生成 View 后恢复、known evidence、分页与可见性、剩余读/生成额度、Host readout、原失败保留和缓存重入。
特意构造的错误 View 原样保留，再由真实 READ 分支取得原文，证明没有用理想状态修复旧结果。
核心回归 74 项通过；后续 Host-frame 套件 21 项、选择接线 15 项、最终专项与缓存回归 28 项通过。
这些集合重叠，不相加。Ruff 11 文件、mypy 9 实现及两项依赖边界通过。
8 项可选 Coalent 原生核测试因未配置本地核心路径跳过；该外部方法没有有限动作回放支持，未宣称新增支持。
早期测试曾误把已关闭错误回执等同异常中断，另有分页测试误设删除末页后仍有 next；
最终检查保留真实状态区别和原分页行为，没有为测试修改实验结果。

**此功能尚未用于新的真实模型分支实验。** 当前 480 位置采集仍使用冻结 `890dbdd0`，没有热更新，
只有初始调用快照；未来实际验收和自身轨迹采集须显式使用新代码与上述选项。
Lab 内部快照格式与回放参数新增，Product Schema/API/权限/Canonical 未改变。

第一批 32 来源组的 122 位置已关闭：87 程序 completed / 35 failed，187 个实际初始调用捕获。
308 次 generation HTTP，1,010,341 known/charged tokens，新增 unknown=0，embedding=0；
整子进程墙钟 4,008.007938 秒、CPU 187.933329 秒，CPU 尚未结算（父队列仍运行）。
这些程序状态不是语义任务成功率，尚未查看未审来源的答案/动作来标注。
20:51:05 北京时间快照：父 PID1131060/exec93727 和 batch1 子 PID1381395 均存活，
全队列已执行 161/480；实时状态以 driver 和实际进程为准。

来源先审推进到 6/128 族、12/240 行：8 个池不足、2 个支持、1 个有术语限定的支持、
1 个仅支持限定关系的替代解释。这不是全体数据的错误率，也不直接生成 HANDOFF 标签。
已从这 6 族的 24 个关闭位置导出 177 个真实状态（23 个位置有决策、146 个状态在真实操作后），
所有 gold 仍为空；实际请求/状态见证评审待完成。历史 trace 不因此升级成可恢复的后续 Store 快照。
见 `source-expansion-v1/source-review-progress-v3.json` 与 `source-expansion-reviewed-six-families-states-v1/`。
没有启动第二个真实模型任务或在活动队列期间结算离线费用；既有 v1/v2 结算保持关闭。

## v3 历史快照：反馈 dev 完整闭合、冻结模型诊断、新来源采集中

代码提交 `890dbdd0`。已完成 16 状态 / 8 来源组 / 48 pair 的独立反馈 dev；
6 个失败 readout 的 answer 比较仍为 unknown，没有更改程序状态或补答案。
先保存全部质量评审，再沿用既有协议，对质量 tie 应用五维实际成本的分量支配规则：
retrieval generation requests/tokens、acquisition operations、READ operations、完整回执 tokens。
三个目标标签由 tie 变为较省成本的一侧；方向标签与 unknown 不变，不求异类成本的加权和。
所有原评审版本保留，错误引句、角色归属、过度推断与 View 缺陷单列。

| 最终 dev 覆盖 | 有方向状态 / 16 | Directional / tie / unknown pairs |
|---|---:|---:|
| answer | 11 | 21 / 7 / 20 |
| delivery | 16 | 39 / 6 / 3 |

实际调用过的不同绑定仍分别保留；未执行动作没有成为负例。
新 dev 已写入 feedback 与 continued-CE 数据目录，逐条确认原 74 train、860 old-dev 完全相同。
独立 dev 数据位于 `artifacts/generalization-20261021/feedback-dev-final-v1/feedback.jsonl`，
匹配目录为 `feedback-fitting-with-dev-v1/`。这不是一次新拟合。

**Common-support。** 新 dev 的两目标共有 21 个方向 pair，21 个方向全部相同。
旧 train 的 37 feedback + 37 replay 保留为 74 个状态；共有 25 对，24 同向、1 反向。
新诊断入口 `tools/analyze_feedback_support.py` 保持状态顺序、ID、replay 和事件权重，
共同 pair 为空的状态也不删除。完整池仍是主实验；交集只作条件诊断。
当前 dev 不能证明不同信用分配信号，它首先揭示方向覆盖差异；39/21 不能解释成梯度同比放大。

**真实冻结模型评价。** 五个预声明最终 seed0 检查点完成 80 次原生 GPU 前向，没有梯度更新。
实际使用冻结 `890dbdd0`、GPU2、shared 投影、既有 MHA fastpath=False、16384/head2048 条件。
所有模型收到完全相同的 16 个 state/questions；最长 7,761 tokens，全部低于 8K，无截断。
同一次预测评分两目标，另按状态再按 family 平均，并披露方向覆盖和 pair logistic loss。
这些 loss 不代表校准后的成功概率。本批没有超过 8K 的样本，不能据此完成长输入对照。

| 冻结检查点 | answer 正确 / 21 | delivery 正确 / 39 | answer family macro | delivery family macro |
|---|---:|---:|---:|---:|
| T1 main | 7 | 20 | 31.25% | 53.125% |
| T1 operation control | 7 | 20 | 31.25% | 53.125% |
| continued CE | 7 | 20 | 31.25% | 53.125% |
| answer | 15 | 31 | 70.833% | 83.333% |
| delivery | 15 | 32 | 70.833% | 85.417% |

**反思与下一步。** 排序分数上升并不证明决策更适应状态。前三个模型在全部 16 状态按
SEARCH > HANDOFF > REFRESH_VIEW 排序，delivery 在全部状态按 SEARCH > REFRESH_VIEW > HANDOFF 排序；
delivery 的第一动作和绑定仍全部是同一个 `search_0_8`，与 T1 完全相同。
对所有六种固定类型排序作穷举诊断，固定 SEARCH > REFRESH_VIEW > HANDOFF 已精确复现 delivery 的这批排序分数。
这不是执行了六种 Host 控制器，也不是选择一个保留集赢家；它表明当前分数增益可以来自动作先验。
answer 有三次第一动作/绑定变化，其中 C03 的 `search_0_16` 和 E08 的 `search_2_16`
没有在原分支池执行，后果仍未知；不能把相同 SEARCH 名称当成相同参数。
因此继续优先执行后状态、known-evidence 条件变化与参数分支，不据这批静态结果宣称 Host 改善。

评价输入、计划、结果和审计位于 `feedback-checkpoint-evaluation-v1/` 及其同名 plan。
总编码输入 266,675 tokens；五个 evaluator 直接记入原账本 CPU 71.306349 秒，顺序进程墙钟合计
58.473457 秒（含加载，不是独立测量的 GPU kernel 时间）。源码诊断 55 项测试通过、零跳过，
Ruff 5 文件、mypy 3 实现及两项依赖边界通过。此前所有历史权重与结果保持原样。

**128 新来源实际采集已经启动。** 已固定全部 240 请求的两种原接口，共 480 位置；
按原来源顺序分四个 32-family 批次，分别 122/116/122/120 位置。
每请求设置和既有每进程队列 600 requests / 8,000,000 reserved tokens 沿用；不增加限额、不重试。
父进程 1131060 / exec93727，首子进程 1131065，冻结方法 `890dbdd0`。
19:30:34 北京时间快照：batch0 13/122 已执行（11 completed / 2 failed），父子均实际存活。
实时状态以 `source-expansion-collection-v1/driver.json` 和对应子 driver、`/proc` 为准；不要重启。

来源先审明确为：先保存原问题与完整原文池的语义评审，再查看对应 native reference 答案或模型产物。
固定策略采集可与输出盲评并行，不赋予自动梯度资格。已审 2 族 / 4 行；其余来源的采集进度只显示计数，
不向评审显示答案或动作结果。所有未知与失败仍在最终分母中，不按模型结果补抽。
此前“输入准备、不用于当时模型分派”的状态由明确的新采集协议接续，
不代表未审来源已取得训练标签。见 `source-expansion-collection-plan-v1.json`。
已从两族已审来源的 7 个关闭位置导出 46 个真实 train 状态，38 个在实际操作之后；全部 gold 仍为空。
这是 reached-state 覆盖，尚不是任意执行后状态的同 before 分支重建，也没有启动研究拟合。

在上述采集启动前，12 个准备/诊断阶段 CPU 10.304391 秒已一次结算于 `compute-settlement-v2.json`，
没有重复计入 evaluator 的 71.306349 秒。v1/v2 结算均已关闭；当前模型任务期间不做离线结算。
新 source review 与状态导出费用另记，人工语义工作及未计时开销未知。
完整规模曲线、参数/辅助对照、执行后重建、STATE、因子实验、Host 终点和多 seed/外部确认仍未完成。

## v2 历史快照：真实反馈 dev 与新来源边界

上一目标回合为实质进展（接口、数据与提交），本次重验工作区和进程后继续。
已用冻结源码 `9f153b68` 执行全部 **48 条真实 dev 分支**：48 个工具执行完成，
48 个 before/actions 相等；Host readout 为 **42 completed / 6 failed**。
执行句柄 71390 正常返回 0，PID 956232 已退出；不重启或重试。
6 个失败均为已知用量的不完整输出；answer 比较保留 unknown。

整个执行包含 64 次 generation HTTP（含 View 创建与 Host readout），
287,903 known/charged tokens，generation/embedding unknown 增量均为 0。
嵌套整驱动墙钟 896.151687 秒、CPU 94.711639 秒；不能将嵌套计时再相加。
`feedback-dev-review-v1/closed-execution-costs-v1.json` 的逐 case 费用与连续账本差额已对齐。
前 **8/16 状态、4/8 来源组、24 个 pair** 已来源评审并编译为独立 dev，仍是部分池，
不是完整开发集或独立确认。原始记录和剩余 8 状态的完整评审卡均已保存。

实际差异包括：SEARCH 交付完整原文后 Host 仍可能误述历史状态；
REFRESH 可给出正确内容却将模型节点当成用户要求的原文引句；
在 C03 更新状态，SEARCH 取回旧自生回答而遗漏新修正，REFRESH 传递了正确 9:45 信息，
但仍未交付修正原文。部分改进不等于完整成功；全回答缺陷、View 缺陷与目标子指标分开留存。
状态权重与原训练池没有因新增 dev 改动，没有研究模型拟合或 checkpoint 选择。

新增来源继承了后续全局保留集划分：330 候选族缩为 **280 族 / 3,978 条可用 metadata**。
固定 seed0 为各族选择最大 native-step 代表题并保留允许的变体；对全部候选核对既有
698 条保留来源、270 条先前评估来源及 source-selection-v2 dev 的问题、目标文本/池、目标标题。
protected 正文只由边界代码比较，没有输出给方法或评审。
204 族通过，按预声明顺序选出 **128 新族、240 原始记录**，无不足、无结果驱动替补。
新旧合计 256 个登记 train 族，旧 32 个 dev 族保持固定。
目标标题连接检查覆盖旧 71 个 Wiki 来源族与新 128 族；其余旧 57 个来源族没有原生标题记录，
保持原登记单元。因此 256 个连通组不证明跨领域语义完全独立。

复用现有 `prepare_host_intent_t1.py` 生成 128 个新 history / 240 个公开请求；若采用旧双接口，
对应 480 个待采集位置。逐条验证问题与原始段落不变，native answer/support/answerability 未进入公开输入。
这是输入准备，**新增训练操作轨迹仍为 0**。来源先审完成首族两条记录，均缺少完整的
所有权/包含城市关系；没有据此直接标 HANDOFF 或借 native QA 答案补标签。另 238 条待审。

新增通用边界/来源准备测试及 Unicode 贯通测试通过（最新窄测 7 passed），较宽准备回归
32 passed / 4 skipped（该解释器缺 torch；没有修改 tensor 路径，首轮 67 项 GPU 验证保留）。
Ruff 4 文件、mypy 3 实现文件及 package/tools 边界通过。原文/轨迹 JSONL 准备与导出也接入物理行读取。

模型进程退出并取得原账本锁后，19 个不重叠计时阶段的 **106.288865 CPU 秒**已一次结算，
见 `artifacts/generalization-20261021/compute-settlement-v1.json`。HTTP tokens 未重复入账，
原限额与 token 计数未改；旧 pending35 未动。人工语义评审、未计时调试、测试/GPU 诊断和首次下载开销仍未知。
这个结算文件已关闭，后续阶段不得追加或重复结算。

本次新实现是 `tools/prepare_operation_source_expansion.py`；完整研究目标仍 active。
下一步先完成余下 8 个反馈状态的来源评审、common-support 统计和完整 dev 集接线，
再推进新训练源余下评审与实际状态采集、执行后分支重建、嵌套来源与完整训练/Host 对照。

## 工作区与边界

用户提供计划所在的 `jev-read-decisions-20261016` 工作区仍是较早的研究代码；
当前实现工作区为 `/cra/memory/mx_memory/MiLAi-worktrees/training-generalization-20261021`，
分支 `feat/training-generalization-20261021`，基于计划引用的 `248aa05d`。
本机及远端分支未找到计划所述未发布修复分支，因此按现有代码补齐接口。
Git 版本标识只用于定位；没有运行 SHA 或替代内容指纹校验。

旧 v4 已暂停的 Coalent 队列没有重启，旧分数和首次失败没有改写。
本轮授权范围是新训练数据泛化计划。没有推送、合并、部署或改变共享服务。
Product、公开 Schema/API、权限和 Canonical 行为不变。所有原始数据、权重和完整日志留在 ignored artifacts。
真实研究继续使用原 `MiLAi/MiLAi-Lab/artifacts/ser-v20/budget.json`；单元测试使用隔离的临时测试账本。

## v1 已完成并验证

1. **独立反馈 dev 接口**：分支准备和反馈编译显式传递 train/dev，原 split 不重标。
   反馈训练准备将同一 dev 写给反馈与 continued-CE 两臂；检查全部 old_train（包括 masked 行）
   和反馈 train 的 family，报告与旧 dev 的重叠，保留原 exposure。
   Trainer 对同一次预测分别评分 answer/delivery，独立计数与记账，不改变旧操作 dev。
2. **学习曲线与参数范围**：支持 `--eval-at-updates` / `--eval-every-updates`、
   `--encoder-lr` / `--head-lr` / `--freeze-encoder`。
   自定义评估点切分同一个完整优化序列，自动包括终点；权重留在 `checkpoints/update-N`，
   最终仍写 `checkpoint`。冻结 encoder 不进入优化器，训练阶段保持 eval 模式。
3. **公开辅助源**：Promptriever 原始 train 前 2,000 行已取得，20 次成功请求、无重试或替补。
   下载响应总计 28,930,519 字节，raw JSONL 29,251,421 字节。
   全部原始候选先按 base query、规范化 query、docid、literal text 连通分组，再限制负例数。
   得到 912 个连通组，730/182 train/dev；候选 3,979/961，共 4,940。
   四类身份跨分区交集均为 0，只证明当前 intake 的隔离，不证明外部分布或预训练隔离。
   来源及非商业研究条款沿用[官方数据卡](https://huggingface.co/datasets/samaya-ai/msmarco-w-instructions)。
4. **Unicode JSONL**：按物理行读取；真实 train 的 3,979 行在旧 splitlines 下为 3,980 段，
   dev 的 961 行为 962 段。全部候选通过既有 mixture CLI；state/questions/gold 逐条相等，
   query、instruction、passage 与 raw 原文相等。解释、教师分数及离线身份不进入模型输入。

入口：`tools/prepare_promptriever_applicability.py`、`tools/prepare_retrieval_mixture.py`、
`tools/prepare_view_feedback_branches.py`、`tools/prepare_retrieval_feedback.py`、
`tools/prepare_feedback_training.py`、`tools/train_bounded_laya.py`。

本轮最终受影响测试 **67 passed / 0 skipped / 0 failed**。使用现有 cuda-env 的 torch 2.7.0+cu126、
Laya 0.4.8，显式 `CUDA_VISIBLE_DEVICES=2,3`。包含真实梯度、原生训练 CLI 的微型模型两更新、
全参/冻结范围、保存重载、双目标共用预测，以及 Unicode 源到 mixture/evaluator 路径。
微型合成测试不是研究模型训练，更不是泛化效果证据。
Ruff 15 个改动 Python 文件通过；mypy 10 个实现文件通过（follow-imports=silent、ignore-missing-imports，
不声称完整外部库类型验证）；package/tools 边界及改动空白检查通过。
已有 tools 边界中 6 项历史私有依赖维持原状，本轮没有新增。

验证目录：`artifacts/generalization-20261021/validation/pytest.xml`。
真实辅助输入：`artifacts/generalization-20261021/promptriever-first2000/trainable/`。
下载计划、响应、分组、统计及逐条原文比较均在其父目录。

## v1 准备快照

**反馈开发集首轮准备快照**：从已关闭的 D fixed-context 真实捕获准备了 8 个 dev 来源组、16 个初始状态、
48 条 offered-action 分支；每组 2 状态、固定 seed0、共同 fixed-context continuation 两步。
没有读取模型结果选择状态。产物 `artifacts/generalization-20261021/feedback-dev-branches-v1/`。
这 8 组是已暴露开发来源。首轮准备时新反馈标签数为 0；当前执行和部分评审结果见上方续次记录。
尚未支持任意执行后状态回放，不能把初始状态捕获冒充该能力。

**操作来源扩容**：重新核对 17,975 条候选 metadata 和两套各 39,876 条的原 family 分配，
native row/question/family 与 train 身份一致，且两套均 included。
原 T1 操作池为 128 train 来源组（126 组有标签）、固定 32 dev 来源组。
444 候选族中 64 已进入 T1；扣除既有非训练分配、历史 admission 拒绝族和 T1 显式排除后，
当时剩余 **330 个候选族、14,412 行**，仅有 metadata 资格；后续边界审核和选定 128 族见上方记录。
仍须完成新池的
后续 exposure 并完成来源评审和实际工具采集；没有直接当成获准训练清单。
产物 `artifacts/generalization-20261021/source-pool/`，没有新增操作轨迹或标签。

## 对完整计划的验收清单

| 原计划要求 | 当前证据 / 状态 | 尚需证明 |
|---|---|---|
| §5、§9 P0 数据入口与 Unicode | 已验证真实 4,940 候选及 67 项测试 | 后续研究数据继续沿物理行入口 |
| §5.1、§9 P0 独立反馈 dev | 16 状态完整编译接线，五个冻结检查点评价完成 | 后续新拟合中同步评价与效果确认 |
| §6.1 64/128/256 嵌套来源集 | 128 新族、480 位置采集中；12 条来源已审 | 完成来源/实际请求评审、操作标签、固定 dev、嵌套集合 |
| §4.2、§9 P1 STATE train | 复用既有公开源码及入口待开展 | train 对象变化装入记忆环境、实际 View 建立/刷新/交付 |
| §6.1 524 更新的 32/64/128/262/393/524 曲线 | 接口和序列不变性已测试 | 研究模型同步固定 train/dev 诊断与完整成本 |
| §6.2 全参、低 encoder LR、冻结 | 功能与梯度测试通过 | 相同操作 draws 的真实对照 |
| §6.2 辅助阶段后相同操作训练 | 辅助输入已准备，不自动加入主配方 | 预声明辅助预算、相同最终操作序列与 dev |
| §6.2 联合配方 | 原结果保留 | 若再研究，另列固定操作暴露/固定总资源口径 |
| §6.3 32/64/128 反馈来源与自身轨迹 | 尚未扩充 | 规则/当前策略/基线的 reached states，固定每组配额与 replay |
| §6.3 执行后分支重建 | 已实现并通过真实 Store 的机械端到端检查 | 新代码冻结后的真实模型捕获/分支验收与扩充反馈池 |
| §6.3 common-support | dev21 同向；旧 train25 含1反向；同状态/权重导出 | 新扩充反馈池与实际匹配训练对照 |
| §6.4 长上下文 | 原完整输入审计保留 | 8K 内/更长、支持位置/候选数分桶，不静默截断 |
| §6.4 E3 等信息文本 | 旧入口存在，未新训练 | 相同信息、相同条件的实际匹配训练与评价 |
| §6.5 checkpoint 选择与统计 | 尚未选择研究 checkpoint | 训练前固定 family macro 规则，组级配对 bootstrap、跨 seed |
| §6.5 Host 主终点与五层成本 | 未新运行 | 固定 Host/材料/预算的来源忠实完整成功，含未调用和失败分母 |
| §6.6 结果驱动方向 | 尚无新模型效果 | 按实际曲线决定扩源/优化/简化，允许复杂方案不胜出 |
| §7.1 证据增量价值 | 已保留真实分支与参数机制 | known-evidence 对照、即时增量及共同 continuation 结果 |
| §7.2 组合泛化 | 未新运行 | 意图 × 已知证据 × View 新鲜度 × 预算的完整因子组 |
| §7.3 View 维护成本 | 未新运行 | 固定上下文/规则/Jev/去 View/等信息文本，创建刷新复用总成本 |
| §8、§9 P3 外部分布与 seed0/1/2 | 未新运行 | 保护集合、冻结方法、修改协议标识、不用 test oracle 学习 |

计划 §2 的旧统计和 §3 的架构边界沿用为历史参照；没有以新代码或辅助分数替换旧 Host 结果。
HotpotQA 是后备来源，不为扩大数字而机械重复引入 Wiki QA。
首轮无研究模型训练或真实 Host 新调用；续次已有 48 次条件 readout、80 次原生前向和正在进行的
新来源 Host 采集，仍没有研究模型拟合。
GPU 单元验证不能代替研究训练或任务效果。

下一阶段继续当前新来源采集和来源评审，完成执行后分支重建，继而冻结嵌套来源与训练矩阵。
模型运行前再次核对进程、现有服务容量、原连续账本、实际输入长度和完整来源边界。
已有 19 个准备/执行阶段现已一次结算，具体见上方记录；后续费用另记。
人工、未计时调试与最初下载开销标为未知，不向已结算的 pending 文件重复写入。
