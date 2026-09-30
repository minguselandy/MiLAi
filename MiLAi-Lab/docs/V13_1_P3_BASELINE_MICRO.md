# v13.1 P3 外部基线微型检查

状态：READY_FROZEN_FOR_REAL_MICRO；完整P0–P8仍ACTIVE，Product NO_GO。

本轮按照原规划4.3节，使用同一份预先冻结的公共输入分别检查Mem0 OSS与SimpleMem-Text。
固定6类/每臂22步骤：存储重启、偏好变更、相对日期、真实工具角色与ID、owner隔离、失败成本。
[协议](../data/manifests/v13-1-p3-baseline-micro-protocol.json)、
[公共输入](../data/fixtures/v13-1-p3-baseline-micro.json)、
[配置](../configs/v13-1-p3-baseline-micro.json)和
[独立离线检查合同](../data/diagnostics/v13-1-p3-baseline-micro-rubric.json)分开保存。
运行器不导入scorer或读取rubric；archive只传当前步骤的records，后续问题不进入writer。

历史由公开脚本生成，并明确标注assistant消息不是模型过去执行记录。工具用例调用实际
本地ApplicationWorld，真实返回reserved_label_failed与label_status=not_created，原始预约ID
及user/tool SourceEvent保留。该用例检查载体和原生记忆保留，不用于声称原生Agent动作成绩。

SimpleMem新增显式trace_equal_v1 opt-in：每个原始事件的完整JSON作为有标记的历史数据传入
native Dialogue.content，speaker/timestamp映射不变；旧默认载体、POLICY和scope字节保持。
原始event/id可到达模型输入，不意味着native MemoryEntry拥有原始来源字段或必然保留ID。
固定SDK MockHTTP载体检查12项通过；初次10个失败和lint错误保留在ignored artifacts。

新运行器每个步骤使用独立解释器进程，在同一case资源上执行原生API和读回；两臂按case
交错串行。共同reader只接受实际原生search结果，调用与原生内部生成共享每步骤容量；
所有embedding、原生重试与reader调用都进入原连续账本，不能设免费补充writer/reader。
SDK初始化、提供方故障、容量拒绝及首个错误留下独立terminal记录，不以重跑覆盖失败。

Mem0沿现有add_archive调用infer=True ADD-only，与旧after_turn用户/最终助手路径区分。
SimpleMem沿原始文本writer/LanceDB/Tantivy/planning/reflection路径；两项原生并行开关关闭。
原生维护状态、原生检索、共同reader结果、原事件ID保留、输入wire与成本分别报告。
SimpleMem的单owner物理资源拒绝与Mem0共享原生库user过滤不能混称同一隔离机制。

失败成本用例在一次已付费形成后，声明第二次archive生成容量0；容量拒绝不是远端故障。
后续新进程snapshot必须如实保留原生状态及可能的局部写入。固定所有失败、未知和not-run分母。

本轮仅使用既有Qwen与bge服务及现有固定SDK环境，不改变服务或下载依赖。
bge上下文8192是实际配置元数据；当前bridge没有plain-tokenizer容量检查。微型输入小且
全部真实embedding用量计账，这不支持任意输入容量保证。Store I/O与完整冷启动仍分开限定，
不把资源文件大小或局部snapshot计时称为全生命周期I/O实测，也不换算美元/GPU小时。

尚未运行B0–B6、最近邻或pilot/formal；两外部臂微型通过也不代表完整P3完成。

运行器MockHTTP/编排17项通过，Ruff、strict mypy和canonical matrix通过；两CI职责同步。
最终冻结包含199个Lab Python源文件和薄CLI，共200文件；两个解释器prepare均0HTTP，
读取SDK实际身份且源文件集合相同。实时models GET核对7860/7861后原账本仍6337调用，
准备检查未增加generation/embedding。首个失败与全部构建记录哈希保存在协议，真实运行尚未开始。
