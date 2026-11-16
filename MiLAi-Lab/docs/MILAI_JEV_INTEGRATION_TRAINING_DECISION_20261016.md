# MiLAi：开源 Jev 类模型的接入与训练决定

日期：2026-10-16｜任务：决定接入位置、选择开放权重、定义训练与使用路径。

## 0. 本次决定与执行边界

**主模型选择 `convaiinnovations/laya-multilingual`；首个接入点是 Writer 之前的既有 Impact。训练“当前事件作用下的旧单元角色”，随后研究“支持局部 Writer 的必要边界证据”。**

新模型替代原 Impact，不与原 Impact 串联复核；不替换开放式 Writer；不首先接管是否保存、业务权限或最终答案。

本次重新读取 MiLAi PR #124、实际适配源码和 Laya 官方训练、部署资料。PR #124 仍为 open/draft，head 为 `dc431c066ed96e004f009a6b28bf74ff51e5f84f`，已存在薄适配，不需要重新实现同名模块。[1–2]

本文件是确定后的实施方案，不是训练完成报告。本次没有修改远端仓库、下载权重、启动训练或取得模型效果；当前会话运行环境实际为 PyTorch 2.10.0+cpu，CUDA 不可用，未安装 Laya/Transformers，也没有已挂载的模型目录。此状态不说明用户其他机器没有 GPU。

## 1. 为什么选择这个模型

Laya 是开源 Jev 类类型化决策实现，不是 TypeSafe 原版 Jev 权重。本次选择的多语言 checkpoint 模型卡标注 Apache-2.0、约 322M 参数、mmBERT-base 骨干，适合把中文和中英混合材料纳入同一域内训练。[3]

选择依据是开放权重、公开训练入口、多语言材料与已有 MiLAi 适配，而不是宣称它已经具有最佳 MiLAi 能力。官方模型卡也提示默认概率未经校准、通用零样本工作流能力有限。[3]

实现上沿用现成编码器与决策头做领域微调，不从零预训练，也不默认另建三分类头。上游原生训练支持完整微调及冻结编码器只训头；本次不把旧 Qwen 生成式 LoRA 当作 Laya 训练结果。[4–5]

**固定一个 checkpoint 做主实验，不启用按语言或任务自动换模型。**否则混合数据的训练效果会与模型路由因素纠缠。英文专用或更大的开放决策模型可以作为后续同任务对照，不进入首轮主链。

## 2. 接入位置及职责分工

```text
当前真实来源 + 已读取的旧记忆候选
                 ↓
        Laya Impact（替换原 Impact）
                 ↓
             roots / preserve
                 ↓
      既有 plan_regions / 支持组织
                 ↓
    第一阶段：完整输入 Writer
    第二阶段：修改区域 + 必要只读边界 Writer
                 ↓
      既有来源、版本与 MemoryService 提交
```

| 位置 | 本次决定 | 原因 |
|---|---|---|
| Writer 前的 Impact | 首个实际接入和训练任务 | 候选有限、合同明确，直接关系到状态维护，已有代码边界 |
| Writer 的必要只读边界 | 第二个研究任务，与局部输入一起实现 | 使决策不只是短输出，而能降低后续生成工作 |
| Reader 选材和 STOP | 暂不同时接入 | 动作价值依赖当前证据集合和回答后果，需要另一套标签与实验 |
| 全局是否保存、完整抽取、Writer、权限、最终 Judge | 首轮不交给 Laya | 不能把新事实生成、业务授权和效果评价混进一个分类任务 |

这不是断言 Impact 是全部错误的最大来源。必须允许无独立 Impact 的单步 Writer 更好；目标选对而 Writer 仍错时，应改变投入方向。

### 2.1 精确代码位置

复用 `MiLAi-Lab/src/milai_lab/methods/laya_impact.py` 的 `LayaImpactClient.wrap(existing_model_call)`，在现有 benchmark/Host 的共同模型调用边界安装一次。它只拦截 `impact` 和 `impact:<child>`，其余调用交还旧 provider。[2]

`maintain_event` 中的 Impact 之后仍由既有 `plan_regions`、作用域 schema、Writer 和 MemoryService 处理。不要增加“原 Impact → Laya 复核 → Writer → 第二审核模型”。

### 2.2 首版标签不变

| 标签 | 语义 | 返回 |
|---|---|---|
| `direct_root` | 当前事件直接更正、撤销、限定或改变的旧含义 | `roots` |
| `preserve_successor` | 相关后继有明确的不相交作用域或仍然有效的独立支持，不应连带改写 | `preserve` |
| `other` | 既非直接目标，也非明确应保护的后继 | 不加入前两者 |

