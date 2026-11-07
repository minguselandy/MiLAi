# 旧64保留query：元数据资格与评测边界（协议待定）

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
