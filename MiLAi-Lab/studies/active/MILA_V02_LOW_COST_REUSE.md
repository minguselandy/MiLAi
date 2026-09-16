---
document_id: MILA-V02-03-TERMINAL
date: "2026-09-06"
status: COMPLETED_KEEP_BASELINE
N4: NOT_EVALUABLE_NO_ELIGIBLE_EXACT_COPY
N5: NOT_ENTERED
product_effect_claim: NOT_EVALUATED
---

# MILA-V02-03 交付

> 2026-09-06 更正：下面保留修复前的执行结果。因末尾换行就停止 N4 的工程判断已更正；
> 一般性 payload 保真缺陷已修复，原文件公开往返验证通过。原定续做已完成12次后续和3条
> 完整历史对照，N5另一条历史因累计token闸门未启动后续；最终17分配/16模型会话。见
> [修复与续做报告](MILA_V02_PAYLOAD_FIDELITY_CORRECTION_20260906.md)。

继续完整 A0。可信 trace 已交付；计数歧义保留；原样笔记复制在两条正常任务产生的文件上均无
合格机会，未启动 F/S，未得到节省成本的效果估计。实验复制能力不默认接入 Product。

对应 [Goal](../../../MiLAi-Product/docs/goals/MILA_V02_03_可信诊断与低成本记忆续做_开发实验_GOAL_20260906.md)、
[规范合同](MILA_V02_LOW_COST_REUSE_PLAN.md)、[机器总账](MILA_V02_LOW_COST_REUSE_RESULTS.json)、
[来源审计](MILA_V02_LOW_COST_REUSE_AUDIT.md)、[任务预注册](MILA_V02_LOW_COST_REUSE_R.json)。
执行过程及失败记录索引见 [执行记录](MILA_V02_LOW_COST_REUSE_EXECUTION.md)。

## 阶段结果

| 阶段 | 实际交付与出口 |
|---|---|
| N0 | 新 pin/config、来源 hash/截止/未来信息隔离、13 工具目录、安装身份、实际无模型容器边界及预算门验证通过。 |
| N1 | `NEUTRAL_TRACE_READY`：真实旧口径拒绝仅两个局部 ID 不同；显式 v0.2 验证同次 receipt/root 及持久化 query/scope/snapshot 后有限规范化。真实变化仍拒绝。 |
| N2 | 原计数 `AMBIGUOUS`，原参考 3 不改；普通、更新锚点 `SCORABLE`，关键证据均进入 Context，没有可靠 QA 缺陷触发条件。 |
| N3 | 确定性封装、完整 State/CAS、受检引用、no-op、失败确认与拒绝验证通过；发现公开输入会 strip 字符串首尾空白，对不兼容笔记前置拒绝。 |
| N4 | 两次普通 G 完成，0/2 笔记具备原样复制资格；`NOT_EVALUABLE`。F/S 分配 0，不换历史、不剪裁笔记、不降低门槛。 |
| N5 | 未进入：N4 未通过且无可靠一般性 QA 任务缺陷。C 历史未运行，不动用额度补无依据实验。 |

N1 第一批 2 次、第二批 4 次 testkit，共 6 次/18 次官方读取，均在上限内。第二批的计数、普通、
更新和空来源全部通过。真实 PG 负控确认错误 query/scope/未知 predecessor 拒绝；新增来源确实
进入 Context 后，三读中性检查拒绝。原根 ID 保留于隔离 PG，报告给出绑定身份摘要。
v0.1 默认算法和旧摘要解释保留；新增 receipt/continuation 只读核验不改变检索、权限或 Canonical。

计数审计覆盖完整包扫描和相关原文核对：blazer 干洗、Zara 换码靴子及姐姐借用毛衣具有不同
商店/事件/计数单位条件，重复靴子叙述不自动算两个对象。没有把 A0 的 2 改成新 gold。
普通锚点坐标复核更正为 s5 t2/t4，评分状态及来源内容未变。审阅者是执行者 Root Codex，
没有独立模型 Judge 或人类 gold；新锚点的外显问答结果和后续模型输入仍未观察。

## 原样保存的实际限制

Runtime `HostCognitiveBinding` 的 `str_strip_whitespace=True` 继承到 Update payload，
其字符串首尾空白被递归删除。真实公开 UPDATE/GET 确认末尾换行丢失，存入的文本与输入 hash
不再一致。Runtime 与公共 State schema 本轮没有改动；也没有二次编码、添加字符或剪裁笔记
来改变候选含义。

实验封装器使用 `milai_lab_exact_note_v1`，保留其他 payload 字段和引用；`evidence_refs` 使用
实际受检字段，非零版本携带实际 `state_id`，EXPIRED/TRUNCATED/warning 拒绝合并。
现对首尾空白在提交前拒绝。内部 UTF-8、引号和换行可在支持范围内原样保存，真实 PG 验证了
ABSENT→ACTIVE、旧字段/引用保留、无额外写入 no-op、stale、operation conflict 和无效/跨 scope 引用拒绝。