同一事件可以有多个 root。每单元做三选一，但输入必须包含判定它所需的共同事件和关系上下文，不能退化为脱离上下文的短句分类。

`other` 不等于“没有价值”，`roots=[]` 不等于“无需保存”。新事件完全新增事实时，Writer 仍需有创建机会。来源不足的含糊样本不自动标成 preserve 或 other；首版训练遮罩该项，评价保留问题，后续再明确是否需要补读动作。

正文保持与支持保持不同：结论仍成立，支持关系可能仍需要更新。复用现有支持更新对象，不能将 preserve 简化为“所有相关字段永久不动”。

## 3. 第二阶段：学会交付足够小、但语义充分的 Writer 输入

目前适配只替换控制器，不能把完整候选 Writer 宣称为局部计算。第二阶段要将两件事分开：

- **W：可写目标及需要重新解释的区域。**
- **B：不必修改，但必须读到的条件、例外、替代支持和来源边界。**

边界阅读角色与 `preserve_successor` 不是同一标签：某个被保留的单元可能必须读，也可能不必读；某个 `other` 单元可能正是重要的前提。不要在原三分类中硬塞一个互斥的 `context` 类。

首版继续按现有关系组织边界，隔离模型替换效果。边界学习后续可使用同一个 checkpoint 的独立问题／任务标识，条件是“当前事件、候选材料和本次拟议 W”。它是输入选择，不是写后审核。若需要再次模型调用，必须记录该成本，而不能宣传为一次整体前向。

研究标签来自少量受控范围干预：固定真实 before、当前事件和 Writer，比较目标独读、加入共享条件、加入替代支持、完整候选。使用实际后状态的目标更新、非目标保持、时间作用域和来源忠实性评价范围是否足够。完整输入 Writer 也可能答错，不能自动当作 gold。

保留完整内部绑定 map，另外构造模型可读投影。不能将部分记录伪装成完整记录后整体替换；`prior_context`、schema 描述和重复整版正文也需要检查，避免隐藏的全量输入。

**当前 `semantic_delta_v1/v2` 禁止 `dependency_updates`。**首轮沿用已兼容的命题 Writer；差分保持独立对照，不删除兼容检查来“接通”。此事实来自迁移文档的固定源码核查，本次没有重跑该组合。[8]

## 4. 训练数据：从实际事件学习，不从旧预测自我复制

### 4.1 数据来源

优先从实际形成状态、当前来源、已有逐项状态审阅中导出事件。旧 Impact 输出可以作为候选标注或错误样例，但不能未经来源核对直接当正确标签。旧长 JSON 训练集只是素材来源，必须重新标注为短决策任务。

起步可以组织约 200 个有来源依据的源事件做学习诊断，再按未见家族结果扩展；这是建议规模，不是现有样本数量或统计充分性的承诺。只有十几条历史时，不将大量改写包装成数百个独立事件。

运行输入和训练输入应共享同一 payload 构造函数：实际日期、delivery、单元别名、问题措辞与 criteria。`family_id`、划分信息、作者审阅与未来答案留在数据元信息，不进入 `state`。

上游接受 JSONL `{state, questions, expected}` 或分布标签 `gold`。MiLAi 可以直接使用这个格式，保持一行一个事件及多个单元问题。[4]

### 4.2 高价值对照

训练分布应覆盖同主题但不同对象、单根与多根、完全新增、撤销例外而保持一般规则、AND 前提丢失、OR 替代支持仍在、未来生效与历史更正、共享否定／数量、同名对象、缺失来源等。

“支持丢失”不自动标为“结论为假”；“考虑修改”不自动标为“已经修改”；当前请求的执行限制不自动改写持久事实。

实体替换、日期变换、别名排列、选项顺序变化必须同步修改标签。独立事件顺序交换只用于真正独立的事件。测试未见组合时，不将同模板改写混入训练。

### 4.3 划分必须先于展开和增强

按历史／源事件家族先划 train、dev、calibration、test，再展开单元和增强。初期可以按 70/10/10/10 分配家族；家族太少时改用分组交叉诊断，不借百分比制造独立性。

上游 `split_calibration` 随机拆分已展开的 items，未使用历史／事件家族。一个事件多问题直接调用默认划分，会有相关问题跨 train/calibration 的风险。这是对源码的静态判断，不是已经在 MiLAi 运行中观察到的泄漏。[5]

