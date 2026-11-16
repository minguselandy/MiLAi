# A100 冻结确认256来源族：实际操作、Source交付与推理成本

四方法各256个原生首结果的操作轨迹、Source与实际Provider输入均完成只读普查。
主seed没有取得完整成功率优势的区间证据，并使用更多Host tokens和本地计算：
Host已知总tokens为2,214,052，基线为1,985,393；完整推理子进程加已测父CPU为
2635.303秒，基线为816.987秒。完整项目的准备、训练、筛选和外部实验成本仍需另汇总。
这些固定拟合结果不支持按最好seed或某个材料子组选择采用结论。

## 成本范围与测量

| 方法 | 实际HTTP响应 | 已知Host总tokens | 实际NN次数 / 输入tokens | 完整子CPU＋已测父CPU秒 | 各原生owner wall之和秒 |
|---|---:|---:|---:|---:|---:|
| Fixed prefix | 590 | 1,985,393 | 0 / 0 | 816.987 | 7298.32 |
| E3 seed0（主） | 591 | 2,214,052 | 2036 / 12,747,290 | 2635.303 | 7687.71 |
| E3 seed1 | 565 | 2,136,058 | 1959 / 12,353,161 | 2546.707 | 7645.41 |
| E3 seed2 | 616 | 2,187,880 | 1971 / 11,790,893 | 2398.157 | 8258.28 |

失败首结果全部保留并计成本。HTTP次数从原生响应与usage逐项对齐，已知tokens与
已付owner回执一致；本批没有新增generation/embedding未知用量。原生结果中的
`generation_calls`字段包含本地控制调用，不能直接充当HTTP次数。

每个owner完整子进程CPU已包含模型加载、NN、复制和其余客户端工作，父进程记录到
实际计量时为止；不再将native NN/load或残差重复叠加。NN返回内CPU计时、原生模型
compute phase和完整owner计时各有边界，分别保留，不强行互换。未单独计量的作者、
启动、检查及清理开销为unknown，不是零。分析/绘图CPU按各自计时在原账本下一合格
空闲窗口一次计入，不回写或重复计量任何旧调用。

三学习方法GPU2占用的实际job区间分别为2.1355、2.1237、2.2940小时，其中含HTTP
等待、加载和IO；它不是CUDA kernel忙碌小时。固定基线没有本地NN。Host GPU0/1
的计算时间未在这些回执内测量。基线由已冻结8＋248两段组成，wall为两段实际和，
不同时间段的服务状态未受控，不能据此宣称纯GPU加速比或单一机制的因果延迟效应。

## 完整操作绑定与执行结果

| 方法 | SEARCH选择 | READ选择 | READ opened | READ材料预算拒绝 | READ observed / Source页面 | HANDOFF选择 / delivery_selected |
|---|---:|---:|---:|---:|---:|---:|
| Fixed prefix | 625 | 1012 | 1012 | 0 | 0 / 0 | 253 / 0 |
| E3 seed0（主） | 343 | 1675 | 1572 | 96 | 6 / 1 | 18 / 11 |
| E3 seed1 | 381 | 1561 | 1435 | 56 | 70 / 0 | 17 / 5 |
| E3 seed2 | 548 | 1260 | 1177 | 16 | 51 / 16 | 163 / 87 |

所有选中动作的完整id、kind、target与parameters均绑定原生trace位置及对应返回。
READ选择、成功打开、观察/分页、材料预算拒绝和实际交付是不同计数。HANDOFF无参数
可直接结束控制循环，不生成operation_result；带材料参数的HANDOFF执行后才记录
delivery_selected。只看选择数会混淆这两种行为。每个有原生检索结果事件的调用，
operations和read_operations均与其实际operation_result逐条相符。

基线/三seed的原生终止原因为policy_handoff的次数分别253/18/17/163，
budget_exhausted为87/317/293/203。预算耗尽不自动意味着任务失败或材料不足；
这些事件与C/I/W/F/U及材料S/P/I独立列示，不重写任务质量，也不按结局修补动作。

## Source与实际收到材料

