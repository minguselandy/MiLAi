# v24 Formation R1：提示送达但没有形成收益

独立[Goal](MILAI_LIFECYCLE_V24_GOAL.md)的四例同源比较已完成。B1与F都只有临时计算和一次性格式两例通过；两个未来用途实例均未保存。保留失败，继续最小通用修复；R、P10/P12和master仍未完成。

输入、rubric和两臂顺序见[调用前协议](../data/manifests/milai-lifecycle-v24-formation-protocol.json)，全部真实请求前完成[source lock](../data/locks/milai-lifecycle-v24-formation.lock.json)与[execution freeze](../data/manifests/milai-lifecycle-v24-formation-execution-freeze.json)。新73文件mapping为`4701725c48bd652fde54ca80d821590aa47235860900765613c89afe95099be1`，lock SHA为`c31b8d1ce23a2401be9b28a351bf30d479c83b454b67ed8129c31d009f1632a3`。F只追加固定prospective cue；原工具/schema/loop/业务journal不变，不启用SER或R，不增加独立LLM步骤。

| 指标 | B1 | F |
| --- | ---: | ---: |
| 首session形成准确未来记忆 | 0/2 | 0/2 |
| 后续实际查询/回答可用 | 0/2 | 0/2 |
| 临时内容误存 | 0/2 | 0/2 |
| 严格case通过 | 2/4 | 2/4 |
| Host公开消息完成 | 6/6 | 6/6 |
| 正确模拟业务调用 | 2/2 | 2/2 |
| 生成 / generation tokens | 10 / 5325 | 10 / 6028 |
| embedding请求 / tokens | 2 / 29 | 2 / 29 |

Root读完12条公开消息的全部答案、工具参数/回执、持久记忆和实际Provider请求。两臂都正确发送Maple Courtyard的14棵rowan saplings约定确认，也正确取得Eastbank collection回执COL-4826、H-6、awaiting approval。随后直接回答，均没有manage_memory调用；各session结束Store都为空。下一session明确要求查笔记后，两臂各自search一次返回空并承认缺失。临时计算回答378，一次性要求回答恰好READY，没有多余写入。无错误业务动作或null插入。

## Failure Review

Observed failure：前瞻cue没有把已理解的未来事项转为持久记忆。Expected mechanism：普通Host判断下一相关session需要的约定/回执并调用原记忆工具。Actual chain：未来用途公开描述→业务成功回执→正确口头确认→无CRUD→新session空搜索。First broken link为初始session的持久化选择，不是检索排序、SER投影或Store丢写。

H1：`consider ... worth carrying forward`力度不足，模型仍把口头确认当成完成；H2：提示置于静态系统合同，没有在业务回执后获得足够注意。二者都与正确口头理解但零写入相容，当前不能区分。H3：提示根本未送达、工具不可调用或数据已保存后丢失；实际10/10 F请求包含精确cue，所有Store为空且没有写入尝试，反对送达/丢写解释；既有普通manage工具已执行过CRUD，此轮没有证据支持新增工具平台。

最小下一候选是把固定cue改为明确的条件性保存义务：若后续相关session需要该信息，使用原manage_memory持久化，口头确认不等于保存；临时内容仍no-op。仍由普通Host判断未来用途，不强制每轮写入，也不加第二次反思调用。先只改一个通用提示并新freeze，保持四例及B1参考。若仍失败再判断event-triggered提示是否值得研究。业务回执事件方案更复杂，而且本轮两个正例都有业务工具，不能先把事件出现当作语义重要性规则。

Confounds：仅两条正例，均是明确未来用途的业务情景；同温度不保证轨迹确定；临时零误存同时伴随正例零保存，不能称为成功选择。数据是独立开发fixture，已经暴露；没有泛化或未见收益结论。不重跑P9种子3/4，不按新结果改判旧分数。

## 成本与验证

两臂总20生成、10656输入/697输出、11353 generation tokens、4 embedding请求/58tokens；未知/截断/Judge/版本get均0。连续账本588生成/541964tokens/5115embeddingtokens/75exact resolution reads，旧费用不清零。F cue本体66tokens，放入完整实际请求每次额外67tokens，10次合计670输入tokens；实际总费用增加703（另有33输出tokens差异），未改善任务表现。这是固定轨迹的提示开销核对，不是额外模型试跑。

完整结果见[汇总](../data/manifests/milai-lifecycle-v24-formation-r1-results.json)及其两臂明细。trace合计319809、instrumentation212992、checkpoint204800 bytes；新persistent semantic State为0，共享Store和现有历史存储不是0。两条受影响窄pytest、ruff/mypy与一次必要package通过；无全量suite。sdist沿既有diagnostics目录包含独立rubric，wheel不含，runtime未读取rubric。vLLM设置和Product均未改。

## Reflection

1. 支持：最早的缺口仍是持久化选择，普通工具调用本身可完成。
2. 反驳：只增加弱前瞻提醒就足以形成未来记忆。
3. 第一断点：成功回执后的最终回答之前没有manage_memory。
4. 更简单解释：模型把“考虑保存”当成可忽略建议。
5. 更简单方法：明确条件义务的固定cue，保留no-op边界。
6. 复杂度：先不加触发平台、持久状态或额外模型步骤。
7. 过拟合风险：四例已暴露，只允许通用语义指令，不嵌入实体/答案。
8. 反例：继续保留临时计算、一次性格式；将来还需非业务未来事项。
9. 决定：Continue最小Formation修复，R另行冻结。
10. 理由：提示确已送达但行动义务不足的解释可用更小改动证伪；此轮本身不支持保留F为默认方法。

复现：使用本轮发布commit、新lock、两个冻结prepared/config和对应CLI；各新运行须独立空namespace、沿用连续账本。原run目录不可覆盖，不为发布重跑。旧v23 lock的过时描述字段勘误已写入其结果文档，历史字节保持。
