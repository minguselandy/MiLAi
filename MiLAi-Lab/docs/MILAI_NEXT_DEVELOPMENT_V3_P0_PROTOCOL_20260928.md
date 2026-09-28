# v3 P0/P1：普通持久记忆与有限结果核对

状态：接口/候选差异定义；P1尚未实现，P2真实执行未冻结。用户新Goal及明确确认是执行授权。
原计划SHA `f2d58e2df4e0681a712c96f7a0b0c62ec255574f5ae7b76c58100f1cc0672727`，基线b848367；v2及其全部失败保持。

## P0已核对的事实

[实际链路清单](../data/manifests/next-development-v3-p0-audit-20260928.json)核对N5一条形成失败和一条过期ordinary链；
原最终提示已含host_both责任说明，工具可达、回执已送达，缺口在操作提案/语义采用，不虚构Store或投影故障。
strict普通工具具有create/update/delete和现有目标检查、缺正文零写拒绝、相同正文no_change；search与精确read可复用。
现有json_action终答schema只允许answer，适配器只保留answer；C必须显式可选接入schema和AIMessage元数据，旧默认不改。
现有Qwen chat_template的tool分支只渲染content，不渲染tool_call_id。因此必须在三臂同样的请求副本中把真实回执引用显式呈现，不能假定wire字段已经被模型看见。

## 固定的差异与共同信息

| 臂 | 语义职责 | 终答／续接 |
| --- | --- | --- |
| B0 | 原SYSTEM_PROMPT普通记忆ReAct | 原answer；没有程序触发额外复核 |
| B1 | 原SYSTEM_PROMPT＋下列一份通用责任说明 | 原answer；可在同12次容量内自然查询、维护和复核 |
| C | 与B1逐字相同的语义责任说明 | answer＋memory_result；仅在unresolved或机械声明无效时至多一次仅记忆续接 |

三臂只使用普通memory持久入口及相同真实业务工具，保留SEARCH/精确READ/CREATE/UPDATE/DELETE/no_change。
无State正文/独立A/U/自动语义维护，不强制保存、固定卡数或双写。B0/B1是新v3臂名，不等于历史B1 native baseline。
三臂共同提供当前owner实际普通记录正文/真实ID；模型可再SEARCH/READ，查询与embedding成本完整记录。
此最小小bank方案全读当前持久内容，不能声称已经验证检索选择瓶颈。
三臂共同将合法实际tool_call_id/name显式放入请求副本的工具结果文本，使引用可被模型实际看到；原ToolMessage、checkpoint和真实结果JSON不被改写。
C字段只能引用当前owner、当前公开回合的真实工具回执。旧档案回执、别的owner、助手自己写的ID不得支持本轮提交。

## B1/C共同通用责任说明（P1实现前冻结文本）

```text
You are responsible for both the user's current task and any explicitly requested ongoing memory work. When the user asks you to keep information for later, use the memory tools to retain useful, accurate content unless an actual existing record already satisfies the request. Acknowledging a request or retaining conversation history alone is not a saved memory record.
Distinguish ongoing instructions from requests limited to this reply, quoted speech, and suggestions the user has not adopted. Do not turn these into standing preferences. A read-only question or a turn with no new reusable information need not change memory.
When an existing matter changes, use its actual record identity to update the affected content, preserve other still-supported details and unrelated matters, and avoid unnecessary duplicates. Handle authorized removal of a saved item within its stated scope; saving a reminder note does not schedule a notification.
Use actual business results to distinguish an attempted action, a completed action, and a partial failure. If a result changes a current assertion in a saved record, maintain that assertion or report the unfinished memory work. Do not repeat a completed business action to repair memory.
Before finishing, check your memory work against the actual records and tool results available to you. Report only what actually happened. If a correct record already exists, you may leave it unchanged. If work remains unresolved, say what remains instead of claiming that it was saved. The tools do not decide whether the content meets the user's intent; you remain responsible for that judgment.
```

