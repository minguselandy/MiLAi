# 旧64保留query：原生条件合同冻结，完整输入已核验，模型尚未启动

已先冻结三套既定模型、代码与评分，再投影保留语义。模型为原开发阶段已选定的
初始E1/update16、A0/update2104和A1/update2104，主比较A1−A0；不重新选择模型，
不追加拟合、seeds或A→B。7个新代码绑定继承1135个既有绑定；18个权重文件共
2,034,760,045字节复制后逐字节相同，未用SHA/内容指纹。

64组、127条原始行生成4333个原生条件×候选格，其中4066个known、267个unjudged。
127条原始行的完整UTF-8行字节与源文件相同；全部状态/问题、原文title/text、用途、
原生标签与unknown掩码复算一致。4333格全部进入每个模型的公共预测输入，监督
known-only文件不用于删减预测。公共payload只有原始state/questions，没有标签、
membership或native docid。原始参考矩阵与条件对单独离线保存。

原生条件对为1884 stable、267 unknown、0 change；变化联合准确率不可用，不能
填零、补标签或声称已经测到条件翻转泛化。固定64组均有正负原生标签，原A的
family macro balanced accuracy定义成立；20,000次seed0配对query家族bootstrap
只刻画固定语料/拟合/原生标签下的条件差异，不代表64个独立文档历史。

既有8744个DEV128初始模型保存输出已用来核对新失败感知pair评分：完整输出时
全部原生字段逐项相同，无新NN。一次导入缺少langchain_core的CPU检查失败已保留，
使用原有CUDA侧Transformers4.52.3/Tokenizer0.21.4先导入、再追加HTTP依赖的方式修正。
没有升级依赖或增加通用fallback。原生弱负例与unknown mask限制保持。

三模型计划已登记，实际预测仍为0。准入检查确认唯一LME006父2889923仍存活，
所以没有启动第二个模型worker；实际进程退出、完整成本结算和共享锁通过后，
才能逐个显式启动。NN采用原生完整输入guard、GPU2/cuda0、FP32、四线程，
MHAfastpath/reference_compile/TF32关闭。每模型全量审计后才进入下一模型，三者
全部首结果关闭后才离线计分；失败保留，不以重跑或裁输入提高通过率。

[完整准备与冻结记录](../data/manifests/a100-reserved64-native-protocol-preparation-20261107-v1.json)
和[六个入口源码](../tools/reserved64/README.md)已保存。该次级条件指标不是自主Host
任务C、FollowIR p-MRR/检索排名或独立事实性真值，不增加256论文确认的分母。
保留语义现已按冻结合同投影；原生TEST语义保持未打开。

## 历史元数据资格记录（语义投影前）

64个保留query家族的完整元数据已与原分配逐dict相同：原生split均为dev，
allocation_basis均为new_query_family，prior_rows及prior_anchor_groups均为零。
它们包含127条原生新行，与本轮另选的128个DEVELOPMENT query家族无交集。
这些结论来自已有的ID/行位置元数据，没有投影保留query、正文或标签语义。

这64组属于共享文档语料上的条件相关性协议。它们不是64个新文档或独立Source历史，
也不是256论文来源族的自主Host确认或LME/Mem2Act外部任务。不得将64加到256分母，
把原生dev改写成新Source确认，或把无先前anchor理解为模型从未见过文档/网页。
既有非穷尽公开例子ID记录交集为零，也不能证明预训练或全部历史暴露隔离。

当前只关闭了元数据成员资格核验，尚未准入实际模型评测。下一步需在打开保留语义前，
明确固定saved模型、原生完整输入、条件标签/unknown mask与独立评分合同；条件能力
的次级问题必须与已冻结的自主Host主比较分列。不能直接用fixed-prefix动作策略充当
二元条件判断基线，也不能把原生弱负例视作独立人工事实性真值。原A/B未满足扩量
门槛的结论保持，不触发20k/B192/J、新拟合或最好seed选择。

[完整64组元数据与核验记录](../data/manifests/a100-reserved64-query-metadata-qualification-20261107-v1.json)
保存原始分配/保留/曝光/协议路径和完整成员记录。保留query语义和原生TEST仍未打开，
新的评测协议及任何符合范围的实际执行仍属完整目标的未完成工作。

本核验没有模型/HTTP、账本读写或SHA校验；CPU/wall原计时待下一真实空闲窗口计量。
