# v13.1 P3 外部基线微型检查

状态：ENGINEERING_SCOPE_CONFIRMED / BEHAVIORAL_PARTIAL；完整P0–P8仍ACTIVE，Product NO_GO。

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

## 实际结果与保留失败

[结果manifest](../data/manifests/v13-1-p3-baseline-micro-results.json)记录离线逐项审查、
原始trace/terminal/process记录哈希和逐响应费用核对。没有模型Judge或substring自动判分。

| 检查 | Mem0（缓存环境修正后） | SimpleMem-Text |
|---|---|---|
| 存储→独立进程重启→检索 | PASS_SCOPED；原生ID/数据一致 | PASS_SCOPED；原生ID/数据一致 |
| 偏好变更 | PASS_SCOPED；当前茶/历史咖啡 | PASS_SCOPED；当前茶/历史咖啡 |
| 相对日期 | PASS_SCOPED；Friday绝对日期未定 | PASS_SCOPED；Friday绝对日期未定 |
| 工具角色/ID/局部结果 | 完整writer wire；reader局部结果区分失败 | 完整writer wire；reader局部结果区分失败 |
| owner隔离 | 原生user_id过滤为空，原owner继续正确 | 物理owner拒绝，原owner继续正确 |
| 失败后的成本与持久状态 | 诚实MAINTENANCE_INCOMPLETE；旧状态一致 | 诚实INCOMPLETE；旧状态一致 |

首次Mem0初始化使用默认临时缓存，离线BM25缺文件，返回MEM0_BM25_NOT_ACTIVE。
该次0generation/0embedding；实际首个错误与初始22步骤分母保留，剩21步骤NOT_RUN。
找到并核对既有专用缓存40文件，offline编码非空后，新命名空间只增加Root launch
FASTEMBED_CACHE_PATH/HF_HUB_OFFLINE环境记录，SDK/源代码/原输入/reader均不改。
缓存修正单独冻结，不覆盖首次失败，不退回dense-only，也不下载/升级依赖。
环境元数据由Root命令设置；原生runtime trace证明实际cache路径，运行器不代设这些键。

修正后两臂各22实际步骤，总44步骤全部留下terminal；另外初始失败1步骤，总45不同PID。
初始44+纠正Mem022=66声明步骤槽，累计45实际执行/21原初始NOT_RUN；不能报告初始100%覆盖。
两臂当前各5/6案例PASS_SCOPED，回执表达1/6未通过，不宣称完整行为微型通过。

全部14个成功archive的实际HTTP writer输入含完整原行与真实工具body，未含随后reader问题。
两臂形成记录均未保留原SourceEvent ID（0）；预约业务ID与原生entry ID是不同身份。
Mem0把工具事实归为assistant并压成“reservation and label request failed”；SimpleMem保留
工具来源叙述和reserved_label_failed，但也写成联合操作failed。两臂reader都保留正确预约ID
和not_created，却没有清楚说明“预约已创建、标签失败”，不满足局部结果区分。
联合请求失败可能是真实描述，因此这类歧义不强行记作确定的世界错误；遗漏关键局部结果仍失败。
这些trace只能定位到形成/交付/消费链，不能凭一次载体认定全部差异是算法固有缺陷。

容量0拒绝后，Mem0有1次生成admission拒绝，仍先支付248 embedding tokens；SimpleMem有9次
有限原生admission拒绝、0HTTP。两组新进程s2均与原有形成状态逐字段一致。预定拒绝的
scenario检查通过不表示第二次记忆形成完成，更不是远端故障/三个崩溃窗口验收。

| 成本 | generation calls | generation tokens | embedding tokens |
|---|---:|---:|---:|
| 初次Mem0 setup失败 | 0 | 0 | 0 |
| Mem0缓存修正6类 | 13 | 63474 | 3032 |
| SimpleMem6类 | 35 | 24540 | 868 |
| 本轮合计 | 48 | 88014 | 3900 |

53实际embedding请求；全部generation/embedding usage逐terminal核对连续账本，unknown0。
连续累计6385generation /11783316 generation tokens /420830 embedding tokens，SHA256
b00501550dc14c4626223771f208a6a10b3ce0295f1126b9888801085d58b887；Judge0。
v13.1自原起点合计240generation/376230tokens/3900embedding。

## 下一最小区分实验

观察：工具wire完整，实际bank含正确业务ID与not_created，两reader却概括联合失败。
最早可直接定位的断点：Mem0形成事实已模糊且错归role；SimpleMem字段仍在，消费没有清楚区分。
仍支持的竞争解释：公共reader未获得reserved_label_failed的明确公开合同；压缩后的“failed”
表达主导消费。公开合同行为可由world/tool源码核对，不能由rubric或标准答案补给Host。

最小实验是固定各臂这次实际交付material，比共同原prompt与只补公共两阶段状态含义的prompt。
输入material、问题、模型/temp0、输出4096、调用计费不变；无重新形成/重启补造成功记录。
每臂每条件1调用，总4次，容量与原账本计费；首轮输出与全部失败保留。
若明确公共合同仍不改善，不能称“已修复”或只重试取最好结果；若改善只属通用提示消费解释，
不是候选guard或结构记忆收益。此诊断仍不补原SourceEvent ID，B0–B6/最近邻/P4–P8继续待执行。

## 固定material的公共合同诊断结果

[配对协议](../data/manifests/v13-1-p3-partial-contract-protocol.json)冻结实际q1交付material与
两个共同prompt；[逐leg结果](../data/manifests/v13-1-p3-partial-contract-results.json)保留4次输出。
原micro形成/检索不重跑；控制与候选每臂material hash完全相同，候选只补公开两阶段合同。

两个控制仍明确把“预订结果”说成失败。两个候选都正确说明历史预约已创建、标签未创建，
原真实业务ID不变。SimpleMem候选该有限consumer检查通过。Mem0候选另外写出一段不存在于
native memory80986163的引文，并把公共prompt中的“reservation was created but the label attempt
failed”归给该真实记忆。因此其业务字段正确、来源归因失败，overall仍失败。

公共合同可以改变消费解释，但真实记忆ID不证明引文受原内容支持。此轮不能声称guard、
类型或整体准确率独立增益；不能替换原micro5/6结论或把原Source ID补入native bank。
语义引文/自由prose仍未经受限字段guard验证。后续P2只保证公开两字段与实际观察一致。

本诊断4generation/4496tokens/0embedding，Judge0；每次1调用、无重试，全usage与原连续
账本匹配。最新6389generation/11787812generation tokens/420830embedding，unknown0；
账本SHA256566214e33f79cccceec3c30c8b2a2c7f8fe830ea3223685b41cd63593ace0d23。
