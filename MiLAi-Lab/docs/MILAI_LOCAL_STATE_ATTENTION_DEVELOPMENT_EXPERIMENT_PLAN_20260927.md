# MiLAi：局部多 State–Attention 开发与实验规划

> 核心路线：多个可维护的事项级 State；把“更新哪些 State”和“当前使用哪些 State”分开；由共享维护器落实更新，由普通 ReAct Host 完成业务任务。先证明可用，再验证局部性、注意力及成本贡献，不再把可选状态协议变成业务执行前置证明。

- 文档日期：2026-09-27（Asia/Singapore）。
- 代码核对基线：`minguselandy/MiLAi`，`main = 4aea99de0b7e058e2d254bf8860d0aba6d6b48db`。[S01]
- 状态：**拟议开发与实验方案；尚未实现、运行或提交。**
- 范围：MiLAi-Lab；不自动修改 Product、历史实验锁、模型服务或已有结果。
- 审阅方式：GitHub 源码、已有结果及证据表的静态分析；本次没有重新运行模型、测试或业务环境。
- 命名：下文简称 **Local State–Attention（LSA）**，仅作工作名称，不表示新颖性已成立。
- 决策变化：保留 State–Attention 为研究目标；不恢复旧 M1 的同响应强制状态协议，不把 SER、Formation cue 或 Mem0 直接更名为新方法。

## 1. 执行摘要与本轮最重要的决策

当前项目不缺第二套 Store、更多回执或更严格的 schema；更需要一种能够持续工作、能够被普通 LLM 使用、并且能单独验证价值的状态组织方式。

本方案先做一个可运行的最小结构：

```text
真实用户输入 / 工具观察
              ↓
       共享 State 维护器
       ├─ 选择需要更新的事项 U
       ├─ 局部创建或更新 State
       └─ 选择当前需要读取的事项 A
              ↓
      小型 State 上下文 + 合法证据
              ↓
       原 LangMem / ReAct Host
              ↓
       原业务工具与真实回执
```

核心关系是 `U ≠ A`，而不是要求两者永远不同。例如：处理项目 A 时收到项目 B 的延期通知，应更新 B，却不必把 B 的完整状态塞入 A 的当前回答；随后比较两项目时，可能需要读取 A 和 B，却不需要更新它们。

首版使用**一个共享维护器，不是每个 State 一个 Agent**。维护器可以使用当前基础 LLM，并允许独立、可计费的短调用；普通 Host 继续输出现有 `answer/calls`。每轮没有状态变化时不重写；维护器失败时保留未处理输入并退回普通任务流程，而不是因为可选 State 字段错误拒绝整次业务响应。

需要保留的硬边界只有真实权限、租户隔离、业务参数合法性、未知副作用不得盲目重放、实际写入结果和资源可承受性。状态语义、注意力选择、摘要质量和格式偏差主要通过可恢复处理与离线评价解决。

第一轮不追求完整生命周期系统，也不承诺一次解决所有旧失败。先回答：

> 在有多个交错持续事项时，可维护的局部状态是否比全局工作笔记更容易恢复、更少误改，并能通过读写注意力降低无关上下文与维护成本？

## 2. 当前 GitHub 的关键事实与设计含义

| 已核对对象 | 当前事实 | 对新方案的直接含义 |
|---|---|---|
| `baselines/langmem_agent.py` | `build_agent()` 已构建上游 LangMem tools、ToolNode、业务 wrapper、observer、Store 和 checkpoint；长期 Store 与 thread checkpoint 分开。 | 复用底座，不重建 Agent 平台。新增可选控制入口，关闭时保留 B1。 |
| `providers/langmem_chat.py` | 一个 `_generate()` 中已有 M1、ODR、projection、request_view 分支。M1/ODR 的状态处理在返回业务工具调用之前执行，部分错误会抛出 `IncompleteChatResponse`。 | 不继续给主 Host envelope 增加必填 State 字段；控制器与业务输出解耦。 |
| `methods/state_attention.py` | 旧策略要求 State 与问题 hash、整个候选快照、field/coverage review 匹配；它只在已取得池上作决策，不负责实际生产状态或执行检索。 | 保留为历史参考；新事项 State 不应因换一个问题、增加一个无关候选就整体不可用。 |
| `methods/memory_lifecycle.py` | Formation 是 cue/reminder；Reconciliation 候选目前从 `ok: true` 业务结果和此前已交付 exact refs 产生。 | 不把新方案实现成第四版提示；共享维护器要实际提交状态变化。也不能只对 `ok=true` 观察更新。 |
| `runners/langmem_application.py` | 预留可以已提交，但标签失败，返回 `ok=false`；后续需按同 ID 恢复。 | 所有工具观察都进入信息处理；部分成功、失败、未知都可能改变局部理解。 |
| `runners/langmem_foundation.py` | 业务 journal 按 thread/generation/call 保存 pending/complete；未知结果不盲目重放。 | 保留这类真实副作用边界，不能为“减少防御”删除。 |
| `freshness_projection/controller.py` | 已有 exact refresh、request-copy projection、lineage 和实际交付核对。 | 作为可关闭/共享的证据呈现能力，不继续扩大为 State 控制器。 |
| v23–v26 证据表 | SER 未见任务没有自然 refresh/rebase；Formation/Reconciliation cues 无稳定收益；Mem0 四例形成对照有效但额外抽取昂贵。 | 必须分开测状态使用、状态形成和完整端到端；不能把任何一层失败直接当成另一层无效。 |

源码依据：[S02]–[S08]。结果依据：[S09]–[S12]。

### 2.1 现有结果能说明什么，不能说明什么

v23 是两个原生未见 arc 的小比较：B1 为 6/10，SER-lite/full 为 7/10，但没有自然版本刷新或派生重整。它反映形成、取证和容量路径问题，不能证明 SER 的因果收益，更没有检验新的局部多 State 设计。[S10]

v25 提供了跨进程、部分副作用、多用户和不同历史长度的真实模拟应用证据；但每格单轨迹，并记录了相同首请求后的工具选择差异，不能把 long 档成本差直接解释为方法压缩效率。[S11]

v26 的两个形成正例中，Mem0 自动摄取成功，B1 没有形成；总 generation tokens 为 53,852 对 5,324。这个差距是该固定 Mem0 版本、prompt 与输入组合的结果，不是自动抽取必然贵十倍，更不是通用 LLM 不会形成记忆的普遍定理。[S12]

### 2.2 不再延续的设计惯性

