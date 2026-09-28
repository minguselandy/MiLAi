---
status: ACTIVE
scope: MiLAi-Lab / RESEARCH_PROTOTYPE
plan_sha256: ff79dcd0e24458175c520913bac29b842a69b5ebbc15681545748b14b2eb52a2
baseline_report_commit: 676fe4d32005cefbfb01daa4fe24425edf5a5e21
baseline_method_commit: 24ef49945cd12eccbd85792fee3c256bf3fe6d2a
research_goal: NOT_ACHIEVED
product: NO_GO
---

# NEXT_DEVELOPMENT v5 执行记录

用户实际 Goal 明确要求完整阅读并执行[v5计划](MILAI_NEXT_DEVELOPMENT_PLAN_20260928_v5.0.md)，已核实为active。
Root完整读取1,204行；原文DRAFT/PAUSED/NOT_STARTED原样保留，授权来自新Goal。
此次恢复撤销旧v4暂停对新任务的限制，不预设任务结束自动暂停；若无新的暂停要求，以实际完成审计决定状态。
不把评价协议完成或局部工程通过等同完整基础Memory稳定。

当前树 `/cra/memory/mx_memory/MiLAi-worktrees/next-development-v5`，分支
`feat/lab-obligation-contract-v5-20260928`，从已发布v4报告提交建立。
原main、旧树/草稿/失败/分数/锁/账本保留。v4 [PR67](https://github.com/minguselandy/MiLAi/pull/67)
最终[Fast CI](https://github.com/minguselandy/MiLAi/actions/runs/36383042021)已读回success，Full skipped。

## 完整要求与验收表

| 项 | 必须证明的内容 | 当前状态 |
| --- | --- | --- |
| V0 / §6 | 冻结v4身份；六脚本legacy/explicit/memory/optional分解，不改旧分 | COMPLETE；50项来源身份、6脚本、12轨迹/30答/44请求核平 |
| V1 / §7 | 四层rubric；每个task-failing要求有用户可见依据，持久要求有意图依据；diagnostic不改任务分 | COMPLETE；20项窄检查与实际两轮CLI通过；原文依据人工复核 |
| V2 / §8 | 冻结HTTP的obligation→user→formation→delivery→answer链；工具任务另看args/world；无LLM评分 | COMPLETE；6×55人工链已组合，legacy与diagnostic分列 |
| V3 / §9 | 九类请求组件成本；重复/仅审计/只写所需信息；确定性候选old/new tokens和保留证明 | 离线测量完成；R2仅JSON空白候选节省331输入tokens（1.19%），未部署 |
| V4 / §10 | 8–10脚本、每脚本2–4session；完整/部分/临时/独立/引用/只读/删除/助手冲突/动态world/moderate bank | INPUTS_FIXED；10脚本/27消息/133义务，10个正式零模型prepare通过，待发布后freeze |
| V5 / §11 | 当前v4 R2一方法一次前瞻验证；explicit≥95%、所有requested持久变化正确、无假保存/误持久化/重复业务/隐藏要求失败 | NOT_RUN |
| V6 / §12 | 仅真实失败首断点触发单层通用修复；约束修复须旧回归＋至少两个新约束验证 | CONDITIONAL_NOT_TRIGGERED |
| V7 / §13 | 真实world与助手历史冲突覆盖；实际旧transcript保留、current工具/有效来源和无重复副作用 | 新样本必须覆盖；修复条件待V5 |
| V8 / §14 | 真正检索瓶颈后同bank/history/model/tools/world的all/query/working-query/lazy-A比较，全成本 | CONDITIONAL_NOT_TRIGGERED |
| V9 / §17–20 | 四层证据、失败首断点/两解释/反思、成本、复现、Go/Pivot/Stop、逐项完成审计和Luna发布 | PENDING |

§5将V7标条件项，§10与§20同时要求新样本覆盖两个边界：V4/V5因此包含H/I真实验证，
V7的进一步修复只在真实失败后触发。不能以“条件未触发”跳过基本world/assistant验证。
V3允许离线确定性精简候选，但§11/15要求V5首先运行现有方法；候选不进入首轮runtime。
这既提供成本证据，也不把未经验证的成本改动偷偷并入首轮方法。

## 首个断点与竞争解释

v4 R1临时格式是明确当前义务失败，非持久污染。v4 R2 field_plan三个点名字段和不预约均满足，
旧rubric额外要求完整计划，未复述物品被判fail。两种解释分别为“current plan自然要求完整复述”与
“rubric加入未显式点名的额外完整性要求”。v5保留旧5/6，另列explicit pass / full-record incomplete，
不能继续以该例独自证明runtime消费bug或把旧分改成6/6。

## 职责与执行边界

Root拥有文档、输入/rubric、冻结、所有真实调用、评分/分析与账本。复用Sol xhigh作为唯一源码负责人，
当前只允许离线analysis与必要局部检查；Luna high拥有授权Git提交推送；Astra仅具体困难冲突。
V0–V5 runtime不变，真实HTTP并发1，不启动Judge/controller/selector/第二模型或新服务。
保持Host参数、公开工具、strict CRUD、Retained合同和Product NO-GO。

初始只读核对无实验runner。连续账本为原树 `artifacts/ser-v20/budget.json`，
**2994 generation calls / 3,785,491 generation tokens / 21,237 embedding tokens**，
SHA `e47de5a370b7c6dad581d836a440411055c01c137ec4c589f95389109a4ca668`。
V1/V2离线工具和V3请求分析已完成；V4完整输入已固定，正式prepare为159项源码。当前v5新增真实generation/embedding为0。开发代理和离线tokenizer不混入实验费用。
runtime永不读取rubric/gold；只读实际证据与人工判定严格分开，未知值不自动变pass。
