# MiLAi Lab：Agent Memory 前沿调研与 v7 设计依据

日期：2026-09-25。用途：为下一轮 Lab 开发选择可实现的结构和小规模验证方式。本文区分论文主张、固定源码事实和 MiLAi 的拟议改动；没有复现外部论文成绩，没有开展新的模型实验。

规划更新：Goal v7 design revision 2 已将调研内容展开为接口、状态所有权及 P0—P7 开发安排。按用户最新要求，先完成通用开发与集成，再正式选择 benchmark；本文中的 MERIT、MemoryArena 和 MemSyco 是候选，之前的 MERIT 离线样本不是当前执行选择。

**结论：下一步应把已经能修订的记忆接入持续任务，使同一 Host 能根据新观察选择读取、局部修订或直接行动。优先验证记忆是否改变了正确的业务动作，再判断额外管理是否值得。**

## 1. 从 v6 出发，问题需要怎样改写

当前 Goal v6 对应方法 v10、write v9、ingestion v25、material view v5、operation v2。它与早先报告里的“方法 v6/v7”不是同一版本。38 个运行文件与最终冻结映射一致，映射 SHA-256 为 `72f0279eae4223918fdd5869b84d75d85a3ac32800a3fbee7f66c8188ed5c312`。

三个暴露原题、五条最终路径均通过原生评分；真实修订、来源绑定和 State→search 已发生。因此，不能再把现状概括为“功能完全没用过”。准确的缺口是：**已经证明部分操作可执行，但还没有证明 Host 在连续工作中能选择合适的时机、对象和内容，更没有证明复杂路径具有独立收益。**

| 源码或制品事实 | 对规划的影响 |
| --- | --- |
| ordinary 的 `contextual=False`，Host 直接进入自由工具循环；强制 State→search 只在 State 配置下发生 | 不重复开发“取消 ordinary 强制 State”；增加可选 State 策略，并保留旧路径作历史参照 |
| State 的 subject、context、uncertainty 目前会一起进入有效查询 | 需要明确查询投影，单靠提醒模型不要猜测不够 |
| 旧记录已经交付事项、主体、context、来源角色和依赖 | 不能把“再加事项字段”算成语义问题已经解决；要看是否真正更新正确事项 |
| 最终 11 张当前卡全部 explicit；进一步核对，29 次实际创建／修订的参数也都主动选择 explicit | 问题包含 Host 对证据强度的误用，不能只改默认值或批量降级 |
| 正文仍继承批次内 `s0` 等短句柄；结构化来源引用准确 | 修订自由文本合同，保留结构化引用；不能靠文本正则猜测旧 `s0` 指向谁 |
| 当前 managed dispatch 只处理记忆工具；MaterialView 依赖 bound method 找到记忆实例 | 接业务工具需要显式上下文绑定和一层组合分发；只改提示并不构成真实 ReAct 接线 |

v6 的 42 个 settled units 包含 13 次 NO_CHANGE，实际 CREATE/REVISE 是 29 次。后续报告分别记录完成单元、真实变更和任务结果，避免以结算数代替功能使用数。v6 的 243 次生成及失败证据保留，不能作为新 Goal 的独立样本。

## 2. 前沿工作的可用部分与实现代价

### 2.1 AgeMem：记忆可以是同一 Agent 的动作

