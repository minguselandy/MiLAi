# v4 F8 B：六个暴露脚本回归协议

状态：**INPUT_SELECTION_FIXED; NOT_RUN; F8_A_ACCEPTED; WAITING_FOR_PUBLISHED_SOURCE_FREEZE**。
执行以 [工程合同](MILAI_NEXT_DEVELOPMENT_V4_IMPLEMENTATION_CONTRACT_20260928.md)和
[v4 执行记录](MILAI_NEXT_DEVELOPMENT_EXECUTION_GOAL_V4_20260928.md)为准。
本文件只准备 v3 既有输入的回归，不创建 F8 C 的新脚本。

## 单一当前系统与原输入

系统仍称 B0。新配置显式启用 `memory_boundaries`：count 32、candidate tokens 6000、query k10、Attention false，
correction_entries 0。无结构化 memory_result、无默认 U、无新维持器或 Judge。
历史 C 和 v3 B0/B1 仍按其原提交复现，本批不重新运行它们。

按固定顺序 field_plan → editorial_revision → independent_note → quotation → temporary → read_only，
每项仅 B0，一共六 job、15 公开消息。每个脚本使用全新 run/namespace/Store/checkpoint/业务世界，
每条消息按原 session_id 新 session；全部 Retained，无原历史旁路、不预置普通记录。

| 文件 | 用途 |
| --- | --- |
| [config](../data/diagnostics/next-development-v4-b-regression-r1/config.json) | 保持原服务/参数/容量/同一账本，声明 v4 opt-in 开关 |
| [execution order](../data/diagnostics/next-development-v4-b-regression-r1/execution-order.json) | 六项固定顺序，直接引用旧输入文件原字节 |
| [v4 gate](../data/diagnostics/next-development-v4-b-regression-r1/rubric.json) | 离线评估，绑定旧语义 rubric 与各输入 hash |
| [原语义 rubric](../data/diagnostics/next-development-v3-p2-formation-r1/rubric.json) | 原内容/任务/范围/保持/格式要求与互斥成本阶段原样保留 |

旧 rubric 中关于 B1/C 晋级的 gate 不适用于 v4。本批必须通过工程合同的新门槛，不能改写旧 rubric 或旧分数。
v3 六脚本已经暴露，本批所有结果都是回归；不称新的独立效果证据。

## 执行前冻结

Sol 完成 F1–F7 和 F8 A 窄检查后，Root 核对源码/请求合同及实际检查覆盖；Luna 先发布源码和本协议。
随后 Root 才正式 prepare 六项，绑定同一个发布提交、全部源码路径、新配置、旧输入、两份 rubric、
真实工具 catalog/schema、职责/角色文本、模型参数、顺序及各组隔离身份。
prepare 本身零模型；实际运行前保存连续账本副本和服务 GET models 身份。
源码/输入从正式 freeze 到全部六项结束不变；每项一次尝试，失败、错误和未完成都保留。

Host Qwen3.6-35B-A3B-FP8 / 温度0 / thinking=false / max_tokens4096 / context65536 / 每消息12次；
embedding bge-m3 / 1024维；真实 HTTP 并发1。使用既有私密 DSN，仅环境注入，不打印或提交。
唯一预算仍原树 `artifacts/ser-v20/budget.json`，当前起点2950/3,729,307/20,729；实际 freeze 时再核字节。
没有服务设置改变、下载、部署、参数扫描或全量 benchmark。

## Root 核查与评分

逐消息核查输入 → 最终实际 HTTP → 工具/业务世界 → 普通持久记录 → 后续独立 session 请求 → 实际回答。
角色投影、CURRENT TASK 和活跃引用须确实进入实际请求；checkpoint 原内容/ID/ToolMessage 不改。
操作审计必须来自配对工具，provenance 只记实际可见前缀；零写入不能因自然语言 saved 变成保存成功。
失败时先区分执行事实、语义内容、当前约束、范围/维护、后续消费，不以正常退出替代它们。

晋级必须满足：新形成5/5、修订保持1/1、后续使用7/7、持久正例4/4，三类负例边界正确；
当前 BRIEF 生效且下一 session 不泄漏，六个完整脚本6/6；无额外 correction/selector/机械自证调用。
原上下文 note 是否误成为长期偏好仍按原 rubric 评分，不把一切记录都机械算误存。
各项无必要写入/重复事项、假 saved 声称及费用另外单列。

全量实际请求唯一归账，输入/输出 tokens、embedding、检索、普通 CRUD、观察 I/O、纠正/失败分别记。
形成/维护/使用互斥阶段沿用旧 rubric；独立新 note 的质量算形成，费用仍只归 maintenance 一次。
没有为了得到更好数字而抹除准备失败、空提取或失败轨迹；未测物理 I/O/GPU/货币保持 unknown。

## 下一步由证据决定

A/B 全过才创建并冻结8–12个新的 F8 C 脚本。任何 B 失败先按真实首断点、至少两个解释和最小通用修复处理，
保留旧尝试；不得直接跳过门槛。另冻的修复回归仍是暴露数据，不能以重跑通过替换首次失败。
F8 D 仍需真实信息选择瓶颈，不因本配置提供条件分支便启动 Attention。
