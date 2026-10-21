# 训练数据泛化计划执行记录

2026-10-21。完整目标 **ACTIVE / 未完成**。执行依据为
[原计划](MILAI_TRAINING_DATA_GENERALIZATION_PLAN_20261021.md)，原文复制留存，原目录文件未修改。
该计划中的“本轮已完成”是另一环境的历史说明，不能代替本机当前验证。

## 续次执行：真实反馈 dev 与新来源边界

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

## 已完成并验证

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

## 已推进但尚未完成

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
| §5.1、§9 P0 独立反馈 dev | 48 分支完成；8/16 状态已评审编译 | 余下来源评审、完整 dev 接线、训练期效果 |
| §6.1 64/128/256 嵌套来源集 | 128 新族边界通过，240 请求准备；仅 2 条来源已审 | 完成来源评审、实际状态覆盖、固定 dev、嵌套集合 |
| §4.2、§9 P1 STATE train | 复用既有公开源码及入口待开展 | train 对象变化装入记忆环境、实际 View 建立/刷新/交付 |
| §6.1 524 更新的 32/64/128/262/393/524 曲线 | 接口和序列不变性已测试 | 研究模型同步固定 train/dev 诊断与完整成本 |
| §6.2 全参、低 encoder LR、冻结 | 功能与梯度测试通过 | 相同操作 draws 的真实对照 |
| §6.2 辅助阶段后相同操作训练 | 辅助输入已准备，不自动加入主配方 | 预声明辅助预算、相同最终操作序列与 dev |
| §6.2 联合配方 | 原结果保留 | 若再研究，另列固定操作暴露/固定总资源口径 |
| §6.3 32/64/128 反馈来源与自身轨迹 | 尚未扩充 | 规则/当前策略/基线的 reached states，固定每组配额与 replay |
| §6.3 执行后分支重建 | 未实现 | 实际状态和 offered 参数相等、共同 continuation、无隐含负例 |
| §6.3 common-support | 未运行 | 两目标共同有方向的同 pair 交集、同抽样权重、方向分歧计数 |
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
首轮无研究模型训练或真实 Host 新调用；续次已有上述 48 次条件 readout，仍没有研究模型拟合。
GPU 单元验证不能代替研究训练或任务效果。

下一阶段先完成新来源 admission 和实际反馈 dev，继而冻结嵌套来源与训练矩阵。
模型运行前再次核对进程、现有服务容量、原连续账本、实际输入长度和完整来源边界。
已有 19 个准备/执行阶段现已一次结算，具体见上方记录；后续费用另记。
人工、未计时调试与最初下载开销标为未知，不向已结算的 pending 文件重复写入。
