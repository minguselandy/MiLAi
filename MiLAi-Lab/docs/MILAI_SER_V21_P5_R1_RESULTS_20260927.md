# v21 P5 R1：读取减少，完整业务参数仍有四例失败

状态：`FAIL_REFLECT_AND_CONTINUE`，严格预注册判定2/6通过。金额与保留值实例中，两臂均取得当前版本、处理旧回复并使用正确数值，但把目标`item`缩写，不能改判为通过。低排名无关更新两臂都通过；A5将该例exact get从3降为0，却没有降低总tokens。

| 实例 | A4实际参数 | A5实际参数 | 预注册结果 |
| --- | --- | --- | --- |
| numeric_amount | `Cedar-27`, 6595 | `Cedar-27`, 6595 | 两臂FAIL；完整目标应为`invoice Cedar-27` |
| retained_metadata | `Elm-12`, 48 | `Elm-12`, 48 | 两臂FAIL；完整目标应为`container Elm-12` |
| irrelevant_lower_rank | `parcel Orion-17`, North | `parcel Orion-17`, North | 两臂PASS；Y实际低于current primary且已送达 |

所有六例均完成3条公开消息、5次生成、批准后1次业务动作，Host memory写入0、更新后Host search 0。金额由1774变为6595，retained实际取得元数据已变的X@2，旧助手正文被降权；完整参数判定仍失败。六例各3次demotion，机械precision/recall合计18/18；这是snapshot风险，不是逐词因果。

## 成本与源码

| 实例 | A4生成tokens | A5生成tokens | A4 exact get | A5 exact get |
| --- | ---: | ---: | ---: | ---: |
| numeric_amount | 4450 | 4516 | 3 | 3 |
| retained_metadata | 4592 | 4561 | 3 | 3 |
| irrelevant_lower_rank | 5161 | 5213 | 3 | 0 |

无关例A5的projection CPU/wall为2.833/2.219ms，A4为6.760/7.979ms；单次开发运行不能推出稳定延迟收益。两臂普通生成文本和ID不同。更少Store.get是可见机制结果，总tokens反而增加52，不能称为整体成本获胜。

本组六例30次生成，输入27457、输出1036、合计28493tokens；20次embedding/446tokens；15次exact get；projection CPU33.887ms、wall46.048ms（其中get wall19.004ms，不相加）。Provider回执wall12.146秒。无Judge、unknown usage或截断。连续SER账本累计71生成/65327tokens/1035embeddingtokens、33次get，历史费用继续保留。marker共558片段tokens已在输入内；存储分项见[accounting](../data/manifests/milai-ser-v21-p5-accounting.json)。

源码64文件mapping `142ce5dfcc5ecf0f79166cff0c1ad710daeff5e8aac3010ee74db50ad8de70e2`；[lock](../data/locks/milai-ser-v21-p5.lock.json) SHA `3ac92f27d6ac890ff66d03ce1ffbf7d4b160f34d87a4f23ede8a1d7b2c0ede83`。11条必要窄测、ruff、mypy7文件及两项边界通过。唯一必要build通过，sdist已包含25个diagnostics文件及v21配置/锁/CLI，wheel含投影包，闭合v20延后的diagnostics打包项；不重跑模型用于发布。vLLM与Product行为未改。

见[执行前冻结](../data/manifests/milai-ser-v21-p5-freeze.json)、[真实结果](../data/manifests/milai-ser-v21-p5-results.json)。锁中的`evaluation_protocol_sha256`保留v20参考协议，当前P5使用`protocol_sha256`指向[v21协议](../data/manifests/milai-ser-v21-protocol.json)，freeze亦明确该协议。P4真实源码checkpoint为`3ecad01dcf2f3f07bc4a44926848597a2e63f71b`，旧结果不覆盖。

## Failure Review

Observed failure：四次实际业务调用省略类型词，违反冻结的完整item参数评分。Expected mechanism：处理旧值污染后，对批准的完整对象记录当前数值。Actual causal chain：正确检索→真实update→当前正文送达→旧回复降权→正确数值、缩写目标。First broken link位于业务目标标识的表达合同，证据不足以将它归因于rank策略。

H1：模型按常见业务习惯把类型词视为说明、把后面的编号当标识，属于通用目标复制错误。H2：fixture工具仅声明`item:string`与“for an item”，没有明确完整引用规则，严格rubric比公开目标合同更精确。两种解释兼容，但对应的修复不需要改SER。H3作为反例：即使显式要求完整引用，模型也可能继续缩写，届时才说明更普遍的工具参数遵循问题。

最小通用候选是在新版本fixture的item属性description中加入同一句完整引用复制要求。公开任务、CRUD边界、action-critical value和预期参数不变；不添加枚举、const、参数替换、业务真值门或输出归一化。现有Sol独立只读核对认可该定位与最小对照。

潜在混淆：新工具描述会增加输入tokens并可能影响普通生成；这属于诊断工具合同修正，不能冒充SER算法改进。旧四次失败仍永久失败。下一实验只运行受影响两例各A4/A5，共4条新轨迹；原irrelevant证据保留但标明其工具合同仍是v1，不能汇总成全新统一合同的六例同轮成功。

Continue理由：当前证据适应链和get选择行为均可观察，问题可用同一通用合同澄清检验；没有依据增加第二模型、硬业务gate或调vLLM。P6在此小修复结果后继续，不能直接进入formal。

## Reflection（总计划§32）

| 问题 | 回答 |
| --- | --- |
| 支持什么假设 | rank候选可在本无关例省去Y读取；金额与retained仍实际取得当前版本。 |
| 反驳什么假设 | 减少exact get不保证tokens下降；数值正确不代表完整动作参数正确。 |
| first broken link | item目标表达与严格完整引用评分不一致，出现在两臂同样位置。 |
| 更简单解释 | 工具合同未说明类型词属于标识，模型做了常见编号缩写。 |
| 更简单方法 | 先澄清fixture工具合同，无需修改记忆算法或引入action grounding。 |
| 复杂度是否合理 | rank/count两个可调参数仍小；当前收益仅局部get成本，不扩大效率主张。 |
| 过拟合风险 | 修复来自已见失败，故新样例继续归development；同一句规则用于不同对象类型。 |
| 应加什么反例 | 在retained不同类型对象上同样复制完整引用；未受影响irrelevant保留为独立控制。 |
| 下一步 | Continue到4-run目标合同澄清，再按证据完成P6。 |
| 为什么 | 可区分公开合同歧义与一般遵循问题，且不注入正确业务值、不改变旧评分。 |

复现使用`tools/run_milai_ser_v21.py prepare/run`，模板配置`configs/milai-ser-v21.json`、上述lock、v1 fixture/freezes及freeze内的两arm。新run ID和空namespace、独立ignored路径、DSN环境变量、连续账本规则沿v20。原始轨迹在`artifacts/ser-v21/p5-{a4,a5}-{case}-r1/`。目标合同修正另建fixture版本与阶段freeze，不覆盖这轮。
