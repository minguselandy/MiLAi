# P7 R1：暴露回归未收敛，继续开发

同源B1/A5已执行原十二例和MERIT arc0的四次预定运行。诊断语义分别8/12、7/12；两条MERIT轨迹都在episode 2第一个公开消息耗尽12次生成额度，未形成完整arc分数。不能把两条已完成episode的成功报成完整5/5，也不能宣称SER效率或任务收益。本轮结果保留，P7及长程Goal继续。

## 实现与冻结

新 `tools/run_milai_ser_v22.py` 只初始化现有Store/observer/projection并调用原诊断及MERIT runner。两个runner仅修正实际projection.recipe_id身份，loop与scorer未复制。A5核心算法、authority、schema和vLLM均沿用P6最终版本；B1不注入authority。输入、世界、业务schema、原rubric和顺序逐字不变，两臂各用独立空namespace。

- 前身检查点：`010ada50bddc6f208ce4311fe311beff4c5c4551`，已由Luna核对GitHub remote。
- 本轮66文件mapping：`6df42a956fbde97e4a1421bc3179b11026ff0ef65c2c93fec280dce25c2e3b3e`。
- [源码锁](../data/locks/milai-ser-v22.lock.json) SHA：`97821d7d0db2a6e4fe025c1fc63534057db8b133b48c697fb804f75ec7ab2247`。
- [协议](../data/manifests/milai-ser-v22-p7-protocol.json)、[暴露输入冻结](../data/manifests/milai-ser-v22-p7-exposed-freeze.json)、[运行冻结](../data/manifests/milai-ser-v22-p7-freeze.json)、[汇总与连续账本](../data/manifests/milai-ser-v22-p7-r1-results.json)。

20项受影响窄检查、ruff、mypy 11文件、Lab/tools边界与CLI/config检查通过。一次必要build已把v22入口/config/lock、P6R2 lock及55个diagnostic文件纳入sdist；wheel包含投影和原exposed runners，无artifacts或私密产物。打包收据随运行freeze保存。没有新decoder probe、全套测试或vLLM服务调整。

## 原十二例：B1 8/12，A5 7/12

Root逐条阅读全部真实答案、实际记忆内容及工具/业务收据，沿用v16的语义边界。原v14专有材料句柄与maintenance字段不是LangMem要求，rubric从未进入runner。

| 例 | B1 | A5 | 证据 |
| --- | --- | --- | --- |
| d01 | PASS | PASS | 540，未保存临时计算 |
| d02 | FAIL | FAIL | courier消息成功，但回执/要求未保存；下一session空搜索 |
| d03 | PASS | PASS | ISO日期规则保存、检索且范围正确 |
| d04 | FAIL | FAIL | 解释READY含义，却没把READY放在末尾 |
| d05 | PASS | PASS | Cedar十分钟accessibility review，未提前执行 |
| d06 | PASS | PASS | 日期分界前pounds、后kilograms |
| d07 | PASS | PASS | EVEN，未保存临时分支 |
| d08 | FAIL | FAIL | Juniper待办已保存，下一session漏搜 |
| d09 | FAIL | FAIL | 双时区分支已保存，下一session漏搜 |
| d10 | PASS | PASS | 临时房间未保存 |
| d11 | PASS | FAIL | 两臂都保存Nina/log提醒；仅B1本轮下一session搜索 |
| d12 | PASS | PASS | 小写m0及同型号connector保存、检索正确 |

完整独立判定见[B1语义](../data/manifests/milai-ser-v22-p7-b1-diagnostic-semantic.json)与[A5语义](../data/manifests/milai-ser-v22-p7-a5-diagnostic-semantic.json)。历史v16 B1为7/12，d11当时也漏搜，旧分数不替代当前matched基线。

d11的第一断点在搜索前：A5第二session首个请求只有system+user，projection.items和derived_rebases都空，仍注入63-token来源权威协议并直接回答。B1同位置无这段协议，随后自然搜索。H1是无证据时的额外authority扰动检索决策；H2是温度0下仍有运行波动，历史B1漏搜提供反例；H3是普通ReAct自身没有稳定识别隐含历史依赖。没有stale正文、exact refresh或derived demotion参与这个差异，因此不能指控或赞扬rebase本身。

通用候选为仅在实际memory item或可证derived风险存在时附加authority；空search/无memory请求恢复B1同一system合同。assistant-only stale须由derived_rebases继续启用，不能按user关键词、case或预期答案判断。该候选尚未实施，须与runner局部失败隔离分开验证。

## MERIT：两臂同一位置中止

两臂episode 0/1的原native checker均成功，共完成3个公开消息；但没有任何manage_memory调用或Store写入，约定金额未跨episode保存。episode 2第0消息要求从当前笔记退款，原始world的get_order不含该约定；B1做10次空search，A5做8次空search，夹杂政策查询，分别用满本消息12次生成后中止。没有refund业务动作。

