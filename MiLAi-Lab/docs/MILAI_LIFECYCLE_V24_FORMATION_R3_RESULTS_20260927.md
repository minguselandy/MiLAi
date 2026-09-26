# Formation R3：事件提醒送达，形成仍失败

[预注册方案](MILAI_LIFECYCLE_V24_FORMATION_R3_PLAN.md)完成五个小实例、七条公开消息。两个未来事项仍为0/2形成、0/2后续可用，原四例严格2/4；新增一次性业务测量通过1/1，单独报告，不加入旧对照分母。三次业务动作均正确，三个紧接回执的实际HTTP请求均收到提醒，但没有manage_memory调用，所有session结束时Store均为空。按预定停点停止F cue家族升级，转入独立Reconciliation；总Goal继续。

完整回答、动作、回执和费用见[run明细](../data/manifests/milai-lifecycle-v24-formation-r3-f-results.json)，评分与连续费用见[汇总](../data/manifests/milai-lifecycle-v24-formation-r3-results.json)。75文件source mapping为`390a1d7a5e0618e4a7ee22ab59d91ff8357ede2573a548d0f546f71ef2379846`，lock SHA为`3b41b19ff0400f76323831f10e57ad3dc46f4e4df2d3a97a82bcb750a91f6c53`。F2 cue逐字不变；新提醒只追加到首system请求副本，历史和工具正文不改，SER关闭。

Root从每次实际HTTP请求末尾ToolMessage及相应thread/generation/call/name/args/content/status的已完成journal条目独立重建触发资格，再核对projection事件和最终system。12/12请求契约正确，5/5工具材料FULL送达，3/3应触发请求实际含提醒；两个后续search均为空。3/3机械送达不等于语义收益；正反例均零写入，也不能据零误存声称选择性有效。f02后续回答的“No booking has been created”可能指当前轮，保留原句但不将其单独判为确定的历史虚称。

## Failure Review

Observed failure：收到真实业务观察后的明确提醒仍未触发持久化。Expected mechanism：普通Host在最终回答前应用已建立的未来用途规则，保存准确且有scope的最小记忆。Actual causal chain：用户明确未来用途→业务调用与真实回执→匹配提醒实际送达→直接final→跨session空搜索。First broken link是模型选择记忆操作；当前没有发现事件接线或内容送达缺口。

H1：静态提示只因时机不合适而失效；本轮业务回执后提醒仍失败，反对该解释作为充分原因。H2：当前Host在业务完成后强烈倾向直接结束，未执行系统层一般持久化规则；三轮结果与其相容，但没有模型内部证据。H3：公共CRUD能力失效；独立显式保存控制成功反对普遍能力故障，不能证明自主选择可靠。H4：两个正例不代表全部未来信息；样本很小，不能将此结果外推到所有模型/任务。

通用候选包括独立形成阶段或不同模型；前者增加额外调用与运行路径，当前轻量cue的因果假设经静态义务、能力控制和事件提醒已反复诊断，继续堆提示缺乏依据。保留这些候选为未来独立研究，不为了此两例新增自动正文规则、强制CRUD或另一个循环。最小下一工作是总计划§15已要求的独立R：成功业务回执关联此前实际送达的exact记忆refs，让普通Host更新或no-op；F提示关闭。

Confounds：原四例为已暴露开发集，B1/F2是固定历史参考而非本轮fresh matched；新增第五例只检验业务事件是否误导致临时存储。静态规则和事件提醒均属于模型可见干预，不能归因于SER。全部失败和旧费用保留，不重跑P9未见种子。

## 成本与验证

本轮12生成，6996输入+374输出=7370tokens；2次embedding/29tokens。原四例10生成/6152tokens，较F2同四例6043多109（提醒直接输入112，输出少3），较固定B1 5325多827。新增第五例独立耗费1218tokens。不能用五例总成本直接对比旧四例宣称matched变化。

F2 cue每次实际输入增量71，共852tokens；事件提醒每次56，共168。12次projection的CPU合计1024670ns、wall785103ns，事件写出在该计时外；无额外模型阶段、程序Store读取或自动写入。Provider wall4.264秒、整进程9.140秒；trace180534bytes、sidecar114688bytes、checkpoint118784bytes。观察层CPU33421266ns/wall650368212ns，额外Store reads0。

连续账本614生成/557521generation tokens/5216embedding tokens/75exact version-resolution reads；F1、F2、能力控制与F3合计46生成/26910tokens/159embedding tokens。本轮unknown、truncation、Judge、版本get均0。两项相关mock Provider/checkpoint窄测、ruff/mypy与一次必要package通过；旧默认路径和核心SER保持。vLLM、Product、旧M1/ODR设置/语义不改。

## Reflection

1. 支持：事件可用低开销准确绑定并送达，但自主形成与显式保存能力不同。
2. 反驳：只要把同一未来用途规则在业务回执后重申就能修复本组失败。
3. 第一断点：普通Host未选择manage_memory。
4. 更简单解释：当前任务结束倾向与提示执行不足，不必假设Store坏掉。
5. 更简单方法：停止此提示家族，而非新增持续状态或反复换词。
6. 复杂度：请求副本适配器有界；现有成本增加却无形成收益，不默认启用。
7. 过拟合：三个机制无实体/gold规则；继续依当前两例找更强措辞会增加风险。
8. 反例：临时业务回执通过，但零正例成功限制其解释；R另设失败/无关控制。
9. 决定：Kill当前F cue家族升级，Continue独立R和P12。
10. 理由：预定最小时机候选也失败，机制定位充分；总计划还有独立生命周期和真实脚本要求，不能以封存失败结束master。

复现须checkout本轮发布commit，再使用已冻结protocol/input/execution及新namespace，保持B1参考轮次标签和连续成本。原始trace与数据库保留本地ignored；公开manifest提供SHA、合成内容及运行身份。发布不触发额外模型调用或重复构建。