初次测试写入成功但回读精确性未确认，第二次测试 operation ID 误复用被拒绝，第三次完整回执
定位 strip；第四次非模型受限输入 fixture 通过。所有失败记录与 State 留存。第一份诊断未保存
完整墙钟，继续标未知。这些非模型 fixture 不充当自然任务或 F/S 效果样本。

## 机会与成本账

两条 G 都是约 250 词的普通笔记任务，无额外 State 指令；完整 A0 自然保存能力一直可用。
两次结束 State 均仍 ABSENT/version 0。原题和未来问题从 G 历史 JSON 移除，角色、正文与
截止前会话保留。所有文件、来源回执和完成点留存。

| 历史 | G 笔记字节 | G input+output | G 实际在线秒 | 工具动作 | 资格检查秒 | 出口 |
|---|---:|---:|---:|---:|---:|---|
| 27016adc | 1,718 | 221,349 | 116.258 | 10 | 0.0981 | 文件末尾换行，提交前拒绝 |
| 852ce960 | 1,673 | 261,445 | 163.341 | 11 | 0.0951 | 文件末尾换行，提交前拒绝 |

两份笔记的关键历史事实与出处经过核对；第二份明确区分了用户陈述和原助手估算。
不改实际文件以迎合接口。两次候选检查各一次公开 GET、0 次写入、0 次模型调用，合计约
0.1932 秒。成功保存的 Delta_save、F/S 成本比、两次后续净收益及 G+未来完整路径均未观察，
不填 0、不按工具次数推算 token，也不把普通 G 说成免费。

共 **3/28 次分配、2 次实际模型会话**：N0–N2 0/4、N3–N4 3/12、N5 0/12。
第一份分配因研究用 `debug prompt-input` 导出 45 秒超时而在 model exec 前退出，0 token，
仍占一个预留额度；随后新批次保留实际 launcher profile，取消额外导出，正常 bootstrap 未改变。
失败分配原始在线约 48.652 秒，其精确用户/观测分区未知；保留原始结果及 dispatch 审计。

已知 input **477,959**，output **4,835**，合计 **482,794**；cached input **405,760** 是输入子集。
没有未知的已启动模型 usage。两次 G 在线合计 **279.599 秒**；含失败分配的原始在线合计
**328.251 秒**。两个修订后会话的会后观察/处理另计约 **0.1384 秒**。
捕获/READY、分支准备、testkit、测试与工程审阅属于研究开销，已有时段回执保留；工程总墙钟
不完整，未虚构一个穷尽总数。N4 缺少合格机会的退出是合同允许的出口，不构成成本优劣结论。

## 验证、身份与回退

- Runtime：`uv run ruff check src tests migrations`、`uv run mypy`、`uv build` 通过。
  首次完整 pytest 未配置数据库而失败，随后本轮专用 `milai_v0203_checks` 数据库执行
  `uv run pytest -q`：**962 passed / 1 skipped**。跳过项为 Runtime venv 缺 `milai_client`
  的一个 context-chat 客户端集成测试。另有 **7 项定向真实 PG** 通过。
- Lab：`uv run milai-lab-check-boundary`、`uv run pytest -q`（**159 passed**）、
  `uv run ruff check src tests tools`、`uv run mypy src/milai_lab`、`uv build` 通过。
  其中 checkpoint 单测 23 项；公开 MCP/PG fixture 已实际运行。
- 最终 Product tree：`8350e95565cc37c588c1e9b6d9a212b48ede7385d50fe2c5d83dc75912946dd3`；
  lock digest：`850170c1322b785ca4eafc3cdfdee087292f347eb2b9eec4edb5785592e42c6a`。
  旧锁未修改，当前安装路径与新 pin 核验通过。Codex CLI 0.153.0，模型/推理为既定 gpt-6-astra/high。
- F/S 分支入口已经编写，但未获合格 G 条件，**没有真实分支恢复或效果验收**；不描述为已验证用户能力。

只停止本轮核验身份的 API/worker、PostgreSQL 容器；Host/诊断容器退出，认证副本为 0。
新网络、数据卷、运行/检查数据库、失败记录和旧 digest 保留；旧服务与公网未改变。
具体退出身份在运行根目录 `cleanup.json`。

回退只涉及新 testkit 口径及 Lab 配置：默认 v0.1 或改动前保存的 Product testkit/manifest；
普通运行继续 A0。共享 State head 不回退、不清空数据库。没有新增迁移、公共 API 工具、
权限或 Canonical 语义变更。D2 SHADOW、Product-11 封存、Formal 500 不评分、公网不变。
Schema 保持 **0.1.x EXPERIMENTAL / NO-GO FOR SCHEMA FREEZE**。
