# v7 结果：通用开发完成，限定原生使用链验证通过

P0—P7 开发和 E0—E2 小规模评估已完成。最终 ordinary/off 在 MERIT 一个完整已暴露 arc 上取得 **5/5 原生成功、2/2 dependent 成功**，并观察到真实持久 CREATE → 新观察 → REVISE → 新会话当前版 → 业务执行。只证明本次限定路径；不认领泛化、State 收益、相对简单记忆的优势或生产就绪。

最终源码映射：`5579bd06663aabddd9ec0df3ed4dcd18f061e04f4691d69c34cb25ef7fa3c576`，41 个运行／样例文件。协议：method v11 / write v10 / ingestion v27 / material view v8 / operation v2。通用配置为 [off](../configs/contextual-memory-v7-off.json) 和 [optional](../configs/contextual-memory-v7-optional.json)。[开发记录与使用方式](CONTEXTUAL_USER_MEMORY_V7_DEVELOPMENT_20260925.md)、[选择与失败诊断](CONTEXTUAL_USER_MEMORY_V7_EVALUATION_20260925.md) 保留执行依据。

## 改了什么

显式 memory 绑定和可复用 HostSession 取代绑定方法推断及每轮重建；实际交付的材料才授权准确引用，移除消息就撤销引用和缓存。业务回执独立于记忆回执，业务动作不进入读缓存。新会话只保留合法持久记忆，默认原始观察限当前会话；内部 read 不再误标已见。

来源角色、可信 actor 和记录所述对象分开，未知 user 不自动成为所有者。主体目录只有在交付可信 owner 来源或已存 owner 元数据后才提供 u0，Host 不再豁免其交付检查。原生脚本没有稳定 actor，适配器留空而不合并客户。

历史和在线共用紧凑写入规则；精确无变化不增版本，真实变更与来源保留分开。durable 表示跨会话保留，不表示永久真理；有时效的约定和待办事项也可 durable。task 表示当前 HostSession 的寿命，不表示内容是否关于业务任务。来源材料显示保留范围，Host 不把业务成功误当记忆已保存。State 可选，明确 query 不再被自由文本暗中拼接。

所有修复都是通用合同；核心没有题号、客户 ID、金额路由或评分输入。没有程序替 Host 自动建卡、每轮强制写入或额外语义审查模型。

## 原生结果与连续费用

先完成通用开发及冻结，再选首个完整 MERIT D1 hard arc（seed 0、5 episode、7 消息），随后做薄适配。使用原世界、工具及 checker，保留 `_merge` 只评分第一 TaskSpec、`not pre_satisfied` 规则及原生分母。控制器替换为 MiLAi 自主循环，因此是“MERIT 原生任务上的 MiLAi 控制器实验”，不是官方 harness 的完整复现。三次都是同一已暴露单元的修复验证，不是三份独立样本。

| 运行 | 原生 / dependent | Host 请求 | 输入 tokens | 输出 tokens | embedding tokens |
| --- | --- | ---: | ---: | ---: | ---: |
| 首轮：未写入 | 3/5；0/2 | 38 | 172383 | 1216 | 419 |
| 来源保留说明修复：仅 task 写入 | 3/5；0/2 | 38 | 189338 | 1273 | 320 |
| 持久性与主体合同修复 | **5/5；2/2** | **25** | **116367** | **1300** | **534** |
| v7 累计，含全部失败 | — | **101** | **478088** | **3789** | **1273** |

生成 tokens 合计 **481877**；embedding 请求 39 次，Judge 0 次，未知用量 0。累计和复核次数上限保持 null；单工作流容量保留。首次空搜 16 次、第二次空搜 20 次，最终 search 2 次、read 2 次；实际成本下降与多项合同修复共同发生，不归因于某一个提示或宣称因果收益。v6 的 243 次生成及原账本未改。

开发代理另外记录：Goal 完成时运行系统累计 1018288 tokens、3374 秒（约 56 分钟；含开发协作的系统口径），逐代理／模型 token 拆分未暴露，不能当作已核对的 API 计费或与实验 Host 简单相加。常规开发用 Sol；Astra 仅只读审查具体持久性／主体疑难；本轮没有新的下载任务。无实测单价／GPU 时间，不换算金额。

## 真实使用链

1. episode 1：Host 保存两个独立事项。`card:2@1` 是 CUST-1002 / ORD-470977 的 503 cents 约定，来源为该轮原始用户陈述，persistence=durable。
2. episode 2：新原始消息明确改成 6595。Host 找到准确旧记录并提出 REVISE；第一次因使用只有链接、没有正文的旧来源被拒绝。Host 自行读取实际正文后重提，提交 `card:2@2`，保留新旧支持来源。另一个事项 `card:1@1` 完全未改。
3. episode 4：新 HostSession 搜索实际交付 `card:2@2` 的完整正文范围 `[0,215]`，随后真实调用 `refund(order_id="ORD-470977", amount_cents=6595)`；原生世界与 checker 确认成功。

最终有 **2 次持久 CREATE、1 次成功 REVISE、1 次被拒绝后修正的 REVISE**，实际记录变化为 3 次；不把四次 save 请求都算变更。两个 dependent episode 的值都出现在实际交付的记忆正文及执行工具参数中。搜索同时交付了原始依据，所以不能排除 Host 直接从原始来源取值，不能据此声称卡片的独立因果价值。

## 限制和验证边界

首个 plant episode 仍未保存最初约定；后续更正提供了形成当前认识的机会。执行退款后，卡片仍写着尚未处理，模型没有再次回写已执行状态。这两项策略局限如实保留，没有增加任务或制造第二条链掩盖它们。当前结果不证明任意任务都能及时维护记忆；后续若要验证此能力，应另选有真实消费机会的任务。

optional State 已通过接线、查询与部署 schema 检查；本次仅 off，未证明 State 的选择时机或效果。中文词法检索及既有容量限制未解决；删除仅覆盖既有受管记忆／制品，业务世界不属于记忆删除事务。未做 Product 迁移。

受影响的六类窄检查、Ruff、mypy、包依赖边界与真实本地文件样例通过。部署 vLLM 0.27.1 / xgrammar 0.2.3 的 8 项 grammar 检查通过，最终语义修复的 48 项窄检查通过；原生 adapter 2 项检查通过。不同阶段检查有重叠，不合并为独立样本。未运行全量测试、全量 benchmark 或包构建。历史维护测试中旧的直接 `forget()` fixture 不符合已有可信删除合同，未为其放宽权限；它不是本轮的验证范围。

制品索引：`artifacts/contextual-user-memory/v7-development/experiment-summary.json`、`mechanism-chain.json`、`freeze.json` 和源码快照；最终原生运行位于 `artifacts/contextual-user-memory/v7-merit-scope-repair/`，两次失败目录保留。单独账本 `artifacts/contextual-user-memory/v7-budget.json` 连续累计。未创建 commit/tag 或推送，仓库 HEAD `5f233a16829b9c2db603153b0e7d28dd6edb2188` 不能代表未提交工作；各阶段冻结源码是本次复核／回退依据，远端未核对。