- 不要求普通 Host 自主填写复杂 State 后，才允许业务推进。
- 不把“版本变化”“来源已送达”“模型声明支持”混成语义正确证明。
- 不先修出一个语义完美 baseline 才研究方法；用条件能力实验隔离上游问题。
- 不用单个温度、退款或预留案例决定整个研究方向。
- 不把新颖性押在版本号、模块数量和 schema 丰富程度上。

## 3. 研究问题与可验证假设

### 3.1 核心问题

持续任务中，事项总数 N 可以增长，但一次观察影响的事项数 d、一次决策需要的事项数 a 可能远小于 N。能否利用这种局部性，避免全量状态重写和全量状态输入，同时在跨事项依赖存在时仍保留正确组合？

这是假设，不是对所有任务的事实描述。所有事项高度耦合、任务很短、每轮都需比较全部内容时，全局笔记可能更合适。

### 3.2 四个主要假设

| 假设 | 支持所需证据 | 反例及解释 |
|---|---|---|
| H1 局部表示有助保持 | 同样事实、同样维护器下，局部变化后未受影响事实更少被误改，恢复质量不差 | 若只因局部臂保存了更多信息，需要容量匹配后重测 |
| H2 使用注意力有独立价值 | 相同局部 State bank 下，选择性激活比普通顺序/相关性选择更好或更省 | 若所有 State 直接输入已等价，更复杂路由暂时不必要 |
| H3 更新注意力与使用注意力需要分离 | 在“后台事项变化、前台事项不变”及“组合读取但无需更新”场景，U/A 解耦减少漏改或误改 | 若收益只来自更频繁维护，固定更新频率后再测 |
| H4 可维护 State 比持续重建有条件优势 | 多次恢复、稀疏变化时累计成本更低且语义不劣；变化密集时边界可解释 | 若漂移/合并成本高于重建，改用混合维护而非坚持持久摘要 |

State–Attention 在本方案中是**外部记忆控制层**，不声称修改 Transformer 内部 attention。LLM 选择索引/局部更新只是首个可运行实现，不自动等于一种新的学习算法。

### 3.3 创新候选与已知碰撞

“多个局部模块、选择性更新、稀疏通信”已有 RIMs；“按子目标组织工作记忆”已有 HiAgent。不能以“多个 State”本身主张首创。[W03][W04]

候选贡献是：**在跨会话 Agent Memory 中，解耦更新集合与使用集合，学习/实现证据关联的局部维护，并在共享约束下组合使用状态。**其独立贡献必须经 U=A 消融、分块笔记强基线、局部重建对照和跨场景验证建立。本次不是完整 novelty search，首次性尚未确认。

## 4. 数据与语义：Local State 是什么

### 4.1 事项级 State

Local State 是对一个可持续恢复事项的当前理解，不是原始事实库，也不是模型的完整推理自述。

模型需要处理的语义内容尽量只有：

```text
事项标题/范围
当前理解（简短、包含实际条件）
尚未解决的信息需求
必要来源引用
```

程序拥有：state_id、user/workspace scope、版本、最后成功更新时间、尚未处理事件、归档标记、真实存储结果。不要要求模型生成 UUID、hash、事务序号、执行成功证明。

建议内部对象：

```text
LocalState
  id                 # 程序生成
  owner_scope        # 程序绑定；模型不能跨租户改写
  revision           # 程序维护
  title
  content            # 可短段落，不拆成大量强枚举字段
  needs[]            # 可为空；缺省保持/新建为空
  evidence_refs[]    # 精确可见来源；语义支持仍需评价
  related_state_ids[]# 仅实际需要时使用，首轮可不暴露给模型
  pending_event_ids[]# 机械待处理，不等于整条内容已经错误
  archived           # 与物理删除无关
```

不是所有字段每轮都传给模型。正常工作视图只展示当前选中的 title/content/needs 和少量可追溯引用。

### 4.2 粒度原则

围绕“能够独立恢复、常被同一类观察更新”的事项分组；首版采用自然语言事项识别和候选 State 摘要，不用 fixture ID 或预设领域路由。

不做每字段一个 State，也不把整个用户历史都塞进一个 State。允许一条观察更新多个事项，允许暂未归属，允许需要时新建。重复、过细或过大 State 先在开发分析中诊断，只有影响使用时再增加显式 merge/split；首版不自动夜间合并。

### 4.3 生命周期

- 新建：出现需要后续恢复的事项或已有 State 无法表达的独立上下文。
- 更新：新观察改变已有理解，或为原未知补证。
- 暂停：本轮不激活，但可接收变化。
- 归档：事项已结束且不常用；仍可按历史需要检索。
- 重新激活：任务恢复时读取 State，并处理相关待处理事件。
- 物理删除：只能走既有授权遗忘/删除路径，不能由低 attention 分数触发。

“没有当前 gap”不要求删 State；“不活跃”不等于“不值得维护”；“有 pending event”不等于旧 State 的每条事实都错。

### 4.4 证据、State 与工作视图

1. 原始用户/工具观察保持事实来源身份，不从最终 assistant 回答推断真实业务事实。
2. State 是模型估计，可能有误；它引用来源，但引用合法不等于内容被语义支持。
3. 工作视图是选中 State、必要证据和当前观察的组合；不得隐藏当前用户纠正或最新业务回执。
4. 跨会话存活的 State、其索引及原始事件队列均属于记忆资源，计入容量、权限和成本，不能作为隐藏答案通道。
5. 审计 sidecar 不能自动变成只有新方法能检索的完整历史数据库。需要历史访问时通过声明的合法接口，并在匹配对照中提供相同权限。

## 5. 核心算法：两个集合，一个共享维护器

设 State bank 为 S_t，真实新增观察批为 E_t，当前任务请求为 q_t。

```text
U_t = UpdateAttention(E_t, candidate_states)
S'_t = LocalMaintain(S_t, U_t, E_t)
A_t = ReadAttention(q_t, S'_t, current_observations)
C_t = Compose(A_t, shared_constraints, delivered_evidence)
a_t = Host(q_t, C_t, normal_tools)
```

更新目标取决于观察影响；使用目标取决于当前信息需求。逻辑上分开，但第一版可在一次短 LLM 控制调用中合批输出局部编辑和选择结果，不要求两次固定调用。

### 5.1 候选召回

首个小原型可给维护器全部 State 的短目录，而不是所有正文。规模变大后，利用已有 embedding/词项检索召回：当前事件相关、当前请求相关、最近使用、明确引用关系四类候选的并集。