因此，正式管线应在外部完成分组划分，并利用原生低层训练／校准函数分别消费数据。最小首轮可关闭上游随机校准，仅训练并在独立 dev 上诊断；此时明确标记未校准，不能据置信度跳过维护。

## 5. 训练顺序与目标

### 5.1 第一主训练：原生 soft-CE 域内微调

先保留零样本 checkpoint，然后用相同开放权重训练现有编码器和决策头。硬标签可以作为 one-hot 分布交给 soft-CE。单纯头部训练只作资源／可学习性诊断，不与完整微调混称同一训练方法。

不首先要求 RL。上游提供 `soft-ce` 和 `rlcd`；其 RLCD 是噪声 logits 分布上的策略梯度加 soft-CE，不是通过 MiLAi 多轮记忆环境获得奖励的 RL。[4–5]

建议从完整可容纳的短包启动，显式记录每题的状态与 question/options 总长度。下面参数是启动配置，不是已经调优的结果：

```python
from laya.train import TrainConfig, finetune

cfg = TrainConfig(
    loss="soft-ce",
    freeze_encoder=False,
    epochs=4,
    micro_batch=2,
    grad_accum=16,
    encoder_lr=2.5e-5,
    head_lr=1e-4,
    max_len=2048,
    head_max_len=256,
    calib_max=0,
    calib_frac=0.0,  # 不使用单元级随机校准划分
    seed=0,
    eval_data="data/milai_impact/dev.jsonl",
)

# 前提：train/dev 已按历史或事件家族独立划分；每项完整输入确实容纳得下。
# 两个目录是运行者需准备的实际路径，不是本轮已有训练产物。
report = finetune(
    "data/milai_impact/train.jsonl",
    "./models/laya-multilingual-base",
    "./artifacts/milai-impact-ce-v1",
    cfg,
)
```

本段使用已核查上游 Python API，但本次未执行。关闭自动校准后产生的概率不能宣称已校准。后续用独立 calibration 家族经 `calibration_records` / `fit_temperature_map` 拟合并写回标准 checkpoint，保留真正未见的 test。[5]

不要只看 epoch 数。记录实际有效题目数、优化器步数、训练曲线、根目标漏选与事件级表现。预算不足、只预测多数类、截断了必要材料和任务不可学习，是不同诊断；不能靠固定 15 步给全部路线下结论。

### 5.2 第二训练：同数据的增量比较

比较零样本、普通 soft-CE，以及同数据同输入的组合／关系目标。额外增强也给普通 CE，避免把多看数据归为新损失收益。多个正确范围允许多种答案，歧义项遮罩。

控制器产生的真实 Writer 结果可用作后续范围排序或任务后果监督，但不能只奖励最后混合 QA：原文可能补救错误状态。应评价必要更新与非目标保持，并与计算成本形成明确取舍，避免学成“什么都不改最便宜”。

RLCD 可以作为匹配预算的损失消融；不预设它优于 CE，也不把完整微调收益全部归给附加项。

## 6. 训练后的权重怎样真正进入 MiLAi

上游 HTTP 服务支持 `LAYA_EXTRA_MODELS` 注册本地 checkpoint，训练输出包含 `model.safetensors`、`encoder/`、`tokenizer/` 和 `rl_agent_config.json`，不是只有一个 LoRA adapter。[4,6]

例如，在实际训练环境安装好兼容 Laya 后，可用以下方式启动本地服务。路径应指向真实完成的 checkpoint；不要现在创建空目录后声称已有模型。

```bash
export LAYA_EXTRA_MODELS='{"milai-impact-ce-v1":"/absolute/path/to/milai-impact-ce-v1"}'
export LAYA_MODELS=milai-impact-ce-v1
export LAYA_PRELOAD=1
export LAYA_HOST=127.0.0.1
export LAYA_DEVICE=cuda
laya-serve
```

使用 Docker 时，还须把宿主 checkpoint 挂载进容器，并在 `LAYA_EXTRA_MODELS` 中使用容器内路径。`LAYA_MODEL_PATH` 的一次性推理用法，不应未经核查直接当成 HTTP 多模型注册方式；这里使用已核查的 `LAYA_EXTRA_MODELS`。[6]

MiLAi 的显式实例化应指定新别名：

