---
status: PROTOCOL_SELECTED_BEFORE_CALLS
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
source_commit: 4ffd17664ce9d8a6497e57b199b3a6d764adae86
source_pr: 70
model_view: unchanged_v5_full
---

# v6 S3a：S1 字节等价代码的真实 smoke

S1 已独立发布；[工程验收](MILAI_NEXT_DEVELOPMENT_V6_S1_ASSEMBLY_RESULTS_20260928.md)
覆盖 131 个实际 payload、86 次审计、22 组补充分支以及 27 个窄测。
S2 的离线计量已完成，尚未实施任何 Model View 改动。本轮只确认 S1 实际端到端接线。

按固定顺序运行四个已暴露完整脚本，共 13 条公开消息：

1. v5 revised_location：保存、跨 session 更新、当前值查询和保留历史的反向查询。
2. v5 dynamic_world：保存旧规划、真实预约一次、实际工具查询与只读旧规划。
3. v5 explicit_delete：两项独立形成、真正删除一项、保留另一项和当前缺失查询。
4. v5 one_reply_format：当次格式不持久化、不跨 session 延续。

[顺序及输入引用](../data/diagnostics/next-development-v6-s3a-smoke/execution-order.json)
使用原 v5 inputs 和 current_request config 的原字节；不更换样本或改措辞。
[义务合同](../data/diagnostics/next-development-v6-s3a-smoke/obligations.json)
和[评分 guide](../data/diagnostics/next-development-v6-s3a-smoke/rubric-guide.json)
是对应 v5 条目的逐项相同子集，Root 离线读取，runtime 不读。
共54项任务义务：current_explicit26、later_use8、persistent20；本子集diagnostic为0。
沿用历史格式评分口径，不新增标准句式或未请求字段。

本轮唯一方法是 S1 提交 `4ffd17664ce9d8a6497e57b199b3a6d764adae86` 的 B0、full Model View、
显式 current_request。没有 system 对照、selector、correction、reviewer 或新记忆机制。
所有 case 必须符合各自原 task obligations；四个脚本和 current/history/world/DELETE/temporary 边界分别报告。
这是 exposed regression/smoke，不是新样本证据，不能改变原 v5 分数。

冻结记录写入 `artifacts/next-development-v6/s3a-smoke/execution-freeze.json`：源码与 Git SHA、
输入/config/合同/guide/协议及 Root helper 字节哈希、每组顺序、scorer、隔离、服务身份和成本起点。
每脚本独立 run/Store namespace、checkpoint 与业务 SQLite；同脚本的会话和用户边界按原输入执行。
Root 串行运行，每公开消息最多 12 次 Host 生成；共享 Host/embedding 参数和 vLLM 设置不变。

首次运行前 prepare 只生成清单，不联系模型或共享数据库。随后 Root 核对冻结与服务身份，
只在运行时将忽略文件内 DSN 注入环境，不输出凭据。实际进程/HTTP/embedding 与失败费用继续写入
原 `artifacts/ser-v20/budget.json`，不得创建新真实账本或清零历史。

按输入→实际 HTTP→工具/业务数据库→Store→下一请求→实际答复验证；进程完成不等于通过。
保留完整轨迹及全部费用。发生基础设施失败先核对实际进程和部分副作用，不自动重跑；
发生语义失败先定位断点并记录两种解释，禁止为 smoke 修 rubric、换样本或拼轨迹。

无论成功与否，本轮都不代替 S2 改动后完整 12-script/156-obligation 回归，也不代替 S4 新任务。