候选召回只是缩小搜索空间，不能把低相似度等同无影响。保留一次普通 `search_state` 扩展能力、尚未归属事件和“可能需要新事项”的路径。目录读取、候选检索与扩展都计费，不宣称总成本只与活跃 State 数量有关。

### 5.2 局部维护

同一事件批一次处理，不为每个 State 额外调用模型。通常每个局部编辑独立提交；若一次明确的共享约束变化必须同时修改多项，使用一个小型原子更新组，失败时共同保持待处理，避免半组被呈现为全部同步。不要因此把所有普通更新都升级成全局事务。新 State 的 id 由程序生成并把请求内短引用映射到真实 id。

首版使用小 State 的完整内容替换或字段级 upsert，不引入 JSON Patch 路径语法、proof schema、support-role 枚举和 recheck outcome。无变化不生成新版本。未选中的 State 版本保持，而不是把相同正文重写。

### 5.3 选择性读取

根据当前问题、局部需求和共享约束选择少量 State；空集合、多集合都合法。系统级授权/用户隔离等约束不参与 top-k 竞争。跨事项组合从明确必要链接或实际任务需要补充，不能只取一个最高相似度事项。

选中 State 的目的不是立即生成答案，而是帮助 Host 判断当前已知什么、还应使用哪种记忆或业务查询。普通 memory search、业务读取和用户澄清继续可用。

### 5.4 部分失败与真实世界更新

工具回执无论 `ok=true/false` 都进入观察路径。State 可以写“已预留、标签未完成”，不能因整体失败回执自动恢复为“未执行”。未知结果保持未知，由既有业务恢复逻辑处理；State 维护不得重放业务调用。

### 5.5 一次交错示例

```text
当前任务：继续项目 A 的报告。
新观察：项目 B 的交付日期被用户改为下周；报告 A 的受众没有变化。

U = {B 的交付事项}
A = {A 的报告事项, 必要共享格式约束}

随后用户要求比较 A/B 的进度：
U 可以为空
A = {A 的报告事项, B 的交付事项}
```

方法运行时不得看到这个例子的 U/A 标注；标注只用于离线评价。

## 6. ReAct 集成：不再让状态输出与业务动作互相绑死

### 6.1 推荐执行顺序

```text
用户消息或工具观察到达
  1. 记录真实事件；保留原消息
  2. 若有新事件/任务切换/恢复请求，准备 State 候选
  3. 共享维护器处理事件并选择 State
  4. 提交有效局部编辑；未处理事件继续保留
  5. 构造临时 State 视图
  6. 原 Host 生成 answer 或 calls
  7. 原 ToolNode/业务 journal 执行
  8. 下一轮消费真实观察
```

原则是事件合批，不是每个 token、每条旧消息、每个 State 一次调用。没有新事件且任务视图没变时复用已选 id；复用不是保证语义正确，新的用户条件必须能触发重新选择。

### 6.2 当前代码上的落点

`build_agent()` 已接入 `create_react_agent(version="v1")`。优先在该函数增加默认 `None` 的可选控制器/pre-model hook，不改变 B1 默认分支。[S02]

官方参考提供 `pre_model_hook` 与 `llm_input_messages`，后者可改变本次 LLM 输入而不改原历史；`post_model_hook` 在该参考中只支持 v2。因此**不为此直接把已固定 v1 改为 v2**，也不把最终 `response_format` 当成零额外调用接口。[W01] 实现时先对实际锁定包做一个 mock 接线测试，确认历史、工具顺序和恢复语义；若该版本接口有差异，在现有 graph 外增加薄节点，不升级整个 foundation。

State 视图应作为明确标记的工作数据进入本次输入，而不是伪造用户指令或业务 ToolMessage。保持工具调用—回执配对，当前观察和共享授权约束不被裁掉。现有 wrapper 存在 wire/graph 长度与位置匹配假设；新 hook 需要显式保持原消息 ID 映射，不能插一条消息后让 provenance 按旧下标猜。事件采集先于临时视图生成；新的 State 信息不伪装成原始工具证据。[S03][S05]

### 6.3 Provider 的职责收缩

`VLLMChatModel._generate()` 继续负责格式转换、调用和计费，不新增 `local_state_delta` 必填字段。旧 M1/ODR 分支留作历史复现，不通过新 mode 叠加更多证明语义。[S03]

新控制器直接使用独立的、同配置基础 LLM 调用入口；不能递归调用带控制器的 Host，否则会出现自触发。控制调用与 Host 调用使用同一费用归集器，但具有不同 role（`state_control`、`task_host`），不得覆盖彼此的 request/delivery 绑定。

额外控制调用不能绕过实验资源约束：分别统计 Host 与 State-controller 调用，同时归入同一总 token/费用账本。原 Host 每消息调用计数不必因控制调用而机械减少，但比较时要报告并限制总计算预算；不得把“不计入 Host 12 次”写成免费计算。

### 6.4 工具观察入口

优先复用现有工具 wrapper 的真实结果通知，增加一个可选 `on_observation`；它只提交事件，不在每个工具 wrapper 中同步启动多次模型调用。相邻工具结果由下一次前置节点合批处理。

新的状态内容可以包含回执的真实字段，但不能用 renderer 从工具名猜测“成功”。例如 `reserve_and_label` 的部分失败由真实返回内容确定，不写通用 `ok=false => no effect` 规则。[S06]

### 6.5 公共消息结束与进程恢复

新用户信息在生成业务回复前已经进入维护；工具产生的新结果在下一次 Host 请求前进入维护。若本轮最终仍有维护失败，保留可恢复事件和明确状态，不撤销业务成功、不报告已完成持久维护。

工作负载允许时，在公共消息结束前做一次尚未处理事件的合并 flush；它是可见、计费的同步工作，不必创建后台服务。跨进程恢复只需重新打开同一个 State namespace、checkpoint 和待处理事件，不重放已完成业务动作。

`episode_id` 是已有实验线程边界，不能直接当新的事项 State ID。事项可能跨 episode，也可能一个 episode 中有多个事项；禁止借用 fixture 标签来获得正确分组。

## 7. 简化模型协议与存储实现

### 7.1 控制器短协议

第一版可采用下面的小 JSON；它属于单独控制调用，**不是普通 Host 的 answer/calls schema**。

```json
{
  "edits": [
    {
      "id": "s2",
      "content": "交付已延期到下周；其他条款保持。",
      "needs": [],
      "evidence": ["o17"]
    }
  ],
  "focus": ["s1"]
}
```

