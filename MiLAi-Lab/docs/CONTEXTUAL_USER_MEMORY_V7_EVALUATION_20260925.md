# v7 原生小规模评估选择与记录

本轮开发及 E0—E2 已完成，最终 5/5（dependent 2/2）。[最终结果、全部失败费用和限制](CONTEXTUAL_USER_MEMORY_V7_RESULTS_20260925.md) 是结项入口；下文保留各阶段事实。

E0 在 P7 冻结后完成。冻结映射 `009de286e86be77f9cc8c01c3b230fd600c66a026be3213a9914c030f682af58`，生成请求仍为 0。正式清单为 `data/manifests/contextual-memory-v7-e0-selection.json`；此前 research candidate 清单保持原样。

本次只回答：ordinary 同一 Host 能否从真实观察维护正确的当前事项，并在后续业务任务中使用它。选择 MERIT D1 hard 的首个完整 arc（seed 0、5 episode、7 原始消息、2 dependent episode）。这是预先暴露的开发样本，未按模型成绩筛选，不是独立泛化评估。仅 ordinary/off 一个臂，不检验 State 效果或相对简单基线收益。

| 候选 | 能力匹配与本次决定 |
| --- | --- |
| MERIT | MIT、固定源码、本地 SQLite 真实动作、更新后依赖及纯程序评分；一个完整小单元足够定位工程与语义路径。本次选用。 |
| MemoryArena | 同样有跨任务行动，但旅行数据库和环境接入成本较高，所固定源码的项目许可证未核实；本轮不接第二环境。 |
| 已暴露 MemSyco | 可作语义回归，但没有需要的连续业务副作用；本轮不再叠加回归网格。 |

薄适配器只导入固定原生世界、工具、生成器及 checker。Host 只获得当前原始消息、当前 episode 先前公开消息、真实工具结果及 MiLAi 合法交付的记忆；future messages、gold、checker_args、私有世界快照均不注入。world 跨 episode 持续，transcript、可见句柄和任务 State 重置。同一 episode 的第二消息保持会话。

保持官方 `_merge` 的评分规则：多消息 episode 只评分第一 TaskSpec；分母仍为 5，其中 dependent 为 2。success 必须是 `not pre_satisfied and native_checker(after)`；原生 memory_utilized 仅作参数值匹配痕迹，不能证明因果贡献。无需 LLM Judge。

控制器差异明确：官方强制开场 memory.read 和结束 memory.write 替换为 MiLAi 自主循环；每公开消息最多 12 次响应，最后一次预留回答。来源使用 session 默认保留，持久记录带走必要依据。完整原文回放不在新会话自动注入。业务 operator 的可信来源身份不等于记录所描述的客户身份。

运行前记录 adapter 与配置散列；所有失败和重试沿独立 v7 账本连续累计。不会为了提高分数换 arc、增加题、删除失败 episode 或注入错记忆。若出现通用缺陷，只作可解释的窄修复、重新冻结，再在同一已暴露选择验证。运行结果和实际使用链完成后追加于本文。

E1 前的通用输入标签修订已单独冻结为 `2cb76b46776c331b212f70213cfd2a478c9d7e695d28af6828f4b753d8793672`。E0 清单继续保存选题时的初始冻结；运行 manifest 同时记录最新开发冻结，二者不混为同一身份。该修订发生在任何模型请求之前，选题和原生协议不变。

最终接线收口（仍为 0 模型请求）：在线写入规则只从公共工具说明交付一次，移除 COMMON_PROMPT 重复副本；保留记忆工具名在 off 策略下仍禁止注册为业务工具，防止误解析。4 项 session 窄检查通过。最终开发映射 `6ac8a859f0a835cdd993ec620d673e4b7d61f7ad611d25236a04120d085d274a`，之前冻结均保留。

E1 薄适配完成：`tools/run_contextual_merit.py`，散列 `f156f1da1bbf59fbc7274a0824d7465edc1672a21ec318833dff5acdac12e35c`。原生工具及原 arc/world 匹配、5 个初始 checker 为 false，2 个针对性适配测试、Ruff、mypy 通过。真实运行制品目录：`artifacts/contextual-user-memory/v7-merit-e1-prepared/`；目录名保留 prepare 阶段身份，现进入实际运行。


## 首轮真实结果与通用修复依据

首轮 `v7-merit-e1-prepared` 完整执行 5 episode / 7 消息：原生成功 3/5，dependent 0/2；Host 全部返回 complete，但没有 CREATE/REVISE。38 次生成，输入输出合计 173599 tokens，embedding 419，unknown=0，Judge=0。记忆库跨 episode 为空；两个后续任务只能反复搜索当前会话观察，无法取得约定。原始失败和账本完整保留。

这是可达工具未被策略选择的问题，不能以“业务工具调用成功”结项。源码与首轮 trace 显示当前材料只标 CURRENT，没有向 Host 交代在线来源的 session 保留政策；CURRENT 的版本解释也不等于持久性。补充通用保留说明和材料保留状态，让 Host 能判断何时需用普通 memory_save 保留有后续用途的信息；不强制每轮写入，不由程序替模型建立记录。

同时纠正适配身份：上游 scripted 输入没有提供稳定 actor 字段，脚本发布方不是内容中每位客户的发话者。原 adapter 统一 `merit_operator` 的标注没有原生身份依据；后续设为空，保留每条准确来源的 speaker 锚点，由 Host 按实际内容选择记录所述对象。不会根据 customer 字符串在程序中合并人物。首轮身份错误单列，不用修后结果改写首轮。

修复后仅在同一完整 arc、同一世界起点和评分分母重新验证，仍不是独立泛化样本；累计费用不清零。

首轮失败后的通用保留合同修复已冻结：`612c47f7b55b08d974d3d123a9dd3a22037bb9e8e35aa961a8a1b42ebaf60baf`（material view v7，其余协议不变）。Host 明示实际来源保留政策，来源材料附 retention，业务成功不等于保存记忆。新的 actor 空标注仅在薄适配器。受影响 41 项窄检查、3 源 mypy、Ruff 通过；无工具 schema 变更，不重复 grammar 检查。下一次只验证同一完整原生单元。


第二次同 arc 复核（`v7-merit-retention-repair`）仍为 3/5，dependent 0/2；全部 7 轮完成。新增 38 次生成、190611 tokens、embedding 320，unknown=0。Host 这次提出一次 CREATE，但主动选择 persistence=task，且 about_ref=u0 把客户事项归为记忆所有者；新会话仍无持久记录。说明“告知来源保留政策”不足以解决任务事项与持久性概念混淆。保留失败，接下来只修字段说明和共同语义合同，不改原题或自动补卡。

持久性与主体合同修复冻结：`5579bd06663aabddd9ec0df3ed4dcd18f061e04f4691d69c34cb25ef7fa3c576`（method v11 / write v10 / ingestion v27 / material view v8 / operation v2）。task 明确为当前 HostSession 寿命；有后续用途的有范围业务事项可 durable。主体目录不再默认注册 u0，只有实际交付的可信 owner 来源或已存 owner 元数据才提供，Host 取消 u0 的交付豁免；unknown 不推断人物。共同规则保留指令与事实区别。Astra 仅只读复核这项具体疑难，无额外模型实验；48 项受影响窄检查及静态检查通过。