每臂共18生成；完成2/5 episode，尝试4/7公开消息，完整native/dependent分数均为未完成。episode 2的另一个消息及episode 3/4未执行。原interruption、checkpoint、真实world、工具收据和费用全部保留；没有提高max_calls、续加同消息额度或借用旧成功轨迹。

### Failure Review

- Observed failure：没有保存早期约定，后续搜索循环使整个arc提早中止。
- Expected mechanism：普通LangMem形成可跨episode使用的记忆，之后按当前内容行动；单个失败任务不应遮蔽后续独立任务的结果。
- Actual causal chain：公开约定→发送确认但0记忆写入→新episode空bank→反复search/policy→容量错误→外层runner停止。
- First broken link：语义链是formation；评估覆盖链是runner把单消息容量耗尽升级为整arc停止。SER版本链没有输入对象。
- H1：未写入导致空结果；H2：已写入但scope/ranking/投影丢失。实际0operations/0revisions、episode边界Store为空支持H1，反对H2。H3：Host缺少停止空检索的判断，解释成本放大，但不会凭空恢复从未保存的约定。
- Generic repair：先加opt-in局部容量失败隔离，保留当前world/Store和旧checkpoint，记录失败及未尝试消息后进入下一独立episode。Formation另属总计划§14的独立研究，不能伪装成SER修复。
- Confounds：协议文本、运行波动、是否形成记忆和全arc early-stop相互影响；不能用native已完成子集证明整体提升。
- Minimal next experiment：新的源码/协议/锁下，两臂同一arc各一run；不重跑已完成十二例，不同时改变authority。
- Decision：Continue。补齐失败隔离和完整覆盖，再针对无证据协议开销做单独最小对照。P8不提前通过。

局部失败隔离保持原native公式 `not pre_satisfied and checker(after_world)`；不把容量错误强制转换为业务世界失败。另列Host完成、错误索引与skipped消息；若cap前业务已成功，必须保留该事实。服务、Store、instrumentation等非本地容量故障仍按原路径停止。

## 成本与边界

| run | 生成 | generation tokens | embedding请求/tokens | exact get |
| --- | ---: | ---: | ---: | ---: |
| B1 diagnostic | 34 | 18869 | 13 / 373 | 0 |
| A5 diagnostic | 34 | 21024 | 13 / 342 | 0 |
| B1 MERIT（中止） | 18 | 18866 | 10 / 80 | 0 |
| A5 MERIT（中止） | 18 | 19858 | 8 / 57 | 0 |
| 本轮合计 | 104 | 78617 | 44 / 852 | 0 |

input74073/output4544。连续SER账本现为306生成/274357tokens/3689embeddingtokens/75版本解析get，unknown/truncation/Judge均0；本轮两次容量失败不等于token truncation。所有历史费用仍封存于history。

A5的52次生成中48次没有memory item，所有请求却均带authority；4次CURRENT交付，0stale/0deleted、0get、0demotion。rebase precision/recall、stale-consumption与refresh precision的0/0均undefined，不能称零误干预或选择性成功。A5记录23条ordinary lineage，其中大量为空快照；没有新增持续语义State。

本轮projection CPU16506967ns/wall12394227ns，Provider收据wall43.700508秒；它们与端到端过程时延不同。trace2895453 bytes、instrumentation SQLite733184 bytes、checkpoint1191936 bytes；journal/共享PostgreSQL不混入这些分项。B1观察器的额外读和存储见各run结果，不能当成版本解析get。固定authority片段63tokens×52=3276已计入Provider费用，不再次相加，也不把反事实删文本估算冒充实测节省。

## Reflection

1. 支持：真实任务的第一瓶颈可能是形成/检索，并非旧derived污染。
2. 反驳：十三个机制控制通过就足以推定原任务不退化或总成本下降。
3. 第一断点：d02/MERIT是formation，d08/d09/d11是漏搜，d04是指令遵循；整arc early-stop另属runner覆盖缺陷。
4. 简单解释：没有被写入的记忆无法由SER恢复；无stale场景的额外authority可影响普通决策。
5. 简单方法：局部容量错误按episode记录，先复用原loop/scorer继续覆盖；不构建新控制平台。
6. 复杂度：接线必要，但无证据时仍注入authority的开销不合理，需独立最小化。
7. 过拟合：原数据全已暴露，任何后续修复都只算开发；不按d11或退款领域写条件。
8. 反例：容量失败后下一episode必须继续，服务故障仍停；空memory与assistant-only stale必须区分。
9. 决定：Continue P7；P8/formal尚未开放。
10. 理由：机械投影本轮未失效，却有明确覆盖与成本问题，先修复可分辨的小链路，Formation留独立Goal处理。

复现使用本轮锁、config、新CLI的diagnostic/merit模式及 `--exposed-freeze`；四组freeze保存完整参数与prepared SHA。不要覆盖R1产物，后续R2须新namespace/输出/锁。Product Schema/API/权限/Canonical均未改变。源码及紧凑失败证据由Luna发布，整体项目继续。