新增时 `id=null` 并给 title/content；省略的可选字段在更新中保持原值，新建时使用空值。无需 Host 回传 revision/hash。空 edits 和空 focus 都有定义，不要求补写“为什么不操作”。

不要要求完整 reasoning、逐字段 confidence、support role、coverage 证明或 retained/changed acknowledgment。State content 的语义质量由任务和离线审核检验，程序不写正则判断它是否“足够像 proposition”。

### 7.2 存储选择

复用现有 Postgres `BaseStore`，使用独立 namespace，例如：

```text
("local_state", run_id, arm_id, user_id, workspace_id)
```

内容字段沿已有 content 索引；State metadata 在 value 中。版本和 pending events 放轻量元数据/同一存储层，首版无需再增加一个数据库服务或每 State 一个 SQLite。

同一 owner 的写入首先串行合批，沿已有 Graph 串行约束运行。需要真实并发时再补 CAS/冲突合并，不先建设分布式锁、通用事件总线和任务状态机。

### 7.3 一个来源事件，不是多份真相

原始观察按真实 source/event ID 引用。State 可以共享同一来源；共享政策或约束尽量引用，而不是复制到每张卡。source 撤回后记录潜在影响，重新读取时处理；不是递归删除全部下游 State。

当前 `ProvenanceObserver` 保存的是事实与交付证据。不能把“曾在生成请求里出现”自动标成 State 的全部语义依据；未明确获得来源支持的内容应保持其估计性质。

## 8. 减少防御性编程：具体改哪里、不改哪里

### 8.1 错误分层

| 情况 | 建议处理 | 不应做的事 |
|---|---|---|
| 控制器超时、截断或返回无法解析内容 | 本次不应用 State 编辑；保留事件，Host 使用当前真实观察与普通工具；记录 degraded | 中断整个项目、回滚已完成业务、无限重试 |
| focus 中有不存在的 id | 去除无效选择，按普通检索补足或使用空视图；记录一次问题 | 要求 Host 再发多轮 acknowledgment |
| 某条编辑引用不存在的 State/证据 | 只跳过该编辑；不自动猜 ID；其他独立合法编辑可提交 | 把错误 ID 当创建指令；或一项失败拒绝整批任务 |
| needs 等非关键可选字段缺失 | 更新保留旧值，新建使用空列表；有限结构归一化 | 复杂 schema repair Agent |
| State 尚未处理最新事件 | 不把它无提示地呈现为已核对当前事实；优先附变化或使用当前来源 | stale 直接等于整个 State 为假 |
| State 写入失败 | 不报告保存成功；保留 pending；业务结果不回滚 | 吞异常并标维护完成 |
| 用户 scope 不匹配或越权读取 | 拒绝该访问，保留其他合法路径 | 用软回退跨租户取内容 |
| 业务 call 外层 JSON 不可解析/参数不合法 | 保持现有工具边界，不执行无法确定的副作用 | 为减少拒绝而执行猜测参数 |
| 业务结果未知/可能已产生副作用 | 沿现有 journal 查询或恢复，不盲目重放 | generic catch 后重新执行 |
| 原始数据库损坏/权限配置错误 | 显式报基础设施问题；隔离该运行 | 将其伪装为普通模型答错 |

**减少的是可选管理信息对业务主线的阻断，不是减少真实安全性和事实性。**

### 8.2 跳过编辑不等于已经理解

某条编辑因证据引用错误被跳过时，对应事件仍未被语义处理；不能更新 `last_processed` 把它消失。机械 receipt 可以记录“本批消费过”，但语义待处理集合要保留。避免一组游标导致新事实永久丢失。

该逻辑只需一个轻量事件状态或待处理列表，不引入多层 verification protocol。队列不能无限长；使用频率、存储上限和保留策略要可配置并计入总记忆预算。

### 8.3 错误恢复必须在所有匹配臂公平

G/L/LR/LRU 等共享相同重试和降级方式。不能只有新方法遇错继续，而 baseline 因同类控制错误结束。既有历史 B1 不追改；新的共享 harness 修复要单独注明，重新运行对应 reference。

降级运行仍进入主分母，单列 `state_control_degraded`、未完成维护与后续影响。不能只报正常控制调用的成功率。

## 9. 与 SER、记忆形成、遗忘及原始历史的关系

### 9.1 SER 保留为可选证据呈现器

初版不把 SER 开启与 State 分块同时改变。当前温度等既有案例可用于回归，但不再据它调新方法。状态主实验要保持相同的 SER 设置，后续再做 `LSA ± SER`。

局部 State 本身也可能过时。普通助手历史是否降级应作为单独呈现消融，不能靠删除全部历史让新方法赢。保留实际当前观察、调用—回执链与历史查询能力。过去成立的事实不能因今天 State 更新就从历史查询中消失。

### 9.2 State 创建是一种长期记忆形成

如果 LSA 因主动维护器把新约定写入 State，后来恢复成功，这就是持久信息形成，不是“没有增加 memory 却更聪明”。要与同样维护机会下的全局 notes、分块 notes、LangMem manager 或其他自动抽取路径比较。

LangMem 本身提供 manager 和 store-manager 功能，不只有 Host 自选的 manage/search tools。因此不能把较弱的主动调用模式当作 LangMem 所有能力的代表。[W02]

### 9.3 两条信息访问口径

- **匹配机制实验**：所有方法接收相同真实事件，拥有相同来源档案访问权、初始记忆和存储限制；只改变表示/选择/维护方式。
- **公开系统实验**：B1、Mem0、LSA 各按声明的原生流程运行；报告系统差异，不解释为单组件因果效果。

不能把内部 observer 完整历史只给 LSA，再与只能查摘要的 baseline 比较。若控制器需要未入摘要的原始工具观察，必须说明它们何时保存、如何获得、所有臂是否也能获得。

### 9.4 隐私与删除

用户要求删除的内容必须覆盖已保存 State 和缓存引用；不是仅从主 MemoryCard 删除而保留在 State 中。首版复用既有授权删除流程，加 State namespace 的清理入口，不依 attention 权重决定隐私保留。

## 10. 最小代码改动与交付结构

建议首版只新增五个主要模块；规模需要时再拆，不先建通用框架。

```text
MiLAi-Lab/src/milai_lab/methods/local_state_attention/
  models.py       # 小 State / 计划结果 / 事件视图
  bank.py         # BaseStore namespace、版本、pending
  controller.py   # 合批局部维护与 focus 选择
  context.py      # 临时视图、来源展开与普通回退
  integration.py  # graph hook、事件收集、独立计费连接

MiLAi-Lab/tools/run_local_state_attention.py
MiLAi-Lab/configs/local-state-attention.yaml
MiLAi-Lab/tests/unit/test_local_state_attention.py
MiLAi-Lab/docs/LOCAL_STATE_ATTENTION_PLAN.md
```

