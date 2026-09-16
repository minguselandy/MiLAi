# V0222 后续：残余意图边界诊断合同草案

版本：`RESIDUAL_INTENT_BOUNDARY_V1_DRAFT`。状态：`PLANNED_ONLY / INSTANCE_NOT_ADMITTED`。
本文件不解除任何旧批停止锁，不分配当前批剩余位置，不授权凭本文直接发送。
对应用户要求的“执行、遇到问题反思改进”；具体新实例仍须独立 subagent 范围审查。

## 新证据与可证伪问题

P1 的 D11 字符串信号成立，P2 完整离线回归通过；但首个 P3 输出合法完整对象 `S01`，
不是授权 `manager_report`。这不是 Goal 中“H-G 无信号”的自动提示分支，
也不推翻合成字符串对照；新问题是字符串已可表达后，完整输入中的目标选择是否仍受意图边界影响。
当前没有证据确定内部 decoder 根因或 Memory 失败。

最后 user 与 V0221 失败请求逐字相同，授权意图完整处于最后一个字段，不能把“新增尾部答案”
当作解释。公共任务要求完成全部业务对象，但校准 system 已明确禁止执行周围任务或另选动作。
S01 恰为第一个 put_record 分支；实际 data 键也先于 object_id。但 V0221 在同样键序下曾
选对 manager_report，因此键序仅是未分解假设，不能直接归因为 grammar 不允许目标。

## 唯一拟干预：移出原意图为独立消息，不重复答案

仅使用原四根首次 full 参考：`p3-01 / p3-03 / p3-05 / p3-07`，目标依次保持
`manager_report / manager_report / placement_plan / triage`。不打开新来源或题池。

| 条件 | 模型可见呈现 |
| --- | --- |
| B0 原表达 | 完整原 canonical messages，不修改任何字符 |
| B1 独立边界 | 从原最后 user JSON 中移除唯一 authorized_intent 字段，把该字段及原值原样作为独立末尾 user JSON 消息 |

B1 不增加第二份答案、不重写动作、不增加“认真复制”等提示。移出后原公共资料、合同、观察、
inherited_note 均完整保留；独立消息内容仅为 `{"authorized_intent": <原值>}`。
机械重组必须可逆恢复 B0 的 JSON 值，并逐一证明全部来源和意图值相同。
JSON 字符串采用原序列化规则；保存精确 messages 差异和实际发送 bytes/hash。

两条件共享当前冻结 D11 compiler/兼容说明、完整 canonical Schema、参考输出、模型和全部参数。
不重排 Schema 分支或属性，不更换 decoder/model，不提高输出预约，不加推理轮，
不将答案放 enum/const，不减少资料或合法对象集合。B1 不新增答案或原先缺失的尾部信息；
它同时改变消息边界、JSON封装及chat-template标记/距离，检验这组呈现变化的整体效果，
不声称已分解这些子因素或排除位置影响。
它仍是 INTENT_ORACLE 诊断，不代表自然业务任务理解。

## 有界矩阵与事前选择

拟首遍按原四根顺序，每根 B0→B1：8 次；每位置新进程、一次生成、无 Session/World/dispatcher。
只有首遍存在同根 B0 不保真且 B1 精确保真的配对改善，才做第二遍完整8次，每根 B1→B0。
不选择性重跑有利根。总共最多16次、阶段1800秒、每请求HTTP总墙钟≤60秒、并发1。

内容比较继续使用严格 JSON、原完整 Schema、完整动作精确值；不修改输出。
HTTP 成功且可信 usage 已结算时，已预期的 JSON/Schema/目标/值差异作为诊断观测可继续；
任何 HTTP/身份/用量/证据/权限异常或新未知停整个新批。失败占一次尝试，不自动重试。

B1 必须四根两遍8/8精确保真，且至少一根对 B0 的改善两遍一致，才得到
`INTENT_BOUNDARY_SIGNAL`。B0 同样8/8则不选新策略。无首遍差异则停止于8次；
有差异但复验不满足则保留 `NO_QUALIFIED_PRESENTATION_CANDIDATE`。
任何结果都不把旧 P3 改成通过，不把这16次当新的完整 full/finish 执行门。

## 执行前缺一不可

- 新版本、新批 ID、具体源码/夹具/顺序/精确选择器和不修改旧批的机械证明。
- 新历史承接：原三个历史账，加当前 P1 24 次与 P3 1 次已结算账，共已知62874 raw；
  旧未知预约28284继续独立保留，总实际仍未知。不能把新未知自动白名单化。
- 批级永久停止/一次启动/冷进程/单写者/完整原始 bytes、usage、诊断失败分流及负控。
- 对全部16位置的实际 HTTP 输入与完整参考输出容量预检，input+4096≤65536，不能靠裁剪满足。
- 累计 raw cap=null，output4096、temperature0、seed213、top_p1、thinking关闭、stream=false；
  HTTP 身份仍须核对，不操作 GPU/容器/服务、不读取凭据全集。
- 独立 scope review 须明确它为何落在原用户“执行并反思改进、委托 subagent 审查”范围，
  而非由 reviewer 自造用户同意。超出本单一候选、受保护池、模型/服务/Product/A0变更需新用户指令。

## 本对照之后的边界

无合格信号：交付有界未分解结果，不再临时试第三种提示或排序候选。
有合格信号：只允许提出这一呈现候选的独立完整门修订，先做零模型接线与范围审查；
本草案不分配后续 full/finish16次、P4链、恢复、自然任务或 Memory 的生成。
这些仍遵守原路线的完整门和新实例冻结，不以诊断信号代替业务执行。

本轮当前批终态维持 `STRING_RULE_SIGNAL / FULL_FIDELITY_NOT_MET / MEMORY_NOT_ADMITTED`；
P4/E1/E2/M0/M1均 `NOT_TRIGGERED`。后续只读恢复可行性见
[E1 预审](V0222_E1_PREFLIGHT_DESIGN_NOT_ADMITTED.md)。

## 草案范围审查

`/root/p0_audit` 独立只读结论：`DRAFT_SCOPE_PASS_FOR_OFFLINE_IMPLEMENTATION /
LIVE_INSTANCE_NOT_ADMITTED`。这个单一B1、原四根、至多16次的设计可映射到用户
“执行并反思改进、委托subagent审查”的要求，支持下一步离线实现及具体实例审查；
它不是空白在线许可，也不分配后续完整门。审查提出的边界/封装/模板距离混杂说明已纳入。