```python
laya_client = LayaImpactClient(
    base_url="http://127.0.0.1:8000",
    model="milai-impact-ce-v1",
    max_len=2048,
    on_receipt=existing_run_receipt_hook,
)
model_call = laya_client.wrap(existing_model_call)
```

`existing_run_receipt_hook` 和 `existing_model_call` 表示需要接入的现有调用边界，不是已新增的全局变量或声称仓库已有自动配置。默认 benchmark/Host 仍需补这一步；现有 wrapper 本身已经实现。[1–2]

训练、验证和服务端每次都记录实际 checkpoint 身份。不能模型训练完，调用参数仍是 `multilingual`，最终评到基础权重。

回执应在语义标签验收之前保存实际响应／用量，解析失败也算已经执行过的计算。继续使用原账本，不建立第二本。一个 HTTP 请求的多个问题可能对应多个编码序列，不能用 HTTP 次数替代真实模型工作。

## 7. 验证顺序：同时隔离训练、后端与局部化

| 条件 | 控制器 | Writer 输入 |
|---|---|---|
| D0 | 无独立 Impact | 完整候选 |
| D1 | 原生成式 Impact | 完整候选 |
| D2-Laya-0 | 未微调 Laya | 完整候选 |
| D2-Laya-CE | 域内 soft-CE Laya | 完整候选 |
| D3 | 复用 D2-Laya-CE 的同一次选择 | 局部投影 |
| D4 | 复用 D1 的同一次选择 | 同规则局部投影 |

共同 before 用于解释同一选择下的局部化；独立空库连续轨迹用于观察误差积累。两者分开，不让人工完美图独占供给候选方法。[8]

优先报告：必要候选覆盖、root 召回及误选、preserve 误保护、事件级有效范围、联合状态转换、状态受限诊断、正常混合 QA，以及控制器／Writer／Reader 的完整分阶段成本。训练与选择的 CPU/GPU 工作不因为输出 token 为零而忽略。

扩大到多个随机种子和未见家族前，先用少量真实事件接通全路径。若资源紧，只先运行 D0/D1/D2 的小批，再补 D3/D4，而不是同时维护大量半完成配置。

## 8. 对论文方向的判断

**集成 Laya 是实现选择，域内 CE 是强基线；二者本身不是已成立的新颖性主张。**

最值得争取的增量是：从真实形成的、并不完美的记忆中，学习哪些对象需要重新处理、哪些边界证据必须读取，使生成式 Writer 实际局部化，同时保留未来状态的可靠性。

第一阶段没有必要同时解决读取 STOP、全图构造、长期维护调度和 Reader 训练。先判断短决策是否可学、学到后是否改善状态、局部输入是否真正降低工作量。目标选对却写错时，转向 Writer／可独立修订的语义粒度；D0 更好时，允许减少独立控制器。

## 参考资料与核查范围

[1] MiLAi PR #124，本次重新读取：<https://github.com/minguselandy/MiLAi/pull/124>。

[2] MiLAi 固定适配源码：<https://github.com/minguselandy/MiLAi/blob/dc431c066ed96e004f009a6b28bf74ff51e5f84f/MiLAi-Lab/src/milai_lab/methods/laya_impact.py>。

[3] Laya Multilingual 官方模型卡，本次重新读取：<https://huggingface.co/convaiinnovations/laya-multilingual>。只将开放权重、架构和公开限制用于选型，不将作者其他任务分数冒充 MiLAi 结果。

[4] Laya 官方微调指南，本次读取主分支：<https://github.com/NandhaKishorM/laya/blob/main/docs/finetune.md>。

[5] 已核查训练源码：<https://github.com/NandhaKishorM/laya/blob/4ac226d5ee88ed6df8db288a05c766d7a34ee682/laya/train.py>，包括 TrainConfig、split_calibration、finetune 的输出／校准及 dry_run。

[6] 已核查部署文档：<https://github.com/NandhaKishorM/laya/blob/4ac226d5ee88ed6df8db288a05c766d7a34ee682/docs/docker.md>，特别是 HTTP serving 的 LAYA_EXTRA_MODELS 与模型选择。

[7] TypeSafe 官方 Jev 介绍：<https://typesafe.ai/blog/introducing-system-one-models-and-jev>。原版产品和 Laya 开放实现分开命名，不继承宣传中的无语义错误或固定提速保证。

[8] 用户提供的 `MILAI_CONVERSATION_HANDOFF_20261016.md`，第 10–12 节与第 13 节；本文明确标为既有核查的模式兼容、局部 Writer 约束和 D0–D4 原则来自此文件。
