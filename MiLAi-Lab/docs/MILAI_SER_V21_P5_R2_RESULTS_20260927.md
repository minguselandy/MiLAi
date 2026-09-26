# P5 R2：完整对象引用合同修正后4/4通过

状态：`PASS_REPAIRED_TARGET_CONTRACT_ADVANCE_P6`。两个受影响实例各A4/A5均通过原严格参数与机制判定：实际记录`invoice Cedar-27`、6595和`container Elm-12`、48；当前版本实际送达、旧派生回复处理和批准边界均正确。Root已读取四次业务回执。[R1](MILAI_SER_V21_P5_R1_RESULTS_20260927.md)四个失败不改判，全部费用保留。

本轮唯一变更是fixture业务schema的item参数description，要求完整复制用户给出的类型词与编号。没有更改SER源码、策略、authority、vLLM、公开消息、记忆内容/更新或评分。没有增加枚举/const/真值门。两种对象类型都恢复完整引用，支持“公开工具合同不够明确”的解释；仍不能排除普通提示遵循，且这是已见开发实例上的修复。

| 实例 | A4 tokens | A5 tokens | 各臂exact get | 原严格结果 |
| --- | ---: | ---: | ---: | --- |
| numeric_amount | 4664 | 4699 | 3 | 两臂PASS |
| retained_metadata | 4714 | 4739 | 3 | 两臂PASS |

四次新run共20生成：输入18110、输出706、总18816tokens；12次embedding/298tokens；12次exact get。机械demotion precision/recall各12/12，12条ordinary lineage，marker372片段tokens已在输入内。projection CPU24.623ms、wall33.643ms，其中get wall16.461ms；Provider回执wall8.145秒。无Judge/unknown usage/截断。连续SER账本91生成/84143tokens/1333embeddingtokens、45次get。完整存储见[accounting](../data/manifests/milai-ser-v21-p5r2-accounting.json)。

原irrelevant v1两臂结果保留为独立控制：A5 get3→0、tokens5161→5213。没有为了改名重复它，也不把R1成功部分和本轮合称一轮统一新合同的6/6。P5组件门槛现已成立，P6将在尚未运行的九例上统一同一完整引用说明；最终覆盖明确标记11例v2与1例既有irrelevant v1。

## Reflection（总计划§32）

| 问题 | 回答 |
| --- | --- |
| 支持什么假设 | 通用完整引用说明足以解决这两种对象类型的缩写问题，不需要改变SER。 |
| 反驳什么假设 | 此四例不支持必须增加action grounding、第二模型或强制参数替换才能正确执行。 |
| first broken link | R1的目标表达缺口在本轮消失；尚未验证的边界转向current冲突、no-stale和mixed状态。 |
| 更简单解释 | 普通模型对明确工具字段说明更易遵循；这不是记忆算法的新增收益。 |
| 更简单方法 | 公共参数说明即可，无需新运行时状态或业务校验门。 |
| 复杂度是否合理 | 只改fixture字段说明，冻结方法与已有11条检查/一次build复用，没有无关重复验证。 |
| 过拟合风险 | 两例已参与修复，永远是development；未见阶段不能复用它们作独立证据。 |
| 应加什么反例 | 对P6不同类型目标预先采用同一说明，检验删除/冲突与混合证据，不按结果变更rubric。 |
| 下一步 | Continue P6九例，然后P7已暴露回归。 |
| 为什么 | 最小合同实验通过，现有方法/成本门槛可继续检验，但未达到formal或总体完成条件。 |

方法源码与[P5 lock](../data/locks/milai-ser-v21-p5.lock.json)完全不变，64文件mapping仍为`142ce5dfcc5ecf0f79166cff0c1ad710daeff5e8aac3010ee74db50ad8de70e2`；R1源码checkpoint为`2c90dd376c3ec486ed154853a6d980eea8094610`。锁中的fixture合同是R1参考，本轮实际v2合同和逐例A4/A5相同性已在[新freeze](../data/manifests/milai-ser-v21-p5r2-freeze.json)冻结，prepare绑定各自新fixture hash。见[协议](../data/manifests/milai-ser-v21-p5r2-protocol.json)、[实际结果](../data/manifests/milai-ser-v21-p5r2-results.json)。

复现入口不变，改用`data/diagnostics/selective_adaptation_v2/{numeric_amount,retained_metadata}.json`及相应`freezes/`；新run/空namespace/连续账本。原始证据目录`artifacts/ser-v21/p5r2-{a4,a5}-{case}-r1/`。文件与工具说明变更没有重新跑单测或build；此前sdist的目录规则已覆盖diagnostics，当前构建回执只证明当时已存在文件，不声称包含后来新增的v2文件字节。
