# v13.2 紧凑材料的限定工程验收

[机器验收](../data/manifests/v13-2-compact-material-acceptance.json)仅准入新的实验准备。
原候选930fbae与接受存储实现合入后，最终执行源码为209文件、映射
`676ad5dcc1415e30656b433c885804792a5377ecee6a3f4a83d91fb1a3e21e91`。
旧默认仍为`full_v1`、`bank_prefix`；R5只启用`compact_v1`，继续默认存储。
Source、排名、选中候选、读时CAS和原R4指令不改变，Product仍NO_GO。

这次候选联合改变材料表示与正文分配。完整实际来源role/ref/hash、记录ID及完全相等的重复
Scope共享字典；显式解码说明与全部表计入2048。新截断记录已有完整version hash时省去
重复生成的正文hash，既有hash及Source摘要不删除。已选current/history按实际记录身份和
首次记录顺序分组接纳metadata，再按实际增量token成本升级可行完整正文，原位置打破平局，
剩余预算分给真实前缀。冲突候选为完整组或明确空capsule，不由压缩解决冲突。
不能把联合效果归因于纯压缩；没有新模型、服务、Arrow运行依赖或SDK升级。

Source原34命令、154产物与最终850文件完整映射均由Root逐hash核对，12次失败保留。
最终原候选12项检查以9+3分批通过；旧26项/default字节比较在其各自源码身份，不冒称同一最终SHA。
独立合入后的32项检查（材料12、存储13、共存7）、26项默认与双边界、ruff五文件和mypy三源码
均在同一最终209执行身份通过。四legacy组合及event-bound的五组实际同bank对照相对于Root697567d
保持默认材料逐字节一致，目录及缓存envelope仅排除wall_ns/cpu_ns。Root另核对11个材料方法
相对930及五个存储/检索方法相对697的AST。主树转入后的运行文件/测试hash相同。
有限对照不能证明全部输入等价，未跑完整suite、远端CI或模型效果。

| 固定合成压力样本 | 普通tokens | 实际送达 | 实际省略 |
| --- | ---: | --- | --- |
| 英文 | 2046 | 1当前前缀、2完整旧正文 | 1当前单元、2 Source |
| 中文 | 2048 | 1当前前缀、2完整旧正文 | 1当前单元、2 Source |
| 西文 | 2046 | 1当前前缀、2完整旧正文 | 1当前单元、2 Source |

Root独立解码永久JSON并用实际Qwen tokenizer复算这些数值；所交付ID、Scope、来源绑定、
完整旧版本及当前真实前缀一致。当前四版本metadata枚举表示变体最低2245/2254/2257，
只说明这些具体变体超过预算，不能称全布局数学下界。固定合成时间提高可复现性；旧真实时间/hash
压力失败仍是原身份下的失败，不升级为普遍两旧正文保证。

其他样本也保留取舍：长历史1920tokens送当前加2/6旧正文、Source0；超长Scope不截断或改写，
语义单元省略而送实际Source，1246tokens；冲突样本2047tokens，候选整组空capsule及3/6 Source前缀。
writer模拟wire材料1953tokens，两次公开显式读取另付920tokens。实际模型/embedding HTTP为0，
MockTransport不计实验样本。重开需要通过公开API重新建立同一可信当前来源边界，不从旧事件猜边界。

解码的`source_refs_from_bindings`可在record或shared_defaults中，而完整bindings可在外层historical
unit中。Root最初独立decoder误假定record自带bindings，KeyError原脚本和回执保留，修正后通过；
另一次Root索引字段类型误读也保留，未改变运行实现。早期WIP仅有完整hash maps和失败stdout，
并非完整历史源码blobs；部分临时SDK库已回收。未包裹的baseline探索及被覆盖的首inspection JSON
排除于接受证据，现有永久压力JSON与可用完整units保留。

[R5设计](../data/manifests/v13-2-e0-r5-design.json)仍需全840性能协议结束、原账本严格审计，
随后另冻原24/48、完整源码/config/CLI、实际目录/prompt、环境、模型route、rubric和driver。
R0–R4失败与费用独立保留，22/24、完整旧更新及来源语义门禁仍未通过。
资料继续存入[原文、项目及总结索引](V13_2_DESIGN_LITERATURE.md)。
