---
status: ACTIVE
scope: RESEARCH_PROTOTYPE
parent: MILAI_LONG_HORIZON_EXECUTION_GOAL.md
reference_commit: 9387f533b9bb76f01beca59e26887194e878fb64
---

# v24：独立记忆形成与动作后更新

执行总计划§14、§15/P11。P9的21条早期约定观察未保存，成功动作后仍留有pending正文；这些是独立生命周期缺口，不是SER刷新失败。保留P9全部未见结果，不修改其提示或重跑种子3/4。先完成Formation（F）的最小机制，再另行冻结Reconciliation（R），两者不同时改动以免混合归因。

## F：单一通用前瞻提示

B1保持默认LangMem系统提示；`f_prospective_retention`仅通过现有`build_agent(environment_rules=...)`追加以下固定文本：

> Before finishing a turn, consider what would be lost if this observation were unavailable in a later related session: commitments, constraints, unfinished obligations, or reusable results. Use the memory tools to retain or update information worth carrying forward. Keep task-local calculations and one-time response instructions out of durable memory unless the user establishes a future use.

普通Host仍决定原始manage/search工具的CRUD或no-op。无独立提案/反思模型调用，无自动记忆写入，无强制每轮保存、内容规则、gold路由或新增semantic State。原ReAct loop、工具schema、JSON-action适配器和业务journal保持。B1和F均不启用SER，以隔离提示的效果。

Root冻结四个独立开发fixture：未来约定、业务回执、临时计算、一次性输出要求。前两例各两session，后两例各一session，共每臂四case/六公开消息；两臂十二消息机会。后续session明确要求检查已存笔记，用来把形成问题与自主搜索遗漏区分开。评价优先检查首次session结束时是否形成准确且有作用域的持久记忆，然后检查后续实际搜索内容与回答。临时计算/一次性要求不应形成持久记忆。模拟业务回执不是外部真实消息。

两臂按B1→F顺序，独立空namespace、同一输入/工具/固定回执/评分。rubric只由Root读，不进入runtime。F固定文本的SHA、额外实际输入tokens、记忆写入、embedding、轮次和模型可见差异均报告。不能把提示收益归因于SER。不是未见正式样本，不能凭4例宣称普遍可靠性。

复用现有diagnostic runner及启动逻辑，只加必要可选参数，默认保留旧行为；薄v24入口绑定新lock/config/protocol。必要验证覆盖旧默认提示保持、F提示只追加一次、身份绑定和两臂接线。避免复制业务loop或新增方法平台。由原Sol xhigh实现源码/config/CI/窄测，Root负责fixture、冻结、真实调用和报告，Luna high负责发布。

## R：后续独立冻结

仅在F首轮结果分析完成后进入。预期接口为实际成功业务回执→此前动作生成请求实际送达的exact记忆refs→候选提示→普通Host更新或no-op。程序只关联元数据，不判断正文真值/语义相关、不直接改正文，不额外搜索或读取Store。首版业务成功合同为工具JSON回执`ok: true`；journal complete或ToolMessage success本身不能冒充业务成功。无exact候选则不提示。

先用三个独立控制：成功动作对应pending并夹有无关记忆、失败`ok:false`保持pending、成功但无关动作应no-op。具体fixture、提示、source及rubric在调用前另行冻结，F提示不混入R比较。报告stale-current、false update、unnecessary maintenance和action-memory consistency；候选范围仅限实际送达refs的限制必须明确。

## 运行与停点

vLLM设置不变，现有Qwen3.6-35B-A3B-FP8、temperature0、thinking=false、max_tokens4096、每公开消息12生成；embedding bge-m3/1024。所有真实调用并发1。沿用`artifacts/ser-v20/budget.json`，起点568生成/530611 generation tokens/5057 embedding tokens/75 exact version-resolution reads，历史费用不清零。失败不换题、不拼接最好轨迹，定位first broken link、至少两个解释、最小通用修复和反例后才能新freeze。

只运行这组小实例。后续方法稳定再决定暴露原arc0或P12脚本是否需要一次确认，不预先扩大benchmark。P10第二模型端点信息仍待用户补充，其余独立工作继续。P10/P12和总Goal不因本阶段完成而结束。

## 交付

- [ ] F输入/rubric/protocol、最小源码、必要窄验证和新源锁。
- [ ] 同源B1/F十二消息机会、实际wire/持久记忆/业务回执与完整费用。
- [ ] F Failure Review、十项Reflection与Continue/Pivot/Kill。
- [ ] 独立R源冻结、三个控制、实际候选/普通CRUD/反例与费用。
- [ ] 生命周期结果与复现、Luna提交推送并核对remote。

Product、旧M1/ODR、P9结果和原计划字节保持；不引入自动semantic truth gate，不改vLLM配置。