具体文件名是建议，不是必须创建的合同。

| 现有路径 | 计划改动 | 边界 |
|---|---|---|
| `baselines/langmem_agent.py` | 增加可选 controller/hook 与观察回调连接 | `None` 时保持既有默认行为；保留原工具和业务 wrapper |
| `providers/langmem_chat.py` | 如必要，仅连接计费角色/薄视图入口 | 不增加 Host 必填状态字段，不继续扩展 M1/ODR 协议 |
| `baselines/langmem_instrumentation.py` | 复用事件、版本、来源接口；必要时加只读访问方法 | 不让方法解析历史结果报告或读取 gold |
| `runners/langmem_application.py` / runtime | 参数化调用新 method factory | 不复制 ApplicationWorld，不改变当前业务工具语义 |
| `runners/langmem_merit.py` | 后期添加可选方法选择 | 保留原输入、顺序、checker 与容量记录 |
| `methods/state_attention.py` | 只读算法参考 | 不要求新局部 State 满足旧全池 hash 合同 |
| `methods/milai_m1/`、ODR、cue 实现 | 不继续叠加新方法 | 历史可复现不等于新方案必须保持其限制 |
| root `.github/workflows/fast.yml` | 接入新模块的窄测试命令，安装实际所需 optional group | 不只修改 Lab 子目录 workflow，确认根 CI 真正执行新测试 |

当前 root fast workflow 有 core 与 LangMem foundation 检查；新控制路径的必测命令应接入真实 root workflow，而不是仅增加一个看似存在的子目录 workflow。[S13] 不因本规划顺便重构整仓 CI。

### 10.1 单一运行清单

每次运行自动生成一个 `run_manifest.json`：Git SHA、实际 config、Python/dependency identity、模型请求参数、数据 split/hash、arm、重复编号、计费、异常与输出位置。

默认从真实 config/入口生成，不再手工复制一份 source mapping、一份参数声明、一份 model-visible contract 后反复保持一致。独立核对实际请求与 manifest 仍保留；历史锁字节不更改。[S10]

## 11. 建议接口及失败行为

下面是接口草图，不是声称仓库已有这些 API：

```python
class LocalStateController:
    def prepare(self, scope, event_batch, query, source_access):
        """返回有效局部编辑、focus 与退化信息；不执行业务工具。"""

class LocalStateBank:
    def candidates(self, scope, query, events): ...
    def apply_edits(self, scope, edits): ...
    def view(self, scope, selected_ids): ...
```

关键约束：

- `prepare()` 使用独立计费 LLM 入口，不递归调用 Host。
- `apply_edits()` 对每个真实写入返回结果；成功内容才能进入后续“已保存”视图。
- `source_access` 只提供运行权限允许的历史，不提供评分答案或未发生事件。
- 依赖不足时返回少量 needs，而不是生成一份虚假的“全部充分”证明。
- 当本轮请求没有适用 State 时，Host 保持正常能力；无需填充占位 State。

## 12. 分阶段开发与实验：先形成可用方法，再逐项归因

阶段号是逻辑顺序，不要求每阶段发一个新版本。建议第一轮统称 v27 Local State–Attention，不再每次文字修改生成一套新 runner/协议家族。

| 阶段 | 交付 | 最小实验 | 如何决定下一步 |
|---|---|---|---|
| P0 源码基线与配置 | 新方法关闭时的原路径；单一 manifest；原始事件权限说明 | mock B1 请求/工具/持久状态对照 | 只有确定性接线差异才修；不重复旧全部 benchmark |
| P1 可用闭环 | 一个 bank、一个维护器、read view、普通 Host | 两条完整交错轨迹，其中一条跨进程并含部分业务失败 | 必须能正常完成事项、恢复和继续处理；不能只看 schema 通过 |
| P2 State 使用潜力 | 共享 State bank，比较全量/普通检索/State-conditioned focus | 少量配对情景、状态交换、跨事项组合 | 先判断 State 信息有没有用；正确 State 也无帮助就改读法或任务，而非堆维护协议 |
| P3 在线局部维护 | 自行创建事项并更新；无 oracle State ID | G、L、LRU 小样本同源对照 | 获得整体信号；区别信息保存量与选择效果 |
| P4 关键消融与泛化 | LR、U=A、局部重建等针对性对照 | 按任务模板留出，比较适应/保持/成本 | 找最小有贡献机制；删除无增益复杂度 |
| P5 公开任务与重复 | 原生持续任务+第二任务族；完整计账 | 同一 frozen selection、随机化臂次序、多次完整运行 | 不以单轨迹好坏得出方法结论 |
| P6 规模、模型与训练 | 改变 N/d/a、历史、模型；必要时学习 router | 先定位路由/表示瓶颈再训练 | 形成泛化和质量—成本边界 |
| P7 稳定应用与论文包 | 配置、代码、运行摘要、失败分类、可复现命令 | 无模板提示的真实模拟协作 workload | 证明可用范围；Product 发布另行判断 |

### 12.1 P1 的两个示范闭环

**轨迹 A：前台/后台分离。**三件并行事项中，用户先处理 A，随后 B 收到修订，Agent 继续回答 A，再恢复 B，最后组合 A/B 做一次行动。State 的 U/A 不由 fixture 直接给运行器。

**轨迹 B：部分失败后恢复。**执行工具造成一部分真实副作用，另一部分失败；Agent 保存当前理解，进程重启，在新会话查询实际对象并继续未完成部分。不能重复已产生的副作用，也不能用“failed”覆盖全部事实。

验收记录：真实 State 内容、真实工具参数、回执、焦点选择、未影响事项是否保持、控制失败是否妨碍主任务。若接口有问题，修复接口；若内容理解错，定位错误信息需求，不把全部失败归为协议问题。

### 12.2 P2 使用潜力不等于最终效果

P2 可给所有方法同一份基于已发生历史形成的 State bank，避免 formation 失败使所有结果不可解释。允许离线正确 State 作为诊断上界，但单列 `diagnostic_oracle_state`，不计正式方法成绩。

对照包括：同样信息扁平拼接、普通 query retrieval、任务需求 State-conditioned selection、错误/缺项 State。若后者没有独立收益，先检查 attention 是否真的改变了证据，而不是要求维护器生成更多字段。

