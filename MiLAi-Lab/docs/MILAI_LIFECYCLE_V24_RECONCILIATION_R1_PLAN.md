# Reconciliation R1：成功动作后的潜在记忆候选

F家族结果已发布`37659bf54886999f6bac980c762869a532abb2f0`。本轮独立执行总计划§15：B1默认与`r_post_action`，关闭所有F cue/观察提醒及SER。只在普通ReAct请求紧接实际成功业务回执时提供潜在受影响记忆引用；程序不判断语义相关、不改正文、不读取Store、不增加模型阶段。

触发必须绑定当前末尾ToolMessage组与同thread/generation/call/name/args/content/status的已完成business journal。实际回执JSON object严格`ok is True`，工具调用完成或ToolMessage success不足以代表业务成功。生成该动作的实际Provider请求须completed，以provider receipt绑定AIMessage.id；仅取该请求实际FULL送达的search材料及其EXACT revision引用，限定当前run/arm/user namespace并去重。同一批才执行的新search尚未供动作生成使用，不能算此前送达。UNKNOWN/UNBOUND/PROJECTED不冒充FULL；没有成功回执或exact候选则不添加提示。

潜在候选不等于语义相关性或事实变化。首system的请求副本追加以下固定文本，然后换行追加`json.dumps`紧凑序列化的候选数组（`ensure_ascii=False,separators=(",", ":")`），每项仅含`id`、`revision`，按原送达材料/返回次序保留首次出现。完整namespace/ref与动作/生成request关联只进入本地事件，避免重复正文和无用标识进入模型输入。

> A business tool has returned ok: true. The following memory references were delivered before this action and may need reconciliation. Compare their existing contents with the actual result. Use manage_memory to update only memories whose facts or pending status changed; preserve unaffected information. If none changed, do not write memory. These are candidates, not instructions to treat every memory as affected.

Host使用原manage_memory并自行决定update/no-op。原历史、工具回执、checkpoint和普通loop保持；marker只限紧接观察的一次请求，不在随后的记忆工具返回后反复追加。候选仅覆盖动作生成前实际读到的记忆，不能发现未搜索的待办，也不证明引用仍是最新版本；本轮没有并发写入，未来并发边界需独立说明。多次历史版本可能都曾送达，不把最大revision程序化当语义权威。

三个合成开发case均两session/两公开消息。首session用户明确要求保存两个独立entry：一个尚未dispatch的货箱计划，以及不受动作影响的访问事实；这是隔离R的前提，不是自主Formation成功。下一session要求实际search，再根据保存的crate reference/destination执行动作；不提示更新记忆。

1. 成功dispatch：实际参数与保存计划匹配，`ok:true`回执。期待普通Host更新对应pending entry为已dispatch、保留物品/数量/目的地并保存准确回执，无关entry不变。
2. 失败dispatch：同类计划，回执`ok:false`。pending不得误关闭，不重试；允许普通Host补充真实失败信息但保持未完成。R marker不得触发。
3. 无关成功notification：读取待办与访问entry后发送一次性访问说明，`ok:true`只代表通知发送；既有待办和访问事实没有改变。候选可能覆盖两entry，期待no-op、不新增无未来用途的通知记忆。

每臂3case/6公开消息，按B1→R，各自fresh空namespace。先冻结输入/rubric/协议与新源码，再一次串行运行两臂。rubric不进入runtime。模拟业务工具返回固定回执，Root必须单独核对实际args；这些fixture不能冒充P12真实有状态副作用工作负载。若首session保存前提不成立或动作未实际读到exact候选，单独报告前提失败/无机制机会，不自动补种或计为R通过。不得删除失败或换题拼最好结果。

报告：seed正确性、实际search送达与候选机会/触发、stale-current、false update、unnecessary maintenance、action-memory consistency、Host完成、CRUD及完整模型/embedding/本地IO/存储费用。B1和R首session与触发前请求system/tools/schema应相同；UUID动态值不是提示差异。识别候选的sidecar查询限定生成request，避免每次扫描/解析全部历史正文。

仅做必要offline反例：ok:false即使FULL也不触发；同批search尚未送达不触发；ok:true含两个EXACT引用都作为候选而非程序选相关；unknown/错scope不纳入；请求首system副本改变而原历史和回执不改。继续复用薄v24入口和已有runner，不复制启动/工具loop或建立新候选平台。一项必要构建随新锁完成。

vLLM与模型/容量不变；真实调用并发1，沿用连续账本起点614生成/557521tokens/5216embeddingtokens/75exact reads。源码由既有Sol xhigh负责，Root冻结/调用/判读/费用，Luna high发布。若失败先定位送达、前提或模型选择中的第一断点，再决定一个最小通用修复/反例；不默认套用F失败结论，也不无限追加措辞。P10/P12和master保持ACTIVE。