四方法共享相同256来源族，每组初始原始Source为18,932条、8,491,230字符。
本普查逐条比较原生Source的完整正文、role与origin；完整Source值/时钟、Store/Saver、
世界/应用不变与NN完整投影另有已通过的全量机械审计。来源条数和多个seed不扩充
独立来源族数，完整输入/菜单不等于全部Source已送达Host或16k有效上下文。

| 方法 | 实际收到的Tool消息 | 原生检索结果事件 | 已绑定原文范围 | 完整原文块范围 | 收到原文字符量（含重复） | 作者审阅材料S |
|---|---:|---:|---:|---:|---:|---:|
| Fixed prefix | 343 | 340 | 1012 | 902 | 713,599 | 150/256 |
| E3 seed0（主） | 341 | 335 | 1513 | 1348 | 1,074,084 | 149/256 |
| E3 seed1 | 313 | 310 | 1388 | 1215 | 1,014,573 | 139/256 |
| E3 seed2 | 369 | 366 | 962 | 868 | 708,653 | 103/256 |

原文范围、完整块及字符量统计completed-final或failed-last的实际输入Tool receipts；
完整provider消息另保留初始上下文及历史材料，故这些范围数不是全部初始/历史可见量。
同一原文可能被多次送达，字符量含重复，不能充当不同事实数或唯一Source覆盖率。
本批范围均无歧义地匹配原始Source身份，没有合并内容相同但身份不同的Source。
这些receipts中的材料kind全部为original_source，没有Source-View材料；这不等于证明
历史或其他实验从未使用View，也不建立缓存或增量机制的泛化优势。

另外遍历每个实际响应过的Provider请求，按原生tool_call_id保留不同Tool消息。
其中与milai_retrieve_result事件共有的packet逐完整dict相同，所有有该事件的返回
都至少出现在一个响应过的Provider输入中。对未获得响应的请求，此并集可能不完整，
不能仅凭它推断请求未发送。

## 15条没有对应检索结果事件的Tool消息

| 方法 | schema enum拒绝，工具未执行 | read_limit_exhausted，未进控制循环 |
|---|---:|---:|
| Fixed prefix | 3 | 0 |
| E3 seed0（主） | 1 | 5 |
| E3 seed1 | 0 | 3 |
| E3 seed2 | 1 | 2 |

所有15条均已按原始实际wire packet单独阅读与绑定：5条为read_goal.evidence枚举
校验错误，工具未执行；10条为空evidence的读取额度拒绝，其control_steps、operations
和read_operations均为零。这些在进入控制循环前返回的消息没有milai_retrieve_result
事件，仍属于实际收到的Tool消息和原生错误，完整保留其Host后续行为与最终首结果。
它们不是丢失的成功检索，不能补造READ或重跑调用。原生读取准入与内部READ动作数
沿各自实现计数，不能混为同一预算单位。

## 复核与限制

作者审阅质量与区间见[完整质量结果](MILAI_A100_CONFIRMATION256_RESULTS_20261107.md)。
本普查没有独立复评作者标签，不以材料充分或READ增加推断因果质量收益。
指南与Source曝光、非盲审/非独立、固定122敏感性及原生DEV185/TRAIN71限制保持。
完整外部LME/Mem2Act、全项目成本、最终论文与原763行目标尚未完成。

- [紧凑结果及全部15条错误原文](../data/manifests/a100-confirmation256-operations-cost-20261107-v1.json)
- [原生普查分析代码](../tools/analyze_a100_confirmation256_operations_cost.py)

完整逐项动作、用量、Source身份与trace位置保存在ignored artifacts的
`final-confirmation-v1/operations-source-delivery-inference-cost-all4-v1.json`。
代码只读已关闭的256×4原生文件，接收输入artifact目录及一个尚不存在的新输出：

```bash
python3 tools/analyze_a100_confirmation256_operations_cost.py \
  artifacts/a100-development-20261104/final-confirmation-v1 \
  artifacts/a100-development-20261104/final-confirmation-v1/operations-source-delivery-inference-cost-all4-reproduction-v1.json
```

全过程无新模型/HTTP、业务写入、账本读写或SHA校验。初次只读schema检查将路径误作
dict的失败和原计时仍在，并以直接读取既有原生路径修正，没有新增容错或重试框架。