### 12.3 P3 第一轮规模建议

可从 6 条独立交错情景、G/L/LRU 三臂、每臂 2 次完整运行开始，即 36 条轨迹。它是方差与问题定位试验，不是统计充分性的保证。每条轨迹按真实任务需要安排消息，不为了凑调用率填充步骤。

先完成少量 wiring，再按冻结的完整批次比较；不要某臂出现一个好结果就提前停止，只留下有利轨迹。若费用过高，按新预算缩小下一批设计，而不是事后删除某臂的昂贵失败。

## 13. 主对照体系：把“局部”“维护”“注意力”拆开

### 13.1 匹配方法对照

| Arm | 状态形式 | 更新 | 当前使用 | 目的 |
|---|---|---|---|---|
| G：Global Notes | 一个全局工作状态 | 每事件批由共享维护器处理 | 普通预算化呈现 | 判断局部化是否必要 |
| L：Local All | 多个局部 State | 每批给全部 State 候选，允许维护器判断 no-op | 全量或固定非相关性顺序的预算化呈现 | 排除只是分块和格式优势 |
| LR：Local Read | 同 L | 同 L | State-conditioned 选择 | 测使用注意力 |
| LRU：Local Read+Update | 同 L | 选择潜在受影响子集 U 后局部维护 | 独立选择 A | 测更新选择与读写解耦 |
| R：Local Rebuild | 相同事项目录与合法历史访问 | 使用时从原始证据重建所需 State | 同 LR | 测持久维护是否比按需重建划算 |

G/L/LR/LRU 使用同类状态内容生成器、相同外部事件、来源权限和共享约束。L 的“全部候选”不代表强制重写每张卡。R 的历史检索、读取和重建都计费；其事项目录若来自预先分组，需与其他臂共享，不能额外提供 oracle 边界。

先做 G/L/LRU 的小型系统比较；若有信号，再用 LR/R 和 U=A 消融定位来源。不要第一轮就跑十几个臂。

### 13.2 必备的强普通基线

- 公开 LangMem B1：外部参考，不把它当全局 State 消融。
- 强普通摘要/工作笔记：与新方法相同维护机会和模型，不能故意限制为“只能被动记忆”。
- 当前信息可装入窗口时的完整历史，及滑动窗口＋摘要：用来排除状态化只是补偿差摘要。
- 原生 Mem0：先保留现有系统结果；后期在适用任务上再做同域对照。它与 LSA 的工具/抽取/检索合同不同，单列系统比较。
- LangMem manager/统一短维护器：与每轮自动抽取对照，避免只把短策略与固定长 prompt 的昂贵版本比较。[W02]

### 13.3 信息公平比字节相同更重要

新 State 会改变 prompt 字节，不能要求所有方法整个 request 相同。需要相同合法历史、相同业务信息、相同任务与评分，以及可解释的计算预算。

同时做两种口径：

1. **机制隔离**：相同 bank、候选池、State 内容和更新机会，只替换选择策略。
2. **真实系统**：各方法产生各自轨迹，完整报告维护/读取/重试和总成本。

在等预算比较中，允许强基线把额外预算用于更好摘要、读取或复核，而不是为凑 calls 空跑一遍。缓存命中、控制调用和 Host 调用也不能混为同一成本。

## 14. 只做最关键的六个消融

| 消融 | 改什么 | 预期检验 | 不符合时意味着什么 |
|---|---|---|---|
| A1 去掉局部划分 | 合并为 G，维护机会和信息相同 | 表示局部性能否减少未受影响事实漂移 | 可能只需一个好全局笔记 |
| A2 去掉使用注意力 | LR/LRU 改为普通 query retrieval 或预算化全量输入 | State-conditioned selection 是否必要 | 可能只是 local storage/摘要有效 |
| A3 去掉更新选择 | LRU 改为 LR，给全 bank 候选同样维护 | 局部更新是否省成本且不漏改 | 小 N 下无差异合理；大 N 仍无差异则更新 selector 多余 |
| A4 绑定 U=A | 只维护当前激活事项 | 后台更新与前台读取能否解耦 | 若无损，数据可能没有真正测到异步事项变化 |
| A5 不持久维护 | 使用 R，从相同合法历史按需重建 | 维护成本是否能在多次恢复中摊薄 | 若重建更稳更省，采用混合方案 |
| A6 State 交换/缺项 | 相同证据，换状态、删关键未决条件、注入可纠正错误 | State 是否实际驱动 attention，能否接受反证 | 若选择不变，State 是装饰；若错误 State 永远不能纠正，方法有确认偏差 |

额外 token/calls 混杂通过共享维护器、相同候选上限、相同控制调用输入预算的诊断对照，以及完整 end-to-end 成本共同处理。无需几十个删除字段实验。

## 15. 数据集与通用性设计

### 15.1 旧数据的定位

现有温度三例、13 个 SER 控制、12-case 诊断、MERIT arc0、v23 seeds 3/4、v24 形成/维护例和 v25 应用都已经暴露。它们用于回归和错误分析，不再作为新方法的未见结果。[S09][S10][S11]

v23 的 seeds 3/4 已运行，不得继续沿旧文档写 `NOT_RUN`。后续公开任务 selection 重新冻结且不挑选只会触发新功能的题。

### 15.2 新开发族

至少覆盖以下组合，而不仅是数值替换：

1. 同一 owner 的多个事项交错；主题词相似但对象不同。
2. 前台 A 不变、后台 B 收到新要求；之后再恢复 B。
3. 局部变化只影响一事项；共享约束变化影响多事项。
4. 同一事项的适用范围变化，事实正文未变。
5. 当前值变化、同值 metadata 变化、无关事项变化三类。
6. 新事项出现、旧事项归档和重新打开。
7. 工具部分失败、未知结果、成功后尚待维护。
8. 跨会话清空工作上下文，验证实际持久保留。
9. 历史查询与当前执行混合，旧版本仍有历史用途。
10. 错误或缺项 State 遇到新证据后恢复；没有预先依赖边的新条件。
11. 多个当前来源冲突，不能用存储时间或排名当权威。
12. 高耦合反例：几乎所有事项都一起变化，检验局部方法何时不划算。

场景族可来自项目协作、文档交付、配置/编码任务、排程和业务流程。目标标注是事实/行动不变量，不是唯一正确 State 划分。

### 15.3 切分方式

开发/验证/测试按情景模板、约束组合、工具模式和对象关系切分。测试只换人名/数值不算强泛化。验证集用于选预算和超参；正式测试不参与 prompt/状态粒度修改。

