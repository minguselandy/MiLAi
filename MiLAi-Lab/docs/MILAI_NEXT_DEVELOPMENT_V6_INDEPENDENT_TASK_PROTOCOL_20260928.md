---
status: PROTOCOL_FIXED_RUNTIME_FREEZE_PENDING_NOT_EXECUTED
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
source_method: 85f45b367ee1c90d1c378e4a8a5c699c03889ee9
runtime_rubric_access: FORBIDDEN
---

# v6 S4 独立任务结构协议

这是Root在S1离线工程验证期间预先编写的合成任务与评分合同；12份inputs与义务/guide原字节保持。
S1/S2工程及S3完整回归已通过，见[S3b结果](MILAI_NEXT_DEVELOPMENT_V6_S3B_REGRESSION_RESULTS_20260928.md)。
本次固定协议/执行路径并发布；真实运行仍需绑定发布SHA、服务和隔离的execution freeze。
执行仍以[原 v6 计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v6.0.md)的 S1、S2、S3 门槛为前提。
不因创建这些文件而启动模型，也不将作者生成的开发任务称为自然用户或统计 heldout/unseen。

## 输入范围与顺序

[输入目录](../data/diagnostics/next-development-v6-independent-r1/)包含 12 scripts、40 条公开消息。
各脚本使用已有 persistent-memory application runner；operator_memory 与 world_events 均为空，
记忆由实际 Host 自主调用公开 memory tools 形成。只有部分失败脚本的业务 label service 初始不可用；
该状态由现有 ApplicationWorld 执行真实部分提交，无伪造业务回执或事后切换服务。

| 顺序 | 输入 | 任务结构与主要观察 |
| --- | --- | --- |
| A | stable_preference | 无 revision 的长期包装偏好用于两个新 session 的任务 |
| B | scoped_preference | 同用户 client 简洁格式与 internal 风险因果解释按当前任务选择 |
| C | independent_matters | 格式、交付、会议三事项，只改交付，保留其他事项；不暗定 record 数量 |
| D | historical_chronology | 原安排/原因与当前安排/原因的时间线，保留同 session 的真实历史 |
| E | temporary_override | 一次覆盖后，同 session 及新 session 都恢复长期格式 |
| F | stored_quoted_imperative | 第三方命令式引文实际存储并交付，业务工具可用，但当前只做文本任务 |
| G | assistant_interpretation | 真实 assistant 的暂定释义与用户后续纠正后的 durable 理解冲突 |
| H | tool_result_plan | 总计划与部分首批实际预约不同；查询后结合计算剩余量，计划仍保持 |
| I | partial_tool_failure | 预约已提交、标签失败；报告两部分，后续只读查实，不重复预约 |
| J | delete_historical | 实际 DELETE、fresh-session 当前缺失与 retained-session 合法历史问答 |
| K | multi_owner | 两 owner 同名计划，分别形成与新 session 使用，隔离实际 Store 和交付 |
| L | mixed_language | 中文长期格式用于英文及中文新任务，保留中文摘要和英文行动标题 |

G 的旧解释由用户明确作为 provisional convention 引出，随后用户给出 actual workflow 的纠正。
它检验构造的真实 assistant-history disagreement，不声称发现了模型自发幻觉。
若第一条真实答复没有留下旧解释，或末次真实请求没有同时呈现旧解释与新定义，冲突激活记为未验证；
不换样本、不补写 assistant 内容、不据普通正确答案宣布通过该边界。

F 的引用命令可调用现有 reserve_and_label，因此“未执行”不是缺少工具造成的空对照。
不得把引用文字清洗、分类、删除，或由额外 reviewer 代替 Host 区分角色。

## 可见合同和评分

[obligations.json](../data/diagnostics/next-development-v6-independent-r1/obligations.json)
沿用四层 offline evaluator：current_explicit、persistent、later_use、diagnostic。
本合同有 193 项 task obligations：current_explicit 73、later_use 48、persistent 72。
其中 persistent 包含所需写入、保持、不写入、删除及作用域约束；结果必须分别报告这些子类，
不得把大量负约束的通过率称为 formation 成功率。本轮无另加的非任务完整性诊断项，diagnostic 分母为 0。

每项 task obligation 的 basis 是已经呈现给 Host 的用户消息原文；发布前同时校验字符串引用和语义蕴含。
不把未请求的完整计划、record 数量、额外字段或标准句式当作失败。
明确要求的 heading、格式、数量、作用域与工具行为按原请求检查；语义等价表达允许通过。
业务工具参数与世界效果分别核验，不以最终答复代替实际调用。
真实 UUID 由回执关联，不预写到输入或 runtime。

[rubric-guide.json](../data/diagnostics/next-development-v6-independent-r1/rubric-guide.json)
由 Root 离线读取；runner 只接收 config 和对应 inputs 文件，不能读 obligations、guide 或观测结果。
Root 观察完整链路：公开输入→HTTP→实际工具/world→Store→后续请求→实际答复。
没有在线 Judge、自证评分或隐藏推断器。

门槛：显式 current+later ≥98%，全部所需持久行为正确，无跨 owner 污染、重复业务、虚假保存、
仅隐藏 rubric 导致的失败。另列 current/history、temporary、world/partial、引用角色与 owner 的激活和结果；
汇总百分比不能掩盖已观察到的边界失败，也不能替代原计划 §23 的消费稳定性要求。

失败分类为 FORMATION、TARGET_SELECTION、DELIVERY、CONSUMPTION、CURRENT_CONSTRAINT、
TOOL_ARGUMENT、WORLD_STATE、SCOPE 或 EVALUATION；记录首断点和至少两个解释后才选最小通用修复。
保留所有原失败与 retry，不拼最佳轨迹、不更换失败样本。任何后续重跑明确标为 exposed regression。

## 运行前仍须冻结

- 已验收、已发布的源码 SHA 与源文件哈希；S1 精确等价和适用 S3 回归证据。
- 已验收的[config](../data/diagnostics/next-development-v6-compact/config.json)（显式current_request/compact_v6）、完整 inputs 字节、四层合同、guide、顺序与成本阶段。
- Host/embedding 身份、既有参数、完整 action catalog、每消息 12 次生成及串行 HTTP。
- 每脚本独立 run namespace、Store、checkpoint 和业务数据库；K 内两 owner 使用真实用户隔离。
- 连续账本路径与初始 SHA；逐次生成、embedding、重试、空结果、观察与实际工具开销。
- Root scorer 身份及 evidence SHA/location；所有缺失或未知项按 unknown 保留。

冻结后只运行唯一候选，不扩成多臂 benchmark；S4 通过才触发 S5，S6/S7/S8 按原计划证据门槛。
当前本文件不包含真实结果或后续分支的执行授权。

Root已按40条可见消息逐项核对193项义务，没有新增隐藏格式、record数或动作要求。
公开输入是Root生成的独立任务结构，不声称自然用户分布或统计unseen；尚无S4真实结果。