源代码常量由Sol接入该字节；不围绕P2结果改措辞。C的额外文字仅解释结构字段、真实引用和一次续接，不增加另一套语义例子。

## C结果与机械核对合同

终答包含`memory_result: {status: committed|no_change|unresolved, receipt_refs: [...], note?: ...}`，不复制事实正文或创建另一份持久责任库。
committed至少需一个本回合真实成功的普通memory created/updated/deleted回执；READ或相同正文no_change不算新提交。
每个声称引用都应属于本回合实际工具结果。invalid/失败/外owner引用不能通过成功提交核对，不泄露外owner内容。
no_change可合理表示沿用真实已有记录或没有持久变更；它不自动算履行用户意图。实际成功写入与no_change自报矛盾须显式保留。
未引用错误和多操作中的部分成功分别保留，程序结果分列实际成功、零写、失败/未知以及声明支持程度，不将部分提交认证为全部要求完成。
自由回答与结构结果冲突由独立评分记录，不做saved关键词正则、自动语义分类或改写答案。

只有C声明unresolved或结构结果无效时进入至多一次纠正；错误归类no_change但没有机械矛盾时不能暗中纠正。
同一Host、同一graph、同一公开消息和剩余12次生成额度；不追加HumanMessage重发用户任务、不清零容量。
纠正保留当前实际观察、记录、已发生业务与记忆回执。只准记忆查阅/维护，不能调用业务工具；程序不能以“还有额度”为由无限再进入。
再次终答仍无效/未完成如实结束并保留全部费用。真实工具超时/未知业务结果沿既有合同处理，不假定未执行，也不盲目重放。
代码不承诺任意写后崩溃或跨库原子性；闭合回合后的恢复从既有checkpoint/业务日志验证。

## 两种历史合同

Archive-access：内联当前owner已访问的完整合法公开历史，同时共享read_history；只用公开visited信息构造，不交付私有world/checker。
Retained-memory：新session仅当前请求＋该方法真正持久的普通memory＋相同正常业务工具。旧checkpoint、source-event bank、read_history、摘要或旁路索引不得回流。
同一session的本轮实际工具/助手消息仍正常可见；审计可以保留原历史，但权限与Host分开。
强raw方法以后可真实保存原文且承担保留/索引/读取成本；本协议不禁止原文存储以人为扶持结构化记录。
历史协议对全部臂相同、事先冻结；不能观察结果后切换。

P2采用共同Retained-memory以检验跨session真实保留，每脚本从空库自然形成，后续独立session使用。
P3若触发，先Archive的正常业务闭环，再预先登记的共同Retained；旧暴露回归与新开发任务分表。

## P1验收与P2准入

Sol负责真实序列化/ToolNode/Store边界窄测：无成功回执却committed、外owner引用、已有正确记录不强制create、业务后维护失败无重放、部分成功/no_change、超时/未知结果、一次机会耗尽，以及实际Retained信息隔离与原方法默认不变。
同一个边界不以多个重复测试组制造通过数量；源码/entrypoint改动才做必要静态、矩阵、边界和一次build。
所有检查后由Luna发布源码，Root再将实际155+源码身份、输入字节、配置、提示、schema、rubric、顺序、run/owner/store/checkpoint/world和账本起点绑定正式freeze。
本文件的定义不是已完成执行freeze，P2不得从WIP直接运行。

P2默认六类新2–3回合脚本、至少两类应用，B0/B1/C各一次；自然形成前态，不seed正确记录。
记录五层：执行真实性／任务／记忆正文范围／维护状态／后续使用。额外成本与纠正激活比例单列，不靠工具success、目标ID或C自报打语义分。
P2达到至少两个独立脚本端到端改善且负例未明显损坏，才进P3；B1足够则优先保留简单法。
若C有额外收益，进入确认前必须有普通法相当复核计算E6；未实际消耗额外纠正时也明确报告，不强行制造触发。
P4/P5按原计划条件决定，P6始终执行；不自动扩大模型、参数、raw外部系统或State分支。