在线运行不能读“这条事件影响 State B”标签、未来问题或正确业务参数。离线评分允许从模拟世界真值判断 affected facts；存在多个合理 State 划分时用事实保持与行为评价，而不是对 State ID 求唯一匹配。

### 15.4 公开任务

MERIT 可复用已有原生 runner；增加新的未见 selection 时保留原历史、问题、工具与评分，不为展示 U≠A 改题。它的核心作用是端到端行为，不保证自然包含足够局部更新机会。

MemoryArena 可作为第二行动型任务族的候选：原论文专门覆盖跨会话记忆—行动依赖，包含多种 agentic tasks。[W05] 这是外部待接入候选，不是仓库已完成能力；先核验实际数据、许可、环境成本与评分，不能承诺已可运行。

如果公开数据缺少局部多事项结构，自建机制族单独报告，公开测试照原样保留。不能把两者混成一个平均总分来证明通用性。

## 16. 指标与统计口径

### 16.1 任务与语义指标

- 原生 task success、真实动作参数、未完成/错误副作用。
- 未受影响事实保持率；受影响事实更新正确率；不该改却改。
- 跨会话恢复质量、未决条件保留、历史/当前查询区分。
- 需要的信息/State 是否进入当前上下文，以及是否真正改变行为。
- 共享约束遗漏率；错误 State 被新证据纠正的能力。
- State 质量：内容是否表达当前条件与信息需求，而非标签；使用冻结 rubric 抽样审查。

### 16.2 路由与维护指标

- 候选召回是否包含受影响事项；U 的漏选/过选；A 的必要信息覆盖。
- 实际更新 State 数、无意义版本变动、队列积压、更新延迟。
- 被触达 State 版本覆盖不等于语义正确更新；精确引用不等于有效支持。
- 维护失败后的降级完成率及后续恢复率；不只报告成功控制调用。

### 16.3 成本

总费用按实际 Provider receipts 汇总：Host、State-control、摘要/抽取、检索 embedding、失败、重试均计入。State prompt/output 片段只是构成分析，不再加一次到账单。

另列实际延迟、State Store 增长、原始事件存储、candidate/index 成本、exact reads、排队与本地 CPU。跨会话 State 不是零字节“工作态”。

### 16.4 机会与触发

主结果使用全任务分母；机制诊断另外按运行前可判定的变化类型分层。不能只统计方法自己选择触发的事件来证明精度，因为触发是 treatment 的结果。

当某个公开任务没有局部变化机会时，报告机会不足，不把“没有触发”当方法成功或失败；也不替换掉该任务美化成绩。

### 16.5 重复与方差

初轮 2 次只是筛查方差；核心效果阶段建议 3–5 次独立完整运行，后续样本量由方差和预算决定。运行顺序随机化或分块交错，不永远先 baseline 后新方法。

统计以独立事项集合/完整轨迹为单位；同轨迹多个 turn 不是独立样本。报告配对差异、原始计数与区间，必要时按情景族做 cluster bootstrap/置换分析。小样本不制造“显著”结论。

相同 wire 的回放用于验证机械行为，不替代真实模型重复，也不在已经分叉的轨迹间强行复用不匹配输出。

## 17. 规模与参数：用实验选择，不用代码规定

关键横轴：

```text
N：总事项数
 d：单事件实际影响事项数
 a：单行动实际需要事项数
 r：事项恢复/复用次数
 H：历史长度与干扰程度
```

先改变一个轴，不跑巨大笛卡尔积。检验局部设计是否在 d/N 小、a/N 小、恢复次数较多时有优势；在高耦合任务中允许全局笔记获胜。

建议起始配置可用 6–10 个候选、约 2–4 个活跃 State、数千 token 的 State 上下文，但它们只是起点。选择以 token budget 和必要信息覆盖为主，不写“最高只允许三个 State”的语义规则。

状态合并、split、延迟维护、焦点缓存、批量大小在实际瓶颈出现后再加入。没有证据时不要加阈值组合。

当前 vLLM 服务默认保持不变以便比较；控制器可以有独立请求预算。发现真实截断或上下文限制时，允许经明确配置变更做新一组匹配实验，保留原结果；不能使用超出实际模型能力的窗口，也不能悄悄调整共享服务影响其他运行。

## 18. 训练与创新强化：在可用性之后

首版先使用基础 LLM 的有限候选选择与短局部整理，不要求 RL 或多模型系统。

若可用性已成立，但路由/分组不稳，可从开发轨迹训练小型 selector 或轻量适配基础模型：输入只包含当时可见事件、任务和 State 候选；目标是受影响事实覆盖、必要 State 选择和 no-op/保持。未来结果可作为离线标签，不能进入线上输入。

重点训练配对：

- 状态相关变化，应改变相应证据选择。
- 无关变化，应保持其他事项理解。
- 后台更新，不强迫前台激活。
- 需要组合读取，不强迫重写所有相关 State。

若方法最终只是一次 LLM rerank，要如实定位；只有局部持久结构、读写解耦或学习目标产生了强对照下的独立收益，才提升算法贡献主张。RIMs/HiAgent 等相邻工作需在正式稿前做操作级比较。[W03][W04]

## 19. 测试策略：以真实边界为主，不把所有语义变成异常

首版集中覆盖六组：

1. **正常循环**：user→维护→Host→tool→维护→继续；多 State 更新/选择，关闭方法回原路径。
2. **隔离与存储**：scope、局部更新保持、不同事件同文本、重启、真实保存失败与 pending。
3. **可恢复控制错误**：控制器超时、非法 focus、单条编辑失败、可选字段缺失；Host 不被无理由中断。
4. **副作用事实**：部分成功、未知结果、同一已完成动作不因状态重试而重复执行。
5. **信息边界**：当前观察不被 State 过滤，gold 不进入 runtime，State/索引/原始档案成本与权限一致。
6. **当前性与历史**：旧状态不被静默当最新、撤回/删除联动、历史问题仍可使用历史证据。

不对每个空字符串和字典顺序建立独立 fail-closed 分支。结构解析在一个入口做一次；后续使用类型化对象。保持有限格式归一化，不做依据内容猜 ID、改业务参数或自动恢复所有异常。

每次改控制逻辑运行对应窄测；完成切片时跑 foundation、工具 journal、状态集成和包检查。没改变 decoder schema 不重复探针；没改变包内容不为了报告重复构建；共享 adapter 变更仍需要相邻回归。

## 20. 失败后的自主改进流程

