# v4 B R2：一次通用回答接口修订，条件式完整回归

状态：**PROTOCOL_FIXED; ENGINEERING_ACCEPTED; NOT_RUN**。
[R1](MILAI_NEXT_DEVELOPMENT_V4_B_R1_RESULTS_20260928.md)为 5/6：持久链通过，当前临时格式失败。
本轮不能替换 R1 或沿用它的五份成功来拼接通过；[完整 v4 Goal](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V4_20260928.md)仍未完成。

## 单一通用候选与两种解释

实际 `_action_prompt` 规定响应 JSON 外壳，而 `action["answer"]` 直接成为用户可见回复。
增加一个 v4 限定的说明，明确该字段与用户当前回答要求的映射：

> The user-facing final reply is the decoded text in `answer`; the surrounding JSON is the transport envelope. Apply the user's applicable requirements for the reply's format, language, and length to that text while preserving the required JSON structure.

这是接口说明缺口；尚不能认定它就是 R1 唯一失败原因。另一解释是当前 Host 的指令消费不可靠，措辞变化只能拟合暴露例。
schema 原本允许正确字符串，原 Human 完整可见且首请求无工具/历史干扰，因此不是 decoder 禁止前缀或上下文缺失。
Root 采纳一次局部 Astra 建议，由原 Sol 修改 `memory_boundaries.py` 的 v4 通用合同；没有新增代理、控制模型或审计常驻角色。

唯一改动不含样本值/答案/固定前缀，不修改 schema、parser、服务、thinking、参数、容量、原 Human 或工具，
不重复用户原文、不新增 extractor/correction/自动补词。已有临时范围/持久化规则不再扩写，旧 C/默认提示合同不改。
[工程补充回执](../data/manifests/next-development-v4-b-r2-source-checks-20260928.json)已核对：2个既有Graph目标通过；
v4实际四份wire各含一份新增段，旧C三份及原checkpoint没有该段。仅合同常量改变，其他AST/关键文件哈希保持。
入口/包结构未变，未重新构建、全量测试或重复prepare；真实语义仍待本协议运行。

## 一次冻结，分段执行

在任何真实调用前，同时冻结唯一修订源码提交、六份原输入/rubric hash、
[config](../data/diagnostics/next-development-v4-b-regression-r2/config.json)、
[order](../data/diagnostics/next-development-v4-b-regression-r2/execution-order.json)、
[offline gate](../data/diagnostics/next-development-v4-b-regression-r2/rubric.json)、实际工具/模型、隔离身份、scorer 和连续账本。
阈值 N32/B6000/query10、Attention off、correction0 及既有服务配置全部不变；recipe 身份更新。

固定顺序为 temporary → field_plan → editorial_revision → independent_note → quotation → read_only。
每脚本全新隔离状态，每消息沿原 session_id，不注入 gold/rubric，Root 串行调用。

1. 先完成原 temporary 两消息。第一条用户可见答案必须以 BRIEF 开头并完成一句解释；第二条正常解释 caption，无前缀泄漏；
   两条均零持久写入，原当前输入实际送达，无 correction/selector/额外证明调用。
2. 任一项不满足即 **拒绝唯一候选**：其余五例 NOT_RUN，A/B 未过，C 不创建；停止同义措辞/额外 anchor 变体。
3. 全部通过后，保持同一冻结版本继续另外五例，不重跑 temporary。
4. 六份 R2 自身结果必须满足原 v4 门槛：5/5 新形成、1/1 修订保持、7/7 后续使用、4/4 持久完整链、3/3 负例范围、
   当前格式与后续不泄漏正确，合计 6/6。任一退化同样拒绝，不补用 R1 成功轨迹。

所有失败、未运行和费用如实记录。本轮起点以 freeze 时实际账本为准，R1 后当前是
2972 generation calls／3,756,920 generation tokens／20,991 embedding tokens，不清零。
两个先行消息如果通过也是本轮完整六例中的同一份证据，不额外计一次实验成功。

## 结论上限

即使达到 6/6，也只说明通用适配修订通过了六个已暴露脚本，不能证明 H1 唯一、排除波动或证明临时约束稳定。
只有那时才创建并冻结 8–12 个新 F8 C 脚本，检验新的具体内容及边界。真实瓶颈未出现仍不启动 F8 D。
R1 与 R2 的源码、分母、顺序、状态、成本及结果分开报告，不拼接、不称修复后旧题 unseen。
