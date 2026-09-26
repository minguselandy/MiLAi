# Reconciliation R1：引用送达，动作后仍未更新

[R1方案](MILAI_LIFECYCLE_V24_RECONCILIATION_R1_PLAN.md)的同源B1/R各完成三例、六条公开消息，严格均2/3。两臂各准确保存六条独立记忆，后续实际检索、业务参数和结果报告均正确；成功发运后却均保留“尚未发运”的pending正文，act阶段零manage调用。失败动作保持pending，无关通知保持原记忆，两个反例通过。R没有改善动作与记忆的一致性。

76文件mapping为`f594525fa1cbdf8c422b28ed4a8e73f8d209026d6b8cf5a612a724f9fc7fe8e1`，lock SHA为`e6b04d6fbad64ee28f392353215168a2b059a19871c2d81106952f75aa6dc931`。详见[汇总](../data/manifests/milai-lifecycle-v24-reconciliation-r1-results.json)、[B1](../data/manifests/milai-lifecycle-v24-reconciliation-r1-b1-results.json)、[R](../data/manifests/milai-lifecycle-v24-reconciliation-r1-r-results.json)。F和SER均关闭。业务回执仍是合成fixture，不能代替P12的真实有状态副作用模拟。

Root从实际HTTP/journal重建成功回执、动作生成request、FULL search材料与EXACT scoped refs，再核对首system提示。R的两个合格请求2/2实际送达，每次两个候选；失败ok:false请求不触发。候选顺序保留原返回顺序，包含无关访问事实，程序未做语义相关筛选。15/15请求契约正确，15/15工具材料FULL；触发前B1/R使用相同system/tools/schema，动态UUID、时间和namespace不同。

| 指标 | B1 | R |
| --- | ---: | ---: |
| 严格case / action-memory consistency | 2/3 | 2/3 |
| 成功相关动作后stale-current | 1/1 | 1/1 |
| 被错误修改的原entry | 0/6 | 0/6 |
| act阶段manage / 不必要maintenance | 0 / 0 | 0 / 0 |
| 正确业务动作与报告 | 3/3 | 3/3 |
| 完成公开消息 | 6/6 | 6/6 |

4条候选中只有1条语义状态改变，候选不是程序相关性判决。零误更新与零必要更新同时出现，不能据此宣称选择性有效。

## 独立能力控制

随后按[另行冻结的控制](MILAI_LIFECYCLE_V24_RECONCILIATION_CAPABILITY_PLAN.md)，在同源B1、新namespace中只追加用户明确要求“成功后更新原pending entry”的指令。普通Host实际完成search→dispatch→manage_memory(update)，原ID正确，无关entry保持；**但严格内容仍0/1**。实际写入末尾为“successfully dispatched (ID: DSP-7421) and received”，工具仅报告`status: dispatched`，没有签收证据。不能把“工具操作链可用”升级为“更新正确”。原始内容保留在[能力控制明细](../data/manifests/milai-lifecycle-v24-reconciliation-capability-b1-results.json)。

新增控制指令中的“actual outcome and receipt”可能被误解为货物已收到。当前证据同时支持两种解释：该词引入了任务合同歧义；或者Host会把较早状态自行扩展为后续完成状态。下一步需先用单处通用任务合同澄清区分这两种解释，不能马上把R正文复制候选当成已获准有效修复，也不应检查已经成功的Store update路径。

上述定位后，按[唯一澄清方案](MILAI_LIFECYCLE_V24_RECONCILIATION_CAPABILITY_R2_PLAN.md)只将该短语换成“actual returned status and identifier”，新namespace同源单例严格通过1/1：真实update原ID，保留6 display panels/EXH-284/gallery dock D-2，准确写入dispatched与DSP-7421，没有received，无关访问entry原文保持。[两个控制的汇总](../data/manifests/milai-lifecycle-v24-reconciliation-capability-results.json)保留首次0/1。这支持任务措辞歧义解释，但一次通过不能证明一般事实边界可靠，也不改变R1的2/3。接下来允许一次独立原content呈现候选，F不重开。

## Failure Review