每次失败先分类，再决定改哪一层：

| 第一断点 | 优先检查/修复 | 不应立即做 |
|---|---|---|
| 事件根本没交给控制器 | hook、scope、去重/游标、回执真实内容 | 增强语义 prompt |
| 候选没有正确事项 | 候选召回、低相似度新条件、未归属入口 | 强迫只能在候选中选择 |
| 正确事项在候选但 U 选错 | 更新注意力表示/示例、必要时小 selector | 给每领域写路由 if |
| U 正确但 State 内容错 | 简化局部内容生成，区分事实/未决；增加反例 | 继续加审核字段 |
| State 正确但 A 选错 | 需求表示、组合/共享约束、read selector | 全量重写 State |
| 材料正确但业务选择错 | 当前观察与 State 的位置/冲突、Host 取证策略 | 声称状态维护失败 |
| 合法局部错误中断业务 | 将可选控制失败隔离、保留恢复信息 | 更严格统一拒绝 |
| 只有更多调用才好 | 对等计算预算、强摘要基线、必要性消融 | 隐去额外控制成本 |

每轮短记录：实际失败链、至少两个竞争解释、最小可区分实验、修复后受影响正反例。允许继续修复，也允许恢复上一个更简单版本。

工程失败不直接 Kill 理论；一个开发样本失败也不否定通用结构。若同一假设在多个独立情景和实现下都没有收益，或者简化基线在同预算下稳定更好，则缩减该模块。停止/继续依据完整结果与成本，不依据是否实现了预设字段。

## 21. 最小可投稿证据链与阶段决策

最终至少需要：

```text
Problem：多事项交错与局部变化引起误改/无关上下文
Hypothesis：局部可维护 State，且 U/A 解耦，有条件地改善适应与保持
Method：小 State bank + 共享维护器 + 双选择 + 普通 ReAct
Evidence：匹配强基线、读写消融、跨模板测试、完整成本、重复运行
Conclusion：在哪种局部性、耦合度和复用频率下值得使用
```

### Continue

正常任务可以使用，控制错误能够局部恢复；多个独立情景出现保持或恢复收益；强对照未解释掉全部差异。

### Simplify

L 已与 LRU 等价则暂去 selector；R 更好则改成局部重建或混合维护；一个全局笔记已足够时不强迫局部化。

### Redesign

错误集中在状态形成而条件读实验有收益，先改维护器；状态正确而注意力无收益，改读策略；两者都正确而 Host 仍错，单独处理证据使用，不增加 State 数量。

### Stop a component

经多场景、匹配预算、重复运行，组件仍没有独立价值，或只能依赖任务特定规则。停止的是该组件/实现，不必一次否定整个 State–Attention 研究目标。

论文不以“多个 State 首次提出”为 claim；优先验证**局部变化吸收、未受影响状态保持、更新与使用的解耦，以及跨事项组合的代价**。第二模型、公开独立任务族和系统级对照是后期必要证据，资源尚未提供的部分按未运行报告，不让它们阻塞当前原型。

## 22. 第一轮可执行工作包

### WP1：复用底座并形成一条端到端闭环

新增小 State bank、共享维护器和可选 hook；不修改 Host schema。用两条交错/恢复轨迹直接检查实际 State、实际业务回执与降级行为。输出代码、一个 config、一个运行摘要。

### WP2：实现 G/L/LRU 三种配置

共享维护器、来源访问和恢复策略，仅改变状态组织与更新/使用选择；先对预定小样本做重复，保留原始失败，不追求所有旧 benchmark 都先通过。

### WP3：补 LR、U=A 与 R 的针对性消融

只在主要差异可观测后加入；比较分块、读取、更新和维护的独立贡献。加入错误 State、共享约束及高耦合反例。

### WP4：形成泛化验证集和真实预算曲线

按模板/工具模式拆分，扫描 N/d/a 的少量代表点；记录总调用、tokens、State/来源存储、真实恢复质量与副作用错误。

### WP5：原生持续任务、第二模型与研究收口

使用新 selection、相同 checker、多次完整运行；依据结果收敛最小方法。SER、Formation、Reconciliation 可按需比较，不要求把所有历史模块重新集成。

本规划的完成不是“测试全部变绿”，而是得到一套在真实 ReAct 中可持续工作的局部 State–Attention，并知道哪些改进来自局部表示、哪些来自注意力、哪些仅来自额外计算。

## 23. 资料与可核对来源

以下仓库链接全部固定到本次审阅的 commit；它们支持现状，不证明拟议方法已有效。

[S01]: https://github.com/minguselandy/MiLAi/commit/4aea99de0b7e058e2d254bf8860d0aba6d6b48db
[S02]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/baselines/langmem_agent.py
[S03]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/providers/langmem_chat.py
[S04]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/methods/state_attention.py
[S05]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/methods/memory_lifecycle.py
[S06]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/runners/langmem_application.py
[S07]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/runners/langmem_foundation.py
[S08]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/src/milai_lab/methods/freshness_projection/controller.py
[S09]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/docs/MILAI_LONG_HORIZON_EVIDENCE_MAP_20260927.md
[S10]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/docs/MILAI_SER_V23_RESULTS_20260927.md
[S11]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/docs/MILAI_APPLICATION_V25_RESULTS_20260927.md
[S12]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/MiLAi-Lab/docs/MILAI_EXTERNAL_MEMORY_V26_RESULTS_20260927.md
[S13]: https://github.com/minguselandy/MiLAi/blob/4aea99de0b7e058e2d254bf8860d0aba6d6b48db/.github/workflows/fast.yml
[W01]: https://reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent
[W02]: https://langchain-ai.github.io/langmem/reference/
[W03]: https://arxiv.org/abs/1909.10893
[W04]: https://aclanthology.org/2025.acl-long.1575/
[W05]: https://arxiv.org/abs/2602.16313

- [S01] 当前审阅 commit。
- [S02]–[S08] 实际 Agent、Provider、State/Attention、生命周期、业务和 SER 代码。
- [S09]–[S12] 当前证据、未见对照、应用和 Mem0 结果。
- [S13] 根目录快速 CI。
- [W01] 官方 LangGraph API：仅验证集成思路，实际依赖仍以仓库 lock 为准。
- [W02] 官方 LangMem API：manager 与 tools 的区别。
- [W03] RIMs：局部模块、稀疏更新和通信的相关先例。
- [W04] HiAgent：子目标工作记忆的直接相关先例。
- [W05] MemoryArena：多会话记忆—行动任务候选，尚未声明接入完成。