AgeMem 把长短期记忆管理放进 Agent 策略。官方源码的 `agent.py` 在同一 toolkit 中注册业务执行及检索、创建、更新、删除、摘要、过滤操作，并在 `reply()` 循环消费工具结果；自动开场检索的调用在该文件中被注释。论文的效果依赖渐进强化学习，不能从“开放了相同工具”推导未经训练的 MiLAi Host 会获得相同能力。[论文](https://arxiv.org/abs/2601.01885v3) · [固定实现](https://github.com/y1y5/AgeMem/blob/98f563f907d67b2f2436e3ae7b7ceff32e482814/AgeMem_code_agentscope/agent.py)

**采用：**一个 Host、共同工具循环、真实 observation 后再选择动作。**本轮不采用：**训练流程、上下文任意删除和额外自动摘要。普通维护继续没有破坏性权限。

### 2.2 SimpleMem：让记录离开原对话仍可理解

固定源码的 `MemoryBuilder` 将窗口转成独立条目，并将少量上一窗口条目作为生成上下文。它对消除指代、提高信息密度有直接启发，但窗口生成仍调用 LLM；“lossless”命名不证明任意摘要无语义损失，绝对时间转换也需要合法时间锚点。当前仓库已包含超出原始文本方法的其他方向，应固定所读路径。[论文](https://arxiv.org/abs/2601.02553v3) · [固定实现](https://github.com/aiming-lab/SimpleMem/blob/db80b6a7c591e0ea730a058e9f5fc4eb06572299/MCP/reference/core/memory_builder.py)

**采用：**正文独立可读、同一事项可局部修订。**本轮不采用：**每句话建卡、平行窗口反复总结、替换检索器或凭空推定日期。MiLAi 的单位是可独立改变的事项，而不是形式上的最短句子。

### 2.3 ReasoningBank：任务经验与用户信息承担不同用途

官方提示分别从成功和失败轨迹提炼可迁移的行动经验；记忆项包含标题、适用描述和简短内容。它提示 MiLAi 区分“用户表达了什么”和“某次操作中观察到什么”。论文中的轨迹探索和经验提炼不能直接视为零成本功能。[论文](https://arxiv.org/abs/2509.25140) · [固定实现](https://github.com/google-research/reasoning-bank/blob/ed80611788292ea739f1effd31f16c53823b8a0d/WebArena/prompts/memory_instruction.py)

**采用：**真实工具结果才能支持执行状态；经验保留适用范围。**本轮不采用：**额外成功判定 Agent、每次任务结束强制反思、MaTTS 多轨迹探索。某版文件通过检查，不等于用户满意或方法普遍正确。

### 2.4 ProactiveMemory：不干预也可能是正确选择

公开实现将记忆维护与是否注入提醒分成两次模型处理；返回无提醒时继续原任务，有提醒时只注入一次。它提供“选择何时帮助”的研究参照，也暴露出引入独立 Memory Agent 的调用成本。只计算注入次数会漏掉未注入时已经发生的模型处理。[论文](https://arxiv.org/abs/2607.08716v1) · [固定实现](https://github.com/yifannnwu/proactive-memory-agent/blob/89e5c0d6aadfe531a1aee42fd290d48be89973dd/src/memory_agent/memory/memory_agent.py)

**采用：**无新依据时允许不写；材料足够时直接行动；把无收益的管理调用记入成本。**本轮不采用：**第二个运行时 Agent、逐步扫描、两阶段提醒生成或相关训练方案。

### 2.5 MemoryArena：记住与做对需要在同一环境中测量

MemoryArena 的任务包含跨会话依赖，环境执行动作并返回观察，再供后续任务使用。其旅行场景需要额外数据库、环境服务和数据集，所读 README 也注明代码为 preview。它适合后续扩大外部有效性验证，目前不是最小接入成本的首选。[论文](https://arxiv.org/abs/2602.16313v2) · [项目](https://github.com/ZexueHe/MemoryArena)

**采用：**连续任务中的合法历史、环境反馈和后续复用。**本轮不运行：**整套 MemoryArena 或多环境对比。不能把聊天问答通过率直接当作此类 Agent 任务能力。

### 2.6 MERIT：开发后可考虑的小型工具执行基准

MERIT 提供确定性生成任务、SQLite 业务环境、真实工具效果和原生状态检查器；hard 层含先提供、再更新、后使用的信息。读取其 `arcs.py`、`tools.py`、`metrics.py` 与 `run_pilot.py` 并离线检查首条任务链后，可确认其具有更正和业务动作的测试机会，且原生评分不需要 LLM Judge。正式采用与具体样本仍待开发完成后确定。[论文](https://arxiv.org/abs/2609.05441v1) · [固定实现](https://github.com/smshweta/merit-bench/tree/293933d96b1d1849e1f20d1bb324def5de9ed33f)

源码核对还发现三项必须保留的协议差异：

1. 官方 runner 在每个 episode 开始强制 `memory.read()`，driver 在结束后强制 `memory.write()`。MiLAi 要研究自主操作，就需要替换控制器；保留任务、世界、工具和检查器，并明确叫作 **MERIT 原生任务上的 MiLAi 控制器实验**。
2. `_merge()` 可能给一个 episode 追加多个用户消息，但只保留第一项 TaskSpec 的原生评分。不能删掉附加消息，也不能擅自增加原生评分分母。
3. `memory_utilized()` 通过实际工具参数中的值匹配计算指标。它是有用的使用痕迹，不独自证明因果贡献。当前世界已满足目标的情况由 `pre_satisfied` 排除，MiLAi 适配器也必须保留。

这里只评价接入适合度，不移植论文的外部模型成绩或费用。论文页面的编号与所显示提交月份存在不一致，本文以标识符、固定源码和访问日期定位，不据此声称精确发表月份。

### 2.7 MemSkill 与 Hindsight Memory-PRM：作为研究边界

MemSkill 使用可学习的技能选择、执行和技能演化。它说明固定规则不是唯一方向，但会引入训练与多个角色，本轮不实现。本文核对论文，未把其代码列为本轮实施依据。[论文](https://arxiv.org/abs/2602.02474v2)

Hindsight Memory-PRM 利用检索、引用及受控删除重答估计记忆贡献，再进行训练。对本轮有用的是区分“出现”“被用到”和“带来收益”。本轮没有核实其官方实现，不建 PRM，也不对真实存储执行删除来做消融。该论文与 Vectorize 的 Hindsight 项目不是同一实现。[论文](https://arxiv.org/abs/2608.29605v1)

### 2.8 已有 ReMe、OpenViking 参考仍然有用

本地 ReMe 的 `AutoMemoryCCStep` 从会话增量形成输入，`AutoMemoryStep` 保留会话来源关联；可以参考确定性接入增量，不能把 Stop hook 直接变成 MiLAi 每轮强制整理。这个本地树没有在本文假定为干净上游提交，相关文件单独记录散列。

本地 OpenViking 的 Working Memory 更新把模型提出的分节变化与程序合并分开。MiLAi 可以沿用“模型表达局部变化、程序维护确定性身份”的责任边界；不移入七节工作记忆格式、后台管线或异常后全量重建路径。其本地 LICENSE 是 AGPL-3.0 文本，本轮仅作设计参考。

## 3. 对 MiLAi 的设计选择

```text
原生用户消息／真实工具结果
         ↓ 可信适配器接收并交付准确来源
同一个 Host 取得当前任务与合法材料
         ├─ 信息够用 → 执行业务动作或完成回答
         ├─ 缺少历史 → search / read
         ├─ 需要跨步状态 → 可选 State
         └─ 新观察改变可复用事项 → CREATE / REVISE
                    ↓
            确定性版本／引用／权限处理
                    ↓
          后续独立会话再次取得当前理解
                    ↓
        业务工具参数、实际状态变化及原生评分
```

这不是强制工具顺序。来源接收由程序完成，不消耗额外分类模型；是否生成持久理解由 Host 选择。State 不是数据库真相，也不是每轮必填表。创建、修订及检索继续共用现有对象，避免为新名词增建存储层。

查询投影只取明确查询意图和可用的结构条件；覆盖状态根据实际读写结果维护。`UNKNOWN` 不能写成已经搜索而不存在，某路线返回空结果也不证明全库没有相关事实。

真实工具事件应区分请求发出、返回成功、经何种检查确认以及用户是否接受。先保留为 observation 或 TaskState，只有有依据且可复用时才维护持久事项；无需新增固定的多层记忆分类器。

## 4. 创新性：研究问题可成立，方法贡献尚未成立

统一记忆工具、独立条目、按需检索、轨迹经验、主动提醒和跨会话基准已有明确先例。把这些拼接在一起不能直接认领首创。

| 可研究问题 | MiLAi 已有基础与可测增量 | 当前结论边界 |
| --- | --- | --- |
| 事项局部修订能否同时保留旧事项与快速适应变化？ | 既有准确来源、CAS、版本；收敛修订单位，检查无关内容是否被改动 | 工程可行；只在三题上修好不能证明普适性 |
| 同一 Host 能否少做管理而不漏掉必要维护？ | ordinary 自由循环；增加 optional State 和真实 observation 接线 | 未经策略训练的 Host 是否会正确选择，必须实际观察 |
| 准确可追溯的更正能否进入后续工具动作且成本合理？ | 既有当前理解与来源读取；增加原生动作效果与阶段成本记录 | 一条完整链说明可达；正确率差或工具值匹配不能独自证明因果 |

这些问题通过同一条实现路径检验，不扩展为 H7/H8/H9 模块。H1—H6 保持冻结。若 ordinary 与新配置同样成功且成本更低，就保留 ordinary；若新配置从未自发使用 State，结论应是该任务上的机会或策略尚未得到证据，不能强制补一次调用后称为主动记忆有效。

## 5. 已就位的实施材料

六个新增仓库均在 `/cra/memory/mx_memory/reference-sources/contextual-v7/`，为固定 commit 的浅克隆及稀疏检出；相关文件已落盘，未安装依赖、启动服务或运行外部模型。

| 项目 | 固定 commit 前缀 | 本次主要落点 | 固定树许可证情况 |
| --- | --- | --- | --- |
| AgeMem | `98f563f907d6` | Agent/tool loop、memory store | 未找到项目级许可文件，仅参考设计 |
| SimpleMem | `db80b6a7c591` | 文本 memory builder、条目与检索实现 | MIT |
| ReasoningBank | `ed8061178829` | 经验提示与检索实现 | Apache-2.0 |
| ProactiveMemory | `89e5c0d6aadf` | 两阶段维护／提醒、触发与消费 | Apache-2.0 |
| MemoryArena | `6cd9de14b719` | Agent、memory client、旅行环境接入 | 仅见嵌套第三方许可，不能视为全项目许可 |
| MERIT | `293933d96b1d` | 生成器、世界、工具、原生评分与 driver | MIT |

固定源码与论文版本分别记录，不声称当前仓库完整复现了对应论文最新修订。需要运行的 MERIT 已有明确许可证；其模拟 `send_message/refund` 只操作本地世界，不向外部联系人发送信息或执行真实退款。

完整来源散列见[参考清单](../data/manifests/contextual-memory-v7-sources.json)。曾预选的基准样本现保留在[MERIT 研究候选清单](../data/manifests/contextual-memory-v7-merit-small.json)，不自动启动运行。此前已离线生成并核对 `arc0-000`：5 个 episode、7 条原生用户消息、2 个 dependent episode，原生生成时的 leak check 通过。原始任务与初始世界只保存在 ignored artifacts 中，内容和散列不变；规划清单不写入 gold 值。

接下来按 [Goal v7.0](MILA_CONTEXTUAL_USER_MEMORY_DEVELOPMENT_GOAL_v7.0_20260925.md) 实施。本文完成的是调研与规划，不能充当 v7 的运行证据。