Observed failure：R引用提醒没有引发必要更新；明确用户指令引发更新但增加无证据的后续状态。Expected mechanism：普通Host依据实际动作结果更新相关记忆且保持无关事实。Actual chain：准确seed→两条实际FULL/EXACT检索→正确业务调用/回执→R提示送达→直接final；能力控制则在回执后真实update，但写入超出回执。第一断点分别是自主操作选择与更新正文的事实范围，不是同一个错误。

H1：候选未实际送达或缺少更新工具；HTTP验证和真实update控制反对此解释。H2：只有id/revision的候选需回查早前正文，模型未将一般提示转成操作；尚未证伪，可用一次逐字正文呈现对照检验。H3：普通Host根本不能在业务后连续CRUD；能力控制的实际调用链反对此解释。H4：显式用户任务优先于系统层一般维护提示，且“receipt”造成状态歧义；与当前结果相容，不是对模型内部原因的证明。

通用修复顺序：先澄清控制任务的实际返回状态/identifier合同；仅若严格控制通过，再考虑一个R候选呈现变量——附上已经实际送达的原content，不改语义、不另读Store、不改变cue或新增模型阶段。仍失败则停止该轻量提示家族，继续P12，不能通过更多措辞/领域规则寻找最好轨迹。Confounds包括单个正例、已暴露合成任务、动态运行标识和模型输出差异；控制不是R方法收益，也不是正式未见验证。

## 成本与必要验证

B1：15生成，11106输入+637输出=11743tokens；R：15生成，11423输入+616输出=12039tokens。各9次embedding/220tokens。R总费用多296tokens，没有质量收益；实际两次marker直接输入增量154、151，共305tokens，其余差额包含动态标识和输出轨迹差异，不能简单全归因于提示。R的15次projection合计CPU1827283ns/wall1396908ns，无程序Store读/自动写/独立模型阶段。

R1合计30生成/23782tokens/440embeddingtokens，连续644/581303/5656/75exact version-resolution reads。能力控制另6生成/5014输入+333输出=5347tokens、4次embedding/114tokens；两阶段合计36生成/29129tokens/554embeddingtokens，连续650/586650/5770/75。全部unknown/truncation/Judge=0。观察层每臂因六次seed另有12次Store读，明确与程序版本resolution reads分开计数。

澄清控制再6生成/5009输入+323输出=5332tokens、4次embedding/114tokens；两个能力控制合计12生成/10679tokens/228embeddingtokens。R1及全部控制累计42生成/34461tokens/668embeddingtokens，连续656生成/591982tokens/5884embeddingtokens/75exact reads。未因前一控制失败清零费用；源码不变，未重复测试/构建。

B1/R trace分别521791/530520bytes，sidecar各163840bytes，checkpoint各184320bytes。Provider wall分别6.477/6.247秒，进程12.376/12.770秒；单次时间差不解释为稳定提速。完整observer计时在run明细中。四项窄mock/身份/F回归、ruff/mypy与一次package通过，能力控制只改fixture，不重复测试或构建。

R实现仅新增scoped sidecar只读查询、成功回执适配器和薄CLI接线；普通Host负责所有CRUD。研究内部factory多传observer，不改变Product公开API/Schema/权限/Canonical、旧M1/ODR或vLLM设置。旧F/R失败与已执行锁保持。此阶段源码和结果交由Luna提交，master仍ACTIVE。

## Reflection

1. 支持：业务成功和此前实际记忆送达可以低开销精确关联。
2. 反驳：提供id/revision候选就足以触发这次必要更新。
3. 第一断点：R操作选择；控制另有正文范围越界。
4. 更简单解释：显式用户指令与系统维护提示的执行不同，且receipt措辞有歧义。
5. 更简单方法：先澄清控制合同，不加自动写入或持续语义状态。
6. 复杂度：当前adapter有界，但没有语义收益，不默认启用。
7. 过拟合：不按实体/数量/动作名筛选候选；下一呈现试验若启动只复制已送达正文。
8. 反例：failed/no-op已保留；后续仍要求不越过实际返回的状态。
9. 决定：唯一控制澄清已通过，Continue一次原content呈现试验；R修复需重新冻结，P12设计已完成待释放实现。
10. 理由：普通Host准确组合能力已在明确用户任务下得到单例验证；当前仍不能宣布R有效，下一步只检验候选关联呈现，不扩大benchmark或换词堆叠。
